"""ConversationService brief/research-start behavior."""

from __future__ import annotations

import asyncio
import time

from intel_agent.contracts.research import ResearchBrief, ResearchPlan
from intel_agent.conversation import ConversationService
from intel_agent.runtime.events import EventBus


class _Result:
    def __init__(self, output):
        self.output = output


class _Role:
    def __init__(self, output):
        self._output = output
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> _Result:
        self.prompts.append(prompt)
        return _Result(self._output)


class _FailingOrchestrator:
    async def run_task(self, task, event_sink=None, plan=None):
        raise RuntimeError("boom")


class _Settings:
    class _Research:
        deadline_seconds = 60

    research = _Research()


async def test_generate_brief_uses_brief_role_not_full_planner():
    brief = ResearchBrief(
        goal="目标",
        scope="范围",
        questions=["q1", "q2"],
        key_entities=["e1"],
        suggested_sources=["s1"],
    )
    brief_role = _Role(brief)
    service = ConversationService(
        store=None,  # type: ignore[arg-type]  # generate_brief touches only roles
        orchestrator=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        roles={"brief": brief_role},
        registry=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]
        task_store=None,  # type: ignore[arg-type]
    )
    result = await service.generate_brief("调研 AI 芯片")
    assert brief_role.prompts == ["调研 AI 芯片"]
    assert result == {
        "goal": "目标",
        "scope": "范围",
        "questions": ["q1", "q2"],
        "key_entities": ["e1"],
        "suggested_sources": ["s1"],
    }


async def test_start_research_auto_launches_run(material_store, task_store):
    plan = ResearchPlan(questions=["q1"], directions=[])
    service = ConversationService(
        store=material_store,
        orchestrator=_FailingOrchestrator(),
        event_bus=EventBus(),
        roles={"planner": _Role(plan)},
        registry=None,  # type: ignore[arg-type]
        settings=_Settings(),  # type: ignore[arg-type]
        task_store=task_store,
    )
    try:
        view = await service.start_research(
            "调研中国大模型产业", {"questions": ["大模型格局如何？"]}
        )
        conversation_id = view["id"]
        deadline = time.monotonic() + 3
        messages = []
        while time.monotonic() < deadline:
            messages = material_store.list_messages(conversation_id)
            if len(messages) >= 2:
                break
            await asyncio.sleep(0.02)
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "调研中国大模型产业"
        assert messages[1]["content"].startswith("调研未能完成")
        task_id = task_store.latest_task_id(conversation_id)
        assert task_id is not None
        assert task_store.get_task(task_id).status == "failed"
    finally:
        await service.close()
