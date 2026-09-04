"""Dedicated report agent that composes the structured report draft.

The main agent collects and verifies facts; this agent owns the writing
step: turning the task's verified facts, coverage snapshot, and material
digest into a ``ResearchReportInput`` draft. The deterministic renderer in
``report.py`` still validates and writes the final Markdown, so a bad draft
from this agent is rejected rather than trusted. It reuses the main model
and mirrors ``JudgeAgent``'s plain-text-plus-manual-JSON pattern because
thinking-mode providers reject structured output (``tool_choice=required``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
)
from pydantic_ai.providers.openai import OpenAIProvider

from .audit import verified_support_evidence
from .config import ContextConfig, ModelConfig
from .coverage import latest_coverage
from .fact import list_active_facts_for_task
from .materials import load_material_digest
from .models import (
    CoverageSnapshot,
    Fact,
    IntelError,
    IntelTask,
    MaterialDigest,
    ResearchReportInput,
)
from .task import load_task

REPORT_SYSTEM_PROMPT = """你是独立的公开信息调研报告撰写智能体。你只负责把已经审核、已验证的事实和覆盖评估组织成结构化的报告草稿；你不检索、不抓取、不审核证据，也不生成最终 Markdown 文本。最终 Markdown 由系统根据你的草稿确定性渲染。

## 输入
输入是一个 JSON 对象，包含：
- topic / objective / scope / report_depth：调研主题、目标、范围与深度；
- questions：核心问题列表（id + text）；
- facts：已通过审核且有已验证支持证据的事实（fact_id、question_id、statement、claim_type、coverage_status）；
- coverage：覆盖快照（level、gap_score、stop_reason）；
- material_digest：材料导读（overview、key_points，可能为空）。

## 规则
1. 只引用输入 facts 中给出的 fact_id，不得编造 fact_id、statement、URL 或来源。
2. 每个核心问题对应一个 section（question_id 必须来自 questions），结论逐条引用该问题下的已验证事实。
3. 事实型结论用 {"kind": "reported", "fact_id": "..."}；claim_type 为 reported 的事实必须在 statement 中体现归属（原 statement 已含归属，无需改写）。
4. 推断型结论用 {"kind": "inference", "statement": "...", "confidence": "high|medium|low", "fact_ids": ["...", "..."]}，fact_ids 必须引用至少两个不同且 coverage_status 为 covered 的事实；statement 不得包含 URL、内部 ID 或手写引用。
5. 没有已验证事实的问题，其 section 的 conclusions 留空数组 []。
6. overall_conclusions 给出 1–3 条跨问题的综合结论（reported 事实或 inference 推断均可）。
7. 不要输出 Markdown、代码块围栏或任何解释，只输出一个 JSON 对象。

## 输出
只输出一个 JSON 对象，结构如下：
{"sections": [{"question_id": "...", "conclusions": [...]}], "overall_conclusions": [...]}"""


def _build_chat_model(
    cfg: ModelConfig, api_key: str | None
) -> OpenAIChatModel:
    provider = OpenAIProvider(
        base_url=cfg.base_url, api_key=api_key or "missing-api-key"
    )
    return OpenAIChatModel(cfg.name, provider=provider)


def _report_model_settings(
    context: ContextConfig,
) -> OpenAIChatModelSettings:
    settings = OpenAIChatModelSettings(max_tokens=context.main_output_tokens)
    if context.disable_thinking:
        settings["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": False}
        }
    return settings


def _parse_report_input(text: str) -> ResearchReportInput:
    """Parse the report agent's plain-text JSON output into a draft."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise IntelError(
            "REPORT_COMPOSE_FAILED",
            f"报告智能体返回了无法解析的 JSON: {error}",
        ) from error
    try:
        return ResearchReportInput.model_validate(data)
    except ValidationError as error:
        raise IntelError(
            "REPORT_COMPOSE_FAILED", f"报告草稿校验失败: {error}"
        ) from error


def _build_payload(
    task: IntelTask,
    coverage: CoverageSnapshot,
    facts: list[Fact],
    digest: MaterialDigest | None,
) -> dict:
    status_by_fact = {
        fact.fact_id: fact.status
        for question in coverage.per_question
        for fact in question.facts
    }
    return {
        "topic": task.topic,
        "objective": task.objective,
        "scope": {
            "time_range": task.scope.time_range,
            "geography": task.scope.geography,
            "languages": task.scope.languages,
        },
        "report_depth": task.report_depth,
        "questions": [
            {"id": question.id, "text": question.text}
            for question in task.questions
        ],
        "facts": [
            {
                "fact_id": fact.id,
                "question_id": fact.question_id,
                "statement": fact.statement,
                "claim_type": fact.claim_type,
                "coverage_status": status_by_fact.get(fact.id, "unknown"),
            }
            for fact in facts
        ],
        "coverage": {
            "level": coverage.level,
            "gap_score": coverage.gap_score,
            "stop_reason": coverage.stop_reason,
        },
        "material_digest": (
            {
                "overview": digest.overview,
                "key_points": digest.key_points,
            }
            if digest is not None
            else None
        ),
    }


class ReportAgent:
    """Isolated report writer: its own agent, never sharing the main context."""

    def __init__(
        self,
        cfg: ModelConfig,
        api_key: str | None,
        context: ContextConfig,
    ):
        self.agent = Agent(
            _build_chat_model(cfg, api_key),
            system_prompt=REPORT_SYSTEM_PROMPT,
            model_settings=_report_model_settings(context),
        )

    async def compose(
        self,
        *,
        task: IntelTask,
        coverage: CoverageSnapshot,
        facts: list[Fact],
        digest: MaterialDigest | None,
    ) -> ResearchReportInput:
        """Compose a report draft from verified facts and coverage."""
        payload = _build_payload(task, coverage, facts, digest)
        try:
            result = await self.agent.run(
                json.dumps(payload, ensure_ascii=False)
            )
        except IntelError:
            raise
        except Exception as error:
            raise IntelError("REPORT_COMPOSE_FAILED", str(error)) from error
        return _parse_report_input(result.output)

    async def compose_for_task(
        self, cwd: Path, task_id: str
    ) -> ResearchReportInput:
        """Gather task state and compose a draft for it."""
        task = load_task(cwd, task_id)
        coverage = latest_coverage(cwd, task_id)
        if coverage is None:
            raise IntelError(
                "REPORT_COMPOSE_FAILED", "生成报告前必须运行 coverage_eval"
            )
        digest = load_material_digest(cwd, task_id)
        facts = [
            fact
            for fact in list_active_facts_for_task(cwd, task_id)
            if verified_support_evidence(cwd, fact.id)
        ]
        return await self.compose(
            task=task, coverage=coverage, facts=facts, digest=digest
        )
