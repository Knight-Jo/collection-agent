"""Deep-crawl integration across tasks, agent tools, and workflow gates."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic_ai import RunContext

import intel_agent.agent as agent_module
from intel_agent import trajectory
from intel_agent.agent import AgentDeps, build_agent
from intel_agent.audit import audit_task_evidence
from intel_agent.config import (
    BudgetConfig,
    ContextConfig,
    CrawlConfig,
    Settings,
    SourcesConfig,
)
from intel_agent.coverage import eval_coverage
from intel_agent.crawl import create_crawl
from intel_agent.evidence import save_evidence
from intel_agent.fact import save_fact
from intel_agent.fetch import FetchedResponse
from intel_agent.main import _build_parser
from intel_agent.materials import load_material_digest, register_material
from intel_agent.models import IntelError, IntelTask
from intel_agent.runner import TaskRunSpec, build_task_prompt, run_agent_task
from intel_agent.storage import load_crawl, read_json_object, write_json_atomic
from intel_agent.task import create_task, load_task, save_task, set_task_stage
from intel_agent.trajectory import JsonlTrajectoryRecorder
from tests.conftest import DEFAULT_CRITERIA, fake_judge, make_document


def _context(cwd, *, settings: Settings | None = None) -> RunContext[Any]:
    return cast(
        RunContext[Any],
        SimpleNamespace(
            deps=AgentDeps(cwd=cwd, settings=settings or Settings())
        ),
    )


def _offline_settings() -> Settings:
    from intel_agent.config import (
        AcademicSearchConfig,
        ArchiveSearchConfig,
        GitHubSearchConfig,
        NewsSearchConfig,
        SearchConfig,
    )

    # Vertical capabilities disabled: unit tests must not hit real networks.
    return Settings(
        search=SearchConfig(
            searxng_url=None,
            github=GitHubSearchConfig(enabled=False),
            academic=AcademicSearchConfig(enabled=False),
            news=NewsSearchConfig(enabled=False),
            archive=ArchiveSearchConfig(enabled=False),
        )
    )


def _tool(agent, name: str):
    return agent._function_toolset.tools[name].function


def test_failure_includes_exception_type_when_message_is_empty():
    failure = agent_module._failure(RuntimeError())

    assert failure["error"] == {
        "code": "UNKNOWN",
        "message": "RuntimeError",
    }


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
            task = load_task(self.deps.cwd)
            save_task(self.deps.cwd, task.model_copy(update={"stage": "done"}))
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
async def test_runner_continues_an_incomplete_task(monkeypatch, cwd):
    calls: list[tuple[str, dict]] = []
    first = SimpleNamespace(
        output="接下来继续",
        all_messages=lambda: ["first-history"],
    )
    completed = SimpleNamespace(
        output="完成",
        all_messages=lambda: ["complete-history"],
    )

    class FakeEvents:
        def __init__(self, call_number):
            self.call_number = call_number
            self.result = first if call_number == 1 else completed

        async def __aenter__(self):
            if self.call_number == 1:
                create_task(
                    cwd,
                    "主题",
                    ["问题甲", "问题乙"],
                    DEFAULT_CRITERIA,
                )
            else:
                task = load_task(cwd)
                save_task(cwd, task.model_copy(update={"stage": "done"}))
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return FakeEvents(len(calls))

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _settings: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    result = await run_agent_task(
        cwd,
        Settings(),
        TaskRunSpec(
            topic="主题",
            questions=["问题甲", "问题乙"],
            criteria=DEFAULT_CRITERIA,
        ),
    )

    assert result is completed
    assert len(calls) == 2
    assert "任务尚未完成" in calls[1][0]
    assert calls[1][1]["message_history"] == ["first-history"]
    assert calls[1][1]["usage"] is calls[0][1]["usage"]


@pytest.mark.asyncio
async def test_web_search_executes_query_matrix_slots(monkeypatch, cwd):
    create_task(
        cwd,
        "测试主题",
        ["问题甲：测试主题的现状如何", "问题乙：测试主题的进展如何"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    calls: list[str] = []
    trace_path = cwd / "trace.jsonl"
    recorder = JsonlTrajectoryRecorder(trace_path)
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)

    async def fake_search(query, _max, *, client, searxng_url, opts):
        calls.append(query)
        return {
            "results": [
                {
                    "url": f"https://example.com/result-{len(calls)}",
                    "title": "测试主题 结果",
                }
            ],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)
    settings = Settings(budgets=BudgetConfig(search_attempts=40))

    await _tool(build_agent(settings), "web_search")(
        _context(cwd, settings=settings),
        "具体 查询",
        5,
        "general",
        "zh-CN",
        None,
    )
    recorder.close()

    # First call is the model's own query; the next two are deterministic
    # matrix slots executed in the same tool call (run 014).
    assert calls[0] == "具体 查询"
    assert len(calls) == 3
    state = json.loads(
        (cwd / "data/intel/search_matrix.json").read_text(encoding="utf-8")
    )
    assert len(state["executed"]) == 2
    assert len(state["trace"]) == 2
    record = state["trace"][0]
    assert {
        "query",
        "slot",
        "phase",
        "question_id",
        "engines",
        "results",
    } <= set(record)
    assert record["results"][0]["url"].startswith("https://example.com/")
    assert record["results"][0]["rank"] == 1
    assert record["results"][0]["new_domain"] is True
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    matrix_actions = [
        event
        for event in events
        if event["event_type"] == "action"
        and event["payload"].get("action_type") == "search_matrix_slot"
    ]
    matrix_observations = [
        event
        for event in events
        if event["event_type"] == "observation"
        and str(event["payload"].get("action_id", "")).startswith(
            "search_matrix:"
        )
    ]
    assert len(matrix_actions) == len(matrix_observations) == 2
    assert {event["payload"]["action_id"] for event in matrix_actions} == {
        event["payload"]["action_id"] for event in matrix_observations
    }
    assert all(event["question_id"] for event in matrix_actions)


@pytest.mark.asyncio
async def test_query_matrix_round_robins_questions_before_deepening(
    monkeypatch, cwd
):
    task = create_task(
        cwd,
        "测试主题",
        ["问题甲：测试主题的现状如何", "问题乙：测试主题的进展如何"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )

    async def fake_search(query, _max, *, client, searxng_url, opts):
        return {"results": [], "engineUsed": "fake"}

    monkeypatch.setattr(agent_module, "web_search", fake_search)
    settings = Settings(budgets=BudgetConfig(search_attempts=40))
    tool = _tool(build_agent(settings), "web_search")

    await tool(
        _context(cwd, settings=settings),
        "具体 查询",
        5,
        "general",
        "zh-CN",
        None,
    )

    state = json.loads(
        (cwd / "data/intel/search_matrix.json").read_text(encoding="utf-8")
    )
    assert [entry["question_id"] for entry in state["trace"]] == [
        task.questions[0].id,
        task.questions[1].id,
    ]
    assert all(entry["slot"] == "discovery" for entry in state["trace"])


@pytest.mark.asyncio
async def test_query_matrix_respects_phase_budgets(monkeypatch, cwd):
    create_task(
        cwd,
        "测试主题",
        ["问题甲：测试主题的现状如何", "问题乙：测试主题的进展如何"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )

    async def fake_search(query, _max, *, client, searxng_url, opts):
        return {
            "results": [
                {
                    "url": f"https://example.com/{hash(query) % 10000}",
                    "title": "测试主题 结果",
                }
            ],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)
    settings = Settings(budgets=BudgetConfig(search_attempts=40))
    tool = _tool(build_agent(settings), "web_search")
    context = _context(cwd, settings=settings)

    # 5 calls: 4 discovery slots (2 per question) fill first, then verify
    # slots run on their own budget (run 063 P1: model discovery searches
    # must not starve matrix verify).
    for query in (
        "具体 查询",
        "另一 查询",
        "第三 查询",
        "第四 查询",
        "第五 查询",
    ):
        await tool(context, query, 5, "general", "zh-CN", None)

    state = json.loads(
        (cwd / "data/intel/search_matrix.json").read_text(encoding="utf-8")
    )
    # Budget 40 → phase caps: discovery 16, verify 16, adversarial 8.
    assert state["phase_used"]["discovery"] <= 16
    assert state["phase_used"]["verify"] >= 1
    assert state["phase_used"]["adversarial"] <= 8


@pytest.mark.asyncio
async def test_web_search_news_empty_falls_back_to_general(monkeypatch, cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    seen: list[str] = []

    async def fake_search(query, _max, *, client, searxng_url, opts):
        seen.append(opts["category"])
        if opts["category"] == "news":
            return {"results": [], "engineUsed": "fake"}
        return {
            "results": [{"url": "https://example.com/a", "title": "主题 A"}],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)

    await _tool(build_agent(Settings()), "web_search")(
        _context(cwd), "具体 查询", 5, "news", "zh-CN", None
    )

    crawl = load_crawl(cwd, task.id)
    assert [entry.canonical_url for entry in crawl.entries] == [
        "https://example.com/a"
    ]
    # The tool's own calls come first (news, then the general fallback);
    # trailing calls belong to the deterministic query matrix (run 014).
    assert seen[:2] == ["news", "general"]


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
                {"url": "https://example.com/a", "title": "主题 A"},
                {"url": "https://example.com/b", "title": "主题 B"},
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
async def test_blocked_broad_search_does_not_spend_budget(cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)

    result = await _tool(build_agent(Settings()), "web_search")(
        _context(cwd), "低空经济", 5, "general", "zh-CN", None
    )

    assert result["engineUsed"] == "blocked"
    assert load_task(cwd, task.id).collection.search_attempts == 0


@pytest.mark.asyncio
async def test_web_search_uses_configured_search_budget(monkeypatch, cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)

    async def fake_search(*_args, **_kwargs):
        return {"results": [], "engineUsed": "fake"}

    settings = Settings(budgets=BudgetConfig(search_attempts=1))
    monkeypatch.setattr(agent_module, "web_search", fake_search)
    tool = _tool(build_agent(settings), "web_search")

    await tool(
        _context(cwd, settings=settings),
        "亿航智能 订单 270 2026",
        5,
        "general",
        "zh-CN",
        None,
    )
    exhausted = await tool(
        _context(cwd, settings=settings),
        "亿航智能 哈萨克斯坦 订单 2025",
        5,
        "general",
        "zh-CN",
        None,
    )

    assert exhausted["error"]["code"] == "SEARCH_BUDGET_EXHAUSTED"
    assert load_task(cwd, task.id).collection.search_attempts == 1


@pytest.mark.asyncio
async def test_web_search_does_not_seed_unfetchable_redirects(
    monkeypatch, cwd
):
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
                {
                    "url": "https://www.baidu.com/link?url=opaque",
                    "title": "主题 redirect",
                    "fetchable": False,
                },
                {
                    "url": "https://example.com/report.pdf?a=1&amp;b=2",
                    "title": "主题 report",
                    "fetchable": True,
                },
            ],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)
    await _tool(build_agent(Settings()), "web_search")(
        _context(cwd), "具体 企业 报告", 5, "general", "zh-CN", None
    )

    crawl = load_crawl(cwd, task.id)
    assert [entry.canonical_url for entry in crawl.entries] == [
        "https://example.com/report.pdf?a=1&b=2"
    ]


@pytest.mark.asyncio
async def test_crawl_collect_returns_compact_resource_index(monkeypatch, cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    snapshot = create_crawl(
        cwd,
        task.id,
        # Spread across domains: the per-domain cap (run 013) limits a
        # single non-first-party domain to a fraction of the frontier.
        [
            f"https://example{index % 16}.com/{index}.pdf"
            for index in range(80)
        ],
        CrawlConfig(max_urls=80),
    )
    for index, entry in enumerate(snapshot.entries):
        entry.status = "complete"
        entry.document_id = f"doc-{index}"
        entry.mime_type = "application/pdf"
        entry.size = 100
        entry.extraction.status = "complete"

    async def fake_collect(*_args, **_kwargs):
        return snapshot

    monkeypatch.setattr(agent_module, "run_crawl_collect", fake_collect)
    result = await _tool(build_agent(Settings()), "crawl_collect")(
        _context(cwd), task.id
    )

    assert "entries" not in result
    assert result["counts"]["complete"] == 80
    assert len(result["resources"]) == 50
    assert result["resources_truncated"] is True
    assert len(str(result)) < 16_000


@pytest.mark.asyncio
async def test_crawl_collect_wires_one_enabled_browser_renderer(
    monkeypatch, cwd
):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    snapshot = create_crawl(cwd, task.id, [], CrawlConfig())
    renderer_entered = False

    class FakeRenderer:
        def __init__(self, _config):
            pass

        async def __aenter__(self):
            nonlocal renderer_entered
            renderer_entered = True
            return self

        async def __aexit__(self, *_args):
            return None

        async def render(self, _url, _max_bytes):
            raise AssertionError("fake crawl owns rendering")

    async def fake_collect(*_args, renderer=None, **_kwargs):
        assert renderer is not None
        return snapshot

    monkeypatch.setattr(agent_module, "BrowserRenderer", FakeRenderer)
    monkeypatch.setattr(agent_module, "run_crawl_collect", fake_collect)
    settings = Settings.model_validate(
        {"fetch": {"enable_browser_fallback": True}}
    )

    await _tool(build_agent(settings), "crawl_collect")(
        _context(cwd, settings=settings), task.id
    )

    assert renderer_entered is True


@pytest.mark.asyncio
async def test_web_fetch_registers_collected_material(monkeypatch, cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    document = make_document(cwd, "主题材料", "https://example.com/source")

    async def fake_fetch(*_args, **_kwargs):
        return document, "主题材料", []

    monkeypatch.setattr(agent_module, "fetch_document", fake_fetch)

    result = await _tool(build_agent(Settings()), "web_fetch")(
        _context(cwd), document.canonical_url, 1024
    )

    assert result["document"]["id"] == document.id
    digest = load_material_digest(cwd, task.id)
    assert digest is not None
    assert digest.materials[0].document_id == document.id


@pytest.mark.asyncio
async def test_web_fetch_bounds_preview_and_outbound_links(monkeypatch, cwd):
    create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    document = make_document(cwd, "主题材料", "https://example.com/source")
    content = "界" * 10_000
    links = [f"https://example.org/{number}" for number in range(50)]

    async def fake_fetch(*_args, **_kwargs):
        return document, content, links

    settings = Settings(context=ContextConfig(context_window_tokens=32_768))
    monkeypatch.setattr(agent_module, "fetch_document", fake_fetch)

    result = await _tool(build_agent(settings), "web_fetch")(
        _context(cwd, settings=settings), document.canonical_url, 100_000
    )

    assert len(result["preview"].encode("utf-8")) <= 8_192
    assert result["preview"].endswith("[正文预览已截断]")
    assert len(result["outbound_links"]) == 20


@pytest.mark.asyncio
async def test_web_fetch_wires_enabled_browser_renderer(monkeypatch, cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    document = make_document(cwd, "动态主题材料", "https://example.com/app")
    document = document.model_copy(update={"collection_method": "browser"})
    renderer_entered = False

    class FakeRenderer:
        def __init__(self, _config):
            pass

        async def __aenter__(self):
            nonlocal renderer_entered
            renderer_entered = True
            return self

        async def __aexit__(self, *_args):
            return None

        async def render(self, _url, _max_bytes):
            raise AssertionError("fake fetch_document owns rendering")

    async def fake_fetch(*_args, renderer=None, **_kwargs):
        assert renderer is not None
        return document, "动态主题材料", []

    monkeypatch.setattr(agent_module, "BrowserRenderer", FakeRenderer)
    monkeypatch.setattr(agent_module, "fetch_document", fake_fetch)
    settings = Settings.model_validate(
        {"fetch": {"enable_browser_fallback": True}}
    )

    result = await _tool(build_agent(settings), "web_fetch")(
        _context(cwd, settings=settings), document.canonical_url, 1024
    )

    assert renderer_entered is True
    assert result["fetched_via"] == "browser"
    assert load_material_digest(cwd, task.id) is not None


@pytest.mark.asyncio
async def test_failed_web_fetch_registers_one_star_material(monkeypatch, cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)

    async def failed_fetch(*_args, **_kwargs):
        raise IntelError("NETWORK_ERROR", "连接失败")

    monkeypatch.setattr(agent_module, "fetch_document", failed_fetch)
    tool = _tool(build_agent(Settings()), "web_fetch")

    result = await tool(_context(cwd), "https://example.com/fail", 1024)

    assert result["error"]["code"] == "NETWORK_ERROR"
    digest = load_material_digest(cwd, task.id)
    assert digest is not None
    assert digest.materials[0].rating == 1
    assert "连接失败" in digest.materials[0].description


def test_material_digest_tool_returns_ranked_collection(cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    register_material(
        cwd, task.id, "https://example.com/fail", error="提取失败"
    )

    result = _tool(build_agent(Settings()), "material_digest")(
        _context(cwd), task.id
    )

    assert result["materials"][0]["rating"] == 1
    assert "提取失败" in result["materials"][0]["description"]


def test_document_search_finds_crawled_multimedia_text(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    relevant = make_document(
        cwd,
        "[00:00:01.000 --> 00:00:03.000] 公司确认新增订单 270 架",
        "https://media.example.com/interview.mp4",
    )
    unrelated = make_document(
        cwd, "其他内容", "https://media.example.com/photo.jpg"
    )
    crawl = create_crawl(
        cwd,
        task.id,
        [relevant.final_url, unrelated.final_url],
        CrawlConfig(),
    )
    for entry, document in zip(
        crawl.entries, [relevant, unrelated], strict=True
    ):
        entry.status = "complete"
        entry.document_id = document.id
        entry.extraction.status = "complete"
    from intel_agent.storage import save_crawl

    save_crawl(cwd, crawl)
    for document in (relevant, unrelated):
        register_material(
            cwd, task.id, document.final_url, document_id=document.id
        )
    agent = build_agent(Settings())

    assert "document_search" in agent._function_toolset.tools
    result = _tool(agent, "document_search")(
        _context(cwd), task.id, "订单 270", 5
    )

    assert [item["document_id"] for item in result["results"]] == [relevant.id]
    assert "270" in result["results"][0]["snippet"]


def test_document_search_ranks_novel_government_group_above_cited(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    cited_doc = make_document(
        cwd, "订单 270 相关报道", "https://news.cn/order-270"
    )
    novel_doc = make_document(
        cwd, "订单 270 政府文件", "https://www.gov.cn/order-270"
    )
    fact = save_fact(cwd, task.id, task.questions[0].id, "订单为 270")
    save_evidence(cwd, fact.id, cited_doc.id, "supports", "订单 270 相关报道")
    crawl = create_crawl(
        cwd,
        task.id,
        [cited_doc.final_url, novel_doc.final_url],
        CrawlConfig(),
    )
    for entry, document in zip(
        crawl.entries, [cited_doc, novel_doc], strict=True
    ):
        entry.status = "complete"
        entry.document_id = document.id
        entry.extraction.status = "complete"
    from intel_agent.storage import save_crawl

    save_crawl(cwd, crawl)
    for document in (cited_doc, novel_doc):
        register_material(
            cwd, task.id, document.final_url, document_id=document.id
        )
    agent = build_agent(Settings())

    result = _tool(agent, "document_search")(
        _context(cwd), task.id, "订单 270", 5
    )

    ids = [item["document_id"] for item in result["results"]]
    assert ids[0] == novel_doc.id
    assert result["results"][0]["novel_group"] is True


def test_document_search_works_without_deep_crawl(cwd):
    # Run 059 P0: non-deep tasks never create a crawl snapshot, so the old
    # crawl-entry corpus + deep_crawl gate made document_search fail 2/2.
    # The corpus is now every registered task document.
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=False,
    )
    relevant = make_document(
        cwd, "政策文件明确支持人形机器人产业发展", "https://www.gov.cn/policy"
    )
    unrelated = make_document(cwd, "天气晴朗", "https://news.cn/weather")
    for document in (relevant, unrelated):
        register_material(
            cwd, task.id, document.final_url, document_id=document.id
        )
    agent = build_agent(Settings())

    result = _tool(agent, "document_search")(
        _context(cwd), task.id, "人形机器人 政策", 5
    )

    assert [item["document_id"] for item in result["results"]] == [relevant.id]


def test_document_read_reports_total_lines_and_overlap(cwd):
    # Run 059: reads re-covered 44% of the same lines because the tool
    # neither reported the document length nor flagged repeated ranges.
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    document = make_document(
        cwd, "\n".join(f"第 {number} 行内容" for number in range(1, 51))
    )
    register_material(
        cwd, task.id, document.final_url, document_id=document.id
    )
    agent = build_agent(Settings())
    tool = _tool(agent, "document_read")
    context = _context(cwd)

    first = tool(context, document.id, 1, 20)
    assert first["total_lines"] == 50
    assert first["end_line"] == 20

    second = tool(context, document.id, 1, 30)
    assert "already_read" in second
    assert "1-20" in second["already_read"]


def test_evidence_save_rejects_metadata_and_duplicates(cwd):
    # Run 059: 发文字号/成文日期 metadata rows were saved as evidence and
    # drove 16/21 partial verdicts; identical quotes were re-submitted.
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    question = task.questions[0]
    fact = save_fact(cwd, task.id, question.id, "政策事实")
    document = make_document(
        cwd,
        "发文字号： 工信部联科〔2025〕279号\n正文内容明确支持相关产业",
        "https://www.gov.cn/policy",
    )
    register_material(
        cwd, task.id, document.final_url, document_id=document.id
    )
    agent = build_agent(Settings())
    tool = _tool(agent, "evidence_save")
    context = _context(cwd)

    metadata = tool(
        context,
        fact.id,
        document.id,
        "supports",
        "发文字号： 工信部联科〔2025〕279号",
    )
    assert metadata["ok"] is False
    assert metadata["error"]["code"] == "INVALID_INPUT"

    ok = tool(
        context, fact.id, document.id, "supports", "正文内容明确支持相关产业"
    )
    assert "quote" in ok

    duplicate = tool(
        context, fact.id, document.id, "supports", "正文内容明确支持相关产业"
    )
    assert duplicate["ok"] is False
    assert duplicate["error"]["code"] == "BLOCKED_REPETITION"


def test_gap_query_extracts_keywords_not_full_statement():
    # Run 059: 40-80 char fact statements were passed verbatim to
    # academic/software/news providers and returned nothing.
    from intel_agent.agent import _gap_query

    snapshot = SimpleNamespace(
        per_question=[
            SimpleNamespace(
                status="partial",
                question="2026年全球人形机器人头部企业进展",
                facts=[
                    SimpleNamespace(
                        gap_score=2,
                        statement=(
                            "据机构SAG数据,2026年上半年全球人形机器人出货量"
                            "约为1.91万台,同比增长272%,其中中国厂商占全球"
                            "超97%的出货量"
                        ),
                    )
                ],
            )
        ]
    )
    query = _gap_query(snapshot)
    assert query is not None
    assert len(query) < 60
    assert "人形机器人" in query
    assert "1.91万" in query or "272%" in query
    assert "据机构SAG数据" not in query


def test_fact_save_gate_injects_local_hits(cwd):
    # Run 063: the model never called document_search itself, so the gate
    # runs the cheap local lookup and hands back concrete candidates.
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    agent = build_agent(Settings())
    fact_tool = _tool(agent, "fact_save")

    first = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 A")
    first_doc = make_document(cwd, "事实 A 报道", "https://news.cn/a")
    save_evidence(cwd, first["id"], first_doc.id, "supports", "事实 A 报道")

    second_doc = make_document(
        cwd, "独立媒体对事实 A 的详细报道", "https://caixin.com/a2"
    )
    register_material(
        cwd, task.id, second_doc.final_url, document_id=second_doc.id
    )

    blocked = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 B")
    assert blocked["error"]["code"] == "CROSS_VERIFY_BACKLOG"
    assert second_doc.id in blocked["error"]["message"]

    empty_task = create_task(
        cwd, "空主题", ["问题丙", "问题丁"], DEFAULT_CRITERIA
    )
    empty = fact_tool(
        _context(cwd), empty_task.id, empty_task.questions[0].id, "事实 C"
    )
    empty_doc = make_document(cwd, "事实 C 报道", "https://news.cn/c")
    save_evidence(cwd, empty["id"], empty_doc.id, "supports", "事实 C 报道")
    blocked2 = fact_tool(
        _context(cwd), empty_task.id, empty_task.questions[0].id, "事实 D"
    )
    assert blocked2["error"]["code"] == "CROSS_VERIFY_BACKLOG"
    assert "无命中" in blocked2["error"]["message"]


def test_fact_save_gated_while_single_source_backlog_exists(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    agent = build_agent(Settings())
    fact_tool = _tool(agent, "fact_save")

    first = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 A")
    assert "id" in first
    first_doc = make_document(cwd, "事实 A 报道", "https://news.cn/a")
    save_evidence(cwd, first["id"], first_doc.id, "supports", "事实 A 报道")

    blocked = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 B")
    assert blocked["error"]["code"] == "CROSS_VERIFY_BACKLOG"
    assert "事实 A" in blocked["error"]["message"]

    second_doc = make_document(cwd, "事实 A 独立报道", "https://caixin.com/a")
    save_evidence(
        cwd, first["id"], second_doc.id, "supports", "事实 A 独立报道"
    )

    reopened = fact_tool(
        _context(cwd), task.id, task.questions[0].id, "事实 B"
    )
    assert "id" in reopened


def test_fact_save_gate_opens_after_search_budget_exhausted(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    agent = build_agent(Settings())
    fact_tool = _tool(agent, "fact_save")

    first = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 A")
    first_doc = make_document(cwd, "事实 A 报道", "https://news.cn/a")
    save_evidence(cwd, first["id"], first_doc.id, "supports", "事实 A 报道")

    blocked = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 B")
    assert blocked["error"]["code"] == "CROSS_VERIFY_BACKLOG"

    # Mark the search budget exhausted: the honest escape hatch opens.
    loaded = load_task(cwd, task.id)
    loaded.collection.search_stop_reason = "search_budget_exhausted"
    from intel_agent.task import save_task

    save_task(cwd, loaded)

    allowed = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 B")
    assert "id" in allowed


def test_fact_save_gate_opens_after_coverage_no_progress(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    agent = build_agent(Settings())
    fact_tool = _tool(agent, "fact_save")

    first = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 A")
    first_doc = make_document(cwd, "事实 A 报道", "https://news.cn/a")
    save_evidence(cwd, first["id"], first_doc.id, "supports", "事实 A 报道")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    for _ in range(6):
        eval_coverage(cwd, task.id)

    allowed = fact_tool(_context(cwd), task.id, task.questions[0].id, "事实 B")
    assert "id" in allowed


def test_fact_save_gate_exempts_official_backed_primary_claim(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    agent = build_agent(Settings())
    fact_tool = _tool(agent, "fact_save")

    primary = fact_tool(
        _context(cwd),
        task.id,
        task.questions[0].id,
        "政府发布测试主题政策",
        "primary",
    )
    gov_doc = make_document(
        cwd, "政府发布测试主题政策", "https://www.gov.cn/policy"
    )
    save_evidence(
        cwd, primary["id"], gov_doc.id, "supports", "政府发布测试主题政策"
    )

    allowed = fact_tool(
        _context(cwd), task.id, task.questions[0].id, "后续事实"
    )
    assert "id" in allowed


def test_generate_research_report_blocks_repeated_drafts(monkeypatch, cwd):
    from intel_agent.models import (
        FactConclusion,
        ResearchReportInput,
        ResearchReportSection,
    )

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)

    def fake_report(_cwd, _task_id, _draft):
        return {"ok": True, "path": "output/report.md"}

    monkeypatch.setattr(agent_module, "generate_research_report", fake_report)
    tool = _tool(build_agent(Settings()), "generate_research_report")
    draft = ResearchReportInput(
        sections=[
            ResearchReportSection(
                question_id=task.questions[0].id,
                conclusions=[FactConclusion(fact_id="fact-x")],
            )
        ],
        overall_conclusions=[],
    )

    context = _context(cwd)
    for _ in range(3):
        result = tool(context, task.id, draft.model_dump_json())
        assert result["ok"] is True
    blocked = tool(context, task.id, draft.model_dump_json())

    assert blocked["ok"] is False
    assert blocked["errors"][0]["code"] == "REPEATED"
    assert "intel_status" in blocked["next_action"]


def test_generate_research_report_rejects_markdown_draft(cwd):
    # Run 062: the model passed Markdown report text as the draft and the
    # silent verified-draft fallback let it loop 56 failed calls. Markdown
    # drafts must fail loudly with format guidance.
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    tool = _tool(build_agent(Settings()), "generate_research_report")

    result = tool(
        _context(cwd),
        task.id,
        "# 人形机器人产业发展现状 — 调研报告\n- 任务 ID：task-x\n- 主要缺口：…",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"
    assert "JSON" in result["error"]["message"]


def test_generate_research_report_accepts_json_encoded_draft(monkeypatch, cwd):
    from intel_agent.models import ResearchReportInput, ResearchReportSection

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    draft = ResearchReportInput(
        sections=[ResearchReportSection(question_id=task.questions[0].id)],
        overall_conclusions=[],
    )
    captured = []

    def fake_report(_cwd, _task_id, parsed_draft):
        captured.append(parsed_draft)
        return {"ok": True, "path": "output/report.md"}

    monkeypatch.setattr(agent_module, "generate_research_report", fake_report)
    tool = _tool(build_agent(Settings()), "generate_research_report")

    result = tool(_context(cwd), task.id, draft.model_dump_json())

    assert result["ok"] is True
    assert captured == [draft]


def test_generate_research_report_strips_trailing_xml_noise(monkeypatch, cwd):
    from intel_agent.models import ResearchReportInput, ResearchReportSection

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    draft = ResearchReportInput(
        sections=[ResearchReportSection(question_id=task.questions[0].id)],
        overall_conclusions=[],
    )
    captured = []

    def fake_report(_cwd, _task_id, parsed_draft):
        captured.append(parsed_draft)
        return {"ok": True, "path": "output/report.md"}

    monkeypatch.setattr(agent_module, "generate_research_report", fake_report)
    tool = _tool(build_agent(Settings()), "generate_research_report")
    noisy = draft.model_dump_json() + "</draft>\n</invoke>\n"

    result = tool(_context(cwd), task.id, noisy)

    assert result["ok"] is True
    assert captured == [draft]


def test_generate_research_report_garbage_draft_uses_verified_facts(cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    for _ in range(3):
        eval_coverage(cwd, task.id)

    result = _tool(build_agent(Settings()), "generate_research_report")(
        _context(cwd), task.id, '{"sections": [{"question_id": 未闭合的垃圾'
    )

    assert result["ok"] is True
    assert result["path"].endswith("主题-research-report.md")


def test_generate_research_report_falls_back_to_verified_facts(cwd):
    from intel_agent.models import ResearchReportInput

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    for _ in range(3):
        eval_coverage(cwd, task.id)

    result = _tool(build_agent(Settings()), "generate_research_report")(
        _context(cwd), task.id, ResearchReportInput().model_dump_json()
    )

    assert result["ok"] is True
    assert result["path"].endswith("主题-research-report.md")


def test_intel_plan_seeds_configured_sources_into_crawl(cwd):
    settings = Settings(
        sources=SourcesConfig(
            policy=["https://www.gov.cn/policy.pdf"],
            ir_company=["https://ir.example.com/video.mp4"],
        )
    )
    agent = build_agent(settings)
    deps = AgentDeps(cwd=cwd, settings=settings, deep_crawl=True)

    result = _tool(agent, "intel_plan")(
        cast(
            RunContext[Any],
            SimpleNamespace(deps=deps),
        ),
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        True,
    )

    task_id = result["task"]["id"]
    crawl = load_crawl(cwd, task_id)
    assert {entry.canonical_url for entry in crawl.entries} == {
        "https://www.gov.cn/policy.pdf",
        "https://ir.example.com/video.mp4",
    }
    assert all(entry.depth == 0 for entry in crawl.entries)


def test_intel_plan_reuses_an_active_task(cwd):
    agent = build_agent(Settings())
    context = _context(cwd)
    plan = _tool(agent, "intel_plan")

    first = plan(
        context,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        False,
    )
    second = plan(
        context,
        "另一个主题",
        ["另一个问题甲", "另一个问题乙"],
        DEFAULT_CRITERIA,
        False,
    )

    assert second["task"]["id"] == first["task"]["id"]
    assert second["reused_existing_task"] is True
    assert load_task(cwd).topic == "主题"


def test_intel_plan_accepts_json_encoded_criteria(cwd):
    plan = _tool(build_agent(Settings()), "intel_plan")

    result = plan(
        _context(cwd),
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA.model_dump_json(),
        False,
    )

    assert result["task"]["criteria"] == DEFAULT_CRITERIA.model_dump()


def test_coverage_eval_returns_cross_verification_backlog(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )
    document = make_document(
        cwd, "关于测试主题现状的报道", "https://news.cn/story"
    )
    fact = save_fact(cwd, task.id, task.questions[0].id, "测试主题现状为 A")
    save_evidence(
        cwd, fact.id, document.id, "supports", "关于测试主题现状的报道"
    )
    crawl = create_crawl(cwd, task.id, [document.final_url], CrawlConfig())
    for entry in crawl.entries:
        entry.status = "complete"
        entry.document_id = document.id
        entry.extraction.status = "complete"
    from intel_agent.storage import save_crawl

    save_crawl(cwd, crawl)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    agent = build_agent(Settings())

    result = asyncio.run(
        _tool(agent, "coverage_eval")(
            _context(cwd, settings=_offline_settings()), task.id
        )
    )

    assert result["pending_cross_verification"]
    pending = result["pending_cross_verification"][0]
    assert pending["fact_id"] == fact.id
    assert pending["independent_sources"] == 1
    assert "document_search" in result["verification_workflow"]


def test_coverage_eval_assess_no_progress_generates_terminal_report(cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    for _ in range(6):
        eval_coverage(cwd, task.id)
    set_task_stage(cwd, task.id, "assess")

    result = asyncio.run(
        _tool(build_agent(Settings()), "coverage_eval")(
            _context(cwd, settings=_offline_settings()), task.id
        )
    )

    assert result["terminal_report"]
    assert result["pending_cross_verification"] == []
    assert load_task(cwd, task.id).outputs.report is not None


def test_coverage_eval_collect_no_progress_advances_to_assess_and_report(cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    for _ in range(6):
        eval_coverage(cwd, task.id)
    assert load_task(cwd, task.id).stage == "collect"

    result = asyncio.run(
        _tool(build_agent(Settings()), "coverage_eval")(
            _context(cwd, settings=_offline_settings()), task.id
        )
    )

    assert result["terminal_report"]
    task = load_task(cwd, task.id)
    assert task.stage == "assess"
    assert task.outputs.report is not None


@pytest.mark.asyncio
async def test_evidence_audit_tool_refreshes_coverage(cwd):
    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    deps = AgentDeps(
        cwd=cwd,
        settings=_offline_settings(),
        judge=fake_judge,
        judge_provider="test",
        judge_model="fake",
    )
    context = cast(RunContext[Any], SimpleNamespace(deps=deps))
    tool = _tool(build_agent(Settings()), "evidence_audit")

    result = await tool(context, task.id)

    assert result["reviewed"] == 1
    assert "coverage" in result
    assert "stop_reason" in result["coverage"]


@pytest.mark.asyncio
async def test_evidence_audit_skips_after_consecutive_failures(cwd):
    # Run 059 P0: a broken judge used to feed the model the same failure to
    # retry forever. After two consecutive all-failed rounds the tool must
    # return a success-shaped skip inside the cooldown window, and a later
    # successful audit resets the streak.
    async def broken_judge(fact, evidence):
        raise RuntimeError("judge 服务不可用")

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    deps = AgentDeps(
        cwd=cwd,
        settings=_offline_settings(),
        judge=broken_judge,
        judge_provider="test",
        judge_model="fake",
    )
    context = cast(RunContext[Any], SimpleNamespace(deps=deps))
    tool = _tool(build_agent(Settings()), "evidence_audit")

    assert (await tool(context, task.id))["ok"] is False
    assert (await tool(context, task.id))["ok"] is False

    third = await tool(context, task.id)
    assert third["ok"] is True
    assert third["skipped"] is True
    assert third["reviewed"] == 0

    agent_module._AUDIT_FAILURE_COOLDOWN_SECONDS = 0.05
    await asyncio.sleep(0.1)
    deps.judge = fake_judge
    recovered = await tool(context, task.id)
    assert "reviewed" in recovered
    assert recovered["reviewed"] == 1
    assert recovered.get("skipped") is None
    assert deps.audit_failure_streak == 0


def test_coverage_eval_assess_no_verified_facts_still_terminates(cwd):
    async def partial_judge(fact, evidence):
        return [
            {
                "evidence_id": item.id,
                "verdict": "partial",
                "reason": "引文部分支持",
                "unsupported_parts": ["未覆盖部分"],
            }
            for item in evidence
        ]

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, partial_judge, "t", "f"))
    for _ in range(6):
        eval_coverage(cwd, task.id)
    set_task_stage(cwd, task.id, "assess")

    result = asyncio.run(
        _tool(build_agent(Settings()), "coverage_eval")(
            _context(cwd, settings=_offline_settings()), task.id
        )
    )

    assert result["terminal_report"]
    binding = load_task(cwd, task.id).outputs.report
    assert binding is not None
    content = (cwd / binding.path).read_text(encoding="utf-8")
    assert "未形成可验证结论" in content
    assert "## 局限" in content


@pytest.mark.asyncio
async def test_web_search_seed_relevance_ignores_engine_score_and_drops_junk(
    monkeypatch, cwd
):
    task = create_task(
        cwd,
        "测试主题",
        ["测试主题现状", "测试主题进展"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )

    async def fake_search(*_args, **_kwargs):
        return {
            "results": [
                {
                    "url": "https://example.com/junk",
                    "title": "unrelated",
                    "score": 1.0,
                },
                {
                    "url": "https://example.com/high",
                    "title": "测试主题进展",
                    "score": 0.1,
                },
            ],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)

    await _tool(build_agent(Settings()), "web_search")(
        _context(cwd), "具体 查询", 5, "general", "zh-CN", None
    )

    crawl = load_crawl(cwd, task.id)
    entries = {entry.canonical_url: entry for entry in crawl.entries}
    assert set(entries) == {"https://example.com/high"}
    assert entries["https://example.com/high"].relevance >= 1


@pytest.mark.asyncio
async def test_vertical_search_does_not_emit_unlinked_observation(
    monkeypatch, cwd
):
    create_task(
        cwd,
        "测试主题",
        ["测试主题现状", "测试主题进展"],
        DEFAULT_CRITERIA,
    )

    async def fake_news_search(*_args, **_kwargs):
        return {
            "results": [],
            "provider_calls": 1,
            "engines_used": ["fake-news"],
            "degraded": [],
        }

    emitted = []
    monkeypatch.setattr(agent_module, "news_search", fake_news_search)
    monkeypatch.setattr(
        agent_module,
        "emit",
        lambda event: emitted.append(event) or "event-id",
    )
    context = _context(cwd)
    try:
        result = await _tool(build_agent(Settings()), "news_search")(
            context, "具体 新闻 查询", 5, None
        )
    finally:
        await context.deps.http.aclose()

    assert result["provider_calls"] == 1
    assert all(event.event_type != "observation" for event in emitted)


@pytest.mark.asyncio
async def test_web_search_seed_relevance_ignores_year_only_url_match(
    monkeypatch, cwd
):
    task = create_task(
        cwd,
        "测试主题",
        ["2026年测试主题进展", "2026年测试主题现状"],
        DEFAULT_CRITERIA,
        deep_crawl=True,
    )

    async def fake_search(*_args, **_kwargs):
        return {
            "results": [
                {
                    "url": "https://example.com/2026/08/video.html",
                    "title": "some unrelated page",
                },
            ],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)

    await _tool(build_agent(Settings()), "web_search")(
        _context(cwd), "具体 查询", 5, "general", "zh-CN", None
    )

    with pytest.raises(IntelError) as error:
        load_crawl(cwd, task.id)
    assert error.value.code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_web_search_does_not_seed_disabled_active_task(monkeypatch, cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
        deep_crawl=False,
    )

    async def fake_search(*_args, **_kwargs):
        return {
            "results": [{"url": "https://example.com/a", "title": "A"}],
            "engineUsed": "fake",
        }

    monkeypatch.setattr(agent_module, "web_search", fake_search)

    await _tool(build_agent(Settings()), "web_search")(
        _context(cwd), "具体 查询", 5, "general", "zh-CN", None
    )

    with pytest.raises(IntelError) as error:
        load_crawl(cwd, task.id)
    assert error.value.code == "NOT_FOUND"


def test_search_seeding_is_a_noop_without_an_active_task(cwd):
    agent_module._seed_active_crawl(
        cwd,
        Settings(),
        {"results": [{"url": "https://example.com/a"}]},
    )

    assert list((cwd / "data/intel/crawls").glob("*.json")) == []


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
        "total_lines": 3,
        "has_more": False,
        "next_start_line": None,
        "content": (
            "<untrusted_web_content>\n"
            "2: second\n3: third\n"
            "</untrusted_web_content>"
        ),
        "injection_warnings": ["网页包含疑似提示注入文本"],
        "next_action": (
            "从本次 content 选择一个逐字引文，立即调用 fact_save，"
            "再调用 evidence_save；不要重复读取相同行号。"
        ),
    }

    invalid = tool(_context(cwd), document.id, 0, 2)
    assert invalid["error"]["code"] == "INVALID_INPUT"
    past_end = tool(_context(cwd), document.id, 2, 4)
    assert past_end["error"]["code"] == "INVALID_INPUT"

    (cwd / document.text_path).write_text("tampered", encoding="utf-8")
    tampered = tool(_context(cwd), document.id, 1, 1)
    assert tampered["error"]["code"] == "DOCUMENT_TAMPERED"


def test_document_read_caps_each_call_at_200_lines(cwd):
    document = make_document(
        cwd, "\n".join(f"line {number}" for number in range(1, 251))
    )

    result = _tool(build_agent(Settings()), "document_read")(
        _context(cwd), document.id, 1, 250
    )

    assert result["start_line"] == 1
    assert result["end_line"] == 200
    assert result["has_more"] is True
    assert result["next_start_line"] == 201
    assert "200: line 200" in result["content"]
    assert "201: line 201" not in result["content"]


def test_document_read_caps_each_call_at_16_kib_of_utf8(cwd):
    document = make_document(cwd, "\n".join(["界" * 100] * 100))

    result = _tool(build_agent(Settings()), "document_read")(
        _context(cwd), document.id, 1, 100
    )

    assert len(result["content"].encode("utf-8")) <= 16_384
    assert result["end_line"] < 100
    assert result["has_more"] is True
    assert result["next_start_line"] == result["end_line"] + 1


def test_document_read_uses_context_window_payload_limit(cwd):
    document = make_document(cwd, "\n".join(["界" * 100] * 100))
    settings = Settings(context=ContextConfig(context_window_tokens=32_768))
    context = _context(cwd, settings=settings)

    result = _tool(build_agent(settings), "document_read")(
        context, document.id, 1, 100
    )

    assert len(result["content"].encode("utf-8")) <= 8_192
    assert result["has_more"] is True
    assert document.id in context.deps.read_document_ids
    assert "fact_save" in result["next_action"]


@pytest.mark.asyncio
async def test_search_requires_fetch_after_repeated_candidate_batches(
    monkeypatch, cwd
):
    create_task(cwd, "主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    document = make_document(cwd, "主题材料", "https://example.com/source")

    async def fake_search(query, *_args, **_kwargs):
        return {
            "results": [
                {
                    "url": f"https://example.org/{query}",
                    "title": f"主题 {query}",
                }
            ],
            "engineUsed": "fake",
        }

    async def fake_fetch(*_args, **_kwargs):
        return document, "主题材料", []

    settings = Settings(
        budgets=BudgetConfig(search_attempts=40),
        context=ContextConfig(max_search_calls_before_fetch=3),
    )
    context = _context(cwd, settings=settings)
    agent = build_agent(settings)
    search = _tool(agent, "web_search")
    monkeypatch.setattr(agent_module, "web_search", fake_search)
    monkeypatch.setattr(agent_module, "fetch_document", fake_fetch)

    for number in range(3):
        result = await search(
            context,
            f"具体 查询 {number}",
            5,
            "general",
            "zh-CN",
            None,
        )
        assert result["fresh_count"] > 0

    blocked = await search(context, "具体 查询 4", 5, "general", "zh-CN", None)
    assert blocked["error"]["code"] == "FETCH_REQUIRED"
    candidate_urls = {item["url"] for item in blocked["candidates"]}
    assert "https://example.org/具体 查询 0" in candidate_urls
    assert "https://example.org/具体 查询 1" in candidate_urls
    assert len(blocked["candidates"]) <= 10

    await _tool(agent, "web_fetch")(context, document.canonical_url, 1_024)
    resumed = await search(context, "具体 查询 5", 5, "general", "zh-CN", None)
    assert resumed["fresh_count"] > 0


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
