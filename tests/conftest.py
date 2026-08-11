"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from intel_agent.fetch import canonicalize_url
from intel_agent.models import IntelDocument, SufficiencyCriteria
from intel_agent.security import source_group_of
from intel_agent.source import source_type_for_domain
from intel_agent.storage import sha256, write_file_atomic, write_json_atomic
from intel_agent.task import create_task

DEFAULT_CRITERIA = SufficiencyCriteria(
    min_independent_sources=2,
    min_high_quality_sources=1,
    recency_days=90,
    require_recency=False,
)


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    from intel_agent.storage import ensure_intel_dirs

    ensure_intel_dirs(tmp_path)
    return tmp_path


def new_task(
    cwd: Path,
    questions: list[str] | None = None,
    criteria: SufficiencyCriteria = DEFAULT_CRITERIA,
):
    return create_task(
        cwd,
        "测试主题",
        questions
        or ["问题甲：测试主题的现状如何", "问题乙：测试主题的进展如何"],
        criteria,
    )


def make_document(
    cwd: Path,
    text: str,
    url: str = "https://example.com/news/1",
    publish_time: str | None = None,
) -> IntelDocument:
    canonical = canonicalize_url(url)
    raw = text.encode("utf-8")
    raw_sha = sha256(raw)
    doc_id = f"doc-{sha256(f'{canonical}\n{raw_sha}')[:16]}"
    raw_path = f"data/raw/{doc_id}.raw"
    text_path = f"data/raw/{doc_id}.txt"
    write_file_atomic(cwd, raw_path, raw)
    write_file_atomic(cwd, text_path, text)
    from urllib.parse import urlparse

    hostname = urlparse(url).hostname or ""
    document = IntelDocument(
        id=doc_id,
        requested_url=url,
        final_url=url,
        canonical_url=canonical,
        title="测试文档",
        content_type="text/html",
        publish_time=publish_time,
        publish_time_source="meta" if publish_time else "unknown",
        collected_at="2026-01-01T00:00:00+00:00",
        source_type=source_type_for_domain(hostname),
        source_group=source_group_of(url),
        raw_path=raw_path,
        raw_sha256=raw_sha,
        text_path=text_path,
        text_sha256=sha256(text),
        injection_warnings=[],
    )
    write_json_atomic(cwd, f"documents/{doc_id}.json", document.model_dump())
    return document


def save_evidence(
    cwd: Path,
    fact_id: str,
    document: IntelDocument | str,
    relation: str,
    quote: str,
    notes: str = "",
):
    from intel_agent.evidence import save_evidence as _save

    document_id = (
        document.id if isinstance(document, IntelDocument) else document
    )
    return _save(cwd, fact_id, document_id, relation, quote, notes)


async def fake_judge(fact, evidence):
    """默认全部判 full。"""
    return [
        {
            "evidence_id": e.id,
            "verdict": "full",
            "reason": "引文完整支持 Fact",
            "unsupported_parts": [],
        }
        for e in evidence
    ]
