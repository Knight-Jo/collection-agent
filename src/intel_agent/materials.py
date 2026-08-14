"""Task-scoped material recommendations and collection digest."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .audit import review_for_evidence
from .coverage import latest_coverage
from .evidence import list_evidence_for_task, load_document
from .fact import list_active_facts_for_task
from .models import (
    IntelError,
    MaterialDigest,
    MaterialReview,
    utc_now,
)
from .storage import (
    intel_path,
    load_crawl,
    read_json,
    verify_document_integrity,
    workspace_path,
    write_json_atomic,
)
from .task import load_task


def load_material_digest(cwd: Path, task_id: str) -> MaterialDigest | None:
    """Load a task's material digest when one has been created."""
    path = f"materials/{task_id}.json"
    if not intel_path(cwd, path).exists():
        return None
    digest = MaterialDigest.model_validate(read_json(cwd, path))
    if digest.task_id != task_id:
        raise IntelError("STORAGE_CORRUPT", "材料导读任务不匹配")
    return digest


def _empty_digest(task_id: str) -> MaterialDigest:
    now = utc_now()
    return MaterialDigest(task_id=task_id, created_at=now, updated_at=now)


def _save_digest(cwd: Path, digest: MaterialDigest) -> None:
    write_json_atomic(
        cwd, f"materials/{digest.task_id}.json", digest.model_dump()
    )


def register_material(
    cwd: Path,
    task_id: str,
    canonical_url: str,
    *,
    document_id: str | None = None,
    error: str | None = None,
) -> MaterialReview:
    """Register one collected resource under a task."""
    load_task(cwd, task_id)
    canonical_url = canonical_url.strip()
    if not canonical_url:
        raise IntelError("INVALID_INPUT", "材料 URL 不能为空")
    if document_id:
        document = load_document(cwd, document_id)
        verify_document_integrity(cwd, document)
        if document.canonical_url != canonical_url:
            raise IntelError("INVALID_INPUT", "材料 URL 与文档不匹配")
    digest = load_material_digest(cwd, task_id) or _empty_digest(task_id)
    existing = next(
        (
            item
            for item in digest.materials
            if item.canonical_url == canonical_url
        ),
        None,
    )
    now = utc_now()
    review = MaterialReview(
        task_id=task_id,
        canonical_url=canonical_url,
        document_id=document_id,
        rating=1 if error or not document_id else 2,
        description=(
            f"材料不可读：{error or '未成功归档正文'}"
            if error or not document_id
            else "材料已归档，可结合当前调研问题选择阅读。"
        )[:120],
        error=error,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    materials = [
        item
        for item in digest.materials
        if item.canonical_url != canonical_url
    ]
    materials.append(review)
    _save_digest(
        cwd,
        digest.model_copy(update={"materials": materials, "updated_at": now}),
    )
    return review


def _sync_crawl_materials(
    cwd: Path, task_id: str, digest: MaterialDigest
) -> MaterialDigest:
    try:
        crawl = load_crawl(cwd, task_id)
    except IntelError as error:
        if error.code == "NOT_FOUND":
            return digest
        raise
    by_url = {item.canonical_url: item for item in digest.materials}
    now = utc_now()
    for entry in crawl.entries:
        error = entry.error or entry.extraction.error
        readable = entry.document_id and entry.extraction.status == "complete"
        if not readable and not error:
            error = f"采集状态为 {entry.status}/{entry.extraction.status}"
        previous = by_url.get(entry.canonical_url)
        by_url[entry.canonical_url] = MaterialReview(
            task_id=task_id,
            canonical_url=entry.canonical_url,
            document_id=entry.document_id if readable else None,
            rating=2 if readable else 1,
            description=(
                "材料已归档，可结合当前调研问题选择阅读。"
                if readable
                else f"材料不可读：{error}"
            )[:120],
            error=None if readable else error,
            created_at=previous.created_at if previous else entry.created_at,
            updated_at=now,
        )
    return digest.model_copy(
        update={"materials": list(by_url.values()), "updated_at": now}
    )


def _question_matches(task, text: str) -> list[str]:
    normalized = text.casefold()
    if task.topic.casefold() not in normalized:
        return []
    return [question.id for question in task.questions]


def _description(
    title: str,
    rating: int,
    question: str | None,
    error: str | None,
) -> str:
    if error:
        return f"材料不可读：{error}"[:120]
    if rating == 5:
        return f"{title}直接支撑“{question}”，建议优先精读。"[:120]
    if rating == 4:
        return (
            f"{title}包含与“{question}”相关的候选证据，建议结合其他来源阅读。"[
                :120
            ]
        )
    if rating == 3:
        return f"{title}与当前主题相关，可用于补充背景和上下文。"[:120]
    return f"{title}已归档，但与核心问题的直接关联有限。"[:120]


def generate_material_digest(cwd: Path, task_id: str) -> MaterialDigest:
    """Rate all task materials and persist a concise reading guide."""
    task = load_task(cwd, task_id)
    digest = _sync_crawl_materials(
        cwd,
        task.id,
        load_material_digest(cwd, task.id) or _empty_digest(task.id),
    )
    facts = list_active_facts_for_task(cwd, task.id)
    fact_by_id = {fact.id: fact for fact in facts}
    evidence_by_document = defaultdict(list)
    for evidence in list_evidence_for_task(cwd, task.id):
        if evidence.fact_id in fact_by_id:
            evidence_by_document[evidence.document_id].append(evidence)

    reviewed_materials: list[MaterialReview] = []
    type_counts: Counter[str] = Counter()
    publish_dates: list[str] = []
    verified_fact_ids: set[str] = set()
    now = utc_now()
    for material in digest.materials:
        if not material.document_id or material.error:
            reviewed_materials.append(
                material.model_copy(
                    update={
                        "rating": 1,
                        "description": _description(
                            "材料", 1, None, material.error or "正文不可用"
                        ),
                        "question_ids": [],
                        "updated_at": now,
                    }
                )
            )
            continue
        document = load_document(cwd, material.document_id)
        verify_document_integrity(cwd, document)
        type_counts[document.content_type.split(";", 1)[0]] += 1
        if document.publish_time:
            publish_dates.append(document.publish_time)
        text = workspace_path(cwd, document.text_path).read_text(
            encoding="utf-8"
        )
        evidence = evidence_by_document.get(document.id, [])
        full = [
            item
            for item in evidence
            if item.relation == "supports"
            and (review := review_for_evidence(cwd, item.id))
            and review.verdict == "full"
        ]
        question_ids = sorted(
            {
                fact_by_id[item.fact_id].question_id
                for item in evidence
                if item.fact_id in fact_by_id
            }
        )
        if full:
            rating = 5
            verified_fact_ids.update(item.fact_id for item in full)
        elif evidence:
            rating = 4
        else:
            question_ids = _question_matches(
                task, f"{document.title}\n{text[:8_000]}"
            )
            rating = 3 if question_ids else 2
        question = next(
            (item.text for item in task.questions if item.id in question_ids),
            None,
        )
        reviewed_materials.append(
            material.model_copy(
                update={
                    "rating": rating,
                    "description": _description(
                        document.title or document.source_group,
                        rating,
                        question,
                        None,
                    ),
                    "question_ids": question_ids,
                    "updated_at": now,
                }
            )
        )

    reviewed_materials.sort(
        key=lambda item: (-item.rating, item.canonical_url)
    )
    priority = [
        item.canonical_url for item in reviewed_materials if item.rating >= 4
    ]
    reading_guide = {
        question.id: [
            item.canonical_url
            for item in reviewed_materials
            if question.id in item.question_ids
        ]
        for question in task.questions
    }
    coverage = latest_coverage(cwd, task.id)
    gaps = (
        [
            f"{question.question}：{'；'.join(question.notes)}"
            for question in coverage.per_question
            if question.answer_status != "answered"
        ]
        if coverage
        else []
    )
    type_summary = "、".join(
        f"{kind} {count} 份" for kind, count in sorted(type_counts.items())
    )
    date_summary = (
        f"，发布时间覆盖 {min(publish_dates)} 至 {max(publish_dates)}"
        if publish_dates
        else ""
    )
    result = digest.model_copy(
        update={
            "overview": (
                f"共收集 {len(reviewed_materials)} 份材料"
                + (f"，其中 {type_summary}" if type_summary else "")
                + date_summary
                + "。"
            ),
            "key_points": [
                fact.statement
                for fact in facts
                if fact.id in verified_fact_ids
            ][:5],
            "priority_materials": priority,
            "reading_guide": reading_guide,
            "gaps": gaps,
            "materials": reviewed_materials,
            "updated_at": now,
        }
    )
    _save_digest(cwd, result)
    return result
