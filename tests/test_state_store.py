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


def test_confirmed_proposal_queues_once(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    trigger = store.add_user_message("task-1", "现有材料够吗", "client-1")
    action = store.create_action(
        task_id="task-1",
        trigger_message_id=trigger.id,
        action_type="continue_research",
        payload={"question_ids": ["q-1"]},
        proposed=True,
    )
    confirmation = store.add_user_message("task-1", "确认继续搜索", "client-2")

    queued = store.confirm_action(action.id, confirmation.id)
    repeated = store.confirm_action(action.id, confirmation.id)

    assert repeated == queued
    assert queued.status == "queued"
    assert queued.request_mode == "confirmed_proposal"


def test_unconfirmed_proposal_can_expire(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    trigger = store.add_user_message("task-1", "现有材料够吗", "client-1")
    action = store.create_action(
        task_id="task-1",
        trigger_message_id=trigger.id,
        action_type="continue_research",
        payload={},
        proposed=True,
    )

    expired = store.transition_action(action.id, "expired")

    assert expired.status == "expired"
    assert expired.request_mode is None


def test_retry_creates_new_run_and_keeps_interrupted_terminal(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    first = store.create_run("task-1", "initial", 0, {})
    store.transition_run(first.id, "running")

    interrupted = store.transition_run(first.id, "interrupted")
    retry = store.retry_run(first.id)

    assert interrupted.status == "interrupted"
    assert retry.retry_of_run_id == first.id
    assert retry.id != first.id


def test_checkpoint_commit_advances_version_once(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    checkpoint = store.start_checkpoint(run.id, reason="final")

    committed = store.commit_checkpoint(checkpoint.id)
    repeated = store.commit_checkpoint(checkpoint.id)

    assert committed.input_committed_state_version == 0
    assert committed.output_committed_state_version == 1
    assert repeated == committed
    assert store.committed_state_version("task-1") == 1


def test_stale_report_requires_explicit_current_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    draft = store.create_report_draft("task-1", "output/report.md", "abc")
    run = store.create_run("task-1", "initial", 0, {})
    checkpoint = store.start_checkpoint(run.id, reason="new evidence")
    store.commit_checkpoint(checkpoint.id)

    with pytest.raises(IntelError) as caught:
        store.publish_report(draft.id)

    assert caught.value.code == "STALE_REPORT"
    published = store.publish_report(
        draft.id,
        publish_stale=True,
        expected_current_state_version=1,
    )
    assert published.status == "published"


def test_new_report_draft_abandons_previous_draft(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    first = store.create_report_draft("task-1", "output/v1.md", "one")

    second = store.create_report_draft("task-1", "output/v2.md", "two")

    assert store.get_report(first.id).status == "abandoned"
    assert second.version == 2


def test_publishing_new_report_supersedes_previous_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    first = store.create_report_draft("task-1", "output/v1.md", "one")
    store.publish_report(first.id)
    second = store.create_report_draft("task-1", "output/v2.md", "two")

    published = store.publish_report(second.id)

    assert store.get_report(first.id).status == "superseded"
    assert published.status == "published"


def test_durable_events_resume_after_sequence(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    first = store.append_event("task-1", "message.accepted", {"id": "one"})
    second = store.append_event("task-1", "answer.completed", {"id": "two"})

    assert store.events_after("task-1", first.sequence) == [second]


def test_transient_events_are_not_persisted(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")

    with pytest.raises(IntelError) as caught:
        store.append_event("task-1", "answer.delta", {"text": "partial"})

    assert caught.value.code == "INVALID_INPUT"
    assert store.events_after("task-1", 0) == []
