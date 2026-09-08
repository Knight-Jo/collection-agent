"""Context manager and citation tests (T15)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from intel_agent.context.formatter import validate_citation_ids
from intel_agent.context.manager import ContextManager
from intel_agent.contracts.documents import (
    Chunk,
    DocumentIdentity,
    EvidenceBlock,
    ExtractResult,
    Locator,
    NormalizationInput,
)
from intel_agent.contracts.errors import DomainError
from intel_agent.contracts.research import (
    ContextPackage,
    ContextRequest,
)
from intel_agent.contracts.resources import Resource, ResourceOrigin
from intel_agent.indexing.service import IndexingService
from intel_agent.indexing.tokenize import TiktokenCounter
from intel_agent.normalization import Normalizer
from intel_agent.runtime.config import ContextConfig, IndexingConfig


def _seed(material_store, task_id, doc_id, text):

    content_hash = doc_id
    resource = Resource(
        resource_id=f"res-{doc_id}",
        content_hash=content_hash,
        byte_length=0,
        media_type="text/plain",
        content_ref=content_hash,
        origin=ResourceOrigin(acquired_at=datetime.now(UTC)),
        created_at=datetime.now(UTC),
    )
    material_store.register_resource(resource)
    identity = material_store.resolve_identity(doc_id)
    rev = material_store.resolve_revision(
        identity.document_id, f"res-{doc_id}"
    )
    normalizer = Normalizer(version="1")
    result = ExtractResult(
        resource_id=f"res-{doc_id}",
        blocks=[
            EvidenceBlock(
                block_id="x",
                text=text,
                block_type="paragraph",
                locator=Locator(page=1),
                origin_method="native_text",
                backend_id="b",
                backend_version="1",
            )
        ],
        coverage=[],
        status="success",
        extraction_profile_id="ep",
    )
    inp = NormalizationInput(
        result=result,
        resource_id=f"res-{doc_id}",
        identity=DocumentIdentity(
            document_id=identity.document_id, source_key=doc_id
        ),
        revision_id=rev,
    )
    document = normalizer.normalize(inp)
    artifact_id = material_store.save_document(task_id, document)
    asyncio.run(
        IndexingService(
            material_store, IndexingConfig(), TiktokenCounter()
        ).index(artifact_id)
    )
    return artifact_id


def test_context_respects_budget_and_builds_citations(material_store):
    task = material_store.create_task("动力电池回收")
    _seed(
        material_store,
        task.task_id,
        "https://a.example/x",
        "动力电池回收产业近年持续增长，梯次利用与湿法冶金回收路线"
        "在不同场景下逐步成熟，头部企业加速布局产能。",
    )
    _seed(
        material_store,
        task.task_id,
        "https://b.example/y",
        "回收技术取得重要进展，锂镍钴的回收率已提升至九成以上，"
        "成本与环保合规成为规模化竞争的关键变量。",
    )

    counter = TiktokenCounter()
    manager = ContextManager(material_store, counter, ContextConfig())
    package = asyncio.run(
        manager.build(
            ContextRequest(
                task_id=task.task_id, query="动力电池", max_tokens=96
            )
        )
    )
    assert package.token_count <= 96
    assert package.citations
    assert package.token_count == counter.count(package.formatted_text)
    assert package.citations[0].citation_id == "C1"


def test_validate_citation_ids_rejects_unknown(material_store):
    package = ContextPackage(
        task_id="t",
        query="q",
        scope_id="s",
        formatted_text="",
        token_count=0,
    )
    with pytest.raises(DomainError) as raised:
        validate_citation_ids(["C999"], package)
    assert raised.value.code == "INVALID_DECISION"


def _chunk(artifact_id: str, ordinal: int) -> Chunk:
    return Chunk(
        chunk_id=f"{artifact_id}-{ordinal}",
        artifact_id=artifact_id,
        document_id=f"doc-{artifact_id}",
        revision_id="rev",
        text="正文内容" * 20,
        chunk_profile_id="p",
        ordinal=ordinal,
    )


def test_diversify_caps_chunks_per_artifact():
    # ranked order: five chunks from artifact A then two from B
    ranked = [_chunk("A", i) for i in range(1, 6)] + [
        _chunk("B", i) for i in range(1, 3)
    ]
    diversified = ContextManager._diversify(ranked, cap=2)
    order = [c.artifact_id for c in diversified]
    # B's chunks move ahead of A's overflow; A keeps its first two slots
    assert order == ["A", "A", "B", "B", "A", "A", "A"]


def test_diversify_keeps_order_below_cap():
    ranked = [_chunk("A", 1), _chunk("B", 1), _chunk("C", 1)]
    assert [c.artifact_id for c in ContextManager._diversify(ranked, 3)] == [
        "A",
        "B",
        "C",
    ]
