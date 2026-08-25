from __future__ import annotations

import asyncio

from intel_agent.conversation import ConversationRuntime
from intel_agent.dialogue import DialogueAction, DialogueDecision
from intel_agent.retrieval import RetrievedPassage
from intel_agent.state_store import StateStore
from tests.conftest import new_task


class _Retriever:
    def __init__(self, passages=()):
        self.passages = list(passages)
        self.seeded: list[str] = []

    def seed_completed_task(self, task_id: str) -> None:
        self.seeded.append(task_id)

    def retrieve(self, task_id: str, query: str, **_kwargs):
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

    async def summarize(self, _messages):
        self.summary_calls += 1
        return "早期对话摘要"


class _ActionRunner:
    def __init__(self):
        self.calls = []
        self.called = asyncio.Event()

    async def run(self, action, _cancellation_token=None):
        self.calls.append(action)
        self.called.set()


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

    failed = runtime.store.get_message(user.id)
    assert failed.status == "failed"
    assert failed.error == "model unavailable"


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

    view = runtime.conversation_view(task.id)
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
