-- Workspace extensions: task kinds, execution timeline, idempotency,
-- monitors, fact checks, and media jobs (spec 002).

ALTER TABLE tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'research';
ALTER TABLE tasks ADD COLUMN phase TEXT;
ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN error TEXT;
ALTER TABLE tasks ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0;

CREATE TABLE task_timeline (
    entry_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX task_timeline_seq ON task_timeline(task_id, sequence);

CREATE TABLE idempotency (
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    result_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (operation, idempotency_key)
);

CREATE TABLE config_revisions (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT NOT NULL
);

CREATE TABLE monitors (
    monitor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    strategy TEXT NOT NULL,
    questions TEXT NOT NULL DEFAULT '[]',
    websites TEXT NOT NULL DEFAULT '[]',
    schedule TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    config_version INTEGER NOT NULL DEFAULT 1,
    baseline_run_id TEXT,
    active_run_id TEXT,
    next_run_at TEXT,
    last_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE monitor_runs (
    run_id TEXT PRIMARY KEY,
    monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
    trigger TEXT NOT NULL,
    scheduled_for TEXT,
    input_snapshot TEXT NOT NULL DEFAULT '{}',
    baseline_run_id TEXT,
    initial_baseline INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '[]'
);
CREATE UNIQUE INDEX monitor_scheduled ON monitor_runs(monitor_id, scheduled_for)
    WHERE scheduled_for IS NOT NULL;
CREATE INDEX monitor_runs_monitor ON monitor_runs(monitor_id);

CREATE TABLE monitor_fact_versions (
    fact_version_id TEXT PRIMARY KEY,
    monitor_id TEXT NOT NULL,
    created_run_id TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    predicate TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '{}',
    value TEXT NOT NULL DEFAULT '{}',
    statement TEXT NOT NULL,
    previous_version_id TEXT,
    citations TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX monitor_fact_versions_key
    ON monitor_fact_versions(monitor_id, fact_key);

CREATE TABLE monitor_baseline_facts (
    run_id TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    fact_version_id TEXT NOT NULL,
    PRIMARY KEY (run_id, fact_key)
);

CREATE TABLE monitor_baseline_sources (
    run_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    PRIMARY KEY (run_id, source_key)
);

CREATE TABLE monitor_changes (
    change_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    previous_version_id TEXT,
    current_version_id TEXT,
    source_key TEXT,
    citation TEXT,
    importance TEXT NOT NULL DEFAULT 'normal',
    importance_reason TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX monitor_changes_run ON monitor_changes(run_id);

CREATE TABLE fact_checks (
    fact_check_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
    claim TEXT NOT NULL,
    input_snapshot TEXT NOT NULL DEFAULT '{}',
    understanding TEXT NOT NULL DEFAULT '',
    questions TEXT NOT NULL DEFAULT '[]',
    checkability TEXT NOT NULL DEFAULT 'pending',
    checkability_reason TEXT,
    verdict TEXT,
    evidence_sufficiency TEXT,
    rationale TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '[]',
    independent_sources INTEGER NOT NULL DEFAULT 0,
    primary_sources INTEGER NOT NULL DEFAULT 0,
    counter_evidence INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE fact_evidence (
    evidence_id TEXT PRIMARY KEY,
    fact_check_id TEXT NOT NULL REFERENCES fact_checks(fact_check_id),
    relation TEXT NOT NULL,
    quote TEXT NOT NULL,
    citation TEXT NOT NULL,
    publisher_key TEXT,
    independence_group TEXT,
    source_nature TEXT NOT NULL DEFAULT 'unknown',
    attribution_basis TEXT NOT NULL DEFAULT '',
    source_title TEXT NOT NULL DEFAULT ''
);
CREATE INDEX fact_evidence_check ON fact_evidence(fact_check_id);

CREATE TABLE media_jobs (
    media_job_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
    resource_id TEXT NOT NULL,
    artifact_id TEXT,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    input_snapshot TEXT NOT NULL DEFAULT '{}',
    summary TEXT,
    limitations TEXT NOT NULL DEFAULT '[]',
    coverage TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE media_facts (
    fact_id TEXT PRIMARY KEY,
    media_job_id TEXT NOT NULL REFERENCES media_jobs(media_job_id),
    statement TEXT NOT NULL,
    segment_ids TEXT NOT NULL DEFAULT '[]',
    verification_status TEXT NOT NULL DEFAULT 'unverified'
);
CREATE INDEX media_facts_job ON media_facts(media_job_id);

CREATE TABLE media_evidence (
    evidence_id TEXT PRIMARY KEY,
    media_job_id TEXT NOT NULL REFERENCES media_jobs(media_job_id),
    fact_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    block_span TEXT NOT NULL,
    locator TEXT NOT NULL DEFAULT '{}',
    quote TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'mentions'
);
CREATE INDEX media_evidence_job ON media_evidence(media_job_id);
