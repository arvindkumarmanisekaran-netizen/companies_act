BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legal_documents (
    id TEXT PRIMARY KEY,
    source_category TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    title TEXT NOT NULL,
    publication_date DATE,
    effective_date DATE,
    enactment_date DATE,
    source_file TEXT,
    source_path TEXT,
    source_url TEXT,
    full_text TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legal_documents_type
    ON legal_documents (instrument_type);
CREATE INDEX IF NOT EXISTS idx_legal_documents_publication_date
    ON legal_documents (publication_date);
CREATE INDEX IF NOT EXISTS idx_legal_documents_title_lower
    ON legal_documents (LOWER(title));

CREATE TABLE IF NOT EXISTS document_identifiers (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    UNIQUE (document_id, identifier_type, identifier_value)
);

CREATE INDEX IF NOT EXISTS idx_document_identifiers_value
    ON document_identifiers (identifier_type, identifier_value);

CREATE TABLE IF NOT EXISTS document_pages (
    document_id TEXT NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    text TEXT NOT NULL DEFAULT '',
    extraction_method TEXT,
    requires_review BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS act_provisions (
    id TEXT PRIMARY KEY,
    act_id TEXT NOT NULL DEFAULT 'act:companies-act-2013',
    provision_type TEXT NOT NULL,
    section_number TEXT,
    label TEXT,
    title TEXT,
    parent_id TEXT REFERENCES act_provisions(id) ON DELETE CASCADE,
    current_text TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    sort_key TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_act_provisions_section
    ON act_provisions (section_number);
CREATE INDEX IF NOT EXISTS idx_act_provisions_parent
    ON act_provisions (parent_id);

CREATE TABLE IF NOT EXISTS provision_versions (
    id BIGSERIAL PRIMARY KEY,
    provision_id TEXT NOT NULL REFERENCES act_provisions(id) ON DELETE CASCADE,
    valid_from DATE,
    valid_to DATE,
    text TEXT,
    status TEXT,
    source_document_id TEXT REFERENCES legal_documents(id) ON DELETE SET NULL,
    change_type TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provision_versions_provision
    ON provision_versions (provision_id, valid_from);

CREATE TABLE IF NOT EXISTS legal_relationships (
    id BIGSERIAL PRIMARY KEY,
    source_document_id TEXT REFERENCES legal_documents(id) ON DELETE CASCADE,
    source_provision_id TEXT REFERENCES act_provisions(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    target_document_id TEXT REFERENCES legal_documents(id) ON DELETE CASCADE,
    target_provision_id TEXT REFERENCES act_provisions(id) ON DELETE CASCADE,
    target_external_id TEXT,
    confidence NUMERIC(5,4),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT legal_relationship_source_present CHECK (
        source_document_id IS NOT NULL OR source_provision_id IS NOT NULL
    ),
    CONSTRAINT legal_relationship_target_present CHECK (
        target_document_id IS NOT NULL OR target_provision_id IS NOT NULL OR target_external_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_legal_relationships_source_document
    ON legal_relationships (source_document_id);
CREATE INDEX IF NOT EXISTS idx_legal_relationships_target_document
    ON legal_relationships (target_document_id);
CREATE INDEX IF NOT EXISTS idx_legal_relationships_target_provision
    ON legal_relationships (target_provision_id);
CREATE INDEX IF NOT EXISTS idx_legal_relationships_type
    ON legal_relationships (relationship_type);

CREATE UNIQUE INDEX IF NOT EXISTS uq_relationship_document_to_provision
    ON legal_relationships (source_document_id, relationship_type, target_provision_id)
    WHERE source_document_id IS NOT NULL AND target_provision_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    source_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    documents_seen INTEGER NOT NULL DEFAULT 0,
    documents_imported INTEGER NOT NULL DEFAULT 0,
    documents_failed INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ingestion_errors (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    source_path TEXT,
    error_type TEXT,
    error_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version)
VALUES ('001_initial_schema')
ON CONFLICT (version) DO NOTHING;

COMMIT;
