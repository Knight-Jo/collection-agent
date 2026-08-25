from __future__ import annotations

from dataclasses import dataclass

import pytest

from intel_agent.intake import IntakeEngine
from intel_agent.models import IntelError


@dataclass
class _Result:
    output: str


class _FakeAgent:
    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def run(self, prompt: str):
        self.prompts.append(prompt)
        return _Result(self.outputs.pop(0))


async def test_intake_parses_capability_without_research_brief():
    engine = IntakeEngine(
        agent=_FakeAgent(
            '{"intent":"capability_query","reply":"我可以开展公开信息调研。",'
            '"research_brief":null,"missing_fields":[]}'
        )
    )

    decision = await engine.decide("你能做什么？", [])

    assert decision.intent == "capability_query"
    assert decision.research_brief is None


async def test_intake_repairs_malformed_json_once():
    engine = IntakeEngine(
        agent=_FakeAgent(
            "not-json",
            '{"intent":"clarify_research","reply":"请补充地区。",'
            '"research_brief":null,"missing_fields":["geography"]}',
        )
    )

    decision = await engine.decide("调研这个产业", [])

    assert decision.missing_fields == ["geography"]


async def test_start_research_requires_brief():
    engine = IntakeEngine(
        agent=_FakeAgent(
            '{"intent":"start_research","reply":"开始。",'
            '"research_brief":null,"missing_fields":[]}',
            "[]",
        )
    )

    with pytest.raises(IntelError) as caught:
        await engine.decide("调研先进封装", [])

    assert caught.value.code == "INTAKE_FAILED"
