"""Transactional repository for local conversational research state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from .models import (
    ActionRequest,
    ActionRequestStatus,
    ActionType,
    CitationDraft,
    CommittedAssetType,
    Conversation,
    ConversationEpoch,
    ConversationEvent,
    IntelError,
    Message,
    MessageCitation,
    ReportVersion,
    ResearchCheckpoint,
    ResearchRun,
    ResearchRunStatus,
    new_id,
    utc_now,
)
from .state_db import connect_state_db, initialize_state_db

ACTION_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"queued", "rejected", "expired"},
    "queued": {"executing", "expired", "cancelled"},
    "executing": {"succeeded", "failed", "cancelled"},
}
RUN_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "interrupted"},
}


class StateStore:
    """Persist single-user task conversations in the local SQLite database."""

    def __init__(self, cwd: Path):
        self.cwd = cwd
        initialize_state_db(cwd)

    def register_task(self, task_id: str) -> Conversation:
        """Create the task's single conversation and first epoch if absent."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO task_state(task_id) VALUES (?)",
                (task_id,),
            )
            existing = connection.execute(
                "SELECT * FROM conversations WHERE task_id = ?", (task_id,)
            ).fetchone()
            if existing is not None:
                return _row_to_conversation(existing)

            conversation_id = new_id("conversation")
            epoch_id = new_id("epoch")
            connection.execute(
                "INSERT INTO conversations("
                "id, task_id, created_at, updated_at"
                ") VALUES (?, ?, ?, ?)",
                (conversation_id, task_id, now, now),
            )
            connection.execute(
                "INSERT INTO conversation_epochs("
                "id, conversation_id, sequence, started_at"
                ") VALUES (?, ?, 1, ?)",
                (epoch_id, conversation_id, now),
            )
            connection.execute(
                "UPDATE conversations SET active_epoch_id = ? WHERE id = ?",
                (epoch_id, conversation_id),
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return _row_to_conversation(_required(row, "conversation"))

    def get_conversation(self, task_id: str) -> Conversation:
        """Return one task's conversation."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", f"任务会话不存在: {task_id}")
        return _row_to_conversation(row)

    def get_conversation_by_id(self, conversation_id: str) -> Conversation:
        """Return one conversation by its durable identifier."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", f"任务会话不存在: {conversation_id}")
        return _row_to_conversation(row)

    def start_epoch(self, task_id: str) -> ConversationEpoch:
        """Archive the visible context and start a fresh conversation epoch."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE task_id = ?", (task_id,)
            ).fetchone()
            if conversation is None:
                raise IntelError("NOT_FOUND", f"任务会话不存在: {task_id}")
            conversation_id = conversation["id"]
            connection.execute(
                "UPDATE conversation_epochs SET archived_at = ? "
                "WHERE conversation_id = ? AND archived_at IS NULL",
                (now, conversation_id),
            )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM conversation_epochs WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            epoch_id = new_id("epoch")
            connection.execute(
                "INSERT INTO conversation_epochs("
                "id, conversation_id, sequence, started_at"
                ") VALUES (?, ?, ?, ?)",
                (epoch_id, conversation_id, sequence, now),
            )
            connection.execute(
                "UPDATE conversations SET active_epoch_id = ?, updated_at = ? "
                "WHERE id = ?",
                (epoch_id, now, conversation_id),
            )
            row = connection.execute(
                "SELECT * FROM conversation_epochs WHERE id = ?", (epoch_id,)
            ).fetchone()
        return _row_to_epoch(_required(row, "conversation epoch"))

    def active_epoch(self, task_id: str) -> ConversationEpoch:
        """Return the task conversation's active context epoch."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT conversation_epochs.* FROM conversation_epochs "
                "JOIN conversations ON conversations.active_epoch_id = "
                "conversation_epochs.id WHERE conversations.task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", f"活动会话上下文不存在: {task_id}")
        return _row_to_epoch(row)

    def update_epoch_summary(
        self, epoch_id: str, summary: str, through_sequence: int
    ) -> ConversationEpoch:
        """Atomically advance one epoch summary coverage."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE conversation_epochs SET summary = ?, "
                "summary_through_sequence = ?, summary_updated_at = ? "
                "WHERE id = ? AND summary_through_sequence < ?",
                (summary, through_sequence, now, epoch_id, through_sequence),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT * FROM conversation_epochs WHERE id = ?",
                    (epoch_id,),
                ).fetchone()
                if existing is None:
                    raise IntelError(
                        "NOT_FOUND", f"会话上下文不存在: {epoch_id}"
                    )
            row = connection.execute(
                "SELECT * FROM conversation_epochs WHERE id = ?", (epoch_id,)
            ).fetchone()
        return _row_to_epoch(_required(row, "conversation epoch"))

    def add_user_message(
        self,
        task_id: str,
        content: str,
        client_message_id: str,
    ) -> Message:
        """Append a user message, returning the original on an exact retry."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE task_id = ?", (task_id,)
            ).fetchone()
            if conversation is None:
                raise IntelError("NOT_FOUND", f"任务会话不存在: {task_id}")
            conversation_id = conversation["id"]
            existing = connection.execute(
                "SELECT * FROM messages "
                "WHERE conversation_id = ? AND client_message_id = ?",
                (conversation_id, client_message_id),
            ).fetchone()
            if existing is not None:
                if existing["content"] != content:
                    raise IntelError(
                        "IDEMPOTENCY_CONFLICT",
                        "client_message_id 已用于不同内容",
                    )
                return _row_to_message(existing)

            epoch_id = conversation["active_epoch_id"]
            if epoch_id is None:
                raise IntelError("STORAGE_CORRUPT", "任务会话缺少活动上下文")
            sequence = _next_message_sequence(connection, conversation_id)
            message_id = new_id("message")
            connection.execute(
                "INSERT INTO messages("
                "id, conversation_id, epoch_id, sequence, "
                "client_message_id, role, content, status, created_at"
                ") VALUES (?, ?, ?, ?, ?, 'user', ?, 'accepted', ?)",
                (
                    message_id,
                    conversation_id,
                    epoch_id,
                    sequence,
                    client_message_id,
                    content,
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            _insert_event(
                connection,
                conversation_id,
                "message.accepted",
                {"message_id": message_id},
                now,
                message_id=message_id,
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(_required(row, "message"))

    def set_message_processing(self, message_id: str) -> Message:
        """Mark an accepted user message as being processed."""
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            message = _find_message(connection, message_id)
            if message["role"] != "user":
                raise IntelError("INVALID_INPUT", "只能处理用户消息")
            if message["status"] == "accepted":
                connection.execute(
                    "UPDATE messages SET status = 'processing' WHERE id = ?",
                    (message_id,),
                )
            elif message["status"] != "processing":
                raise _invalid_transition(
                    "message", message["status"], "processing"
                )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(_required(row, "message"))

    def fail_message(self, message_id: str, error: str) -> Message:
        """Finish an accepted or processing user message with an error."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            message = _find_message(connection, message_id)
            if message["role"] != "user":
                raise IntelError("INVALID_INPUT", "只能结束用户消息")
            if message["status"] not in {"accepted", "processing"}:
                raise _invalid_transition(
                    "message", message["status"], "failed"
                )
            connection.execute(
                "UPDATE messages SET status = 'failed', completed_at = ?, "
                "error = ? WHERE id = ?",
                (now, error, message_id),
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(_required(row, "message"))

    def cancel_message(self, message_id: str) -> Message:
        """Cancel an accepted or processing user message."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            message = _find_message(connection, message_id)
            if message["role"] != "user":
                raise IntelError("INVALID_INPUT", "只能取消用户消息")
            if message["status"] not in {"accepted", "processing"}:
                raise _invalid_transition(
                    "message", message["status"], "cancelled"
                )
            connection.execute(
                "UPDATE messages SET status = 'cancelled', completed_at = ? "
                "WHERE id = ?",
                (now, message_id),
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(_required(row, "message"))

    def complete_message(
        self,
        user_message_id: str,
        content: str,
        citations: Sequence[CitationDraft] = (),
    ) -> Message:
        """Complete one user request and insert its immutable assistant reply."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (user_message_id,)
            ).fetchone()
            if user is None:
                raise IntelError(
                    "NOT_FOUND", f"用户消息不存在: {user_message_id}"
                )
            if user["role"] != "user":
                raise IntelError("INVALID_INPUT", "只能回复用户消息")
            existing = connection.execute(
                "SELECT * FROM messages WHERE reply_to_id = ?",
                (user_message_id,),
            ).fetchone()
            if existing is not None:
                if existing["content"] != content:
                    raise IntelError(
                        "IDEMPOTENCY_CONFLICT", "用户消息已有不同回答"
                    )
                return _row_to_message(existing)
            if user["status"] not in {"accepted", "processing"}:
                raise IntelError(
                    "INVALID_STATE_TRANSITION", "用户消息已结束处理"
                )

            task_id = connection.execute(
                "SELECT task_id FROM conversations WHERE id = ?",
                (user["conversation_id"],),
            ).fetchone()[0]
            for citation in citations:
                _validate_citation(connection, task_id, citation)

            connection.execute(
                "UPDATE messages SET status = 'completed', completed_at = ? "
                "WHERE id = ?",
                (now, user_message_id),
            )
            sequence = _next_message_sequence(
                connection, user["conversation_id"]
            )
            assistant_id = new_id("message")
            connection.execute(
                "INSERT INTO messages("
                "id, conversation_id, epoch_id, sequence, role, content, "
                "status, reply_to_id, created_at, completed_at"
                ") VALUES (?, ?, ?, ?, 'assistant', ?, 'completed', ?, ?, ?)",
                (
                    assistant_id,
                    user["conversation_id"],
                    user["epoch_id"],
                    sequence,
                    content,
                    user_message_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, user["conversation_id"]),
            )
            for citation_sequence, citation in enumerate(citations, start=1):
                connection.execute(
                    "INSERT INTO message_citations("
                    "id, task_id, message_id, sequence, citation_kind, "
                    "document_id, evidence_id, fact_id, title, source_url, "
                    "quote_text, line_start, line_end, source_content_hash, "
                    "created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_id("citation"),
                        task_id,
                        assistant_id,
                        citation_sequence,
                        citation.citation_kind,
                        citation.document_id,
                        citation.evidence_id,
                        citation.fact_id,
                        citation.title,
                        citation.source_url,
                        citation.quote_text,
                        citation.line_start,
                        citation.line_end,
                        citation.source_content_hash,
                        now,
                    ),
                )
            _insert_event(
                connection,
                user["conversation_id"],
                "answer.completed",
                {
                    "message_id": assistant_id,
                    "reply_to_id": user_message_id,
                },
                now,
                message_id=assistant_id,
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (assistant_id,)
            ).fetchone()
        return _row_to_message(_required(row, "assistant message"))

    def get_message(self, message_id: str) -> Message:
        """Return one persisted message."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", f"消息不存在: {message_id}")
        return _row_to_message(row)

    def reply_for_message(self, message_id: str) -> Message | None:
        """Return the immutable assistant reply when it exists."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE reply_to_id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(row) if row is not None else None

    def pending_messages(self) -> list[Message]:
        """Return unfinished user requests for process restart recovery."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT messages.* FROM messages "
                "WHERE messages.role = 'user' "
                "AND messages.status IN ('accepted', 'processing') "
                "AND NOT EXISTS (SELECT 1 FROM messages replies "
                "WHERE replies.reply_to_id = messages.id) "
                "ORDER BY messages.created_at, messages.rowid"
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def list_messages(
        self, task_id: str, *, active_epoch_only: bool = True
    ) -> list[Message]:
        """List task messages in stable conversation order."""
        where = "AND messages.epoch_id = conversations.active_epoch_id"
        if not active_epoch_only:
            where = ""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                f"SELECT messages.* FROM messages "
                f"JOIN conversations "
                f"ON conversations.id = messages.conversation_id "
                f"WHERE conversations.task_id = ? {where} "
                f"ORDER BY messages.sequence",
                (task_id,),
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def citations_for_message(self, message_id: str) -> list[MessageCitation]:
        """Return citations in their answer display order."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT * FROM message_citations WHERE message_id = ? "
                "ORDER BY sequence",
                (message_id,),
            ).fetchall()
        return [_row_to_citation(row) for row in rows]

    def seed_committed_assets(
        self,
        task_id: str,
        assets: Iterable[tuple[CommittedAssetType, str]],
    ) -> None:
        """Idempotently expose existing task assets to conversation reads."""
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = _task_state(connection, task_id)
            connection.executemany(
                "INSERT OR IGNORE INTO task_committed_assets("
                "task_id, asset_type, asset_id, committed_state_version"
                ") VALUES (?, ?, ?, ?)",
                (
                    (
                        task_id,
                        asset_type,
                        asset_id,
                        state["current_committed_state_version"],
                    )
                    for asset_type, asset_id in assets
                ),
            )

    def committed_asset_ids(
        self, task_id: str, asset_type: CommittedAssetType
    ) -> set[str]:
        """Return IDs visible in the task's committed research state."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT asset_id FROM task_committed_assets "
                "WHERE task_id = ? AND asset_type = ?",
                (task_id, asset_type),
            ).fetchall()
        return {row[0] for row in rows}

    def create_action(
        self,
        task_id: str,
        trigger_message_id: str,
        action_type: ActionType,
        payload: dict[str, object],
        *,
        proposed: bool = False,
        target_research_run_id: str | None = None,
        precondition_search_plan_version_id: str | None = None,
    ) -> ActionRequest:
        """Persist an explicit action or a proposal awaiting confirmation."""
        if (
            action_type == "modify_search_plan"
            and precondition_search_plan_version_id is None
        ):
            raise IntelError("INVALID_INPUT", "修改检索计划必须指定原计划版本")
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = _task_state(connection, task_id)
            message = connection.execute(
                "SELECT messages.id FROM messages "
                "JOIN conversations "
                "ON conversations.id = messages.conversation_id "
                "WHERE messages.id = ? AND conversations.task_id = ?",
                (trigger_message_id, task_id),
            ).fetchone()
            if message is None:
                raise IntelError("INVALID_INPUT", "触发消息不属于当前任务")
            action_id = new_id("action")
            status = "proposed" if proposed else "queued"
            request_mode = None if proposed else "explicit_message"
            request_message_id = None if proposed else trigger_message_id
            queued_at = None if proposed else now
            connection.execute(
                "INSERT INTO action_requests("
                "id, task_id, trigger_message_id, action_type, "
                "immutable_payload_json, request_mode, request_message_id, "
                "precondition_committed_state_version, "
                "precondition_search_plan_version_id, status, created_at, "
                "queued_at, target_research_run_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    task_id,
                    trigger_message_id,
                    action_type,
                    _json(payload),
                    request_mode,
                    request_message_id,
                    state["current_committed_state_version"],
                    precondition_search_plan_version_id,
                    status,
                    now,
                    queued_at,
                    target_research_run_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM action_requests WHERE id = ?", (action_id,)
            ).fetchone()
        return _row_to_action(_required(row, "action request"))

    def get_action(self, action_id: str) -> ActionRequest:
        """Return one action request."""
        with connect_state_db(self.cwd) as connection:
            row = _find_action(connection, action_id)
        return _row_to_action(row)

    def list_actions(self, task_id: str) -> list[ActionRequest]:
        """List task actions in creation order."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT * FROM action_requests WHERE task_id = ? "
                "ORDER BY created_at, rowid",
                (task_id,),
            ).fetchall()
        return [_row_to_action(row) for row in rows]

    def confirm_action(
        self, action_id: str, confirmation_message_id: str
    ) -> ActionRequest:
        """Confirm one proposal and queue it exactly once."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = _find_action(connection, action_id)
            if action["status"] == "queued":
                if (
                    action["request_mode"] == "confirmed_proposal"
                    and action["request_message_id"] == confirmation_message_id
                ):
                    return _row_to_action(action)
                raise _invalid_transition("action", "queued", "queued")
            if action["status"] != "proposed":
                raise _invalid_transition("action", action["status"], "queued")
            message = connection.execute(
                "SELECT messages.id FROM messages "
                "JOIN conversations "
                "ON conversations.id = messages.conversation_id "
                "WHERE messages.id = ? AND conversations.task_id = ?",
                (confirmation_message_id, action["task_id"]),
            ).fetchone()
            if message is None:
                raise IntelError("INVALID_INPUT", "确认消息不属于当前任务")
            current_version = _task_state(connection, action["task_id"])[
                "current_committed_state_version"
            ]
            if (
                current_version
                != action["precondition_committed_state_version"]
            ):
                connection.execute(
                    "UPDATE action_requests SET status = 'expired', "
                    "completed_at = ? WHERE id = ?",
                    (now, action_id),
                )
            else:
                connection.execute(
                    "UPDATE action_requests SET status = 'queued', "
                    "request_mode = 'confirmed_proposal', "
                    "request_message_id = ?, confirmed_at = ?, queued_at = ? "
                    "WHERE id = ?",
                    (confirmation_message_id, now, now, action_id),
                )
            row = connection.execute(
                "SELECT * FROM action_requests WHERE id = ?", (action_id,)
            ).fetchone()
        return _row_to_action(_required(row, "action request"))

    def transition_action(
        self,
        action_id: str,
        new_status: ActionRequestStatus,
        *,
        error: str | None = None,
        created_research_run_id: str | None = None,
        applied_search_plan_version_id: str | None = None,
        applied_checkpoint_id: str | None = None,
        created_report_version_id: str | None = None,
    ) -> ActionRequest:
        """Apply one allowed action lifecycle transition."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = _find_action(connection, action_id)
            if new_status not in ACTION_TRANSITIONS.get(
                action["status"], set()
            ):
                raise _invalid_transition(
                    "action", action["status"], new_status
                )
            executing_at = now if new_status == "executing" else None
            completed_at = (
                now
                if new_status
                in {
                    "succeeded",
                    "failed",
                    "rejected",
                    "expired",
                    "cancelled",
                }
                else None
            )
            connection.execute(
                "UPDATE action_requests SET status = ?, "
                "executing_at = COALESCE(?, executing_at), "
                "completed_at = COALESCE(?, completed_at), error = ?, "
                "created_research_run_id = "
                "COALESCE(?, created_research_run_id), "
                "applied_search_plan_version_id = "
                "COALESCE(?, applied_search_plan_version_id), "
                "applied_checkpoint_id = COALESCE(?, applied_checkpoint_id), "
                "created_report_version_id = "
                "COALESCE(?, created_report_version_id) WHERE id = ?",
                (
                    new_status,
                    executing_at,
                    completed_at,
                    error,
                    created_research_run_id,
                    applied_search_plan_version_id,
                    applied_checkpoint_id,
                    created_report_version_id,
                    action_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM action_requests WHERE id = ?", (action_id,)
            ).fetchone()
        return _row_to_action(_required(row, "action request"))

    def create_run(
        self,
        task_id: str,
        run_type: str,
        input_committed_state_version: int,
        input_snapshot: dict[str, object],
        *,
        trigger_message_id: str | None = None,
        action_request_id: str | None = None,
        retry_of_run_id: str | None = None,
    ) -> ResearchRun:
        """Create one queued research execution attempt."""
        if run_type == "retry" and retry_of_run_id is None:
            raise IntelError("INVALID_INPUT", "重试运行必须关联原运行")
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _task_state(connection, task_id)
            run_id = new_id("run")
            connection.execute(
                "INSERT INTO research_runs("
                "id, task_id, run_type, trigger_message_id, "
                "action_request_id, retry_of_run_id, "
                "input_committed_state_version, input_snapshot_json, "
                "status, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
                (
                    run_id,
                    task_id,
                    run_type,
                    trigger_message_id,
                    action_request_id,
                    retry_of_run_id,
                    input_committed_state_version,
                    _json(input_snapshot),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM research_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(_required(row, "research run"))

    def transition_run(
        self,
        run_id: str,
        new_status: ResearchRunStatus,
        *,
        phase: str | None = None,
        outcome: str | None = None,
        error: str | None = None,
    ) -> ResearchRun:
        """Apply one allowed research run transition."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _find_run(connection, run_id)
            if new_status not in RUN_TRANSITIONS.get(run["status"], set()):
                raise _invalid_transition("run", run["status"], new_status)
            started_at = now if new_status == "running" else None
            completed_at = (
                now
                if new_status
                in {"succeeded", "failed", "cancelled", "interrupted"}
                else None
            )
            connection.execute(
                "UPDATE research_runs SET status = ?, "
                "started_at = COALESCE(?, started_at), completed_at = ?, "
                "phase = COALESCE(?, phase), outcome = ?, error = ? "
                "WHERE id = ?",
                (
                    new_status,
                    started_at,
                    completed_at,
                    phase,
                    outcome,
                    error,
                    run_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM research_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(_required(row, "research run"))

    def get_run(self, run_id: str) -> ResearchRun:
        """Return one research run."""
        with connect_state_db(self.cwd) as connection:
            row = _find_run(connection, run_id)
        return _row_to_run(row)

    def list_runs(self, task_id: str) -> list[ResearchRun]:
        """List task runs in creation order."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT * FROM research_runs WHERE task_id = ? "
                "ORDER BY created_at, rowid",
                (task_id,),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def retry_run(self, run_id: str) -> ResearchRun:
        """Create a fresh queued run linked to a failed or interrupted run."""
        with connect_state_db(self.cwd) as connection:
            run = _find_run(connection, run_id)
            if run["status"] not in {"failed", "interrupted"}:
                raise IntelError(
                    "INVALID_STATE_TRANSITION", "只能重试失败或中断的运行"
                )
            current_version = _task_state(connection, run["task_id"])[
                "current_committed_state_version"
            ]
            snapshot = json.loads(run["input_snapshot_json"])
        return self.create_run(
            run["task_id"],
            "retry",
            current_version,
            snapshot,
            trigger_message_id=run["trigger_message_id"],
            action_request_id=run["action_request_id"],
            retry_of_run_id=run_id,
        )

    def start_checkpoint(
        self,
        run_id: str,
        *,
        reason: str,
        search_plan_version_id: str | None = None,
        trigger_action_request_id: str | None = None,
    ) -> ResearchCheckpoint:
        """Open one checkpoint against the task's current committed state."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _find_run(connection, run_id)
            state = _task_state(connection, run["task_id"])
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM research_checkpoints WHERE research_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            checkpoint_id = new_id("checkpoint")
            connection.execute(
                "INSERT INTO research_checkpoints("
                "id, task_id, research_run_id, sequence, "
                "search_plan_version_id, input_committed_state_version, "
                "status, trigger_action_request_id, reason, started_at"
                ") VALUES (?, ?, ?, ?, ?, ?, 'started', ?, ?, ?)",
                (
                    checkpoint_id,
                    run["task_id"],
                    run_id,
                    sequence,
                    search_plan_version_id,
                    state["current_committed_state_version"],
                    trigger_action_request_id,
                    reason,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM research_checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()
        return _row_to_checkpoint(_required(row, "research checkpoint"))

    def commit_checkpoint(
        self,
        checkpoint_id: str,
        assets: Iterable[tuple[CommittedAssetType, str]] = (),
    ) -> ResearchCheckpoint:
        """Commit one checkpoint and advance the research state once."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            checkpoint = _find_checkpoint(connection, checkpoint_id)
            if checkpoint["status"] == "committed":
                return _row_to_checkpoint(checkpoint)
            if checkpoint["status"] != "started":
                raise _invalid_transition(
                    "checkpoint", checkpoint["status"], "committed"
                )
            state = _task_state(connection, checkpoint["task_id"])
            input_version = checkpoint["input_committed_state_version"]
            if state["current_committed_state_version"] != input_version:
                raise IntelError(
                    "STALE_CHECKPOINT", "检查点基于过期的研究状态"
                )
            output_version = input_version + 1
            asset_values = list(assets)
            connection.executemany(
                "INSERT OR IGNORE INTO checkpoint_assets("
                "checkpoint_id, task_id, asset_type, asset_id"
                ") VALUES (?, ?, ?, ?)",
                (
                    (
                        checkpoint_id,
                        checkpoint["task_id"],
                        asset_type,
                        asset_id,
                    )
                    for asset_type, asset_id in asset_values
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO task_committed_assets("
                "task_id, asset_type, asset_id, committed_state_version"
                ") VALUES (?, ?, ?, ?)",
                (
                    (
                        checkpoint["task_id"],
                        asset_type,
                        asset_id,
                        output_version,
                    )
                    for asset_type, asset_id in asset_values
                ),
            )
            connection.execute(
                "UPDATE research_checkpoints SET status = 'committed', "
                "output_committed_state_version = ?, committed_at = ? "
                "WHERE id = ?",
                (output_version, now, checkpoint_id),
            )
            connection.execute(
                "UPDATE task_state SET current_committed_state_version = ?, "
                "updated_at = ? WHERE task_id = ?",
                (output_version, now, checkpoint["task_id"]),
            )
            row = connection.execute(
                "SELECT * FROM research_checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()
        return _row_to_checkpoint(_required(row, "research checkpoint"))

    def committed_state_version(self, task_id: str) -> int:
        """Return the task's current committed research-state version."""
        with connect_state_db(self.cwd) as connection:
            return _task_state(connection, task_id)[
                "current_committed_state_version"
            ]

    def create_report_draft(
        self,
        task_id: str,
        content_path: str,
        content_sha256: str,
        *,
        report_id: str | None = None,
    ) -> ReportVersion:
        """Create a draft and abandon the task's previous draft atomically."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = _task_state(connection, task_id)
            connection.execute(
                "UPDATE report_versions SET status = 'abandoned', "
                "abandoned_at = ? WHERE task_id = ? AND status = 'draft'",
                (now, task_id),
            )
            version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 "
                "FROM report_versions WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            report_id = report_id or new_id("report")
            connection.execute(
                "INSERT INTO report_versions("
                "id, task_id, version, status, content_path, content_sha256, "
                "based_on_committed_state_version, created_at"
                ") VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)",
                (
                    report_id,
                    task_id,
                    version,
                    content_path,
                    content_sha256,
                    state["current_committed_state_version"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE task_state SET current_draft_report_version_id = ?, "
                "updated_at = ? WHERE task_id = ?",
                (report_id, now, task_id),
            )
            row = connection.execute(
                "SELECT * FROM report_versions WHERE id = ?", (report_id,)
            ).fetchone()
        return _row_to_report(_required(row, "report version"))

    def get_report(self, report_id: str) -> ReportVersion:
        """Return one report version."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM report_versions WHERE id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", f"报告版本不存在: {report_id}")
        return _row_to_report(row)

    def list_reports(self, task_id: str) -> list[ReportVersion]:
        """List task report versions in numeric order."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT * FROM report_versions WHERE task_id = ? "
                "ORDER BY version",
                (task_id,),
            ).fetchall()
        return [_row_to_report(row) for row in rows]

    def abandon_report(self, report_id: str) -> ReportVersion:
        """Abandon an unpublished draft."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            report = _find_report(connection, report_id)
            if report["status"] != "draft":
                raise _invalid_transition(
                    "report", report["status"], "abandoned"
                )
            connection.execute(
                "UPDATE report_versions SET status = 'abandoned', "
                "abandoned_at = ? WHERE id = ?",
                (now, report_id),
            )
            connection.execute(
                "UPDATE task_state SET current_draft_report_version_id = NULL, "
                "updated_at = ? WHERE task_id = ? "
                "AND current_draft_report_version_id = ?",
                (now, report["task_id"], report_id),
            )
            row = connection.execute(
                "SELECT * FROM report_versions WHERE id = ?", (report_id,)
            ).fetchone()
        return _row_to_report(_required(row, "report version"))

    def publish_report(
        self,
        report_id: str,
        *,
        publish_stale: bool = False,
        expected_current_state_version: int | None = None,
    ) -> ReportVersion:
        """Publish a draft, rejecting stale content unless explicitly pinned."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            report = _find_report(connection, report_id)
            if report["status"] != "draft":
                raise _invalid_transition(
                    "report", report["status"], "published"
                )
            state = _task_state(connection, report["task_id"])
            current_version = state["current_committed_state_version"]
            is_stale = (
                report["based_on_committed_state_version"] != current_version
            )
            stale_confirmed = (
                publish_stale
                and expected_current_state_version is not None
                and expected_current_state_version == current_version
            )
            if is_stale and not stale_confirmed:
                raise IntelError("STALE_REPORT", "报告基于旧研究状态")
            connection.execute(
                "UPDATE report_versions SET status = 'superseded' "
                "WHERE task_id = ? AND status = 'published'",
                (report["task_id"],),
            )
            connection.execute(
                "UPDATE report_versions SET status = 'published', "
                "published_at = ? WHERE id = ?",
                (now, report_id),
            )
            connection.execute(
                "UPDATE task_state SET current_draft_report_version_id = NULL, "
                "current_published_report_version_id = ?, updated_at = ? "
                "WHERE task_id = ?",
                (report_id, now, report["task_id"]),
            )
            row = connection.execute(
                "SELECT * FROM report_versions WHERE id = ?", (report_id,)
            ).fetchone()
        return _row_to_report(_required(row, "report version"))

    def append_event(
        self,
        task_id: str,
        event_type: str,
        data: dict[str, object],
        *,
        message_id: str | None = None,
        action_request_id: str | None = None,
        research_run_id: str | None = None,
    ) -> ConversationEvent:
        """Append one durable event with a conversation-scoped sequence."""
        if event_type in {"answer.delta", "run.progress", "heartbeat"}:
            raise IntelError(
                "INVALID_INPUT", f"瞬时事件不能持久化: {event_type}"
            )
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE task_id = ?", (task_id,)
            ).fetchone()
            if conversation is None:
                raise IntelError("NOT_FOUND", f"任务会话不存在: {task_id}")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM conversation_events WHERE conversation_id = ?",
                (conversation["id"],),
            ).fetchone()[0]
            cursor = connection.execute(
                "INSERT INTO conversation_events("
                "conversation_id, sequence, event_type, data_json, "
                "message_id, action_request_id, research_run_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation["id"],
                    sequence,
                    event_type,
                    _json(data),
                    message_id,
                    action_request_id,
                    research_run_id,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM conversation_events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_event(_required(row, "conversation event"))

    def events_after(
        self, task_id: str, sequence: int
    ) -> list[ConversationEvent]:
        """Return durable events after a reconnect sequence."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT conversation_events.* FROM conversation_events "
                "JOIN conversations ON conversations.id = "
                "conversation_events.conversation_id "
                "WHERE conversations.task_id = ? "
                "AND conversation_events.sequence > ? "
                "ORDER BY conversation_events.sequence",
                (task_id, sequence),
            ).fetchall()
        return [_row_to_event(row) for row in rows]


def _next_message_sequence(
    connection: sqlite3.Connection, conversation_id: str
) -> int:
    return connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 "
        "FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]


def _insert_event(
    connection: sqlite3.Connection,
    conversation_id: str,
    event_type: str,
    data: dict[str, object],
    created_at: str,
    *,
    message_id: str | None = None,
    action_request_id: str | None = None,
    research_run_id: str | None = None,
) -> None:
    sequence = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 "
        "FROM conversation_events WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO conversation_events("
        "conversation_id, sequence, event_type, data_json, message_id, "
        "action_request_id, research_run_id, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id,
            sequence,
            event_type,
            _json(data),
            message_id,
            action_request_id,
            research_run_id,
            created_at,
        ),
    )


def _validate_citation(
    connection: sqlite3.Connection,
    task_id: str,
    citation: CitationDraft,
) -> None:
    assets: list[tuple[CommittedAssetType, str]] = [
        ("document", citation.document_id)
    ]
    if citation.evidence_id:
        assets.append(("evidence", citation.evidence_id))
    if citation.fact_id:
        assets.append(("fact", citation.fact_id))
    for asset_type, asset_id in assets:
        found = connection.execute(
            "SELECT 1 FROM task_committed_assets "
            "WHERE task_id = ? AND asset_type = ? AND asset_id = ?",
            (task_id, asset_type, asset_id),
        ).fetchone()
        if found is None:
            raise IntelError(
                "INVALID_CITATION",
                f"引用资产不属于当前任务: {asset_type}/{asset_id}",
            )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _task_state(connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM task_state WHERE task_id = ?", (task_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"任务状态不存在: {task_id}")
    return row


def _find_message(
    connection: sqlite3.Connection, message_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM messages WHERE id = ?", (message_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"消息不存在: {message_id}")
    return row


def _find_action(
    connection: sqlite3.Connection, action_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM action_requests WHERE id = ?", (action_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"动作请求不存在: {action_id}")
    return row


def _find_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM research_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"研究运行不存在: {run_id}")
    return row


def _find_checkpoint(
    connection: sqlite3.Connection, checkpoint_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM research_checkpoints WHERE id = ?", (checkpoint_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"研究检查点不存在: {checkpoint_id}")
    return row


def _find_report(
    connection: sqlite3.Connection, report_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM report_versions WHERE id = ?", (report_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"报告版本不存在: {report_id}")
    return row


def _invalid_transition(kind: str, old: str, new: str) -> IntelError:
    return IntelError(
        "INVALID_STATE_TRANSITION", f"{kind} 状态不能从 {old} 变为 {new}"
    )


def _required(row: sqlite3.Row | None, kind: str) -> sqlite3.Row:
    if row is None:
        raise IntelError("STORAGE_CORRUPT", f"写入后未找到 {kind}")
    return row


def _row_to_conversation(row: sqlite3.Row) -> Conversation:
    return Conversation.model_validate(dict(row))


def _row_to_epoch(row: sqlite3.Row) -> ConversationEpoch:
    return ConversationEpoch.model_validate(dict(row))


def _row_to_message(row: sqlite3.Row) -> Message:
    value = dict(row)
    intent_json = value.pop("intent_json")
    value["intent"] = (
        json.loads(intent_json) if intent_json is not None else None
    )
    return Message.model_validate(value)


def _row_to_citation(row: sqlite3.Row) -> MessageCitation:
    return MessageCitation.model_validate(dict(row))


def _row_to_action(row: sqlite3.Row) -> ActionRequest:
    value = dict(row)
    value["immutable_payload"] = json.loads(
        value.pop("immutable_payload_json")
    )
    return ActionRequest.model_validate(value)


def _row_to_run(row: sqlite3.Row) -> ResearchRun:
    value = dict(row)
    value["input_snapshot"] = json.loads(value.pop("input_snapshot_json"))
    return ResearchRun.model_validate(value)


def _row_to_checkpoint(row: sqlite3.Row) -> ResearchCheckpoint:
    return ResearchCheckpoint.model_validate(dict(row))


def _row_to_report(row: sqlite3.Row) -> ReportVersion:
    return ReportVersion.model_validate(dict(row))


def _row_to_event(row: sqlite3.Row) -> ConversationEvent:
    value = dict(row)
    value["data"] = json.loads(value.pop("data_json"))
    return ConversationEvent.model_validate(value)
