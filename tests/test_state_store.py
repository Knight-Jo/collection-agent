from __future__ import annotations

import pytest

from intel_agent.models import (
    CitationDraft,
    CommittedAssetType,
    IntelError,
    ResearchBrief,
)
from intel_agent.state_store import StateStore


def _brief() -> ResearchBrief:
    return ResearchBrief(
        topic="先进封装",
        objective="梳理产业现状",
        key_questions=["产业规模如何？", "竞争格局如何？"],
    )


def test_bind_intake_task_is_atomic_and_idempotent(cwd):
    store = StateStore(cwd)
    conversation = store.create_conversation("browser-c1")
    message = store.add_user_message(
        conversation.id, "调研先进封装", "browser-m1"
    )

    first = store.bind_intake_task(conversation.id, message.id, _brief())
    second = store.bind_intake_task(conversation.id, message.id, _brief())

    assert second == first
    assert first.task_id is not None
    assert len(store.list_runs(first.task_id)) == 1
    assert len(store.list_conversations()) == 1


def test_bind_intake_task_rolls_back_on_event_failure(cwd, monkeypatch):
    store = StateStore(cwd)
    conversation = store.create_conversation()
    message = store.add_user_message(
        conversation.id, "调研先进封装", "browser-m1"
    )

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr("intel_agent.state_store._insert_event", fail_event)
    with pytest.raises(RuntimeError, match="event write failed"):
        store.bind_intake_task(conversation.id, message.id, _brief())

    assert store.get_conversation_by_id(conversation.id).task_id is None
    assert store.list_runs_for_conversation(conversation.id) == []


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


def test_message_events_and_citations_are_committed_together(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    store.seed_committed_assets(
        "task-1",
        [("document", "document-1"), ("evidence", "evidence-1")],
    )
    user = store.add_user_message("task-1", "问题", "client-1")
    store.set_message_processing(user.id)
    citation = CitationDraft(
        citation_kind="verified_evidence",
        document_id="document-1",
        evidence_id="evidence-1",
        title="材料",
        source_url="https://example.com/source",
        quote_text="引用",
        line_start=2,
        line_end=3,
        source_content_hash="abc",
    )

    assistant = store.complete_message(user.id, "回答", [citation])

    assert store.citations_for_message(assistant.id)[0].quote_text == "引用"
    events = store.events_after("task-1", 0)
    assert [event.event_type for event in events] == [
        "message.accepted",
        "answer.completed",
    ]
    assert events[-1].data["reply_to_id"] == user.id


def test_complete_message_rejects_cross_task_citation(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    store.register_task("task-2")
    store.seed_committed_assets("task-2", [("document", "document-2")])
    user = store.add_user_message("task-1", "问题", "client-1")
    citation = CitationDraft(
        citation_kind="material_clue",
        document_id="document-2",
        title="其他任务材料",
        source_url="https://example.com/source",
        quote_text="引用",
        line_start=1,
        line_end=1,
        source_content_hash="abc",
    )

    with pytest.raises(IntelError) as caught:
        store.complete_message(user.id, "回答", [citation])

    assert caught.value.code == "INVALID_CITATION"
    assert store.get_message(user.id).status == "accepted"


def test_message_can_fail_after_processing(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    user = store.add_user_message("task-1", "问题", "client-1")

    processing = store.set_message_processing(user.id)
    failed = store.fail_message(user.id, "model unavailable")

    assert processing.status == "processing"
    assert failed.status == "failed"
    assert failed.error == "model unavailable"


def test_committed_asset_seeding_is_idempotent(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    assets: list[tuple[CommittedAssetType, str]] = [
        ("document", "document-1"),
        ("fact", "fact-1"),
    ]

    store.seed_committed_assets("task-1", assets)
    store.seed_committed_assets("task-1", assets)

    assert store.committed_asset_ids("task-1", "document") == {"document-1"}
    assert store.committed_asset_ids("task-1", "fact") == {"fact-1"}


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


def test_list_projections_use_stable_order(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    trigger = store.add_user_message("task-1", "继续搜索", "client-1")
    first_action = store.create_action(
        "task-1", trigger.id, "continue_research", {}
    )
    second_action = store.create_action(
        "task-1", trigger.id, "generate_report", {}
    )
    first_run = store.create_run("task-1", "initial", 0, {})
    second_run = store.create_run("task-1", "continue_research", 0, {})
    first_report = store.create_report_draft("task-1", "one.md", "one")
    second_report = store.create_report_draft("task-1", "two.md", "two")

    assert store.get_action(first_action.id) == first_action
    assert store.list_actions("task-1") == [first_action, second_action]
    assert store.get_run(first_run.id) == first_run
    assert store.list_runs("task-1") == [first_run, second_run]
    assert [item.id for item in store.list_reports("task-1")] == [
        first_report.id,
        second_report.id,
    ]
