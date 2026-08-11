"""Evidence CRUD with quote location (port of evidence.ts)."""

from __future__ import annotations

from pathlib import Path

from .fact import load_fact
from .models import EvidenceSupport, IntelDocument, IntelError, utc_now
from .storage import (
    intel_path,
    list_json,
    read_json,
    sha256,
    verify_document_integrity,
    workspace_path,
    write_json_atomic,
)


def load_document(cwd: Path, document_id: str) -> IntelDocument:
    document = IntelDocument.model_validate(
        read_json(cwd, f"documents/{document_id}.json")
    )
    if document.id != document_id:
        raise IntelError(
            "STORAGE_CORRUPT", f"文档文件名与记录 ID 不匹配: {document_id}"
        )
    return document


def normalize_quote(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _require_successful_extraction(document: IntelDocument) -> None:
    if document.extraction_status != "complete":
        raise IntelError(
            "EXTRACTION_UNAVAILABLE",
            f"文档正文提取未成功: {document.id}",
        )


def _evidence_id(
    # Line range is part of the ID: the same quote at a different position is
    # a different evidence record, so document revisions can't alias quotes.
    fact_id: str,
    document_id: str,
    relation: str,
    line_start: int,
    line_end: int,
    quote: str,
) -> str:
    return f"ev-{sha256(f'{fact_id}\n{document_id}\n{relation}\n{line_start}-{line_end}\n{quote}')[:16]}"


def locate_quote(
    cwd: Path, document: IntelDocument, quote: str
) -> tuple[int, int]:
    text = (
        workspace_path(cwd, document.text_path)
        .read_text(encoding="utf-8")
        .replace("\r\n", "\n")
    )
    offset = text.find(quote)
    if offset < 0:
        raise IntelError(
            "QUOTE_NOT_FOUND", f"引文不在文档正文中: {document.id}"
        )
    line_start = text[:offset].count("\n") + 1
    return line_start, line_start + quote.count("\n")


def verify_evidence(cwd: Path, evidence: EvidenceSupport) -> EvidenceSupport:
    if (
        not evidence.id
        or not evidence.task_id
        or not evidence.fact_id
        or not evidence.document_id
    ):
        raise IntelError("STORAGE_CORRUPT", "证据记录不匹配")
    if evidence.relation not in ("supports", "contradicts"):
        raise IntelError("STORAGE_CORRUPT", "证据记录不匹配")
    fact = load_fact(cwd, evidence.fact_id)
    document = load_document(cwd, evidence.document_id)
    verify_document_integrity(cwd, document)
    _require_successful_extraction(document)
    quote = normalize_quote(evidence.quote)
    try:
        line_start, line_end = locate_quote(cwd, document, quote)
    except IntelError as error:
        if error.code == "QUOTE_NOT_FOUND":
            raise IntelError(
                "STORAGE_CORRUPT", f"证据记录不匹配: {evidence.id}"
            ) from error
        raise
    if (
        not quote
        or evidence.task_id != fact.task_id
        or evidence.quote != quote
        or evidence.line_start != line_start
        or evidence.line_end != line_end
        or evidence.id
        != _evidence_id(
            evidence.fact_id,
            evidence.document_id,
            evidence.relation,
            line_start,
            line_end,
            quote,
        )
    ):
        raise IntelError("STORAGE_CORRUPT", f"证据记录不匹配: {evidence.id}")
    return evidence


def load_evidence(cwd: Path, evidence_id: str) -> EvidenceSupport:
    evidence = verify_evidence(
        cwd,
        EvidenceSupport.model_validate(
            read_json(cwd, f"evidence/{evidence_id}.json")
        ),
    )
    if evidence.id != evidence_id:
        raise IntelError(
            "STORAGE_CORRUPT", f"证据文件名与记录 ID 不匹配: {evidence_id}"
        )
    return evidence


def list_evidence_for_task(cwd: Path, task_id: str) -> list[EvidenceSupport]:
    return [
        verify_evidence(cwd, EvidenceSupport.model_validate(item))
        for item in list_json(cwd, "evidence")
        if item.get("task_id") == task_id
    ]


def list_evidence_for_fact(cwd: Path, fact_id: str) -> list[EvidenceSupport]:
    fact = load_fact(cwd, fact_id)
    return [
        e
        for e in list_evidence_for_task(cwd, fact.task_id)
        if e.fact_id == fact.id
    ]


def save_evidence(
    cwd: Path,
    fact_id: str,
    document_id: str,
    relation: str,
    quote: str,
    notes: str | None = None,
) -> EvidenceSupport:
    fact = load_fact(cwd, fact_id)
    if relation not in ("supports", "contradicts"):
        raise IntelError("INVALID_INPUT", "relation 无效")
    quote = normalize_quote(quote)
    if not quote:
        raise IntelError("INVALID_INPUT", "quote 不能为空")
    document = load_document(cwd, document_id)
    verify_document_integrity(cwd, document)
    _require_successful_extraction(document)
    line_start, line_end = locate_quote(cwd, document, quote)
    id_ = _evidence_id(
        fact.id, document.id, relation, line_start, line_end, quote
    )
    if intel_path(cwd, f"evidence/{id_}.json").exists():
        return load_evidence(cwd, id_)
    evidence = EvidenceSupport(
        id=id_,
        task_id=fact.task_id,
        fact_id=fact.id,
        document_id=document.id,
        relation=relation,
        quote=quote,
        line_start=line_start,
        line_end=line_end,
        notes=(notes or "").strip(),
        created_at=utc_now(),
    )
    write_json_atomic(cwd, f"evidence/{id_}.json", evidence.model_dump())
    return evidence
