"""Shared task specification, prompt construction, and streamed agent runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator
from pydantic_ai import (
    AgentRunResult,
    CancellationToken,
)
from pydantic_ai.usage import UsageLimits

from .agent import build_agent, build_deps
from .config import Settings
from .models import SufficiencyCriteria

EventCallback = Callable[[object], Awaitable[None]]


class TaskRunSpec(BaseModel):
    """Validated inputs shared by CLI and Web task runs."""

    topic: str
    questions: list[str]
    criteria: SufficiencyCriteria
    deep_crawl: bool | None = None

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("主题不能为空")
        return value

    @field_validator("questions")
    @classmethod
    def normalize_questions(cls, value: list[str]) -> list[str]:
        questions = list(
            dict.fromkeys(item.strip() for item in value if item.strip())
        )
        if not 2 <= len(questions) <= 6:
            raise ValueError("关键问题数量必须为 2–6 个")
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
    return (
        f"请围绕主题「{spec.topic}」执行公开来源情报收集与研判。\n"
        f"【关键问题·必须原样使用】调用 intel_plan 时必须原样使用下列问题，不得替换、增删或改写：\n"
        f"{questions}\n"
        f"【充分性标准·必须照此设置】min_independent_sources={criteria.min_independent_sources}，"
        f"min_high_quality_sources={criteria.min_high_quality_sources}，recency_days={criteria.recency_days}，"
        f"require_recency={str(criteria.require_recency).lower()}（{recency_required}）。\n"
        f"【深度抓取】调用 intel_plan 时必须设置 deep_crawl={str(bool(spec.deep_crawl)).lower()}。"
        f"{deep_crawl_instruction}"
        f"【检索纪律】先按问题逐一 web_search（每问题至少一次），优先官方/政府/主流新闻/学术来源；"
        f"每问题定向抓取 2-3 篇不同来源组的文档；同一问题至少 2 个独立来源组才可能达到 covered。\n"
        f"【检索多样性·重要】避免反复抓取同一批结果：web_search 返回的 already_archived=true 表示"
        f"该 URL 已归档，不要再抓取；若某问题结果几乎全部已归档（fresh_count 很小），必须换更具体的"
        f"查询词（公司名/机构名/具体事件/年份），或把 language 设为 en 搜英文一手来源（公司新闻稿、"
        f"交易所公告、行业媒体），或使用 filetype=pdf 搜索政府报告/白皮书。百度百科/维基百科只能当背景知识，"
        f"不能作为主要证据来源；优先抓取 gov.cn/新闻/企业官网/学术来源。\n"
        f"【来源扩展】web_fetch 返回的 outbound_links 可继续直接抓取（不消耗搜索预算），优先跟进"
        f"gov.cn/新闻/学术/公司官网链接；已知权威来源（如 ir.亿航公司.com、sec.gov、caixin.com）"
        f"可直接 web_fetch 无需先搜索。intel_plan 返回的 suggested_direct_sources 可直接抓取。\n"
        f"【金融数据源】投资/融资/市场规模类问题：可直接 web_fetch caixin.com（财新）、cls.cn（财联社）、"
        f"eastmoney.com（东方财富）、xueqiu.com（雪球）的搜索页/行情页/专题页；搜索研报时优先 filetype=pdf。\n"
        f"【订单数据】公司订单/交付/财报数据：直接 fetch ir.{{公司}}.com 投资者关系页、"
        f"sec.gov/edgar（美国上市公司财报）；英文搜索用 orders deliveries FY2025 等专业词。\n"
        f"【事实纪律】fact_save 只登记单一、原子、可独立核验的命题；引文必须逐字覆盖命题的"
        f"全部重要组成（主体/动作/范围/时间/数量）；evidence_audit 返回 partial 时用 fact_supersede "
        f"拆分为更窄的事实，或保存覆盖完整组成的引文。\n"
        f"【挑战纪律】intel_challenge_confirm 中 addressed 优先（引用本轮新增且已 full 审核的证据）；"
        f"确需 dismissed 时必须给出具体、可审查的理由（说明为何该缺口可接受）。\n"
        "按工作流推进：intel_plan → 逐问题检索抓取 → 事实与证据 → evidence_audit → coverage_eval"
        "（充分或 no_progress 停止）→ intel_status(assess) → generate_package + intel_assess → "
        "intel_status(challenge) → intel_challenge_start/confirm（最多 2 轮）→ 收敛后重新出包与研判 → "
        "intel_status(done)，并向用户报告结论、置信度、矛盾、缺口和产物路径。"
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
                settings.crawl.enabled_by_default
                if spec.deep_crawl is None
                else spec.deep_crawl
            )
        }
    )
    agent = build_agent(settings)
    deps = build_deps(cwd, settings, deep_crawl=bool(resolved_spec.deep_crawl))
    if hasattr(deps, "crawl_event_callback"):
        deps.crawl_event_callback = on_event
    async with agent.run_stream_events(
        build_task_prompt(resolved_spec),
        deps=deps,
        usage_limits=UsageLimits(request_limit=settings.budgets.request_limit),
        cancellation_token=cancellation_token,
    ) as events:
        async for event in events:
            if on_event is not None:
                await on_event(event)
        result = events.result
    if result is None:
        raise RuntimeError("Agent run completed without a result")
    return result
