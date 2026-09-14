from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import close_pool, get_connection, open_pool

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="Companies Act Private Legal API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            row = cursor.fetchone()
    return {"status": "ok", "database": row["ok"] == 1}


@app.get("/api/documents/{document_id}")
def get_document(document_id: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, source_category, instrument_type, title,
                       publication_date, effective_date, source_file,
                       source_path, full_text, metadata
                FROM legal_documents
                WHERE id = %s
                """,
                (document_id,),
            )
            document = cursor.fetchone()

            if not document:
                raise HTTPException(status_code=404, detail="Document not found")

            cursor.execute(
                """
                SELECT identifier_type, identifier_value
                FROM document_identifiers
                WHERE document_id = %s
                ORDER BY identifier_type, identifier_value
                """,
                (document_id,),
            )
            identifiers = cursor.fetchall()

    document["identifiers"] = identifiers
    return document


@app.get("/api/sections/{section_number}")
def get_section(section_number: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, section_number, title, parent_id, provision_type,
                       current_text, status, metadata
                FROM act_provisions
                WHERE section_number = %s
                  AND provision_type = 'section'
                ORDER BY id
                LIMIT 1
                """,
                (section_number.upper(),),
            )
            section = cursor.fetchone()

    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@app.get("/api/sections/{section_number}/related")
def get_related_documents(section_number: str):
    target_id = f"act:companies-act-2013:section:{section_number.upper()}"

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.id AS relationship_id,
                       r.relationship_type,
                       r.confidence,
                       r.evidence,
                       d.id AS document_id,
                       d.instrument_type,
                       d.title,
                       d.publication_date
                FROM legal_relationships r
                JOIN legal_documents d
                  ON d.id = r.source_document_id
                WHERE r.target_provision_id = %s
                ORDER BY d.publication_date NULLS LAST, d.title
                """,
                (target_id,),
            )
            relationships = cursor.fetchall()

    return {"section": section_number.upper(), "relationships": relationships}


@app.get("/api/search")
def search(q: str = Query(min_length=2, max_length=200), limit: int = 25):
    limit = max(1, min(limit, 100))
    pattern = f"%{q}%"

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, instrument_type, title, publication_date
                FROM legal_documents
                WHERE title ILIKE %s OR full_text ILIKE %s
                ORDER BY publication_date DESC NULLS LAST, title
                LIMIT %s
                """,
                (pattern, pattern, limit),
            )
            documents = cursor.fetchall()

    return {"query": q, "results": documents}
