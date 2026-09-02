"""Runtime fixes for resumable Gemini Companies Act parsing.

This launcher keeps checkpoint parsing resilient while preserving the existing
parser implementation. It normalizes harmless Gemini formatting variants in
section numbers, merges overlap duplicates globally before validation, and makes
empty structured responses fully retryable.
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


def merge_duplicate_sections_globally(chunks: list[dict]) -> None:
    """Merge duplicate sections even when Gemini assigns them to different chapters.

    Overlapping PDF batches occasionally repeat a section under the preceding or
    following chapter identity. The core parser only deduplicates inside one
    chapter, so merge those repeated section payloads before the normal chapter
    merge. The first occurrence keeps its chapter placement while all later legal
    text, subsections, clauses, amendment notes, and statuses are merged into it.
    """
    seen: dict[str, dict] = {}
    for chunk in chunks:
        for chapter in chunk.get("chapters", []):
            retained = []
            for section in chapter.get("sections", []):
                key = normalize_section_number(section.get("section_number", "")).upper()
                section["section_number"] = key
                if not key:
                    retained.append(section)
                    continue
                existing = seen.get(key)
                if existing is None:
                    seen[key] = section
                    retained.append(section)
                    continue
                parser._merge_sections([existing], [section])
            chapter["sections"] = retained


def merge_act_chunks_normalized(chunks: list[dict], doc_type: str) -> dict:
    normalize_chunk_section_numbers(chunks)
    merge_duplicate_sections_globally(chunks)
    return _ORIGINAL_MERGE_ACT_CHUNKS(chunks, doc_type)


def main() -> None:
    # An empty Gemini response is usually another transient capacity/output issue.
    # Give it the same full retry budget as 429/503 responses.
    if "NO STRUCTURED OUTPUT" not in checkpoint.TRANSIENT_MARKERS:
        checkpoint.TRANSIENT_MARKERS += ("NO STRUCTURED OUTPUT",)

    # Normalize section identifiers and globally merge overlap duplicates before
    # the core parser performs its normal chapter merge and validation.
    parser.merge_act_chunks = merge_act_chunks_normalized
    checkpoint.main()


if __name__ == "__main__":
    main()
