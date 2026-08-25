"""Single-process run registry and safe event projection for the Web API."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import CancellationToken
from pydantic_ai.exceptions import RunCancelled

from ..config import Settings
from ..continuation import ResearchGate
from ..crawl import CrawlEvent
from ..models import IntelError, utc_now
from ..runner import TaskRunSpec, run_agent_task
from ..task import load_task
from ..trajectory import JsonlTrajectoryRecorder
from .schemas import RunErrorView, RunEvent, RunStatus, RunView, UsageView

Runner = Callable[..., Awaitable[Any]]
TERMINAL_STATUSES = {
    "completed_sufficient",
    "completed_with_gaps",
    "failed",
    "cancelled",
}


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
        gate: ResearchGate | None = None,
    ) -> None:
        self.cwd = cwd
        self.settings = settings
        self.runner = runner
        self.gate = gate or ResearchGate()
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
            run_id = f"run-{uuid.uuid4()}"
            if not await self.gate.try_acquire(run_id):
                raise IntelError(
                    "RUN_ALREADY_ACTIVE",
                    "已有研究任务正在运行，请等待或先停止该任务",
                )
            state = _RunState(run_id=run_id, spec=spec)
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
        loop = asyncio.get_running_loop()
        recorder = _make_stream_recorder(self, state, loop)

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
                recorder=recorder,
            )
            if state.cancellation_token.cancelled:
                state.status = "cancelled"
                await self._append(state, "run.cancelled", {})
            else:
                task = load_task(self.cwd, state.task_id)
                if task.stage != "done":
                    state.status = "failed"
                    state.error = RunErrorView(
                        code="RUN_INCOMPLETE",
                        message="模型运行已结束，但研究任务未进入 done 阶段",
                    )
                    await self._append(
                        state,
                        "run.failed",
                        {
                            "code": state.error.code,
                            "message": state.error.message,
                        },
                    )
                    return
                state.status = (
                    "completed_with_gaps"
                    if task.completion_status == "with_gaps"
                    else "completed_sufficient"
                )
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
            recorder.close()
            state.finished_at = utc_now()
            self.gate.release(state.run_id)
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
    return None


class StreamTrajectoryRecorder(JsonlTrajectoryRecorder):
    """Persist a run trajectory to disk and mirror envelopes to the SSE stream."""

    def __init__(
        self, path: Path, on_envelope: Callable[[dict], None]
    ) -> None:
        super().__init__(path)
        self._on_envelope = on_envelope

    def _on_record(self, envelope: dict) -> None:
        self._on_envelope(envelope)


def _make_stream_recorder(
    registry: RunRegistry, state: _RunState, loop: asyncio.AbstractEventLoop
) -> StreamTrajectoryRecorder:
    """Build the per-run recorder: file sink + SSE projection.

    Trajectory events arrive on both the async loop (runner/agent) and worker
    threads (sync tools co-emitting state changes), so the SSE append is
    marshalled onto the loop with ``run_coroutine_threadsafe``.
    """
    path = (
        registry.cwd / "data" / "runs" / state.run_id / "trace.jsonl"
    ).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    def on_envelope(envelope: dict) -> None:
        asyncio.run_coroutine_threadsafe(
            registry._append(  # noqa: SLF001
                state,
                f"trajectory.{envelope['event_type']}",
                envelope,
            ),
            loop,
        )

    return StreamTrajectoryRecorder(path, on_envelope)
