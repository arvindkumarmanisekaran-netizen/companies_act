"""Runtime fixes for resumable Gemini Companies Act parsing.

This launcher keeps checkpoint parsing resilient while preserving the existing
parser implementation. It normalizes harmless Gemini formatting variants in
section numbers before merge/validation and makes empty structured responses
fully retryable.
"""

from __future__ import annotations

import re

from scripts import ai_parse_legal_documents as parser
from scripts import ai_parse_with_checkpoint as checkpoint


_ORIGINAL_MERGE_ACT_CHUNKS = parser.merge_act_chunks


def normalize_section_number(value: object) -> str:
    """Normalize AI formatting such as 378-I -> 378I and 378Z-O -> 378ZO."""
    number = str(value).strip()
    number = re.sub(
        r"(?<=[A-Za-z0-9])(?:\s*-\s*|\s+)(?=[A-Za-z])",
        "",
        number,
    )
    return number


def normalize_chunk_section_numbers(chunks: list[dict]) -> None:
    for chunk in chunks:
        for chapter in chunk.get("chapters", []):
            for section in chapter.get("sections", []):
                section["section_number"] = normalize_section_number(
                    section.get("section_number", "")
                )


def merge_act_chunks_normalized(chunks: list[dict], doc_type: str) -> dict:
    normalize_chunk_section_numbers(chunks)
    return _ORIGINAL_MERGE_ACT_CHUNKS(chunks, doc_type)


def main() -> None:
    # An empty Gemini response is usually another transient capacity/output issue.
    # Give it the same full retry budget as 429/503 responses.
    if "NO STRUCTURED OUTPUT" not in checkpoint.TRANSIENT_MARKERS:
        checkpoint.TRANSIENT_MARKERS += ("NO STRUCTURED OUTPUT",)

    # Normalize section identifiers before deduplication and validation so legal
    # sections such as 378I/378ZI are not rejected solely due to AI hyphenation.
    parser.merge_act_chunks = merge_act_chunks_normalized
    checkpoint.main()


if __name__ == "__main__":
    main()
