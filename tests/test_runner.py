"""Shared CLI/Web agent runner tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from intel_agent.config import Settings
from intel_agent.models import SufficiencyCriteria
from intel_agent.runner import TaskRunSpec, build_task_prompt, run_agent_task


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

    with pytest.raises(ValidationError):
        TaskRunSpec(
            topic="测试",
            questions=["只有一个问题"],
            criteria=spec.criteria,
        )


def test_build_task_prompt_preserves_user_input_and_criteria():
    prompt = build_task_prompt(make_spec())

    assert "低空经济" in prompt
    assert "投资进展如何？；商业化进展如何？" in prompt
    assert "min_independent_sources=2" in prompt
    assert "require_recency=false" in prompt


@pytest.mark.asyncio
async def test_run_agent_task_streams_events(monkeypatch, cwd):
    received: list[object] = []
    result = SimpleNamespace(output="完成")

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
            assert kwargs["deps"] == "deps"
            assert kwargs["usage_limits"].request_limit == 200
            return FakeContext()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps", lambda _cwd, _settings: "deps"
    )

    async def on_event(event: object) -> None:
        received.append(event)

    actual = await run_agent_task(
        cwd, Settings(), make_spec(), on_event=on_event
    )

    assert actual is result
    assert received == ["tool-started", "tool-completed"]
