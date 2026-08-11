"""Single-process run registry and safe event projection for the Web API."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import (
    CancellationToken,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
)
from pydantic_ai.exceptions import RunCancelled

from ..config import Settings
from ..crawl import CrawlEvent
from ..models import IntelError, utc_now
from ..runner import TaskRunSpec, run_agent_task
from ..task import load_task
from .schemas import RunErrorView, RunEvent, RunStatus, RunView, UsageView

Runner = Callable[..., Awaitable[Any]]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class _RunState:
    run_id: str
    spec: TaskRunSpec
    status: RunStatus = "queued"
    task_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    result: str | None = None
    error: RunErrorView | None = None
    usage: UsageView | None = None
    events: list[RunEvent] = field(default_factory=list)
    cancellation_token: CancellationToken = field(
        default_factory=CancellationToken
    )
    task: asyncio.Task[None] | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    last_task_update: str | None = None


class RunRegistry:
    """Own one active agent run while retaining terminal runs for inspection."""

    def __init__(
        self,
        cwd: Path,
        settings: Settings,
        *,
        runner: Runner = run_agent_task,
    ) -> None:
        self.cwd = cwd
        self.settings = settings
        self.runner = runner
        self._runs: dict[str, _RunState] = {}
        self._lock = asyncio.Lock()

    async def create(self, spec: TaskRunSpec) -> RunView:
        async with self._lock:
            if any(
                state.status in {"queued", "running"}
                for state in self._runs.values()
            ):
                raise IntelError(
                    "RUN_ALREADY_ACTIVE",
                    "已有研究任务正在运行，请等待或先停止该任务",
                )
            state = _RunState(run_id=f"run-{uuid.uuid4()}", spec=spec)
            self._runs[state.run_id] = state
            state.task = asyncio.create_task(self._execute(state))
            return self._view(state)

    def get(self, run_id: str) -> RunView:
        return self._view(self._state(run_id))

    def events(self, run_id: str, after_id: int = 0) -> list[RunEvent]:
        return [
            event
            for event in self._state(run_id).events
            if event.id > after_id
        ]

    async def subscribe(
        self, run_id: str, after_id: int = 0
    ) -> AsyncIterator[RunEvent | None]:
        state = self._state(run_id)
        cursor = after_id
        while True:
            pending = [event for event in state.events if event.id > cursor]
            for event in pending:
                cursor = event.id
                yield event
            if state.status in TERMINAL_STATUSES:
                return
            try:
                async with state.condition:
                    await asyncio.wait_for(state.condition.wait(), timeout=15)
            except TimeoutError:
                yield None

    def cancel(self, run_id: str) -> RunView:
        state = self._state(run_id)
        state.cancellation_token.cancel()
        return self._view(state)

    async def wait(self, run_id: str) -> None:
        task = self._state(run_id).task
        if task is not None:
            await task

    async def _execute(self, state: _RunState) -> None:
        state.status = "running"
        state.started_at = utc_now()
        previous_task_id = self._active_task_id()
        await self._append(state, "run.started", {"topic": state.spec.topic})

        async def on_event(event: object) -> None:
            projected = _project_native_event(event)
            if projected is not None:
                await self._append(state, *projected)
            current_task_id = self._active_task_id()
            if state.task_id is None and current_task_id != previous_task_id:
                state.task_id = current_task_id
            if state.task_id is not None:
                task = load_task(self.cwd, state.task_id)
                if task.updated_at != state.last_task_update:
                    state.last_task_update = task.updated_at
                    await self._append(
                        state,
                        "task.updated",
                        {"task_id": task.id, "stage": task.stage},
                    )

        try:
            result = await self.runner(
                self.cwd,
                self.settings,
                state.spec,
                on_event=on_event,
                cancellation_token=state.cancellation_token,
            )
            if state.cancellation_token.cancelled:
                state.status = "cancelled"
                await self._append(state, "run.cancelled", {})
            else:
                state.status = "completed"
                state.result = str(result.output)
                usage = result.usage
                state.usage = UsageView(
                    requests=usage.requests,
                    tool_calls=usage.tool_calls,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                )
                await self._append(
                    state,
                    "run.completed",
                    {"task_id": state.task_id, "result": state.result},
                )
        except RunCancelled:
            state.status = "cancelled"
            await self._append(state, "run.cancelled", {})
        except Exception as error:
            state.status = "failed"
            code = (
                error.code if isinstance(error, IntelError) else "RUN_FAILED"
            )
            state.error = RunErrorView(code=code, message=str(error))
            await self._append(
                state, "run.failed", {"code": code, "message": str(error)}
            )
        finally:
            state.finished_at = utc_now()
            async with state.condition:
                state.condition.notify_all()

    async def _append(
        self, state: _RunState, event_type: str, data: dict[str, Any]
    ) -> None:
        state.events.append(
            RunEvent(
                id=len(state.events) + 1,
                type=event_type,
                timestamp=utc_now(),
                data=data,
            )
        )
        async with state.condition:
            state.condition.notify_all()

    def _active_task_id(self) -> str | None:
        try:
            return load_task(self.cwd).id
        except IntelError as error:
            if error.code == "NOT_FOUND":
                return None
            raise

    def _state(self, run_id: str) -> _RunState:
        state = self._runs.get(run_id)
        if state is None:
            raise IntelError("NOT_FOUND", f"运行不存在: {run_id}")
        return state

    @staticmethod
    def _view(state: _RunState) -> RunView:
        return RunView(
            run_id=state.run_id,
            status=state.status,
            task_id=state.task_id,
            created_at=state.created_at,
            started_at=state.started_at,
            finished_at=state.finished_at,
            result=state.result,
            error=state.error,
            usage=state.usage,
        )


def _project_native_event(
    event: object,
) -> tuple[str, dict[str, Any]] | None:
    if isinstance(event, CrawlEvent):
        return event.type, event.data
    if isinstance(event, FunctionToolCallEvent):
        return (
            "tool.started",
            {
                "tool_name": event.part.tool_name,
                "tool_call_id": event.tool_call_id,
            },
        )
    if isinstance(event, FunctionToolResultEvent):
        return (
            "tool.completed",
            {
                "tool_name": event.part.tool_name,
                "tool_call_id": event.tool_call_id,
            },
        )
    return None
