"""MaterialStore: transactional identity, documents, scope, and index state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..contracts.documents import (
    Chunk,
    DocumentIdentity,
    NormalizedDocument,
)
from ..contracts.errors import DomainError
from ..contracts.research import (
    ContextFilter,
    MaterialScope,
)
from ..contracts.resources import Resource, ResourceOrigin
from ._ids import document_id, new_id, revision_id
from .sqlite import SqliteStore


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class MaterialStore:
    """Authoritative business storage over SQLite (spec §9.2)."""

    def __init__(self, db) -> None:
        if isinstance(db, SqliteStore):
            self.db = db
        else:
            self.db = SqliteStore(db)

    def close(self) -> None:
        self.db.close()

    # --- resources ----------------------------------------------------------

    def register_resource(self, resource: Resource) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO resources
                (resource_id, content_hash, content_ref, byte_length,
                 media_type, requested_url, final_url, local_display_name,
                 acquired_at, parent_resource_id, transform, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource.resource_id,
                    resource.content_hash,
                    resource.content_ref,
                    resource.byte_length,
                    resource.media_type,
                    resource.origin.requested_url,
                    resource.origin.final_url,
                    resource.origin.local_display_name,
                    _iso(resource.origin.acquired_at),
                    resource.parent_resource_id,
                    json.dumps(resource.transform, ensure_ascii=False)
                    if resource.transform is not None
                    else None,
                    _iso(resource.created_at),
                ),
            )

    def get_resource(self, resource_id: str) -> Resource:
        row = self.db.execute(
            "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"resource not found: {resource_id}",
                stage="storage",
            )
        return Resource(
            resource_id=row["resource_id"],
            content_hash=row["content_hash"],
            byte_length=row["byte_length"],
            media_type=row["media_type"],
            content_ref=row["content_ref"],
            origin=ResourceOrigin(
                requested_url=row["requested_url"],
                final_url=row["final_url"],
                local_display_name=row["local_display_name"],
                acquired_at=_parse_iso(row["acquired_at"]),
            ),
            created_at=_parse_iso(row["created_at"]),
            parent_resource_id=row["parent_resource_id"],
            transform=json.loads(row["transform"])
            if row["transform"]
            else None,
        )

    # --- identity -----------------------------------------------------------

    def resolve_identity(self, source_key: str) -> DocumentIdentity:
        did = document_id(source_key)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO documents (document_id, source_key,"
                " aliases) VALUES (?, ?, '[]')",
                (did, source_key),
            )
        return DocumentIdentity(document_id=did, source_key=source_key)

    def resolve_revision(self, document_id: str, resource_id: str) -> str:
        resource = self.get_resource(resource_id)
        rev = revision_id(document_id, resource.content_hash)
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO revisions
                (revision_id, document_id, content_hash, resource_id,
                 created_at) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rev,
                    document_id,
                    resource.content_hash,
                    resource_id,
                    _iso(datetime.now(UTC)),
                ),
            )
        return rev

    # --- documents ----------------------------------------------------------

    def save_document(self, task_id: str, document: NormalizedDocument) -> str:
        payload = json.dumps(
            document.model_dump(mode="json"), ensure_ascii=False
        )
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT artifact_id FROM artifacts WHERE artifact_id = ?",
                (document.artifact_id,),
            ).fetchone()
            if existing is not None:
                self._associate(conn, task_id, document.artifact_id)
                return document.artifact_id
            conn.execute(
                """
                INSERT INTO artifacts
                (artifact_id, revision_id, document_id, resource_id,
                 extraction_profile_id, normalizer_version, manifest_hash,
                 status, title, published_at, language, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.artifact_id,
                    document.revision_id,
                    document.document_id,
                    document.resource_id,
                    document.extraction_profile_id,
                    document.normalizer_version,
                    document.artifact_id.split("-", 1)[1],
                    document.status,
                    document.title,
                    _iso(document.published_at)
                    if document.published_at
                    else None,
                    document.language,
                    payload,
                    _iso(datetime.now(UTC)),
                ),
            )
            for occurrence in document.provenance:
                conn.execute(
                    """
                    INSERT INTO provenance
                    (artifact_id, document_id, provider, query_id,
                     original_url, channel, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.artifact_id,
                        document.document_id,
                        occurrence.provider,
                        occurrence.query_id,
                        occurrence.original_url,
                        occurrence.channel,
                        _iso(occurrence.observed_at),
                    ),
                )
            for ordinal, block in enumerate(document.blocks):
                conn.execute(
                    """
                    INSERT INTO blocks (artifact_id, block_id, ordinal, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        document.artifact_id,
                        block.block_id,
                        ordinal,
                        json.dumps(
                            block.model_dump(mode="json"), ensure_ascii=False
                        ),
                    ),
                )
            self._associate(conn, task_id, document.artifact_id)
        return document.artifact_id

    @staticmethod
    def _associate(conn, task_id: str, artifact_id: str) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO task_materials
            (task_id, artifact_id, ordinal, accepted, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (task_id, artifact_id, _iso(datetime.now(UTC))),
        )

    def get_document(self, artifact_id: str) -> NormalizedDocument:
        row = self.db.execute(
            "SELECT payload FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"artifact not found: {artifact_id}",
                stage="storage",
            )
        return NormalizedDocument.model_validate(json.loads(row["payload"]))

    # --- chunks -------------------------------------------------------------

    def save_chunks(self, artifact_id: str, chunks: list[Chunk]) -> None:
        with self.db.transaction() as conn:
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO chunks
                    (chunk_id, artifact_id, document_id, revision_id,
                     chunk_profile_id, ordinal, text, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.artifact_id,
                        chunk.document_id,
                        chunk.revision_id,
                        chunk.chunk_profile_id,
                        chunk.ordinal,
                        chunk.text,
                        json.dumps(
                            chunk.model_dump(mode="json"), ensure_ascii=False
                        ),
                    ),
                )

    def read_chunks(self, scope: MaterialScope) -> list[Chunk]:
        if not scope.artifact_ids:
            return []
        placeholders = ",".join("?" for _ in scope.artifact_ids)
        rows = self.db.execute(
            f"""
            SELECT payload FROM chunks
            WHERE artifact_id IN ({placeholders})
            ORDER BY artifact_id, ordinal
            """,
            tuple(scope.artifact_ids),
        ).fetchall()
        return [Chunk.model_validate(json.loads(r["payload"])) for r in rows]

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.db.execute(
            f"SELECT payload FROM chunks WHERE chunk_id IN ({placeholders})",
            tuple(chunk_ids),
        ).fetchall()
        return [Chunk.model_validate(json.loads(r["payload"])) for r in rows]

    # --- lexical ------------------------------------------------------------

    def save_chunk_terms(self, chunk_id: str, terms: list[str]) -> None:
        with self.db.transaction() as conn:
            for term in terms:
                conn.execute(
                    "INSERT OR IGNORE INTO chunk_terms (chunk_id, term)"
                    " VALUES (?, ?)",
                    (chunk_id, term),
                )

    def search_lexical(
        self, query_terms: list[str], scope: MaterialScope, top_k: int
    ) -> list[tuple[str, int]]:
        if not scope.artifact_ids or not query_terms:
            return []
        term_ph = ",".join("?" for _ in query_terms)
        art_ph = ",".join("?" for _ in scope.artifact_ids)
        rows = self.db.execute(
            f"""
            SELECT ct.chunk_id, COUNT(*) AS matches
            FROM chunk_terms ct
            JOIN chunks c ON c.chunk_id = ct.chunk_id
            WHERE ct.term IN ({term_ph})
              AND c.artifact_id IN ({art_ph})
            GROUP BY ct.chunk_id
            ORDER BY matches DESC
            LIMIT ?
            """,
            (*query_terms, *scope.artifact_ids, top_k),
        ).fetchall()
        return [(r["chunk_id"], r["matches"]) for r in rows]

    # --- scope --------------------------------------------------------------

    def resolve_scope(
        self, task_id: str, filters: ContextFilter | None = None
    ) -> MaterialScope:
        filters = filters or ContextFilter()
        with self.db.transaction() as conn:
            scope_id = new_id("scope")
            conn.execute(
                "INSERT INTO scopes (scope_id, task_id, created_at)"
                " VALUES (?, ?, ?)",
                (scope_id, task_id, _iso(datetime.now(UTC))),
            )
            rows = self._eligible_artifacts(conn, task_id, filters)
            for ordinal, row in enumerate(rows):
                conn.execute(
                    "INSERT INTO scope_artifacts (scope_id, artifact_id,"
                    " ordinal) VALUES (?, ?, ?)",
                    (scope_id, row["artifact_id"], ordinal),
                )
        return self.get_scope(scope_id)

    def _eligible_artifacts(self, conn, task_id, filters):
        sql = """
            SELECT a.artifact_id FROM artifacts a
            JOIN task_materials tm ON tm.artifact_id = a.artifact_id
            JOIN (
                SELECT document_id, MAX(created_at) AS latest
                FROM artifacts GROUP BY document_id
            ) latest ON latest.document_id = a.document_id
                 AND latest.latest = a.created_at
            WHERE tm.task_id = ? AND tm.accepted = 1
        """
        params: list[Any] = [task_id]
        if filters.document_ids:
            placeholders = ",".join("?" for _ in filters.document_ids)
            sql += f" AND a.document_id IN ({placeholders})"
            params.extend(filters.document_ids)
        sql += " ORDER BY a.document_id"
        return conn.execute(sql, tuple(params)).fetchall()

    def save_scope(self, scope: MaterialScope) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scopes (scope_id, task_id,"
                " created_at) VALUES (?, ?, ?)",
                (scope.scope_id, scope.task_id, _iso(scope.created_at)),
            )

    def get_scope(self, scope_id: str) -> MaterialScope:
        row = self.db.execute(
            "SELECT * FROM scopes WHERE scope_id = ?", (scope_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND", f"scope not found: {scope_id}", stage="storage"
            )
        artifact_rows = self.db.execute(
            "SELECT artifact_id FROM scope_artifacts WHERE scope_id = ?"
            " ORDER BY ordinal",
            (scope_id,),
        ).fetchall()
        return MaterialScope(
            scope_id=scope_id,
            task_id=row["task_id"],
            artifact_ids=[r["artifact_id"] for r in artifact_rows],
            created_at=_parse_iso(row["created_at"]),
        )

    # --- index state --------------------------------------------------------

    def record_index(
        self,
        artifact_id: str,
        chunk_profile_id: str,
        *,
        embedding_profile_id: str | None = None,
        lexical_status: str = "pending",
        vector_status: str = "pending",
        chunk_count: int = 0,
        lexical_error: str | None = None,
        vector_error: str | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO index_jobs
                (artifact_id, chunk_profile_id, embedding_profile_id,
                 lexical_status, vector_status, lexical_error, vector_error,
                 chunk_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    chunk_profile_id,
                    embedding_profile_id,
                    lexical_status,
                    vector_status,
                    lexical_error,
                    vector_error,
                    chunk_count,
                    _iso(datetime.now(UTC)),
                ),
            )

    # --- conversations ------------------------------------------------------

    def create_conversation(self, title: str = "新对话") -> dict:
        conversation_id = new_id("conv")
        now = _iso(datetime.now(UTC))
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversations"
                " (conversation_id, title, status, created_at, updated_at)"
                " VALUES (?, ?, 'intake', ?, ?)",
                (conversation_id, title, now, now),
            )
        return self.get_conversation(conversation_id)

    def list_conversations(self, archived: bool = False) -> list[dict]:
        statuses = ("archived",) if archived else ("intake", "active")
        placeholders = ",".join("?" for _ in statuses)
        rows = self.db.execute(
            f"SELECT * FROM conversations WHERE status IN ({placeholders})"
            " ORDER BY updated_at DESC",
            statuses,
        ).fetchall()
        return [self._conversation_view(r) for r in rows]

    def get_conversation(self, conversation_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"conversation not found: {conversation_id}",
                stage="storage",
            )
        return self._conversation_view(row)

    def set_conversation_status(
        self, conversation_id: str, status: str
    ) -> dict:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET status = ?, updated_at = ?"
                " WHERE conversation_id = ?",
                (status, _iso(datetime.now(UTC)), conversation_id),
            )
        return self.get_conversation(conversation_id)

    def set_conversation_title(self, conversation_id: str, title: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, status = 'active',"
                " updated_at = ? WHERE conversation_id = ?",
                (title, _iso(datetime.now(UTC)), conversation_id),
            )

    def save_brief(self, conversation_id: str, brief: dict) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET brief = ?, updated_at = ?"
                " WHERE conversation_id = ?",
                (
                    json.dumps(brief, ensure_ascii=False),
                    _iso(datetime.now(UTC)),
                    conversation_id,
                ),
            )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        task_id: str | None = None,
        citations: list | None = None,
        status: str = "completed",
    ) -> dict:
        message_id = new_id("msg")
        now = _iso(datetime.now(UTC))
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS seq FROM messages"
                " WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            sequence = row["seq"] + 1
            conn.execute(
                "INSERT INTO messages (message_id, conversation_id, role,"
                " content, status, task_id, citations, sequence, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    status,
                    task_id,
                    json.dumps(citations, ensure_ascii=False)
                    if citations is not None
                    else None,
                    sequence,
                    now,
                ),
            )
        return {
            "id": message_id,
            "role": role,
            "content": content,
            "status": status,
            "citations": citations or [],
        }

    def list_messages(self, conversation_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ?"
            " ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
        return [
            {
                "id": r["message_id"],
                "role": r["role"],
                "content": r["content"],
                "status": r["status"],
                "citations": json.loads(r["citations"])
                if r["citations"]
                else [],
            }
            for r in rows
        ]

    def add_timeline(
        self,
        conversation_id: str,
        kind: str,
        label: str,
        *,
        detail: str | None = None,
        task_id: str | None = None,
        at: str | None = None,
    ) -> dict:
        timeline_id = new_id("tl")
        at = at or _iso(datetime.now(UTC))
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS seq FROM timeline"
                " WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            sequence = row["seq"] + 1
            conn.execute(
                "INSERT INTO timeline (timeline_id, conversation_id, task_id,"
                " kind, label, detail, at, sequence) VALUES (?, ?, ?, ?, ?,"
                " ?, ?, ?)",
                (
                    timeline_id,
                    conversation_id,
                    task_id,
                    kind,
                    label,
                    detail,
                    at,
                    sequence,
                ),
            )
        return {
            "id": timeline_id,
            "kind": kind,
            "label": label,
            "detail": detail,
            "at": at,
        }

    def list_timeline(self, conversation_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM timeline WHERE conversation_id = ?"
            " ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
        return [
            {
                "id": r["timeline_id"],
                "kind": r["kind"],
                "label": r["label"],
                "detail": r["detail"],
                "at": r["at"],
            }
            for r in rows
        ]

    @staticmethod
    def _conversation_view(row) -> dict:
        return {
            "id": row["conversation_id"],
            "title": row["title"],
            "status": row["status"],
            "updated_at": row["updated_at"],
            "brief": json.loads(row["brief"]) if row["brief"] else None,
        }

    # --- research results ---------------------------------------------------

    def save_research_result(
        self,
        task_id: str,
        *,
        report: dict | None = None,
        coverage: dict | None = None,
        evidence: dict | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO research_results
                (task_id, report, coverage, evidence, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    report = COALESCE(excluded.report, research_results.report),
                    coverage = COALESCE(
                        excluded.coverage, research_results.coverage
                    ),
                    evidence = COALESCE(
                        excluded.evidence, research_results.evidence
                    ),
                    updated_at = excluded.updated_at
                """,
                (
                    task_id,
                    json.dumps(report, ensure_ascii=False)
                    if report is not None
                    else None,
                    json.dumps(coverage, ensure_ascii=False)
                    if coverage is not None
                    else None,
                    json.dumps(evidence, ensure_ascii=False)
                    if evidence is not None
                    else None,
                    _iso(datetime.now(UTC)),
                ),
            )

    def get_research_result(self, task_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM research_results WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "report": json.loads(row["report"]) if row["report"] else None,
            "coverage": json.loads(row["coverage"])
            if row["coverage"]
            else None,
            "evidence": json.loads(row["evidence"])
            if row["evidence"]
            else None,
        }
