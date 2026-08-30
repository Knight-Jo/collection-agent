from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
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


class _StreamResult:
    def __init__(self, chunks: list[str]):
        self.chunks = chunks

    async def stream_text(self, *, delta: bool, debounce_by: float | None):
        assert delta is True
        for chunk in self.chunks:
            yield chunk


class _FakeStreamingAgent(_FakeAgent):
    def __init__(self, *chunks: str):
        super().__init__()
        self.chunks = list(chunks)

    @asynccontextmanager
    async def run_stream(self, prompt: str):
        self.prompts.append(prompt)
        yield _StreamResult(self.chunks)


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


def test_material_clue_cannot_produce_answered_status(cwd):
    task = new_task(cwd)
    clue = _passage("material:one")
    clue = clue.model_copy(update={"citation_kind": "material_clue"})
    fake = _FakeAgent(
        '{"intent":"ask_evidence","answer":"可能已发布。",'
        '"answerability":"answered","cited_passage_ids":["material:one"],'
        '"gaps":[]}'
    )

    decision = asyncio.run(
        DialogueEngine(agent=fake).answer(
            task=task,
            query="当前状态？",
            summary="",
            messages=[],
            passages=[clue],
            run_status="idle",
        )
    )

    assert decision.answerability == "partial"


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


async def test_dialogue_routes_explicit_new_topic_without_model(cwd):
    task = new_task(cwd)
    fake = _FakeAgent("not called")
    decision = await DialogueEngine(agent=fake).answer(
        task=task,
        query="换个主题，调研新能源汽车出口",
        summary="",
        messages=[],
        passages=[_passage()],
        run_status="idle",
    )

    assert decision.intent == "new_topic"
    assert decision.action is None
    assert decision.cited_passage_ids == []
    assert fake.prompts == []


async def test_dialogue_streams_answer_text_from_partial_json(cwd):
    task = new_task(cwd)
    fake = _FakeStreamingAgent(
        '{"intent":"ask_evidence","answer":"当前',
        '状态良好","answerability":"answered",',
        '"cited_passage_ids":[],"gaps":[]}',
    )
    engine = DialogueEngine(agent=fake)
    deltas: list[str] = []

    async def receive(delta: str) -> None:
        deltas.append(delta)

    decision = await engine.answer(
        task=task,
        query="当前状态？",
        summary="",
        messages=[],
        passages=[],
        run_status="idle",
        on_delta=receive,
    )

    assert deltas == ["当前状态良好"]
    assert decision.answer == "当前状态良好"
    assert len(fake.prompts) == 1


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
    assert '"title": "DialogueDecision"' in fake.prompts[1]


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


async def test_summary_merges_prior_memory_without_storing_research_facts():
    fake = _FakeAgent("更新后的对话记忆")
    engine = DialogueEngine(agent=fake)

    result = await engine.summarize([], previous_summary="用户要求中文简报")

    assert result == "更新后的对话记忆"
    assert "用户要求中文简报" in fake.prompts[0]
    assert "不得记录研究事实" in fake.prompts[0]


async def test_dialogue_accepts_greeting_without_action(cwd):
    task = new_task(cwd)
    greeting = (
        '{"intent":"greeting","answer":"你好，我可以继续解读当前调研材料。",'
        '"answerability":"answered","cited_passage_ids":[],"gaps":[]}'
    )
    engine = DialogueEngine(agent=_FakeAgent(greeting, greeting))

    decision = await engine.answer(
        task=task,
        query="hello",
        summary="",
        messages=[],
        passages=[],
        run_status="idle",
    )

    assert decision.intent == "greeting"
    assert decision.action is None


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
