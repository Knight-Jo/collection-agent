from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pydantic_ai import CancellationToken
from pydantic_ai.models.test import TestModel

import intel_agent.continuation as continuation_module
from intel_agent.agent import build_agent, build_deps
from intel_agent.continuation import (
    ALLOWED_CONTINUATION_TOOLS,
    ContinuationRunner,
)
from intel_agent.fact import save_fact
from intel_agent.materials import register_material
from intel_agent.models import ResearchBrief
from intel_agent.state_store import StateStore
from intel_agent.task import load_task
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
