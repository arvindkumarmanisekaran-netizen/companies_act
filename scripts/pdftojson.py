import json
import re
import shutil
from pathlib import Path
from pdf2image import convert_from_path
import pdfplumber
import pytesseract
import pytest

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

    return doc_structure


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

    pdf_files = list(DOCS_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {DOCS_DIR}")
        return

    parsed_docs = {"current_act": None, "bare_act": None, "amendments": []}

    for pdf_path in pdf_files:
        doc_type = classify_document(pdf_path)
        print(f"Processing ({doc_type}): {pdf_path.name}...")

        raw_text = extract_raw_text(pdf_path)
        parsed_structure = parse_act_to_json(raw_text, doc_type)

        if doc_type == "current_act":
            parsed_docs["current_act"] = parsed_structure
        elif doc_type == "bare_act":
            parsed_docs["bare_act"] = parsed_structure
        elif doc_type == "amendment":
            parsed_docs["amendments"].append(parsed_structure)

    if parsed_docs["current_act"]:
        output_path = DOCS_DIR / "sections_master.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(parsed_docs["current_act"], f, indent=2, ensure_ascii=False)

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


# ==========================================
# JSON STRUCTURE & COMPLETENESS TESTS
# ==========================================


@pytest.fixture
def parsed_sample_doc():
    """Fixture providing parsed JSON structure from multi-section legal text."""
    sample_raw_text = """
CHAPTER VII
MANAGEMENT AND ADMINISTRATION
120. Maintenance and inspection of documents in electronic form.—Without prejudice to any other
provisions of this Act, any document, record, register, minutes, etc.,—
(a) required to be kept by a company; or
(b) allowed to be inspected or copies to be given to any person by a company under this Act.

121. Report on annual general meeting.—(1) Every listed public company shall prepare in the 
prescribed manner.  
(2) The company shall file with the Registrar a copy of the report 1***.
2[(3) If the company fails to file the report under sub-section (2)...]

122. Applicability of this Chapter to One Person Company.—(1) The provisions of section 98 shall 
not apply.
(2) The ordinary businesses as mentioned under clause (a) of sub-section (2)...
(3) For the purposes of section 114, any business...
(4) Notwithstanding anything in this Act...

CHAPTER VIII
DECLARATION AND PAYMENT OF DIVIDEND
123. Declaration of dividend.—(1) No dividend shall be declared or paid by a company except—
(a) out of the profits of the company; or
(b) out of the profits of previous financial years.

1. The words omitted by Act 1 of 2018, s. 31 (w.e.f. 7-5-2018).
2. Subs. by Act 22 of 2019, s. 19 (w.e.f. 2-11-2018).
"""
    return parse_act_to_json(sample_raw_text, "current_act")


def test_presence_of_all_expected_sections(parsed_sample_doc):
    """Test that all expected sections (120, 121, 122, 123) are present in sequence."""
    extracted_sections = []
    for chapter in parsed_sample_doc.get("chapters", []):
        for sec in chapter.get("sections", []):
            extracted_sections.append(sec.get("section_number"))

    expected_sections = ["120", "121", "122", "123"]
    assert (
        extracted_sections == expected_sections
    ), f"Missing or out-of-order sections. Expected {expected_sections}, got {extracted_sections}"


def test_presence_of_subsections_in_every_section(parsed_sample_doc):
    """Test that every extracted section contains a non-empty list of subsections."""
    for chapter in parsed_sample_doc.get("chapters", []):
        for sec in chapter.get("sections", []):
            sec_num = sec.get("section_number")
            subsections = sec.get("subsections", [])

            assert isinstance(
                subsections, list
            ), f"Section {sec_num} subsections field is not a list"
            assert len(subsections) > 0, f"Section {sec_num} has no subsections"


def test_section_121_all_subsections_present(parsed_sample_doc):
    """Test that Section 121 contains all 3 numerical subsections [(1), (2), (3)]."""
    sec_121 = None
    for chapter in parsed_sample_doc.get("chapters", []):
        for sec in chapter.get("sections", []):
            if sec.get("section_number") == "121":
                sec_121 = sec
                break

    assert sec_121 is not None, "Section 121 not found in JSON output"

    subsec_numbers = [sub["subsection_number"] for sub in sec_121["subsections"]]
    assert subsec_numbers == [
        "(1)",
        "(2)",
        "(3)",
    ], f"Section 121 subsection hierarchy mismatch. Expected ['(1)', '(2)', '(3)'], got {subsec_numbers}"  # noqa: E501


def test_section_122_all_subsections_present(parsed_sample_doc):
    """Test that Section 122 contains all 4 numerical subsections [(1), (2), (3), (4)]."""
    sec_122 = None
    for chapter in parsed_sample_doc.get("chapters", []):
        for sec in chapter.get("sections", []):
            if sec.get("section_number") == "122":
                sec_122 = sec
                break

    assert sec_122 is not None, "Section 122 not found in JSON output"

    subsec_numbers = [sub["subsection_number"] for sub in sec_122["subsections"]]
    assert subsec_numbers == [
        "(1)",
        "(2)",
        "(3)",
        "(4)",
    ], f"Section 122 subsection hierarchy mismatch. Expected ['(1)', '(2)', '(3)', '(4)'], got {subsec_numbers}"  # noqa: E501


def test_json_schema_field_integrity(parsed_sample_doc):
    """Test that all section and subsection objects contain required structural schema keys."""
    required_sec_keys = {"section_number", "title", "status", "subsections"}
    required_sub_keys = {
        "subsection_number",
        "text",
        "status",
        "clauses",
        "amendments",
    }

    for chapter in parsed_sample_doc.get("chapters", []):
        for sec in chapter.get("sections", []):
            assert required_sec_keys.issubset(
                sec.keys()
            ), f"Section {sec.get('section_number')} missing keys: {required_sec_keys - sec.keys()}"
            for sub in sec["subsections"]:
                assert required_sub_keys.issubset(
                    sub.keys()
                ), f"Subsection {sub.get('subsection_number')} in Sec {sec.get('section_number')} missing keys: {required_sub_keys - sub.keys()}"  # noqa: E501
