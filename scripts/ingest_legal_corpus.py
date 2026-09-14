#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from backend.app.config import get_settings

ACT_SECTION_PREFIX = "act:companies-act-2013:section:"

SECTION_RE = re.compile(
    r"\b(?:section|sections|sec\.?)[\s:]*([0-9]{1,3}[A-Z]?)\b",
    re.IGNORECASE,
)
GSR_RE = re.compile(r"\bG\.?\s*S\.?\s*R\.?\s*([0-9]+)\s*\(E\)", re.IGNORECASE)
SO_RE = re.compile(r"\bS\.?\s*O\.?\s*([0-9]+)\s*\(E\)", re.IGNORECASE)
CIRCULAR_RE = re.compile(
    r"\bGeneral\s+Circular\s+(?:No\.?\s*)?([0-9]+\s*/\s*[0-9]{4})",
    re.IGNORECASE,
)
GAZETTE_RE = re.compile(r"\bCG-[A-Z]{2}-E-[0-9]{8}-[0-9]+\b", re.IGNORECASE)
FORM_RE = re.compile(
    r"\b(?:Form\s+(?:No\.?\s*)?)"
    r"((?:INC|MGT|AOC|ADT|CRA|DIR|DPT|FC|CAA|NCLT|NFRA|PAS|GNL|MSME)[-\s]?[0-9A-Z]+)\b",
    re.IGNORECASE,
)
STANDARD_RE = re.compile(r"\b(Ind\s+AS|AS)\s*[-–:]?\s*([0-9]{1,3})\b", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+-\s+")


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slug(value) -> str:
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = clean(value)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def source_category(relative_path: str) -> str:
    parts = Path(relative_path).parts
    return parts[0] if len(parts) > 1 else "root"


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = DATE_PREFIX_RE.sub("", stem)
    return clean(stem)


def classify_instrument(title: str, text: str, category: str) -> str:
    sample = f"{title}\n{text[:12000]}".lower()
    category_l = category.lower()

    if "companies (amendment) ordinance" in sample or "companies amendment ordinance" in sample:
        return "amendment_ordinance"
    if re.search(r"companies\s*\(amendment\)\s*act", sample):
        return "amendment_act"
    if "removal of difficulties" in sample and "order" in sample:
        return "removal_of_difficulties_order"
    if "corrigendum" in sample or "corrigenda" in sample:
        return "corrigendum"
    if "commencement" in sample and ("notification" in sample or "appoints" in sample):
        return "commencement_notification"
    if "amendment rules" in sample:
        return "amendment_rules"
    if "general circular" in sample or "circular" in category_l:
        return "circular"
    if "accounting standard" in category_l or re.search(r"\b(?:ind\s+as|as)\s*\d+\b", title, re.I):
        return "accounting_standard"
    if "forms" in category_l or FORM_RE.search(sample):
        return "form"
    if "regulation" in sample:
        return "regulation"
    if "order" in sample or "orders" in category_l:
        return "order"
    if "gazette" in category_l:
        return "gazette_notification"
    if "notification" in category_l or "notification" in sample:
        return "notification"
    if "rules" in category_l or "rules, 20" in sample:
        return "rules"
    return "legal_document"


def canonical_document_id(data: dict, relative_path: str, title: str, instrument_type: str) -> str:
    raw_id = clean(data.get("document_id"))
    id_source = clean(data.get("document_id_source"))
    if raw_id and id_source != "filename_stem_fallback":
        return f"{instrument_type}:mca:{slug(raw_id)}"

    source = data.get("source") or {}
    raw_source_id = clean(source.get("document_id") or source.get("id"))
    if raw_source_id:
        return f"{instrument_type}:mca:{slug(raw_source_id)}"

    digest = hashlib.sha1(f"{relative_path}|{title}".encode("utf-8")).hexdigest()[:16]
    return f"{instrument_type}:{slug(source_category(relative_path))}:{digest}"


def relationship_type(context: str, instrument_type: str) -> str:
    c = context.lower()
    if re.search(r"\bsubstitut\w*\b", c):
        return "substitutes"
    if re.search(r"\binsert\w*\b", c):
        return "inserts"
    if re.search(r"\bomit\w*\b", c):
        return "omits"
    if re.search(r"\b(?:amend|amended|replace)\w*\b", c):
        return "amends"
    if re.search(r"\b(?:come into force|commencement|appoints? .* date)\b", c):
        return "commences"
    if "in exercise of the powers conferred" in c or "pursuant to section" in c or "under section" in c:
        return "issued_under"
    if "clarif" in c or (instrument_type == "circular" and "attention" in c):
        return "clarifies"
    if "supersed" in c:
        return "supersedes"
    if "in continuation of" in c:
        return "continues"
    if "corrigend" in c:
        return "corrects"
    return "references"


def extract_identifiers(text: str, title: str):
    haystack = f"{title}\n{text[:30000]}"
    values = []
    values.extend(("gsr", f"G.S.R. {m}(E)") for m in GSR_RE.findall(haystack))
    values.extend(("so", f"S.O. {m}(E)") for m in SO_RE.findall(haystack))
    values.extend(("circular", clean(m).replace(" ", "")) for m in CIRCULAR_RE.findall(haystack))
    values.extend(("gazette_id", m.upper()) for m in GAZETTE_RE.findall(haystack))
    values.extend(("form", clean(m).upper().replace(" ", "-")) for m in FORM_RE.findall(haystack))
    values.extend(
        ("accounting_standard", f"{clean(kind)} {number}")
        for kind, number in STANDARD_RE.findall(haystack)
    )
    return sorted(set(values))


def extract_section_relationships(text: str, instrument_type: str):
    relationships = {}
    for match in SECTION_RE.finditer(text):
        number = match.group(1).upper()
        start = max(0, match.start() - 260)
        end = min(len(text), match.end() + 260)
        context = text[start:end]
        rel_type = relationship_type(context, instrument_type)
        snippet = clean(context)[:700]
        relationships.setdefault(
            (number, rel_type),
            {
                "section_number": number,
                "relationship_type": rel_type,
                "evidence": {"snippet": snippet},
            },
        )
    return list(relationships.values())


def normalize_pages(data: dict):
    pages = data.get("pages") or []
    normalized = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_number = page.get("page") or page.get("page_number") or index
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            page_number = index
        normalized.append(
            {
                "page_number": page_number,
                "text": page.get("text") or "",
                "method": page.get("method") or page.get("extraction_method"),
                "requires_review": bool(page.get("requires_review", False)),
                "metadata": {
                    key: value
                    for key, value in page.items()
                    if key not in {"page", "page_number", "text", "method", "extraction_method", "requires_review"}
                },
            }
        )
    return normalized


def load_document(path: Path, input_root: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")

    pages = normalize_pages(data)
    full_text = data.get("full_text") or "\n\n".join(page["text"] for page in pages if page["text"])
    source = data.get("source") or {}

    filename = source.get("filename") or f"{path.stem}.pdf"
    relative_path = source.get("relative_path") or str(path.relative_to(input_root).with_suffix(".pdf"))
    category = source_category(relative_path)
    title = clean(data.get("title")) or title_from_filename(filename)
    instrument_type = clean(data.get("instrument_type")) or classify_instrument(title, full_text, category)
    document_id = canonical_document_id(data, relative_path, title, instrument_type)

    filename_date = DATE_PREFIX_RE.match(Path(filename).stem)
    publication_date = (
        parse_date(data.get("publication_date"))
        or parse_date(source.get("publication_date"))
        or (parse_date(filename_date.group(1)) if filename_date else None)
    )

    extraction = data.get("extraction") or {}
    metadata = {
        "schema_source": "converted_pdf_json",
        "source_json": str(path.relative_to(input_root)),
        "extraction": extraction,
    }

    return {
        "id": document_id,
        "source_category": category,
        "instrument_type": instrument_type,
        "title": title,
        "publication_date": publication_date,
        "effective_date": parse_date(data.get("effective_date")),
        "enactment_date": parse_date(data.get("enactment_date")),
        "source_file": filename,
        "source_path": relative_path,
        "source_url": source.get("url") or source.get("document_url"),
        "full_text": full_text,
        "metadata": metadata,
        "pages": pages,
        "identifiers": extract_identifiers(full_text, title),
        "relationships": extract_section_relationships(full_text, instrument_type),
    }


def upsert_document(connection, document: dict):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO legal_documents (
                id, source_category, instrument_type, title,
                publication_date, effective_date, enactment_date,
                source_file, source_path, source_url, full_text, metadata
            ) VALUES (
                %(id)s, %(source_category)s, %(instrument_type)s, %(title)s,
                %(publication_date)s, %(effective_date)s, %(enactment_date)s,
                %(source_file)s, %(source_path)s, %(source_url)s, %(full_text)s, %(metadata)s
            )
            ON CONFLICT (id) DO UPDATE SET
                source_category = EXCLUDED.source_category,
                instrument_type = EXCLUDED.instrument_type,
                title = EXCLUDED.title,
                publication_date = EXCLUDED.publication_date,
                effective_date = EXCLUDED.effective_date,
                enactment_date = EXCLUDED.enactment_date,
                source_file = EXCLUDED.source_file,
                source_path = EXCLUDED.source_path,
                source_url = EXCLUDED.source_url,
                full_text = EXCLUDED.full_text,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """,
            {**document, "metadata": Jsonb(document["metadata"])},
        )

        for identifier_type, identifier_value in document["identifiers"]:
            cursor.execute(
                """
                INSERT INTO document_identifiers (document_id, identifier_type, identifier_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (document_id, identifier_type, identifier_value) DO NOTHING
                """,
                (document["id"], identifier_type, identifier_value),
            )

        for page in document["pages"]:
            cursor.execute(
                """
                INSERT INTO document_pages (
                    document_id, page_number, text, extraction_method, requires_review, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, page_number) DO UPDATE SET
                    text = EXCLUDED.text,
                    extraction_method = EXCLUDED.extraction_method,
                    requires_review = EXCLUDED.requires_review,
                    metadata = EXCLUDED.metadata
                """,
                (
                    document["id"],
                    page["page_number"],
                    page["text"],
                    page["method"],
                    page["requires_review"],
                    Jsonb(page["metadata"]),
                ),
            )

        for relationship in document["relationships"]:
            section_number = relationship["section_number"]
            provision_id = f"{ACT_SECTION_PREFIX}{section_number}"

            cursor.execute(
                """
                INSERT INTO act_provisions (
                    id, provision_type, section_number, label, status, sort_key, metadata
                ) VALUES (%s, 'section', %s, %s, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    provision_id,
                    section_number,
                    f"Section {section_number}",
                    section_number.zfill(6),
                    Jsonb({"placeholder": True}),
                ),
            )

            cursor.execute(
                """
                INSERT INTO legal_relationships (
                    source_document_id, relationship_type, target_provision_id,
                    confidence, evidence, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    document["id"],
                    relationship["relationship_type"],
                    provision_id,
                    0.75,
                    Jsonb(relationship["evidence"]),
                    Jsonb({"extraction": "deterministic_regex"}),
                ),
            )


def discover_json_files(input_root: Path):
    for path in sorted(input_root.rglob("*.json")):
        if path.name.endswith(".partial.json"):
            continue
        if path.name in {"conversion_manifest.json", "conversion_manifest.jsonl"}:
            continue
        yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest private converted legal corpus JSON into PostgreSQL")
    parser.add_argument("--input-root", type=Path, help="Converted corpus root. Defaults to LEGAL_CORPUS_ROOT.")
    parser.add_argument("--limit", type=int, default=0, help="Import at most N documents; 0 means all.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing to PostgreSQL.")
    args = parser.parse_args()

    settings = get_settings()
    default_root = Path(__import__("os").environ.get("LEGAL_CORPUS_ROOT", "scripts/mca_companies_act_2013_text"))
    input_root = (args.input_root or default_root).expanduser().resolve()

    if not input_root.exists():
        raise SystemExit(f"Input root does not exist: {input_root}")

    paths = list(discover_json_files(input_root))
    if args.limit > 0:
        paths = paths[: args.limit]

    print(f"Input root: {input_root}")
    print(f"Documents discovered: {len(paths)}")

    if args.dry_run:
        failures = 0
        for index, path in enumerate(paths, start=1):
            try:
                document = load_document(path, input_root)
                print(f"[{index}/{len(paths)}] {document['id']} | {document['instrument_type']} | {document['title']}")
            except Exception as exc:
                failures += 1
                print(f"[FAILED] {path}: {exc}")
        print(f"Dry run complete. Failures: {failures}")
        return 1 if failures else 0

    with psycopg.connect(settings.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ingestion_runs (source_root, documents_seen, metadata)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (str(input_root), len(paths), Jsonb({"started_by": "scripts/ingest_legal_corpus.py"})),
            )
            run_id = cursor.fetchone()[0]
        connection.commit()

        imported = 0
        failed = 0

        for index, path in enumerate(paths, start=1):
            try:
                document = load_document(path, input_root)
                upsert_document(connection, document)
                connection.commit()
                imported += 1
                print(f"[{index}/{len(paths)}] imported {document['id']}")
            except Exception as exc:
                connection.rollback()
                failed += 1
                print(f"[{index}/{len(paths)}] FAILED {path}: {exc}")
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO ingestion_errors (run_id, source_path, error_type, error_message)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (run_id, str(path), type(exc).__name__, str(exc)[:4000]),
                    )
                connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingestion_runs
                SET completed_at = %s,
                    status = %s,
                    documents_imported = %s,
                    documents_failed = %s
                WHERE id = %s
                """,
                (
                    datetime.now(timezone.utc),
                    "completed" if failed == 0 else "completed_with_errors",
                    imported,
                    failed,
                    run_id,
                ),
            )
        connection.commit()

    print("\nIngestion complete")
    print(f"  imported: {imported}")
    print(f"  failed:   {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
