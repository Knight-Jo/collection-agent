"""SQLite boundary for conversational research state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .storage import ensure_intel_dirs

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_state (
    task_id TEXT PRIMARY KEY,
    current_committed_state_version INTEGER NOT NULL DEFAULT 0
        CHECK (current_committed_state_version >= 0),
    current_draft_report_version_id TEXT REFERENCES report_versions(id),
    current_published_report_version_id TEXT REFERENCES report_versions(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES task_state(task_id)
        ON DELETE CASCADE,
    active_epoch_id TEXT REFERENCES conversation_epochs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_epochs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id)
        ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    summary TEXT NOT NULL DEFAULT '',
    summary_through_sequence INTEGER NOT NULL DEFAULT 0
        CHECK (summary_through_sequence >= 0),
    summary_updated_at TEXT,
    started_at TEXT NOT NULL,
    archived_at TEXT,
    UNIQUE (conversation_id, sequence)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id)
        ON DELETE CASCADE,
    epoch_id TEXT NOT NULL REFERENCES conversation_epochs(id)
        ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    client_message_id TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'accepted', 'processing', 'completed', 'failed', 'cancelled'
    )),
    intent_json TEXT,
    reply_to_id TEXT REFERENCES messages(id),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    UNIQUE (conversation_id, sequence),
    CHECK (
        (role = 'user' AND client_message_id IS NOT NULL)
        OR
        (role = 'assistant' AND client_message_id IS NULL
            AND status = 'completed' AND reply_to_id IS NOT NULL
            AND completed_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS action_requests (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    trigger_message_id TEXT NOT NULL REFERENCES messages(id),
    action_type TEXT NOT NULL CHECK (action_type IN (
        'continue_research', 'search_gap', 'search_specific_topic',
        'modify_search_plan', 'generate_report', 'regenerate_report'
    )),
    immutable_payload_json TEXT NOT NULL,
    request_mode TEXT CHECK (
        request_mode IN ('explicit_message', 'confirmed_proposal')
    ),
    request_message_id TEXT REFERENCES messages(id),
    precondition_committed_state_version INTEGER NOT NULL
        CHECK (precondition_committed_state_version >= 0),
    precondition_search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    status TEXT NOT NULL CHECK (status IN (
        'proposed', 'queued', 'executing', 'succeeded', 'failed',
        'rejected', 'expired', 'cancelled'
    )),
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    queued_at TEXT,
    executing_at TEXT,
    completed_at TEXT,
    created_research_run_id TEXT REFERENCES research_runs(id),
    target_research_run_id TEXT REFERENCES research_runs(id),
    applied_search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    applied_checkpoint_id TEXT REFERENCES research_checkpoints(id),
    created_report_version_id TEXT REFERENCES report_versions(id),
    error TEXT,
    expires_at TEXT,
    CHECK (
        (status = 'proposed' AND request_mode IS NULL
            AND request_message_id IS NULL)
        OR
        (status != 'proposed' AND request_mode IS NOT NULL
            AND request_message_id IS NOT NULL)
    ),
    CHECK (
        action_type != 'modify_search_plan'
        OR precondition_search_plan_version_id IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    run_type TEXT NOT NULL CHECK (run_type IN (
        'initial', 'continue_research', 'retry', 'legacy_import'
    )),
    provenance TEXT NOT NULL DEFAULT 'native'
        CHECK (provenance IN ('native', 'migrated')),
    trigger_message_id TEXT REFERENCES messages(id),
    action_request_id TEXT REFERENCES action_requests(id),
    retry_of_run_id TEXT REFERENCES research_runs(id),
    input_committed_state_version INTEGER NOT NULL
        CHECK (input_committed_state_version >= 0),
    input_snapshot_json TEXT NOT NULL,
    initial_search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    active_search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled',
        'interrupted'
    )),
    phase TEXT CHECK (phase IN (
        'planning', 'collecting', 'assessing', 'checkpointing'
    )),
    outcome TEXT CHECK (outcome IN ('sufficient', 'with_gaps')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error TEXT,
    CHECK (run_type != 'retry' OR retry_of_run_id IS NOT NULL),
    CHECK (
        status NOT IN ('succeeded', 'failed', 'cancelled', 'interrupted')
        OR completed_at IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS search_plan_versions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    research_run_id TEXT NOT NULL REFERENCES research_runs(id)
        ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    plan_json TEXT NOT NULL,
    trigger_message_id TEXT REFERENCES messages(id),
    action_request_id TEXT REFERENCES action_requests(id),
    created_at TEXT NOT NULL,
    UNIQUE (research_run_id, sequence)
);

CREATE TABLE IF NOT EXISTS research_checkpoints (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    research_run_id TEXT NOT NULL REFERENCES research_runs(id)
        ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    input_committed_state_version INTEGER NOT NULL
        CHECK (input_committed_state_version >= 0),
    output_committed_state_version INTEGER CHECK (
        output_committed_state_version >= 0
    ),
    status TEXT NOT NULL CHECK (status IN (
        'started', 'committed', 'failed', 'cancelled'
    )),
    trigger_action_request_id TEXT REFERENCES action_requests(id),
    reason TEXT NOT NULL,
    started_at TEXT NOT NULL,
    committed_at TEXT,
    UNIQUE (research_run_id, sequence),
    CHECK (
        (status = 'committed' AND output_committed_state_version IS NOT NULL
            AND committed_at IS NOT NULL)
        OR
        (status != 'committed' AND output_committed_state_version IS NULL
            AND committed_at IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS report_versions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'draft', 'published', 'superseded', 'abandoned'
    )),
    content_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    based_on_committed_state_version INTEGER NOT NULL
        CHECK (based_on_committed_state_version >= 0),
    publication_origin TEXT NOT NULL DEFAULT 'native'
        CHECK (publication_origin IN ('native', 'legacy_migration')),
    created_at TEXT NOT NULL,
    published_at TEXT,
    abandoned_at TEXT,
    UNIQUE (task_id, version),
    CHECK (
        (status IN ('published', 'superseded') AND published_at IS NOT NULL)
        OR
        (status NOT IN ('published', 'superseded') AND published_at IS NULL)
    ),
    CHECK (
        (status = 'abandoned' AND abandoned_at IS NOT NULL)
        OR
        (status != 'abandoned' AND abandoned_at IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS conversation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id)
        ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    message_id TEXT REFERENCES messages(id),
    action_request_id TEXT REFERENCES action_requests(id),
    research_run_id TEXT REFERENCES research_runs(id),
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, sequence)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_epoch_per_conversation
ON conversation_epochs(conversation_id) WHERE archived_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS one_running_run_per_task
ON research_runs(task_id) WHERE status = 'running';

CREATE UNIQUE INDEX IF NOT EXISTS one_draft_report_per_task
ON report_versions(task_id) WHERE status = 'draft';

CREATE UNIQUE INDEX IF NOT EXISTS one_published_report_per_task
ON report_versions(task_id) WHERE status = 'published';

CREATE UNIQUE INDEX IF NOT EXISTS one_client_message_per_conversation
ON messages(conversation_id, client_message_id)
WHERE client_message_id IS NOT NULL;
"""


def state_db_path(cwd: Path) -> Path:
    """Return the local SQLite state database path."""
    return cwd / "data/intel/intel.db"


def connect_state_db(cwd: Path) -> sqlite3.Connection:
    """Open one SQLite connection with required safety settings."""
    ensure_intel_dirs(cwd)
    connection = sqlite3.connect(state_db_path(cwd), timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_state_db(cwd: Path) -> Path:
    """Create or upgrade the local state database idempotently."""
    path = state_db_path(cwd)
    with connect_state_db(cwd) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
    return path
