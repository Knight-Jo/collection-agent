"""Shared task specification, prompt construction, and streamed agent runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import (
    AgentRunResult,
    CancellationToken,
)
from pydantic_ai.usage import UsageLimits

from .agent import build_agent, build_deps
from .config import Settings
from .models import ReportDepth, ResearchScope, SufficiencyCriteria
from .task import parse_time_range

EventCallback = Callable[[object], Awaitable[None]]


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
        "调用 intel_plan 时根据主题、目标和范围生成 3–6 个可独立回答的调研问题。\n"
        if not spec.questions
        else (
            "调用 intel_plan 时必须原样保留下列用户问题，并补充必要问题，"
            "使最终问题总数为 2–6 个：\n"
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
        "引文必须逐字覆盖主体、动作、范围、时间和数量，partial 时缩窄事实或补充引文。冲突数字分别记录并披露口径。\n"
        "【报告要求】先运行 material_digest 生成材料集合摘要和 1–5 星阅读推荐；正式报告只使用"
        "审核通过的结构化结论，逐问题回答并披露分歧、局限和未回答内容。证据包和红队复审是可选审计步骤。\n"
        "按主流程推进：intel_plan → 定向 web_search/web_fetch → fact_save/evidence_save → "
        "evidence_audit → coverage_eval（充分或 no_progress 停止）→ intel_status(assess) → "
        "material_digest → generate_research_report → intel_status(done)，最后返回报告路径和核心发现。"
    )


async def run_agent_task(
    cwd: Path,
    settings: Settings,
    spec: TaskRunSpec,
    *,
    on_event: EventCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> AgentRunResult[str]:
    """Run one task and forward each native Pydantic AI event."""
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
    agent = build_agent(settings)
    deps = build_deps(cwd, settings, deep_crawl=bool(resolved_spec.deep_crawl))
    for name in ("objective", "scope", "report_depth"):
        if hasattr(deps, name):
            setattr(deps, name, getattr(resolved_spec, name))
    if hasattr(deps, "crawl_event_callback"):
        deps.crawl_event_callback = on_event

    import logfire

    logfire.configure()
    logfire.instrument_system_metrics()
    logfire.instrument_pydantic_ai()

    async with agent.run_stream_events(
        build_task_prompt(resolved_spec),
        deps=deps,
        usage_limits=UsageLimits(
            request_limit=min(
                settings.budgets.request_limit,
                resolved_spec.max_requests or settings.budgets.request_limit,
            ),
            tool_calls_limit=resolved_spec.max_tool_calls,
        ),
        cancellation_token=cancellation_token,
    ) as events:
        async for event in events:
            if on_event is not None:
                await on_event(event)
        result = events.result
    if result is None:
        raise RuntimeError("Agent run completed without a result")
    return result
