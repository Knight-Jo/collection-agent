from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, cast

from pydantic_ai import CancellationToken

from intel_agent.conversation import ConversationRuntime
from intel_agent.dialogue import DialogueAction, DialogueDecision
from intel_agent.intake import IntakeDecision
from intel_agent.models import (
    ActionRequest,
    Message,
    ResearchBrief,
    ResearchRun,
)
from intel_agent.retrieval import RetrievedPassage
from intel_agent.state_store import StateStore
from tests.conftest import new_task


class _Retriever:
    def __init__(self, passages=()):
        self.passages = list(passages)
        self.seeded: list[str] = []

    def seed_completed_task(self, task_id: str) -> None:
        self.seeded.append(task_id)

    def retrieve(
        self, task_id: str, query: str, *, limit: int = 8
    ) -> list[RetrievedPassage]:
        del task_id, query, limit
        return self.passages


class _Dialogue:
    def __init__(self, decision: DialogueDecision, *, fail: bool = False):
        self.decision = decision
        self.fail = fail
        self.answer_calls = 0
        self.summary_calls = 0

    async def answer(self, **_kwargs):
        self.answer_calls += 1
        if self.fail:
            raise RuntimeError("model unavailable")
        return self.decision

    async def summarize(self, messages: Sequence[Message]) -> str:
        del messages
        self.summary_calls += 1
        return "早期对话摘要"


class _ActionRunner:
    def __init__(self):
        self.calls = []
        self.called = asyncio.Event()

    async def run(
        self, action: ActionRequest, cancellation_token: CancellationToken
    ) -> None:
        del cancellation_token
        self.calls.append(action)
        self.called.set()


class _InitialRunner:
    def __init__(self):
        self.calls: list[tuple[ResearchRun, ResearchBrief]] = []
        self.called = asyncio.Event()

    async def run_initial(
        self,
        run: ResearchRun,
        brief: ResearchBrief,
        cancellation_token: CancellationToken,
    ) -> None:
        del cancellation_token
        self.calls.append((run, brief))
        self.called.set()


class _Intake:
    def __init__(self, decision: IntakeDecision, *, fail: bool = False):
        self.decision = decision
        self.fail = fail

    async def decide(self, query: str, messages: Sequence[Message]):
        del query, messages
        if self.fail:
            raise RuntimeError("intake unavailable")
        return self.decision


def _capability() -> IntakeDecision:
    return IntakeDecision(
        intent="capability_query",
        reply="我可以开展公开信息调研。",
    )


def _start_research() -> IntakeDecision:
    return IntakeDecision(
        intent="start_research",
        reply="已建立调研任务。",
        research_brief=ResearchBrief(
            topic="先进封装",
            key_questions=["产业规模如何？", "竞争格局如何？"],
        ),
    )


async def test_capability_query_keeps_intake_unbound(cwd):
    runtime = ConversationRuntime(
        cwd,
        intake=_Intake(_capability()),
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
    )
    conversation = runtime.create_conversation()

    user = runtime.submit_message(
        conversation.id, "你能做什么？", "client-intake-1"
    )
    assistant = await runtime.wait_message(user.id)

    assert assistant.content == "我可以开展公开信息调研。"
    assert (
        runtime.store.get_conversation_by_id(conversation.id).task_id is None
    )
    assert runtime.store.list_runs_for_conversation(conversation.id) == []


async def test_clear_request_binds_one_task(cwd):
    initial = _InitialRunner()
    runtime = ConversationRuntime(
        cwd,
        intake=_Intake(_start_research()),
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
        initial=initial,
    )
    conversation = runtime.create_conversation()

    user = runtime.submit_message(
        conversation.id, "调研先进封装产业", "client-intake-1"
    )
    await runtime.wait_message(user.id)
    await initial.called.wait()
    bound = runtime.store.get_conversation_by_id(conversation.id)

    assert bound.status == "active"
    assert bound.task_id is not None
    assert len(runtime.store.list_runs(bound.task_id)) == 1
    assert initial.calls[0][0].run_type == "initial"
    assert initial.calls[0][1].topic == "先进封装"


async def test_recovery_schedules_queued_initial_run(cwd):
    first = ConversationRuntime(
        cwd,
        intake=_Intake(_start_research()),
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
    )
    conversation = first.create_conversation()
    user = first.submit_message(
        conversation.id, "调研先进封装产业", "client-intake-1"
    )
    await first.wait_message(user.id)
    initial = _InitialRunner()
    recovered = ConversationRuntime(
        cwd,
        intake=_Intake(_start_research()),
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
        initial=initial,
    )

    count = recovered.recover()
    await initial.called.wait()

    assert count == 1
    assert initial.calls[0][0].status == "queued"


async def test_intake_failure_does_not_mutate_user_message(cwd):
    runtime = ConversationRuntime(
        cwd,
        intake=_Intake(_capability(), fail=True),
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
    )
    conversation = runtime.create_conversation()

    user = runtime.submit_message(conversation.id, "调研", "client-intake-1")
    await runtime.wait_message(user.id)

    assert runtime.store.get_message(user.id).status == "accepted"
    attempt = runtime.store.latest_processing_attempt(user.id)
    assert attempt.status == "failed"
    view = runtime.conversation_view_by_id(conversation.id)
    attempts = cast(list[dict[str, object]], view["processing_attempts"])
    assert attempts[0]["error_detail"] == "intake unavailable"


def _decision(
    *,
    citations: list[str] | None = None,
    action: DialogueAction | None = None,
) -> DialogueDecision:
    return DialogueDecision(
        intent="ask_evidence" if action is None else "continue_research",
        answer="基于当前材料的回答",
        answerability="answered",
        cited_passage_ids=citations or [],
        gaps=[],
        action=action,
    )


def _passage() -> RetrievedPassage:
    return RetrievedPassage(
        id="evidence:one",
        citation_kind="verified_evidence",
        document_id="document-1",
        evidence_id="evidence-1",
        fact_id="fact-1",
        title="官方材料",
        source_url="https://example.com/source",
        quote_text="已确认事实",
        line_start=3,
        line_end=3,
        source_content_hash="abc",
        score=2,
    )


async def test_runtime_accepts_completes_and_binds_citation(cwd):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    store.seed_committed_assets(
        task.id,
        [
            ("document", "document-1"),
            ("fact", "fact-1"),
            ("evidence", "evidence-1"),
        ],
    )
    runtime = ConversationRuntime(
        cwd,
        dialogue=_Dialogue(_decision(citations=["evidence:one"])),
        retriever=_Retriever([_passage()]),
    )

    user = runtime.submit_message(task.id, "已有结论？", "client-1")
    retried = runtime.submit_message(task.id, "已有结论？", "client-1")
    assistant = await runtime.wait_message(user.id)

    assert retried.id == user.id
    assert assistant.content == "基于当前材料的回答"
    assert store.citations_for_message(assistant.id)[0].document_id == (
        "document-1"
    )
    assert len(store.list_messages(task.id)) == 2


async def test_runtime_proposes_or_runs_actions(cwd):
    task = new_task(cwd)
    proposed_dialogue = _Dialogue(
        _decision(
            action=DialogueAction(
                type="continue_research",
                request_mode="proposed",
                scope={"topic": "供应商"},
            )
        )
    )
    runner = _ActionRunner()
    runtime = ConversationRuntime(
        cwd,
        dialogue=proposed_dialogue,
        retriever=_Retriever(),
        continuation=runner,
    )

    proposed_message = runtime.submit_message(
        task.id, "材料够吗？", "client-1"
    )
    await runtime.wait_message(proposed_message.id)

    action = runtime.store.list_actions(task.id)[0]
    assert action.status == "proposed"
    assert runner.calls == []

    explicit_runtime = ConversationRuntime(
        cwd,
        dialogue=_Dialogue(
            _decision(
                action=DialogueAction(
                    type="continue_research",
                    request_mode="explicit_message",
                    scope={"topic": "供应商"},
                )
            )
        ),
        retriever=_Retriever(),
        continuation=runner,
    )
    explicit = explicit_runtime.submit_message(
        task.id, "继续搜索供应商", "client-2"
    )
    await explicit_runtime.wait_message(explicit.id)
    await asyncio.wait_for(runner.called.wait(), timeout=1)

    assert len(runner.calls) == 1


async def test_runtime_marks_model_failure(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd,
        dialogue=_Dialogue(_decision(), fail=True),
        retriever=_Retriever(),
    )

    user = runtime.submit_message(task.id, "问题", "client-1")
    await runtime.wait_message(user.id)

    accepted = runtime.store.get_message(user.id)
    failed = runtime.store.latest_processing_attempt(user.id)
    assert accepted.status == "accepted"
    assert failed.status == "failed"
    assert failed.error_detail == "model unavailable"


async def test_runtime_recovers_unfinished_message(cwd):
    task = new_task(cwd)
    store = StateStore(cwd)
    store.register_task(task.id)
    unfinished = store.add_user_message(task.id, "恢复问题", "client-1")
    runtime = ConversationRuntime(
        cwd,
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
    )

    recovered = runtime.recover()
    assistant = await runtime.wait_message(unfinished.id)

    assert recovered == 1
    assert assistant.reply_to_id == unfinished.id


async def test_runtime_updates_epoch_summary_after_twelve_messages(cwd):
    task = new_task(cwd)
    dialogue = _Dialogue(_decision())
    runtime = ConversationRuntime(
        cwd,
        dialogue=dialogue,
        retriever=_Retriever(),
    )

    for number in range(7):
        message = runtime.submit_message(
            task.id, f"问题 {number}", f"client-{number}"
        )
        await runtime.wait_message(message.id)

    view = cast(dict[str, Any], runtime.conversation_view(task.id))
    assert view["epoch"]["summary"] == "早期对话摘要"
    assert view["epoch"]["summary_through_sequence"] == 6
    assert dialogue.summary_calls == 1


async def test_ordinary_question_never_calls_continuation(cwd):
    task = new_task(cwd)
    runner = _ActionRunner()
    runtime = ConversationRuntime(
        cwd,
        dialogue=_Dialogue(_decision()),
        retriever=_Retriever(),
        continuation=runner,
    )

    message = runtime.submit_message(task.id, "当前结论？", "client-1")
    await runtime.wait_message(message.id)

    assert runner.calls == []
