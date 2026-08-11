"""Coverage evaluation with stop conditions (port of coverage.ts)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .audit import review_for_evidence
from .conflicts import load_conflicts
from .evidence import list_evidence_for_fact, load_document
from .fact import list_active_facts_for_question
from .models import (
    CoverageHistory,
    CoverageSnapshot,
    EvidenceConflict,
    Fact,
    FactCoverage,
    QuestionCoverage,
    SourceType,
    is_valid_calendar_date,
    new_id,
)
from .storage import (
    intel_path,
    read_json,
    sha256,
    verify_document_integrity,
    write_json_atomic,
)
from .task import load_task

HIGH_QUALITY: set[SourceType] = {"official", "government", "news", "academic"}


def _is_recent(value: str | None, now: datetime, recency_days: int) -> bool:
    if not value or not is_valid_calendar_date(value):
        return False
    timestamp = datetime.fromisoformat(f"{value}T00:00:00Z")
    age = now - timestamp
    return timedelta(0) <= age <= timedelta(days=recency_days)


def _evaluate_fact(
    cwd: Path,
    fact: Fact,
    criteria,
    conflicts: list[EvidenceConflict],
    now: datetime,
) -> FactCoverage:
    evidence = list_evidence_for_fact(cwd, fact.id)
    candidate_supports = [e for e in evidence if e.relation == "supports"]
    reviewed = [
        (e, review_for_evidence(cwd, e.id)) for e in candidate_supports
    ]
    supports = [
        e for e, review in reviewed if review and review.verdict == "full"
    ]
    pending = sum(1 for _, review in reviewed if review is None)
    partial = sum(
        1 for _, review in reviewed if review and review.verdict == "partial"
    )
    irrelevant = sum(
        1
        for _, review in reviewed
        if review and review.verdict == "irrelevant"
    )
    contradictory_reviews = sum(
        1
        for _, review in reviewed
        if review and review.verdict == "contradicts"
    )
    contradicts = [e for e in evidence if e.relation == "contradicts"]
    documents = []
    for e in supports:
        document = load_document(cwd, e.document_id)
        verify_document_integrity(cwd, document)
        documents.append(document)
    source_groups = sorted({d.source_group for d in documents})
    high_quality_groups = {
        d.source_group for d in documents if d.source_type in HIGH_QUALITY
    }
    recent_count = sum(
        1
        for d in documents
        if _is_recent(d.publish_time, now, criteria.recency_days)
    )
    unknown_publish_time = sum(
        1
        for d in documents
        if not d.publish_time or not is_valid_calendar_date(d.publish_time)
    )
    fact_conflicts = [c for c in conflicts if c.fact_id == fact.id]
    unresolved_conflicts = sum(
        1 for c in fact_conflicts if c.resolution == "unresolved"
    )
    registered = {eid for c in fact_conflicts for eid in c.evidence_ids}
    unresolved_contradictions = sum(
        1 for e in contradicts if e.id not in registered
    )
    source_gap = max(0, criteria.min_independent_sources - len(source_groups))
    quality_gap = max(
        0, criteria.min_high_quality_sources - len(high_quality_groups)
    )
    recency_gap = 1 if criteria.require_recency and recent_count == 0 else 0
    gap_score = (
        source_gap
        + quality_gap
        + recency_gap
        + unresolved_conflicts
        + unresolved_contradictions
    )
    notes: list[str] = []
    if source_gap > 0:
        notes.append("独立来源组不足")
    if quality_gap > 0:
        notes.append("高质量独立来源组不足")
    if recency_gap > 0:
        notes.append("无可确认的时效窗口内证据")
    if unresolved_conflicts > 0:
        notes.append("存在未消解矛盾")
    if unresolved_contradictions > 0:
        notes.append("存在未登记或未处理的反证")
    if source_gap > 0 and supports:
        keywords = " ".join(fact.statement.split()[:6])
        notes.append(
            f"建议搜索「{keywords}」的交叉验证来源（第 2 个独立来源组）"
        )
    if pending > 0:
        notes.append(f"{pending} 条候选支持尚未语义审核")
    if partial > 0:
        notes.append(f"{partial} 条引文只部分支持 Fact")
    if irrelevant > 0:
        notes.append(f"{irrelevant} 条引文与 Fact 无直接支持关系")
    if contradictory_reviews > 0:
        notes.append(f"{contradictory_reviews} 条候选支持实际与 Fact 矛盾")
    if not candidate_supports:
        status = "gap"
    elif supports and gap_score == 0:
        status = "covered"
    else:
        status = "partial"
    return FactCoverage(
        fact_id=fact.id,
        statement=fact.statement,
        status=status,
        candidate_supports_count=len(candidate_supports),
        supports_count=len(supports),
        pending_reviews=pending,
        partial_reviews=partial,
        irrelevant_reviews=irrelevant,
        contradictory_reviews=contradictory_reviews,
        contradicts_count=len(contradicts),
        independent_sources=len(source_groups),
        source_groups=source_groups,
        high_quality_sources=len(high_quality_groups),
        recent_count=recent_count,
        unknown_publish_time=unknown_publish_time,
        unresolved_conflicts=unresolved_conflicts,
        unresolved_contradictions=unresolved_contradictions,
        gap_score=gap_score,
        notes=notes,
    )


def _evaluate_question(
    cwd: Path,
    task_id: str,
    question_id: str,
    conflicts: list[EvidenceConflict],
    now: datetime,
) -> QuestionCoverage:
    task = load_task(cwd, task_id)
    question = next(q for q in task.questions if q.id == question_id)
    facts = [
        _evaluate_fact(cwd, f, task.criteria, conflicts, now)
        for f in list_active_facts_for_question(cwd, task.id, question.id)
    ]
    covered_count = sum(1 for f in facts if f.status == "covered")
    has_support = any(f.candidate_supports_count > 0 for f in facts)
    if not facts or not has_support:
        status = "gap"
        notes = ["尚未登记事实"] if not facts else ["事实尚无支持证据"]
    elif covered_count == len(facts):
        status = "covered"
        notes = []
    else:
        status = "partial"
        notes = ["存在未充分覆盖的事实"]
    return QuestionCoverage(
        question_id=question.id,
        question=question.text,
        status=status,
        fact_count=len(facts),
        covered_fact_count=covered_count,
        facts=facts,
        notes=notes,
    )


def _load_history(cwd: Path, task_id: str) -> CoverageHistory:
    path = f"coverage/{task_id}.json"
    if not intel_path(cwd, path).exists():
        return CoverageHistory(task_id=task_id, snapshots=[])
    return CoverageHistory.model_validate(read_json(cwd, path))


def latest_coverage(cwd: Path, task_id: str) -> CoverageSnapshot | None:
    snapshots = _load_history(cwd, task_id).snapshots
    return snapshots[-1] if snapshots else None


def eval_coverage(
    cwd: Path, task_id: str, now: datetime | None = None
) -> CoverageSnapshot:
    now = now or datetime.now(UTC)
    task = load_task(cwd, task_id)
    conflicts = load_conflicts(cwd, task.id)
    per_question = [
        _evaluate_question(cwd, task.id, q.id, conflicts, now)
        for q in task.questions
    ]
    covered = sum(1 for q in per_question if q.status == "covered")
    ratio = covered / len(task.questions)
    # Level thresholds: all questions covered -> sufficient; >=70% -> mostly
    # sufficient (collection may stop); below that the task is still gapped.
    level = (
        "sufficient"
        if ratio == 1
        else "mostly_sufficient"
        if ratio >= 0.7
        else "insufficient"
    )
    gap_score = sum(
        (1 if q.fact_count == 0 else sum(f.gap_score for f in q.facts))
        for q in per_question
    )
    fingerprint = sha256(
        __import__("json").dumps(
            [
                {
                    "question_id": q.question_id,
                    "status": q.status,
                    "facts": [
                        {
                            "fact_id": f.fact_id,
                            "status": f.status,
                            "gap_score": f.gap_score,
                            "supports_count": f.supports_count,
                            "pending_reviews": f.pending_reviews,
                            "partial_reviews": f.partial_reviews,
                            "irrelevant_reviews": f.irrelevant_reviews,
                            "contradictory_reviews": f.contradictory_reviews,
                        }
                        for f in q.facts
                    ],
                }
                for q in per_question
            ],
            ensure_ascii=False,
        )
    )
    # Only a strictly smaller gap_score counts as progress; the agent gets two
    # consecutive rounds to improve before no_progress stops collection. Note a
    # gap_score increase is also "not progress" — e.g. newly found contradicting
    # evidence raises the score, which correctly means more collection, not less.
    history = _load_history(cwd, task.id)
    previous = history.snapshots[-1] if history.snapshots else None
    progressed = previous is None or gap_score < previous.gap_score
    no_progress_rounds = (
        0
        if previous is None or progressed
        else previous.no_progress_rounds + 1
    )
    stop_reason = (
        "sufficient"
        if level == "sufficient"
        else ("no_progress" if no_progress_rounds >= 2 else None)
    )
    snapshot = CoverageSnapshot(
        id=new_id("cov"),
        task_id=task.id,
        created_at=now.isoformat(),
        fingerprint=fingerprint,
        gap_score=gap_score,
        no_progress_rounds=no_progress_rounds,
        stop_reason=stop_reason,
        level=level,
        per_question=per_question,
    )
    write_json_atomic(
        cwd,
        f"coverage/{task.id}.json",
        CoverageHistory(
            task_id=task.id, snapshots=[*history.snapshots, snapshot]
        ).model_dump(),
    )
    return snapshot
