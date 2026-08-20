"""Shared CLI/Web agent runner tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from intel_agent.config import BudgetConfig, Settings
from intel_agent.models import ResearchScope, SufficiencyCriteria
from intel_agent.runner import TaskRunSpec, build_task_prompt, run_agent_task
from intel_agent.task import create_task, load_task, parse_time_range


def make_spec() -> TaskRunSpec:
    return TaskRunSpec(
        topic="低空经济",
        questions=["投资进展如何？", "商业化进展如何？"],
        criteria=SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
    )


def test_parse_time_range_recognizes_single_year_and_ranges():
    assert parse_time_range("2026年低空经济投资与融资趋势") == "2026"
    assert parse_time_range("低空经济 2024-2026 发展情况") == "2024-2026"
    assert parse_time_range("低空经济 2024年至2026年 发展情况") == "2024-2026"
    assert parse_time_range("低空经济投资与融资趋势") == ""
    assert parse_time_range("") == ""


def test_create_task_copies_explicit_scope_time_range_to_every_question(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["2026年测试主题的现状如何", "测试主题的进展如何"],
        SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
        scope=ResearchScope(time_range="2024-2026"),
    )

    assert [q.time_range for q in task.questions] == [
        "2024-2026",
        "2024-2026",
    ]


def test_create_task_parses_year_per_question_without_scope(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["2026年测试主题的现状如何", "测试主题的进展如何"],
        SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
    )

    assert [q.time_range for q in task.questions] == ["2026", ""]
    persisted = load_task(cwd, task.id)
    assert [q.time_range for q in persisted.questions] == ["2026", ""]


def test_task_run_spec_validates_run_limits():
    spec = make_spec().model_copy(
        update={"max_requests": 40, "max_tool_calls": 12}
    )

    assert TaskRunSpec.model_validate(spec.model_dump()).max_requests == 40
    assert TaskRunSpec.model_validate(spec.model_dump()).max_tool_calls == 12

    with pytest.raises(ValidationError):
        TaskRunSpec.model_validate(
            {**make_spec().model_dump(), "max_requests": 0}
        )


def test_task_run_spec_normalizes_and_validates_questions():
    spec = TaskRunSpec(
        topic="  测试主题  ",
        questions=[" 问题甲 ", "问题甲", " 问题乙 "],
        criteria=SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
    )

    assert spec.topic == "测试主题"
    assert spec.questions == ["问题甲", "问题乙"]

    one_question = TaskRunSpec(
        topic="测试",
        questions=["只有一个问题"],
        criteria=spec.criteria,
    )
    assert one_question.questions == ["只有一个问题"]


def test_task_run_spec_accepts_topic_without_questions():
    spec = TaskRunSpec(topic=" 低空经济 ")

    assert spec.topic == "低空经济"
    assert spec.questions == []
    assert spec.objective == ""
    assert spec.scope.model_dump() == {
        "time_range": "",
        "geography": [],
        "languages": [],
    }
    assert spec.report_depth == "standard"


def test_topic_only_prompt_asks_agent_to_generate_questions():
    prompt = build_task_prompt(TaskRunSpec(topic="低空经济"))

    assert "生成 3–6 个" in prompt
    assert "低空经济" in prompt


def test_prompt_preserves_optional_research_brief():
    spec = TaskRunSpec.model_validate(
        {
            "topic": "低空经济",
            "objective": "了解产业现状",
            "questions": ["政策如何变化？"],
            "scope": {
                "time_range": "2024-2026",
                "geography": ["中国"],
                "languages": ["zh-CN", "en"],
            },
            "report_depth": "deep",
        }
    )

    prompt = build_task_prompt(spec)
    assert "了解产业现状" in prompt
    assert "政策如何变化？" in prompt
    assert "补充" in prompt
    assert "2024-2026" in prompt
    assert "中国" in prompt
    assert "zh-CN、en" in prompt


def test_build_task_prompt_preserves_user_input_and_criteria():
    prompt = build_task_prompt(make_spec())

    assert "低空经济" in prompt
    assert "投资进展如何？；商业化进展如何？" in prompt
    assert "min_independent_sources=2" in prompt
    assert "require_recency=false" in prompt


def test_prompt_is_generic_and_report_first():
    prompt = build_task_prompt(TaskRunSpec(topic="量子计算"))

    assert "material_digest" in prompt
    assert "generate_research_report" in prompt
    assert "亿航" not in prompt
    assert "caixin.com" not in prompt


def test_deep_crawl_defaults_off():
    assert Settings().crawl.enabled_by_default is False


@pytest.mark.asyncio
async def test_run_agent_task_streams_events(monkeypatch, cwd):
    received: list[object] = []
    result = SimpleNamespace(output="完成")
    deps = SimpleNamespace(crawl_event_callback=None)

    class FakeEvents:
        def __init__(self):
            self.result = result
            self._events = iter(["tool-started", "tool-completed"])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration as error:
                raise StopAsyncIteration from error

    class FakeContext:
        async def __aenter__(self):
            return FakeEvents()

        async def __aexit__(self, *_args):
            return False

    class FakeAgent:
        def run_stream_events(self, prompt, **kwargs):
            assert "低空经济" in prompt
            assert kwargs["deps"] is deps
            assert deps.crawl_event_callback is on_event
            assert kwargs["usage_limits"].request_limit == 200
            return FakeContext()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: deps,
    )

    async def on_event(event: object) -> None:
        received.append(event)

    actual = await run_agent_task(
        cwd, Settings(), make_spec(), on_event=on_event
    )

    assert actual is result
    assert received == ["tool-started", "tool-completed"]


@pytest.mark.asyncio
async def test_run_agent_task_applies_tighter_task_limits(monkeypatch, cwd):
    result = SimpleNamespace(output="完成")
    captured = None

    class FakeEvents:
        def __init__(self):
            self.result = result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, _prompt, **kwargs):
            nonlocal captured
            captured = kwargs["usage_limits"]
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: SimpleNamespace(
            crawl_event_callback=None
        ),
    )
    settings = Settings(budgets=BudgetConfig(request_limit=200))

    await run_agent_task(
        cwd,
        settings,
        make_spec().model_copy(
            update={"max_requests": 40, "max_tool_calls": 12}
        ),
    )

    assert captured is not None
    assert captured.request_limit == 40
    assert captured.tool_calls_limit == 12


@pytest.mark.asyncio
async def test_deep_report_enables_recursive_collection(monkeypatch, cwd):
    result = SimpleNamespace(output="完成")
    captured: dict[str, object] = {}

    class FakeEvents:
        def __init__(self):
            self.result = result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, prompt, **_kwargs):
            captured["prompt"] = prompt
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: (
            captured.update({"deep_crawl": deep_crawl})
            or SimpleNamespace(crawl_event_callback=None)
        ),
    )

    await run_agent_task(
        cwd,
        Settings(),
        TaskRunSpec(topic="量子计算", report_depth="deep", deep_crawl=False),
    )

    assert captured["deep_crawl"] is True
    assert "deep_crawl=true" in str(captured["prompt"])
