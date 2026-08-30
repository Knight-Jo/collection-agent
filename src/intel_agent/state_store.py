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
    AssetRevisionRef,
    CitationDraft,
    CommittedAssetType,
    CommittedResearchSnapshot,
    Conversation,
    ConversationEpoch,
    ConversationEvent,
    IntelError,
    Message,
    MessageCitation,
    MessageProcessingAttempt,
    ReportVersion,
    ResearchBrief,
    ResearchCheckpoint,
    ResearchOutcome,
    ResearchRun,
    ResearchRunStatus,
    RunWorkspace,
    SearchPlanVersion,
    TimelineEntry,
    new_id,
    utc_now,
)
from .state_db import connect_state_db, initialize_state_db
from .trajectory import _redact_payload


def _redact_event_data(data: dict[str, object]) -> dict[str, object]:
    return _redact_payload(data)


ACTION_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"queued", "rejected", "expired"},
    "queued": {"executing", "expired", "cancelled"},
    "executing": {"succeeded", "failed", "cancelled"},
}
RUN_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled"},
    "running": {"stopping", "succeeded", "failed", "interrupted"},
    "stopping": {"stopped", "interrupted"},
}


class StateStore:
    """Persist conversational research state in a local SQLite database.

    The store is the single durable repository behind the conversation
    layer: conversations, epochs, messages, processing attempts, actions,
    runs, checkpoints, reports, and events are all written through here.
    Mutating methods run in ``BEGIN IMMEDIATE`` transactions and enforce
    the allowed lifecycle transitions (see ``ACTION_TRANSITIONS`` and
    ``RUN_TRANSITIONS``), raising ``IntelError`` on invalid moves, so the
    runtime layer can trust that persisted state stays consistent and
    survives process restarts.

    Attributes
    ----------
    cwd:
        Working directory where the SQLite state database lives; the
        schema is created on first use. The store holds no other state,
        and each call opens and closes its own connection.

    Public methods
    --------------
    Conversations and epochs:
        create_conversation / list_conversations / archive_conversation /
        restore_conversation / register_task / get_conversation /
        get_conversation_by_id manage the lifecycle from intake through
        task binding to archiving. start_epoch / active_epoch /
        active_epoch_for_conversation / update_epoch_summary keep the
        active context window and its rolling summary.
    Messages:
        add_user_message / complete_message / get_message /
        reply_for_message / list_messages /
        list_messages_for_conversation / conversation_message_view /
        citations_for_message append and read dialogue.
        bind_intake_task atomically binds an intake conversation to a new
        task and its queued initial run. set_message_processing /
        ensure_processing_attempt / retry_processing_attempt /
        transition_processing_attempt / latest_processing_attempt /
        fail_message / cancel_message / pending_messages drive the
        per-message processing lifecycle and restart recovery.
    Actions:
        create_action / get_action / list_actions / confirm_action /
        transition_action persist proposals and apply lifecycle
        transitions.
    Runs:
        create_run / transition_run / get_run / list_runs / retry_run /
        cancel_run / stop_run / finish_stop / recover_expired_runs manage
        research execution with leases. create_search_plan_version /
        get_search_plan_version / active_search_plan record immutable plan
        versions; list_runs_for_conversation lists runs for one
        conversation.
    Checkpoints and assets:
        start_checkpoint / commit_checkpoint / committed_state_version
        advance the task's committed research state;
        seed_committed_assets / committed_asset_ids expose which assets
        are visible at that state.
    Reports:
        create_report_draft / get_report / list_reports /
        abandon_report / publish_report manage report versions, with
        publish rejecting stale content unless explicitly pinned.
    Events:
        append_event / events_after / events_after_conversation /
        timeline_after record durable events and the conversation
        timeline for reconnect catch-up.
    """

    def __init__(self, cwd: Path):
        self.cwd = cwd
        initialize_state_db(cwd)

    def create_conversation(
        self, client_conversation_id: str | None = None
    ) -> Conversation:
        """Create an unbound intake conversation and its first epoch."""
        now = utc_now()
        conversation_id = client_conversation_id or new_id("conversation")
        epoch_id = new_id("epoch")
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if existing is not None:
                return _row_to_conversation(existing)
            connection.execute(
                "INSERT INTO conversations("
                "id, status, title, created_at, updated_at"
                ") VALUES (?, 'intake', '新对话', ?, ?)",
                (conversation_id, now, now),
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

    def list_conversations(
        self, *, archived: bool = False
    ) -> list[Conversation]:
        """List visible or archived conversations by recent activity."""
        status_filter = "= 'archived'" if archived else "!= 'archived'"
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                f"SELECT * FROM conversations WHERE status {status_filter} "
                "ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [_row_to_conversation(row) for row in rows]

    def archive_conversation(self, conversation_id: str) -> Conversation:
        """Hide a conversation without changing its research task."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if existing is None:
                raise IntelError(
                    "NOT_FOUND", f"任务会话不存在: {conversation_id}"
                )
            if existing["status"] == "archived":
                return _row_to_conversation(existing)
            if existing["task_id"] is not None:
                unfinished = connection.execute(
                    "SELECT 1 FROM research_runs WHERE task_id = ? "
                    "AND status IN ('queued', 'running', 'stopping') LIMIT 1",
                    (existing["task_id"],),
                ).fetchone()
                if unfinished is not None:
                    raise IntelError(
                        "CONVERSATION_BUSY",
                        "当前调研尚未结束，请先停止或取消后再归档",
                    )
            connection.execute(
                "UPDATE conversations SET status = 'archived', updated_at = ? "
                "WHERE id = ?",
                (now, conversation_id),
            )
            _insert_event(
                connection, conversation_id, "conversation.archived", {}, now
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return _row_to_conversation(_required(row, "conversation"))

    def restore_conversation(self, conversation_id: str) -> Conversation:
        """Restore one archived conversation without changing its task."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if existing is None:
                raise IntelError(
                    "NOT_FOUND", f"任务会话不存在: {conversation_id}"
                )
            if existing["status"] != "archived":
                return _row_to_conversation(existing)
            status = "active" if existing["task_id"] else "intake"
            connection.execute(
                "UPDATE conversations SET status = ?, updated_at = ? "
                "WHERE id = ?",
                (status, now, conversation_id),
            )
            _insert_event(
                connection, conversation_id, "conversation.restored", {}, now
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return _row_to_conversation(_required(row, "conversation"))

    def register_task(self, task_id: str) -> Conversation:
        """Return or lazily create a conversation for a legacy task."""
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
                "id, task_id, status, title, created_at, updated_at"
                ") VALUES (?, ?, 'active', '历史调研', ?, ?)",
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

    def active_epoch_for_conversation(
        self, conversation_id: str
    ) -> ConversationEpoch:
        """Return one conversation's active context epoch."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT conversation_epochs.* FROM conversation_epochs "
                "JOIN conversations ON conversations.active_epoch_id = "
                "conversation_epochs.id WHERE conversations.id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise IntelError(
                "NOT_FOUND", f"活动会话上下文不存在: {conversation_id}"
            )
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
        conversation_or_task_id: str,
        content: str,
        client_message_id: str,
    ) -> Message:
        """Append a user message, returning the original on an exact retry."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE id = ? OR task_id = ? "
                "ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END LIMIT 1",
                (
                    conversation_or_task_id,
                    conversation_or_task_id,
                    conversation_or_task_id,
                ),
            ).fetchone()
            if conversation is None:
                raise IntelError(
                    "NOT_FOUND",
                    f"任务会话不存在: {conversation_or_task_id}",
                )
            if conversation["status"] == "archived":
                raise IntelError(
                    "CONVERSATION_ARCHIVED",
                    "已归档会话需要恢复后才能继续对话",
                )
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
            event_sequence = _insert_event(
                connection,
                conversation_id,
                "message.accepted",
                {"message_id": message_id},
                now,
                message_id=message_id,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "message",
                {"message_id": message_id, "role": "user"},
                now,
                source_event_sequence=event_sequence,
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(_required(row, "message"))

    def bind_intake_task(
        self,
        conversation_id: str,
        trigger_message_id: str,
        brief: ResearchBrief,
    ) -> Conversation:
        """Atomically bind intake to one task and queued initial run."""
        from .models import SufficiencyCriteria
        from .task import build_task

        task = build_task(
            brief.topic,
            brief.key_questions,
            SufficiencyCriteria(),
            objective=brief.objective,
            scope=brief.scope,
        )
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise IntelError(
                    "NOT_FOUND", f"任务会话不存在: {conversation_id}"
                )
            existing = connection.execute(
                "SELECT task_id FROM research_briefs "
                "WHERE trigger_message_id = ?",
                (trigger_message_id,),
            ).fetchone()
            if existing is not None:
                row = connection.execute(
                    "SELECT * FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                return _row_to_conversation(_required(row, "conversation"))
            if conversation["status"] != "intake" or conversation["task_id"]:
                raise IntelError("INVALID_STATE_TRANSITION", "会话已绑定任务")
            message = _find_message(connection, trigger_message_id)
            if message["conversation_id"] != conversation_id:
                raise IntelError("INVALID_INPUT", "触发消息不属于当前会话")

            connection.execute(
                "INSERT INTO task_state("
                "task_id, task_json, origin_message_id, updated_at"
                ") VALUES (?, ?, ?, ?)",
                (
                    task.id,
                    task.model_dump_json(),
                    trigger_message_id,
                    now,
                ),
            )
            brief_id = new_id("brief")
            connection.execute(
                "INSERT INTO research_briefs("
                "id, conversation_id, trigger_message_id, task_id, "
                "schema_version, brief_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    brief_id,
                    conversation_id,
                    trigger_message_id,
                    task.id,
                    brief.schema_version,
                    brief.model_dump_json(),
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET task_id = ?, status = 'active', "
                "title = ?, updated_at = ? WHERE id = ?",
                (task.id, brief.topic, now, conversation_id),
            )
            run_id = new_id("run")
            connection.execute(
                "INSERT INTO research_runs("
                "id, task_id, run_type, trigger_message_id, "
                "input_committed_state_version, input_snapshot_json, "
                "status, created_at"
                ") VALUES (?, ?, 'initial', ?, 0, ?, 'queued', ?)",
                (
                    run_id,
                    task.id,
                    trigger_message_id,
                    _json({"research_brief_id": brief_id}),
                    now,
                ),
            )
            _insert_event(
                connection,
                conversation_id,
                "task.created",
                {"task_id": task.id},
                now,
                message_id=trigger_message_id,
            )
            event_sequence = _insert_event(
                connection,
                conversation_id,
                "run.queued",
                {"run_id": run_id},
                now,
                research_run_id=run_id,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "task_created",
                {"task_id": task.id, "run_id": run_id},
                now,
                source_event_sequence=event_sequence,
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return _row_to_conversation(_required(row, "conversation"))

    def list_runs_for_conversation(
        self, conversation_id: str
    ) -> list[ResearchRun]:
        """List bound task runs, or none while the conversation is intake."""
        conversation = self.get_conversation_by_id(conversation_id)
        if conversation.task_id is None:
            return []
        return self.list_runs(conversation.task_id)

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

    def ensure_processing_attempt(
        self, message_id: str
    ) -> MessageProcessingAttempt:
        """Return an existing attempt or create the first one."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _find_message(connection, message_id)
            existing = connection.execute(
                "SELECT * FROM message_processing_attempts "
                "WHERE user_message_id = ? ORDER BY attempt DESC LIMIT 1",
                (message_id,),
            ).fetchone()
            if existing is not None:
                return _row_to_processing_attempt(existing)
            attempt_id = new_id("attempt")
            connection.execute(
                "INSERT INTO message_processing_attempts("
                "id, user_message_id, attempt, status, started_at"
                ") VALUES (?, ?, 1, 'accepted', ?)",
                (attempt_id, message_id, now),
            )
            row = connection.execute(
                "SELECT * FROM message_processing_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
        return _row_to_processing_attempt(_required(row, "processing attempt"))

    def retry_processing_attempt(
        self, message_id: str
    ) -> MessageProcessingAttempt:
        """Create the next attempt after a failed or cancelled one."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _find_message(connection, message_id)
            latest = connection.execute(
                "SELECT * FROM message_processing_attempts "
                "WHERE user_message_id = ? ORDER BY attempt DESC LIMIT 1",
                (message_id,),
            ).fetchone()
            if latest is None:
                attempt = 1
            elif latest["status"] not in {"failed", "cancelled"}:
                return _row_to_processing_attempt(latest)
            else:
                attempt = latest["attempt"] + 1
            attempt_id = new_id("attempt")
            connection.execute(
                "INSERT INTO message_processing_attempts("
                "id, user_message_id, attempt, status, started_at"
                ") VALUES (?, ?, ?, 'accepted', ?)",
                (attempt_id, message_id, attempt, now),
            )
            row = connection.execute(
                "SELECT * FROM message_processing_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
        return _row_to_processing_attempt(_required(row, "processing attempt"))

    def transition_processing_attempt(
        self,
        attempt_id: str,
        status: str,
        *,
        assistant_message_id: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> MessageProcessingAttempt:
        """Advance processing independently from the user message."""
        now = utc_now()
        completed_at = (
            now if status in {"completed", "failed", "cancelled"} else None
        )
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE message_processing_attempts SET status = ?, "
                "assistant_message_id = COALESCE(?, assistant_message_id), "
                "error_code = ?, error_detail = ?, completed_at = ? "
                "WHERE id = ?",
                (
                    status,
                    assistant_message_id,
                    error_code,
                    error_detail,
                    completed_at,
                    attempt_id,
                ),
            )
            if cursor.rowcount == 0:
                raise IntelError(
                    "NOT_FOUND", f"消息处理尝试不存在: {attempt_id}"
                )
            row = connection.execute(
                "SELECT * FROM message_processing_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
        return _row_to_processing_attempt(_required(row, "processing attempt"))

    def latest_processing_attempt(
        self, message_id: str
    ) -> MessageProcessingAttempt:
        """Return the most recent attempt for a user message."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM message_processing_attempts "
                "WHERE user_message_id = ? ORDER BY attempt DESC LIMIT 1",
                (message_id,),
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", "消息尚无处理尝试")
        return _row_to_processing_attempt(row)

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
        *,
        mark_user_completed: bool = True,
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

            if mark_user_completed:
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
            event_sequence = _insert_event(
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
            _insert_timeline_entry(
                connection,
                user["conversation_id"],
                "message",
                {"message_id": assistant_id, "role": "assistant"},
                now,
                source_event_sequence=event_sequence,
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
                "AND NOT EXISTS (SELECT 1 FROM message_processing_attempts a "
                "WHERE a.user_message_id = messages.id "
                "AND a.status IN ('completed', 'failed', 'cancelled')) "
                "ORDER BY messages.created_at, messages.rowid"
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def list_messages_for_conversation(
        self, conversation_id: str, *, active_epoch_only: bool = True
    ) -> list[Message]:
        """List messages without requiring a bound task."""
        where = "AND messages.epoch_id = conversations.active_epoch_id"
        if not active_epoch_only:
            where = ""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                f"SELECT messages.* FROM messages JOIN conversations "
                f"ON conversations.id = messages.conversation_id "
                f"WHERE conversations.id = ? {where} "
                f"ORDER BY messages.sequence",
                (conversation_id,),
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def conversation_message_view(
        self, conversation_id: str
    ) -> tuple[
        list[Message],
        dict[str, list[MessageCitation]],
        dict[str, MessageProcessingAttempt],
    ]:
        """Read active messages and their display metadata in one snapshot."""
        with connect_state_db(self.cwd) as connection:
            messages = connection.execute(
                "SELECT messages.* FROM messages JOIN conversations "
                "ON conversations.id = messages.conversation_id "
                "WHERE conversations.id = ? "
                "AND messages.epoch_id = conversations.active_epoch_id "
                "ORDER BY messages.sequence",
                (conversation_id,),
            ).fetchall()
            citations = connection.execute(
                "SELECT message_citations.* FROM message_citations "
                "JOIN messages ON messages.id = message_citations.message_id "
                "JOIN conversations ON conversations.id = "
                "messages.conversation_id "
                "WHERE conversations.id = ? "
                "AND messages.epoch_id = conversations.active_epoch_id "
                "ORDER BY messages.sequence, message_citations.sequence",
                (conversation_id,),
            ).fetchall()
            attempts = connection.execute(
                "SELECT attempts.* FROM message_processing_attempts attempts "
                "JOIN messages ON messages.id = attempts.user_message_id "
                "JOIN conversations ON conversations.id = "
                "messages.conversation_id "
                "WHERE conversations.id = ? "
                "AND messages.epoch_id = conversations.active_epoch_id "
                "AND attempts.attempt = ("
                "SELECT MAX(latest.attempt) FROM message_processing_attempts "
                "latest WHERE latest.user_message_id = attempts.user_message_id"
                ") ORDER BY messages.sequence",
                (conversation_id,),
            ).fetchall()
        citations_by_message: dict[str, list[MessageCitation]] = {}
        for row in citations:
            citations_by_message.setdefault(row["message_id"], []).append(
                _row_to_citation(row)
            )
        attempts_by_message = {
            row["user_message_id"]: _row_to_processing_attempt(row)
            for row in attempts
        }
        return (
            [_row_to_message(row) for row in messages],
            citations_by_message,
            attempts_by_message,
        )

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

    def claim_action(self, action_id: str) -> ActionRequest:
        """Atomically claim a queued action for one executor."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = _find_action(connection, action_id)
            if action["status"] == "executing":
                return _row_to_action(action)
            if action["status"] != "queued":
                raise _invalid_transition(
                    "action", action["status"], "executing"
                )
            current = _task_state(connection, action["task_id"])[
                "current_committed_state_version"
            ]
            if current != action["precondition_committed_state_version"]:
                connection.execute(
                    "UPDATE action_requests SET status = 'expired', completed_at = ? "
                    "WHERE id = ?",
                    (now, action_id),
                )
            else:
                connection.execute(
                    "UPDATE action_requests SET status = 'executing', executing_at = ? "
                    "WHERE id = ? AND status = 'queued'",
                    (now, action_id),
                )
            row = connection.execute(
                "SELECT * FROM action_requests WHERE id = ?", (action_id,)
            ).fetchone()
        return _row_to_action(_required(row, "action request"))

    def claim_run(
        self,
        run_id: str,
        *,
        phase: str,
        lease_owner: str,
        lease_expires_at: str | None = None,
    ) -> ResearchRun:
        """Atomically claim one queued Run against its input version."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _find_run(connection, run_id)
            if run["status"] == "running":
                return _row_to_run(run)
            if run["status"] != "queued":
                raise _invalid_transition("run", run["status"], "running")
            state = _task_state(connection, run["task_id"])
            if (
                state["current_committed_state_version"]
                != run["input_committed_state_version"]
            ):
                raise IntelError("STALE_RUN", "运行基于过期的研究状态")
            connection.execute(
                "UPDATE research_runs SET status = 'running', phase = ?, "
                "started_at = ?, lease_owner = ?, lease_expires_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (phase, now, lease_owner, lease_expires_at, run_id),
            )
            conversation_id = _conversation_id_for_run(connection, run)
            event_sequence = _insert_event(
                connection,
                conversation_id,
                "run.running",
                {"run_id": run_id, "status": "running", "phase": phase},
                now,
                research_run_id=run_id,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "run_status",
                {"run_id": run_id, "status": "running", "phase": phase},
                now,
                source_event_sequence=event_sequence,
            )
            row = connection.execute(
                "SELECT * FROM research_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(_required(row, "research run"))

    def finish_run(
        self,
        run_id: str,
        *,
        expected_input_version: int,
        staged_manifest: Iterable[AssetRevisionRef] = (),
        outcome: str = "committed",
    ) -> ResearchOutcome:
        """Atomically finalize a running Run and its committed snapshot."""
        if outcome not in {"committed", "no_progress"}:
            raise IntelError("INVALID_INPUT", "无效的运行结果")
        now = utc_now()
        manifest = list(staged_manifest)
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _find_run(connection, run_id)
            existing = connection.execute(
                "SELECT * FROM research_outcomes WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing is not None:
                return _row_to_outcome(existing)
            if run["status"] != "running":
                raise IntelError(
                    "RUN_NOT_RUNNING", "只有 running 运行可以完成"
                )
            state = _task_state(connection, run["task_id"])
            if (
                state["current_committed_state_version"]
                != expected_input_version
            ):
                raise IntelError("STALE_CHECKPOINT", "运行基于过期的研究状态")
            workspace = _find_workspace(connection, run_id)
            if workspace["status"] != "open":
                raise IntelError("WORKSPACE_CLOSED", "运行工作区已关闭")
            seen: set[tuple[str, str, str]] = set()
            for revision in manifest:
                key = (
                    revision.asset_type,
                    revision.logical_id,
                    revision.revision_id,
                )
                if key in seen:
                    continue
                seen.add(key)
                if revision.task_id != run["task_id"]:
                    raise IntelError(
                        "TASK_MISMATCH", "revision 不属于运行任务"
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO run_workspace_assets("
                    "run_id, task_id, asset_type, logical_id, revision_id, content_sha256) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        revision.task_id,
                        revision.asset_type,
                        revision.logical_id,
                        revision.revision_id,
                        revision.content_sha256,
                    ),
                )
            manifest_rows = connection.execute(
                "SELECT asset_type, logical_id, revision_id, content_sha256, task_id "
                "FROM run_workspace_assets WHERE run_id = ? "
                "ORDER BY asset_type, logical_id, revision_id",
                (run_id,),
            ).fetchall()
            normalized_manifest = [
                {
                    "asset_type": row["asset_type"],
                    "logical_id": row["logical_id"],
                    "revision_id": row["revision_id"],
                    "content_sha256": row["content_sha256"],
                    "task_id": row["task_id"],
                }
                for row in manifest_rows
            ]
            has_progress = outcome == "committed" and bool(normalized_manifest)
            output_version = (
                expected_input_version + 1
                if has_progress
                else expected_input_version
            )
            checkpoint_sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM research_checkpoints "
                "WHERE research_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            checkpoint_id = new_id("checkpoint")
            fingerprint = _manifest_fingerprint(normalized_manifest)
            connection.execute(
                "INSERT INTO research_checkpoints("
                "id, task_id, research_run_id, sequence, input_committed_state_version, "
                "output_committed_state_version, status, reason, started_at, committed_at, "
                "snapshot_fingerprint) VALUES (?, ?, ?, ?, ?, ?, 'committed', ?, ?, ?, ?)",
                (
                    checkpoint_id,
                    run["task_id"],
                    run_id,
                    checkpoint_sequence,
                    expected_input_version,
                    output_version,
                    "run finished" if has_progress else "no progress",
                    now,
                    now,
                    fingerprint,
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO checkpoint_assets("
                "checkpoint_id, task_id, asset_type, asset_id) "
                "VALUES (?, ?, ?, ?)",
                (
                    (
                        checkpoint_id,
                        run["task_id"],
                        item["asset_type"],
                        item["logical_id"],
                    )
                    for item in normalized_manifest
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO task_committed_assets("
                "task_id, asset_type, asset_id, committed_state_version) "
                "VALUES (?, ?, ?, ?)",
                (
                    (
                        run["task_id"],
                        item["asset_type"],
                        item["logical_id"],
                        output_version,
                    )
                    for item in normalized_manifest
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO committed_snapshots("
                "id, task_id, version, checkpoint_id, asset_manifest_json, fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("snapshot"),
                    run["task_id"],
                    output_version,
                    checkpoint_id,
                    _json(normalized_manifest),
                    fingerprint,
                    now,
                ),
            )
            connection.execute(
                "UPDATE task_state SET current_committed_state_version = ?, updated_at = ? "
                "WHERE task_id = ?",
                (output_version, now, run["task_id"]),
            )
            connection.execute(
                "UPDATE run_workspaces SET status = 'committed' WHERE run_id = ?",
                (run_id,),
            )
            connection.execute(
                "UPDATE research_runs SET status = 'succeeded', completed_at = ?, "
                "outcome = ?, phase = 'checkpointing', lease_owner = NULL, lease_expires_at = NULL "
                "WHERE id = ?",
                (now, "sufficient" if has_progress else "with_gaps", run_id),
            )
            if run["action_request_id"]:
                connection.execute(
                    "UPDATE action_requests SET status = 'succeeded', completed_at = ?, "
                    "applied_checkpoint_id = ? WHERE id = ? AND status = 'executing'",
                    (now, checkpoint_id, run["action_request_id"]),
                )
            conversation_id = _conversation_id_for_run(connection, run)
            checkpoint_event_sequence = _insert_event(
                connection,
                conversation_id,
                "checkpoint.committed",
                {
                    "checkpoint_id": checkpoint_id,
                    "committed_state_version": output_version,
                    "snapshot_fingerprint": fingerprint,
                },
                now,
                research_run_id=run_id,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "checkpoint",
                {
                    "checkpoint_id": checkpoint_id,
                    "committed_state_version": output_version,
                },
                now,
                source_event_sequence=checkpoint_event_sequence,
            )
            run_event_sequence = _insert_event(
                connection,
                conversation_id,
                "run.succeeded",
                {
                    "run_id": run_id,
                    "status": "succeeded",
                    "outcome": outcome,
                    "committed_state_version": output_version,
                },
                now,
                research_run_id=run_id,
                action_request_id=run["action_request_id"],
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "run_status",
                {
                    "run_id": run_id,
                    "status": "succeeded",
                    "outcome": outcome,
                },
                now,
                source_event_sequence=run_event_sequence,
            )
            connection.execute(
                "INSERT INTO research_outcomes(run_id, task_id, outcome, committed_state_version, "
                "snapshot_fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    run["task_id"],
                    outcome,
                    output_version,
                    fingerprint,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM research_outcomes WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _row_to_outcome(_required(row, "research outcome"))

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
            connection.execute(
                "INSERT INTO run_workspaces(run_id, task_id, base_version, status) "
                "VALUES (?, ?, ?, 'open')",
                (run_id, task_id, input_committed_state_version),
            )
        return _row_to_run(_required(row, "research run"))

    def stage_revision(
        self, run_id: str, revision: AssetRevisionRef
    ) -> RunWorkspace:
        """Stage one immutable asset reference in the run workspace."""
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            workspace = _find_workspace(connection, run_id)
            if workspace["status"] != "open":
                raise IntelError("WORKSPACE_CLOSED", "运行工作区已关闭")
            if revision.task_id != workspace["task_id"]:
                raise IntelError("TASK_MISMATCH", "revision 不属于运行任务")
            connection.execute(
                "INSERT OR IGNORE INTO run_workspace_assets("
                "run_id, task_id, asset_type, logical_id, revision_id, content_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    revision.task_id,
                    revision.asset_type,
                    revision.logical_id,
                    revision.revision_id,
                    revision.content_sha256,
                ),
            )
        return self.run_view(run_id)

    def stage_asset(
        self,
        run_id: str,
        asset_type: CommittedAssetType,
        logical_id: str,
        content_sha256: str,
    ) -> RunWorkspace:
        """Stage a content-addressed asset produced by the active Run."""
        return self.stage_revision(
            run_id,
            AssetRevisionRef(
                asset_type=asset_type,
                logical_id=logical_id,
                revision_id=logical_id,
                content_sha256=content_sha256,
                task_id=self.get_run(run_id).task_id,
            ),
        )

    def committed_snapshot(
        self, task_id: str, version: int | None = None
    ) -> CommittedResearchSnapshot:
        """Read one immutable snapshot, creating an empty version-zero baseline."""
        with connect_state_db(self.cwd) as connection:
            _task_state(connection, task_id)
            if version is None:
                version = connection.execute(
                    "SELECT current_committed_state_version FROM task_state WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            row = connection.execute(
                "SELECT * FROM committed_snapshots WHERE task_id = ? AND version = ?",
                (task_id, version),
            ).fetchone()
            if row is None and version == 0:
                manifest: list[dict[str, object]] = []
                fingerprint = _manifest_fingerprint(manifest)
                snapshot_id = new_id("snapshot")
                connection.execute(
                    "INSERT OR IGNORE INTO committed_snapshots("
                    "id, task_id, version, asset_manifest_json, fingerprint, created_at) "
                    "VALUES (?, ?, 0, ?, ?, ?)",
                    (
                        snapshot_id,
                        task_id,
                        _json(manifest),
                        fingerprint,
                        utc_now(),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM committed_snapshots WHERE task_id = ? AND version = 0",
                    (task_id,),
                ).fetchone()
        return _row_to_snapshot(_required(row, "committed snapshot"))

    def run_view(self, run_id: str) -> RunWorkspace:
        """Return staged revisions for an open run only."""
        with connect_state_db(self.cwd) as connection:
            workspace = _find_workspace(connection, run_id)
            if workspace["status"] != "open":
                raise IntelError("WORKSPACE_CLOSED", "运行工作区已关闭")
            rows = connection.execute(
                "SELECT * FROM run_workspace_assets WHERE run_id = ? "
                "ORDER BY asset_type, logical_id, revision_id",
                (run_id,),
            ).fetchall()
        return RunWorkspace(
            run_id=workspace["run_id"],
            task_id=workspace["task_id"],
            base_version=workspace["base_version"],
            status=workspace["status"],
            staged_revisions=[
                AssetRevisionRef(
                    asset_type=row["asset_type"],
                    logical_id=row["logical_id"],
                    revision_id=row["revision_id"],
                    content_sha256=row["content_sha256"],
                    task_id=row["task_id"],
                )
                for row in rows
            ],
        )

    def transition_run(
        self,
        run_id: str,
        new_status: ResearchRunStatus,
        *,
        phase: str | None = None,
        outcome: str | None = None,
        error: str | None = None,
        lease_owner: str | None = None,
        lease_expires_at: str | None = None,
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
                in {
                    "stopped",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "interrupted",
                }
                else None
            )
            connection.execute(
                "UPDATE research_runs SET status = ?, "
                "started_at = COALESCE(?, started_at), completed_at = ?, "
                "phase = COALESCE(?, phase), outcome = ?, error = ?, "
                "lease_owner = ?, lease_expires_at = ? "
                "WHERE id = ?",
                (
                    new_status,
                    started_at,
                    completed_at,
                    phase,
                    outcome,
                    error,
                    lease_owner
                    if new_status in {"running", "stopping"}
                    else None,
                    lease_expires_at
                    if new_status in {"running", "stopping"}
                    else None,
                    run_id,
                ),
            )
            if new_status in {
                "stopped",
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
            }:
                workspace_status = (
                    "committed" if new_status == "succeeded" else "abandoned"
                )
                connection.execute(
                    "UPDATE run_workspaces SET status = ? WHERE run_id = ?",
                    (workspace_status, run_id),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO research_outcomes("
                    "run_id, task_id, outcome, committed_state_version, created_at) "
                    "VALUES (?, ?, ?, (SELECT current_committed_state_version "
                    "FROM task_state WHERE task_id = ?), ?)",
                    (
                        run_id,
                        run["task_id"],
                        "committed"
                        if new_status == "succeeded"
                        else new_status,
                        run["task_id"],
                        now,
                    ),
                )
            conversation_id = _conversation_id_for_run(connection, run)
            event_sequence = _insert_event(
                connection,
                conversation_id,
                f"run.{new_status}",
                {"run_id": run_id, "status": new_status},
                now,
                research_run_id=run_id,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "run_status",
                {"run_id": run_id, "status": new_status},
                now,
                source_event_sequence=event_sequence,
            )
            row = connection.execute(
                "SELECT * FROM research_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(_required(row, "research run"))

    def create_search_plan_version(
        self,
        run_id: str,
        plan: dict[str, object],
        *,
        trigger_message_id: str | None = None,
        action_request_id: str | None = None,
    ) -> SearchPlanVersion:
        """Append an immutable plan version and make it active for the Run."""
        now = utc_now()
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _find_run(connection, run_id)
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM search_plan_versions WHERE research_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            plan_id = new_id("search-plan")
            connection.execute(
                "INSERT INTO search_plan_versions("
                "id, task_id, research_run_id, sequence, plan_json, "
                "trigger_message_id, action_request_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan_id,
                    run["task_id"],
                    run_id,
                    sequence,
                    _json(plan),
                    trigger_message_id,
                    action_request_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE research_runs SET active_search_plan_version_id = ?, "
                "initial_search_plan_version_id = "
                "COALESCE(initial_search_plan_version_id, ?) WHERE id = ?",
                (plan_id, plan_id, run_id),
            )
            row = connection.execute(
                "SELECT * FROM search_plan_versions WHERE id = ?",
                (plan_id,),
            ).fetchone()
        return _row_to_search_plan(_required(row, "search plan version"))

    def get_search_plan_version(self, plan_id: str) -> SearchPlanVersion:
        """Return one immutable SearchPlan version by stable ID."""
        with connect_state_db(self.cwd) as connection:
            row = connection.execute(
                "SELECT * FROM search_plan_versions WHERE id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise IntelError("NOT_FOUND", f"检索计划版本不存在: {plan_id}")
        return _row_to_search_plan(row)

    def active_search_plan(self, run_id: str) -> SearchPlanVersion:
        """Resolve the current plan while exposing its stable version ID."""
        run = self.get_run(run_id)
        if run.active_search_plan_version_id is None:
            raise IntelError("NOT_FOUND", f"研究运行尚无检索计划: {run_id}")
        return self.get_search_plan_version(run.active_search_plan_version_id)

    def cancel_run(self, run_id: str) -> ResearchRun:
        """Cancel a queued run before execution starts."""
        return self.transition_run(run_id, "cancelled")

    def stop_run(self, run_id: str) -> ResearchRun:
        """Request cooperative stopping for a running run."""
        run = self.get_run(run_id)
        return self.transition_run(
            run_id,
            "stopping",
            lease_owner=run.lease_owner,
            lease_expires_at=run.lease_expires_at,
        )

    def finish_stop(self, run_id: str) -> ResearchRun:
        """Finish a stop after in-flight work can no longer commit."""
        return self.transition_run(run_id, "stopped")

    def recover_expired_runs(
        self, now: str | None = None
    ) -> list[ResearchRun]:
        """Mark abandoned active runs interrupted; never resume them in place.

        Startup recovery has no reliable cross-process heartbeat, so the
        no-argument form treats every active run as belonging to an exited
        runtime.  Tests and explicit reapers may pass a timestamp to retain
        the legacy expiry-only behavior.
        """
        recovered: list[ResearchRun] = []
        with connect_state_db(self.cwd) as connection:
            if now is None:
                rows = connection.execute(
                    "SELECT * FROM research_runs "
                    "WHERE status IN ('running', 'stopping') "
                    "ORDER BY created_at, rowid"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM research_runs "
                    "WHERE status IN ('running', 'stopping') "
                    "AND (lease_expires_at IS NULL OR lease_expires_at < ?) "
                    "ORDER BY created_at, rowid",
                    (now,),
                ).fetchall()
        for row in rows:
            recovered.append(
                self.transition_run(
                    row["id"],
                    "interrupted",
                    error="runtime lease expired",
                )
            )
        return recovered

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
            if run["status"] != "running":
                raise IntelError(
                    "RUN_NOT_RUNNING", "只有 running 运行可以开始检查点"
                )
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
            run = _find_run(connection, checkpoint["research_run_id"])
            if run["status"] in {
                "stopping",
                "stopped",
                "cancelled",
                "interrupted",
            }:
                raise IntelError(
                    "RUN_STOPPING", "运行停止后未提交材料不能进入事实状态"
                )
            if run["status"] != "running":
                raise IntelError(
                    "RUN_NOT_RUNNING", "只有 running 运行可以提交检查点"
                )
            state = _task_state(connection, checkpoint["task_id"])
            input_version = checkpoint["input_committed_state_version"]
            if state["current_committed_state_version"] != input_version:
                raise IntelError(
                    "STALE_CHECKPOINT", "检查点基于过期的研究状态"
                )
            output_version = input_version + 1
            asset_values = list(assets)
            if not asset_values:
                output_version = input_version
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
            staged_rows = connection.execute(
                "SELECT asset_type, logical_id, revision_id, content_sha256, task_id "
                "FROM run_workspace_assets WHERE run_id = ? "
                "ORDER BY asset_type, logical_id, revision_id",
                (checkpoint["research_run_id"],),
            ).fetchall()
            manifest = [
                {
                    "asset_type": row["asset_type"],
                    "logical_id": row["logical_id"],
                    "revision_id": row["revision_id"],
                    "content_sha256": row["content_sha256"],
                    "task_id": row["task_id"],
                }
                for row in staged_rows
            ]
            fingerprint = _manifest_fingerprint(manifest)
            connection.execute(
                "INSERT OR IGNORE INTO committed_snapshots("
                "id, task_id, version, checkpoint_id, asset_manifest_json, "
                "fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("snapshot"),
                    checkpoint["task_id"],
                    output_version,
                    checkpoint_id,
                    _json(manifest),
                    fingerprint,
                    now,
                ),
            )
            connection.execute(
                "UPDATE research_checkpoints SET snapshot_fingerprint = ? "
                "WHERE id = ?",
                (fingerprint, checkpoint_id),
            )
            connection.execute(
                "UPDATE run_workspaces SET status = 'committed' WHERE run_id = ?",
                (checkpoint["research_run_id"],),
            )
            conversation_id = _conversation_id_for_run(connection, run)
            event_sequence = _insert_event(
                connection,
                conversation_id,
                "checkpoint.committed",
                {
                    "checkpoint_id": checkpoint_id,
                    "committed_state_version": output_version,
                },
                now,
                research_run_id=run["id"],
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "checkpoint",
                {
                    "checkpoint_id": checkpoint_id,
                    "committed_state_version": output_version,
                },
                now,
                source_event_sequence=event_sequence,
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
        expected_current_state_version: int | None = None,
        expected_snapshot_fingerprint: str | None = None,
    ) -> ReportVersion:
        """Create a draft and abandon the task's previous draft atomically."""
        now = utc_now()
        snapshot = self.committed_snapshot(task_id)
        with connect_state_db(self.cwd) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = _task_state(connection, task_id)
            current_version = state["current_committed_state_version"]
            if (
                expected_current_state_version is not None
                and expected_current_state_version != current_version
            ):
                raise IntelError("STALE_REPORT", "报告基于过期研究状态")
            if snapshot.version != current_version:
                raise IntelError("STALE_REPORT", "报告 snapshot 已变化")
            if (
                expected_snapshot_fingerprint is not None
                and expected_snapshot_fingerprint != snapshot.fingerprint
            ):
                raise IntelError("STALE_REPORT", "报告 snapshot 指纹已变化")
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
            checkpoint = connection.execute(
                "SELECT id FROM research_checkpoints "
                "WHERE task_id = ? AND status = 'committed' "
                "ORDER BY output_committed_state_version DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            report_id = report_id or new_id("report")
            connection.execute(
                "INSERT INTO report_versions("
                "id, task_id, version, status, content_path, content_sha256, "
                "based_on_checkpoint_id, based_on_committed_state_version, "
                "snapshot_fingerprint, created_at"
                ") VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    task_id,
                    version,
                    content_path,
                    content_sha256,
                    checkpoint["id"] if checkpoint is not None else None,
                    state["current_committed_state_version"],
                    snapshot.fingerprint,
                    now,
                ),
            )
            connection.execute(
                "UPDATE task_state SET current_draft_report_version_id = ?, "
                "updated_at = ? WHERE task_id = ?",
                (report_id, now, task_id),
            )
            conversation_id = _conversation_id_for_task(connection, task_id)
            event_sequence = _insert_event(
                connection,
                conversation_id,
                "report.created",
                {"report_id": report_id, "version": version},
                now,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "report_created",
                {"report_id": report_id, "version": version},
                now,
                source_event_sequence=event_sequence,
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
            snapshot = connection.execute(
                "SELECT fingerprint FROM committed_snapshots "
                "WHERE task_id = ? AND version = ?",
                (report["task_id"], current_version),
            ).fetchone()
            is_stale = report[
                "based_on_committed_state_version"
            ] != current_version or (
                report["snapshot_fingerprint"] is not None
                and (
                    snapshot is None
                    or report["snapshot_fingerprint"]
                    != snapshot["fingerprint"]
                )
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
            conversation_id = _conversation_id_for_task(
                connection, report["task_id"]
            )
            event_sequence = _insert_event(
                connection,
                conversation_id,
                "report.published",
                {"report_id": report_id, "version": report["version"]},
                now,
            )
            _insert_timeline_entry(
                connection,
                conversation_id,
                "report_published",
                {"report_id": report_id, "version": report["version"]},
                now,
                source_event_sequence=event_sequence,
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
        data = _redact_event_data(data)
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

    def events_after_conversation(
        self, conversation_id: str, sequence: int
    ) -> list[ConversationEvent]:
        """Replay committed events using the event cursor only."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_events "
                "WHERE conversation_id = ? AND sequence > ? "
                "ORDER BY sequence",
                (conversation_id, sequence),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def timeline_after(
        self, conversation_id: str, sequence: int
    ) -> list[TimelineEntry]:
        """Read display projections using the independent Timeline cursor."""
        with connect_state_db(self.cwd) as connection:
            rows = connection.execute(
                "SELECT * FROM timeline_entries WHERE conversation_id = ? "
                "AND timeline_sequence > ? ORDER BY timeline_sequence",
                (conversation_id, sequence),
            ).fetchall()
        return [_row_to_timeline_entry(row) for row in rows]


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
) -> int:
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
    return sequence


def _insert_timeline_entry(
    connection: sqlite3.Connection,
    conversation_id: str,
    entry_type: str,
    data: dict[str, object],
    created_at: str,
    *,
    source_event_sequence: int | None = None,
) -> None:
    sequence = connection.execute(
        "SELECT COALESCE(MAX(timeline_sequence), 0) + 1 "
        "FROM timeline_entries WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO timeline_entries("
        "id, conversation_id, timeline_sequence, source_event_sequence, "
        "entry_type, data_json, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            new_id("timeline"),
            conversation_id,
            sequence,
            source_event_sequence,
            entry_type,
            _json(data),
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


def _conversation_id_for_run(
    connection: sqlite3.Connection, run: sqlite3.Row
) -> str:
    row = connection.execute(
        "SELECT conversations.id FROM conversations "
        "LEFT JOIN messages ON messages.conversation_id = conversations.id "
        "WHERE messages.id = ? OR conversations.task_id = ? "
        "ORDER BY CASE WHEN messages.id = ? THEN 0 ELSE 1 END, "
        "conversations.updated_at DESC LIMIT 1",
        (run["trigger_message_id"], run["task_id"], run["trigger_message_id"]),
    ).fetchone()
    if row is None:
        raise IntelError("STORAGE_CORRUPT", "研究运行缺少关联会话")
    return row["id"]


def _conversation_id_for_task(
    connection: sqlite3.Connection, task_id: str
) -> str:
    row = connection.execute(
        "SELECT id FROM conversations WHERE task_id = ? "
        "ORDER BY updated_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None:
        raise IntelError("STORAGE_CORRUPT", "任务缺少关联会话")
    return row["id"]


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


def _row_to_processing_attempt(
    row: sqlite3.Row,
) -> MessageProcessingAttempt:
    return MessageProcessingAttempt.model_validate(dict(row))


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


def _row_to_search_plan(row: sqlite3.Row) -> SearchPlanVersion:
    value = dict(row)
    value["plan"] = json.loads(value.pop("plan_json"))
    return SearchPlanVersion.model_validate(value)


def _row_to_snapshot(row: sqlite3.Row) -> CommittedResearchSnapshot:
    raw_manifest = json.loads(row["asset_manifest_json"])
    if not isinstance(raw_manifest, list):
        raise IntelError("STORAGE_CORRUPT", "研究快照清单格式无效")
    manifest = [AssetRevisionRef.model_validate(item) for item in raw_manifest]
    normalized = [item.model_dump(mode="json") for item in manifest]
    if _manifest_fingerprint(normalized) != row["fingerprint"]:
        raise IntelError("STORAGE_CORRUPT", "研究快照指纹不匹配")
    return CommittedResearchSnapshot(
        task_id=row["task_id"],
        version=row["version"],
        checkpoint_id=row["checkpoint_id"],
        asset_manifest=manifest,
        fingerprint=row["fingerprint"],
        created_at=row["created_at"],
    )


def _row_to_outcome(row: sqlite3.Row) -> ResearchOutcome:
    return ResearchOutcome.model_validate(dict(row))


def _find_workspace(
    connection: sqlite3.Connection, run_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM run_workspaces WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise IntelError("NOT_FOUND", f"运行工作区不存在: {run_id}")
    return row


def _manifest_fingerprint(manifest: list[dict[str, object]]) -> str:
    import hashlib

    payload = json.dumps(
        manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _row_to_checkpoint(row: sqlite3.Row) -> ResearchCheckpoint:
    return ResearchCheckpoint.model_validate(dict(row))


def _row_to_report(row: sqlite3.Row) -> ReportVersion:
    return ReportVersion.model_validate(dict(row))


def _row_to_event(row: sqlite3.Row) -> ConversationEvent:
    value = dict(row)
    value["data"] = json.loads(value.pop("data_json"))
    return ConversationEvent.model_validate(value)


def _row_to_timeline_entry(row: sqlite3.Row) -> TimelineEntry:
    value = dict(row)
    value["data"] = json.loads(value.pop("data_json"))
    return TimelineEntry.model_validate(value)
