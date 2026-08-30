"""Async orchestration for persistent task-scoped dialogue."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Protocol

from pydantic_ai import CancellationToken

from .config import Settings
from .dialogue import DialogueDecision, DialogueEngine
from .intake import IntakeDecision, IntakeEngine
from .logging import get_logger
from .models import (
    ActionRequest,
    CitationDraft,
    Conversation,
    IntelError,
    Message,
    ReportVersion,
    ResearchBrief,
    ResearchRun,
)
from .report_versions import ReportPublisher
from .retrieval import RetrievedPassage, TaskRetriever
from .state_store import StateStore
from .task import load_task

logger = get_logger(__name__)


class _Dialogue(Protocol):
    async def answer(self, **kwargs: object) -> DialogueDecision: ...

    async def summarize(self, messages: Sequence[Message]) -> str: ...


class _Intake(Protocol):
    async def decide(
        self, query: str, messages: Sequence[Message]
    ) -> IntakeDecision: ...


class _Retriever(Protocol):
    def seed_completed_task(self, task_id: str) -> None: ...

    def retrieve(
        self, task_id: str, query: str, *, limit: int = 8
    ) -> list[RetrievedPassage]: ...


class _ReportPublisher(Protocol):
    async def run(self, action: ActionRequest) -> object: ...

    def create_draft(self, task_id: str) -> ReportVersion: ...

    def read(self, report_id: str) -> tuple[ReportVersion, str]: ...

    def publish(
        self,
        report_id: str,
        *,
        publish_stale: bool = False,
        expected_current_state_version: int | None = None,
    ) -> ReportVersion: ...


class _ContinuationRunner(Protocol):
    async def run(
        self, action: ActionRequest, cancellation_token: CancellationToken
    ) -> object: ...


class _InitialRunner(Protocol):
    async def run_initial(
        self,
        run: ResearchRun,
        brief: ResearchBrief,
        cancellation_token: CancellationToken,
    ) -> object: ...


class ConversationRuntime:
    """Provide the persistent, task-scoped conversation with the agent.

    The class exists so the web layer can drive one user conversation end
    to end behind the FastAPI routes: from the first intake message,
    through task binding, cited dialogue answers, and proposed actions,
    to research runs. That conversation must survive process restarts
    (durable state in the store, in-memory bookkeeping rebuilt via
    ``recover``) and must answer promptly even while research executes,
    so dialogue stays in-process and research work is delegated to the
    injected runners.

    Attributes
    ----------
    cwd:
        Working directory containing task definitions and durable state.
    store:
        ``StateStore`` backing the conversation; all durable reads and
        writes go through it.
    intake:
        Engine that classifies taskless messages and may return a research
        brief. Built from ``IntakeEngine`` when not injected.
    dialogue:
        Engine that answers task-bound questions with citations and may
        propose actions. Built from ``DialogueEngine`` when not injected.
    retriever:
        Passage retriever for answer grounding and baseline seeding. Built
        from ``TaskRetriever`` when not injected.
    initial:
        Runner for initial research runs; ``None`` leaves initial runs
        queued for an external worker.
    continuation:
        Runner for continuation research actions; ``None`` leaves
        continuation actions queued for an external worker.
    publisher:
        Worker for report generation and regeneration actions. Built from
        ``ReportPublisher`` when not injected.
    _dialogue_lock / _message_tasks / _action_tasks / _action_tokens /
    _run_tasks / _run_tokens / _transient_subscribers:
        In-memory bookkeeping (serialization lock, background-task and
        cancellation-token registries, transient event subscribers)
        rebuilt after a restart via ``recover``.

    Public methods
    --------------
    create_conversation / submit_message / wait_message:
        Start an intake conversation, persist a user message, and await its
        reply.
    retry_message / cancel_message:
        Re-run or cancel processing of one message.
    recover:
        Reschedule unfinished messages and queued initial runs after a
        process restart.
    confirm_action / reject_action / cancel_action:
        Accept, refuse, or cancel a proposed or running action.
    stop_research_run / cancel_research_run:
        Request stop or cancellation of a research run.
    conversation_view / conversation_view_by_id:
        Project the full conversation state for the Web UI.
    transient_events / publish_transient:
        Subscribe to and publish non-durable live events.
    """

    def __init__(
        self,
        cwd: Path,
        settings: Settings | None = None,
        *,
        intake: _Intake | None = None,
        dialogue: _Dialogue | None = None,
        retriever: _Retriever | None = None,
        initial: _InitialRunner | None = None,
        continuation: _ContinuationRunner | None = None,
        publisher: _ReportPublisher | None = None,
    ):
        settings = settings or Settings()
        self.cwd = cwd
        self.store = StateStore(cwd)
        self.intake = intake or IntakeEngine(settings)
        self.dialogue = dialogue or DialogueEngine(settings)
        self.retriever = retriever or TaskRetriever(cwd, self.store)
        self.initial = initial
        self.continuation = continuation
        self.publisher = publisher or ReportPublisher(cwd, store=self.store)
        self._dialogue_lock = asyncio.Lock()
        self._message_tasks: dict[str, asyncio.Task[None]] = {}
        self._action_tasks: set[asyncio.Task[object]] = set()
        self._action_tasks_by_id: dict[str, asyncio.Task[object]] = {}
        self._action_tokens: dict[str, CancellationToken] = {}
        self._run_tasks: dict[str, asyncio.Task[object]] = {}
        self._run_tokens: dict[str, CancellationToken] = {}
        self._transient_subscribers: dict[
            str, set[asyncio.Queue[tuple[str, dict[str, object]]]]
        ] = {}

    @asynccontextmanager
    async def transient_events(
        self, conversation_id: str
    ) -> AsyncIterator[asyncio.Queue[tuple[str, dict[str, object]]]]:
        """Subscribe to non-durable events for one live response."""
        self.store.get_conversation_by_id(conversation_id)
        queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue()
        subscribers = self._transient_subscribers.setdefault(
            conversation_id, set()
        )
        subscribers.add(queue)
        try:
            yield queue
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._transient_subscribers.pop(conversation_id, None)

    def publish_transient(
        self,
        conversation_id: str,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        """Publish a best-effort event to currently connected clients."""
        for queue in self._transient_subscribers.get(conversation_id, ()):
            queue.put_nowait((event_type, data))

    def create_conversation(self) -> Conversation:
        """Create a new taskless intake conversation."""
        return self.store.create_conversation()

    def submit_message(
        self,
        conversation_or_task_id: str,
        content: str,
        client_message_id: str,
    ) -> Message:
        """Persist a user message before scheduling its dialogue turn."""
        try:
            conversation = self.store.get_conversation_by_id(
                conversation_or_task_id
            )
        except IntelError as error:
            if error.code != "NOT_FOUND":
                raise
            self._ensure_task(conversation_or_task_id)
            conversation = self.store.get_conversation(conversation_or_task_id)
        message = self.store.add_user_message(
            conversation.id, content, client_message_id
        )
        attempt = self.store.ensure_processing_attempt(message.id)
        if (
            attempt.status in {"accepted", "processing"}
            and self.store.reply_for_message(message.id) is None
            and message.id not in self._message_tasks
        ):
            self._schedule_message(message.id)
        return message

    async def wait_message(self, message_id: str) -> Message:
        """Wait for processing and return the reply or terminal user request."""
        task = self._message_tasks.get(message_id)
        if task is not None:
            await task
        reply = self.store.reply_for_message(message_id)
        return reply or self.store.get_message(message_id)

    def recover(self) -> int:
        """Reschedule unfinished messages after a process restart."""
        pending = self.store.pending_messages()
        for message in pending:
            if message.id not in self._message_tasks:
                self._schedule_message(message.id)
        recovered_runs = 0
        if self.initial is not None:
            for conversation in self.store.list_conversations():
                if conversation.task_id is None:
                    continue
                task = load_task(self.cwd, conversation.task_id)
                brief = ResearchBrief(
                    topic=task.topic,
                    objective=task.objective,
                    key_questions=[item.text for item in task.questions],
                    scope=task.scope,
                )
                for run in self.store.list_runs(task.id):
                    if run.run_type == "initial" and run.status == "queued":
                        self._schedule_initial(run, brief)
                        recovered_runs += 1
        return len(pending) + recovered_runs

    def retry_message(self, message_id: str) -> Message:
        """Retry system processing without duplicating the user message."""
        attempt = self.store.retry_processing_attempt(message_id)
        if (
            attempt.status == "accepted"
            and message_id not in self._message_tasks
        ):
            self._schedule_message(message_id)
        return self.store.get_message(message_id)

    def confirm_action(
        self, action_id: str, client_message_id: str
    ) -> ActionRequest:
        """Confirm a proposed action and queue its unchanged payload."""
        action = self.store.get_action(action_id)
        confirmation = self.store.add_user_message(
            action.task_id, "确认执行建议", client_message_id
        )
        queued = self.store.confirm_action(action_id, confirmation.id)
        if queued.status != "queued":
            self.store.complete_message(
                confirmation.id, "该调研建议已过期，请重新发起续研。"
            )
            self.store.append_event(
                action.task_id,
                "action.expired",
                {"action_id": action_id},
                action_request_id=action_id,
            )
            return queued
        self.store.complete_message(
            confirmation.id, "已确认，任务进入执行队列。"
        )
        self.store.append_event(
            action.task_id,
            "action.queued",
            {"action_id": action_id},
            action_request_id=action_id,
        )
        self._schedule_action(queued)
        return queued

    def reject_action(self, action_id: str) -> ActionRequest:
        """Reject one proposed action."""
        action = self.store.transition_action(action_id, "rejected")
        self.store.append_event(
            action.task_id,
            "action.rejected",
            {"action_id": action.id},
            action_request_id=action.id,
        )
        return action

    async def cancel_action(self, action_id: str) -> ActionRequest:
        """Cancel a proposed, queued, or executing task action."""
        action = self.store.get_action(action_id)
        if action.status == "proposed":
            return self.reject_action(action_id)
        token = self._action_tokens.get(action_id)
        if token is not None:
            token.cancel()
        task = self._action_tasks_by_id.get(action_id)
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
        current = self.store.get_action(action_id)
        if current.status == "queued":
            current = self.store.transition_action(action_id, "cancelled")
        return current

    async def cancel_research_run(self, run_id: str) -> ResearchRun:
        """Cancel a continuation run through its originating action."""
        run = self.store.get_run(run_id)
        if run.action_request_id is None:
            if run.status == "queued":
                token = self._run_tokens.get(run.id)
                if token is not None:
                    token.cancel()
                return self.store.transition_run(run.id, "cancelled")
            return run
        await self.cancel_action(run.action_request_id)
        return self.store.get_run(run_id)

    def stop_research_run(self, run_id: str) -> ResearchRun:
        """Request stop for a running Run and signal its active worker."""
        run = self.store.stop_run(run_id)
        token = self._run_tokens.get(run.id)
        if token is not None:
            token.cancel()
        if run.action_request_id is not None:
            token = self._action_tokens.get(run.action_request_id)
            if token is not None:
                token.cancel()
        return run

    async def cancel_message(self, message_id: str) -> Message:
        """Cancel in-memory generation and persist the terminal state."""
        task = self._message_tasks.get(message_id)
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        message = self.store.get_message(message_id)
        if message.status in {"accepted", "processing"}:
            return self.store.cancel_message(message_id)
        return message

    def conversation_view(self, task_id: str) -> dict[str, object]:
        """Return the complete task conversation projection for the Web UI."""
        self._ensure_task(task_id)
        conversation = self.store.get_conversation(task_id)
        return self.conversation_view_by_id(conversation.id)

    def conversation_view_by_id(
        self, conversation_id: str
    ) -> dict[str, object]:
        """Return a Conversation projection before or after Task binding."""
        conversation = self.store.get_conversation_by_id(conversation_id)
        epoch = self.store.active_epoch_for_conversation(conversation_id)
        messages, citations, attempts = self.store.conversation_message_view(
            conversation_id
        )
        message_values = []
        processing_attempts = []
        for message in messages:
            value = message.model_dump(mode="json")
            value["citations"] = [
                item.model_dump(mode="json")
                for item in citations.get(message.id, [])
            ]
            message_values.append(value)
            if message.role == "user":
                attempt = attempts.get(message.id)
                if attempt is not None:
                    processing_attempts.append(attempt.model_dump(mode="json"))
        task_id = conversation.task_id
        actions = self.store.list_actions(task_id) if task_id else []
        runs = self.store.list_runs(task_id) if task_id else []
        reports = self.store.list_reports(task_id) if task_id else []
        return {
            "conversation": conversation.model_dump(mode="json"),
            "epoch": epoch.model_dump(mode="json"),
            "messages": message_values,
            "processing_attempts": processing_attempts,
            "actions": [item.model_dump(mode="json") for item in actions],
            "runs": [item.model_dump(mode="json") for item in runs],
            "reports": [item.model_dump(mode="json") for item in reports],
            "committed_state_version": (
                self.store.committed_state_version(task_id) if task_id else 0
            ),
        }

    def _ensure_task(self, task_id: str) -> None:
        load_task(self.cwd, task_id)
        self.store.register_task(task_id)
        if any(
            event.event_type == "task.baseline_seeded"
            for event in self.store.events_after(task_id, 0)
        ):
            return
        self.retriever.seed_completed_task(task_id)
        self.store.append_event(task_id, "task.baseline_seeded", {})

    def _schedule_message(self, message_id: str) -> None:
        task = asyncio.create_task(self._process_message(message_id))
        self._message_tasks[message_id] = task
        task.add_done_callback(
            lambda _task: self._message_tasks.pop(message_id, None)
        )

    async def _process_message(self, message_id: str) -> None:
        attempt = self.store.ensure_processing_attempt(message_id)
        conversation: Conversation | None = None
        try:
            self.store.transition_processing_attempt(attempt.id, "processing")
            user = self.store.get_message(message_id)
            conversation = self.store.get_conversation_by_id(
                user.conversation_id
            )
            if conversation.task_id is None:
                messages = self.store.list_messages_for_conversation(
                    conversation.id
                )
                async with self._dialogue_lock:
                    intake = await self.intake.decide(user.content, messages)
                if intake.intent == "start_research":
                    if intake.research_brief is None:
                        raise RuntimeError(
                            "intake result lacks research brief"
                        )
                    bound = self.store.bind_intake_task(
                        conversation.id, user.id, intake.research_brief
                    )
                    if self.initial is not None and bound.task_id is not None:
                        run = self.store.list_runs(bound.task_id)[-1]
                        self._schedule_initial(run, intake.research_brief)
                assistant = self.store.complete_message(
                    user.id,
                    intake.reply,
                    mark_user_completed=False,
                )
                self.store.transition_processing_attempt(
                    attempt.id,
                    "completed",
                    assistant_message_id=assistant.id,
                )
                return
            task_id = conversation.task_id
            task = load_task(self.cwd, task_id)
            passages = self.retriever.retrieve(task.id, user.content, limit=8)
            epoch = self.store.active_epoch(task.id)
            messages = self.store.list_messages(task.id)
            runs = self.store.list_runs(task.id)
            run_status = runs[-1].status if runs else "idle"
            self.publish_transient(
                conversation.id,
                "answer.started",
                {"reply_to_id": user.id},
            )

            async def publish_delta(delta: str) -> None:
                self.publish_transient(
                    conversation.id,
                    "answer.delta",
                    {"reply_to_id": user.id, "delta": delta},
                )

            async with self._dialogue_lock:
                decision = await self.dialogue.answer(
                    task=task,
                    query=user.content,
                    summary=epoch.summary,
                    messages=messages,
                    passages=passages,
                    run_status=run_status,
                    on_delta=publish_delta,
                )
            passages_by_id = {item.id: item for item in passages}
            citations = [
                _citation_from_passage(passages_by_id[passage_id])
                for passage_id in decision.cited_passage_ids
            ]
            assistant = self.store.complete_message(
                user.id,
                decision.answer,
                citations,
                mark_user_completed=False,
            )
            if decision.action is not None:
                proposed = decision.action.request_mode == "proposed"
                action = self.store.create_action(
                    task.id,
                    user.id,
                    decision.action.type,
                    decision.action.scope,
                    proposed=proposed,
                )
                event_type = "action.proposed" if proposed else "action.queued"
                self.store.append_event(
                    task.id,
                    event_type,
                    {"action_id": action.id},
                    action_request_id=action.id,
                )
                if not proposed:
                    self._schedule_action(action)
            await self._maybe_update_summary(task.id)
            self.store.transition_processing_attempt(
                attempt.id,
                "completed",
                assistant_message_id=assistant.id,
            )
        except asyncio.CancelledError:
            self.store.transition_processing_attempt(attempt.id, "cancelled")
            if conversation is not None:
                self.publish_transient(
                    conversation.id,
                    "answer.failed",
                    {"reply_to_id": message_id},
                )
            raise
        except Exception as error:
            self.store.transition_processing_attempt(
                attempt.id,
                "failed",
                error_code=getattr(error, "code", "PROCESSING_FAILED"),
                error_detail=str(error),
            )
            if conversation is not None:
                self.publish_transient(
                    conversation.id,
                    "answer.failed",
                    {"reply_to_id": message_id},
                )
            logger.exception("Conversation message processing failed")

    def _schedule_action(self, action: ActionRequest) -> None:
        if action.action_type in {"generate_report", "regenerate_report"}:
            if self.publisher is None:
                return
            task = asyncio.create_task(self.publisher.run(action))
        else:
            if self.continuation is None:
                return
            token = CancellationToken()
            self._action_tokens[action.id] = token
            task = asyncio.create_task(self.continuation.run(action, token))
        self._action_tasks.add(task)
        self._action_tasks_by_id[action.id] = task

        def discard(completed: asyncio.Task[object]) -> None:
            self._action_tasks.discard(completed)
            self._action_tasks_by_id.pop(action.id, None)
            self._action_tokens.pop(action.id, None)

        task.add_done_callback(discard)

    def _schedule_initial(
        self, run: ResearchRun, brief: ResearchBrief
    ) -> None:
        if self.initial is None or run.id in self._run_tasks:
            return
        token = CancellationToken()
        self._run_tokens[run.id] = token
        task = asyncio.create_task(self.initial.run_initial(run, brief, token))
        self._run_tasks[run.id] = task

        def discard(_completed: asyncio.Task[object]) -> None:
            self._run_tasks.pop(run.id, None)
            self._run_tokens.pop(run.id, None)

        task.add_done_callback(discard)

    async def _maybe_update_summary(self, task_id: str) -> None:
        epoch = self.store.active_epoch(task_id)
        messages = self.store.list_messages(task_id)
        unsummarized = [
            item
            for item in messages
            if item.sequence > epoch.summary_through_sequence
        ]
        if len(unsummarized) <= 12 or len(messages) <= 8:
            return
        older = messages[:-8]
        if not older:
            return
        try:
            async with self._dialogue_lock:
                summary = await self.dialogue.summarize(older)
            self.store.update_epoch_summary(
                epoch.id, summary, older[-1].sequence
            )
        except Exception:
            logger.exception("Conversation summary update failed")


def _citation_from_passage(passage: RetrievedPassage) -> CitationDraft:
    return CitationDraft(
        citation_kind=passage.citation_kind,
        document_id=passage.document_id,
        evidence_id=passage.evidence_id,
        fact_id=passage.fact_id,
        title=passage.title,
        source_url=passage.source_url,
        quote_text=passage.quote_text,
        line_start=passage.line_start,
        line_end=passage.line_end,
        source_content_hash=passage.source_content_hash,
    )
