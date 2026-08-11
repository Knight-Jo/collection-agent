"""Aggregate persisted domain records into Web workbench read models."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Literal

from ..audit import list_support_reviews_for_task
from ..challenge import list_challenge_rounds
from ..conflicts import load_conflicts
from ..coverage import latest_coverage
from ..evidence import list_evidence_for_task, load_document
from ..fact import list_facts_for_task
from ..models import IntelError, IntelTask
from ..storage import list_json, sha256, workspace_path
from ..task import load_task
from .schemas import (
    ArtifactView,
    DocumentSummary,
    EvidenceView,
    FactView,
    QuestionView,
    TaskSummary,
    TaskView,
)


def list_task_summaries(cwd: Path) -> list[TaskSummary]:
    """Return all persisted tasks ordered by most recent update."""
    summaries: list[TaskSummary] = []
    for item in list_json(cwd, "tasks"):
        task = IntelTask.model_validate(item)
        coverage = latest_coverage(cwd, task.id)
        summaries.append(
            TaskSummary(
                id=task.id,
                topic=task.topic,
                stage=task.stage,
                updated_at=task.updated_at,
                coverage_level=coverage.level if coverage else None,
                gap_score=coverage.gap_score if coverage else None,
                evidence_count=task.collection.evidence_count,
            )
        )
    return sorted(summaries, key=lambda item: item.updated_at, reverse=True)


def get_task_view(cwd: Path, task_id: str) -> TaskView:
    """Build a question-first task view with nested evidence and reviews."""
    task = load_task(cwd, task_id)
    coverage = latest_coverage(cwd, task.id)
    facts = list_facts_for_task(cwd, task.id)
    evidence = list_evidence_for_task(cwd, task.id)
    reviews = {
        review.evidence_id: review
        for review in list_support_reviews_for_task(cwd, task.id)
    }
    evidence_by_fact = defaultdict(list)
    for item in evidence:
        document = load_document(cwd, item.document_id)
        evidence_by_fact[item.fact_id].append(
            EvidenceView(
                id=item.id,
                relation=item.relation,
                quote=item.quote,
                line_start=item.line_start,
                line_end=item.line_end,
                notes=item.notes,
                document=DocumentSummary(
                    id=document.id,
                    title=document.title,
                    final_url=document.final_url,
                    source_type=document.source_type,
                    source_group=document.source_group,
                    publish_time=document.publish_time,
                    content_type=document.content_type,
                    text_sha256=document.text_sha256,
                    injection_warnings=document.injection_warnings,
                ),
                review=reviews.get(item.id),
            )
        )

    fact_coverage = {
        fact.fact_id: fact
        for question in (coverage.per_question if coverage else [])
        for fact in question.facts
    }
    question_coverage = {
        question.question_id: question
        for question in (coverage.per_question if coverage else [])
    }
    facts_by_question = defaultdict(list)
    for fact in facts:
        facts_by_question[fact.question_id].append(
            FactView(
                id=fact.id,
                statement=fact.statement,
                status=fact.status,
                superseded_by=fact.superseded_by,
                supersession_reason=fact.supersession_reason,
                coverage=fact_coverage.get(fact.id),
                evidence=evidence_by_fact[fact.id],
            )
        )

    return TaskView(
        task=task,
        coverage=coverage,
        questions=[
            QuestionView(
                id=question.id,
                text=question.text,
                coverage=question_coverage.get(question.id),
                facts=facts_by_question[question.id],
            )
            for question in task.questions
        ],
        conflicts=load_conflicts(cwd, task.id),
        challenges=list_challenge_rounds(cwd, task.id),
    )


def get_artifact(
    cwd: Path,
    task_id: str,
    kind: Literal["assessment", "package"],
) -> ArtifactView:
    """Load an output only when it still matches its persisted binding hash."""
    task = load_task(cwd, task_id)
    binding = getattr(task.outputs, kind)
    if binding is None:
        raise IntelError("NOT_FOUND", f"任务尚未生成 {kind} 产物")
    path = workspace_path(cwd, binding.path)
    if (
        not path.exists()
        or sha256(path.read_bytes()) != binding.content_sha256
    ):
        raise IntelError("OUTPUT_TAMPERED", f"{kind} 产物缺失或已被修改")
    return ArtifactView(
        kind=kind,
        path=binding.path,
        content=path.read_text(encoding="utf-8"),
        content_sha256=binding.content_sha256,
    )
