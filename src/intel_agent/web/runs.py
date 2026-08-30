"""Compatibility adapter for the topic-only Web run contract."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from ..config import Settings
from ..continuation import ResearchGate
from ..crawl import CrawlEvent
from ..models import IntelError
from ..runner import TaskRunSpec, build_completion_output
from ..task import activate_task, build_task, load_task
from ..trajectory import JsonlTrajectoryRecorder
from .schemas import RunErrorView, RunEvent, RunStatus, RunView, UsageView


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
