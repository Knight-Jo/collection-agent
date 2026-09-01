from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from pydantic_ai import CancellationToken
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel

import intel_agent.continuation as continuation_module
from intel_agent.agent import build_agent, build_deps
from intel_agent.continuation import (
    ALLOWED_CONTINUATION_TOOLS,
    ContinuationRunner,
)
from intel_agent.fact import save_fact
from intel_agent.materials import register_material
from intel_agent.models import ResearchBrief, TaskOutputBinding
from intel_agent.state_store import StateStore
from intel_agent.task import load_task, save_task
from intel_agent.trajectory import make_event
from tests.conftest import make_document, new_task, save_evidence


async def test_initial_run_uses_bound_task_and_commits_assets(
    monkeypatch, cwd
):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    run = store.create_run(task.id, "initial", 0, {})

    async def fake_agent_task(_cwd, _settings, spec, **_kwargs):
        assert spec.topic == task.topic
        document = make_document(cwd, "初次调研材料")
        register_material(
            cwd,
            task.id,
            document.canonical_url,
            document_id=document.id,
        )
        return SimpleNamespace(output="done")

    monkeypatch.setattr(continuation_module, "run_agent_task", fake_agent_task)
    runner = ContinuationRunner(cwd, store=store)

    await runner.run_initial(
        run,
        ResearchBrief(topic=task.topic, key_questions=["问题"]),
        CancellationToken(),
    )

    assert store.get_run(run.id).status == "succeeded"
    assert store.committed_state_version(task.id) == 1
    assert store.committed_asset_ids(task.id, "document")


async def test_initial_run_creates_and_closes_default_trajectory(
    monkeypatch, cwd
):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    run = store.create_run(task.id, "initial", 0, {})

    async def fake_agent_task(_cwd, _settings, _spec, **kwargs):
        recorder = kwargs["recorder"]
        assert recorder is not None
        recorder.record(
            make_event("run_started", "system", {}, layer="evaluation")
        )
        recorder.record(
            make_event(
                "run_finished",
                "system",
                {"status": "succeeded"},
                layer="evaluation",
            )
        )
        return SimpleNamespace(output="done")

    monkeypatch.setattr(continuation_module, "run_agent_task", fake_agent_task)
    runner = ContinuationRunner(cwd, store=store)

    await runner.run_initial(
        run,
        ResearchBrief(topic=task.topic, key_questions=["问题"]),
    )

    trace = cwd / "data" / "runs" / run.id / "trace.jsonl"
    assert trace.exists()
    assert [
        json.loads(line)["sequence"] for line in trace.read_text().splitlines()
    ] == [1, 2]


async def test_continuation_run_records_native_events(monkeypatch, cwd):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    trigger = store.add_user_message(task.id, "继续搜索", "client-trace")
    action = store.create_action(
        task.id, trigger.id, "continue_research", {"topic": "供应链"}
    )

    class FakeEvents:
        def __init__(self):
            self.result = SimpleNamespace(output="done")
            self.events = iter(
                [
                    FunctionToolCallEvent(
                        part=ToolCallPart(
                            tool_name="web_search",
                            tool_call_id="call-1",
                            args={"query": "供应链"},
                        )
                    ),
                    FunctionToolResultEvent(
                        ToolReturnPart(
                            tool_name="web_search",
                            tool_call_id="call-1",
                            content={"count": 1, "results": ["result"]},
                        )
                    ),
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration as error:
                raise StopAsyncIteration from error

    class FakeAgent:
        def run_stream_events(self, _prompt, **_kwargs):
            return FakeEvents()

    monkeypatch.setattr(
        continuation_module,
        "build_agent",
        lambda *_args, **_kwargs: FakeAgent(),
    )
    runner = ContinuationRunner(cwd, store=store)

    result = await runner.run(action)

    assert result.status == "succeeded"
    run = store.list_runs(task.id)[0]
    records = [
        json.loads(line)
        for line in (cwd / "data" / "runs" / run.id / "trace.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [record["event_type"] for record in records] == [
        "run_started",
        "decision",
        "action",
        "observation",
        "run_finished",
    ]
    assert records[-1]["payload"]["status"] == "succeeded"


def test_build_agent_filters_continuation_tools(monkeypatch, cwd):
    captured: list[list[str]] = []
    monkeypatch.setattr(
        "intel_agent.agent._build_chat_model",
        lambda _cfg, _key: TestModel(custom_output_text="完成", call_tools=[]),
    )
    agent = build_agent(
        allowed_tools=ALLOWED_CONTINUATION_TOOLS,
        conversation_capture=lambda _messages, specs: captured.append(
            [item["name"] for item in specs]
        ),
    )

    agent.run_sync("继续调研", deps=build_deps(cwd))

    assert captured
    assert set(captured[-1]) == ALLOWED_CONTINUATION_TOOLS
    assert "intel_plan" not in captured[-1]
    assert "generate_research_report" not in captured[-1]


async def test_continuation_commits_new_assets_and_activates_task(
    monkeypatch, cwd
):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    trigger = store.add_user_message(task.id, "继续搜索", "client-1")
    action = store.create_action(
        task.id, trigger.id, "continue_research", {"topic": "供应链"}
    )

    class _Agent:
        async def run(self, _prompt, *, deps, **_kwargs):
            document = make_document(cwd, "新增供应链事实")
            register_material(
                cwd,
                task.id,
                document.canonical_url,
                document_id=document.id,
            )
            fact = save_fact(
                cwd,
                task.id,
                task.questions[0].id,
                "新增供应链事实",
            )
            save_evidence(cwd, fact.id, document, "supports", "新增供应链事实")
            return SimpleNamespace(output="done")

    monkeypatch.setattr(
        continuation_module, "build_agent", lambda *_args, **_kwargs: _Agent()
    )
    runner = ContinuationRunner(cwd, store=store)

    result = await runner.run(action)

    assert result.status == "succeeded"
    assert load_task(cwd).id == task.id
    assert store.committed_state_version(task.id) == 1
    assert store.committed_asset_ids(task.id, "fact")
    assert store.list_runs(task.id)[0].status == "succeeded"


async def test_failed_continuation_does_not_commit_json_orphans(
    monkeypatch, cwd
):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    trigger = store.add_user_message(task.id, "继续搜索", "client-1")
    action = store.create_action(
        task.id, trigger.id, "continue_research", {"topic": "风险"}
    )

    class _FailingAgent:
        async def run(self, _prompt, *, deps, **_kwargs):
            document = make_document(cwd, "失败运行遗留材料")
            register_material(
                cwd,
                task.id,
                document.canonical_url,
                document_id=document.id,
            )
            raise RuntimeError("model failed")

    monkeypatch.setattr(
        continuation_module,
        "build_agent",
        lambda *_args, **_kwargs: _FailingAgent(),
    )
    runner = ContinuationRunner(cwd, store=store)

    result = await runner.run(action)

    assert result.status == "failed"
    assert store.committed_state_version(task.id) == 0
    assert store.committed_asset_ids(task.id, "document") == set()
    assert store.list_runs(task.id)[0].status == "failed"


async def test_cancelled_continuation_marks_run_and_action(cwd):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    trigger = store.add_user_message(task.id, "继续搜索", "client-1")
    action = store.create_action(
        task.id, trigger.id, "continue_research", {"topic": "风险"}
    )
    token = CancellationToken()
    token.cancel()
    runner = ContinuationRunner(cwd, store=store)

    result = await runner.run(action, token)

    assert result.status == "cancelled"
    assert store.list_runs(task.id)[0].status == "cancelled"


async def test_stop_running_continuation_preserves_committed_boundary(
    monkeypatch, cwd
):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    trigger = store.add_user_message(task.id, "继续搜索", "client-1")
    action = store.create_action(
        task.id, trigger.id, "continue_research", {"topic": "风险"}
    )
    started = asyncio.Event()
    token = CancellationToken()

    class _WaitingAgent:
        async def run(self, _prompt, **_kwargs):
            started.set()
            while not token.cancelled:
                await asyncio.sleep(0)
            raise asyncio.CancelledError

    monkeypatch.setattr(
        continuation_module,
        "build_agent",
        lambda *_args, **_kwargs: _WaitingAgent(),
    )
    runner = ContinuationRunner(cwd, store=store)
    execution = asyncio.create_task(runner.run(action, token))
    await started.wait()

    token.cancel()
    result = await execution

    assert result.status == "cancelled"
    assert store.list_runs(task.id)[0].status == "stopped"
    assert store.committed_state_version(task.id) == 0


async def test_continuations_create_run_only_after_workspace_claim(
    monkeypatch, cwd
):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    first_trigger = store.add_user_message(task.id, "继续搜索", "client-1")
    second_trigger = store.add_user_message(task.id, "继续搜索", "client-2")
    first = store.create_action(
        task.id, first_trigger.id, "continue_research", {"topic": "甲"}
    )
    second = store.create_action(
        task.id, second_trigger.id, "continue_research", {"topic": "乙"}
    )
    started = asyncio.Event()
    release = asyncio.Event()

    class _WaitingAgent:
        async def run(self, _prompt, **_kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(output="done")

    monkeypatch.setattr(
        continuation_module,
        "build_agent",
        lambda *_args, **_kwargs: _WaitingAgent(),
    )
    runner = ContinuationRunner(cwd, store=store)
    first_task = asyncio.create_task(runner.run(first))
    await started.wait()
    second_task = asyncio.create_task(runner.run(second))
    await asyncio.sleep(0)

    assert len(store.list_runs(task.id)) == 1
    assert store.get_action(second.id).status == "queued"

    release.set()
    await first_task
    await second_task
    assert len(store.list_runs(task.id)) == 2


def _running_run(store, cwd, task):
    store.register_task(task.id)
    run = store.create_run(task.id, "initial", 0, {})
    store.claim_run(
        run.id,
        phase="collecting",
        lease_owner=run.id,
        lease_expires_at="2099-01-01T00:00:00Z",
    )
    return store.get_run(run.id)


def test_gracefully_finish_succeeds_when_task_done(cwd):
    # Web run 057: finish_run hit database is locked after the agent already
    # reached done and produced a report; the run must not be marked failed.
    from intel_agent.continuation import _gracefully_finish_or_fail

    task = new_task(cwd)
    task = task.model_copy(
        update={
            "stage": "done",
            "outputs": task.outputs.model_copy(
                update={
                    "report": TaskOutputBinding(
                        coverage_id="cov-x",
                        coverage_fingerprint="fp",
                        path="output/report.md",
                        content_sha256="sha",
                        created_at="2026-01-01T00:00:00Z",
                    )
                }
            ),
        }
    )
    save_task(cwd, task)
    store = StateStore(cwd)
    run = _running_run(store, cwd, task)

    result = _gracefully_finish_or_fail(
        store, cwd, run, RuntimeError("database is locked")
    )

    assert result.status == "succeeded"


def test_gracefully_finish_fails_when_task_incomplete(cwd):
    from intel_agent.continuation import _gracefully_finish_or_fail

    task = new_task(cwd)
    store = StateStore(cwd)
    run = _running_run(store, cwd, task)

    result = _gracefully_finish_or_fail(
        store, cwd, run, RuntimeError("model failed")
    )

    assert result.status == "failed"


def test_retry_on_locked_retries_then_succeeds():
    import sqlite3

    from intel_agent.state_store import _retry_on_locked

    calls = {"n": 0}

    @_retry_on_locked
    def operation():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert operation() == "ok"
    assert calls["n"] == 3


def test_retry_on_locked_gives_up_after_attempts():
    import sqlite3

    import pytest

    from intel_agent.state_store import _retry_on_locked

    @_retry_on_locked
    def operation():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        operation()


def test_retry_on_locked_does_not_retry_other_errors():
    import sqlite3

    import pytest

    from intel_agent.state_store import _retry_on_locked

    calls = {"n": 0}

    @_retry_on_locked
    def operation():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table")

    with pytest.raises(sqlite3.OperationalError):
        operation()
    assert calls["n"] == 1
