"""Gemini-parse the non-ordinance Companies Act PDFs and assemble the viewer JSON.

PDF splitting is mechanical only. Every legal word and structural field written to
the generated JSON is extracted by a Gemini multimodal model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter

try:
    from scripts.pdftojson import merge_bare_act_history
except ModuleNotFoundError:  # Support direct execution: python scripts/<file>.py
    from pdftojson import merge_bare_act_history


ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
AI_OUTPUT_DIR = DOCS_DIR / "ai_parsed_documents"
MASTER_PATH = DOCS_DIR / "sections_master.json"
FRONTEND_MASTER_PATH = ROOT / "frontend" / "public" / "docs" / "sections_master.json"
MODEL = os.getenv("GEMINI_PDF_MODEL", "gemini-2.5-flash-lite")
BATCH_PAGES = int(os.getenv("GEMINI_PDF_BATCH_PAGES", "20"))
OVERLAP_PAGES = int(os.getenv("GEMINI_PDF_OVERLAP_PAGES", "2"))

DOCUMENTS = {
    "Companies_Act_2013_Current.pdf": "current_act",
    "Companies_Act_2013_Bare.pdf": "bare_act",
    "Companies_Amendment_2015.pdf": "amendment",
    "Companies_Amendment_2017.pdf": "amendment",
    "Companies_Amendment_2019.pdf": "amendment",
    "Companies_Amendment_2020.pdf": "amendment",
}


class AmendmentNote(BaseModel):
    footnote_ref: str = ""
    note: str


class Clause(BaseModel):
    clause_number: str
    text: str


class Subsection(BaseModel):
    subsection_number: str = Field(description="For example (1), (2A), or N/A.")
    text: str
    status: Literal["active", "amended", "omitted", "substituted"] = "active"
    clauses: list[Clause] = Field(default_factory=list)
    amendments: list[AmendmentNote] = Field(default_factory=list)


class Section(BaseModel):
    section_number: str = Field(description="Only the number and suffix, for example 10A.")
    title: str = Field(description="Section title without the leading section number.")
    status: Literal["active", "amended", "omitted", "substituted"] = "active"
    subsections: list[Subsection] = Field(default_factory=list)
    amendments: list[AmendmentNote] = Field(default_factory=list)


class Chapter(BaseModel):
    chapter_number: str = Field(description="For example CHAPTER III.")
    chapter_title: str
    sections: list[Section] = Field(default_factory=list)


class ParsedActChunk(BaseModel):
    act_title: str
    doc_type: Literal["current_act", "bare_act"]
    chapters: list[Chapter]


class AmendmentOperation(BaseModel):
    principal_section: str
    operation: Literal["inserted", "omitted", "substituted", "amended"]
    target: str
    enacted_text: str
    source_excerpt: str
    effective_date: str
    page_reference: str


class ParsedAmendment(BaseModel):
    document_title: str
    act_number: str
    publication_date: str
    amendments: list[AmendmentOperation]


ACT_SYSTEM_PROMPT = """You are transcribing Indian legislation into structured JSON.
Read the supplied PDF page images and embedded text. Extract only substantive provisions of the
Companies Act, 2013: chapters, sections, subsections, clauses, and amendment footnotes. Ignore the
table of contents, page furniture, publisher commentary, and indexes. Preserve legal wording,
numbering, capitalization, brackets, punctuation, provisos, explanations, and amendment notes.
Never summarize or invent text. A section title must not repeat its section number. Use N/A only
when a section truly has no numbered subsection. A page may begin or end in the middle of a
provision; extract every visible fragment and assign it to its visible section/subsection. Overlap
with adjacent batches is intentional and will be deduplicated."""

AMENDMENT_SYSTEM_PROMPT = """You are extracting an Indian Companies Act amendment into JSON.
Read every page image and all embedded text. Extract every operation that changes the Companies
Act, 2013. Preserve exact legal wording, numbering, punctuation, effective dates, and page
references. Do not summarize replacement wording or infer anything not stated in the PDF. A
principal section contains only its number and optional letter suffix, such as 10A or 441."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stem(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem)


def split_pdf(pdf_path: Path, destination: Path) -> list[tuple[Path, int, int]]:
    """Split by page only; this function never extracts or interprets PDF text."""
    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    stride = BATCH_PAGES - OVERLAP_PAGES
    if stride < 1:
        raise ValueError("GEMINI_PDF_BATCH_PAGES must exceed GEMINI_PDF_OVERLAP_PAGES")

    chunks = []
    start = 0
    while start < page_count:
        end = min(start + BATCH_PAGES, page_count)
        writer = PdfWriter()
        for page_number in range(start, end):
            writer.add_page(reader.pages[page_number])
        chunk_path = destination / f"pages-{start + 1:04d}-{end:04d}.pdf"
        with chunk_path.open("wb") as stream:
            writer.write(stream)
        chunks.append((chunk_path, start + 1, end))
        if end == page_count:
            break
        start += stride
    return chunks


def _parse_response(client, pdf_path: Path, prompt: str, schema, system_prompt: str):
    from google.genai import types

    pdf_part = types.Part.from_bytes(
        data=pdf_path.read_bytes(),
        mime_type="application/pdf",
    )
    last_error = None
    for attempt in range(1, 6):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=[pdf_part, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=65536,
                ),
            )
            if not response.text:
                raise RuntimeError(f"Gemini returned no structured output for {pdf_path.name}")
            return schema.model_validate_json(response.text)
        except Exception as error:
            last_error = error
            if attempt == 5:
                break
            delay = min(2**attempt, 30)
            print(
                f"Gemini request attempt {attempt} failed; retrying in {delay}s: {error}",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"Gemini failed to parse {pdf_path.name}") from last_error


def parse_act(client, pdf_path: Path, doc_type: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="companies-act-ai-") as temp_dir:
        chunks = split_pdf(pdf_path, Path(temp_dir))
        parsed_chunks = []
        carry_chapter = "not yet established"
        carry_section = "not yet established"
        for index, (chunk_path, page_start, page_end) in enumerate(chunks, start=1):
            print(
                f"AI parsing {pdf_path.name}: batch {index}/{len(chunks)} "
                f"(source pages {page_start}-{page_end})",
                flush=True,
            )
            parsed = _parse_response(
                client,
                chunk_path,
                (
                    f"This is {doc_type} source pages {page_start}-{page_end}. Extract all visible "
                    "Companies Act provisions into the schema. Check every supplied page. "
                    f"The last chapter identified in the preceding batch was {carry_chapter}; "
                    f"the last section was {carry_section}. If these pages begin mid-provision "
                    "without repeating its headings, use that carry-over identity. A heading "
                    "visible in this batch always takes precedence."
                ),
                ParsedActChunk,
                ACT_SYSTEM_PROMPT,
            )
            parsed.doc_type = doc_type
            parsed_chunk = parsed.model_dump(mode="json")
            parsed_chunks.append(parsed_chunk)
            for chapter in parsed_chunk.get("chapters", []):
                if chapter.get("chapter_number") not in {"", "N/A"}:
                    carry_chapter = (
                        f"{chapter['chapter_number']} ({chapter.get('chapter_title', '')})"
                    )
                if chapter.get("sections"):
                    last_section = chapter["sections"][-1]
                    carry_section = (
                        f"section {last_section.get('section_number', '')} "
                        f"({last_section.get('title', '')})"
                    )
    return merge_act_chunks(parsed_chunks, doc_type)


def parse_amendment(client, pdf_path: Path) -> dict:
    parsed = _parse_response(
        client,
        pdf_path,
        "Extract every amendment operation in this Act. Check every page, including schedules.",
        ParsedAmendment,
        AMENDMENT_SYSTEM_PROMPT,
    )
    validate_amendment(parsed, pdf_path)
    return parsed.model_dump(mode="json")


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def merge_legal_text(first: str, second: str) -> str:
    """Join overlapping AI fragments without dropping a page-boundary continuation."""
    first, second = _normalized(first), _normalized(second)
    if not first:
        return second
    if not second:
        return first
    if first in second:
        return second
    if second in first:
        return first

    first_words, second_words = first.split(), second.split()
    limit = min(len(first_words), len(second_words), 250)
    for overlap in range(limit, 2, -1):
        if first_words[-overlap:] == second_words[:overlap]:
            return " ".join(first_words + second_words[overlap:])
        if second_words[-overlap:] == first_words[:overlap]:
            return " ".join(second_words + first_words[overlap:])
    return f"{first} {second}"


def _merge_notes(target: list[dict], incoming: list[dict]) -> None:
    seen = {(item.get("footnote_ref", ""), _normalized(item.get("note", ""))) for item in target}
    for note in incoming:
        key = (note.get("footnote_ref", ""), _normalized(note.get("note", "")))
        if key not in seen:
            target.append(note)
            seen.add(key)


def _merge_clauses(target: list[dict], incoming: list[dict]) -> None:
    by_number = {item.get("clause_number", "").upper(): item for item in target}
    for clause in incoming:
        key = clause.get("clause_number", "").upper()
        if key in by_number:
            by_number[key]["text"] = merge_legal_text(by_number[key].get("text", ""), clause.get("text", ""))
        else:
            target.append(clause)
            by_number[key] = clause


def _merge_subsections(target: list[dict], incoming: list[dict]) -> None:
    by_number = {item.get("subsection_number", "").upper(): item for item in target}
    for subsection in incoming:
        key = subsection.get("subsection_number", "").upper()
        existing = by_number.get(key)
        if existing is None:
            target.append(subsection)
            by_number[key] = subsection
            continue
        existing["text"] = merge_legal_text(existing.get("text", ""), subsection.get("text", ""))
        _merge_clauses(existing.setdefault("clauses", []), subsection.get("clauses", []))
        _merge_notes(existing.setdefault("amendments", []), subsection.get("amendments", []))
        if existing.get("status") == "active" and subsection.get("status") != "active":
            existing["status"] = subsection["status"]


def _merge_sections(target: list[dict], incoming: list[dict]) -> None:
    by_number = {str(item.get("section_number", "")).upper(): item for item in target}
    for section in incoming:
        key = str(section.get("section_number", "")).upper()
        existing = by_number.get(key)
        if existing is None:
            target.append(section)
            by_number[key] = section
            continue
        if len(section.get("title", "")) > len(existing.get("title", "")):
            existing["title"] = section["title"]
        _merge_subsections(existing.setdefault("subsections", []), section.get("subsections", []))
        _merge_notes(existing.setdefault("amendments", []), section.get("amendments", []))
        if existing.get("status") == "active" and section.get("status") != "active":
            existing["status"] = section["status"]


def merge_act_chunks(chunks: list[dict], doc_type: str) -> dict:
    merged = {"act_title": "THE COMPANIES ACT, 2013", "doc_type": doc_type, "chapters": []}
    chapters_by_number = {}
    for chunk in chunks:
        if chunk.get("act_title"):
            merged["act_title"] = chunk["act_title"]
        for chapter in chunk.get("chapters", []):
            key = chapter.get("chapter_number", "").strip().upper()
            if key in {"", "N/A"}:
                continue
            existing = chapters_by_number.get(key)
            if existing is None:
                merged["chapters"].append(chapter)
                chapters_by_number[key] = chapter
                continue
            if len(chapter.get("chapter_title", "")) > len(existing.get("chapter_title", "")):
                existing["chapter_title"] = chapter["chapter_title"]
            _merge_sections(existing.setdefault("sections", []), chapter.get("sections", []))
    normalize_section_titles(merged)
    validate_act(merged, doc_type)
    return merged


def normalize_section_titles(document: dict) -> None:
    for chapter in document.get("chapters", []):
        for section in chapter.get("sections", []):
            number = str(section.get("section_number", "")).strip()
            section["title"] = re.sub(
                rf"^(?:section\s+)?{re.escape(number)}[.:-]?\s*",
                "",
                str(section.get("title", "")),
                count=1,
                flags=re.IGNORECASE,
            )


def validate_act(document: dict, doc_type: str) -> None:
    chapters = document.get("chapters", [])
    sections = [section for chapter in chapters for section in chapter.get("sections", [])]
    if len(chapters) < 20:
        raise ValueError(f"{doc_type} has only {len(chapters)} chapters")
    if len(sections) < 400:
        raise ValueError(f"{doc_type} has only {len(sections)} sections")
    invalid = [s.get("section_number") for s in sections if not re.fullmatch(r"\d+[A-Z]*", str(s.get("section_number", "")), re.IGNORECASE)]
    if invalid:
        raise ValueError(f"{doc_type} contains invalid section numbers: {invalid[:10]}")
    duplicates = []
    seen = set()
    for section in sections:
        key = str(section["section_number"]).upper()
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        raise ValueError(f"{doc_type} contains duplicate sections: {duplicates[:10]}")


def validate_amendment(document: ParsedAmendment, source: Path) -> None:
    if not document.amendments:
        raise ValueError(f"No amendments extracted from {source.name}")
    for amendment in document.amendments:
        if not re.fullmatch(r"\d+[A-Z]*", amendment.principal_section, re.IGNORECASE):
            raise ValueError(f"Invalid principal section {amendment.principal_section!r}")
        if amendment.operation != "omitted" and not (amendment.enacted_text or amendment.source_excerpt):
            raise ValueError(f"Missing legal wording for section {amendment.principal_section}")


def amendment_source_map(parsed_amendments: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for document in parsed_amendments:
        title = document.get("document_title", "Companies Amendment Act")
        for amendment in document.get("amendments", []):
            page = f", {amendment['page_reference']}" if amendment.get("page_reference") else ""
            target = f" {amendment['target']}" if amendment.get("target") else ""
            note = (
                f"{title}: {amendment['operation']}{target} "
                f"(section {amendment['principal_section']}{page})"
            )
            result.setdefault(amendment["principal_section"].upper(), []).append(note)
    return result


def write_source_output(source: Path, kind: str, parsed: dict, output_path: Path) -> None:
    payload = {
        "filename": source.name,
        "sha256": sha256_file(source),
        "kind": kind,
        "model": MODEL,
        "parsed": parsed,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def assemble(input_dir: Path) -> None:
    files = sorted(input_dir.glob("*.json"))
    if len(files) != len(DOCUMENTS):
        raise ValueError(f"Expected {len(DOCUMENTS)} AI outputs in {input_dir}, found {len(files)}")
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    by_kind = {}
    amendments = []
    for payload in payloads:
        if payload["kind"] == "amendment":
            amendments.append(payload["parsed"])
        else:
            by_kind[payload["kind"]] = payload["parsed"]
    if set(by_kind) != {"current_act", "bare_act"}:
        raise ValueError("Both current_act and bare_act AI outputs are required")

    master = merge_bare_act_history(
        by_kind["current_act"], by_kind["bare_act"], amendment_source_map(amendments)
    )
    normalize_section_titles(master)
    master["ai_parse_metadata"] = {
        "provider": "Google Gemini",
        "model": MODEL,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "documents": [
            {"filename": item["filename"], "sha256": item["sha256"], "kind": item["kind"]}
            for item in payloads
        ],
        "excluded": ["docs/ordinances/*.pdf"],
    }
    serialized = json.dumps(master, indent=2, ensure_ascii=False) + "\n"
    MASTER_PATH.write_text(serialized, encoding="utf-8")
    FRONTEND_MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_MASTER_PATH.write_text(serialized, encoding="utf-8")

    AI_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in files:
        destination = AI_OUTPUT_DIR / path.name
        destination.write_bytes(path.read_bytes())
    print(f"Assembled {len(payloads)} AI-parsed documents into {MASTER_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assemble-dir", type=Path)
    args = parser.parse_args()

    if args.assemble_dir:
        assemble(args.assemble_dir)
        return
    if not args.source or not args.output:
        parser.error("use --source and --output, or --assemble-dir")
    source = args.source.resolve()
    kind = DOCUMENTS.get(source.name)
    if kind is None:
        raise ValueError(f"Unsupported source {source.name}; ordinances are intentionally excluded")

    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    client = genai.Client(api_key=api_key)
    parsed = parse_amendment(client, source) if kind == "amendment" else parse_act(client, source, kind)
    write_source_output(source, kind, parsed, args.output)
    print(f"Wrote AI-parsed {kind} JSON to {args.output}")


if __name__ == "__main__":
    main()
