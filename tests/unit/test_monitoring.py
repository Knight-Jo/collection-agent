"""Monitor diff/scheduler/service regression tests (spec 002 US1-US2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace

from intel_agent.contracts.documents import Citation
from intel_agent.contracts.research import (
    CoverageAssessment,
    EvidenceItem,
    EvidenceReview,
    ResearchAssessment,
)
from intel_agent.monitoring.diff import (
    derive_fact_key,
    diff_baseline,
    normalize_source_key,
    normalize_statement,
)
from intel_agent.monitoring.models import (
    FactVersion,
    Monitor,
    MonitorRun,
    MonitorSchedule,
)
from intel_agent.monitoring.scheduler import next_run_after
from intel_agent.monitoring.service import MonitoringService
from intel_agent.runtime.config import ResearchSettings
from intel_agent.storage.monitoring import MonitoringStore
from intel_agent.storage.sqlite import SqliteStore
from intel_agent.storage.tasks import TaskStore

# --- diff helpers -----------------------------------------------------------


def test_normalize_source_key_is_page_level():
    assert (
        normalize_source_key("https://Example.COM/path") == "example.com/path"
    )
    assert normalize_source_key("https://a.com:443/x") == "a.com/x"
    # query and fragment carry tracking noise, not identity
    assert normalize_source_key("https://a.com/p?utm=1#sec") == "a.com/p"
    assert normalize_source_key("https://a.com/p/") == "a.com/p"
    assert normalize_source_key("https://a.com") == "a.com/"
    assert normalize_source_key("not a url") == ""


def test_normalize_statement_folds_case_and_punctuation():
    assert normalize_statement("GDP is  $10B!") == normalize_statement(
        "gdp is $10b"
    )
    assert normalize_statement("  Hello,   World ") == "hello world"


def test_derive_fact_key_is_stable_and_value_independent():
    a = derive_fact_key("subj", "pred", {"t": "2026"})
    b = derive_fact_key("subj", "pred", {"t": "2026"})
    c = derive_fact_key("subj", "pred", {"t": "2027"})
    assert a == b
    assert a != c


def test_diff_baseline_classifies_new_changed_matched_removed():
    baseline = {
        "k1": "acme employs 5000 people",
        "k2": "acme is headquartered in paris",
        "k3": "acme revenue is stable",
    }
    current = {
        # wording drift only -> matched
        "x1": "Acme employs 5000 people worldwide!",
        # one value token swapped -> changed, mapped back to its origin
        "x2": "acme is headquartered in berlin",
        # no baseline overlap -> new
        "x3": "acme opened an office in singapore",
        # exact restatement -> matched
        "k3": "acme revenue is stable",
    }
    new, changed, matched, removed, near = diff_baseline(current, baseline)
    assert new == {"x3"}
    assert changed == {"x2"}
    assert near == {"x2": "k2"}
    assert "x1" in matched and "k3" in matched
    # k1 was consumed by the drift match x1 and k2 by the change x2,
    # so no baseline fact disappeared
    assert removed == set()


def test_diff_baseline_reports_removed_facts():
    baseline = {"k1": "acme employs 5000 people"}
    current = {"x1": "acme opened an office in singapore"}
    _new, _changed, _matched, removed, _near = diff_baseline(current, baseline)
    assert removed == {"k1"}


def test_next_run_daily():
    schedule = MonitorSchedule(
        cadence="daily", local_time="09:00", timezone="UTC"
    )
    now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    nxt = next_run_after(schedule, now)
    assert nxt > now
    assert (nxt.hour, nxt.minute) == (9, 0)
    assert nxt.date().isoformat() == "2026-09-06"


def test_next_run_weekly():
    schedule = MonitorSchedule(
        cadence="weekly", local_time="09:00", timezone="UTC", weekday=0
    )
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)  # Sunday
    nxt = next_run_after(schedule, now)
    assert nxt.weekday() == 0
    assert nxt > now


# --- storage upserts --------------------------------------------------------


def _store(tmp_path):
    sqlite = SqliteStore(tmp_path / "m.sqlite")
    store = MonitoringStore(sqlite)
    task_store = TaskStore(sqlite)  # monitor_runs.task_id references tasks
    now = datetime.now(UTC)
    store.save_monitor(
        Monitor(
            monitor_id="mon1",
            name="n",
            subject="s",
            strategy="g",
            schedule=MonitorSchedule(
                cadence="daily", local_time="09:00", timezone="UTC"
            ),
            created_at=now,
            updated_at=now,
        )
    )
    return store, task_store


def test_save_run_upsert_updates_summary(tmp_path):
    store, task_store = _store(tmp_path)
    task = task_store.create_task("q", kind="monitor")
    run = MonitorRun(
        run_id="r1", monitor_id="mon1", task_id=task.task_id, trigger="manual"
    )
    store.save_run(run)
    # the service re-saves the same run with its summary when execution
    # finishes; a plain second insert would violate the primary key
    store.save_run(run.model_copy(update={"summary": "3 项变化"}))
    assert store.get_run("r1").summary == "3 项变化"


def test_save_fact_version_reobservation(tmp_path):
    store, _task_store = _store(tmp_path)
    version = FactVersion(
        fact_version_id="fk-1",
        monitor_id="mon1",
        created_run_id="r1",
        fact_key="fk-1",
        statement="acme employs 5000 people",
    )
    store.save_fact_version(version)
    # a later run restates the same fact key with a new observation
    store.save_fact_version(
        version.model_copy(
            update={
                "created_run_id": "r2",
                "statement": "acme employs 6000 people",
            }
        )
    )
    row = store.db.execute(
        "SELECT created_run_id, statement FROM monitor_fact_versions"
        " WHERE fact_version_id = 'fk-1'"
    ).fetchone()
    assert row["created_run_id"] == "r2"
    assert row["statement"] == "acme employs 6000 people"


# --- service flow ------------------------------------------------------------


class FakePlanner:
    async def run(self, prompt):
        return SimpleNamespace(output=None)


class FakeOrchestrator:
    def __init__(self, assessments):
        self._assessments = list(assessments)
        self.roles = {"planner": FakePlanner()}

    async def run_assessment(self, task, plan=None):
        item = self._assessments.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeApplication:
    def __init__(self) -> None:
        self.registered: dict[str, Callable[[str], Awaitable[None]]] = {}
        self.launched: list[tuple[str, Callable[[str], Awaitable[None]]]] = []

    def register_runner(self, kind, runner):
        self.registered[kind] = runner

    def launch(self, task_id, runner):
        self.launched.append((task_id, runner))

    async def run_pending(self):
        launched, self.launched = self.launched, []
        for task_id, runner in launched:
            await runner(task_id)


def _citation(cid: str, url: str) -> Citation:
    return Citation(
        citation_id=cid,
        chunk_id=f"chunk-{cid}",
        artifact_id=f"art-{cid}",
        document_id=f"doc-{cid}",
        revision_id=f"rev-{cid}",
        resource_id=f"res-{cid}",
        source_url=url,
    )


def _assessment(claims: list[tuple[str, str]], citations: list[Citation]):
    return ResearchAssessment(
        task_id="t",
        coverage=CoverageAssessment(sufficiency="high"),
        evidence_review=EvidenceReview(
            claims=[
                EvidenceItem(claim=claim, relation="supports", citation_id=cid)
                for claim, cid in claims
            ]
        ),
        citations=citations,
        stop_reason="evidence_sufficient",
    )


def _schedule():
    return MonitorSchedule(cadence="daily", local_time="09:00", timezone="UTC")


def _service(tmp_path, assessments):
    sqlite = SqliteStore(tmp_path / "m.sqlite")
    store = MonitoringStore(sqlite)
    task_store = TaskStore(sqlite)
    app = FakeApplication()
    orchestrator = FakeOrchestrator(assessments)
    service = MonitoringService(
        store, task_store, orchestrator, app, ResearchSettings()
    )
    return service, store, task_store, app


async def test_monitor_run_flow_records_changes(tmp_path):
    baseline_claims = [
        ("Acme 2025 revenue is 10 billion dollars.", "c1"),
        ("Acme employs 5000 people.", "c1"),
        ("Acme is headquartered in Paris.", "c2"),
    ]
    cits1 = [
        _citation("c1", "https://example.com/reports"),
        _citation("c2", "https://example.com/reports"),
    ]
    second_claims = [
        # punctuation drift keeps identity -> matched
        ("Acme 2025 revenue is 10 billion dollars!", "c1"),
        # value token swapped -> changed_fact
        ("Acme employs 6000 people.", "c1"),
        # no baseline overlap -> new_fact
        ("Acme opened a new office in Singapore.", "c3"),
    ]
    cits2 = cits1 + [_citation("c3", "https://example.com/press/launch?utm=x")]

    service, store, task_store, app = _service(
        tmp_path,
        [
            _assessment(baseline_claims, cits1),
            _assessment(second_claims, cits2),
        ],
    )
    monitor = service.create_monitor("m", "Acme", "track", _schedule())

    # run 1: the initial baseline run records facts but emits no events
    run1 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    assert store.list_changes(run1.run_id) == []
    assert store.get_monitor(monitor.monitor_id).baseline_run_id == run1.run_id

    # run 2: compares against the frozen baseline
    run2 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()

    changes = store.list_changes(run2.run_id)
    kinds = {c.kind for c in changes}
    assert kinds == {"changed_fact", "new_fact", "removed_fact", "new_source"}

    changed = next(c for c in changes if c.kind == "changed_fact")
    assert "5000" in changed.summary and "6000" in changed.summary
    assert changed.previous_version_id

    removed = next(c for c in changes if c.kind == "removed_fact")
    assert "Paris" in removed.summary

    new_source = next(c for c in changes if c.kind == "new_source")
    assert new_source.source_key == "example.com/press/launch"

    # the run row survived the end-of-run re-save and carries its summary
    assert store.get_run(run2.run_id).summary == "4 项变化"

    # task lifecycle and slot hygiene
    assert task_store.get_task(run2.task_id).status == "completed"
    monitor = store.get_monitor(monitor.monitor_id)
    assert monitor.active_run_id is None
    assert monitor.next_run_at is not None
    assert monitor.baseline_run_id == run2.run_id

    # new facts keep resolvable citations
    office = next(
        c for c in changes if c.kind == "new_fact" and "Singapore" in c.summary
    )
    assert office.current_version_id is not None
    version = store.latest_fact_version(
        monitor.monitor_id, office.current_version_id
    )
    assert version is not None
    assert version.citations[0].citation_id == "c3"


async def test_monitor_run_failure_releases_slot_and_reschedules(tmp_path):
    service, store, task_store, app = _service(
        tmp_path, [RuntimeError("boom")]
    )
    monitor = service.create_monitor("m", "s", "g", _schedule())
    run = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()

    task = task_store.get_task(run.task_id)
    assert task.status == "failed"
    assert isinstance(task.error, dict)
    assert task.error["code"] == "MONITOR_RUN_FAILED"
    loaded = store.get_monitor(monitor.monitor_id)
    assert loaded.active_run_id is None
    assert loaded.next_run_at is not None

    # the slot is free again: a retry submits without CONFLICT
    run2 = await service.submit_run(monitor.monitor_id, "manual")
    assert run2.run_id != run.run_id


async def test_update_monitor_persists_fields(tmp_path):
    service, store, _task_store, _app = _service(tmp_path, [])
    monitor = service.create_monitor("m", "s", "g", _schedule())
    updated = service.update_monitor(
        monitor.monitor_id,
        {
            "name": "renamed",
            "questions": ["q1"],
            "schedule": {
                "cadence": "weekly",
                "local_time": "08:00",
                "timezone": "UTC",
                "weekday": 1,
            },
        },
    )
    assert updated.name == "renamed"
    assert updated.questions == ["q1"]
    assert updated.schedule.cadence == "weekly"
    assert updated.config_version == 2
    assert store.get_monitor(monitor.monitor_id).name == "renamed"
