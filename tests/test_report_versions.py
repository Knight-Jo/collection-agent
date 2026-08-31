from __future__ import annotations

import asyncio

import pytest

from intel_agent.audit import audit_task_evidence
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.models import IntelError
from intel_agent.report import generate_research_report
from intel_agent.report_versions import ReportPublisher
from intel_agent.retrieval import TaskRetriever
from intel_agent.state_store import StateStore
from intel_agent.storage import sha256, workspace_path
from intel_agent.task import load_task
from tests.conftest import fake_judge, make_document, save_evidence
from tests.test_report import report_draft, seed_reportable_task


def _publisher(cwd, task_id):
    store = StateStore(cwd)
    TaskRetriever(cwd, store).seed_completed_task(task_id)
    return store, ReportPublisher(cwd, store=store)


def test_report_draft_rejects_empty_committed_research_state(cwd):
    task, facts, _documents = seed_reportable_task(cwd)
    result = generate_research_report(cwd, task.id, report_draft(task, facts))
    assert result["ok"] is True
    publisher = ReportPublisher(cwd, store=StateStore(cwd))

    assert publisher.report_ready(task.id) is False
    with pytest.raises(IntelError) as caught:
        publisher.create_draft(task.id)

    assert caught.value.code == "REPORT_NOT_READY"


def test_report_draft_preserves_legacy_binding_and_filters_uncommitted_fact(
    cwd,
):
    task, facts, _documents = seed_reportable_task(cwd)
    legacy = generate_research_report(cwd, task.id, report_draft(task, facts))
    assert legacy["ok"] is True
    legacy_binding = load_task(cwd, task.id).outputs.report
    store, publisher = _publisher(cwd, task.id)

    extra_document = make_document(
        cwd, "不应进入版本报告的未提交事实", "https://example.com/orphan"
    )
    extra_fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "不应进入版本报告的未提交事实",
        claim_type="primary",
    )
    save_evidence(
        cwd,
        extra_fact.id,
        extra_document,
        "supports",
        extra_fact.statement,
    )
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)

    draft = publisher.create_draft(task.id)

    content_path = workspace_path(cwd, draft.content_path)
    content = content_path.read_text(encoding="utf-8")
    assert draft.content_sha256 == sha256(content_path.read_bytes())
    assert extra_fact.statement not in content
    assert load_task(cwd, task.id).outputs.report == legacy_binding
    assert store.get_report(draft.id) == draft


def test_report_draft_is_reused_until_research_state_changes(cwd):
    task, _facts, _documents = seed_reportable_task(cwd)
    store, publisher = _publisher(cwd, task.id)

    first = publisher.create_draft(task.id)
    repeated = publisher.create_draft(task.id)

    assert repeated == first

    run = store.create_run(task.id, "continue_research", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="new evidence")
    store.commit_checkpoint(checkpoint.id, [("document", "new-doc")])
    second = publisher.create_draft(task.id)
    published = publisher.publish(second.id)

    assert store.get_report(first.id).status == "abandoned"
    assert second.version == 2
    assert published.status == "published"
    event_types = [
        event.event_type for event in store.events_after(task.id, 0)
    ]
    assert event_types.count("report.created") == 2
    assert event_types.count("report.published") == 1


def test_report_publisher_passes_fixed_snapshot_to_renderer(cwd, monkeypatch):
    task, _facts, _documents = seed_reportable_task(cwd)
    store, publisher = _publisher(cwd, task.id)
    captured = []

    def fake_renderer(
        _cwd, _task_id, *, allowed_fact_ids, output_path, snapshot
    ):
        captured.append(snapshot)
        path = workspace_path(cwd, output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixed", encoding="utf-8")
        return {"ok": True, "path": str(path), "errors": []}

    monkeypatch.setattr(
        "intel_agent.report_versions.render_verified_report", fake_renderer
    )
    publisher.create_draft(task.id)

    assert captured and captured[0].version == store.committed_state_version(
        task.id
    )


def test_publisher_requires_confirmation_for_stale_draft(cwd):
    task, _facts, _documents = seed_reportable_task(cwd)
    store, publisher = _publisher(cwd, task.id)
    draft = publisher.create_draft(task.id)
    run = store.create_run(task.id, "initial", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="new evidence")
    store.commit_checkpoint(checkpoint.id, [("document", "new-doc")])

    with pytest.raises(IntelError) as caught:
        publisher.publish(draft.id)

    assert caught.value.code == "STALE_REPORT"
    published = publisher.publish(
        draft.id,
        publish_stale=True,
        expected_current_state_version=1,
    )
    assert published.status == "published"


def test_report_version_records_latest_committed_checkpoint(cwd):
    task, _facts, _documents = seed_reportable_task(cwd)
    store, publisher = _publisher(cwd, task.id)
    run = store.create_run(task.id, "initial", 0, {})
    store.transition_run(run.id, "running")
    checkpoint = store.start_checkpoint(run.id, reason="research complete")
    store.commit_checkpoint(checkpoint.id, [("document", "new-doc")])

    draft = publisher.create_draft(task.id)

    assert draft.based_on_checkpoint_id == checkpoint.id
