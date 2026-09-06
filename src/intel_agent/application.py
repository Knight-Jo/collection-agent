"""Application: composition root and single background-execution owner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .contracts.errors import DomainError
from .contracts.research import ResearchResult, ResearchTask
from .conversation import ConversationService
from .orchestration import ResearchOrchestrator
from .runtime.config import ResearchSettings
from .runtime.events import EventBus
from .storage.materials import MaterialStore
from .storage.tasks import TaskStore

Runner = Callable[[str], Awaitable[None]]


class ResearchApplication:
    """Owns running tasks and dispatches execution by task kind.

    The application is the single owner of background execution: it registers
    every in-flight task, bounds concurrency, and provides cancel/resume/
    recovery. API and schedulers only submit persisted work; they never create
    unmanaged background tasks.
    """

    def __init__(
        self,
        store: MaterialStore,
        task_store: TaskStore,
        orchestrator: ResearchOrchestrator,
        settings: ResearchSettings,
        conversation_service: ConversationService | None = None,
        event_bus: EventBus | None = None,
        concurrency: int = 4,
    ) -> None:
        self.store = store
        self.task_store = task_store
        self.orchestrator = orchestrator
        self.settings = settings
        self.conversations = conversation_service
        self.events = event_bus
        self._sem = asyncio.Semaphore(concurrency)
        self._running: dict[str, asyncio.Task] = {}
        self._runners: dict[str, Runner] = {}
        self._runners["research"] = self._run_research
        # Workspace services, wired by bootstrap.
        self.search_settings: Any = None
        self.monitoring: Any = None
        self.factcheck: Any = None
        self.media: Any = None
        self.library: Any = None
        self.material_store = store
        self.settings_store: Any = None
        self.resource_store: Any = None

    # --- runner registry ----------------------------------------------------

    def register_runner(self, kind: str, runner: Runner) -> None:
        self._runners[kind] = runner

    # --- background execution owner -----------------------------------------

    def launch(self, task_id: str, runner: Runner) -> None:
        async def _guarded() -> None:
            async with self._sem:
                try:
                    await runner(task_id)
                finally:
                    self._running.pop(task_id, None)

        self._running[task_id] = asyncio.create_task(_guarded())

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running

    def request_cancel(self, task_id: str) -> None:
        self.task_store.request_cancel(task_id)
        task = self._running.get(task_id)
        if task is not None:
            task.cancel()

    async def resume(self, task_id: str) -> None:
        task = self.task_store.get_task(task_id)
        if task.status not in ("interrupted", "failed", "cancelled"):
            raise DomainError(
                "CONFLICT", f"cannot resume task in state {task.status}"
            )
        runner = self._runners.get(task.kind)
        if runner is None:
            raise DomainError(
                "NOT_FOUND", f"no runner for task kind {task.kind}"
            )
        self.task_store.update_task_status(task_id, "queued", error=None)
        self.launch(task_id, runner)

    async def recover(self) -> None:
        """Re-register queued work and interrupt orphaned running tasks."""
        self._running.clear()
        for task_id in self._orphaned_running():
            self.task_store.update_task_status(
                task_id,
                "interrupted",
                error={
                    "code": "INTERRUPTED",
                    "message": "process restarted",
                    "stage": "task",
                    "retryable": True,
                },
            )
        for task_id in self._queued():
            task = self.task_store.get_task(task_id)
            runner = self._runners.get(task.kind)
            if runner is not None:
                self.launch(task_id, runner)

    def _orphaned_running(self) -> list[str]:
        return self.task_store.list_task_ids_by_status("running")

    def _queued(self) -> list[str]:
        return self.task_store.list_task_ids_by_status("queued")

    # --- research lifecycle (CLI surface) -----------------------------------

    def submit(self, question: str) -> ResearchTask:
        task = self.task_store.create_task(
            question,
            kind="research",
            deadline_seconds=self.settings.research.deadline_seconds,
        )
        self.launch(task.task_id, self._run_research)
        return task

    async def _run_research(self, task_id: str) -> None:
        task = self.task_store.get_task(task_id)
        await self.orchestrator.run_task(task)

    def cancel(self, task_id: str) -> None:
        self.request_cancel(task_id)

    async def wait(self, task_id: str) -> ResearchResult:
        task = self._running.get(task_id)
        if task is None:
            raise DomainError("NOT_FOUND", f"task not running: {task_id}")
        result = await task
        return result  # type: ignore[return-value]

    def status(self, task_id: str) -> ResearchTask:
        return self.task_store.get_task(task_id)

    async def close(self) -> None:
        for task in self._running.values():
            task.cancel()
        if self._running:
            await asyncio.gather(
                *self._running.values(), return_exceptions=True
            )
        self._running.clear()
        if self.conversations is not None:
            await self.conversations.close()
        self.store.close()
