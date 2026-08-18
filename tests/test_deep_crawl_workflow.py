"""Deep-crawl integration across tasks, agent tools, and workflow gates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic_ai import RunContext

import intel_agent.agent as agent_module
from intel_agent.agent import AgentDeps, build_agent
from intel_agent.config import BudgetConfig, CrawlConfig, Settings
from intel_agent.coverage import eval_coverage
from intel_agent.crawl import create_crawl
from intel_agent.fetch import FetchedResponse
from intel_agent.main import _build_parser
from intel_agent.materials import load_material_digest, register_material
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
    assert seen == ["news", "general"]


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
        [f"https://example.com/{index}.pdf" for index in range(80)],
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
    agent = build_agent(Settings())

    assert "document_search" in agent._function_toolset.tools
    result = _tool(agent, "document_search")(
        _context(cwd), task.id, "订单 270", 5
    )

    assert [item["document_id"] for item in result["results"]] == [relevant.id]
    assert "270" in result["results"][0]["snippet"]


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
        "has_more": False,
        "next_start_line": None,
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
