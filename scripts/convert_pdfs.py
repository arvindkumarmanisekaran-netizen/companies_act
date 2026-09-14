#!/usr/bin/env python3

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF


# ============================================================
# PATHS
# ============================================================

DEFAULT_INPUT_ROOT = Path("mca_companies_act_2013")
DEFAULT_OUTPUT_ROOT = Path("mca_companies_act_2013_text")


# ============================================================
# GEMINI
# ============================================================

DEFAULT_GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite",
)

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"

GEMINI_MAX_ATTEMPTS = 5
GEMINI_RETRY_BASE_SECONDS = 3
GEMINI_429_BASE_SECONDS = 15

# Delay after one Gemini page request and before another.
GEMINI_INTER_REQUEST_DELAY_SECONDS = 1.5


# ============================================================
# DOCUMENT RETRY
# ============================================================

DOCUMENT_MAX_ATTEMPTS = 3
DOCUMENT_RETRY_DELAY_SECONDS = 5

# Required delay between one PDF conversion and the next.
DOCUMENT_CONVERSION_DELAY_SECONDS = 5


# ============================================================
# TEXT QUALITY
# ============================================================

MIN_NATIVE_ENGLISH_CHARS = 120
MIN_NATIVE_ENGLISH_WORDS = 20


# ============================================================
# PAGE RENDERING
# ============================================================

RENDER_DPI = 170


# ============================================================
# FILESYSTEM
# ============================================================

# Linux ext4 normally allows at most 255 bytes for one filename component.
MAX_FILENAME_COMPONENT_BYTES = 255

# This is the longest suffix we create.
#
#   document.partial.json.tmp
#
# We MUST reserve space for this when truncating the stem.
LONGEST_OUTPUT_SUFFIX = ".partial.json.tmp"

# Hash used when truncating very long names.
OUTPUT_HASH_LENGTH = 12


# ============================================================
# GEMINI GLOBAL STATE
# ============================================================

gemini_backend = None
gemini_client = None
gemini_model_object = None
gemini_model_name = None


# ============================================================
# GEMINI PROMPT
# ============================================================

GEMINI_PAGE_PROMPT = """
You are performing exact legal-document text extraction from one page of an
Indian Ministry of Corporate Affairs / Gazette PDF.

Extract ONLY the ENGLISH text visible on this page.

STRICT REQUIREMENTS:

1. IGNORE all Hindi / Devanagari text completely.
2. Do NOT translate Hindi into English.
3. Do NOT summarize.
4. Do NOT paraphrase.
5. Do NOT explain the document.
6. Do NOT infer missing words.
7. Preserve the original English wording as accurately as possible.
8. Preserve section numbers, rule numbers, clause numbers, sub-clauses,
   provisos, explanations, form numbers, notification numbers, circular
   numbers, dates, Gazette identifiers and statutory citations exactly.
9. Preserve paragraph order.
10. Preserve headings.
11. Preserve footnotes if they are in English.
12. Preserve table content. Represent tables as readable plain text or
    Markdown-style rows, but do not omit cells.
13. Preserve amendment language exactly, including wording such as:
       "for the words..."
       "the following shall be substituted..."
       "shall be inserted..."
       "shall be omitted..."
14. Do not add Markdown code fences.
15. Do not prepend phrases such as "Extracted text:".
16. If there is genuinely no English text on the page, return exactly:

NO_ENGLISH_TEXT

Return only the extracted English document text.
""".strip()


# ============================================================
# TEXT REGEX
# ============================================================

DEVANAGARI_RE = re.compile(
    r"[\u0900-\u097F]"
)

DEVANAGARI_EXTENDED_RE = re.compile(
    r"[\uA8E0-\uA8FF]"
)

LATIN_LETTER_RE = re.compile(
    r"[A-Za-z]"
)

ENGLISH_WORD_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9'’.\-]*\b"
)


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_whitespace(text: str) -> str:

    if not text:
        return ""

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    text = text.replace(
        "\u00a0",
        " ",
    )

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        lines.append(
            line
        )

    result = []
    previous_blank = False

    for line in lines:

        blank = not line

        if blank and previous_blank:
            continue

        result.append(
            line
        )

        previous_blank = blank

    return "\n".join(
        result
    ).strip()


def remove_devanagari_characters(
    text: str,
) -> str:

    if not text:
        return ""

    text = DEVANAGARI_RE.sub(
        "",
        text,
    )

    text = DEVANAGARI_EXTENDED_RE.sub(
        "",
        text,
    )

    return text


def extract_english_only_from_native(
    text: str,
) -> str:

    if not text:
        return ""

    original_lines = (
        text
        .replace(
            "\r\n",
            "\n",
        )
        .replace(
            "\r",
            "\n",
        )
        .splitlines()
    )

    output_lines = []

    for raw_line in original_lines:

        raw_line = raw_line.replace(
            "\u00a0",
            " ",
        )

        line = remove_devanagari_characters(
            raw_line
        )

        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if not line:
            continue

        latin_count = len(
            LATIN_LETTER_RE.findall(
                line
            )
        )

        if latin_count > 0:

            output_lines.append(
                line
            )

            continue

        # Keep standalone legal numbering.
        structural = bool(
            re.fullmatch(
                r"""
                (?:
                    [\(\[\{]?
                    \d+
                    [A-Za-z]?
                    [\)\]\}]?
                    [.\-:]?
                )
                |
                (?:
                    [\(\[]
                    [ivxlcdmIVXLCDM]+
                    [\)\]]
                )
                |
                (?:
                    [\-–—]+
                )
                """,
                line,
                re.VERBOSE,
            )
        )

        if structural:

            output_lines.append(
                line
            )

    return clean_whitespace(
        "\n".join(
            output_lines
        )
    )


# ============================================================
# XFA PLACEHOLDER DETECTION
# ============================================================

XFA_PLACEHOLDER_PATTERNS = [
    "please wait...",
    "please wait",
    "if this message is not eventually replaced",
    "your pdf viewer may not be able to display this type of document",
    "to view the full contents of this document",
    "you need a later version of the pdf viewer",
]


def looks_like_xfa_placeholder(
    text: str,
) -> bool:

    normalized = clean_whitespace(
        text
    ).lower()

    if not normalized:
        return False

    matches = sum(
        1
        for phrase in XFA_PLACEHOLDER_PATTERNS
        if phrase in normalized
    )

    return matches >= 2


# ============================================================
# NATIVE TEXT QUALITY
# ============================================================

def native_text_statistics(
    text: str,
) -> dict:

    return {
        "latin_characters":
            len(
                LATIN_LETTER_RE.findall(
                    text or ""
                )
            ),

        "english_words":
            len(
                ENGLISH_WORD_RE.findall(
                    text or ""
                )
            ),

        "text_characters":
            len(
                text or ""
            ),
    }


def native_text_is_good(
    text: str,
) -> tuple[bool, str, dict]:

    stats = native_text_statistics(
        text
    )

    if not text.strip():

        return (
            False,
            "empty",
            stats,
        )

    if looks_like_xfa_placeholder(
        text
    ):

        return (
            False,
            "xfa_placeholder",
            stats,
        )

    if (
        stats["latin_characters"]
        < MIN_NATIVE_ENGLISH_CHARS
    ):

        return (
            False,
            "too_few_english_characters",
            stats,
        )

    if (
        stats["english_words"]
        < MIN_NATIVE_ENGLISH_WORDS
    ):

        return (
            False,
            "too_few_english_words",
            stats,
        )

    return (
        True,
        "good",
        stats,
    )


# ============================================================
# GEMINI INITIALIZATION
# ============================================================

def initialize_gemini(
    model_name: str,
):

    global gemini_backend
    global gemini_client
    global gemini_model_object
    global gemini_model_name

    if gemini_backend is not None:
        return

    api_key = os.environ.get(
        GEMINI_API_KEY_ENV
    )

    if not api_key:

        raise RuntimeError(
            "Gemini fallback is required but "
            "GEMINI_API_KEY is not set.\n\n"
            "Example:\n"
            "export GEMINI_API_KEY='your-key'"
        )

    gemini_model_name = model_name

    # ========================================================
    # CURRENT SDK
    # ========================================================

    try:

        from google import genai

        gemini_client = genai.Client(
            api_key=api_key
        )

        gemini_backend = (
            "google-genai"
        )

        print()
        print(
            "[GEMINI] Initialized"
        )

        print(
            "[GEMINI] Backend:",
            gemini_backend,
        )

        print(
            "[GEMINI] Model:",
            gemini_model_name,
        )

        print(
            "[GEMINI] API key source:",
            GEMINI_API_KEY_ENV,
        )

        return

    except ImportError:
        pass

    # ========================================================
    # OLD SDK FALLBACK
    # ========================================================

    try:

        import google.generativeai as old_genai

        old_genai.configure(
            api_key=api_key
        )

        gemini_model_object = (
            old_genai.GenerativeModel(
                model_name
            )
        )

        gemini_backend = (
            "google-generativeai"
        )

        print()
        print(
            "[GEMINI] Initialized"
        )

        print(
            "[GEMINI] Backend:",
            gemini_backend,
        )

        print(
            "[GEMINI] Model:",
            gemini_model_name,
        )

        print(
            "[GEMINI] API key source:",
            GEMINI_API_KEY_ENV,
        )

        return

    except ImportError:
        pass

    raise RuntimeError(
        "No Gemini Python SDK is installed.\n\n"
        "Install with:\n\n"
        "pip install google-genai"
    )


# ============================================================
# PAGE RENDER
# ============================================================

def render_page_png(
    page,
    dpi: int = RENDER_DPI,
) -> bytes:

    zoom = (
        dpi
        / 72.0
    )

    matrix = fitz.Matrix(
        zoom,
        zoom,
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False,
    )

    return pixmap.tobytes(
        "png"
    )


# ============================================================
# GEMINI RESPONSE
# ============================================================

def normalize_gemini_text(
    text: str,
) -> str:

    text = clean_whitespace(
        text or ""
    )

    if not text:
        return ""

    if (
        text.strip()
        == "NO_ENGLISH_TEXT"
    ):

        return ""

    # Defensive removal.
    text = remove_devanagari_characters(
        text
    )

    text = clean_whitespace(
        text
    )

    text = re.sub(
        r"^```(?:text|markdown)?\s*",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return text.strip()


def is_rate_limit_error(
    exc: Exception,
) -> bool:

    value = str(
        exc
    ).lower()

    return (
        "429" in value
        or
        "resource_exhausted" in value
        or
        "rate limit" in value
        or
        "quota" in value
    )


# ============================================================
# GEMINI SINGLE REQUEST
# ============================================================

def extract_page_with_gemini_once(
    png_bytes: bytes,
) -> str:

    if (
        gemini_backend
        == "google-genai"
    ):

        from google.genai import types

        response = (
            gemini_client
            .models
            .generate_content(
                model=gemini_model_name,
                contents=[
                    GEMINI_PAGE_PROMPT,

                    types.Part.from_bytes(
                        data=png_bytes,
                        mime_type="image/png",
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                ),
            )
        )

        return normalize_gemini_text(
            response.text
            or ""
        )

    if (
        gemini_backend
        == "google-generativeai"
    ):

        response = (
            gemini_model_object
            .generate_content(
                [
                    GEMINI_PAGE_PROMPT,

                    {
                        "mime_type":
                            "image/png",

                        "data":
                            png_bytes,
                    },
                ],
                generation_config={
                    "temperature":
                        0,
                },
            )
        )

        return normalize_gemini_text(
            getattr(
                response,
                "text",
                "",
            )
            or ""
        )

    raise RuntimeError(
        "Gemini has not been initialized."
    )


# ============================================================
# GEMINI RETRY
# ============================================================

def extract_page_with_gemini(
    png_bytes: bytes,
    model_name: str,
    document_name: str,
    page_number: int,
) -> str:

    initialize_gemini(
        model_name
    )

    last_error = None

    for attempt in range(
        1,
        GEMINI_MAX_ATTEMPTS + 1,
    ):

        print(
            (
                "    [GEMINI] "
                f"Attempt {attempt}/"
                f"{GEMINI_MAX_ATTEMPTS}"
            ),
            flush=True,
        )

        started = (
            time.monotonic()
        )

        try:

            text = (
                extract_page_with_gemini_once(
                    png_bytes
                )
            )

            elapsed = (
                time.monotonic()
                - started
            )

            print(
                (
                    "    [GEMINI] "
                    f"Success in {elapsed:.2f}s; "
                    f"English chars={len(text)}"
                ),
                flush=True,
            )

            if (
                GEMINI_INTER_REQUEST_DELAY_SECONDS
                > 0
            ):

                time.sleep(
                    GEMINI_INTER_REQUEST_DELAY_SECONDS
                )

            return text

        except Exception as exc:

            last_error = exc

            print(
                (
                    "    [GEMINI] "
                    f"Failed: {repr(exc)}"
                ),
                flush=True,
            )

            if (
                attempt
                >= GEMINI_MAX_ATTEMPTS
            ):
                break

            if is_rate_limit_error(
                exc
            ):

                delay = (
                    GEMINI_429_BASE_SECONDS
                    * (
                        2
                        ** (
                            attempt - 1
                        )
                    )
                )

            else:

                delay = (
                    GEMINI_RETRY_BASE_SECONDS
                    * (
                        2
                        ** (
                            attempt - 1
                        )
                    )
                )

            print(
                (
                    "    [GEMINI] "
                    f"Retrying in {delay}s..."
                ),
                flush=True,
            )

            time.sleep(
                delay
            )

    raise RuntimeError(
        (
            "Gemini extraction failed after "
            f"{GEMINI_MAX_ATTEMPTS} attempts "
            f"for {document_name}, "
            f"page {page_number}: "
            f"{last_error}"
        )
    )


# ============================================================
# DOWNLOAD MANIFESTS
# ============================================================

def load_download_manifests(
    input_root: Path,
) -> dict:

    mapping = {}

    manifest_files = list(
        input_root.rglob(
            "downloads.csv"
        )
    )

    print(
        "[MANIFEST] Found",
        len(
            manifest_files
        ),
        "downloads.csv files",
    )

    for manifest_path in manifest_files:

        try:

            with manifest_path.open(
                "r",
                newline="",
                encoding="utf-8-sig",
            ) as file:

                reader = csv.DictReader(
                    file
                )

                for row in reader:

                    document_id = clean_whitespace(
                        row.get(
                            "document_id",
                            "",
                        )
                    )

                    saved_filename = clean_whitespace(
                        row.get(
                            "saved_filename",
                            "",
                        )
                    )

                    if (
                        not document_id
                        or
                        not saved_filename
                    ):
                        continue

                    pdf_path = (
                        manifest_path.parent
                        / saved_filename
                    )

                    try:

                        resolved = str(
                            pdf_path.resolve()
                        )

                    except Exception:
                        continue

                    mapping[
                        resolved
                    ] = document_id

        except Exception as exc:

            print(
                (
                    "[MANIFEST] Could not read "
                    f"{manifest_path}: "
                    f"{repr(exc)}"
                )
            )

    print(
        "[MANIFEST] Document IDs mapped:",
        len(
            mapping
        ),
    )

    return mapping


# ============================================================
# DOCUMENT ID
# ============================================================

def determine_document_id(
    pdf_path: Path,
    manifest_mapping: dict,
) -> str:

    resolved = str(
        pdf_path.resolve()
    )

    document_id = (
        manifest_mapping.get(
            resolved
        )
    )

    if document_id:
        return document_id

    match = re.search(
        r"\((\d{3,})\)\s*$",
        pdf_path.stem,
    )

    if match:

        return match.group(
            1
        )

    return pdf_path.stem


def document_id_source(
    pdf_path: Path,
    manifest_mapping: dict,
) -> str:

    resolved = str(
        pdf_path.resolve()
    )

    if (
        resolved
        in manifest_mapping
    ):

        return "downloads_manifest"

    if re.search(
        r"\((\d{3,})\)\s*$",
        pdf_path.stem,
    ):

        return "filename"

    return "filename_stem_fallback"


# ============================================================
# SAFE OUTPUT FILENAMES
# ============================================================

def truncate_utf8_bytes(
    value: str,
    maximum_bytes: int,
) -> str:

    raw = value.encode(
        "utf-8"
    )

    if len(raw) <= maximum_bytes:
        return value

    raw = raw[
        :maximum_bytes
    ]

    while raw:

        try:

            return raw.decode(
                "utf-8"
            ).rstrip(
                " ."
            )

        except UnicodeDecodeError:

            raw = raw[:-1]

    return ""


def safe_output_stem(
    pdf_path: Path,
) -> str:
    """
    Make an output basename guaranteed to fit even when our
    longest suffix is added:

        .partial.json.tmp

    When truncation is necessary, append a deterministic SHA1
    fragment so two long filenames with an identical prefix do
    not overwrite each other.
    """

    original_stem = (
        pdf_path.stem
    )

    suffix_bytes = len(
        LONGEST_OUTPUT_SUFFIX.encode(
            "utf-8"
        )
    )

    max_stem_bytes = (
        MAX_FILENAME_COMPONENT_BYTES
        - suffix_bytes
    )

    original_bytes = (
        original_stem.encode(
            "utf-8"
        )
    )

    if (
        len(
            original_bytes
        )
        <= max_stem_bytes
    ):

        return original_stem

    digest = hashlib.sha1(
        pdf_path.name.encode(
            "utf-8"
        )
    ).hexdigest()[
        :OUTPUT_HASH_LENGTH
    ]

    hash_marker = (
        f"__{digest}"
    )

    hash_bytes = len(
        hash_marker.encode(
            "utf-8"
        )
    )

    prefix_budget = (
        max_stem_bytes
        - hash_bytes
    )

    prefix = truncate_utf8_bytes(
        original_stem,
        prefix_budget,
    )

    result = (
        prefix
        + hash_marker
    )

    # Defensive verification.
    longest_result = (
        result
        + LONGEST_OUTPUT_SUFFIX
    )

    if (
        len(
            longest_result.encode(
                "utf-8"
            )
        )
        > MAX_FILENAME_COMPONENT_BYTES
    ):

        raise RuntimeError(
            (
                "Internal filename sizing error: "
                f"{longest_result}"
            )
        )

    return result


def build_output_paths(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
) -> dict:

    relative_parent = (
        pdf_path
        .relative_to(
            input_root
        )
        .parent
    )

    output_dir = (
        output_root
        / relative_parent
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stem = safe_output_stem(
        pdf_path
    )

    return {
        "directory":
            output_dir,

        "stem":
            stem,

        "json":
            output_dir
            / f"{stem}.json",

        "txt":
            output_dir
            / f"{stem}.txt",

        "checkpoint":
            output_dir
            / f"{stem}.partial.json",
    }


# ============================================================
# TIME
# ============================================================

def utc_now_iso() -> str:

    return (
        datetime
        .now(
            timezone.utc
        )
        .isoformat()
    )


# ============================================================
# CHECKPOINT
# ============================================================

def load_checkpoint(
    checkpoint_path: Path,
) -> Optional[dict]:

    if not checkpoint_path.exists():
        return None

    try:

        return json.loads(
            checkpoint_path.read_text(
                encoding="utf-8"
            )
        )

    except Exception as exc:

        print(
            (
                "[CHECKPOINT] "
                f"Could not read "
                f"{checkpoint_path}: "
                f"{repr(exc)}"
            )
        )

        return None


def save_checkpoint(
    checkpoint_path: Path,
    data: dict,
):

    # Example:
    #
    # file.partial.json
    #
    # becomes:
    #
    # file.partial.json.tmp

    temp_path = Path(
        str(
            checkpoint_path
        )
        + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp_path.replace(
        checkpoint_path
    )


# ============================================================
# TXT OUTPUT
# ============================================================

def build_txt_output(
    final_json: dict,
) -> str:

    lines = []

    lines.append(
        (
            "DOCUMENT ID: "
            f"{final_json.get('document_id', '')}"
        )
    )

    lines.append(
        (
            "DOCUMENT ID SOURCE: "
            f"{final_json.get('document_id_source', '')}"
        )
    )

    lines.append(
        (
            "SOURCE FILE: "
            f"{final_json['source']['filename']}"
        )
    )

    lines.append(
        (
            "SOURCE PATH: "
            f"{final_json['source']['relative_path']}"
        )
    )

    lines.append(
        (
            "TOTAL PAGES: "
            f"{final_json['extraction']['total_pages']}"
        )
    )

    lines.append(
        (
            "NATIVE TEXT PAGES: "
            f"{final_json['extraction']['native_text_pages']}"
        )
    )

    lines.append(
        (
            "GEMINI PAGES: "
            f"{final_json['extraction']['gemini_pages']}"
        )
    )

    lines.append(
        ""
    )

    for page in final_json.get(
        "pages",
        []
    ):

        lines.append(
            "=" * 78
        )

        lines.append(
            (
                f"PAGE {page.get('page')} "
                f"[{page.get('method', '')}]"
            )
        )

        lines.append(
            "=" * 78
        )

        lines.append(
            ""
        )

        text = page.get(
            "text",
            ""
        )

        if text:

            lines.append(
                text
            )

        else:

            lines.append(
                "[NO ENGLISH TEXT]"
            )

        lines.append(
            ""
        )

    return "\n".join(
        lines
    ).rstrip() + "\n"


# ============================================================
# PAGE EXTRACTION
# ============================================================

def extract_page(
    page,
    page_number: int,
    pdf_name: str,
    gemini_model: str,
    force_gemini: bool = False,
) -> dict:

    native_raw = ""

    native_reason = (
        "not_attempted"
    )

    stats = {
        "latin_characters":
            0,

        "english_words":
            0,

        "text_characters":
            0,
    }

    if not force_gemini:

        try:

            native_raw = page.get_text(
                "text",
                sort=True,
            )

        except Exception as exc:

            native_reason = (
                "native_extraction_error"
            )

            print(
                (
                    "    [NATIVE] Error: "
                    f"{repr(exc)}"
                )
            )

        native_english = (
            extract_english_only_from_native(
                native_raw
            )
        )

        (
            native_good,
            native_reason,
            stats,
        ) = native_text_is_good(
            native_english
        )

        if native_good:

            return {
                "page":
                    page_number,

                "method":
                    "native_text",

                "fallback_reason":
                    None,

                "native_statistics":
                    stats,

                "text":
                    native_english,
            }

    else:

        native_reason = (
            "force_gemini"
        )

    print(
        (
            "    [FALLBACK] "
            "Gemini required: "
            f"{native_reason}"
        ),
        flush=True,
    )

    png_bytes = render_page_png(
        page
    )

    gemini_text = (
        extract_page_with_gemini(
            png_bytes=png_bytes,
            model_name=gemini_model,
            document_name=pdf_name,
            page_number=page_number,
        )
    )

    return {
        "page":
            page_number,

        "method":
            "gemini_vision",

        "fallback_reason":
            native_reason,

        "native_statistics":
            stats,

        "text":
            gemini_text,
    }


# ============================================================
# FINAL JSON
# ============================================================

def create_final_json(
    pdf_path: Path,
    input_root: Path,
    output_stem: str,
    document_id: str,
    id_source: str,
    pages: list,
    total_pages: int,
    gemini_model: str,
) -> dict:

    native_pages = sum(
        1
        for page in pages
        if page.get(
            "method"
        )
        == "native_text"
    )

    gemini_pages = sum(
        1
        for page in pages
        if page.get(
            "method"
        )
        == "gemini_vision"
    )

    empty_pages = sum(
        1
        for page in pages
        if not clean_whitespace(
            page.get(
                "text",
                "",
            )
        )
    )

    full_text_parts = []

    for page in pages:

        text = clean_whitespace(
            page.get(
                "text",
                "",
            )
        )

        if text:

            full_text_parts.append(
                text
            )

    full_text = "\n\n".join(
        full_text_parts
    )

    return {
        "schema_version":
            "1.0",

        "document_id":
            document_id,

        "document_id_source":
            id_source,

        "source": {
            "filename":
                pdf_path.name,

            "relative_path":
                str(
                    pdf_path.relative_to(
                        input_root
                    )
                ),

            "absolute_path":
                str(
                    pdf_path.resolve()
                ),
        },

        "output": {
            "safe_stem":
                output_stem,

            "filename_was_shortened":
                (
                    output_stem
                    != pdf_path.stem
                ),
        },

        "language": {
            "output_language":
                "English",

            "hindi_extracted":
                False,

            "translation_used":
                False,
        },

        "extraction": {
            "status":
                "complete",

            "completed_at":
                utc_now_iso(),

            "total_pages":
                total_pages,

            "native_text_pages":
                native_pages,

            "gemini_pages":
                gemini_pages,

            "empty_english_pages":
                empty_pages,

            "gemini_model":
                (
                    gemini_model
                    if gemini_pages
                    else None
                ),

            "render_dpi":
                (
                    RENDER_DPI
                    if gemini_pages
                    else None
                ),

            "requires_review":
                bool(
                    empty_pages
                ),
        },

        "pages":
            pages,

        "full_text":
            full_text,
    }


# ============================================================
# PROCESS ONE PDF
# ============================================================

def process_pdf(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    manifest_mapping: dict,
    gemini_model: str,
    force: bool = False,
    force_gemini: bool = False,
) -> dict:

    outputs = build_output_paths(
        pdf_path,
        input_root,
        output_root,
    )

    final_json_path = outputs[
        "json"
    ]

    txt_path = outputs[
        "txt"
    ]

    checkpoint_path = outputs[
        "checkpoint"
    ]

    output_stem = outputs[
        "stem"
    ]

    if (
        final_json_path.exists()
        and
        txt_path.exists()
        and
        not force
    ):

        return {
            "status":
                "skipped",

            "reason":
                "already_complete",

            "pdf":
                str(
                    pdf_path
                ),

            "json":
                str(
                    final_json_path
                ),

            "txt":
                str(
                    txt_path
                ),
        }

    if force:

        for path in [
            final_json_path,
            txt_path,
            checkpoint_path,
            Path(
                str(
                    checkpoint_path
                )
                + ".tmp"
            ),
        ]:

            try:

                if path.exists():

                    path.unlink()

            except Exception:
                pass

    document_id = determine_document_id(
        pdf_path,
        manifest_mapping,
    )

    id_source = document_id_source(
        pdf_path,
        manifest_mapping,
    )

    print(
        "  Document ID:",
        document_id,
    )

    print(
        "  ID source:",
        id_source,
    )

    if (
        output_stem
        != pdf_path.stem
    ):

        print(
            "  Long filename detected."
        )

        print(
            "  Safe output stem:",
            output_stem,
        )

    document = fitz.open(
        pdf_path
    )

    pages_by_number = {}

    try:

        total_pages = (
            document.page_count
        )

        print(
            "  Pages:",
            total_pages,
        )

        checkpoint = (
            load_checkpoint(
                checkpoint_path
            )
            or {}
        )

        checkpoint_pages = (
            checkpoint.get(
                "pages"
            )
            or []
        )

        pages_by_number = {
            int(
                item[
                    "page"
                ]
            ):
                item
            for item in checkpoint_pages
            if item.get(
                "page"
            )
            is not None
        }

        if pages_by_number:

            print(
                (
                    "  RESUME: "
                    f"{len(pages_by_number)}/"
                    f"{total_pages} pages "
                    "already checkpointed"
                )
            )

        for page_index in range(
            total_pages
        ):

            page_number = (
                page_index + 1
            )

            if (
                page_number
                in pages_by_number
            ):

                print(
                    (
                        f"  [{page_number}/"
                        f"{total_pages}] "
                        "checkpoint → SKIP PAGE"
                    ),
                    flush=True,
                )

                continue

            print(
                (
                    f"  [{page_number}/"
                    f"{total_pages}] "
                    "extracting..."
                ),
                flush=True,
            )

            page = document.load_page(
                page_index
            )

            result = extract_page(
                page=page,
                page_number=page_number,
                pdf_name=pdf_path.name,
                gemini_model=gemini_model,
                force_gemini=force_gemini,
            )

            print(
                (
                    "    method="
                    f"{result['method']} "
                    "english_chars="
                    f"{len(result.get('text', ''))}"
                ),
                flush=True,
            )

            pages_by_number[
                page_number
            ] = result

            ordered_pages = [
                pages_by_number[
                    number
                ]
                for number in sorted(
                    pages_by_number
                )
            ]

            checkpoint_data = {
                "schema_version":
                    "1.0",

                "status":
                    "partial",

                "document_id":
                    document_id,

                "document_id_source":
                    id_source,

                "source_pdf":
                    str(
                        pdf_path
                    ),

                "output_stem":
                    output_stem,

                "total_pages":
                    total_pages,

                "updated_at":
                    utc_now_iso(),

                "pages":
                    ordered_pages,
            }

            save_checkpoint(
                checkpoint_path,
                checkpoint_data,
            )

            print(
                (
                    "    checkpoint="
                    f"{len(pages_by_number)}/"
                    f"{total_pages}"
                ),
                flush=True,
            )

    finally:

        document.close()

    if (
        len(
            pages_by_number
        )
        != total_pages
    ):

        raise RuntimeError(
            (
                "Conversion incomplete: "
                f"expected {total_pages} pages, "
                f"have {len(pages_by_number)}."
            )
        )

    pages = [
        pages_by_number[
            number
        ]
        for number in range(
            1,
            total_pages + 1
        )
    ]

    final_json = create_final_json(
        pdf_path=pdf_path,
        input_root=input_root,
        output_stem=output_stem,
        document_id=document_id,
        id_source=id_source,
        pages=pages,
        total_pages=total_pages,
        gemini_model=gemini_model,
    )

    final_json_path.write_text(
        json.dumps(
            final_json,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    txt_path.write_text(
        build_txt_output(
            final_json
        ),
        encoding="utf-8",
    )

    if (
        final_json_path.exists()
        and
        txt_path.exists()
    ):

        checkpoint_path.unlink(
            missing_ok=True
        )

        temporary_checkpoint = Path(
            str(
                checkpoint_path
            )
            + ".tmp"
        )

        temporary_checkpoint.unlink(
            missing_ok=True
        )

    return {
        "status":
            "complete",

        "pdf":
            str(
                pdf_path
            ),

        "document_id":
            document_id,

        "pages":
            total_pages,

        "native_pages":
            final_json[
                "extraction"
            ][
                "native_text_pages"
            ],

        "gemini_pages":
            final_json[
                "extraction"
            ][
                "gemini_pages"
            ],

        "empty_pages":
            final_json[
                "extraction"
            ][
                "empty_english_pages"
            ],

        "filename_shortened":
            (
                output_stem
                != pdf_path.stem
            ),

        "json":
            str(
                final_json_path
            ),

        "txt":
            str(
                txt_path
            ),
    }


# ============================================================
# DOCUMENT RETRY
# ============================================================

def process_pdf_with_retry(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    manifest_mapping: dict,
    gemini_model: str,
    force: bool = False,
    force_gemini: bool = False,
) -> dict:

    last_error = None

    outputs = build_output_paths(
        pdf_path,
        input_root,
        output_root,
    )

    checkpoint_path = outputs[
        "checkpoint"
    ]

    for attempt in range(
        1,
        DOCUMENT_MAX_ATTEMPTS + 1,
    ):

        print()
        print(
            (
                "[DOCUMENT ATTEMPT] "
                f"{attempt}/"
                f"{DOCUMENT_MAX_ATTEMPTS}"
            ),
            flush=True,
        )

        # Do not erase a checkpoint during a retry.
        effective_force = (
            force
            and
            attempt == 1
        )

        try:

            return process_pdf(
                pdf_path=pdf_path,
                input_root=input_root,
                output_root=output_root,
                manifest_mapping=manifest_mapping,
                gemini_model=gemini_model,
                force=effective_force,
                force_gemini=force_gemini,
            )

        except KeyboardInterrupt:
            raise

        except Exception as exc:

            last_error = exc

            print()
            print(
                (
                    "[DOCUMENT ATTEMPT FAILED] "
                    f"{attempt}/"
                    f"{DOCUMENT_MAX_ATTEMPTS}"
                )
            )

            print(
                "Error:",
                repr(
                    exc
                ),
            )

            if (
                attempt
                >= DOCUMENT_MAX_ATTEMPTS
            ):

                break

            if checkpoint_path.exists():

                try:

                    checkpoint = load_checkpoint(
                        checkpoint_path
                    )

                    checkpoint_count = len(
                        (
                            checkpoint
                            or {}
                        ).get(
                            "pages",
                            [],
                        )
                    )

                except Exception:

                    checkpoint_count = 0

                print(
                    (
                        "[DOCUMENT RETRY] "
                        f"Checkpoint contains "
                        f"{checkpoint_count} completed page(s). "
                        "Retry will resume from it."
                    )
                )

            else:

                print(
                    (
                        "[DOCUMENT RETRY] "
                        "No checkpoint was written before "
                        "this failure. Retry will restart "
                        "the unfinished portion."
                    )
                )

            print(
                (
                    "[DOCUMENT RETRY] "
                    f"Waiting "
                    f"{DOCUMENT_RETRY_DELAY_SECONDS}s..."
                ),
                flush=True,
            )

            time.sleep(
                DOCUMENT_RETRY_DELAY_SECONDS
            )

    raise RuntimeError(
        (
            "PDF conversion failed after "
            f"{DOCUMENT_MAX_ATTEMPTS} "
            "document attempts: "
            f"{last_error}"
        )
    )


# ============================================================
# DISCOVER PDFS RECURSIVELY
# ============================================================

def discover_pdfs(
    input_root: Path,
    category_filter: Optional[str] = None,
) -> list[Path]:

    pdfs = []

    category_normalized = (
        category_filter.lower()
        if category_filter
        else None
    )

    for pdf_path in input_root.rglob(
        "*.pdf"
    ):

        relative_path = (
            pdf_path
            .relative_to(
                input_root
            )
        )

        relative_parts = [
            part.lower()
            for part in relative_path.parts
        ]

        if (
            "debug"
            in relative_parts
        ):

            continue

        if category_normalized:

            relative_text = str(
                relative_path
            ).lower()

            if (
                category_normalized
                not in relative_text
            ):

                continue

        pdfs.append(
            pdf_path
        )

    return sorted(
        pdfs,
        key=lambda path:
            str(
                path
            ).lower(),
    )


# ============================================================
# CONVERSION MANIFEST
# ============================================================

def append_conversion_manifest(
    output_root: Path,
    record: dict,
):

    manifest_path = (
        output_root
        / "conversion_manifest.jsonl"
    )

    record = dict(
        record
    )

    record[
        "timestamp"
    ] = utc_now_iso()

    with manifest_path.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
        )

        file.write(
            "\n"
        )


# ============================================================
# DRY RUN
# ============================================================

def dry_run_report(
    pdfs: list[Path],
    input_root: Path,
    output_root: Path,
):

    complete = 0
    partial = 0
    pending = 0
    long_names = 0

    categories = {}

    for pdf_path in pdfs:

        relative = (
            pdf_path
            .relative_to(
                input_root
            )
        )

        category = (
            relative.parts[0]
            if relative.parts
            else "(root)"
        )

        categories[
            category
        ] = (
            categories.get(
                category,
                0,
            )
            + 1
        )

        outputs = build_output_paths(
            pdf_path,
            input_root,
            output_root,
        )

        if (
            outputs["stem"]
            != pdf_path.stem
        ):

            long_names += 1

        if (
            outputs[
                "json"
            ].exists()
            and
            outputs[
                "txt"
            ].exists()
        ):

            complete += 1

        elif outputs[
            "checkpoint"
        ].exists():

            partial += 1

        else:

            pending += 1

    print()
    print("=" * 78)
    print(
        "PDF CONVERSION DRY RUN"
    )
    print("=" * 78)

    print()
    print(
        "FOLDERS / CATEGORIES"
    )

    print("-" * 78)

    for category, count in sorted(
        categories.items()
    ):

        print(
            (
                f"{category:<55} "
                f"{count:>7}"
            )
        )

    print("-" * 78)

    print(
        "Total PDFs:",
        len(
            pdfs
        ),
    )

    print(
        "Already complete:",
        complete,
    )

    print(
        "Partial/checkpoint:",
        partial,
    )

    print(
        "Pending:",
        pending,
    )

    print(
        "Long output names requiring safe shortening:",
        long_names,
    )


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Convert MCA PDFs recursively into "
            "English-only JSON and TXT."
        )
    )

    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )

    parser.add_argument(
        "--type",
        dest="category_filter",
        default=None,
        help=(
            "Optional path/category filter."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
    )

    parser.add_argument(
        "--force-gemini",
        action="store_true",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "TESTING ONLY: process the first N PDFs."
        ),
    )

    parser.add_argument(
        "--gemini-model",
        default=DEFAULT_GEMINI_MODEL,
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()

    input_root = (
        args.input_root
        .expanduser()
        .resolve()
    )

    output_root = (
        args.output_root
        .expanduser()
        .resolve()
    )

    if not input_root.exists():

        print(
            "ERROR: input root does not exist:"
        )

        print(
            input_root
        )

        sys.exit(
            1
        )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("=" * 78)

    print(
        "MCA PDF → ENGLISH TEXT CONVERTER"
    )

    print("=" * 78)

    print(
        "Input root:",
        input_root,
    )

    print(
        "Output root:",
        output_root,
    )

    print(
        "Recursive subfolder search:",
        "YES",
    )

    print(
        "Gemini model:",
        args.gemini_model,
    )

    print(
        "Gemini API key env:",
        GEMINI_API_KEY_ENV,
    )

    print(
        "English only:",
        "YES",
    )

    print(
        "Hindi extraction:",
        "DISABLED",
    )

    print(
        "Hindi translation:",
        "DISABLED",
    )

    print(
        "Document retries:",
        DOCUMENT_MAX_ATTEMPTS,
    )

    print(
        "Delay between documents:",
        f"{DOCUMENT_CONVERSION_DELAY_SECONDS}s",
    )

    print(
        "Max output filename component:",
        f"{MAX_FILENAME_COMPONENT_BYTES} bytes",
    )

    # ========================================================
    # DISCOVER
    # ========================================================

    all_pdfs = discover_pdfs(
        input_root,
        args.category_filter,
    )

    print()
    print(
        "Total PDFs discovered recursively:",
        len(
            all_pdfs
        ),
    )

    pdfs = all_pdfs

    if (
        args.limit
        is not None
    ):

        print()
        print("!" * 78)

        print(
            (
                "LIMIT ACTIVE: "
                f"only the first {args.limit} "
                "PDFs will be processed."
            )
        )

        print(
            "Remove --limit to process all folders."
        )

        print("!" * 78)

        pdfs = all_pdfs[
            :args.limit
        ]

    print()
    print(
        "PDFs selected for this run:",
        len(
            pdfs
        ),
    )

    if not pdfs:

        print(
            "Nothing to process."
        )

        return

    if args.dry_run:

        dry_run_report(
            pdfs,
            input_root,
            output_root,
        )

        return

    # ========================================================
    # MANIFEST IDs
    # ========================================================

    manifest_mapping = (
        load_download_manifests(
            input_root
        )
    )

    total = len(
        pdfs
    )

    complete = 0
    skipped = 0
    failed = 0

    native_pages = 0
    gemini_pages = 0

    shortened_names = 0

    started = (
        time.monotonic()
    )

    # ========================================================
    # PROCESS
    # ========================================================

    for index, pdf_path in enumerate(
        pdfs,
        start=1,
    ):

        print()
        print("#" * 78)

        print(
            f"PDF {index}/{total}"
        )

        print("#" * 78)

        relative_path = (
            pdf_path
            .relative_to(
                input_root
            )
        )

        print(
            "Folder:",
            (
                relative_path.parts[0]
                if relative_path.parts
                else "(root)"
            ),
        )

        print(
            "Source:",
            relative_path,
        )

        item_started = (
            time.monotonic()
        )

        actual_attempt = False

        try:

            outputs = build_output_paths(
                pdf_path,
                input_root,
                output_root,
            )

            already_complete = (
                outputs[
                    "json"
                ].exists()
                and
                outputs[
                    "txt"
                ].exists()
                and
                not args.force
            )

            if already_complete:

                result = {
                    "status":
                        "skipped",

                    "reason":
                        "already_complete",

                    "pdf":
                        str(
                            pdf_path
                        ),

                    "json":
                        str(
                            outputs[
                                "json"
                            ]
                        ),

                    "txt":
                        str(
                            outputs[
                                "txt"
                            ]
                        ),
                }

            else:

                actual_attempt = True

                result = process_pdf_with_retry(
                    pdf_path=pdf_path,
                    input_root=input_root,
                    output_root=output_root,
                    manifest_mapping=manifest_mapping,
                    gemini_model=args.gemini_model,
                    force=args.force,
                    force_gemini=args.force_gemini,
                )

            if (
                result.get(
                    "status"
                )
                == "skipped"
            ):

                skipped += 1

                print()
                print(
                    "STATUS: ALREADY COMPLETE → SKIP"
                )

            else:

                complete += 1

                native_pages += (
                    result.get(
                        "native_pages",
                        0,
                    )
                )

                gemini_pages += (
                    result.get(
                        "gemini_pages",
                        0,
                    )
                )

                if result.get(
                    "filename_shortened"
                ):

                    shortened_names += 1

                print()
                print(
                    "STATUS: COMPLETE"
                )

                print(
                    "Native pages:",
                    result.get(
                        "native_pages"
                    ),
                )

                print(
                    "Gemini pages:",
                    result.get(
                        "gemini_pages"
                    ),
                )

                print(
                    "Empty English pages:",
                    result.get(
                        "empty_pages"
                    ),
                )

                print(
                    "Filename shortened:",
                    result.get(
                        "filename_shortened"
                    ),
                )

                print(
                    "JSON:",
                    result.get(
                        "json"
                    ),
                )

                print(
                    "TXT:",
                    result.get(
                        "txt"
                    ),
                )

            append_conversion_manifest(
                output_root,
                result,
            )

        except KeyboardInterrupt:

            print()
            print(
                "Stopped by user."
            )

            outputs = build_output_paths(
                pdf_path,
                input_root,
                output_root,
            )

            if outputs[
                "checkpoint"
            ].exists():

                print(
                    (
                        "Current PDF checkpoint exists. "
                        "Rerun to resume."
                    )
                )

            else:

                print(
                    (
                        "No checkpoint exists for the "
                        "current unfinished page."
                    )
                )

            raise

        except Exception as exc:

            failed += 1

            print()
            print("=" * 78)

            print(
                "STATUS: FAILED AFTER ALL RETRIES"
            )

            print("=" * 78)

            print(
                "PDF:",
                relative_path,
            )

            print(
                "ERROR:",
                repr(
                    exc
                ),
            )

            append_conversion_manifest(
                output_root,
                {
                    "status":
                        "failed",

                    "pdf":
                        str(
                            pdf_path
                        ),

                    "error":
                        str(
                            exc
                        ),

                    "document_attempts":
                        DOCUMENT_MAX_ATTEMPTS,
                },
            )

        item_elapsed = (
            time.monotonic()
            - item_started
        )

        elapsed = (
            time.monotonic()
            - started
        )

        remaining = (
            total
            - index
        )

        average = (
            elapsed
            / index
        )

        eta = (
            average
            * remaining
        )

        eta += (
            DOCUMENT_CONVERSION_DELAY_SECONDS
            * remaining
        )

        print()
        print(
            (
                "[PROGRESS] "
                f"{index}/{total} "
                f"({index / total * 100:.1f}%) | "
                f"complete={complete} "
                f"skipped={skipped} "
                f"failed={failed} | "
                f"current={item_elapsed:.1f}s | "
                f"elapsed={elapsed / 60:.1f}m | "
                f"ETA≈{eta / 60:.1f}m"
            ),
            flush=True,
        )

        # ====================================================
        # DOCUMENT DELAY
        # ====================================================

        if (
            actual_attempt
            and
            index < total
        ):

            print()
            print(
                (
                    "[DOCUMENT DELAY] "
                    f"Waiting "
                    f"{DOCUMENT_CONVERSION_DELAY_SECONDS}s "
                    "before next PDF..."
                ),
                flush=True,
            )

            time.sleep(
                DOCUMENT_CONVERSION_DELAY_SECONDS
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    elapsed = (
        time.monotonic()
        - started
    )

    print()
    print("=" * 78)

    print(
        "CONVERSION RUN COMPLETE"
    )

    print("=" * 78)

    print(
        "PDFs selected:",
        total,
    )

    print(
        "Converted:",
        complete,
    )

    print(
        "Already complete / skipped:",
        skipped,
    )

    print(
        "Failed after retries:",
        failed,
    )

    print(
        "Native pages converted this run:",
        native_pages,
    )

    print(
        "Gemini pages converted this run:",
        gemini_pages,
    )

    print(
        "Long filenames safely shortened:",
        shortened_names,
    )

    print(
        "Runtime:",
        f"{elapsed / 60:.2f} minutes",
    )

    print(
        "Output:",
        output_root,
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "Conversion stopped."
        )

        sys.exit(
            130
        )