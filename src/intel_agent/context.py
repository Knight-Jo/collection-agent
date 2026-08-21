"""Bound model history while restoring durable research state."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from pydantic_ai import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RunContext,
    UserPromptPart,
)

from .audit import review_for_evidence
from .config import ContextConfig
from .coverage import latest_coverage
from .evidence import list_evidence_for_task, load_document
from .fact import list_active_facts_for_task
from .materials import load_material_digest
from .models import IntelError
from .task import load_task, summarize_task

CONTEXT_SNAPSHOT_PREFIX = "[CONTEXT_SNAPSHOT]\n"


class _ContextDeps(Protocol):
    cwd: Path
    read_document_ids: set[str]


def _archived_documents(cwd: Path, task_id: str) -> list[dict[str, str]]:
    digest = load_material_digest(cwd, task_id)
    if digest is None:
        return []
    documents: list[dict[str, str]] = []
    for material in reversed(digest.materials):
        if not material.document_id or material.error:
            continue
        try:
            document = load_document(cwd, material.document_id)
        except IntelError:
            continue
        documents.append(
            {
                "id": document.id,
                "title": document.title,
                "url": document.canonical_url,
            }
        )
        if len(documents) == 8:
            break
    return documents


def build_context_snapshot(
    cwd: Path, *, read_document_ids: set[str] | None = None
) -> str:
    """Build a compact, deterministic snapshot from persisted task state."""
    try:
        task = load_task(cwd)
    except IntelError as error:
        if error.code == "NOT_FOUND":
            return json.dumps({"task": None}, ensure_ascii=False)
        raise
    coverage = latest_coverage(cwd, task.id)
    facts = list_active_facts_for_task(cwd, task.id)[:20]
    documents = _archived_documents(cwd, task.id)
    material_digest = load_material_digest(cwd, task.id)
    evidence = list_evidence_for_task(cwd, task.id)
    reviews = {
        item.id: review
        for item in evidence
        if item.relation == "supports"
        and (review := review_for_evidence(cwd, item.id)) is not None
    }
    pending_evidence_ids = [
        item.id
        for item in evidence
        if item.relation == "supports" and item.id not in reviews
    ]
    next_action = summarize_task(cwd, task.id)["next_action"]
    read_document_ids = read_document_ids or set()
    if pending_evidence_ids:
        next_action = (
            "停止搜索、抓取和覆盖评估。立即调用 "
            f"evidence_audit(task_id='{task.id}') 审核全部待审证据。"
        )
    elif reviews and (
        coverage is None
        or max(review.created_at for review in reviews.values())
        > coverage.created_at
    ):
        next_action = (
            f"审核已更新，立即调用 coverage_eval(task_id='{task.id}')。"
        )
    elif task.stage == "assess":
        if task.outputs.report is not None:
            next_action = (
                "正式报告已生成，立即调用 "
                f"intel_status(task_id='{task.id}', stage='done')。"
            )
        elif material_digest is not None and material_digest.overview:
            next_action = (
                "材料导读已生成，不要重复调用 material_digest。立即调用 "
                f"generate_research_report(task_id='{task.id}', draft=...)。"
            )
        else:
            next_action = (
                f"立即调用 material_digest(task_id='{task.id}')，"
                "然后生成正式报告。"
            )
    elif (
        task.stage == "collect"
        and coverage is not None
        and coverage.stop_reason
    ):
        next_action = (
            "覆盖评估已达到停止条件，禁止继续收集。立即调用 "
            f"intel_status(task_id='{task.id}', stage='assess')。"
        )
    elif read_document_ids and task.collection.evidence_count == 0:
        next_action = (
            f"已读取文档 {sorted(read_document_ids)[-1]}，不要再次读取。"
            "立即从最近返回的原文中提取一个原子命题并调用 fact_save，"
            "再用逐字引文调用 evidence_save。"
        )
    elif documents and task.collection.evidence_count == 0:
        next_action = (
            "停止继续搜索或抓取。调用 document_read 读取 archived_documents[0]，"
            "然后依次调用 fact_save 和 evidence_save。"
        )
    snapshot = {
        "task_id": task.id,
        "stage": task.stage,
        "completion_status": task.completion_status,
        "questions": [
            {"id": question.id, "text": question.text}
            for question in task.questions
        ],
        "collection": task.collection.model_dump(),
        "archived_documents": documents,
        "read_document_ids": sorted(read_document_ids),
        "pending_evidence_ids": pending_evidence_ids,
        "reviewed_evidence_ids": sorted(reviews),
        "material_digest_ready": bool(
            material_digest is not None and material_digest.overview
        ),
        "facts": [
            {
                "id": fact.id,
                "question_id": fact.question_id,
                "statement": fact.statement[:160],
                "claim_type": fact.claim_type,
            }
            for fact in facts
        ],
        "coverage": (
            {
                "level": coverage.level,
                "gap_score": coverage.gap_score,
                "stop_reason": coverage.stop_reason,
                "questions": [
                    {
                        "question_id": item.question_id,
                        "status": item.status,
                        "covered_fact_count": item.covered_fact_count,
                        "fact_count": item.fact_count,
                    }
                    for item in coverage.per_question
                ],
            }
            if coverage is not None
            else None
        ),
        "next_action": next_action,
    }
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ": "))


def _without_old_snapshots(messages: list[ModelMessage]) -> list[ModelMessage]:
    cleaned: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            cleaned.append(message)
            continue
        parts = [
            part
            for part in message.parts
            if not (
                isinstance(part, UserPromptPart)
                and isinstance(part.content, str)
                and part.content.startswith(CONTEXT_SNAPSHOT_PREFIX)
            )
        ]
        cleaned.append(
            message
            if len(parts) == len(message.parts)
            else replace(message, parts=parts)
        )
    return cleaned


def _with_snapshot(
    messages: list[ModelMessage], snapshot: str
) -> list[ModelMessage]:
    if not messages or not isinstance(messages[-1], ModelRequest):
        return messages
    updated = replace(
        messages[-1],
        parts=[
            *messages[-1].parts,
            UserPromptPart(content=CONTEXT_SNAPSHOT_PREFIX + snapshot),
        ],
    )
    return [*messages[:-1], updated]


def _serialized_size(messages: list[ModelMessage]) -> int:
    return len(ModelMessagesTypeAdapter.dump_json(messages))


def compact_message_history(
    messages: list[ModelMessage], *, max_bytes: int, snapshot: str
) -> list[ModelMessage]:
    """Keep the initial task and newest complete exchanges under a byte cap."""
    prepared = _with_snapshot(_without_old_snapshots(messages), snapshot)
    if len(prepared) <= 2 or _serialized_size(prepared) <= max_bytes:
        return prepared

    first = prepared[0]
    for start in range(1, len(prepared) - 1):
        if not isinstance(prepared[start], ModelResponse):
            continue
        candidate = [first, *prepared[start:]]
        if _serialized_size(candidate) <= max_bytes:
            return candidate

    return [first, prepared[-1]]


def make_history_processor(config: ContextConfig):
    """Create a Pydantic AI history processor for the configured window."""

    def process(
        ctx: RunContext[_ContextDeps], messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        return compact_message_history(
            messages,
            max_bytes=config.history_max_bytes(),
            snapshot=build_context_snapshot(
                ctx.deps.cwd,
                read_document_ids=getattr(
                    ctx.deps, "read_document_ids", set()
                ),
            ),
        )

    return process
