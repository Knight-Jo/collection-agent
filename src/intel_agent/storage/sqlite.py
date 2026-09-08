"""SQLite connection wrapper and schema migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

MIGRATIONS = (
    "001_initial.sql",
    "002_conversations.sql",
    "003_research_results.sql",
    "004_runtime_state.sql",
    "005_workspace_extensions.sql",
    "006_monitor_watch_sources.sql",
)


class SqliteStore:
    """A single-threaded SQLite connection with migration management.

    Business modules never touch SQL directly; they go through MaterialStore
    (storage/materials.py), which is the only caller of this wrapper.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self.migrate()
        return conn

    def migrate(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta ("
            " key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        applied = {
            row["key"]
            for row in conn.execute("SELECT key FROM schema_meta").fetchall()
            if row["key"].startswith("migration:")
        }
        for name in MIGRATIONS:
            key = f"migration:{name}"
            if key in applied:
                continue
            script = resources.files(
                "intel_agent.storage.migrations"
            ).joinpath(name)
            with resources.as_file(script) as path:
                sql = path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
                (key, name),
            )
            conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.connect().execute(sql, params)

    def executescript(self, sql: str) -> None:
        self.connect().executescript(sql)

    def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
