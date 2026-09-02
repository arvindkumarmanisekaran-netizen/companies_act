"""Checkpoint/resume wrapper for Gemini legal PDF parsing.

Successful act chunks are written to a persistent checkpoint directory so a
GitHub Actions retry can continue without re-sending already parsed pages.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

from scripts import ai_parse_legal_documents as parser


MAX_ATTEMPTS = int(os.getenv("GEMINI_MAX_RETRY_ATTEMPTS", "10"))
RETRY_BASE_SECONDS = float(os.getenv("GEMINI_RETRY_BASE_SECONDS", "5"))
RETRY_MAX_SECONDS = float(os.getenv("GEMINI_RETRY_MAX_SECONDS", "120"))
RETRY_JITTER_SECONDS = float(os.getenv("GEMINI_RETRY_JITTER_SECONDS", "5"))

TRANSIENT_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
    "high demand",
)


def checkpoint_key(page_start: int, page_end: int) -> str:
    return f"pages-{page_start:04d}-{page_end:04d}.json"


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def is_transient_error(error: Exception) -> bool:
    text = f"{type(error).__name__}: {error}".upper()
    return any(marker.upper() in text for marker in TRANSIENT_MARKERS)


def parse_response(client, pdf_path: Path, prompt: str, schema, system_prompt: str):
    from google.genai import types

    pdf_part = types.Part.from_bytes(
        data=pdf_path.read_bytes(),
        mime_type="application/pdf",
    )
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=parser.MODEL,
                contents=[pdf_part, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=65536,
                ),
            )
            if not response.text:
                raise RuntimeError(
                    f"Gemini returned no structured output for {pdf_path.name}"
                )
            return schema.model_validate_json(response.text)
        except Exception as error:
            last_error = error
            retryable = is_transient_error(error) or attempt < 3
            if attempt >= MAX_ATTEMPTS or not retryable:
                break
            exponential = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            delay = min(exponential, RETRY_MAX_SECONDS)
            delay += random.uniform(0, max(RETRY_JITTER_SECONDS, 0))
            print(
                f"Gemini request attempt {attempt}/{MAX_ATTEMPTS} failed; "
                f"retrying in {delay:.1f}s: {error}",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"Gemini failed to parse {pdf_path.name}") from last_error


def update_carry(parsed_chunk: dict, carry_chapter: str, carry_section: str):
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
    return carry_chapter, carry_section


def parse_act_with_checkpoints(
    client,
    pdf_path: Path,
    doc_type: str,
    checkpoint_dir: Path,
) -> dict:
    import tempfile

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="companies-act-ai-") as temp_dir:
        chunks = parser.split_pdf(pdf_path, Path(temp_dir))
        parsed_chunks = []
        carry_chapter = "not yet established"
        carry_section = "not yet established"

        for index, (chunk_path, page_start, page_end) in enumerate(chunks, start=1):
            checkpoint = checkpoint_dir / checkpoint_key(page_start, page_end)
            if checkpoint.exists():
                try:
                    parsed_chunk = json.loads(checkpoint.read_text(encoding="utf-8"))
                    parser.ParsedActChunk.model_validate(parsed_chunk)
                    parsed_chunk["doc_type"] = doc_type
                    parsed_chunks.append(parsed_chunk)
                    carry_chapter, carry_section = update_carry(
                        parsed_chunk, carry_chapter, carry_section
                    )
                    print(
                        f"Resuming {pdf_path.name}: batch {index}/{len(chunks)} "
                        f"(source pages {page_start}-{page_end}) from checkpoint",
                        flush=True,
                    )
                    continue
                except Exception as error:
                    print(
                        f"Ignoring invalid checkpoint {checkpoint.name}: {error}",
                        flush=True,
                    )
                    checkpoint.unlink(missing_ok=True)

            print(
                f"AI parsing {pdf_path.name}: batch {index}/{len(chunks)} "
                f"(source pages {page_start}-{page_end})",
                flush=True,
            )
            parsed = parse_response(
                client,
                chunk_path,
                (
                    f"This is {doc_type} source pages {page_start}-{page_end}. "
                    "Extract all visible Companies Act provisions into the schema. "
                    "Check every supplied page. "
                    f"The last chapter identified in the preceding batch was "
                    f"{carry_chapter}; the last section was {carry_section}. "
                    "If these pages begin mid-provision without repeating its "
                    "headings, use that carry-over identity. A heading visible in "
                    "this batch always takes precedence."
                ),
                parser.ParsedActChunk,
                parser.ACT_SYSTEM_PROMPT,
            )
            parsed.doc_type = doc_type
            parsed_chunk = parsed.model_dump(mode="json")
            atomic_write_json(checkpoint, parsed_chunk)
            parsed_chunks.append(parsed_chunk)
            carry_chapter, carry_section = update_carry(
                parsed_chunk, carry_chapter, carry_section
            )
            print(f"Checkpointed {checkpoint.name}", flush=True)

            if index < len(chunks) and parser.REQUEST_DELAY_SECONDS > 0:
                print(
                    f"Pacing Gemini requests for "
                    f"{parser.REQUEST_DELAY_SECONDS:g}s",
                    flush=True,
                )
                time.sleep(parser.REQUEST_DELAY_SECONDS)

    return parser.merge_act_chunks(parsed_chunks, doc_type)


def parse_amendment_with_checkpoint(
    client,
    pdf_path: Path,
    checkpoint_dir: Path,
) -> dict:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_dir / "amendment.json"
    if checkpoint.exists():
        try:
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            parsed = parser.ParsedAmendment.model_validate(payload)
            parser.validate_amendment(parsed, pdf_path)
            print(f"Resuming {pdf_path.name} from checkpoint", flush=True)
            return payload
        except Exception as error:
            print(
                f"Ignoring invalid checkpoint {checkpoint.name}: {error}",
                flush=True,
            )
            checkpoint.unlink(missing_ok=True)

    parsed = parse_response(
        client,
        pdf_path,
        "Extract every amendment operation in this Act. Check every page, including schedules.",
        parser.ParsedAmendment,
        parser.AMENDMENT_SYSTEM_PROMPT,
    )
    parser.validate_amendment(parsed, pdf_path)
    payload = parsed.model_dump(mode="json")
    atomic_write_json(checkpoint, payload)
    print(f"Checkpointed {checkpoint.name}", flush=True)
    return payload


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--source", type=Path, required=True)
    argument_parser.add_argument("--output", type=Path, required=True)
    argument_parser.add_argument("--checkpoint-dir", type=Path, required=True)
    args = argument_parser.parse_args()

    source = args.source.resolve()
    kind = parser.DOCUMENTS.get(source.name)
    if kind is None:
        raise ValueError(
            f"Unsupported source {source.name}; ordinances are intentionally excluded"
        )

    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    client = genai.Client(api_key=api_key)

    source_checkpoints = args.checkpoint_dir / parser.safe_stem(source)
    if kind == "amendment":
        parsed = parse_amendment_with_checkpoint(client, source, source_checkpoints)
    else:
        parsed = parse_act_with_checkpoints(
            client, source, kind, source_checkpoints
        )
    parser.write_source_output(source, kind, parsed, args.output)
    print(f"Wrote AI-parsed {kind} JSON to {args.output}")


if __name__ == "__main__":
    main()
