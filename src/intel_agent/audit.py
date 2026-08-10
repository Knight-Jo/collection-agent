"""Semantic support entailment audit (port of audit.ts)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .evidence import list_evidence_for_fact, load_evidence
from .fact import list_active_facts_for_task, load_fact
from .models import (
    SUPPORT_REVIEW_PROMPT_VERSION,
    EvidenceSupport,
    Fact,
    IntelError,
    SupportReview,
    SupportVerdict,
    utc_now,
)
from .storage import intel_path, list_json, read_json, sha256, write_json_atomic
from .task import load_task


def review_id(fact_id: str, evidence_id: str) -> str:
    return f"review-{sha256(f'{fact_id}\n{evidence_id}\n{SUPPORT_REVIEW_PROMPT_VERSION}')[:16]}"


VALID_VERDICTS = {"full", "partial", "irrelevant", "contradicts"}


def validate_verdict(result: dict) -> dict:
    unsupported = result.get("unsupported_parts") or []
    reason = (result.get("reason") or "").strip()
    if (
        not isinstance(result.get("evidence_id"), str)
        or result.get("verdict") not in VALID_VERDICTS
        or not reason
        or len(reason) > 1_000
        or not isinstance(unsupported, list)
        or len(unsupported) > 10
        or not all(isinstance(p, str) and p.strip() and len(p.strip()) <= 300 for p in unsupported)
        or (result["verdict"] == "full" and unsupported)
        or (result["verdict"] == "partial" and not unsupported)
    ):
        raise IntelError("SEMANTIC_AUDIT_FAILED", "语义审核返回了无效 verdict")
    return {
        "evidence_id": result["evidence_id"],
        "verdict": result["verdict"],
        "reason": reason,
        "unsupported_parts": [p.strip() for p in unsupported],
    }


def verify_review(cwd: Path, review: SupportReview) -> SupportReview:
    if (
        not review.id
        or not review.task_id
        or not review.fact_id
        or not review.evidence_id
        or review.verdict not in VALID_VERDICTS
        or not review.reason
        or review.prompt_version != SUPPORT_REVIEW_PROMPT_VERSION
        or not review.judge_provider.strip()
        or not review.judge_model.strip()
    ):
        raise IntelError("STORAGE_CORRUPT", "审核记录不匹配")
    try:
        fact = load_fact(cwd, review.fact_id)
        evidence = load_evidence(cwd, review.evidence_id)
    except IntelError as error:
        if error.code == "NOT_FOUND":
            raise IntelError("STORAGE_CORRUPT", f"审核记录不匹配: {review.id}")
        raise
    try:
        validate_verdict(review.model_dump())
    except IntelError:
        raise IntelError("STORAGE_CORRUPT", f"审核记录不匹配: {review.id}")
    if (
        evidence.relation != "supports"
        or evidence.fact_id != fact.id
        or review.task_id != fact.task_id
        or review.id != review_id(fact.id, evidence.id)
    ):
        raise IntelError("STORAGE_CORRUPT", f"审核记录不匹配: {review.id}")
    return review


def load_support_review(cwd: Path, evidence_id: str) -> SupportReview:
    evidence = load_evidence(cwd, evidence_id)
    id_ = review_id(evidence.fact_id, evidence.id)
    review = verify_review(cwd, SupportReview.model_validate(read_json(cwd, f"reviews/{id_}.json")))
    if review.id != id_:
        raise IntelError("STORAGE_CORRUPT", f"审核文件名与记录 ID 不匹配: {id_}")
    return review


def review_for_evidence(cwd: Path, evidence_id: str) -> SupportReview | None:
    evidence = load_evidence(cwd, evidence_id)
    id_ = review_id(evidence.fact_id, evidence.id)
    return load_support_review(cwd, evidence.id) if intel_path(cwd, f"reviews/{id_}.json").exists() else None


def list_support_reviews_for_task(cwd: Path, task_id: str) -> list[SupportReview]:
    return [
        verify_review(cwd, SupportReview.model_validate(item))
        for item in list_json(cwd, "reviews")
        if item.get("task_id") == task_id
    ]


def validate_batch(evidence: list[EvidenceSupport], raw: list[dict]) -> list[dict]:
    if not isinstance(raw, list):
        raise IntelError("SEMANTIC_AUDIT_FAILED", "语义审核未返回 verdict 列表")
    expected = {e.id for e in evidence}
    results = [validate_verdict(item) for item in raw]
    returned = {r["evidence_id"] for r in results}
    if (
        len(results) != len(expected)
        or len(returned) != len(results)
        or any(r["evidence_id"] not in expected for r in results)
    ):
        raise IntelError("SEMANTIC_AUDIT_FAILED", "语义审核 evidence IDs 不完整或不匹配")
    return results


async def audit_task_evidence(
    cwd: Path,
    task_id: str,
    judge: object,
    judge_provider: str,
    judge_model: str,
) -> dict:
    task = load_task(cwd, task_id)
    if not judge_provider.strip() or not judge_model.strip():
        raise IntelError("SEMANTIC_AUDIT_FAILED", "语义审核缺少 judge 信息")
    batches: list[tuple[Fact, list[EvidenceSupport]]] = []
    cached = 0
    for fact in list_active_facts_for_task(cwd, task.id):
        pending: list[EvidenceSupport] = []
        for evidence in list_evidence_for_fact(cwd, fact.id):
            if evidence.relation != "supports":
                continue
            if review_for_evidence(cwd, evidence.id):
                cached += 1
            else:
                pending.append(evidence)
        if pending:
            batches.append((fact, pending))

    results: list[tuple[Fact, list[dict]]] = []
    try:
        judged = await asyncio.gather(
            *(judge(fact, evidence) for fact, evidence in batches), return_exceptions=True
        )
        for (fact, evidence), verdicts in zip(batches, judged):
            if isinstance(verdicts, BaseException):
                if isinstance(verdicts, IntelError):
                    raise verdicts
                raise IntelError("SEMANTIC_AUDIT_FAILED", str(verdicts))
            results.append((fact, validate_batch(evidence, verdicts)))
    except IntelError:
        raise
    except Exception as error:
        raise IntelError("SEMANTIC_AUDIT_FAILED", str(error))

    reviews = [
        SupportReview(
            id=review_id(fact.id, verdict["evidence_id"]),
            task_id=task.id,
            fact_id=fact.id,
            evidence_id=verdict["evidence_id"],
            verdict=verdict["verdict"],
            reason=verdict["reason"],
            unsupported_parts=verdict["unsupported_parts"],
            judge_provider=judge_provider.strip(),
            judge_model=judge_model.strip(),
            prompt_version=SUPPORT_REVIEW_PROMPT_VERSION,
            created_at=utc_now(),
        )
        for fact, verdicts in results
        for verdict in verdicts
    ]
    for review in reviews:
        write_json_atomic(cwd, f"reviews/{review.id}.json", review.model_dump())

    counts = {"full": 0, "partial": 0, "irrelevant": 0, "contradicts": 0}
    for review in list_support_reviews_for_task(cwd, task.id):
        counts[review.verdict] += 1
    return {
        "task_id": task.id,
        "reviewed": len(reviews),
        "cached": cached,
        "verdict_counts": counts,
        "judge_provider": judge_provider.strip(),
        "judge_model": judge_model.strip(),
        "prompt_version": SUPPORT_REVIEW_PROMPT_VERSION,
    }


def is_full_support(cwd: Path, evidence: EvidenceSupport) -> bool:
    review = review_for_evidence(cwd, evidence.id)
    return evidence.relation == "supports" and review is not None and review.verdict == "full"


def verified_support_evidence(cwd: Path, fact_id: str) -> list[EvidenceSupport]:
    load_fact(cwd, fact_id)
    return [e for e in list_evidence_for_fact(cwd, fact_id) if is_full_support(cwd, e)]
