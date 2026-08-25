from __future__ import annotations

from dataclasses import dataclass

import pytest

from intel_agent.dialogue import DialogueEngine, build_dialogue_prompt
from intel_agent.models import IntelError
from intel_agent.retrieval import RetrievedPassage
from tests.conftest import new_task


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


def _passage(passage_id: str = "evidence:one") -> RetrievedPassage:
    return RetrievedPassage(
        id=passage_id,
        citation_kind="verified_evidence",
        document_id="document-1",
        evidence_id="evidence-1",
        fact_id="fact-1",
        title="Official filing",
        source_url="https://example.com/filing",
        quote_text="The company launched the product.",
        line_start=4,
        line_end=4,
        source_content_hash="abc",
        score=2,
    )


async def test_dialogue_filters_citations_outside_allow_list(cwd):
    task = new_task(cwd)
    fake = _FakeAgent(
        '{"intent":"ask_evidence","answer":"已发布。",'
        '"answerability":"answered","cited_passage_ids":'
        '["evidence:one","invented"],"gaps":[]}'
    )
    engine = DialogueEngine(agent=fake)

    decision = await engine.answer(
        task=task,
        query="是否发布？",
        summary="",
        messages=[],
        passages=[_passage()],
        run_status="idle",
    )

    assert decision.cited_passage_ids == ["evidence:one"]
    assert decision.action is None


async def test_dialogue_repairs_malformed_json_once(cwd):
    task = new_task(cwd)
    fake = _FakeAgent(
        "not json",
        '```json\n{"intent":"ask_evidence","answer":"材料不足",'
        '"answerability":"not_answerable","cited_passage_ids":[],"gaps":'
        '["缺少官方数据"]}\n```',
    )
    engine = DialogueEngine(agent=fake)

    decision = await engine.answer(
        task=task,
        query="结论是什么？",
        summary="",
        messages=[],
        passages=[],
        run_status="idle",
    )

    assert decision.answerability == "not_answerable"
    assert len(fake.prompts) == 2


async def test_dialogue_rejects_non_object_json_after_repair(cwd):
    task = new_task(cwd)
    engine = DialogueEngine(agent=_FakeAgent("[]", "[]"))

    with pytest.raises(IntelError) as caught:
        await engine.answer(
            task=task,
            query="结论是什么？",
            summary="",
            messages=[],
            passages=[],
            run_status="idle",
        )

    assert caught.value.code == "DIALOGUE_FAILED"


async def test_question_cannot_become_explicit_search(cwd):
    task = new_task(cwd)
    fake = _FakeAgent(
        '{"intent":"ask_evidence","answer":"建议补查。",'
        '"answerability":"partial","cited_passage_ids":[],"gaps":[], '
        '"action":{"type":"continue_research","request_mode":'
        '"explicit_message","scope":{"topic":"供应商"}}}'
    )
    engine = DialogueEngine(agent=fake)

    decision = await engine.answer(
        task=task,
        query="你觉得有没有必要继续搜索供应商？",
        summary="",
        messages=[],
        passages=[],
        run_status="idle",
    )

    assert decision.action is not None
    assert decision.action.request_mode == "proposed"


async def test_explicit_search_instruction_stays_explicit(cwd):
    task = new_task(cwd)
    fake = _FakeAgent(
        '{"intent":"continue_research","answer":"开始补充检索。",'
        '"answerability":"partial","cited_passage_ids":[],"gaps":[], '
        '"action":{"type":"continue_research","request_mode":'
        '"explicit_message","scope":{"topic":"美国监管文件"}}}'
    )
    engine = DialogueEngine(agent=fake)

    decision = await engine.answer(
        task=task,
        query="继续搜索美国监管文件",
        summary="",
        messages=[],
        passages=[],
        run_status="idle",
    )

    assert decision.action is not None
    assert decision.action.request_mode == "explicit_message"


def test_dialogue_prompt_is_bounded_to_supplied_context(cwd):
    task = new_task(cwd)
    prompt = build_dialogue_prompt(
        task,
        "Earlier discussion",
        [],
        [_passage()],
        "idle",
    )

    assert task.topic in prompt
    assert "evidence:one" in prompt
    assert "The company launched" in prompt
    assert "unrelated secret" not in prompt
