PRAGMA foreign_keys = ON;

CREATE TABLE resources (
    resource_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    content_ref TEXT NOT NULL,
    byte_length INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    requested_url TEXT,
    final_url TEXT,
    local_display_name TEXT,
    acquired_at TEXT NOT NULL,
    parent_resource_id TEXT,
    transform TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX resources_hash ON resources(content_hash);

CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    aliases TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE revisions (
    revision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    content_hash TEXT NOT NULL,
    resource_id TEXT NOT NULL REFERENCES resources(resource_id),
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX revision_identity ON revisions(document_id, content_hash);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
    document_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    extraction_profile_id TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    language TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX artifact_identity
    ON artifacts(revision_id, extraction_profile_id, normalizer_version, manifest_hash);

CREATE TABLE provenance (
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    document_id TEXT NOT NULL,
    provider TEXT,
    query_id TEXT,
    original_url TEXT,
    channel TEXT,
    observed_at TEXT
);
CREATE INDEX provenance_artifact ON provenance(artifact_id);

CREATE TABLE blocks (
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    block_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (artifact_id, block_id)
);

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    chunk_profile_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX chunk_identity ON chunks(artifact_id, chunk_profile_id, ordinal);
CREATE INDEX chunks_artifact ON chunks(artifact_id);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    round INTEGER NOT NULL DEFAULT 0,
    budget_used TEXT NOT NULL DEFAULT '{}',
    checkpoint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deadline_at TEXT
);

CREATE TABLE work_items (
    work_item_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    artifact_id TEXT,
    resource_id TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    attempt INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX work_items_task ON work_items(task_id);

CREATE TABLE task_materials (
    task_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX task_artifact_identity ON task_materials(task_id, artifact_id);
CREATE INDEX task_materials_task ON task_materials(task_id);

CREATE TABLE scopes (
    scope_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE scope_artifacts (
    scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
    artifact_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL
);
CREATE INDEX scope_artifacts_scope ON scope_artifacts(scope_id);

CREATE TABLE index_jobs (
    artifact_id TEXT NOT NULL,
    chunk_profile_id TEXT NOT NULL,
    embedding_profile_id TEXT,
    lexical_status TEXT NOT NULL DEFAULT 'pending',
    vector_status TEXT NOT NULL DEFAULT 'pending',
    lexical_error TEXT,
    vector_error TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, chunk_profile_id)
);

CREATE TABLE attempts (
    work_item_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    unit_key TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    PRIMARY KEY (work_item_id, stage, unit_key, attempt)
);

CREATE TABLE budget_reservations (
    reservation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE chunk_terms (
    chunk_id TEXT NOT NULL,
    term TEXT NOT NULL,
    PRIMARY KEY (chunk_id, term)
);
CREATE INDEX chunk_terms_term ON chunk_terms(term);

