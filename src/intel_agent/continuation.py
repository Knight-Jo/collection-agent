"""Restricted continuation of an existing local research task."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from pydantic_ai import CancellationToken
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.usage import RunUsage, UsageLimits

from .agent import build_agent, build_deps
from .config import Settings
from .coverage import latest_coverage
from .models import (
    ActionRequest,
    AssetRevisionRef,
    CollectionState,
    CommittedAssetType,
    IntelError,
    ResearchBrief,
    ResearchRun,
)
from .runner import (
    ActionTrace,
    TaskRunSpec,
    _close_pending_actions,
    _translate_stream_event,
    run_agent_task,
)
from .state_store import StateStore
from .task import activate_task, load_task, save_task
from .trajectory import (
    JsonlTrajectoryRecorder,
    ModelCallPayload,
    RunFinishedPayload,
    RunStartedPayload,
    TrajectoryRecorder,
    bind_context,
    emit,
    make_event,
    restore_context,
)
from .web.views import get_task_view

ALLOWED_CONTINUATION_TOOLS = {
    "web_search",
    "github_search",
    "academic_search",
    "news_search",
    "crawl_collect",
    "web_fetch",
    "document_search",
    "document_read",
    "fact_save",
    "fact_supersede",
    "evidence_save",
    "evidence_audit",
    "evidence_conflict_create",
    "evidence_conflict_resolve",
    "coverage_eval",
}

CONTINUATION_PROMPT = """\
你正在续研一个已经存在的公开信息调研任务。只能围绕用户给定范围补充搜索、抓取、
事实、证据、审核、冲突与覆盖评估。不得创建新任务，不得生成或修改报告，不得更改
任务主题和关键问题。完成这一轮明确范围后立即停止，并简述新增材料与仍存缺口。
"""


async def _run_continuation_agent(
    agent,
    prompt: str,
    *,
    deps,
    limits: UsageLimits,
    usage: RunUsage,
    cancellation_token: CancellationToken,
    cwd: Path,
    model_name: str,
):
    """Run one continuation while translating native stream events."""
    if not hasattr(agent, "run_stream_events"):
        return await agent.run(
            prompt,
            deps=deps,
            usage_limits=limits,
            cancellation_token=cancellation_token,
        )

    actions: dict[str, ActionTrace] = {}
    requests_seen = 0
    request_started = time.monotonic()
    input_before = 0
    output_before = 0

    def close_model_call(finish_reason: str) -> None:
        if requests_seen == 0:
            return
        emit(
            make_event(
                "model_call",
                "model",
                ModelCallPayload(
                    request_index=requests_seen,
                    model=model_name,
                    input_tokens=usage.input_tokens - input_before,
                    output_tokens=usage.output_tokens - output_before,
                    finish_reason=finish_reason,
                    latency_ms=max(
                        0, int((time.monotonic() - request_started) * 1000)
                    ),
                ),
                layer="technical",
            )
        )

    finish_reason = "aborted"
    try:
        async with agent.run_stream_events(
            prompt,
            deps=deps,
            usage_limits=limits,
            usage=usage,
            cancellation_token=cancellation_token,
        ) as events:
            async for event in events:
                if usage.requests > requests_seen:
                    if requests_seen:
                        close_model_call("tool_call")
                    requests_seen = usage.requests
                    request_started = time.monotonic()
                    input_before = usage.input_tokens
                    output_before = usage.output_tokens
                _translate_stream_event(event, cwd, actions)
            result = events.result
        if result is None:
            raise RuntimeError("Continuation run completed without a result")
        finish_reason = "stop"
        return result
    finally:
        close_model_call(finish_reason)
        _close_pending_actions(actions)


def _ensure_research_run_trace(
    recorder: TrajectoryRecorder,
    run: ResearchRun,
    *,
    cwd: Path,
) -> None:
    """Add lifecycle events when execution ended before the agent started."""
    if recorder.has_run_started and recorder.has_run_finished:
        return
    task = load_task(cwd, run.task_id)
    binding = bind_context(run.id, recorder, task_id=run.task_id)
    try:
        if not recorder.has_run_started:
            emit(
                make_event(
                    "run_started",
                    "system",
                    RunStartedPayload(
                        topic=task.topic,
                        objective=task.objective,
                        questions=[
                            question.text for question in task.questions
                        ],
                        criteria=task.criteria.model_dump(mode="json"),
                        report_depth=task.report_depth,
                    ),
                    layer="evaluation",
                )
            )
        if not recorder.has_run_finished:
            status = (
                "succeeded"
                if run.status == "succeeded"
                else "cancelled"
                if run.status in {"cancelled", "stopped", "stopping"}
                else "failed"
            )
            emit(
                make_event(
                    "run_finished",
                    "system",
                    RunFinishedPayload(
                        status=status,
                        stage=task.stage,
                        error_code=(
                            "ResearchRunFailed" if status == "failed" else None
                        ),
                        error_summary=(
                            "run aborted; inspect run.log"
                            if status == "failed"
                            else "run cancelled"
                            if status == "cancelled"
                            else None
                        ),
                    ),
                    layer="evaluation",
                )
            )
    finally:
        restore_context(binding)


class ResearchGate:
    """Allow one research execution in the single-user workspace."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: str | None = None

    @property
    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self, owner: str) -> None:
        await self._lock.acquire()
        self._owner = owner

    async def try_acquire(self, owner: str) -> bool:
        if self._lock.locked():
            return False
        await self.acquire(owner)
        return True

    def release(self, owner: str) -> None:
        if self._owner != owner:
            raise RuntimeError("research gate owner mismatch")
        self._owner = None
        self._lock.release()


class ContinuationRunner:
    """Run one explicitly requested continuation and commit its asset delta."""

    def __init__(
        self,
        cwd: Path,
        settings: Settings | None = None,
        *,
        store: StateStore | None = None,
        gate: ResearchGate | None = None,
    ) -> None:
        self.cwd = cwd
        self.settings = settings or Settings()
        self.store = store or StateStore(cwd)
        self.gate = gate or ResearchGate()

    async def run_initial(
        self,
        run: ResearchRun,
        brief: ResearchBrief,
        cancellation_token: CancellationToken | None = None,
        *,
        on_event: Callable[[object], Awaitable[None]] | None = None,
        recorder: TrajectoryRecorder | None = None,
    ) -> ResearchRun:
        """Execute the queued initial run created by intake."""
        active_recorder = recorder or JsonlTrajectoryRecorder(
            self.cwd / "data" / "runs" / run.id / "trace.jsonl"
        )
        token = cancellation_token or CancellationToken()
        if token.cancelled:
            current = self.store.get_run(run.id)
            result = (
                self.store.cancel_run(run.id)
                if current.status == "queued"
                else current
            )
            try:
                _ensure_research_run_trace(
                    active_recorder, result, cwd=self.cwd
                )
            finally:
                active_recorder.close()
            return result
        acquired = False
        try:
            await self.gate.acquire(run.id)
            acquired = True
            if token.cancelled:
                current = self.store.get_run(run.id)
                return (
                    self.store.cancel_run(run.id)
                    if current.status == "queued"
                    else current
                )
            self.store.claim_run(
                run.id,
                phase="planning",
                lease_owner=run.id,
                lease_expires_at=(
                    datetime.now(UTC) + timedelta(minutes=2)
                ).isoformat(),
            )
            self.store.create_search_plan_version(
                run.id,
                {
                    "topic": brief.topic,
                    "objective": brief.objective,
                    "questions": brief.key_questions,
                    "investigation_items": brief.investigation_items,
                    "scope": brief.scope.model_dump(mode="json"),
                },
                trigger_message_id=run.trigger_message_id,
            )
            task = activate_task(self.cwd, run.task_id)
            before = _asset_snapshot(self.cwd, task.id, run.id)
            await run_agent_task(
                self.cwd,
                self.settings,
                TaskRunSpec(
                    topic=brief.topic,
                    objective=brief.objective,
                    questions=brief.key_questions,
                    scope=brief.scope,
                    report_depth=task.report_depth,
                    criteria=task.criteria,
                    deep_crawl=task.deep_crawl,
                ),
                cancellation_token=token,
                bound_task_id=task.id,
                run_id=run.id,
                on_event=on_event,
                recorder=active_recorder,
            )
            if token.cancelled:
                raise asyncio.CancelledError
            added = _asset_snapshot(self.cwd, task.id, run.id) - before
            manifest = _run_manifest(self.cwd, run.id, task.id, added)
            self.store.finish_run(
                run.id,
                expected_input_version=run.input_committed_state_version,
                staged_manifest=manifest,
                outcome="committed" if manifest else "no_progress",
            )
            return self.store.get_run(run.id)
        except (RunCancelled, asyncio.CancelledError):
            current = self.store.get_run(run.id)
            if current.status == "queued":
                return self.store.cancel_run(run.id)
            if current.status == "running":
                self.store.stop_run(run.id)
            return self.store.finish_stop(run.id)
        except Exception as error:
            current = self.store.get_run(run.id)
            if current.status == "running":
                return self.store.transition_run(
                    run.id, "failed", error=str(error)
                )
            return current
        finally:
            try:
                _ensure_research_run_trace(
                    active_recorder,
                    self.store.get_run(run.id),
                    cwd=self.cwd,
                )
            finally:
                active_recorder.close()
                if acquired:
                    self.gate.release(run.id)

    async def run(
        self,
        action: ActionRequest,
        cancellation_token: CancellationToken | None = None,
        *,
        recorder: TrajectoryRecorder | None = None,
    ) -> ActionRequest:
        """Execute one queued continuation and return its terminal action."""
        token = cancellation_token or CancellationToken()
        owner = f"action:{action.id}"
        await self.gate.acquire(owner)
        run: ResearchRun | None = None
        saved_collection: CollectionState | None = None
        active_recorder: TrajectoryRecorder | None = None
        trace_binding = None
        trace_started = time.monotonic()
        terminal_status = "failed"
        terminal_error_code: str | None = None
        terminal_error_summary: str | None = None
        usage = RunUsage()
        try:
            claimed_action, run = self.store.claim_action_run(action.id)
            if run is None:
                return claimed_action
            active_recorder = recorder or JsonlTrajectoryRecorder(
                self.cwd / "data" / "runs" / run.id / "trace.jsonl"
            )
            trace_binding = bind_context(
                run.id, active_recorder, task_id=run.task_id
            )
            task = activate_task(self.cwd, action.task_id)
            if not active_recorder.has_run_started:
                emit(
                    make_event(
                        "run_started",
                        "system",
                        RunStartedPayload(
                            topic=task.topic,
                            objective=task.objective,
                            questions=[
                                question.text for question in task.questions
                            ],
                            criteria=task.criteria.model_dump(mode="json"),
                            report_depth=task.report_depth,
                        ),
                        layer="evaluation",
                    )
                )
            if token.cancelled:
                terminal_status = "cancelled"
                terminal_error_code = "RunCancelled"
                terminal_error_summary = "run cancelled"
                self.store.transition_run(run.id, "cancelled")
                return self.store.transition_action(action.id, "cancelled")
            self.store.claim_run(
                run.id,
                phase="collecting",
                lease_owner=run.id,
                lease_expires_at=(
                    datetime.now(UTC) + timedelta(minutes=2)
                ).isoformat(),
            )
            self.store.create_search_plan_version(
                run.id,
                {
                    "action_type": action.action_type,
                    "scope": action.immutable_payload,
                },
                trigger_message_id=action.trigger_message_id,
                action_request_id=action.id,
            )
            saved_collection = task.collection
            save_task(
                self.cwd,
                task.model_copy(
                    update={
                        "collection": task.collection.model_copy(
                            update={
                                "search_attempts": 0,
                                "search_attempts_by_pool": {},
                                "search_stop_reason": None,
                                "fetch_attempts_since_evidence": 0,
                                "stop_reason": None,
                            }
                        )
                    }
                ),
            )
            before = _asset_snapshot(self.cwd, action.task_id, run.id)
            agent = build_agent(
                self.settings,
                system_prompt=CONTINUATION_PROMPT,
                allowed_tools=ALLOWED_CONTINUATION_TOOLS,
            )
            deps = build_deps(
                self.cwd,
                self.settings,
                deep_crawl=task.deep_crawl,
                task_id=action.task_id,
                run_id=run.id,
            )
            prompt = (
                "继续当前任务，严格限定在以下用户请求范围：\n"
                + json.dumps(action.immutable_payload, ensure_ascii=False)
            )
            await _run_continuation_agent(
                agent,
                prompt,
                deps=deps,
                limits=UsageLimits(
                    request_limit=self.settings.budgets.request_limit
                ),
                usage=usage,
                cancellation_token=token,
                cwd=self.cwd,
                model_name=self.settings.model.name,
            )
            if token.cancelled:
                raise asyncio.CancelledError
            after = _asset_snapshot(self.cwd, action.task_id, run.id)
            added = after - before
            manifest = _run_manifest(self.cwd, run.id, action.task_id, added)
            self.store.finish_run(
                run.id,
                expected_input_version=run.input_committed_state_version,
                staged_manifest=manifest,
                outcome="committed" if manifest else "no_progress",
            )
            terminal_status = "succeeded"
            return self.store.get_action(action.id)
        except (RunCancelled, asyncio.CancelledError):
            terminal_status = "cancelled"
            terminal_error_code = "RunCancelled"
            terminal_error_summary = "run cancelled"
            if run is None:
                return self.store.get_action(action.id)
            current_run = self.store.get_run(run.id)
            if current_run.status == "running":
                self.store.stop_run(run.id)
                self.store.finish_stop(run.id)
            elif current_run.status == "stopping":
                self.store.finish_stop(run.id)
            current_action = self.store.get_action(action.id)
            if current_action.status == "executing":
                return self.store.transition_action(action.id, "cancelled")
            return current_action
        except Exception as error:
            terminal_status = "failed"
            terminal_error_code = type(error).__name__
            terminal_error_summary = "run aborted; inspect run.log"
            if run is None:
                current_action = self.store.get_action(action.id)
                if current_action.status == "executing":
                    return self.store.transition_action(
                        action.id, "failed", error=str(error)
                    )
                return current_action
            current_run = self.store.get_run(run.id)
            if current_run.status == "running":
                self.store.transition_run(run.id, "failed", error=str(error))
            current_action = self.store.get_action(action.id)
            if current_action.status == "executing":
                return self.store.transition_action(
                    action.id, "failed", error=str(error)
                )
            return current_action
        finally:
            try:
                if saved_collection is not None and run is not None:
                    latest = load_task(self.cwd, action.task_id)
                    restored = saved_collection.model_copy(
                        update={
                            "evidence_count": latest.collection.evidence_count
                        }
                    )
                    save_task(
                        self.cwd,
                        latest.model_copy(update={"collection": restored}),
                    )
                if (
                    active_recorder is not None
                    and run is not None
                    and not active_recorder.has_run_finished
                ):
                    latest_task = load_task(self.cwd, run.task_id)
                    coverage = latest_coverage(self.cwd, run.task_id)
                    emit(
                        make_event(
                            "run_finished",
                            "system",
                            RunFinishedPayload(
                                status=terminal_status,
                                stage=latest_task.stage,
                                requests=usage.requests,
                                tool_calls=usage.tool_calls,
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                total_tokens=usage.total_tokens,
                                elapsed_ms=max(
                                    0,
                                    int(
                                        (time.monotonic() - trace_started)
                                        * 1000
                                    ),
                                ),
                                error_code=terminal_error_code,
                                error_summary=terminal_error_summary,
                                final_coverage=(
                                    {
                                        "gap_score": coverage.gap_score,
                                        "level": coverage.level,
                                    }
                                    if coverage is not None
                                    else {}
                                ),
                            ),
                            layer="evaluation",
                        )
                    )
            finally:
                try:
                    if trace_binding is not None:
                        restore_context(trace_binding)
                finally:
                    try:
                        if active_recorder is not None:
                            active_recorder.close()
                    finally:
                        self.gate.release(owner)


def _asset_snapshot(
    cwd: Path, task_id: str, run_id: str | None = None
) -> set[tuple[CommittedAssetType, str]]:
    assets: set[tuple[CommittedAssetType, str]] = set()
    if run_id is not None:
        store = StateStore(cwd)
        try:
            workspace = store.run_view(run_id)
        except IntelError as error:
            if error.code != "WORKSPACE_CLOSED":
                raise
            workspace = None
        if workspace is not None:
            assets.update(
                {
                    (
                        cast(CommittedAssetType, item.asset_type),
                        item.logical_id,
                    )
                    for item in workspace.staged_revisions
                }
            )
    view = get_task_view(cwd, task_id)
    assets.update(
        {
            ("document", resource.document_id)
            for resource in view.resources
            if resource.document_id is not None
        }
    )
    for question in view.questions:
        for fact in question.facts:
            assets.add(("fact", fact.id))
            for evidence in fact.evidence:
                assets.add(("evidence", evidence.id))
                assets.add(("document", evidence.document.id))
    return assets


def _run_manifest(
    cwd: Path,
    run_id: str,
    task_id: str,
    fallback: set[tuple[CommittedAssetType, str]],
) -> list[AssetRevisionRef]:
    """Prefer the durable workspace revisions over legacy JSON discovery."""
    store = StateStore(cwd)
    try:
        staged = store.run_view(run_id).staged_revisions
    except IntelError as error:
        if error.code != "WORKSPACE_CLOSED":
            raise
        staged = []
    revisions = {(item.asset_type, item.logical_id): item for item in staged}
    revisions.update(
        {
            (item.asset_type, item.logical_id): item
            for item in _asset_revisions(task_id, fallback)
        }
    )
    return list(revisions.values())


def _asset_revisions(
    task_id: str,
    assets: set[tuple[CommittedAssetType, str]],
) -> list[AssetRevisionRef]:
    """Convert the JSON task delta into stable references for the run workspace."""
    return [
        AssetRevisionRef(
            asset_type=asset_type,
            logical_id=asset_id,
            revision_id=asset_id,
            content_sha256="",
            task_id=task_id,
        )
        for asset_type, asset_id in sorted(assets)
    ]
