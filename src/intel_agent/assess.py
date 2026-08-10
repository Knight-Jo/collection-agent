"""Structured assessment generation (port of assess.ts)."""

from __future__ import annotations

import re
from pathlib import Path

from .audit import verified_support_evidence
from .coverage import latest_coverage
from .evidence import list_evidence_for_task, load_document
from .fact import list_active_facts_for_task
from .models import AssessmentConclusion, EvidenceSupport, IntelError, normalized_statement
from .storage import verify_document_integrity, write_file_atomic
from .task import bind_task_output, load_task


def _slug(value: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", value.lower()).strip("-")[:60]
    return slug or "topic"


def _fact_ids_for(conclusion: AssessmentConclusion) -> list[str]:
    return list(dict.fromkeys(conclusion.fact_ids)) if conclusion.kind == "inference" else [conclusion.fact_id]


def _append_evidence(cwd: Path, lines: list[str], evidence: list[EvidenceSupport], label: str) -> None:
    if not evidence:
        return
    lines.append(f"- {label}:")
    for item in evidence:
        document = load_document(cwd, item.document_id)
        lines.append(f"  - {item.id}: {document.source_group} — {document.final_url}")
        lines.append(f"    - 引文（行 {item.line_start}–{item.line_end}）: {item.quote.replace(chr(10), ' ')}")


def generate_assessment(cwd: Path, task_id: str, conclusions: list[AssessmentConclusion]) -> dict:
    task = load_task(cwd, task_id)
    coverage = latest_coverage(cwd, task.id)
    errors: list[dict] = []
    if coverage is None:
        errors.append({"index": -1, "code": "INVALID_INPUT", "message": "研判前必须运行 coverage_eval"})
    if not conclusions:
        errors.append({"index": -1, "code": "INVALID_INPUT", "message": "至少需要一条结构化结论"})
    facts = list_active_facts_for_task(cwd, task.id)
    fact_by_id = {f.id: f for f in facts}
    evidence = list_evidence_for_task(cwd, task.id)
    evidence_by_fact: dict[str, list[EvidenceSupport]] = {}
    for item in evidence:
        evidence_by_fact.setdefault(item.fact_id, []).append(item)
    for document_id in {e.document_id for e in evidence}:
        verify_document_integrity(cwd, load_document(cwd, document_id))

    for index, conclusion in enumerate(conclusions):
        fact_ids = _fact_ids_for(conclusion)
        conclusion_facts = [fact_by_id.get(fid) for fid in fact_ids]
        if not fact_ids or any(f is None for f in conclusion_facts):
            errors.append({"index": index, "code": "INVALID_INPUT", "message": "结论引用了无效或跨任务的 fact_id"})
            continue
        if any(len(verified_support_evidence(cwd, f.id)) == 0 for f in conclusion_facts if f):
            errors.append({"index": index, "code": "INSUFFICIENT_EVIDENCE", "message": "结论引用的 Fact 缺少支持证据"})
            continue
        if conclusion.kind == "fact":
            fact_coverage = next(
                (fc for q in (coverage.per_question if coverage else []) for fc in q.facts if fc.fact_id == conclusion.fact_id),
                None,
            )
            if fact_coverage is None or fact_coverage.status != "covered":
                errors.append({"index": index, "code": "INSUFFICIENT_EVIDENCE", "message": "事实结论尚未达到 covered"})
        elif conclusion.kind == "reported":
            if not conclusion.attribution.strip():
                errors.append({"index": index, "code": "INVALID_INPUT", "message": "单源转述必须提供 attribution"})
        elif (
            not normalized_statement(conclusion.statement)
            or not conclusion.rationale.strip()
            or conclusion.confidence not in ("high", "medium", "low")
        ):
            errors.append({"index": index, "code": "INVALID_INPUT", "message": "推断必须提供 statement、rationale、confidence 和 fact_ids"})
    if errors:
        return {"ok": False, "errors": errors}

    lines = [
        f"# 研判报告：{task.topic}",
        "",
        f"- 任务 ID: {task.id}",
        f"- 覆盖快照: {coverage.id}",
        f"- 充分性: {coverage.level}",
        "",
    ]
    for conclusion in conclusions:
        conclusion_facts = [fact_by_id[fid] for fid in _fact_ids_for(conclusion)]
        statement = normalized_statement(conclusion.statement) if conclusion.kind == "inference" else conclusion_facts[0].statement
        label = "事实" if conclusion.kind == "fact" else "单源转述" if conclusion.kind == "reported" else "推断"
        lines.append(f"## [{label}] {statement}")
        lines.append("")
        if conclusion.kind == "reported":
            lines.append(f"- 归属: {conclusion.attribution.strip()}")
        if conclusion.kind == "inference":
            lines.append(f"- 置信度: {conclusion.confidence}")
            lines.append(f"- 推理依据: {conclusion.rationale.strip()}")
        for fact in conclusion_facts:
            lines.append(f"- 依据事实: {fact.statement} ({fact.id})")
            _append_evidence(cwd, lines, verified_support_evidence(cwd, fact.id), "支持证据")
            _append_evidence(cwd, lines, [e for e in evidence_by_fact.get(fact.id, []) if e.relation == "contradicts"], "相反证据")
        lines.append("")
    relative_path = f"output/{_slug(task.topic)}-assessment.md"
    write_file_atomic(cwd, relative_path, "\n".join(lines) + "\n")
    bind_task_output(cwd, task.id, "assessment", relative_path, coverage)
    return {"ok": True, "path": str(cwd / relative_path), "errors": []}
