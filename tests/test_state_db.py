from __future__ import annotations

import sqlite3

import pytest

from intel_agent.state_db import connect_state_db, initialize_state_db


def test_initialize_enables_sqlite_safety_and_schema(cwd):
    path = initialize_state_db(cwd)

    assert path == cwd / "data/intel/intel.db"
    with connect_state_db(cwd) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "task_state",
        "conversations",
        "conversation_epochs",
        "messages",
        "action_requests",
        "research_runs",
        "search_plan_versions",
        "research_checkpoints",
        "report_versions",
        "conversation_events",
    } <= tables


def test_schema_enforces_foreign_keys_and_status_values(cwd):
    initialize_state_db(cwd)

    with connect_state_db(cwd) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO conversations(id, task_id, created_at, updated_at) "
                "VALUES ('conversation-1', 'missing', 'now', 'now')"
            )
        connection.execute("INSERT INTO task_state(task_id) VALUES ('task-1')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO research_runs("
                "id, task_id, run_type, input_committed_state_version, "
                "input_snapshot_json, status, created_at"
                ") VALUES ('run-1', 'task-1', 'initial', 0, '{}', "
                "'unknown', 'now')"
            )


def test_partial_indexes_reject_conflicting_active_records(cwd):
    initialize_state_db(cwd)

    with connect_state_db(cwd) as connection:
        connection.execute("INSERT INTO task_state(task_id) VALUES ('task-1')")
        connection.execute(
            "INSERT INTO research_runs("
            "id, task_id, run_type, input_committed_state_version, "
            "input_snapshot_json, status, created_at"
            ") VALUES ('run-1', 'task-1', 'initial', 0, '{}', "
            "'running', 'now')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO research_runs("
                "id, task_id, run_type, input_committed_state_version, "
                "input_snapshot_json, status, created_at"
                ") VALUES ('run-2', 'task-1', 'continue_research', 0, '{}', "
                "'running', 'now')"
            )


def test_initialize_is_idempotent(cwd):
    first = initialize_state_db(cwd)
    second = initialize_state_db(cwd)

    assert second == first
