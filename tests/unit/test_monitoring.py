"""Monitor diff/scheduler/service regression tests (spec 002 US1-US2)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from intel_agent.contracts.documents import (
    Citation,
    EvidenceBlock,
    ExtractResult,
)
from intel_agent.contracts.errors import DomainError
from intel_agent.contracts.research import (
    CoverageAssessment,
    EvidenceItem,
    EvidenceReview,
    ResearchAssessment,
    StopReason,
)
from intel_agent.contracts.resources import (
    FetchRequest,
    FetchResult,
    Resource,
    ResourceOrigin,
)
from intel_agent.fetch.service import FetchService
from intel_agent.monitoring.diff import (
    derive_fact_key,
    diff_baseline,
    normalize_source_key,
    normalize_statement,
)
from intel_agent.monitoring.gates import WatchGate
from intel_agent.monitoring.models import (
    FactVersion,
    Monitor,
    MonitorRun,
    MonitorSchedule,
    WatchSourceState,
)
from intel_agent.monitoring.scheduler import MonitorScheduler, next_run_after
from intel_agent.monitoring.service import MonitoringService
from intel_agent.runtime.config import FetchConfig, ResearchSettings
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
    def __init__(self):
        self.prompts: list[str] = []

    async def run(self, prompt):
        self.prompts.append(prompt)
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


def _assessment(
    claims: list[tuple[str, str]],
    citations: list[Citation],
    stop_reason: StopReason = "evidence_sufficient",
):
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
        stop_reason=stop_reason,
    )


def _schedule():
    return MonitorSchedule(cadence="daily", local_time="09:00", timezone="UTC")


def _service(tmp_path, assessments, settings=None):
    sqlite = SqliteStore(tmp_path / "m.sqlite")
    store = MonitoringStore(sqlite)
    task_store = TaskStore(sqlite)
    app = FakeApplication()
    orchestrator = FakeOrchestrator(assessments)
    service = MonitoringService(
        store,
        task_store,
        orchestrator,
        app,
        settings or ResearchSettings(),
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
    version = store.latest_fact_version(
        monitor.monitor_id, office.current_version_id or ""
    )
    assert version is not None
    assert version.citations[0].citation_id == "c3"

    # run views expose display statuses, not raw task statuses
    detail = service.get(monitor.monitor_id)
    assert detail.runs[-1].status == "succeeded"
    assert detail.runs[-1].run.gate_outcome == ""


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


# --- conditional fetch (gate L0) ---------------------------------------------


class FakeResponse:
    def __init__(self, status_code, headers=None, chunks=()):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.url = "https://watch.example/page"
        self.closed = False

    async def aclose(self):
        self.closed = True

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class FakeHttpClient:
    def __init__(self, response):
        self._response = response
        self.requests: list[dict] = []

    def build_request(self, method, url, headers=None, timeout=None):
        self.requests.append({"url": url, "headers": dict(headers or {})})
        return SimpleNamespace(url=url)

    async def send(self, request, stream=True, follow_redirects=False):
        return self._response


class FakeResourceStore:
    async def write_stream(self, chunks, *, origin, media_type, max_bytes):
        data = b""
        async for chunk in chunks:
            data += chunk
        return Resource(
            resource_id="res-1",
            content_hash=f"sha-{len(data)}",
            byte_length=len(data),
            media_type=media_type,
            content_ref="mem://res-1",
            origin=origin,
            created_at=datetime.now(UTC),
        )


async def test_fetch_sends_conditional_validators_and_handles_304(monkeypatch):
    async def _pass(url):
        return None, []

    monkeypatch.setattr("intel_agent.fetch.service.validate_public_url", _pass)
    client = FakeHttpClient(FakeResponse(304, {"etag": '"v2"'}))
    service = FetchService(client, None, FetchConfig())  # type: ignore[arg-type]
    result = await service.fetch(
        FetchRequest(
            url="https://watch.example/page",
            etag='"v1"',
            last_modified="Wed, 21 Oct 2015 07:28:00 GMT",
        )
    )
    assert result.not_modified
    assert result.resource is None
    assert result.status_code == 304
    assert result.etag == '"v2"'
    sent = client.requests[0]["headers"]
    assert sent["If-None-Match"] == '"v1"'
    assert sent["If-Modified-Since"] == "Wed, 21 Oct 2015 07:28:00 GMT"


async def test_fetch_exposes_validators_on_200(monkeypatch):
    async def _pass(url):
        return None, []

    monkeypatch.setattr("intel_agent.fetch.service.validate_public_url", _pass)
    body = b"<html><body>x</body></html>"
    client = FakeHttpClient(
        FakeResponse(
            200,
            {"etag": '"v3"', "content-type": "text/html"},
            chunks=[body],
        )
    )
    service = FetchService(
        client,  # type: ignore[arg-type]
        FakeResourceStore(),  # type: ignore[arg-type]
        FetchConfig(),
    )
    result = await service.fetch(
        FetchRequest(url="https://watch.example/page")
    )
    assert result.resource is not None
    assert result.resource.byte_length == len(body)
    assert result.etag == '"v3"'
    assert not result.not_modified


# --- watch gate (L0/L1/L2) ---------------------------------------------------


def _resource(content_hash: str) -> Resource:
    now = datetime.now(UTC)
    return Resource(
        resource_id=f"res-{content_hash[:6]}",
        content_hash=content_hash,
        byte_length=10,
        media_type="text/html",
        content_ref=f"mem://{content_hash}",
        origin=ResourceOrigin(
            requested_url="u", final_url="u", acquired_at=now
        ),
        created_at=now,
    )


def _ok_result(byte_hash: str, etag: str | None = None) -> FetchResult:
    return FetchResult(
        resource=_resource(byte_hash),
        status_code=200,
        etag=etag,
        elapsed_ms=5,
    )


def _not_modified(etag: str | None = None) -> FetchResult:
    return FetchResult(
        resource=None,
        status_code=304,
        not_modified=True,
        etag=etag,
        elapsed_ms=2,
    )


class StubFetch:
    def __init__(self, results):
        self._results = list(results)
        self.requests: list[FetchRequest] = []

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request)
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class StubExtraction:
    def __init__(self, texts_by_hash: dict[str, list[str]]):
        self._texts = texts_by_hash
        self.calls = 0

    async def extract(self, resource, profile_id):
        self.calls += 1
        texts = self._texts.get(resource.content_hash, [])
        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=[
                EvidenceBlock(
                    block_id=f"b{i}",
                    text=text,
                    block_type="paragraph",
                    origin_method="native_text",
                    backend_id="stub",
                    backend_version="1",
                )
                for i, text in enumerate(texts)
            ],
            status="success",
            extraction_profile_id=profile_id,
        )


def _watch_monitor(store: MonitoringStore, url: str) -> Monitor:
    now = datetime.now(UTC)
    monitor = Monitor(
        monitor_id="monw",
        name="n",
        subject="s",
        strategy="g",
        websites=[url],
        schedule=MonitorSchedule(
            cadence="daily", local_time="09:00", timezone="UTC"
        ),
        created_at=now,
        updated_at=now,
    )
    store.save_monitor(monitor)
    return monitor


async def test_watch_gate_first_check_is_changed(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    extraction = StubExtraction({"h1": ["alpha beta"]})
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]), extraction, store
    )

    result = await gate.check(monitor)

    check = result.checks[0]
    assert check.outcome == "changed"
    assert not result.should_skip_research
    state = store.get_watch_source("monw", url)
    assert state is not None
    assert state.etag == '"v1"'
    assert state.byte_hash == "h1"
    assert state.content_hash  # extraction ran and the digest is stored


async def test_watch_gate_304_short_circuits_without_extraction(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]),
        StubExtraction({"h1": ["alpha beta"]}),
        store,
    )
    await gate.check(monitor)  # seed baseline state

    extraction = StubExtraction({})
    gate2 = WatchGate(StubFetch([_not_modified('"v1"')]), extraction, store)
    result = await gate2.check(monitor)

    assert result.checks[0].outcome == "unchanged"
    assert result.should_skip_research
    assert extraction.calls == 0  # 304 answered before any parsing
    state = store.get_watch_source("monw", url)
    assert state is not None
    assert state.etag == '"v1"'


async def test_watch_gate_304_sends_stored_validators(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]),
        StubExtraction({"h1": ["alpha beta"]}),
        store,
    )
    await gate.check(monitor)

    fetch = StubFetch([_not_modified('"v1"')])
    gate2 = WatchGate(fetch, StubExtraction({}), store)
    await gate2.check(monitor)

    sent = fetch.requests[0]
    assert sent.etag == '"v1"'
    assert sent.last_modified is None


async def test_watch_gate_same_bytes_skip_extraction(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]),
        StubExtraction({"h1": ["alpha beta"]}),
        store,
    )
    await gate.check(monitor)

    extraction = StubExtraction({"h1": ["alpha beta"]})
    gate2 = WatchGate(
        StubFetch([_ok_result("h1", etag='"v2"')]), extraction, store
    )
    result = await gate2.check(monitor)

    # identical bytes: unchanged even though the server rotated its ETag
    assert result.checks[0].outcome == "unchanged"
    assert result.should_skip_research
    assert extraction.calls == 0
    state = store.get_watch_source("monw", url)
    assert state is not None
    assert state.etag == '"v2"'


async def test_watch_gate_template_churn_is_content_unchanged(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]),
        StubExtraction({"h1": ["alpha beta"]}),
        store,
    )
    await gate.check(monitor)

    # bytes changed (ads/timestamps) but extracted main content is identical
    gate2 = WatchGate(
        StubFetch([_ok_result("h2", etag='"v2"')]),
        StubExtraction({"h2": ["alpha beta"]}),
        store,
    )
    result = await gate2.check(monitor)

    assert result.checks[0].outcome == "content_unchanged"
    assert result.should_skip_research


async def test_watch_gate_real_content_change(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]),
        StubExtraction({"h1": ["alpha beta"]}),
        store,
    )
    await gate.check(monitor)

    gate2 = WatchGate(
        StubFetch([_ok_result("h2", etag='"v2"')]),
        StubExtraction({"h2": ["alpha beta", "new announcement"]}),
        store,
    )
    result = await gate2.check(monitor)

    assert result.checks[0].outcome == "changed"
    assert result.changed_urls == [url]
    assert not result.should_skip_research


async def test_watch_gate_failure_preserves_validators(tmp_path):
    store, _task_store = _store(tmp_path)
    url = "https://watch.example/page"
    monitor = _watch_monitor(store, url)
    gate = WatchGate(
        StubFetch([_ok_result("h1", etag='"v1"')]),
        StubExtraction({"h1": ["alpha beta"]}),
        store,
    )
    await gate.check(monitor)

    gate2 = WatchGate(
        StubFetch([DomainError("NETWORK_ERROR", "down", stage="fetch")]),
        StubExtraction({}),
        store,
    )
    result = await gate2.check(monitor)

    check = result.checks[0]
    assert check.outcome == "failed"
    assert check.error_code == "NETWORK_ERROR"
    assert not result.should_skip_research  # failure is not "no change"
    state = store.get_watch_source("monw", url)
    assert state is not None
    assert state.etag == '"v1"'  # last good validators survive
    assert state.byte_hash == "h1"


# --- gate integration with the run flow --------------------------------------


class NoCallOrchestrator(FakeOrchestrator):
    async def run_assessment(self, task, plan=None):
        raise AssertionError("research loop must not run when gate is green")


async def test_monitor_run_skips_research_when_gate_unchanged(tmp_path):
    sqlite = SqliteStore(tmp_path / "m.sqlite")
    store = MonitoringStore(sqlite)
    task_store = TaskStore(sqlite)
    app = FakeApplication()
    url = "https://watch.example/page"
    service = MonitoringService(
        store,
        task_store,
        NoCallOrchestrator([]),
        app,
        ResearchSettings(),
    )
    monitor = service.create_monitor(
        "m", "s", "g", _schedule(), websites=[url]
    )
    store.save_watch_source(
        WatchSourceState(
            monitor_id=monitor.monitor_id,
            url=url,
            etag='"v1"',
            byte_hash="h1",
            content_hash="c1",
            last_checked_at=datetime.now(UTC),
            last_outcome="changed",
        )
    )
    gate = WatchGate(
        StubFetch([_not_modified('"v1"')]), StubExtraction({}), store
    )
    service.gate = gate

    run = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()

    assert task_store.get_task(run.task_id).status == "completed"
    loaded = store.get_run(run.run_id)
    assert loaded.gate_outcome.startswith("skipped:")
    assert "unchanged" in loaded.gate_outcome
    assert "跳过" in loaded.summary
    monitor = store.get_monitor(monitor.monitor_id)
    assert monitor.active_run_id is None
    assert monitor.next_run_at is not None


async def test_monitor_run_gate_changed_proceeds_to_research(tmp_path):
    sqlite = SqliteStore(tmp_path / "m.sqlite")
    store = MonitoringStore(sqlite)
    task_store = TaskStore(sqlite)
    app = FakeApplication()
    url = "https://watch.example/page"
    assessment = _assessment(
        [("Acme employs 5000 people.", "c1")],
        [_citation("c1", "https://example.com/reports")],
    )
    service = MonitoringService(
        store,
        task_store,
        FakeOrchestrator([assessment]),
        app,
        ResearchSettings(),
    )
    monitor = service.create_monitor(
        "m", "s", "g", _schedule(), websites=[url]
    )
    gate = WatchGate(
        StubFetch([_ok_result("h9", etag='"v9"')]),
        StubExtraction({"h9": ["acme employs 5000 people"]}),
        store,
    )
    service.gate = gate

    run = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()

    loaded = store.get_run(run.run_id)
    assert loaded.gate_outcome == "changed=1"
    assert task_store.get_task(run.task_id).status == "completed"
    # initial baseline run recorded facts without changes
    assert store.list_changes(run.run_id) == []


async def test_plan_prompt_includes_questions_and_websites(tmp_path):
    service, _store, _task_store, app = _service(
        tmp_path,
        [
            _assessment(
                [("Acme employs 5000 people.", "c1")],
                [_citation("c1", "https://example.com/reports")],
            )
        ],
    )
    monitor = service.create_monitor(
        "m",
        "s",
        "g",
        _schedule(),
        questions=["What is Acme's revenue?"],
        websites=["https://watch.example/page"],
    )
    await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()

    planner = service.orchestrator.roles["planner"]
    prompt = planner.prompts[0]
    assert "What is Acme's revenue?" in prompt
    assert "https://watch.example/page" in prompt


# --- failure backoff and degraded state --------------------------------------


async def test_failure_backoff_and_degraded_then_recover(tmp_path):
    from intel_agent.runtime.config import MonitorConfig

    settings = ResearchSettings(
        monitor=MonitorConfig(
            failure_backoff_base_seconds=60,
            failure_backoff_max_seconds=600,
            degraded_after_failures=2,
        )
    )
    claims = [("Acme employs 5000 people.", "c1")]
    citations = [_citation("c1", "https://example.com/reports")]
    service, store, task_store, app = _service(
        tmp_path,
        [
            RuntimeError("first"),
            RuntimeError("second"),
            _assessment(claims, citations),
        ],
        settings=settings,
    )
    monitor = service.create_monitor("m", "s", "g", _schedule())
    before = datetime.now(UTC)

    await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    m = store.get_monitor(monitor.monitor_id)
    assert m.consecutive_failures == 1
    assert m.status == "active"
    # backoff (60s), not the next daily slot (hours away)
    assert m.next_run_at is not None
    delay = (m.next_run_at - before).total_seconds()
    assert 0 < delay < 3600

    await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    m = store.get_monitor(monitor.monitor_id)
    assert m.consecutive_failures == 2
    assert m.status == "degraded"  # threshold reached
    # degraded monitors remain schedulable (under backoff)
    assert m.next_run_at is not None
    at_due = m.next_run_at + timedelta(seconds=1)
    assert monitor.monitor_id in {
        x.monitor_id for x in store.list_due_monitors(at_due)
    }

    run3 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    m = store.get_monitor(monitor.monitor_id)
    assert m.consecutive_failures == 0  # success resets health
    assert m.status == "active"
    assert task_store.get_task(run3.task_id).status == "completed"


# --- scheduler daemon --------------------------------------------------------


def _with_next_run(store, monitor, when):
    store.set_next_run(monitor.monitor_id, when)


async def test_scheduler_tick_selects_due_and_caps_burst(tmp_path):
    service, store, _task_store, app = _service(
        tmp_path,
        [
            _assessment(
                [("a", "c1")], [_citation("c1", "https://x.example/1")]
            ),
            _assessment(
                [("b", "c1")], [_citation("c1", "https://x.example/2")]
            ),
            _assessment(
                [("c", "c1")], [_citation("c1", "https://x.example/3")]
            ),
        ],
    )
    now = datetime.now(UTC)
    past = now - timedelta(minutes=5)
    m1 = service.create_monitor("m1", "s", "g", _schedule())
    m2 = service.create_monitor("m2", "s", "g", _schedule())
    m3 = service.create_monitor("m3", "s", "g", _schedule())
    m4 = service.create_monitor("m4", "s", "g", _schedule())  # future
    m5 = service.create_monitor("m5", "s", "g", _schedule())  # paused
    service.update_monitor(m5.monitor_id, {"status": "paused"})
    for m in (m1, m2, m3, m5):
        _with_next_run(store, m, past)
    _with_next_run(store, m4, now + timedelta(hours=3))

    due_ids = {m.monitor_id for m in service.due_monitors(now)}
    assert due_ids == {m1.monitor_id, m2.monitor_id, m3.monitor_id}
    # paused and future monitors are never due

    scheduler = MonitorScheduler(
        service,
        interval_seconds=60,
        jitter_seconds=0,
        max_submissions_per_tick=2,
    )
    run_ids = await scheduler.tick()
    assert len(run_ids) == 2  # burst cap
    assert len(app.launched) == 2
    # future monitor untouched
    assert store.list_runs(m4.monitor_id) == []

    # complete the two submitted runs, then only the remaining monitor is due
    await app.run_pending()
    run_ids2 = await scheduler.tick()
    assert len(run_ids2) == 1


async def test_scheduler_tolerates_active_run_conflict(tmp_path):
    service, store, _task_store, app = _service(tmp_path, [])
    monitor = service.create_monitor("m", "s", "g", _schedule())
    _with_next_run(store, monitor, datetime.now(UTC) - timedelta(minutes=1))
    await service.submit_run(monitor.monitor_id, "manual")  # slot occupied

    scheduler = MonitorScheduler(
        service,
        interval_seconds=60,
        jitter_seconds=0,
        max_submissions_per_tick=3,
    )
    run_ids = await scheduler.tick()  # must not raise CONFLICT
    assert run_ids == []


async def test_scheduler_start_stop_lifecycle(tmp_path):
    service, _store, _task_store, _app = _service(tmp_path, [])
    scheduler = MonitorScheduler(
        service,
        interval_seconds=0.01,
        jitter_seconds=0,
        max_submissions_per_tick=1,
    )
    scheduler.start()
    assert scheduler.running
    await asyncio.sleep(0.05)  # let at least one tick pass
    await scheduler.stop()
    assert not scheduler.running
    await asyncio.sleep(0.02)  # no further ticks after stop


# --- change deduplication -----------------------------------------------------


async def test_change_dedup_until_baseline_advances(tmp_path):
    baseline_claims = [
        ("Acme employs 5000 people.", "c1"),
        ("Acme is headquartered in Paris.", "c1"),
    ]
    later_claims = baseline_claims + [
        ("Acme opened a new office.", "c1"),
    ]
    cits = [_citation("c1", "https://example.com/reports")]
    service, store, _task_store, app = _service(
        tmp_path,
        [
            _assessment(baseline_claims, cits),  # baseline, sufficient
            _assessment(later_claims, cits, stop_reason="max_rounds"),
            _assessment(later_claims, cits, stop_reason="max_rounds"),
            _assessment(later_claims, cits),  # sufficient: advance + clear
        ],
    )
    monitor = service.create_monitor("m", "Acme", "track", _schedule())

    run1 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()  # baseline frozen, no events
    assert store.list_changes(run1.run_id) == []

    run2 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    kinds2 = [c.kind for c in store.list_changes(run2.run_id)]
    assert kinds2 == ["new_fact"]  # the office fact is new

    run3 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    assert store.list_changes(run3.run_id) == []  # suppressed repeat

    run4 = await service.submit_run(monitor.monitor_id, "manual")
    await app.run_pending()
    assert store.list_changes(run4.run_id) == []  # still suppressed
    # baseline advanced and the suppression set was cleared
    assert store.get_monitor(monitor.monitor_id).baseline_run_id == run4.run_id
    assert store.reported_fingerprints(monitor.monitor_id) == set()
