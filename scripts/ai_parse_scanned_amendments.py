"""Parse scanned Companies Act amendment PDFs with OpenAI PDF vision.

The script intentionally fails closed: it never substitutes local OCR when an AI
response is missing or invalid, and it writes output only after every scanned
document has been parsed successfully.
"""

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent
ORDINANCE_DIR = ROOT / "docs" / "ordinances"
AI_OUTPUT_DIR = ROOT / "docs" / "ai_parsed_amendments"
MASTER_PATH = ROOT / "docs" / "sections_master.json"
FRONTEND_MASTER_PATH = ROOT / "frontend" / "public" / "docs" / "sections_master.json"
MODEL = os.getenv("OPENAI_PDF_MODEL", "gpt-5.6")


class AmendmentOperation(BaseModel):
    principal_section: str = Field(
        description="Companies Act, 2013 principal section number, for example 12 or 76A."
    )
    operation: Literal["inserted", "omitted", "substituted", "amended"]
    target: str = Field(
        description="Exact subsection, clause, proviso, explanation, words, or provision affected."
    )
    enacted_text: str = Field(
        description="Exact replacement or inserted legal wording; empty for a pure omission."
    )
    source_excerpt: str = Field(
        description="Short exact ordinance wording that establishes this amendment."
    )
    effective_date: str = Field(
        description="Effective date printed in the document, or empty when not stated."
    )
    page_reference: str = Field(
        description="Printed page number, or PDF page number when no printed number is visible."
    )


class ParsedOrdinance(BaseModel):
    document_title: str
    ordinance_number: str
    publication_date: str
    amendments: list[AmendmentOperation]


SYSTEM_INSTRUCTIONS = """You are extracting Indian corporate legislation from a scanned PDF.
Read both the page images and any extracted text. Transcribe conservatively and preserve the exact
legal meaning, numbering, capitalization, brackets, and punctuation. Extract every operation that
changes the Companies Act, 2013. Do not infer an amendment that is not visible in the document.
Do not summarize replacement wording. If a field is not stated, return an empty string. A section
number must contain only its number and optional letter suffix, such as 10A or 441."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_parsed_document(document: ParsedOrdinance, source: Path) -> None:
    if not document.amendments:
        raise ValueError(f"No amendments were extracted from {source.name}")
    for amendment in document.amendments:
        if not re.fullmatch(r"\d+[A-Z]?", amendment.principal_section.strip(), re.IGNORECASE):
            raise ValueError(
                f"Invalid principal section {amendment.principal_section!r} in {source.name}"
            )
        if amendment.operation in {"inserted", "substituted", "amended"} and not (
            amendment.enacted_text or amendment.source_excerpt
        ):
            raise ValueError(
                f"Missing legal wording for section {amendment.principal_section} in {source.name}"
            )


def parse_pdf(client: OpenAI, pdf_path: Path) -> ParsedOrdinance:
    uploaded = client.files.create(file=pdf_path.open("rb"), purpose="user_data")
    try:
        response = client.responses.parse(
            model=MODEL,
            store=False,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": uploaded.id,
                            "detail": "high",
                        },
                        {
                            "type": "input_text",
                            "text": (
                                "Extract this ordinance into the required structured schema. "
                                "Check every page, including schedules and commencement notes."
                            ),
                        },
                    ],
                },
            ],
            text_format=ParsedOrdinance,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError(f"OpenAI returned no parsed output for {pdf_path.name}")
        validate_parsed_document(parsed, pdf_path)
        return parsed
    finally:
        client.files.delete(uploaded.id)


def source_note(document: ParsedOrdinance, amendment: AmendmentOperation) -> str:
    page = f", {amendment.page_reference}" if amendment.page_reference else ""
    target = f" {amendment.target}" if amendment.target else ""
    return (
        f"{document.document_title}: {amendment.operation}{target}"
        f" (section {amendment.principal_section}{page})"
    )


def normalize_section_titles(master: dict) -> None:
    for chapter in master.get("chapters", []):
        for section in chapter.get("sections", []):
            section_number = str(section.get("section_number", "")).strip()
            title = str(section.get("title", ""))
            section["title"] = re.sub(
                rf"^{re.escape(section_number)}\.\s*", "", title, count=1
            )


def merge_ai_sources(master: dict, parsed_documents: list[dict]) -> None:
    notes_by_section: dict[str, list[str]] = {}
    for item in parsed_documents:
        document = ParsedOrdinance.model_validate(item["parsed"])
        for amendment in document.amendments:
            notes_by_section.setdefault(amendment.principal_section.upper(), []).append(
                source_note(document, amendment)
            )

    unresolved = "Amendment source was not identified in the parsed footnotes."
    for chapter in master.get("chapters", []):
        for section in chapter.get("sections", []):
            section_number = str(section.get("section_number", "")).upper()
            notes = list(dict.fromkeys(notes_by_section.get(section_number, [])))
            if not notes:
                continue
            ai_note = "; ".join(notes)
            candidates = []
            if section.get("historical"):
                candidates.append(section)
            candidates.extend(section.get("historical_subsections", []))
            for subsection in section.get("subsections", []):
                candidates.extend(subsection.get("historical_clauses", []))
                candidates.extend(subsection.get("historical_versions", []))
            for candidate in candidates:
                if candidate.get("source_note") == unresolved:
                    candidate["source_note"] = ai_note


def write_outputs(parsed_documents: list[dict]) -> None:
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    normalize_section_titles(master)
    merge_ai_sources(master, parsed_documents)
    master["ai_parse_metadata"] = {
        "model": MODEL,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "documents": [
            {
                "filename": item["filename"],
                "sha256": item["sha256"],
                "output": item["output"],
            }
            for item in parsed_documents
        ],
    }
    serialized = json.dumps(master, indent=2, ensure_ascii=False) + "\n"
    MASTER_PATH.write_text(serialized, encoding="utf-8")
    FRONTEND_MASTER_PATH.write_text(serialized, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing AI outputs without calling OpenAI or rewriting the master JSON.",
    )
    args = parser.parse_args()

    pdf_paths = sorted(ORDINANCE_DIR.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"No scanned ordinance PDFs found in {ORDINANCE_DIR}")

    AI_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parsed_documents = []
    client = None if args.validate_only else OpenAI()

    for pdf_path in pdf_paths:
        output_path = AI_OUTPUT_DIR / f"{pdf_path.stem}.json"
        if args.validate_only:
            parsed = ParsedOrdinance.model_validate_json(output_path.read_text(encoding="utf-8"))
            validate_parsed_document(parsed, pdf_path)
        else:
            parsed = parse_pdf(client, pdf_path)
            output_path.write_text(
                parsed.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        parsed_documents.append(
            {
                "filename": pdf_path.name,
                "sha256": sha256_file(pdf_path),
                "output": str(output_path.relative_to(ROOT)),
                "parsed": parsed.model_dump(mode="json"),
            }
        )

    if not args.validate_only:
        write_outputs(parsed_documents)
        print(f"AI-parsed {len(parsed_documents)} scanned ordinance PDFs with {MODEL}.")
    else:
        print(f"Validated {len(parsed_documents)} existing AI ordinance outputs.")


if __name__ == "__main__":
    main()
