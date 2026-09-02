import json
import re
import shutil
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_DIR = SCRIPT_DIR.parent / "docs"


def extract_footnotes(raw_text: str) -> tuple[str, dict]:
    footnote_pattern = re.compile(r"^\s*(\d+)\.\s+(.*?(?:w\.e\.f\.|Act\s+\d+).*?)$", re.MULTILINE)
    footnotes = {}

    for match in footnote_pattern.finditer(raw_text):
        fn_num = match.group(1)
        fn_text = match.group(2).strip()
        footnotes[fn_num] = re.sub(r"\s+", " ", fn_text)

    clean_body = footnote_pattern.sub("", raw_text)
    return clean_body, footnotes


def sanitize_text(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"\b\d+\*+", "", text)
    text = re.sub(r"(\d+)\[", "[", text)

    lines = text.split("\n")
    cleaned = []
    for line in lines:
        line_str = line.strip()
        if line_str.isdigit() or re.match(r"^\d+\s+SECTIONS$", line_str, re.IGNORECASE):
            continue
        cleaned.append(line_str)

    joined = " ".join(cleaned)
    joined = re.sub(r"(\w+)-\s+(\w+)", r"\1\2", joined)
    return re.sub(r"\s+", " ", joined).strip()


def extract_raw_text(pdf_path: Path) -> str:
    # Keep parser-only tests usable without installing the optional OCR stack.
    import pdfplumber
    import pytesseract
    from pdf2image import convert_from_path

    raw_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < 30:
                try:
                    images = convert_from_path(str(pdf_path), first_page=i + 1, last_page=i + 1)
                    if images:
                        ocr_text = pytesseract.image_to_string(images[0])
                        raw_pages.append(ocr_text)
                except Exception as e:
                    print(f"  [OCR Error] Page {i+1} failed on {pdf_path.name}: {e}")
            else:
                raw_pages.append(page_text)
    return "\n".join(raw_pages)


def extract_clauses(text: str) -> list:
    if not text:
        return []

    clause_pattern = re.compile(
        r"(\([a-z]\)|\([i|v|x]+\))\s*(.*?)(?=\([a-z]\)|\([i|v|x]+\)|$)",
        re.DOTALL | re.IGNORECASE,
    )
    matches = clause_pattern.findall(text)

    clauses = []
    for clause_num, clause_text in matches:
        cleaned_text = sanitize_text(clause_text)
        cleaned_text = re.sub(r"\[$", "", cleaned_text).strip()

        if cleaned_text:
            clauses.append({"clause_number": clause_num.strip(), "text": cleaned_text})

    return clauses


def map_amendments(text: str, footnotes: dict) -> list:
    amendments = []
    for fn_num, fn_text in footnotes.items():
        if f"{fn_num}***" in text or f"{fn_num}[" in text or f"[{fn_num}" in text:
            amendments.append({"footnote_ref": fn_num, "note": fn_text})
    return amendments


def parse_subsections(section_body: str, footnotes: dict) -> list:
    clean_body = sanitize_text(section_body)

    num_subsec_pattern = re.compile(
        r"(?<!sub-section\s)(?<!sub-sections\s)(?<!section\s)(\(\d+[A-Z]?\))\s*(.*?)(?=(?<!sub-section\s)(?<!sub-sections\s)(?<!section\s)\(\d+[A-Z]?\)|$)",  # noqa: E501
        re.DOTALL | re.IGNORECASE,
    )
    matches = num_subsec_pattern.findall(clean_body)

    subsections = []
    if matches:
        for num, content in matches:
            text = content.strip()
            text_cleaned = re.sub(r"^\[|\]$", "", text).strip()

            status = "active"
            if "omitted" in text_cleaned.lower():
                status = "omitted"
            elif "substituted" in text_cleaned.lower() or "subs." in text_cleaned.lower():
                status = "substituted"

            amendments = map_amendments(content, footnotes)
            clauses = extract_clauses(text_cleaned)

            # Preserve preamble text instead of dropping subsection text completely
            if clauses:
                first_clause = clauses[0]["clause_number"]
                if first_clause in text_cleaned:
                    text_prefix = text_cleaned.split(first_clause)[0].strip()
                    if text_prefix:
                        text_cleaned = text_prefix

            subsections.append(
                {
                    "subsection_number": num.strip(),
                    "text": text_cleaned,
                    "status": status,
                    "clauses": clauses,
                    "amendments": amendments,
                }
            )
    else:
        text_cleaned = re.sub(r"^\[|\]$", "", clean_body).strip()
        status = "active"
        if "omitted" in text_cleaned.lower():
            status = "omitted"
        elif "substituted" in text_cleaned.lower():
            status = "substituted"

        amendments = map_amendments(section_body, footnotes)
        clauses = extract_clauses(text_cleaned)

        if clauses:
            first_clause = clauses[0]["clause_number"]
            if first_clause in text_cleaned:
                text_prefix = text_cleaned.split(first_clause)[0].strip()
                if text_prefix:
                    text_cleaned = text_prefix

        subsections.append(
            {
                "subsection_number": "N/A",
                "text": text_cleaned,
                "status": status,
                "clauses": clauses,
                "amendments": amendments,
            }
        )

    return subsections


def parse_sections_robust(chap_content: str, footnotes: dict) -> list:
    sections = []
    sec_split_pattern = re.compile(r"\n(?=(\d+[A-Z]?)\.\s+)")
    chunks = sec_split_pattern.split(chap_content)

    if len(chunks) == 1:
        return sections

    for i in range(1, len(chunks), 2):
        sec_num = chunks[i].strip()
        full_body = chunks[i + 1].strip() if (i + 1) < len(chunks) else ""

        lines = full_body.split("\n", 1)
        title_candidate = lines[0].strip()

        if "—" in title_candidate or "-" in title_candidate:
            parts = re.split(r"[—\-]", title_candidate, maxsplit=1)
            sec_title = sanitize_text(parts[0])
            rest_of_first_line = parts[1].strip() if len(parts) > 1 else ""
            sec_body = rest_of_first_line + ("\n" + lines[1] if len(lines) > 1 else "")
        else:
            sec_title = sanitize_text(title_candidate)
            sec_body = lines[1] if len(lines) > 1 else ""

        parsed_subsecs = parse_subsections(sec_body, footnotes)

        # -------------------------------------------------------------
        # FIX: Filter out sections that are table-of-contents artifacts
        # (i.e., they have an "N/A" subsection with no clauses/actual text body)
        # -------------------------------------------------------------
        is_toc_artifact = (
            len(parsed_subsecs) == 1
            and parsed_subsecs[0]["subsection_number"] == "N/A"
            and not parsed_subsecs[0]["clauses"]
            and len(parsed_subsecs[0]["text"]) < 10
        )
        if is_toc_artifact:
            continue

        sections.append(
            {
                "section_number": sec_num,
                "title": sec_title,
                "status": (
                    "amended"
                    if any(
                        s["status"] != "active" or len(s["amendments"]) > 0 for s in parsed_subsecs
                    )
                    else "active"
                ),
                "subsections": parsed_subsecs,
                "amendments": map_amendments(sec_body, footnotes),
            }
        )

    return sections


def parse_act_to_json(raw_text: str, doc_type: str) -> dict:
    cleaned_text, footnotes = extract_footnotes(raw_text)

    doc_structure = {
        "act_title": "THE COMPANIES ACT, 2013",
        "doc_type": doc_type,
        "chapters": [],
    }

    chapter_pattern = re.compile(r"(CHAPTER\s+[IVXLCDM\d]+)\s*\n+([^\n]+)", re.MULTILINE)
    chapters_raw = chapter_pattern.split(cleaned_text)

    if len(chapters_raw) > 1:
        for i in range(1, len(chapters_raw), 3):
            chap_num = chapters_raw[i].strip()
            chap_title = sanitize_text(chapters_raw[i + 1])
            chap_content = chapters_raw[i + 2] if (i + 2) < len(chapters_raw) else ""

            sections = parse_sections_robust(chap_content, footnotes)
            doc_structure["chapters"].append(
                {
                    "chapter_number": chap_num,
                    "chapter_title": chap_title,
                    "sections": sections,
                }
            )
    else:
        sections = parse_sections_robust(cleaned_text, footnotes)
        doc_structure["chapters"].append(
            {
                "chapter_number": "N/A",
                "chapter_title": "General",
                "sections": sections,
            }
        )

    doc_structure["chapters"] = deduplicate_chapters(doc_structure["chapters"])
    return doc_structure


def _content_score(chapter: dict) -> int:
    """Prefer the full Act chapter over its shorter table-of-contents copy."""
    return sum(
        len(section.get("title", ""))
        + sum(
            len(subsection.get("text", ""))
            + sum(len(clause.get("text", "")) for clause in subsection.get("clauses", []))
            for subsection in section.get("subsections", [])
        )
        for section in chapter.get("sections", [])
    )


def deduplicate_chapters(chapters: list) -> list:
    """Remove duplicate chapter headings produced by parsing the PDF table of contents."""
    order = []
    best_by_number = {}

    for chapter in chapters:
        chapter_number = chapter.get("chapter_number", "").strip().upper()
        if chapter_number not in best_by_number:
            order.append(chapter_number)
            best_by_number[chapter_number] = chapter
        elif _content_score(chapter) > _content_score(best_by_number[chapter_number]):
            best_by_number[chapter_number] = chapter

    return [best_by_number[number] for number in order]


def extract_amendment_section_references(raw_text: str, source_document: str) -> dict:
    """Map principal-Act section numbers mentioned by an amendment to its source document."""
    references = {}
    pattern = re.compile(
        r"(?:(?:in|after|before)\s+)?sections?\s+(\d+[A-Z]?)\s+of\s+"
        r"(?:the\s+principal\s+Act|the\s+Companies\s+Act,?\s*2013)",
        re.IGNORECASE,
    )
    for section_number in pattern.findall(raw_text):
        references.setdefault(section_number.upper(), []).append(source_document)
    return references


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _materially_different(first: str, second: str) -> bool:
    first_normalized = _normalized_text(first)
    second_normalized = _normalized_text(second)
    if first_normalized == second_normalized:
        return False
    if not first_normalized or not second_normalized:
        return first_normalized != second_normalized
    return SequenceMatcher(None, first_normalized, second_normalized).ratio() < 0.97


def _source_note(section: dict, subsection: dict | None, amendment_sources: dict) -> str:
    notes = []
    for amendment in section.get("amendments", []):
        if amendment.get("note"):
            notes.append(amendment["note"])
    if subsection:
        for amendment in subsection.get("amendments", []):
            if amendment.get("note"):
                notes.append(amendment["note"])

    section_number = str(section.get("section_number", "")).upper()
    notes.extend(amendment_sources.get(section_number, []))
    unique_notes = list(dict.fromkeys(notes))
    return "; ".join(unique_notes) or "Amendment source was not identified in the parsed footnotes."


def _historical_entry(item: dict, change_type: str, source_note: str) -> dict:
    historical = deepcopy(item)
    historical["change_type"] = change_type
    historical["source_note"] = source_note
    historical["historical"] = True
    return historical


def merge_bare_act_history(current_act: dict, bare_act: dict | None, amendment_sources: dict) -> dict:
    """Keep enacted wording beside the current wording instead of silently discarding it."""
    if not bare_act:
        return current_act

    current_act = deepcopy(current_act)
    current_chapters = {
        chapter.get("chapter_number", "").strip().upper(): chapter
        for chapter in current_act.get("chapters", [])
    }

    for bare_chapter in bare_act.get("chapters", []):
        chapter_key = bare_chapter.get("chapter_number", "").strip().upper()
        current_chapter = current_chapters.get(chapter_key)
        if current_chapter is None:
            historical_chapter = deepcopy(bare_chapter)
            historical_chapter["historical"] = True
            current_act.setdefault("chapters", []).append(historical_chapter)
            current_chapters[chapter_key] = historical_chapter
            continue

        current_sections = {
            str(section.get("section_number", "")).upper(): section
            for section in current_chapter.get("sections", [])
        }

        for bare_section in bare_chapter.get("sections", []):
            section_key = str(bare_section.get("section_number", "")).upper()
            current_section = current_sections.get(section_key)
            if current_section is None:
                source_note = _source_note(bare_section, None, amendment_sources)
                omitted_section = _historical_entry(bare_section, "omitted", source_note)
                omitted_section["status"] = "omitted"
                current_chapter.setdefault("sections", []).append(omitted_section)
                continue

            current_subsections = {
                str(subsection.get("subsection_number", "N/A")).upper(): subsection
                for subsection in current_section.get("subsections", [])
            }

            for bare_subsection in bare_section.get("subsections", []):
                subsection_key = str(bare_subsection.get("subsection_number", "N/A")).upper()
                current_subsection = current_subsections.get(subsection_key)
                source_note = _source_note(current_section, current_subsection, amendment_sources)

                if current_subsection is None:
                    current_section.setdefault("historical_subsections", []).append(
                        _historical_entry(bare_subsection, "omitted", source_note)
                    )
                    continue

                bare_clauses = bare_subsection.get("clauses", [])
                current_clauses = {
                    str(clause.get("clause_number", "")).lower(): clause
                    for clause in current_subsection.get("clauses", [])
                }
                for bare_clause in bare_clauses:
                    clause_key = str(bare_clause.get("clause_number", "")).lower()
                    current_clause = current_clauses.get(clause_key)
                    if current_clause is None:
                        current_subsection.setdefault("historical_clauses", []).append(
                            _historical_entry(bare_clause, "omitted", source_note)
                        )
                    elif _materially_different(
                        bare_clause.get("text", ""), current_clause.get("text", "")
                    ):
                        current_subsection.setdefault("historical_clauses", []).append(
                            _historical_entry(bare_clause, "substituted", source_note)
                        )

                if not bare_clauses and _materially_different(
                    bare_subsection.get("text", ""), current_subsection.get("text", "")
                ):
                    current_subsection.setdefault("historical_versions", []).append(
                        _historical_entry(bare_subsection, "substituted", source_note)
                    )

    return current_act


def classify_document(pdf_path: Path) -> str:
    """Classifies document type based on filename."""
    filename = pdf_path.name.lower()
    if "current" in filename or "principal" in filename:
        return "current_act"
    elif "bare" in filename or "original" in filename:
        return "bare_act"
    elif "amendment" in filename or "ordinance" in filename:
        return "amendment"
    else:
        return "current_act"


def process_docs_pipeline():
    """Main pipeline execution function."""
    if not DOCS_DIR.exists():
        print(f"Directory not found: {DOCS_DIR}")
        return

    pdf_files = sorted(DOCS_DIR.rglob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {DOCS_DIR}")
        return

    parsed_docs = {"current_act": None, "bare_act": None}
    amendment_sources = {}

    for pdf_path in pdf_files:
        doc_type = classify_document(pdf_path)
        print(f"Processing ({doc_type}): {pdf_path.name}...")

        raw_text = extract_raw_text(pdf_path)
        if doc_type == "current_act":
            parsed_docs["current_act"] = parse_act_to_json(raw_text, doc_type)
        elif doc_type == "bare_act":
            parsed_docs["bare_act"] = parse_act_to_json(raw_text, doc_type)
        elif doc_type == "amendment":
            references = extract_amendment_section_references(
                raw_text, pdf_path.stem.replace("_", " ")
            )
            for section_number, sources in references.items():
                amendment_sources.setdefault(section_number, []).extend(sources)

    if parsed_docs["current_act"]:
        master_document = merge_bare_act_history(
            parsed_docs["current_act"], parsed_docs["bare_act"], amendment_sources
        )
        output_path = DOCS_DIR / "sections_master.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(master_document, f, indent=2, ensure_ascii=False)

        print(f"\nMaster compiled JSON saved to: {output_path.name}")

        # Automatically sync generated JSON file to React frontend
        frontend_public_docs = SCRIPT_DIR.parent / "frontend" / "public" / "docs"
        frontend_public_docs.mkdir(parents=True, exist_ok=True)
        destination_path = frontend_public_docs / "sections_master.json"

        shutil.copy(output_path, destination_path)
        print(
            f"Copied output to frontend public directory: {destination_path.relative_to(SCRIPT_DIR.parent)}"  # noqa: E501
        )


if __name__ == "__main__":
    process_docs_pipeline()
