"""Transactional repository for local conversational research state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import (
    Conversation,
    ConversationEpoch,
    IntelError,
    Message,
    new_id,
    utc_now,
)
from .state_db import connect_state_db, initialize_state_db


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
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _row_to_message(_required(row, "message"))

    def complete_message(self, user_message_id: str, content: str) -> Message:
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


def _next_message_sequence(
    connection: sqlite3.Connection, conversation_id: str
) -> int:
    return connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 "
        "FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]


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
    value["intent"] = (
        json.loads(value.pop("intent_json"))
        if value["intent_json"] is not None
        else None
    )
    return Message.model_validate(value)
