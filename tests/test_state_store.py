from __future__ import annotations

import pytest

from intel_agent.models import IntelError
from intel_agent.state_store import StateStore


def test_message_retry_is_idempotent(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")

    first = store.add_user_message("task-1", "问题", "client-1")
    retried = store.add_user_message("task-1", "问题", "client-1")

    assert retried.id == first.id
    assert [item.sequence for item in store.list_messages("task-1")] == [1]


def test_message_retry_rejects_different_content(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    store.add_user_message("task-1", "问题", "client-1")

    with pytest.raises(IntelError) as caught:
        store.add_user_message("task-1", "不同问题", "client-1")

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


def test_new_epoch_hides_old_messages_without_deleting_them(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    old = store.add_user_message("task-1", "旧问题", "client-1")

    store.start_epoch("task-1")
    new = store.add_user_message("task-1", "新问题", "client-2")

    assert store.list_messages("task-1") == [new]
    assert store.list_messages("task-1", active_epoch_only=False) == [old, new]


def test_complete_message_inserts_one_assistant_reply(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    user = store.add_user_message("task-1", "问题", "client-1")

    assistant = store.complete_message(user.id, "回答")

    assert assistant.role == "assistant"
    assert assistant.reply_to_id == user.id
    assert store.get_message(user.id).status == "completed"
    assert [item.sequence for item in store.list_messages("task-1")] == [1, 2]
