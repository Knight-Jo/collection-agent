"""SQLite boundary for conversational research state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .storage import ensure_intel_dirs

SCHEMA_VERSION = 7

SCHEMA_V1 = """
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
        (status IN ('rejected', 'expired')
            AND request_mode IS NULL AND request_message_id IS NULL)
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

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS message_citations (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    citation_kind TEXT NOT NULL CHECK (
        citation_kind IN ('verified_evidence', 'material_clue')
    ),
    document_id TEXT NOT NULL,
    evidence_id TEXT,
    fact_id TEXT,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    quote_text TEXT NOT NULL,
    line_start INTEGER NOT NULL CHECK (line_start >= 1),
    line_end INTEGER NOT NULL CHECK (line_end >= line_start),
    source_content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (message_id, sequence),
    UNIQUE (
        message_id, citation_kind, document_id, line_start, line_end
    )
);

CREATE TABLE IF NOT EXISTS task_committed_assets (
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (
        asset_type IN (
            'document', 'fact', 'evidence', 'review', 'conflict', 'coverage',
            'material_digest', 'task_revision'
        )
    ),
    asset_id TEXT NOT NULL,
    committed_state_version INTEGER NOT NULL
        CHECK (committed_state_version >= 0),
    PRIMARY KEY (task_id, asset_type, asset_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_assets (
    checkpoint_id TEXT NOT NULL REFERENCES research_checkpoints(id)
        ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (
        asset_type IN (
            'document', 'fact', 'evidence', 'review', 'conflict', 'coverage',
            'material_digest', 'task_revision'
        )
    ),
    asset_id TEXT NOT NULL,
    PRIMARY KEY (checkpoint_id, asset_type, asset_id)
);
"""

SCHEMA_V3 = """
ALTER TABLE task_state ADD COLUMN task_json TEXT;
ALTER TABLE task_state ADD COLUMN origin_message_id TEXT;

CREATE UNIQUE INDEX task_origin_message
ON task_state(origin_message_id) WHERE origin_message_id IS NOT NULL;

CREATE TABLE conversations_v3 (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES task_state(task_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'intake'
        CHECK (status IN ('intake', 'active', 'archived')),
    title TEXT NOT NULL DEFAULT '新对话',
    active_epoch_id TEXT REFERENCES conversation_epochs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (status != 'active' OR task_id IS NOT NULL)
);

INSERT INTO conversations_v3(
    id, task_id, status, title, active_epoch_id, created_at, updated_at
)
SELECT id, task_id, 'active', '历史调研', active_epoch_id, created_at, updated_at
FROM conversations;

DROP TABLE conversations;
ALTER TABLE conversations_v3 RENAME TO conversations;

CREATE TABLE research_runs_v3 (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    run_type TEXT NOT NULL CHECK (run_type IN (
        'initial', 'continue_research', 'retry', 'legacy_import'
    )),
    provenance TEXT NOT NULL DEFAULT 'native'
        CHECK (provenance IN ('native', 'migrated')),
    trigger_message_id TEXT REFERENCES messages(id),
    action_request_id TEXT REFERENCES action_requests(id),
    retry_of_run_id TEXT REFERENCES research_runs_v3(id),
    input_committed_state_version INTEGER NOT NULL
        CHECK (input_committed_state_version >= 0),
    input_snapshot_json TEXT NOT NULL,
    initial_search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    active_search_plan_version_id TEXT REFERENCES search_plan_versions(id),
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'stopping', 'stopped', 'succeeded', 'failed',
        'cancelled', 'interrupted'
    )),
    phase TEXT CHECK (phase IN (
        'planning', 'collecting', 'assessing', 'checkpointing'
    )),
    outcome TEXT CHECK (outcome IN ('sufficient', 'with_gaps')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    error TEXT,
    CHECK (run_type != 'retry' OR retry_of_run_id IS NOT NULL),
    CHECK (
        status NOT IN (
            'stopped', 'succeeded', 'failed', 'cancelled', 'interrupted'
        ) OR completed_at IS NOT NULL
    )
);

INSERT INTO research_runs_v3(
    id, task_id, run_type, provenance, trigger_message_id,
    action_request_id, retry_of_run_id, input_committed_state_version,
    input_snapshot_json, initial_search_plan_version_id,
    active_search_plan_version_id, status, phase, outcome, created_at,
    started_at, completed_at, error
)
SELECT id, task_id, run_type, provenance, trigger_message_id,
    action_request_id, retry_of_run_id, input_committed_state_version,
    input_snapshot_json, initial_search_plan_version_id,
    active_search_plan_version_id, status, phase, outcome, created_at,
    started_at, completed_at, error
FROM research_runs;

DROP TABLE research_runs;
ALTER TABLE research_runs_v3 RENAME TO research_runs;

ALTER TABLE report_versions ADD COLUMN based_on_checkpoint_id TEXT
    REFERENCES research_checkpoints(id);

CREATE TABLE research_briefs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id)
        ON DELETE CASCADE,
    trigger_message_id TEXT NOT NULL UNIQUE REFERENCES messages(id),
    task_id TEXT UNIQUE REFERENCES task_state(task_id),
    schema_version TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE message_processing_attempts (
    id TEXT PRIMARY KEY,
    user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'accepted', 'processing', 'completed', 'failed', 'cancelled'
    )),
    assistant_message_id TEXT REFERENCES messages(id),
    error_code TEXT,
    error_detail TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (user_message_id, attempt)
);

CREATE TABLE timeline_entries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id)
        ON DELETE CASCADE,
    timeline_sequence INTEGER NOT NULL CHECK (timeline_sequence >= 1),
    source_event_sequence INTEGER,
    entry_type TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, timeline_sequence)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_epoch_per_conversation
ON conversation_epochs(conversation_id) WHERE archived_at IS NULL;

CREATE UNIQUE INDEX one_running_run_per_task
ON research_runs(task_id) WHERE status IN ('running', 'stopping');
"""

SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS committed_snapshots (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 0),
    checkpoint_id TEXT REFERENCES research_checkpoints(id),
    asset_manifest_json TEXT NOT NULL DEFAULT '[]',
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (task_id, version)
);

CREATE TABLE IF NOT EXISTS run_workspaces (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    base_version INTEGER NOT NULL CHECK (base_version >= 0),
    status TEXT NOT NULL CHECK (status IN ('open', 'committed', 'abandoned'))
);

CREATE TABLE IF NOT EXISTS run_workspace_assets (
    run_id TEXT NOT NULL REFERENCES run_workspaces(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL,
    logical_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY (run_id, asset_type, logical_id, revision_id)
);

CREATE TABLE IF NOT EXISTS research_outcomes (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'committed', 'no_progress', 'failed', 'cancelled', 'stopped',
        'interrupted'
    )),
    committed_state_version INTEGER NOT NULL CHECK (committed_state_version >= 0),
    snapshot_fingerprint TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_run_per_action
ON research_runs(action_request_id) WHERE action_request_id IS NOT NULL;
"""

SCHEMA_V5 = """
CREATE TABLE task_committed_assets_v5 (
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (
        asset_type IN (
            'document', 'fact', 'evidence', 'review', 'conflict', 'coverage',
            'material_digest', 'task_revision'
        )
    ),
    asset_id TEXT NOT NULL,
    committed_state_version INTEGER NOT NULL
        CHECK (committed_state_version >= 0),
    PRIMARY KEY (task_id, asset_type, asset_id)
);

CREATE TABLE checkpoint_assets_v5 (
    checkpoint_id TEXT NOT NULL REFERENCES research_checkpoints(id)
        ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES task_state(task_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (
        asset_type IN (
            'document', 'fact', 'evidence', 'review', 'conflict', 'coverage',
            'material_digest', 'task_revision'
        )
    ),
    asset_id TEXT NOT NULL,
    PRIMARY KEY (checkpoint_id, asset_type, asset_id)
);

INSERT INTO task_committed_assets_v5
SELECT task_id, asset_type, asset_id, committed_state_version
FROM task_committed_assets;

INSERT INTO checkpoint_assets_v5
SELECT checkpoint_id, task_id, asset_type, asset_id
FROM checkpoint_assets;

DROP TABLE task_committed_assets;
DROP TABLE checkpoint_assets;
ALTER TABLE task_committed_assets_v5 RENAME TO task_committed_assets;
ALTER TABLE checkpoint_assets_v5 RENAME TO checkpoint_assets;
"""

SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS web_run_projections (
    run_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA_V7 = """
DROP TABLE IF EXISTS web_run_projections;
"""

_STATE_DB_PATHS: dict[Path, Path] = {}


def configure_state_db_path(cwd: Path, configured_path: str | None) -> None:
    """Bind one workspace to an optional process-local SQLite path."""
    workspace = cwd.resolve()
    if configured_path is None:
        _STATE_DB_PATHS.pop(workspace, None)
        return
    path = Path(configured_path).expanduser()
    _STATE_DB_PATHS[workspace] = (
        path if path.is_absolute() else workspace / path
    ).resolve()


def state_db_path(cwd: Path) -> Path:
    """Return the local SQLite state database path."""
    workspace = cwd.resolve()
    return _STATE_DB_PATHS.get(workspace, workspace / "data/intel/intel.db")


@contextmanager
def connect_state_db(cwd: Path):
    """Open one SQLite connection with required safety settings.

    The connection is committed (or rolled back) and closed when the
    ``with`` block exits, so no caller leaks a connection or leaves an open
    transaction that could hold the write lock (web run 057: a leaked /
    unclosed connection contributed to ``database is locked`` in
    ``finish_run``).
    """
    ensure_intel_dirs(cwd)
    path = state_db_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_state_db(cwd: Path) -> Path:
    """Create or upgrade the local state database idempotently."""
    path = state_db_path(cwd)
    with connect_state_db(cwd) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA_V1)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (1,),
        )
        if SCHEMA_VERSION >= 2:
            connection.executescript(SCHEMA_V2)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (2,),
            )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 3"
        ).fetchone()
        if SCHEMA_VERSION >= 3 and migrated is None:
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.executescript(SCHEMA_V3)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (3,)
            )
            connection.execute("PRAGMA foreign_keys = ON")
            violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"state migration violated foreign keys: {violations}"
                )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 4"
        ).fetchone()
        if SCHEMA_VERSION >= 4 and migrated is None:
            _add_column_if_missing(
                connection,
                "research_checkpoints",
                "snapshot_fingerprint",
                "TEXT",
            )
            _add_column_if_missing(
                connection,
                "report_versions",
                "snapshot_fingerprint",
                "TEXT",
            )
            connection.executescript(SCHEMA_V4)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (4,)
            )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 5"
        ).fetchone()
        if SCHEMA_VERSION >= 5 and migrated is None:
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.executescript(SCHEMA_V5)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (5,)
            )
            violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"state migration violated foreign keys: {violations}"
                )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 6"
        ).fetchone()
        if SCHEMA_VERSION >= 6 and migrated is None:
            connection.executescript(SCHEMA_V6)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (6,)
            )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 7"
        ).fetchone()
        if SCHEMA_VERSION >= 7 and migrated is None:
            connection.executescript(SCHEMA_V7)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (7,)
            )
    return path


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
