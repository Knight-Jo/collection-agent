"""In-memory Web run lifecycle tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import RunCancelled

from intel_agent.config import CrawlConfig, Settings
from intel_agent.crawl import crawl_collect
from intel_agent.fetch import FetchedResponse
from intel_agent.models import IntelError
from intel_agent.storage import load_crawl
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
async def test_registry_cancellation_pauses_crawl_for_resume(cwd):
    fetching = asyncio.Event()
    task_ids: list[str] = []

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
        task_ids.append(task.id)

        async def fetcher(_url, _init, _address):
            fetching.set()
            return await asyncio.Future()

        async def resolver(_hostname):
            return ["93.184.216.34"]

        crawl = asyncio.create_task(
            crawl_collect(
                run_cwd,
                task.id,
                ["https://example.com/resource.txt"],
                config=CrawlConfig(
                    obey_robots=False, per_host_delay_seconds=0
                ),
                fetcher=fetcher,
                resolver=resolver,
                on_event=on_event,
            )
        )
        while not cancellation_token.cancelled:
            await asyncio.sleep(0)
        crawl.cancel()
        try:
            await crawl
        except asyncio.CancelledError as error:
            raise RunCancelled("cancelled") from error

    registry = RunRegistry(cwd, Settings(), runner=fake_runner)
    created = await registry.create(make_spec())
    await fetching.wait()

    registry.cancel(created.run_id)
    await registry.wait(created.run_id)

    assert registry.get(created.run_id).status == "cancelled"
    assert "run.cancelled" in [
        event.type for event in registry.events(created.run_id)
    ]
    snapshot = load_crawl(cwd, task_ids[0])
    assert snapshot.status == "paused"
    assert snapshot.entries[0].status == "queued"
