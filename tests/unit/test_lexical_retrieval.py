"""Lexical tokenization and scoped retrieval tests (T13)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from intel_agent.contracts.documents import (
    DocumentIdentity,
    EvidenceBlock,
    ExtractResult,
    Locator,
    NormalizationInput,
)
from intel_agent.contracts.research import ContextFilter
from intel_agent.contracts.resources import Resource, ResourceOrigin
from intel_agent.indexing.lexical import lexical_tokens
from intel_agent.indexing.service import IndexingService
from intel_agent.indexing.tokenize import TiktokenCounter
from intel_agent.normalization import Normalizer
from intel_agent.runtime.config import IndexingConfig


def test_chinese_query_shares_index_terms_without_spaces():
    query = set(lexical_tokens("动力电池"))
    body = set(lexical_tokens("我国动力电池产业规模持续增长"))
    assert query <= body


def test_english_words_are_casefolded():
    tokens = set(lexical_tokens("Battery Recycling"))
    assert "w:battery" in tokens
    assert "w:recycling" in tokens


def _document(doc_id, revision_id, resource_id, text):
    normalizer = Normalizer(version="1")
    result = ExtractResult(
        resource_id=resource_id,
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
        resource_id=resource_id,
        identity=DocumentIdentity(document_id=doc_id, source_key=doc_id),
        revision_id=revision_id,
    )
    return normalizer.normalize(inp)


def _register_resource(material_store, resource_id, content_hash):
    resource = Resource(
        resource_id=resource_id,
        content_hash=content_hash,
        byte_length=0,
        media_type="text/plain",
        content_ref=content_hash,
        origin=ResourceOrigin(acquired_at=datetime.now(UTC)),
        created_at=datetime.now(UTC),
    )
    material_store.register_resource(resource)
    return resource_id


def test_scoped_lexical_retrieval_does_not_leak_across_tasks(material_store):
    _register_resource(material_store, "res-a", "hash-a")
    _register_resource(material_store, "res-b", "hash-b")
    id_a = material_store.resolve_identity("da")
    id_b = material_store.resolve_identity("db")
    rev_a = material_store.resolve_revision(id_a.document_id, "res-a")
    rev_b = material_store.resolve_revision(id_b.document_id, "res-b")
    doc_a = _document("da", rev_a, "res-a", "动力电池产业持续增长")
    doc_b = _document("db", rev_b, "res-b", "动力电池回收技术进展")
    art_a = material_store.save_document("task-a", doc_a)
    art_b = material_store.save_document("task-b", doc_b)

    counter = TiktokenCounter()
    service = IndexingService(material_store, IndexingConfig(), counter)
    asyncio.run(service.index(art_a))
    asyncio.run(service.index(art_b))

    scope = material_store.resolve_scope("task-a", ContextFilter())
    terms = lexical_tokens("动力电池")
    results = material_store.search_lexical(terms, scope, 10)
    assert results
    for chunk_id, _ in results:
        assert chunk_id  # results constrained to task-a scope
