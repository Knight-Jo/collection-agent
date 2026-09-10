"""Crash-injection / recovery integration tests (spec 002 SC-402)."""

from __future__ import annotations

import asyncio

import pytest

from intel_agent.application import ResearchApplication
from intel_agent.contracts.errors import DomainError
from intel_agent.runtime.config import ResearchSettings
from intel_agent.storage.materials import MaterialStore
from intel_agent.storage.sqlite import SqliteStore
from intel_agent.storage.tasks import TaskStore


class _FakeOrchestrator:
    def __init__(self):
        self.ran = []

    async def run_task(self, task):
        self.ran.append(task.task_id)
        return None


def _app(tmp_path, orchestrator=None):
    sqlite = SqliteStore(tmp_path / "c.sqlite")
    store = MaterialStore(sqlite)
    task_store = TaskStore(sqlite)
    app = ResearchApplication(
        store,
        task_store,
        orchestrator or _FakeOrchestrator(),  # type: ignore[arg-type]
        ResearchSettings(),
        concurrency=4,
    )
    return app, task_store


def test_claim_queued_atomic_and_conflict(tmp_path):
    _, task_store = _app(tmp_path)
    task = task_store.create_task("q", kind="monitor")
    assert task_store.claim_queued(task.task_id) == 1
    with pytest.raises(DomainError) as raised:
        task_store.claim_queued(task.task_id)
    assert raised.value.code == "CONFLICT"
    assert task_store.get_task(task.task_id).attempt == 1
    task_store.update_task_status(task.task_id, "queued")
    assert task_store.claim_queued(task.task_id) == 2


def test_recover_interrupts_running_and_requeues_queued(tmp_path):
    app, task_store = _app(tmp_path)

    running = task_store.create_task("a", kind="research")
    task_store.claim_queued(running.task_id)

    queued = task_store.create_task("b", kind="research")

    executed = []

    async def runner(task_id):
        task_store.claim_queued(task_id)
        executed.append(task_id)

    app.register_runner("research", runner)

    async def scenario():
        await app.recover()
        await asyncio.sleep(0.1)

    asyncio.run(scenario())

    assert task_store.get_task(running.task_id).status == "interrupted"
    assert task_store.get_task(queued.task_id).status == "running"
    assert queued.task_id in executed


def _record(tid, sink):
    async def runner(task_id):
        sink.append(task_id)

    return runner(tid)


def test_idempotency_same_input_returns_original(tmp_path):
    _, task_store = _app(tmp_path)
    assert task_store.register_idempotent(
        "factcheck_submit", "k", "h1", "fc-1"
    )
    assert not task_store.register_idempotent(
        "factcheck_submit", "k", "h1", "fc-2"
    )
    record = task_store.find_idempotent("factcheck_submit", "k")
    assert record is not None
    assert record["input_hash"] == "h1"
    assert record["result_ref"] == "fc-1"


def test_idempotency_different_input_is_new_operation(tmp_path):
    _, task_store = _app(tmp_path)
    assert task_store.register_idempotent("monitor_run", "k", "h1", "r1")
    # different operation namespace: same key is independent
    assert task_store.register_idempotent(
        "factcheck_submit", "k", "h1", "fc-1"
    )


def test_timeline_persists_attempts(tmp_path):
    _, task_store = _app(tmp_path)
    task = task_store.create_task("q", kind="media")
    task_store.add_timeline(task.task_id, "queued", "submitted", attempt=0)
    task_store.add_timeline(task.task_id, "transcribing", "started", attempt=1)
    entries = task_store.list_timeline(task.task_id)
    assert [e.phase for e in entries] == ["queued", "transcribing"]
    assert [e.sequence for e in entries] == [1, 2]
