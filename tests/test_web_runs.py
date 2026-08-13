"""In-memory Web run lifecycle tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

import intel_agent.extract as extract_module
import intel_agent.runner as runner_module
from intel_agent.agent import AgentDeps, build_deps
from intel_agent.config import CrawlConfig, Settings
from intel_agent.crawl import crawl_collect
from intel_agent.fetch import FetchedResponse
from intel_agent.models import IntelError
from intel_agent.storage import load_crawl
from intel_agent.task import create_task
from intel_agent.web.runs import RunRegistry
from tests.test_runner import make_spec


def _blocking_whisper_worker(_audio, marker_path, _results):
    Path(marker_path).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(30)


@pytest.mark.asyncio
async def test_registry_runs_task_and_replays_events(cwd):
    async def fake_runner(
        run_cwd, _settings, spec, *, on_event, cancellation_token
    ):
        from intel_agent.task import create_task

        task = create_task(run_cwd, spec.topic, spec.questions, spec.criteria)
        from intel_agent.task import save_task

        save_task(
            run_cwd,
            task.model_copy(
                update={"stage": "done", "completion_status": "sufficient"}
            ),
        )
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

    assert view.status == "completed_sufficient"
    assert view.task_id is not None
    assert view.result == "完成"
    assert [event.type for event in registry.events(created.run_id)] == [
        "run.started",
        "task.updated",
        "run.completed",
    ]


@pytest.mark.asyncio
async def test_registry_marks_model_stop_before_done_as_incomplete(cwd):
    async def fake_runner(
        run_cwd, _settings, spec, *, on_event, cancellation_token
    ):
        create_task(run_cwd, spec.topic, spec.questions, spec.criteria)
        return SimpleNamespace(
            output="stopped",
            usage=SimpleNamespace(
                requests=1,
                tool_calls=0,
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )

    registry = RunRegistry(cwd, Settings(), runner=fake_runner)

    created = await registry.create(make_spec())
    await registry.wait(created.run_id)
    view = registry.get(created.run_id)

    assert view.status == "failed"
    assert view.error is not None
    assert view.error.code == "RUN_INCOMPLETE"


@pytest.mark.asyncio
async def test_registry_exposes_completed_with_gaps(cwd):
    async def fake_runner(
        run_cwd, _settings, spec, *, on_event, cancellation_token
    ):
        task = create_task(run_cwd, spec.topic, spec.questions, spec.criteria)
        from intel_agent.task import save_task

        save_task(
            run_cwd,
            task.model_copy(
                update={"stage": "done", "completion_status": "with_gaps"}
            ),
        )
        return SimpleNamespace(
            output="done",
            usage=SimpleNamespace(
                requests=1,
                tool_calls=0,
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )

    registry = RunRegistry(cwd, Settings(), runner=fake_runner)

    created = await registry.create(make_spec())
    await registry.wait(created.run_id)

    assert registry.get(created.run_id).status == "completed_with_gaps"


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


@pytest.mark.asyncio
async def test_registry_projects_live_crawl_events(cwd):
    async def fake_runner(
        run_cwd, _settings, spec, *, on_event, cancellation_token
    ):
        from intel_agent.task import create_task

        task = create_task(
            run_cwd,
            spec.topic,
            spec.questions,
            spec.criteria,
            deep_crawl=True,
        )

        async def fetcher(_url, _init, _address):
            return FetchedResponse(
                status=200,
                headers={"content-type": "text/plain"},
                body=b"resource",
            )

        async def resolver(_hostname):
            return ["93.184.216.34"]

        async def forward_event(event):
            if event.type == "crawl.completed":
                assert load_crawl(run_cwd, task.id).status == "complete"
            await on_event(event)

        await crawl_collect(
            run_cwd,
            task.id,
            ["https://example.com/resource.txt"],
            config=CrawlConfig(
                max_depth=0,
                obey_robots=False,
                per_host_delay_seconds=0,
            ),
            fetcher=fetcher,
            resolver=resolver,
            on_event=forward_event,
        )
        usage = SimpleNamespace(
            requests=0,
            tool_calls=1,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
        )
        return SimpleNamespace(output="done", usage=usage)

    registry = RunRegistry(cwd, Settings(), runner=fake_runner)

    created = await registry.create(make_spec())
    await registry.wait(created.run_id)
    crawl_events = [
        event
        for event in registry.events(created.run_id)
        if event.type.startswith("crawl.")
    ]

    assert {event.type for event in crawl_events} == {
        "crawl.started",
        "crawl.progress",
        "crawl.resource",
        "crawl.completed",
    }
    assert crawl_events[0].type == "crawl.started"
    assert crawl_events[-1].type == "crawl.completed"
    assert crawl_events[-1].data["status"] == "complete"
    resource = next(
        event for event in crawl_events if event.type == "crawl.resource"
    )
    assert resource.data["resource"]["document_id"] is not None
    assert resource.data["counts"]["complete"] == 1


@pytest.mark.asyncio
async def test_registry_cancellation_pauses_crawl_for_resume(cwd, monkeypatch):
    marker = cwd / "whisper.pid"
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        make_spec().criteria,
        deep_crawl=True,
    )
    settings = Settings(
        crawl=CrawlConfig(
            max_depth=0,
            obey_robots=False,
            per_host_delay_seconds=0,
            whisper_model=str(marker),
        )
    )
    agent = Agent(
        TestModel(call_tools=["crawl_collect"]),
        deps_type=AgentDeps,
        output_type=str,
    )

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "audio/mpeg"},
            body=b"audio",
        )

    async def resolver(_hostname):
        return ["93.184.216.34"]

    @agent.tool(name="crawl_collect")
    async def crawl_collect_tool(ctx: RunContext[AgentDeps]):
        return await crawl_collect(
            ctx.deps.cwd,
            task.id,
            ["https://example.com/clip.mp3"],
            config=ctx.deps.settings.crawl,
            fetcher=fetcher,
            resolver=resolver,
            on_event=ctx.deps.crawl_event_callback,
        )

    def fake_run_process(command, _cancellation_event=None):
        Path(command[-1]).write_bytes(b"wav")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    deps: list[AgentDeps] = []

    def capture_deps(*args, **kwargs):
        built = build_deps(*args, **kwargs)
        deps.append(built)
        return built

    monkeypatch.setattr(runner_module, "build_agent", lambda _settings: agent)
    monkeypatch.setattr(runner_module, "build_deps", capture_deps)
    monkeypatch.setattr(
        extract_module, "_whisper_worker", _blocking_whisper_worker
    )
    monkeypatch.setattr(extract_module, "_run_process", fake_run_process)
    monkeypatch.setattr(extract_module.shutil, "which", lambda _name: "ffmpeg")
    registry = RunRegistry(cwd, settings)

    try:
        created = await registry.create(
            make_spec().model_copy(update={"deep_crawl": True})
        )
        async with asyncio.timeout(10):
            while not marker.exists():
                view = registry.get(created.run_id)
                assert view.status not in {
                    "failed",
                    "completed_sufficient",
                    "completed_with_gaps",
                    "cancelled",
                }, view.error
                await asyncio.sleep(0.01)
        pid = int(marker.read_text(encoding="utf-8"))

        started = asyncio.get_running_loop().time()
        registry.cancel(created.run_id)
        await asyncio.wait_for(registry.wait(created.run_id), timeout=2)

        assert asyncio.get_running_loop().time() - started < 2
        assert registry.get(created.run_id).status == "cancelled"
        event_types = [event.type for event in registry.events(created.run_id)]
        assert "run.cancelled" in event_types
        assert "crawl.completed" not in event_types
        snapshot = load_crawl(cwd, task.id)
        assert snapshot.status == "paused"
        assert snapshot.entries[0].status == "queued"
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        for item in deps:
            await item.http.aclose()
