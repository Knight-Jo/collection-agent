"""Shared task specification, prompt construction, and streamed agent runner."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import (
    AgentRunResult,
    CancellationToken,
    ModelMessage,
)
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessagesTypeAdapter,
)
from pydantic_ai.usage import RunUsage, UsageLimits

from . import trajectory
from .agent import build_agent, build_deps
from .audit import verified_support_evidence
from .config import Settings
from .coverage import latest_coverage
from .fact import list_active_facts_for_task
from .logging import get_logger
from .models import (
    IntelError,
    IntelTask,
    ReportDepth,
    ResearchScope,
    SufficiencyCriteria,
)
from .reason_rules import derive_reason_codes, reason_summary, snapshot_state
from .state_db import configure_state_db_path
from .task import load_task, parse_time_range
from .trajectory import (
    ActionPayload,
    DecisionPayload,
    ModelCallPayload,
    ObservationPayload,
    RunFinishedPayload,
    RunStartedPayload,
    TrajectoryRecorder,
    emit,
    make_event,
)

EventCallback = Callable[[object], Awaitable[None]]

logger = get_logger(__name__)

_SENSITIVE_KEY_RE = re.compile(
    r"key|token|authorization|cookie|secret|password", re.IGNORECASE
)
ActionTrace = tuple[str | None, float, str | None, str | None]
_MAX_SAME_TARGET_FAILURES = 3
_RESULT_SCALAR_KEYS = {
    "accepted_count",
    "candidate_count",
    "code",
    "count",
    "document_id",
    "engineUsed",
    "evidence_id",
    "fact_id",
    "ok",
    "status",
}


def _redact(value) -> object:
    """Drop credential-like keys from tool arguments before tracing.

    Pydantic AI stores raw model tool args as a JSON string, so a plain dict
    walk would let ``"api_key"`` inside a stringified payload leak unchanged.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
        if isinstance(parsed, dict):
            return json.dumps(_redact(parsed), ensure_ascii=False)
        return value
    if isinstance(value, dict):
        return {
            key: _redact(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY_RE.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _result_summary(value: object) -> dict[str, object]:
    redacted = _redact(value)
    if isinstance(redacted, str):
        try:
            parsed = json.loads(redacted)
        except (json.JSONDecodeError, ValueError):
            parsed = redacted
    else:
        parsed = redacted
    encoded = json.dumps(parsed, ensure_ascii=False, default=str).encode()
    summary: dict[str, object] = {
        "result_type": type(parsed).__name__,
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
    }
    if isinstance(parsed, dict):
        summary.update(
            {
                key: item
                for key, item in parsed.items()
                if key in _RESULT_SCALAR_KEYS
                and isinstance(item, (str, int, float, bool, type(None)))
            }
        )
        error = parsed.get("error")
        errors = parsed.get("errors")
        if (
            not isinstance(error, dict)
            and isinstance(errors, list)
            and errors
            and isinstance(errors[0], dict)
        ):
            error = errors[0]
        if isinstance(error, dict):
            # Failures stay diagnosable from the trace alone (run 059: 65
            # audit failures were only recoverable via run.log greps).
            code = error.get("code")
            message = error.get("message")
            if isinstance(code, str):
                summary["error_code"] = code
            if isinstance(message, str):
                summary["error_message"] = message[:200]
        for key in ("results", "items", "documents", "facts", "evidence"):
            items = parsed.get(key)
            if isinstance(items, list):
                summary["item_count"] = len(items)
                break
    elif isinstance(parsed, list):
        summary["item_count"] = len(parsed)
    return summary


def _tool_failure_target(tool: str, args: object) -> str:
    values = _as_dict(args)
    target_fields = {
        key: values[key]
        for key in (
            "task_id",
            "question_id",
            "investigation_item_id",
            "fact_id",
            "document_id",
            "conflict_id",
            "url",
            "query",
        )
        if key in values
    }
    return f"{tool}:{json.dumps(target_fields, sort_keys=True, ensure_ascii=False)}"


def _business_failure_key(
    event: object, targets: dict[str, str]
) -> tuple[bool, str | None]:
    """Return whether this is a result and its stable business-failure key."""
    if isinstance(event, FunctionToolCallEvent):
        targets[event.tool_call_id] = _tool_failure_target(
            event.part.tool_name, event.part.args
        )
        return False, None
    if not isinstance(event, FunctionToolResultEvent):
        return False, None
    target = targets.pop(
        event.tool_call_id,
        f"{getattr(event.part, 'tool_name', '')}:unknown",
    )
    content = event.content
    if content is None:
        content = getattr(event.part, "content", None)
    summary = _result_summary(content)
    if summary.get("ok") is not False:
        return True, None
    error_code = str(summary.get("error_code", "BUSINESS_ERROR"))
    return True, f"{target}:{error_code}"


def _translate_stream_event(
    event: object,
    cwd: Path,
    actions: dict[str, ActionTrace] | None = None,
) -> None:
    """Translate a native Pydantic AI stream event into trajectory events.

    A model tool call becomes a ``decision`` (reason_source=derived, since the
    model's true reason is unknown) plus the ``action``; the tool result
    becomes the ``observation`` linked by ``action_id``.
    """
    actions = actions if actions is not None else {}
    if isinstance(event, FunctionToolCallEvent):
        tool = event.part.tool_name
        args = _redact(event.part.args)
        identifiers = _as_dict(event.part.args)
        question_id = identifiers.get("question_id")
        investigation_item_id = identifiers.get("investigation_item_id")
        question_id = question_id if isinstance(question_id, str) else None
        investigation_item_id = (
            investigation_item_id
            if isinstance(investigation_item_id, str)
            else None
        )
        state = snapshot_state(cwd)
        reason_codes = derive_reason_codes(tool, state)
        decision_id = emit(
            make_event(
                "decision",
                "model",
                DecisionPayload(
                    decision=tool,
                    reason_codes=reason_codes,
                    reason_source="derived",
                    reason_summary=reason_summary(reason_codes),
                    selected_action={"type": tool, "args": args},
                    state_snapshot=state,
                ),
                layer="business",
                question_id=question_id,
                investigation_item_id=investigation_item_id,
            )
        )
        action_event_id = emit(
            make_event(
                "action",
                "model",
                ActionPayload(
                    action_id=event.tool_call_id,
                    tool=tool,
                    action_type=tool,
                    args=args,
                ),
                layer="technical",
                parent_event_id=decision_id,
                question_id=question_id,
                investigation_item_id=investigation_item_id,
            )
        )
        actions[event.tool_call_id] = (
            action_event_id,
            time.monotonic(),
            question_id,
            investigation_item_id,
        )
    elif isinstance(event, FunctionToolResultEvent):
        action_event_id, started, question_id, investigation_item_id = (
            actions.pop(
                event.tool_call_id, (None, time.monotonic(), None, None)
            )
        )
        content = event.content
        if content is None:
            content = getattr(event.part, "content", None)
        result_summary = _result_summary(content)
        outcome = getattr(event.part, "outcome", "failed")
        if outcome == "success":
            status = "succeeded"
        elif outcome == "denied":
            status = "denied"
        elif outcome == "interrupted":
            status = "interrupted"
        else:
            status = "failed"
        if result_summary.get("ok") is False:
            status = "failed"
        emit(
            make_event(
                "observation",
                "tool",
                ObservationPayload(
                    action_id=event.tool_call_id,
                    status=status,
                    duration_ms=max(
                        0, int((time.monotonic() - started) * 1000)
                    ),
                    result={
                        "tool": getattr(event.part, "tool_name", ""),
                        **result_summary,
                    },
                    error=(
                        None
                        if status == "succeeded"
                        else "tool execution did not succeed"
                    ),
                ),
                layer="technical",
                parent_event_id=action_event_id,
                question_id=question_id,
                investigation_item_id=investigation_item_id,
            )
        )


def _close_pending_actions(actions: dict[str, ActionTrace]) -> None:
    """Close tool calls whose result never arrived before the run ended."""
    for action_id, (
        action_event_id,
        started,
        question_id,
        investigation_item_id,
    ) in actions.items():
        emit(
            make_event(
                "observation",
                "system",
                ObservationPayload(
                    action_id=action_id,
                    status="interrupted",
                    duration_ms=max(
                        0, int((time.monotonic() - started) * 1000)
                    ),
                    error="tool result unavailable because the run ended",
                ),
                layer="technical",
                parent_event_id=action_event_id,
                question_id=question_id,
                investigation_item_id=investigation_item_id,
            )
        )
    actions.clear()


class TaskRunSpec(BaseModel):
    """Validated inputs shared by CLI and Web task runs."""

    topic: str
    objective: str = ""
    questions: list[str] = Field(default_factory=list)
    scope: ResearchScope = Field(default_factory=ResearchScope)
    report_depth: ReportDepth = "standard"
    criteria: SufficiencyCriteria = Field(default_factory=SufficiencyCriteria)
    deep_crawl: bool | None = None
    max_requests: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("主题不能为空")
        return value

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        return value.strip()

    @field_validator("questions")
    @classmethod
    def normalize_questions(cls, value: list[str]) -> list[str]:
        questions = list(
            dict.fromkeys(item.strip() for item in value if item.strip())
        )
        if len(questions) > 6:
            raise ValueError("用户关键问题数量不能超过 6 个")
        return questions

    @model_validator(mode="after")
    def validate_criteria(self) -> TaskRunSpec:
        if (
            self.criteria.min_independent_sources < 1
            or self.criteria.min_high_quality_sources < 0
            or self.criteria.recency_days < 1
        ):
            raise ValueError("充分性标准必须是有效正整数")
        return self


def build_task_prompt(spec: TaskRunSpec) -> str:
    """Build the authoritative workflow prompt for a task run."""
    questions = "；".join(spec.questions)
    criteria = spec.criteria
    recency_required = (
        "（强制）"
        if criteria.require_recency
        else "（非强制，仅统计缺口不阻断）"
    )
    deep_crawl_instruction = (
        "web_search 会把候选 URL 加入任务抓取队列；完成检索后调用 crawl_collect(task_id)，"
        "再读取文档、保存证据并评估覆盖。\n"
        if spec.deep_crawl
        else "使用逐页 web_fetch 收集文档。\n"
    )
    question_instruction = (
        "调用 intel_plan 时根据主题、目标和范围生成 3–6 个可独立回答的调研问题；"
        "为每个问题生成 2–4 个 investigation_items，并以问题文本为 key 传入。\n"
        if not spec.questions
        else (
            "调用 intel_plan 时必须且只能使用以下问题，不得新增、删除、合并或改写：\n"
            f"{questions}\n"
        )
    )
    scope_parts = [
        value
        for value in (
            f"时间范围={spec.scope.time_range}"
            if spec.scope.time_range
            else "",
            (
                f"地区={'、'.join(spec.scope.geography)}"
                if spec.scope.geography
                else ""
            ),
            (
                f"语言={'、'.join(spec.scope.languages)}"
                if spec.scope.languages
                else ""
            ),
        )
        if value
    ]
    # Per-question year constraints are parsed deterministically by the task
    # layer; surface them so the model fetches in-scope sources. Task scope
    # wins and is already shown above, so only list parsed question years
    # when no task-level range exists.
    question_time_parts = (
        [
            f"「{question}」时间范围={parsed}"
            for question in spec.questions
            if not spec.scope.time_range
            and (parsed := parse_time_range(question))
        ]
        if spec.questions
        else []
    )
    time_constraint_line = (
        f"；逐问题时间约束：{'；'.join(question_time_parts)}。"
        if question_time_parts
        else "。"
    )
    return (
        f"请围绕主题「{spec.topic}」执行公开信息调研并形成正式报告。\n"
        f"【调研目标】{spec.objective or '围绕主题形成公开信息调研报告'}。\n"
        f"【调研范围】{'；'.join(scope_parts) or '未限定'}{time_constraint_line}报告深度={spec.report_depth}。\n"
        f"【关键问题】{question_instruction}"
        f"【交叉验证标准】corroborated 和 reported 声明均使用 min_independent_sources={criteria.min_independent_sources}，"
        f"min_high_quality_sources={criteria.min_high_quality_sources}，recency_days={criteria.recency_days}，"
        f"require_recency={str(criteria.require_recency).lower()}（{recency_required}）；"
        "primary 声明仅当至少一个审核通过的支持文档来自官方或政府来源时才可由单一来源支持；"
        "含年份的问题必须用该时间范围内的来源取证，范围外或发布时间未知的来源不满足时间要求。\n"
        f"【深度抓取】调用 intel_plan 时必须设置 deep_crawl={str(bool(spec.deep_crawl)).lower()}。"
        f"{deep_crawl_instruction}"
        "【检索纪律】围绕每个问题制定不同查询，优先获取与声明类型匹配的一手或高质量公开来源；"
        "搜索摘要不是证据，already_archived=true 的 URL 不重复抓取。普通检索不足或发现高价值附件时再使用深度抓取。\n"
        "【事实纪律】fact_save 仅保存原子、可核验的命题，并正确选择 primary、corroborated 或 reported；"
        "任务含 investigation_items 时必须传对应 investigation_item_id；"
        "引文必须逐字覆盖主体、动作、范围、时间和数量，partial 时缩窄事实或补充引文。冲突数字分别记录并披露口径。\n"
        "【报告要求】先运行 material_digest 生成材料集合摘要和 1–5 星阅读推荐；正式报告只使用"
        "审核通过的结构化结论，逐问题回答并披露分歧、局限和未回答内容。报告草稿由独立报告智能体撰写。\n"
        "按主流程推进：intel_plan → 定向 web_search/web_fetch → fact_save/evidence_save → "
        "evidence_audit → coverage_eval（充分或 no_progress 停止）→ intel_status(assess) → "
        "material_digest → generate_research_report → intel_status(done)，最后返回报告路径和核心发现。"
    )


def build_completion_output(cwd: Path, task: IntelTask) -> str:
    """Return a deterministic completion summary from persisted evidence."""
    verified_count = sum(
        bool(verified_support_evidence(cwd, fact.id))
        for fact in list_active_facts_for_task(cwd, task.id)
    )
    coverage = latest_coverage(cwd, task.id)
    report_path = task.outputs.report.path if task.outputs.report else "未生成"
    return "\n".join(
        [
            "任务已完成。",
            f"completion_status={task.completion_status}",
            f"报告路径={report_path}",
            f"已验证事实数={verified_count}",
            f"coverage_gap={coverage.gap_score if coverage else '未评估'}",
        ]
    )


async def run_agent_task(
    cwd: Path,
    settings: Settings,
    spec: TaskRunSpec,
    *,
    on_event: EventCallback | None = None,
    cancellation_token: CancellationToken | None = None,
    recorder: TrajectoryRecorder | None = None,
    conversation_path: Path | None = None,
    bound_task_id: str | None = None,
    run_id: str | None = None,
) -> AgentRunResult[str]:
    """Run one task, forwarding native Pydantic AI events and, optionally,
    recording a structured run trajectory (run/step lifecycle, model calls) and
    the full model conversation (per-turn message history) for debugging."""
    configure_state_db_path(cwd, settings.storage.state_db_path)
    trace_started = time.monotonic()
    trace_binding: trajectory.ContextBinding | None = None
    terminal_status = "succeeded"
    terminal_error_code: str | None = None
    terminal_error_summary: str | None = None
    resolved_spec = spec.model_copy(
        update={
            "deep_crawl": (
                spec.report_depth == "deep"
                or (
                    spec.deep_crawl
                    if spec.deep_crawl is not None
                    else settings.crawl.enabled_by_default
                )
            )
        }
    )
    conversation: list[ModelMessage] = []
    tool_specs: list[dict] = []

    def capture_conversation(
        messages: list[ModelMessage], specs: list[dict]
    ) -> None:
        conversation[:] = messages
        tool_specs[:] = specs

    if conversation_path is not None:
        agent = build_agent(
            settings, conversation_capture=capture_conversation
        )
    else:
        agent = build_agent(settings)
    deps_kwargs: dict[str, Any] = {
        "deep_crawl": bool(resolved_spec.deep_crawl)
    }
    if bound_task_id is not None:
        deps_kwargs["task_id"] = bound_task_id
    if run_id is not None:
        deps_kwargs["run_id"] = run_id
    deps = build_deps(cwd, settings, **deps_kwargs)
    for name in ("objective", "scope", "report_depth"):
        if hasattr(deps, name):
            setattr(deps, name, getattr(resolved_spec, name))
    if hasattr(deps, "crawl_event_callback"):
        deps.crawl_event_callback = on_event

    limits = UsageLimits(
        request_limit=min(
            settings.budgets.request_limit,
            resolved_spec.max_requests or settings.budgets.request_limit,
        ),
        tool_calls_limit=resolved_spec.max_tool_calls,
    )
    usage = RunUsage()
    prompt = build_task_prompt(resolved_spec)
    message_history: list[ModelMessage] | None = None

    if recorder is not None:
        trace_binding = trajectory.bind_context(
            run_id or f"run-{uuid.uuid4()}",
            recorder,
            task_id=bound_task_id,
        )
        if not recorder.has_run_started:
            trajectory.emit(
                make_event(
                    "run_started",
                    "system",
                    RunStartedPayload(
                        topic=spec.topic,
                        objective=spec.objective,
                        questions=spec.questions,
                        criteria=spec.criteria.model_dump(mode="json"),
                        report_depth=spec.report_depth,
                    ),
                    layer="evaluation",
                )
            )
    logger.info(
        "run started topic=%s questions=%d",
        spec.topic,
        len(spec.questions),
    )

    step_index = 0
    requests_seen = 0
    final_stage = ""
    call_open = False
    call_started = 0.0
    call_input_before = 0
    call_output_before = 0
    call_tool_calls_before = 0
    action_traces: dict[str, ActionTrace] = {}
    failure_targets: dict[str, str] = {}
    last_failure_key: str | None = None
    same_target_failures = 0

    def close_call(finish_reason: str) -> None:
        nonlocal call_open
        if not call_open:
            return
        latency_ms = int((time.monotonic() - call_started) * 1000)
        input_tokens = usage.input_tokens - call_input_before
        output_tokens = usage.output_tokens - call_output_before
        logger.info(
            "model_call #%d in=%d out=%d latency=%dms finish=%s",
            step_index,
            input_tokens,
            output_tokens,
            latency_ms,
            finish_reason,
        )
        if recorder is not None:
            trajectory.emit(
                make_event(
                    "model_call",
                    "model",
                    ModelCallPayload(
                        request_index=step_index,
                        model=settings.model.name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        finish_reason=finish_reason,
                        latency_ms=latency_ms,
                    ),
                    layer="technical",
                )
            )
        call_open = False

    def open_call() -> None:
        nonlocal step_index, call_open, call_started
        nonlocal call_input_before, call_output_before, call_tool_calls_before
        step_index += 1
        trajectory.set_step_id(step_index)
        call_open = True
        call_started = time.monotonic()
        call_input_before = usage.input_tokens
        call_output_before = usage.output_tokens
        call_tool_calls_before = usage.tool_calls

    def current_finish_reason() -> str:
        return (
            "tool_call"
            if usage.tool_calls > call_tool_calls_before
            else "stop"
        )

    final_result = None
    try:
        while True:
            async with agent.run_stream_events(
                prompt,
                deps=deps,
                message_history=message_history,
                usage_limits=limits,
                usage=usage,
                cancellation_token=cancellation_token,
            ) as events:
                async for event in events:
                    # A model request is the true decision cycle: usage.requests
                    # increments once per request, so a bump here closes the
                    # previous model_call and opens a new step.
                    if usage.requests > requests_seen:
                        requests_seen = usage.requests
                        close_call(current_finish_reason())
                        open_call()
                    if recorder is not None:
                        _translate_stream_event(event, cwd, action_traces)
                    if on_event is not None:
                        await on_event(event)
                    is_result, failure_key = _business_failure_key(
                        event, failure_targets
                    )
                    if not is_result:
                        continue
                    if failure_key is None:
                        last_failure_key = None
                        same_target_failures = 0
                        continue
                    if failure_key == last_failure_key:
                        same_target_failures += 1
                    else:
                        last_failure_key = failure_key
                        same_target_failures = 1
                    if same_target_failures >= _MAX_SAME_TARGET_FAILURES:
                        raise IntelError(
                            "TOOL_FAILURE_LOOP",
                            "同一工具目标连续失败，已停止本轮以避免无效重试",
                        )
                result = events.result
            final_result = result
            if result is None:
                raise RuntimeError("Agent run completed without a result")
            try:
                task = load_task(cwd)
            except IntelError as error:
                if error.code != "NOT_FOUND":
                    raise
                close_call(current_finish_reason())
                return result
            final_stage = task.stage
            if task.stage == "done":
                result.output = build_completion_output(cwd, task)
                close_call("stop")
                return result
            message_history = result.all_messages()
            prompt = (
                "任务尚未完成。不要解释、总结或承诺下一步；"
                "立即依据最新 CONTEXT_SNAPSHOT 的 next_action 调用一个工具继续。"
            )
    except (RunCancelled, asyncio.CancelledError) as error:
        terminal_status = "cancelled"
        terminal_error_code = type(error).__name__
        terminal_error_summary = "run cancelled"
        logger.info("run cancelled")
        raise
    except Exception as error:
        terminal_status = "failed"
        terminal_error_code = type(error).__name__
        terminal_error_summary = "run aborted; inspect run.log"
        logger.exception("run aborted")
        raise
    finally:
        close_call("aborted")
        if recorder is not None:
            _close_pending_actions(action_traces)
        logger.info(
            "run finished stage=%s requests=%d tool_calls=%d tokens=%d",
            final_stage or "none",
            usage.requests,
            usage.tool_calls,
            usage.total_tokens,
        )
        if conversation_path is not None:
            messages = (
                final_result.all_messages()
                if final_result is not None
                else conversation
            )
            if messages:
                conversation_path.parent.mkdir(parents=True, exist_ok=True)
                conversation_path.write_bytes(
                    ModelMessagesTypeAdapter.dump_json(messages, indent=2)
                )
            if tool_specs:
                specs_path = conversation_path.with_name("tool-specs.json")
                specs_path.write_text(
                    json.dumps(tool_specs, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        try:
            if recorder is not None and not recorder.has_run_finished:
                coverage: dict = {}
                try:
                    task = load_task(cwd)
                    snapshot = latest_coverage(cwd, task.id)
                    if snapshot is not None:
                        coverage = {
                            "gap_score": snapshot.gap_score,
                            "level": snapshot.level,
                        }
                except IntelError:
                    pass
                trajectory.emit(
                    make_event(
                        "run_finished",
                        "system",
                        RunFinishedPayload(
                            status=terminal_status,
                            stage=final_stage,
                            requests=usage.requests,
                            tool_calls=usage.tool_calls,
                            input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens,
                            total_tokens=usage.total_tokens,
                            elapsed_ms=max(
                                0,
                                int((time.monotonic() - trace_started) * 1000),
                            ),
                            error_code=terminal_error_code,
                            error_summary=terminal_error_summary,
                            final_coverage=coverage,
                        ),
                        layer="evaluation",
                    )
                )
        finally:
            if trace_binding is not None:
                trajectory.restore_context(trace_binding)
