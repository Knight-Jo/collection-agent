"""Deep-crawl integration across tasks, agent tools, and workflow gates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic_ai import RunContext

import intel_agent.agent as agent_module
from intel_agent.agent import AgentDeps, build_agent
from intel_agent.config import CrawlConfig, Settings
from intel_agent.coverage import eval_coverage
from intel_agent.crawl import create_crawl
from intel_agent.fetch import FetchedResponse
from intel_agent.main import _build_parser
from intel_agent.models import IntelError, IntelTask
from intel_agent.runner import TaskRunSpec, build_task_prompt, run_agent_task
from intel_agent.storage import load_crawl, read_json_object, write_json_atomic
from intel_agent.task import create_task, load_task, set_task_stage
from tests.conftest import DEFAULT_CRITERIA, make_document


def _context(cwd, *, settings: Settings | None = None) -> RunContext[Any]:
    return cast(
        RunContext[Any],
        SimpleNamespace(
            deps=AgentDeps(cwd=cwd, settings=settings or Settings())
        ),
    )


def _tool(agent, name: str):
    return agent._function_toolset.tools[name].function


def test_deep_crawl_persists_and_legacy_tasks_default_off(cwd):
    enabled = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    assert enabled.deep_crawl is True
    assert load_task(cwd, enabled.id).deep_crawl is True

    record = enabled.model_dump()
    record.pop("deep_crawl")
    legacy = IntelTask.model_validate(record)
    assert legacy.deep_crawl is False


def test_task_run_spec_and_cli_keep_deep_crawl_omission_distinct():
    spec = TaskRunSpec(
        topic="主题",
        questions=["问题甲", "问题乙"],
        criteria=DEFAULT_CRITERIA,
    )
    assert spec.deep_crawl is None

    parser = _build_parser()
    base = ["--topic", "主题", "--questions", "问题甲", "问题乙"]
    assert parser.parse_args(base).deep_crawl is None
    assert parser.parse_args([*base, "--deep-crawl"]).deep_crawl is True
    assert parser.parse_args([*base, "--no-deep-crawl"]).deep_crawl is False


@pytest.mark.asyncio
async def test_runner_resolves_deep_crawl_default_before_prompt(
    monkeypatch, cwd
):
    prompts: list[str] = []
    result = SimpleNamespace(output="完成")

    class FakeEvents:
        def __init__(self):
            self.result = result

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeContext:
        async def __aenter__(self):
            return FakeEvents()

        async def __aexit__(self, *_args):
            return False

    class FakeAgent:
        def run_stream_events(self, prompt, **_kwargs):
            prompts.append(prompt)
            return FakeContext()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: "deps",
    )
    spec = TaskRunSpec(
        topic="主题",
        questions=["问题甲", "问题乙"],
        criteria=DEFAULT_CRITERIA,
    )

    await run_agent_task(
        cwd,
        Settings(crawl=CrawlConfig(enabled_by_default=True)),
        spec,
    )

    assert "deep_crawl=true" in prompts[0]
    assert "intel_plan" in build_task_prompt(spec)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "model_argument", "expected"),
    [(None, False, True), (False, True, False)],
)
async def test_runner_deep_crawl_setting_is_authoritative_at_plan_tool(
    monkeypatch, cwd, requested, model_argument, expected
):
    planning_tool = _tool(build_agent(Settings()), "intel_plan")
    result = SimpleNamespace(output="完成")

    class FakeEvents:
        def __init__(self, deps):
            self.deps = deps
            self.result = result

        async def __aenter__(self):
            tool_result = planning_tool(
                cast(RunContext[Any], SimpleNamespace(deps=self.deps)),
                "主题",
                ["问题甲", "问题乙"],
                DEFAULT_CRITERIA,
                model_argument,
            )
            assert tool_result["task"]["deep_crawl"] is expected
            return self

        async def __aexit__(self, *_args):
            await self.deps.http.aclose()
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, _prompt, **kwargs):
            return FakeEvents(kwargs["deps"])

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _settings: FakeAgent()
    )
    spec = TaskRunSpec(
        topic="主题",
        questions=["问题甲", "问题乙"],
        criteria=DEFAULT_CRITERIA,
        deep_crawl=requested,
    )

    await run_agent_task(
        cwd,
        Settings(crawl=CrawlConfig(enabled_by_default=True)),
        spec,
    )

    assert load_task(cwd).deep_crawl is expected


@pytest.mark.asyncio
async def test_web_search_seeds_only_enabled_active_task(monkeypatch, cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )

    async def fake_search(*_args, **_kwargs):
        return {
            "results": [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.com/b", "title": "B"},
            ],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)
    agent = build_agent(Settings())

    result = await _tool(agent, "web_search")(
        _context(cwd), "具体 查询", 5, "general", "zh-CN", None
    )

    assert result["fresh_count"] == 2
    crawl = load_crawl(cwd, task.id)
    assert [entry.canonical_url for entry in crawl.entries] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


@pytest.mark.asyncio
async def test_agent_crawl_collect_rejects_disabled_task(monkeypatch, cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    called = False

    async def fake_collect(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(agent_module, "run_crawl_collect", fake_collect)
    result = await _tool(build_agent(Settings()), "crawl_collect")(
        _context(cwd), task.id
    )

    assert result["error"]["code"] == "INVALID_INPUT"
    assert called is False


def test_document_read_returns_bounded_numbered_verified_lines(cwd):
    document = make_document(cwd, "first\nsecond\nthird")
    record = read_json_object(cwd, f"documents/{document.id}.json")
    record["injection_warnings"] = ["网页包含疑似提示注入文本"]
    write_json_atomic(cwd, f"documents/{document.id}.json", record)
    tool = _tool(build_agent(Settings()), "document_read")

    result = tool(_context(cwd), document.id, 2, 3)
    assert result == {
        "document_id": document.id,
        "start_line": 2,
        "end_line": 3,
        "content": (
            "<untrusted_web_content>\n"
            "2: second\n3: third\n"
            "</untrusted_web_content>"
        ),
        "injection_warnings": ["网页包含疑似提示注入文本"],
    }

    invalid = tool(_context(cwd), document.id, 0, 2)
    assert invalid["error"]["code"] == "INVALID_INPUT"
    past_end = tool(_context(cwd), document.id, 2, 4)
    assert past_end["error"]["code"] == "INVALID_INPUT"

    (cwd / document.text_path).write_text("tampered", encoding="utf-8")
    tampered = tool(_context(cwd), document.id, 1, 1)
    assert tampered["error"]["code"] == "DOCUMENT_TAMPERED"


def test_document_read_requires_complete_extraction(cwd):
    document = make_document(cwd, "text")
    record = read_json_object(cwd, f"documents/{document.id}.json")
    record["extraction_status"] = "failed"
    write_json_atomic(cwd, f"documents/{document.id}.json", record)

    result = _tool(build_agent(Settings()), "document_read")(
        _context(cwd), document.id, 1, 1
    )

    assert result["error"]["code"] == "EXTRACTION_UNAVAILABLE"


def test_deep_crawl_blocks_coverage_and_collect_transition(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    create_crawl(
        cwd,
        task.id,
        ["https://example.com/queued"],
        CrawlConfig(),
    )

    with pytest.raises(IntelError) as coverage_error:
        eval_coverage(cwd, task.id)
    assert coverage_error.value.code == "CRAWL_INCOMPLETE"

    with pytest.raises(IntelError) as transition_error:
        set_task_stage(cwd, task.id, "assess")
    assert transition_error.value.code == "CRAWL_INCOMPLETE"


def test_enabled_task_without_crawl_ledger_is_incomplete(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )

    with pytest.raises(IntelError) as error:
        eval_coverage(cwd, task.id)
    assert error.value.code == "CRAWL_INCOMPLETE"


@pytest.mark.asyncio
async def test_cancelled_crawl_restores_resumable_frontier(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    fetching = asyncio.Event()

    async def fetcher(_url, _init, _address) -> FetchedResponse:
        fetching.set()
        pending: asyncio.Future[FetchedResponse] = asyncio.Future()
        return await pending

    running = asyncio.create_task(
        agent_module.run_crawl_collect(
            cwd,
            task.id,
            ["https://example.com/a"],
            config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
            fetcher=fetcher,
        )
    )
    await asyncio.wait_for(fetching.wait(), timeout=1)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    snapshot = load_crawl(cwd, task.id)
    assert snapshot.status == "paused"
    assert snapshot.entries[0].status == "queued"
