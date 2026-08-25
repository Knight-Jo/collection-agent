"""Async orchestration for persistent task-scoped dialogue."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import suppress
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


class ConversationRuntime:
    """Process local task messages without mixing research execution state."""

    def __init__(
        self,
        cwd: Path,
        settings: Settings | None = None,
        *,
        intake: _Intake | None = None,
        dialogue: _Dialogue | None = None,
        retriever: _Retriever | None = None,
        continuation: _ContinuationRunner | None = None,
        publisher: _ReportPublisher | None = None,
    ):
        settings = settings or Settings()
        self.cwd = cwd
        self.store = StateStore(cwd)
        self.intake = intake or IntakeEngine(settings)
        self.dialogue = dialogue or DialogueEngine(settings)
        self.retriever = retriever or TaskRetriever(cwd, self.store)
        self.continuation = continuation
        self.publisher = publisher or ReportPublisher(cwd, store=self.store)
        self._dialogue_lock = asyncio.Lock()
        self._message_tasks: dict[str, asyncio.Task[None]] = {}
        self._action_tasks: set[asyncio.Task[object]] = set()
        self._action_tasks_by_id: dict[str, asyncio.Task[object]] = {}
        self._action_tokens: dict[str, CancellationToken] = {}

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
        return len(pending)

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
                return self.store.transition_run(run.id, "cancelled")
            return run
        await self.cancel_action(run.action_request_id)
        return self.store.get_run(run_id)

    def stop_research_run(self, run_id: str) -> ResearchRun:
        """Request stop for a running Run and signal its active worker."""
        run = self.store.stop_run(run_id)
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
        messages = self.store.list_messages_for_conversation(conversation_id)
        message_values = []
        for message in messages:
            value = message.model_dump(mode="json")
            value["citations"] = [
                item.model_dump(mode="json")
                for item in self.store.citations_for_message(message.id)
            ]
            message_values.append(value)
        task_id = conversation.task_id
        actions = self.store.list_actions(task_id) if task_id else []
        runs = self.store.list_runs(task_id) if task_id else []
        reports = self.store.list_reports(task_id) if task_id else []
        return {
            "conversation": conversation.model_dump(mode="json"),
            "epoch": epoch.model_dump(mode="json"),
            "messages": message_values,
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
                    self.store.bind_intake_task(
                        conversation.id, user.id, intake.research_brief
                    )
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
            async with self._dialogue_lock:
                decision = await self.dialogue.answer(
                    task=task,
                    query=user.content,
                    summary=epoch.summary,
                    messages=messages,
                    passages=passages,
                    run_status=run_status,
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
            raise
        except Exception as error:
            self.store.transition_processing_attempt(
                attempt.id,
                "failed",
                error_code=getattr(error, "code", "PROCESSING_FAILED"),
                error_detail=str(error),
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
