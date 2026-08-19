"""Citation-safe public information research report generation."""

from __future__ import annotations

import re
from pathlib import Path

from .audit import verified_support_evidence
from .coverage import current_coverage_fingerprint, latest_coverage
from .evidence import load_document
from .fact import list_active_facts_for_task
from .materials import generate_material_digest
from .models import (
    CoverageSnapshot,
    EvidenceSupport,
    ResearchConclusion,
    ResearchReportInput,
    normalized_statement,
)
from .storage import verify_document_integrity, write_file_atomic
from .task import bind_task_output, load_task


def _slug(value: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", value.lower()).strip("-")[:60]
    return slug or "topic"


_UNSAFE_REPORT_TEXT = re.compile(
    r"https?://|www\.|[<>]|\]\(|\[\d+\]|(?:task|fact|doc|cov|ev|q)-[0-9a-f]",
    re.IGNORECASE,
)


def _fact_ids(conclusion: ResearchConclusion) -> list[str]:
    if conclusion.kind == "inference":
        return list(dict.fromkeys(conclusion.fact_ids))
    return [conclusion.fact_id]


def _statement(conclusion: ResearchConclusion, fact_by_id: dict) -> str:
    if conclusion.kind == "inference":
        return normalized_statement(conclusion.statement)
    return fact_by_id[conclusion.fact_id].statement


def _report_limitations(coverage: CoverageSnapshot) -> list[str]:
    """Mandatory limitation entries derived from the coverage snapshot.

    Single-source facts, uncovered questions, time-scope gaps, unresolved
    conflicts, and source over-concentration must surface in the report
    (run 012: truthful coverage); "未发现额外局限" is only valid when this
    list is empty.
    """
    limitations: list[str] = []
    group_counts: dict[str, int] = {}
    for question in coverage.per_question:
        if question.status != "covered":
            limitations.append(f"问题未完全覆盖：「{question.question}」")
            limitations.extend(question.notes)
        for fact in question.facts:
            if fact.independent_sources == 1 and fact.status != "gap":
                limitations.append(f"单源事实：「{fact.statement}」")
            if fact.time_scope_gap > 0:
                limitations.append(
                    f"时间缺口：「{fact.statement}」缺少时间范围内来源"
                )
            if (
                fact.unresolved_conflicts > 0
                or fact.unresolved_contradictions > 0
            ):
                limitations.append(f"未解决冲突：「{fact.statement}」")
            for group in fact.source_groups:
                group_counts[group] = group_counts.get(group, 0) + 1
    fact_total = sum(q.fact_count for q in coverage.per_question)
    if fact_total >= 3 and group_counts:
        dominant_count = max(group_counts.values())
        if dominant_count / fact_total > 0.5:
            limitations.append("来源过度集中：超过半数事实来自同一来源组")
    return list(dict.fromkeys(limitations))


def generate_research_report(
    cwd: Path,
    task_id: str,
    draft: ResearchReportInput,
) -> dict:
    """Validate structured findings and write the primary research report."""
    task = load_task(cwd, task_id)
    coverage = latest_coverage(cwd, task.id)
    if coverage is None:
        return {
            "ok": False,
            "errors": [
                {
                    "index": -1,
                    "code": "INVALID_INPUT",
                    "message": "生成报告前必须运行 coverage_eval",
                }
            ],
        }

    facts = list_active_facts_for_task(cwd, task.id)
    fact_by_id = {fact.id: fact for fact in facts}
    fact_coverage = {
        fact.fact_id: fact
        for question in coverage.per_question
        for fact in question.facts
    }
    if set(fact_by_id) != set(
        fact_coverage
    ) or coverage.fingerprint != current_coverage_fingerprint(cwd, task.id):
        return {
            "ok": False,
            "errors": [
                {
                    "index": -1,
                    "code": "COVERAGE_STALE",
                    "message": "活动事实已变化，请重新运行 coverage_eval",
                }
            ],
        }
    question_ids = {question.id for question in task.questions}
    indexed: list[tuple[int, str | None, ResearchConclusion]] = []
    index = 0
    errors: list[dict] = []
    for section in draft.sections:
        if section.question_id not in question_ids:
            errors.append(
                {
                    "index": index,
                    "code": "INVALID_INPUT",
                    "message": "报告章节引用了无效问题",
                }
            )
        for conclusion in section.conclusions:
            indexed.append((index, section.question_id, conclusion))
            index += 1
    for conclusion in draft.overall_conclusions:
        indexed.append((index, None, conclusion))
        index += 1
    if not indexed:
        errors.append(
            {
                "index": -1,
                "code": "NO_REPORTABLE_FINDINGS",
                "message": "报告至少需要一条有已验证证据的结论",
            }
        )

    evidence_by_conclusion: list[list[EvidenceSupport]] = []
    for item_index, section_question_id, conclusion in indexed:
        ids = _fact_ids(conclusion)
        conclusion_facts = [fact_by_id.get(fact_id) for fact_id in ids]
        if not ids or any(fact is None for fact in conclusion_facts):
            errors.append(
                {
                    "index": item_index,
                    "code": "INVALID_INPUT",
                    "message": "结论引用了无效或跨任务的事实",
                }
            )
            evidence_by_conclusion.append([])
            continue
        if section_question_id and any(
            fact and fact.question_id != section_question_id
            for fact in conclusion_facts
        ):
            errors.append(
                {
                    "index": item_index,
                    "code": "INVALID_INPUT",
                    "message": "结论不属于当前报告章节",
                }
            )
        evidence = [
            item
            for fact in conclusion_facts
            if fact
            for item in verified_support_evidence(cwd, fact.id)
        ]
        evidence_by_conclusion.append(evidence)
        if any(
            not verified_support_evidence(cwd, fact.id)
            for fact in conclusion_facts
            if fact
        ):
            errors.append(
                {
                    "index": item_index,
                    "code": "INSUFFICIENT_EVIDENCE",
                    "message": "结论引用的事实缺少已验证支持证据",
                }
            )
            continue
        if _UNSAFE_REPORT_TEXT.search(_statement(conclusion, fact_by_id)):
            errors.append(
                {
                    "index": item_index,
                    "code": "INVALID_INPUT",
                    "message": "结论正文不能包含 URL、手写引用或内部 ID",
                }
            )
        if conclusion.kind == "fact" and (
            fact_by_id[conclusion.fact_id].claim_type == "reported"
        ):
            errors.append(
                {
                    "index": item_index,
                    "code": "INVALID_INPUT",
                    "message": "转述型事实必须使用 reported 并注明来源",
                }
            )
        elif conclusion.kind == "fact" and (
            conclusion.fact_id not in fact_coverage
            or fact_coverage[conclusion.fact_id].status != "covered"
        ):
            errors.append(
                {
                    "index": item_index,
                    "code": "INSUFFICIENT_EVIDENCE",
                    "message": "事实结论尚未达到 covered",
                }
            )
        elif conclusion.kind == "inference":
            if not normalized_statement(conclusion.statement) or len(ids) < 2:
                errors.append(
                    {
                        "index": item_index,
                        "code": "INVALID_INPUT",
                        "message": "推断必须提供 statement 和至少两个不同事实",
                    }
                )
            elif any(
                fact_coverage[fact_id].status != "covered" for fact_id in ids
            ):
                errors.append(
                    {
                        "index": item_index,
                        "code": "INSUFFICIENT_EVIDENCE",
                        "message": "推断引用的事实尚未全部达到 covered",
                    }
                )
    section_question_ids = [section.question_id for section in draft.sections]
    if (
        set(section_question_ids) != question_ids
        or len(section_question_ids) != len(question_ids)
        or any(not section.conclusions for section in draft.sections)
    ):
        errors.append(
            {
                "index": -1,
                "code": "INVALID_INPUT",
                "message": "报告必须完整且逐一回答所有核心问题",
            }
        )
    if any(
        question.answer_status not in {"answered", "partial"}
        for question in coverage.per_question
    ):
        errors.append(
            {
                "index": -1,
                "code": "INSUFFICIENT_EVIDENCE",
                "message": "核心问题仍有未回答或存在冲突的内容",
            }
        )
    if indexed and not any(evidence_by_conclusion):
        errors.append(
            {
                "index": -1,
                "code": "NO_REPORTABLE_FINDINGS",
                "message": "没有结论可以解析到已验证支持证据",
            }
        )
    if errors:
        return {"ok": False, "errors": errors}

    source_numbers: dict[str, int] = {}
    for evidence in (
        item for group in evidence_by_conclusion for item in group
    ):
        if evidence.document_id not in source_numbers:
            source_numbers[evidence.document_id] = len(source_numbers) + 1
    citations = [
        "".join(
            f"[{source_numbers[document_id]}]"
            for document_id in dict.fromkeys(
                evidence.document_id for evidence in evidence_group
            )
        )
        for evidence_group in evidence_by_conclusion
    ]
    digest = generate_material_digest(cwd, task.id)
    question_by_id = {question.id: question for question in task.questions}
    lines = [
        f"# 公开信息调研报告：{task.topic}",
        "",
        "## 执行摘要",
        "",
        "以下核心发现均由已归档并通过审核的公开材料支持：",
    ]
    summary_offset = 0
    for section in draft.sections:
        conclusion = section.conclusions[0]
        prefix = (
            "据以下公开来源，"
            if conclusion.kind == "reported"
            else f"分析判断（{conclusion.confidence}）："
            if conclusion.kind == "inference"
            else ""
        )
        lines.append(
            f"- {question_by_id[section.question_id].text}：{prefix}"
            f"{_statement(conclusion, fact_by_id)}{citations[summary_offset]}"
        )
        summary_offset += len(section.conclusions)
    lines.extend(
        [
            "",
            "## 调研范围",
            "",
            f"- 主题：{task.topic}",
            f"- 目标：{task.objective or '围绕主题开展公开信息调研'}",
            f"- 时间：{task.scope.time_range or '未限定'}",
            f"- 地区：{'、'.join(task.scope.geography) or '未限定'}",
            f"- 语言：{'、'.join(task.scope.languages) or '未限定'}",
            f"- 报告深度：{task.report_depth}",
            f"- 核心问题：{'；'.join(question.text for question in task.questions)}",
        ]
    )
    conclusion_offset = 0
    for section in draft.sections:
        lines.extend(
            ["", f"## {question_by_id[section.question_id].text}", ""]
        )
        for conclusion in section.conclusions:
            statement = _statement(conclusion, fact_by_id)
            prefix = (
                "据以下公开来源，"
                if conclusion.kind == "reported"
                else f"分析判断（{conclusion.confidence}）："
                if conclusion.kind == "inference"
                else ""
            )
            lines.append(
                f"- {prefix}{statement}{citations[conclusion_offset]}"
            )
            if conclusion.kind == "inference":
                basis = "；".join(
                    fact_by_id[fact_id].statement
                    for fact_id in _fact_ids(conclusion)
                )
                lines.append(
                    f"  - 依据已验证事实：{basis}{citations[conclusion_offset]}"
                )
            conclusion_offset += 1

    lines.extend(["", "## 综合结论", ""])
    for conclusion in draft.overall_conclusions:
        statement = _statement(conclusion, fact_by_id)
        prefix = (
            "据以下公开来源，"
            if conclusion.kind == "reported"
            else f"分析判断（{conclusion.confidence}）："
            if conclusion.kind == "inference"
            else ""
        )
        lines.append(f"- {prefix}{statement}{citations[conclusion_offset]}")
        if conclusion.kind == "inference":
            basis = "；".join(
                fact_by_id[fact_id].statement
                for fact_id in _fact_ids(conclusion)
            )
            lines.append(
                f"  - 依据已验证事实：{basis}{citations[conclusion_offset]}"
            )
        conclusion_offset += 1

    lines.extend(["", "## 分歧与不确定性", ""])
    uncertainties = [
        note
        for question in coverage.per_question
        if question.answer_status != "answered"
        for note in question.notes
    ]
    lines.extend(
        f"- {item}" for item in (uncertainties or ["未发现已登记的重大分歧。"])
    )
    lines.extend(["", "## 局限", ""])
    limitations = _report_limitations(coverage) + list(digest.gaps)
    lines.extend(f"- {item}" for item in (limitations or ["未发现额外局限。"]))
    lines.extend(["", "## 材料导读", "", digest.overview])
    if digest.key_points:
        lines.extend(["", "### 内容摘要", ""])
        lines.extend(f"- {point}" for point in digest.key_points)
    for material in digest.materials:
        lines.append(
            f"- {'★' * material.rating}{'☆' * (5 - material.rating)} "
            f"[{material.description}]({material.canonical_url})"
        )
    lines.extend(["", "## 来源目录", ""])
    document_hashes: dict[str, str] = {}
    for document_id, number in source_numbers.items():
        document = load_document(cwd, document_id)
        verify_document_integrity(cwd, document)
        document_hashes[document.id] = document.text_sha256
        lines.append(
            f"[{number}] {document.source_group}，"
            f"{document.publish_time or '发布时间未知'}，{document.final_url}"
        )

    relative_path = f"output/{_slug(task.topic)}-research-report.md"
    write_file_atomic(cwd, relative_path, "\n".join(lines) + "\n")
    bind_task_output(
        cwd,
        task.id,
        "report",
        relative_path,
        coverage,
        document_hashes=document_hashes,
    )
    return {"ok": True, "path": str(cwd / relative_path), "errors": []}
