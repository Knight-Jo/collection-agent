"""Evidence package Markdown generation (port of package.ts)."""

from __future__ import annotations

import re
from pathlib import Path

from .audit import review_for_evidence
from .coverage import latest_coverage
from .evidence import list_evidence_for_fact, load_document
from .fact import list_active_facts_for_question, list_facts_for_task
from .models import EvidenceSupport, IntelError
from .storage import verify_document_integrity, write_file_atomic
from .task import bind_task_output, load_task


def _slug(value: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", value.lower()).strip("-")[:60]
    return slug or "topic"


def _append_evidence(cwd: Path, lines: list[str], label: str, evidence: list[EvidenceSupport]) -> None:
    if not evidence:
        return
    lines.append("")
    lines.append(f"#### {label}")
    for item in evidence:
        document = load_document(cwd, item.document_id)
        verify_document_integrity(cwd, document)
        lines.append("")
        lines.append(f"- 证据 ID: {item.id}")
        lines.append(f"- 文档 ID: {document.id}")
        lines.append(f"- 来源: {document.title} ({document.final_url})")
        lines.append(f"- 来源组: {document.source_group} / {document.source_type}")
        lines.append(f"- 发布时间: {document.publish_time or '未知'}")
        lines.append(f"- 正文 SHA-256: {document.text_sha256}")
        lines.append(f"- 定位: 行 {item.line_start}–{item.line_end}")
        lines.append(f"- 引文: > {item.quote.replace(chr(10), chr(10) + '  > ')}")
        if item.relation == "supports":
            review = review_for_evidence(cwd, item.id)
            lines.append(f"- 审核结论: {review.verdict if review else 'pending'}")
            if review:
                lines.append(f"- 审核理由: {review.reason}")
                lines.append(f"- 未支持部分: {'；'.join(review.unsupported_parts) or '无'}")
                lines.append(f"- 审核模型: {review.judge_provider}/{review.judge_model} ({review.prompt_version})")


def generate_package(cwd: Path, task_id: str) -> dict:
    task = load_task(cwd, task_id)
    coverage = latest_coverage(cwd, task.id)
    if coverage is None:
        raise IntelError("INVALID_INPUT", "生成证据包前必须运行 coverage_eval")
    lines = [
        f"# 证据包：{task.topic}",
        "",
        f"- 任务 ID: {task.id}",
        f"- 覆盖快照: {coverage.id}",
        f"- 充分性: {coverage.level}",
        f"- 覆盖缺口分数: {coverage.gap_score}",
        f"- 停止原因: {coverage.stop_reason or '继续定向补充'}",
        "",
        "> 所有引文均已在本地规范化正文中精确定位；SHA-256 用于检测采集后篡改。",
    ]
    evidence_count = 0
    for question in task.questions:
        question_coverage = next(qc for qc in coverage.per_question if qc.question_id == question.id)
        lines.append("")
        lines.append(f"## {question.text}")
        lines.append("")
        lines.append(f"- 问题 ID: {question.id}")
        lines.append(f"- 覆盖状态: {question_coverage.status}")
        for fact in list_active_facts_for_question(cwd, task.id, question.id):
            fact_coverage = next(fc for fc in question_coverage.facts if fc.fact_id == fact.id)
            evidence = list_evidence_for_fact(cwd, fact.id)
            supports = [e for e in evidence if e.relation == "supports" and (r := review_for_evidence(cwd, e.id)) and r.verdict == "full"]
            candidates = [e for e in evidence if e.relation == "supports" and (r := review_for_evidence(cwd, e.id)) and r.verdict != "full"]
            contradicts = [e for e in evidence if e.relation == "contradicts"]
            evidence_count += len(evidence)
            lines.append("")
            lines.append(f"### {fact.statement}")
            lines.append("")
            lines.append(f"- 事实 ID: {fact.id}")
            lines.append(f"- 事实覆盖状态: {fact_coverage.status}")
            lines.append(f"- 独立来源组: {fact_coverage.independent_sources}")
            lines.append(f"- 未消解矛盾: {fact_coverage.unresolved_conflicts + fact_coverage.unresolved_contradictions}")
            _append_evidence(cwd, lines, "已验证支持证据", supports)
            _append_evidence(cwd, lines, "候选支持证据（不计入覆盖）", candidates)
            _append_evidence(cwd, lines, "反驳证据", contradicts)
    superseded = [f for f in list_facts_for_task(cwd, task.id) if f.status == "superseded"]
    if superseded:
        lines.append("")
        lines.append("## 已替换事实（审计历史）")
        for fact in superseded:
            evidence = list_evidence_for_fact(cwd, fact.id)
            evidence_count += len(evidence)
            lines.append("")
            lines.append(f"### {fact.statement}")
            lines.append("")
            lines.append(f"- 事实 ID: {fact.id}")
            lines.append(f"- 替换原因: {fact.supersession_reason}")
            lines.append(f"- 替代事实: {', '.join(fact.superseded_by)}")
            _append_evidence(cwd, lines, "历史候选支持", [e for e in evidence if e.relation == "supports"])
            _append_evidence(cwd, lines, "历史反驳证据", [e for e in evidence if e.relation == "contradicts"])
    relative_path = f"output/{_slug(task.topic)}-evidence-package.md"
    write_file_atomic(cwd, relative_path, "\n".join(lines) + "\n")
    bind_task_output(cwd, task.id, "package", relative_path, coverage)
    return {"path": str(cwd / relative_path), "evidence_count": evidence_count, "coverage_id": coverage.id}
