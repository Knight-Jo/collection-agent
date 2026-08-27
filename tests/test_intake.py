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


async def test_intake_repair_explains_schema_validation_errors():
    agent = _FakeAgent(
        '{"intent":"start_research","reply":"开始。",'
        '"research_brief":{"topic":"先进封装","objective":"分析产业",'
        '"key_questions":["市场如何？","竞争如何？"],'
        '"scope":"近三年、全球范围","entities":[],'
        '"constraints":"仅基于公开信息",'
        '"requested_outputs":["research_report"]},'
        '"missing_fields":[]}',
        '{"intent":"start_research","reply":"开始。",'
        '"research_brief":{"topic":"先进封装","objective":"分析产业",'
        '"key_questions":["市场如何？","竞争如何？"],'
        '"scope":{"time_range":"近三年","geography":["全球"],'
        '"languages":[]},"entities":[],'
        '"constraints":["仅基于公开信息"],'
        '"requested_outputs":["research_report"]},'
        '"missing_fields":[]}',
    )
    engine = IntakeEngine(agent=agent)

    decision = await engine.decide("调研先进封装", [])

    assert decision.research_brief is not None
    assert decision.research_brief.scope.geography == ["全球"]
    assert '"loc": ["research_brief", "scope"]' in agent.prompts[1]
    assert '"time_range"' in agent.prompts[1]


async def test_intake_accepts_single_values_for_list_fields():
    agent = _FakeAgent(
        '{"intent":"start_research","reply":"开始。",'
        '"research_brief":{"topic":"先进封装","objective":"分析产业",'
        '"key_questions":["市场如何？","竞争如何？"],'
        '"scope":{"time_range":"近三年","geography":"全球",'
        '"languages":"中文"},"entities":"企业甲",'
        '"constraints":"仅基于公开信息",'
        '"requested_outputs":"research_report"},'
        '"missing_fields":[]}'
    )
    engine = IntakeEngine(agent=agent)

    decision = await engine.decide("调研先进封装", [])

    assert decision.research_brief is not None
    assert decision.research_brief.scope.geography == ["全球"]
    assert decision.research_brief.scope.languages == ["中文"]
    assert decision.research_brief.entities == ["企业甲"]
    assert decision.research_brief.constraints == ["仅基于公开信息"]
    assert decision.research_brief.requested_outputs == ["research_report"]
    assert len(agent.prompts) == 1


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
