"""Deterministic reason attribution for trajectory decisions.

``reason_codes`` express a *state gap* (why a gap-driven action is warranted),
never an action restatement ("fetch because fetch needed" is circular). For
``origin=model`` decisions they are derived from the state snapshot observed at
the call site and therefore labelled ``reason_source="derived"`` — an inference,
not the model's real reason. Deterministic code paths produce their reasons at
the same moment as the decision and label them ``reason_source="rule"``.
"""

from __future__ import annotations

from pathlib import Path

from .coverage import latest_coverage
from .models import IntelError
from .task import load_task

REASON_CODES = (
    "MISSING_PRIMARY_SOURCE",
    "LOW_COVERAGE",
    "LOW_SOURCE_DIVERSITY",
    "EVIDENCE_GAIN_TOO_LOW",
    "QUERY_BUDGET_EXHAUSTED",
    "SEARCH_RESULT_NOT_MATERIALIZED",
    "SOURCE_CONTENT_NOT_ACQUIRED",
    "CLAIM_NOT_VERIFIED",
    "EVIDENCE_NOT_VERIFIED",
    "CONFLICT_UNRESOLVED",
)

_REASON_SUMMARIES = {
    "MISSING_PRIMARY_SOURCE": "缺少一手来源",
    "LOW_COVERAGE": "关键问题覆盖不足",
    "LOW_SOURCE_DIVERSITY": "来源多样性不足",
    "EVIDENCE_GAIN_TOO_LOW": "证据增益过低",
    "QUERY_BUDGET_EXHAUSTED": "检索预算耗尽",
    "SEARCH_RESULT_NOT_MATERIALIZED": "检索结果尚未落地为文档",
    "SOURCE_CONTENT_NOT_ACQUIRED": "来源正文尚未获取",
    "CLAIM_NOT_VERIFIED": "声明尚未核验",
    "EVIDENCE_NOT_VERIFIED": "证据尚未语义审核",
    "CONFLICT_UNRESOLVED": "存在未消解矛盾",
}


def snapshot_state(cwd: Path) -> dict:
    """Minimal state slice that influenced a decision (not the whole state)."""
    try:
        task = load_task(cwd)
    except IntelError:
        return {}
    coverage = latest_coverage(cwd, task.id)
    unresolved_conflicts = (
        sum(
            fact.unresolved_conflicts + fact.unresolved_contradictions
            for question in coverage.per_question
            for fact in question.facts
        )
        if coverage
        else 0
    )
    return {
        "stage": task.stage,
        "gap_score": coverage.gap_score if coverage else None,
        "coverage_level": coverage.level if coverage else None,
        "no_progress_rounds": coverage.no_progress_rounds
        if coverage
        else None,
        "stop_reason": coverage.stop_reason if coverage else None,
        "unresolved_conflicts": unresolved_conflicts,
        "search_attempts": task.collection.search_attempts,
        "fetch_attempts_since_evidence": task.collection.fetch_attempts_since_evidence,
        "evidence_count": task.collection.evidence_count,
    }


def derive_reason_codes(action: str, state: dict) -> list[str]:
    """Derive gap reasons from (action, state); heuristics are labelled derived."""
    gap = state.get("gap_score")
    conflicts = state.get("unresolved_conflicts") or 0
    reasons: list[str] = []
    if action == "web_fetch" or action in ("document_search", "document_read"):
        reasons.append("SOURCE_CONTENT_NOT_ACQUIRED")
    elif action == "evidence_audit":
        reasons.append("EVIDENCE_NOT_VERIFIED")
    elif action in ("fact_save", "fact_supersede", "evidence_save"):
        reasons.append("CLAIM_NOT_VERIFIED")
    elif action in ("evidence_conflict_create", "evidence_conflict_resolve"):
        reasons.append("CONFLICT_UNRESOLVED")
    elif action == "coverage_eval":
        reasons.append("LOW_COVERAGE")
    elif action in ("web_search", "crawl_collect"):
        if gap and gap > 0:
            reasons.append("LOW_COVERAGE")
        if conflicts > 0:
            reasons.append("CONFLICT_UNRESOLVED")
        if not reasons:
            reasons.append("SEARCH_RESULT_NOT_MATERIALIZED")
    return reasons


def reason_summary(reason_codes: list[str]) -> str:
    return "；".join(
        _REASON_SUMMARIES.get(code, code) for code in reason_codes
    )
