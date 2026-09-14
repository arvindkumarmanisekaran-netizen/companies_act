# Private database backend

This directory contains the server-side API and PostgreSQL schema for the private legal corpus.

The repository contains code and schema only. The private corpus, converted text, generated relationships, database contents, dumps, backups and real credentials must stay outside Git.

## 1. PostgreSQL

Create the database and application user on the private server:

```sql
CREATE USER companies_act_app WITH PASSWORD 'use-a-strong-password';
CREATE DATABASE companies_act OWNER companies_act_app;
```

Do not put the real password in GitHub.

## 2. Python environment

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Copy the environment template and edit it locally:

```bash
cp .env.example .env
```

Example private-server settings:

```env
DATABASE_URL=postgresql://companies_act_app:YOUR_PASSWORD@127.0.0.1:5432/companies_act
API_HOST=127.0.0.1
API_PORT=8000
API_CORS_ORIGINS=http://localhost:5173
LEGAL_CORPUS_ROOT=/srv/companies-act/private/converted-text
```

`.env` is ignored by Git.

## 3. Apply database schema

Run from the repository root so package imports are deterministic:

```bash
python -m backend.migrate
```

The initial migration creates:

- `legal_documents`
- `document_identifiers`
- `document_pages`
- `act_provisions`
- `provision_versions`
- `legal_relationships`
- `ingestion_runs`
- `ingestion_errors`

## 4. Validate the converted corpus without writing

```bash
python -m scripts.ingest_legal_corpus \
  --input-root /srv/companies-act/private/converted-text \
  --limit 10 \
  --dry-run
```

## 5. Ingest into PostgreSQL

Start with a small batch:

```bash
python -m scripts.ingest_legal_corpus \
  --input-root /srv/companies-act/private/converted-text \
  --limit 10
```

When the sample is validated, import the complete corpus:

```bash
python -m scripts.ingest_legal_corpus \
  --input-root /srv/companies-act/private/converted-text
```

The importer is idempotent for documents, page records, identifiers and document-to-section relationships. It records each run and any failed files in `ingestion_runs` and `ingestion_errors`.

The first version intentionally uses deterministic extraction for section references and document identifiers. Ambiguous relationships should be reviewed before AI-assisted enrichment is added.

## 6. Run the API

From the repository root:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Initial endpoints:

```text
GET /api/health
GET /api/documents/{document_id}
GET /api/sections/{section_number}
GET /api/sections/{section_number}/related
GET /api/search?q=...
```

For production, place the API behind the server's HTTPS reverse proxy. Do not expose PostgreSQL directly to the internet.

## Data boundary

The following must remain private and must never be committed:

```text
source PDFs for the private corpus
converted TXT/JSON corpus
private document metadata
extracted relationship datasets
database dumps/backups
.env files
real database/API credentials
```

The public repository may contain application code, database migrations, parsers and API contracts, but not the private corpus itself.
