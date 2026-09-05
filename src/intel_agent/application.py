"""ResearchApplication: task lifecycle over the research engine."""

from __future__ import annotations

import asyncio

from .contracts.errors import DomainError
from .contracts.research import ResearchResult, ResearchTask
from .runtime.config import ResearchSettings
from .storage.materials import MaterialStore


class ResearchApplication:
    """Owns running tasks; submit/resume/status/wait/cancel/close."""

    def __init__(
        self,
        store: MaterialStore,
        orchestrator,
        settings: ResearchSettings,
        conversation_service=None,
        event_bus=None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.settings = settings
        self.conversations = conversation_service
        self.events = event_bus
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, question: str) -> ResearchTask:
        task = self.store.create_task(
            question, deadline_seconds=self.settings.research.deadline_seconds
        )
        self._tasks[task.task_id] = asyncio.create_task(
            self.orchestrator.run_task(task)
        )
        return task

    def resume(self, task_id: str) -> ResearchTask:
        task = self.store.get_task(task_id)
        self._tasks[task_id] = asyncio.create_task(
            self.orchestrator.resume(task_id)
        )
        return task

    def cancel(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.cancel()

    async def wait(self, task_id: str) -> ResearchResult:
        task = self._tasks.get(task_id)
        if task is None:
            raise DomainError("NOT_FOUND", f"task not running: {task_id}")
        return await task

    def status(self, task_id: str) -> ResearchTask:
        return self.store.get_task(task_id)

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if self.conversations is not None:
            await self.conversations.close()
        self.store.close()
