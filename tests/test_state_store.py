from __future__ import annotations

import pytest

from intel_agent.evidence import save_evidence
from intel_agent.fact import save_fact
from intel_agent.materials import register_material
from intel_agent.models import (
    AssetRevisionRef,
    CitationDraft,
    CommittedAssetType,
    IntelError,
    ResearchBrief,
)
from intel_agent.state_db import connect_state_db
from intel_agent.state_store import StateStore
from intel_agent.storage import workspace_path
from tests.conftest import make_document, new_task


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


def test_run_writes_stage_document_fact_and_evidence_revisions(cwd):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    run = store.create_run(task.id, "continue_research", 0, {})
    store.claim_run(run.id, phase="collecting", lease_owner="worker")
    document = make_document(cwd, "staged source")
    register_material(
        cwd,
        task.id,
        document.canonical_url,
        document_id=document.id,
        run_id=run.id,
    )
    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "staged fact",
        run_id=run.id,
    )
    evidence = save_evidence(
        cwd,
        fact.id,
        document.id,
        "supports",
        "staged source",
        "",
        run_id=run.id,
    )

    staged = store.run_view(run.id).staged_revisions

    assert {(item.asset_type, item.logical_id) for item in staged} == {
        ("document", document.id),
        ("fact", fact.id),
        ("evidence", evidence.id),
        ("material_digest", task.id),
    }


def test_claim_action_run_is_idempotent_and_atomic(cwd):
    store = StateStore(cwd)
    task_id = "task-claim"
    store.register_task(task_id)
    trigger = store.add_user_message(task_id, "继续搜索", "claim-client")
    action = store.create_action(
        task_id, trigger.id, "continue_research", {"topic": "原子"}
    )

    claimed, run = store.claim_action_run(action.id)
    replayed, replay_run = store.claim_action_run(action.id)

    assert claimed.status == "executing"
    assert run is not None
    assert replayed == claimed
    assert replay_run == run
    assert run.action_request_id == action.id
    assert store.list_runs(task_id) == [run]


def test_committed_snapshot_is_stable_and_workspace_isolated(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    baseline = store.committed_snapshot("task-1")
    assert baseline.version == 0
    assert baseline.asset_manifest == []
    assert store.committed_snapshot("task-1", 0) == baseline

    run = store.create_run("task-1", "initial", 0, {})
    revision = AssetRevisionRef(
        asset_type="document",
        logical_id="doc-1",
        revision_id="rev-1",
        content_sha256="a" * 64,
        task_id="task-1",
    )
    workspace = store.stage_revision(run.id, revision)
    assert workspace.staged_revisions == [revision]
    with pytest.raises(IntelError, match="不属于"):
        store.stage_revision(
            run.id, revision.model_copy(update={"task_id": "task-2"})
        )

    store.transition_run(run.id, "cancelled")
    with pytest.raises(IntelError, match="已关闭"):
        store.run_view(run.id)


def test_snapshot_manifest_accepts_derived_asset_revisions(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")

    for asset_type in (
        "document",
        "fact",
        "evidence",
        "review",
        "conflict",
        "coverage",
        "material_digest",
        "task_revision",
    ):
        store.stage_asset(run.id, asset_type, f"{asset_type}-1", "")

    store.finish_run(run.id, expected_input_version=0)
    snapshot = store.committed_snapshot("task-1", 1)

    assert {item.asset_type for item in snapshot.asset_manifest} == {
        "document",
        "fact",
        "evidence",
        "review",
        "conflict",
        "coverage",
        "material_digest",
        "task_revision",
    }


def test_committed_snapshot_rejects_tampered_materialized_revision(cwd):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    run = store.create_run(task.id, "initial", 0, {})
    store.transition_run(run.id, "running")
    document = make_document(cwd, "immutable source")
    store.stage_asset(run.id, "document", document.id, document.text_sha256)
    store.finish_run(run.id, expected_input_version=0)

    workspace_path(cwd, document.text_path).write_text(
        "tampered", encoding="utf-8"
    )

    with pytest.raises(IntelError, match="哈希不匹配"):
        store.committed_snapshot(task.id, 1)


def test_claim_action_is_idempotent_and_expires_stale_precondition(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    message = store.add_user_message("task-1", "继续", "client-1")
    action = store.create_action("task-1", message.id, "continue_research", {})

    claimed = store.claim_action(action.id)
    assert claimed.status == "executing"
    assert store.claim_action(action.id).status == "executing"


def test_claim_run_is_idempotent_and_checks_input_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})

    claimed = store.claim_run(run.id, phase="planning", lease_owner="worker-1")

    assert claimed.status == "running"
    assert (
        store.claim_run(run.id, phase="planning", lease_owner="worker-1")
        == claimed
    )

    committed = store.create_run("task-1", "continue_research", 0, {})
    store.finish_run(
        run.id,
        expected_input_version=0,
        staged_manifest=[
            AssetRevisionRef(
                asset_type="document",
                logical_id="doc-1",
                revision_id="rev-1",
                content_sha256="",
                task_id="task-1",
            )
        ],
    )
    with pytest.raises(IntelError, match="过期"):
        store.claim_run(
            committed.id, phase="collecting", lease_owner="worker-2"
        )


def test_finish_run_atomically_commits_and_replays(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")
    revision = AssetRevisionRef(
        asset_type="document",
        logical_id="doc-1",
        revision_id="rev-1",
        content_sha256="",
        task_id="task-1",
    )

    outcome = store.finish_run(
        run.id, expected_input_version=0, staged_manifest=[revision]
    )
    replay = store.finish_run(
        run.id, expected_input_version=0, staged_manifest=[revision]
    )

    assert outcome == replay
    assert outcome.outcome == "committed"
    assert outcome.committed_state_version == 1
    assert store.committed_snapshot("task-1", 1).fingerprint
    assert store.get_run(run.id).status == "succeeded"
    event_types = [
        event.event_type for event in store.events_after("task-1", 0)
    ]
    assert event_types[-2:] == ["checkpoint.committed", "run.succeeded"]


def test_finish_run_rejects_stale_input_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    first = store.create_run("task-1", "initial", 0, {})
    store.transition_run(first.id, "running")
    store.finish_run(
        first.id,
        expected_input_version=0,
        staged_manifest=[
            AssetRevisionRef(
                asset_type="document",
                logical_id="doc-1",
                revision_id="rev-1",
                content_sha256="",
                task_id="task-1",
            )
        ],
    )

    stale = store.create_run("task-1", "continue_research", 0, {})
    store.transition_run(stale.id, "running")
    with pytest.raises(IntelError, match="过期"):
        store.finish_run(stale.id, expected_input_version=0)


def test_committed_snapshot_rejects_tampered_manifest_fingerprint(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")
    store.finish_run(run.id, expected_input_version=0)

    with connect_state_db(cwd) as connection:
        connection.execute(
            "UPDATE committed_snapshots SET fingerprint = ? "
            "WHERE task_id = ? AND version = 0",
            ("0" * 64, "task-1"),
        )

    with pytest.raises(IntelError, match="指纹不匹配"):
        store.committed_snapshot("task-1", 0)


def test_finish_run_no_progress_keeps_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")

    outcome = store.finish_run(
        run.id, expected_input_version=0, outcome="no_progress"
    )

    assert outcome.committed_state_version == 0
    assert store.committed_state_version("task-1") == 0


def test_search_plan_versions_are_immutable_and_run_scoped(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    first = store.create_search_plan_version(run.id, {"query": "one"})
    second = store.create_search_plan_version(run.id, {"query": "two"})

    assert first.sequence == 1
    assert second.sequence == 2
    assert store.get_search_plan_version(first.id).plan == {"query": "one"}
    assert store.active_search_plan(run.id).id == second.id


def test_conversation_archive_is_reversible_and_filtered(cwd):
    store = StateStore(cwd)
    conversation = store.create_conversation("browser-c1")

    archived = store.archive_conversation(conversation.id)

    assert archived.status == "archived"
    assert store.list_conversations() == []
    assert store.list_conversations(archived=True) == [archived]

    restored = store.restore_conversation(conversation.id)

    assert restored.status == "intake"
    assert store.list_conversations() == [restored]
    assert store.list_conversations(archived=True) == []
    assert [
        event.event_type
        for event in store.events_after_conversation(conversation.id, 0)
    ] == ["conversation.archived", "conversation.restored"]


def test_conversation_with_unfinished_run_cannot_be_archived(cwd):
    store = StateStore(cwd)
    conversation = store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})

    with pytest.raises(IntelError) as caught:
        store.archive_conversation(conversation.id)

    assert caught.value.code == "CONVERSATION_BUSY"
    store.transition_run(run.id, "cancelled")
    assert store.archive_conversation(conversation.id).status == "archived"


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


def test_cancel_and_stop_have_distinct_run_semantics(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    queued = store.create_run("task-1", "initial", 0, {})

    cancelled = store.cancel_run(queued.id)
    running = store.create_run("task-1", "initial", 0, {})
    store.transition_run(
        running.id,
        "running",
        lease_owner="runtime-1",
        lease_expires_at="2026-08-25T01:00:00+00:00",
    )
    stopping = store.stop_run(running.id)
    stopped = store.finish_stop(running.id)

    assert cancelled.status == "cancelled"
    assert stopping.status == "stopping"
    assert stopped.status == "stopped"


def test_recovery_interrupts_expired_running_and_stopping_runs(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    running = store.create_run("task-1", "initial", 0, {})
    store.transition_run(
        running.id,
        "running",
        lease_owner="old-runtime",
        lease_expires_at="2026-08-25T00:00:00+00:00",
    )

    recovered = store.recover_expired_runs("2026-08-25T00:00:01+00:00")

    assert [item.id for item in recovered] == [running.id]
    assert recovered[0].status == "interrupted"


def test_event_and_timeline_sequences_are_independent(cwd):
    store = StateStore(cwd)
    conversation = store.create_conversation()
    store.add_user_message(conversation.id, "你能做什么", "client-1")

    events = store.events_after_conversation(conversation.id, 0)
    timeline = store.timeline_after(conversation.id, 0)

    assert events[0].sequence == 1
    assert timeline[0].timeline_sequence == 1
    assert timeline[0].source_event_sequence == events[0].sequence
    assert timeline[0].id != str(events[0].id)


def test_run_state_and_event_projection_roll_back_together(cwd, monkeypatch):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("projection failed")

    monkeypatch.setattr(
        "intel_agent.state_store._insert_timeline_entry", fail_projection
    )
    with pytest.raises(RuntimeError, match="projection failed"):
        store.transition_run(run.id, "running")

    assert store.get_run(run.id).status == "queued"
    assert all(
        event.research_run_id != run.id
        for event in store.events_after("task-1", 0)
    )


def test_stopping_run_cannot_commit_working_assets(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="batch")
    store.stop_run(run.id)

    with pytest.raises(IntelError) as caught:
        store.commit_checkpoint(checkpoint.id, [("document", "working-doc")])

    assert caught.value.code == "RUN_STOPPING"
    assert store.committed_asset_ids("task-1", "document") == set()


def test_checkpoint_commit_advances_version_once(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="final")

    committed = store.commit_checkpoint(
        checkpoint.id, [("document", "working-doc")]
    )
    repeated = store.commit_checkpoint(checkpoint.id)

    assert committed.input_committed_state_version == 0
    assert committed.output_committed_state_version == 1
    assert repeated == committed
    assert store.committed_state_version("task-1") == 1


def test_checkpoint_requires_running_run(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})

    with pytest.raises(IntelError) as caught:
        store.start_checkpoint(run.id, reason="queued")

    assert caught.value.code == "RUN_NOT_RUNNING"


def test_empty_checkpoint_is_no_progress(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="no new evidence")

    committed = store.commit_checkpoint(checkpoint.id)

    assert committed.output_committed_state_version == 0
    assert store.committed_state_version("task-1") == 0


def test_stale_report_requires_explicit_current_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    draft = store.create_report_draft("task-1", "output/report.md", "abc")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="new evidence")
    store.commit_checkpoint(checkpoint.id, [("document", "new-evidence")])

    with pytest.raises(IntelError) as caught:
        store.publish_report(draft.id)

    assert caught.value.code == "STALE_REPORT"
    published = store.publish_report(
        draft.id,
        publish_stale=True,
        expected_current_state_version=1,
    )
    assert published.status == "published"


def test_report_fingerprint_mismatch_is_stale_even_at_same_version(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    snapshot = store.committed_snapshot("task-1")
    draft = store.create_report_draft(
        "task-1",
        "output/report.md",
        "abc",
        expected_snapshot_fingerprint=snapshot.fingerprint,
    )

    with connect_state_db(cwd) as connection:
        connection.execute(
            "UPDATE report_versions SET snapshot_fingerprint = ? WHERE id = ?",
            ("0" * 64, draft.id),
        )

    with pytest.raises(IntelError, match="旧研究状态"):
        store.publish_report(draft.id)


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


def test_report_draft_binds_snapshot_fingerprint_and_cas(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    snapshot = store.committed_snapshot("task-1")
    report = store.create_report_draft(
        "task-1",
        "output/report.md",
        "hash",
        expected_current_state_version=0,
        expected_snapshot_fingerprint=snapshot.fingerprint,
    )

    assert report.snapshot_fingerprint == snapshot.fingerprint
    with pytest.raises(IntelError, match="指纹"):
        store.create_report_draft(
            "task-1",
            "output/other.md",
            "hash",
            expected_snapshot_fingerprint="0" * 64,
        )


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


def test_durable_event_redacts_credentials_in_urls_and_fields(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    event = store.append_event(
        "task-1",
        "message.accepted",
        {"url": "https://example.com/a?token=secret", "api_key": "secret"},
    )

    assert event.data == {
        "url": "https://example.com/a?token=%2A%2A%2A",
        "api_key": "***",
    }


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
