"""In-memory Web run lifecycle tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from intel_agent.config import Settings
from intel_agent.models import IntelError
from intel_agent.web.runs import RunRegistry
from tests.test_runner import make_spec


@pytest.mark.asyncio
async def test_registry_runs_task_and_replays_events(cwd):
    async def fake_runner(
        run_cwd, _settings, spec, *, on_event, cancellation_token
    ):
        from intel_agent.task import create_task

        task = create_task(run_cwd, spec.topic, spec.questions, spec.criteria)
        await on_event(SimpleNamespace(event_kind="function_tool_result"))
        usage = SimpleNamespace(
            requests=3,
            tool_calls=2,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )
        return SimpleNamespace(output="完成", usage=usage, task=task)

    registry = RunRegistry(cwd, Settings(), runner=fake_runner)

    created = await registry.create(make_spec())
    await registry.wait(created.run_id)
    view = registry.get(created.run_id)

    assert view.status == "completed"
    assert view.task_id is not None
    assert view.result == "完成"
    assert [event.type for event in registry.events(created.run_id)] == [
        "run.started",
        "task.updated",
        "run.completed",
    ]


@pytest.mark.asyncio
async def test_registry_blocks_parallel_run_and_cancels(cwd):
    started = asyncio.Event()

    async def slow_runner(
        _cwd, _settings, _spec, *, on_event, cancellation_token
    ):
        started.set()
        while not cancellation_token.cancelled:
            await asyncio.sleep(0)
        return SimpleNamespace(
            output="",
            usage=SimpleNamespace(
                requests=0,
                tool_calls=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            ),
        )

    registry = RunRegistry(cwd, Settings(), runner=slow_runner)
    created = await registry.create(make_spec())
    await started.wait()

    with pytest.raises(IntelError) as error:
        await registry.create(make_spec())
    assert error.value.code == "RUN_ALREADY_ACTIVE"

    registry.cancel(created.run_id)
    await registry.wait(created.run_id)
    assert registry.get(created.run_id).status == "cancelled"
