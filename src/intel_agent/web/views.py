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
from ..materials import load_material_digest
from ..models import (
    CrawlEntry,
    ExtractionState,
    IntelDocument,
    IntelError,
    IntelTask,
    MaterialDigest,
)
from ..storage import (
    list_json,
    load_crawl,
    sha256,
    verify_document_integrity,
    workspace_path,
)
from ..task import load_task
from .schemas import (
    ArtifactView,
    CrawlResourceView,
    DocumentSummary,
    EvidenceView,
    FactView,
    QuestionView,
    TaskSummary,
    TaskView,
)


def _source_chain(
    entry: CrawlEntry, entries_by_url: dict[str, CrawlEntry]
) -> list[str]:
    chain = [entry.canonical_url]
    parent_url = entry.parent_url
    seen = {entry.canonical_url}
    while parent_url and parent_url not in seen:
        chain.append(parent_url)
        seen.add(parent_url)
        parent = entries_by_url.get(parent_url)
        parent_url = parent.parent_url if parent else None
    chain.reverse()
    return chain


def _crawl_resources(
    cwd: Path, task_id: str, digest: MaterialDigest | None
) -> list[CrawlResourceView]:
    try:
        crawl = load_crawl(cwd, task_id)
    except IntelError as error:
        if error.code == "NOT_FOUND":
            crawl = None
        else:
            raise
    reviews = (
        {item.canonical_url: item for item in digest.materials}
        if digest
        else {}
    )
    entries = crawl.entries if crawl else []
    entries_by_url = {entry.canonical_url: entry for entry in entries}
    resources: list[CrawlResourceView] = []
    for entry in entries:
        review = reviews.get(entry.canonical_url)
        resources.append(
            CrawlResourceView(
                canonical_url=entry.canonical_url,
                source_chain=_source_chain(entry, entries_by_url),
                depth=entry.depth,
                status=entry.status,
                mime_type=entry.mime_type,
                size=entry.size,
                downloaded_bytes=entry.downloaded_bytes,
                document_id=entry.document_id,
                extraction=entry.extraction,
                error=entry.error,
                rating=review.rating if review else None,
                description=review.description if review else None,
            )
        )
    for material in digest.materials if digest else []:
        if material.canonical_url in entries_by_url:
            continue
        document = (
            load_document(cwd, material.document_id)
            if material.document_id
            else None
        )
        if document:
            verify_document_integrity(cwd, document)
        size = (
            workspace_path(cwd, document.raw_path).stat().st_size
            if document
            else 0
        )
        resources.append(
            CrawlResourceView(
                canonical_url=material.canonical_url,
                source_chain=[material.canonical_url],
                depth=0,
                status="complete" if document else "failed",
                mime_type=document.content_type if document else None,
                size=size or None,
                downloaded_bytes=size,
                document_id=material.document_id,
                extraction=ExtractionState(
                    status=document.extraction_status
                    if document
                    else "failed",
                    text_path=document.text_path if document else None,
                    error=material.error,
                ),
                error=material.error,
                rating=material.rating,
                description=material.description,
            )
        )
    return resources


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
    material_digest = load_material_digest(cwd, task.id)
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
        resources=_crawl_resources(cwd, task.id, material_digest),
        material_digest=material_digest,
    )


def get_resource_download(
    cwd: Path, task_id: str, document_id: str
) -> tuple[Path, IntelDocument]:
    """Resolve a task-owned original only after document integrity checks."""
    load_task(cwd, task_id)
    crawl_document_ids: set[str] = set()
    try:
        crawl = load_crawl(cwd, task_id)
    except IntelError as error:
        if error.code == "NOT_FOUND":
            crawl = None
        else:
            raise
    if crawl:
        crawl_document_ids = {
            entry.document_id for entry in crawl.entries if entry.document_id
        }
    digest = load_material_digest(cwd, task_id)
    material_document_ids = {
        item.document_id
        for item in (digest.materials if digest else [])
        if item.document_id
    }
    if document_id not in crawl_document_ids | material_document_ids:
        raise IntelError("NOT_FOUND", f"任务资源不存在: {document_id}")
    document = load_document(cwd, document_id)
    verify_document_integrity(cwd, document)
    return workspace_path(cwd, document.raw_path), document


def get_artifact(
    cwd: Path,
    task_id: str,
    kind: Literal["report", "assessment", "package"],
) -> ArtifactView:
    """Load an output only when it still matches its persisted binding hash."""
    task = load_task(cwd, task_id)
    binding = getattr(task.outputs, kind)
    if kind == "assessment" and binding is None:
        binding = task.outputs.report
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
