"""Web run adapters and the deprecated single-process compatibility registry."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from pydantic_ai import CancellationToken
from pydantic_ai.exceptions import RunCancelled

from ..config import Settings
from ..continuation import ResearchGate
from ..crawl import CrawlEvent
from ..models import IntelError, utc_now
from ..runner import TaskRunSpec, build_completion_output, run_agent_task
from ..state_store import StateStore
from ..task import activate_task, build_task, load_task
from ..trajectory import JsonlTrajectoryRecorder
from .schemas import RunErrorView, RunEvent, RunStatus, RunView, UsageView

Runner = Callable[..., Awaitable[Any]]
TERMINAL_STATUSES = {
    "completed_sufficient",
    "completed_with_gaps",
    "failed",
    "cancelled",
}
MAX_RETAINED_EVENTS = 5_000
MAX_RETAINED_RUNS = 100


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
    """Deprecated in-memory implementation kept for old direct callers.

    The application installs :class:`LegacyRunAdapter` instead, so Web routes
    use the persistent ResearchRun lifecycle and StateStore events.
    """

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
        self.store = StateStore(cwd)
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
            self._persist(state)
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
        self._persist(state)
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
            self._persist(state)
            self._prune_terminal()
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
        if len(state.events) > MAX_RETAINED_EVENTS:
            del state.events[: len(state.events) - MAX_RETAINED_EVENTS]
        if state.run_id in self._runs and (
            event_type
            in {
                "run.started",
                "run.completed",
                "run.failed",
                "run.cancelled",
                "task.updated",
            }
            or len(state.events) % 100 == 0
        ):
            self._persist(state)
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
            state = self._load(run_id)
            if state is None:
                raise IntelError("NOT_FOUND", f"运行不存在: {run_id}")
            self._runs[run_id] = state
        return state

    def _persist(self, state: _RunState) -> None:
        self.store.save_web_run_projection(
            state.run_id,
            {
                "run_id": state.run_id,
                "spec": state.spec.model_dump(mode="json"),
                "status": state.status,
                "task_id": state.task_id,
                "created_at": state.created_at,
                "started_at": state.started_at,
                "finished_at": state.finished_at,
                "result": state.result,
                "error": state.error.model_dump(mode="json")
                if state.error
                else None,
                "usage": state.usage.model_dump(mode="json")
                if state.usage
                else None,
                "events": [
                    event.model_dump(mode="json") for event in state.events
                ],
            },
        )

    def _load(self, run_id: str) -> _RunState | None:
        raw = self.store.load_web_run_projection(run_id)
        if raw is None:
            return None
        raw = cast(dict[str, Any], raw)
        try:
            state = _RunState(
                run_id=run_id,
                spec=TaskRunSpec.model_validate(raw["spec"]),
                status=raw["status"],
                task_id=raw.get("task_id"),
                created_at=raw["created_at"],
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
                result=raw.get("result"),
                error=(
                    RunErrorView.model_validate(raw["error"])
                    if raw.get("error")
                    else None
                ),
                usage=(
                    UsageView.model_validate(raw["usage"])
                    if raw.get("usage")
                    else None
                ),
                events=[
                    RunEvent.model_validate(item)
                    for item in raw.get("events", [])
                ],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise IntelError(
                "STORAGE_CORRUPT", f"运行记录格式无效: {run_id}"
            ) from error
        return state

    def _prune_terminal(self) -> None:
        terminal = [
            state
            for state in self._runs.values()
            if state.status in TERMINAL_STATUSES
        ]
        for state in sorted(terminal, key=lambda item: item.finished_at or "")[
            :-MAX_RETAINED_RUNS
        ]:
            self._runs.pop(state.run_id, None)

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


class LegacyRunAdapter:
    """Expose the old topic-only Web contract over persistent ResearchRun."""

    def __init__(
        self,
        cwd: Path,
        settings: Settings,
        *,
        runtime: Any,
        gate: ResearchGate | None = None,
    ) -> None:
        self.cwd = cwd
        self.settings = settings
        self.runtime = runtime
        self.store = runtime.store
        self.gate = gate or ResearchGate()

    async def create(self, spec: TaskRunSpec) -> RunView:
        if self.gate.locked or self.store.active_runs():
            raise IntelError(
                "RUN_ALREADY_ACTIVE",
                "已有研究任务正在运行，请等待或先停止该任务",
            )
        questions = spec.questions or [
            f"{spec.topic}的现状、发展与趋势是什么？",
            f"{spec.topic}的主要参与者、证据与风险是什么？",
        ]
        deep_crawl = spec.report_depth == "deep" or (
            spec.deep_crawl
            if spec.deep_crawl is not None
            else self.settings.crawl.enabled_by_default
        )
        task = build_task(
            spec.topic,
            questions,
            spec.criteria,
            deep_crawl=deep_crawl,
            objective=spec.objective,
            scope=spec.scope,
            report_depth=spec.report_depth,
        )
        run = self.store.create_legacy_run(
            task,
            input_snapshot={
                "source": "legacy_api",
                "spec": spec.model_dump(mode="json"),
            },
        )
        activate_task(self.cwd, task.id)
        if self.runtime.initial is not None:
            loop = asyncio.get_running_loop()
            trace_path = self.cwd / "data" / "runs" / run.id / "trace.jsonl"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            recorder = StreamTrajectoryRecorder(
                trace_path,
                lambda envelope: self._schedule_trajectory_event(
                    loop, run.id, task.id, envelope
                ),
            )
            self.runtime.schedule_legacy_run(
                run.id,
                on_event=lambda event: self._record_native_event(
                    run.id, task.id, event
                ),
                recorder=recorder,
            )
        return self._view(run)

    def get(self, run_id: str) -> RunView:
        return self._view(self.store.get_run(run_id))

    def events(self, run_id: str, after_id: int = 0) -> list[RunEvent]:
        return [
            projected
            for event in self.store.events_after_run(run_id, after_id)
            if (projected := self._project_event(event)) is not None
        ]

    async def subscribe(
        self, run_id: str, after_id: int = 0
    ) -> AsyncIterator[RunEvent | None]:
        cursor = after_id
        last_heartbeat = asyncio.get_running_loop().time()
        while True:
            pending = self.events(run_id, cursor)
            for event in pending:
                cursor = event.id
                yield event
            run = self.store.get_run(run_id)
            if run.status in {
                "succeeded",
                "failed",
                "cancelled",
                "stopped",
                "interrupted",
            }:
                return
            await asyncio.sleep(0.25)
            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 15:
                last_heartbeat = now
                yield None

    async def cancel(self, run_id: str) -> RunView:
        run = self.store.get_run(run_id)
        if run.status == "queued":
            await self.runtime.cancel_research_run(run_id)
        elif run.status == "running":
            self.runtime.stop_research_run(run_id)
            await self.runtime.wait_research_run(run_id)
        return self.get(run_id)

    async def wait(self, run_id: str) -> None:
        await self.runtime.wait_research_run(run_id)

    async def _record_native_event(
        self, run_id: str, task_id: str, event: object
    ) -> None:
        projected = _project_native_event(event)
        if projected is None:
            return
        event_type, data = projected
        self.store.append_event(
            task_id,
            event_type,
            data,
            research_run_id=run_id,
        )

    def _schedule_trajectory_event(
        self,
        loop: asyncio.AbstractEventLoop,
        run_id: str,
        task_id: str,
        envelope: dict[str, Any],
    ) -> None:
        async def persist() -> None:
            self.store.append_event(
                task_id,
                f"trajectory.{envelope['event_type']}",
                envelope,
                research_run_id=run_id,
            )

        try:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(persist()))
        except RuntimeError:
            return

    def _view(self, run: Any) -> RunView:
        status: RunStatus
        if run.status == "succeeded":
            status = (
                "completed_with_gaps"
                if run.outcome == "with_gaps"
                else "completed_sufficient"
            )
        elif run.status in {"stopped", "interrupted", "cancelled"}:
            status = "cancelled"
        elif run.status == "stopping":
            status = "running"
        else:
            status = run.status
        result: str | None = None
        if run.status == "succeeded":
            try:
                result = build_completion_output(
                    self.cwd, load_task(self.cwd, run.task_id)
                )
            except IntelError:
                result = None
        error = (
            RunErrorView(code="RUN_FAILED", message=run.error)
            if run.error
            else None
        )
        usage = self._usage(run.id)
        return RunView(
            run_id=run.id,
            status=status,
            task_id=run.task_id,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.completed_at,
            result=result,
            error=error,
            usage=usage,
        )

    def _usage(self, run_id: str) -> UsageView | None:
        path = self.cwd / "data" / "runs" / run_id / "trace.jsonl"
        if not path.exists():
            return None
        try:
            for line in reversed(
                path.read_text(encoding="utf-8").splitlines()
            ):
                envelope = json.loads(line)
                if envelope.get("event_type") != "run_finished":
                    continue
                payload = envelope.get("payload", {})
                return UsageView(
                    requests=int(payload.get("requests", 0)),
                    tool_calls=int(payload.get("tool_calls", 0)),
                    input_tokens=int(payload.get("input_tokens", 0)),
                    output_tokens=int(payload.get("output_tokens", 0)),
                    total_tokens=int(payload.get("total_tokens", 0)),
                )
        except (OSError, TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _project_event(event: Any) -> RunEvent | None:
        mapping = {
            "run.running": "run.started",
            "run.succeeded": "run.completed",
            "run.failed": "run.failed",
            "run.cancelled": "run.cancelled",
            "run.stopped": "run.cancelled",
            "run.interrupted": "run.cancelled",
        }
        event_type = mapping.get(event.event_type) or event.event_type
        if event.event_type in {"run.queued", "task.created", "run.stopping"}:
            return None
        return RunEvent(
            id=event.sequence,
            type=event_type,
            timestamp=event.created_at,
            data=event.data,
        )
