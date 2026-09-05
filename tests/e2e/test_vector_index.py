"""Real Qdrant + embedding vector roundtrip (spec A18/A19/A21 vector path)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from intel_agent.contracts.research import MaterialScope
from intel_agent.indexing.embedding import HttpEmbeddingClient
from intel_agent.indexing.models import VectorPoint
from intel_agent.indexing.qdrant import QdrantVectorIndex, vector_point_id
from intel_agent.runtime.config import EmbeddingConfig

EMBED_URL = "http://127.0.0.1:8001/v1"
QDRANT_URL = "http://127.0.0.1:6333"


def _services_ready() -> bool:
    try:
        httpx.get(f"{EMBED_URL}/models", timeout=2).raise_for_status()
        httpx.get(f"{QDRANT_URL}/collections", timeout=2).raise_for_status()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.real_backend
async def test_vector_upsert_search_delete_roundtrip():
    if not _services_ready():
        pytest.skip("vllm embedding or qdrant not reachable")
    cfg = EmbeddingConfig(
        model_id="qwen3-embedding-0.6b",
        base_url=EMBED_URL,
        dimension=1024,
    )
    pid = cfg.profile_id()
    client = httpx.AsyncClient(base_url=EMBED_URL, trust_env=False)
    embedding = HttpEmbeddingClient(
        client, cfg.model_id, profile_id=pid, dimension=cfg.dimension
    )
    vector_index = QdrantVectorIndex(QDRANT_URL)
    try:
        batch = await embedding.embed(["动力电池回收产业持续增长"], pid)
        assert batch.dimension == 1024
        point = VectorPoint(
            point_id=vector_point_id("chunk-test", pid),
            chunk_id="chunk-test",
            artifact_id="art-test",
            vector=batch.vectors[0],
            payload={"artifact_id": "art-test", "chunk_id": "chunk-test"},
        )
        await vector_index.upsert([point], pid)
        scope = MaterialScope(
            scope_id="s",
            task_id="t",
            artifact_ids=["art-test"],
            created_at=datetime.now(UTC),
        )
        query = (await embedding.embed(["动力电池"], pid)).vectors[0]
        matches = await vector_index.search(query, scope, pid, 3)
        assert matches, "no vector matches"
        assert matches[0].chunk_id == "chunk-test"
        await vector_index.delete([point.point_id], pid)
    finally:
        await vector_index.close()
        await client.aclose()


def test_vector_point_id_is_stable_uuid():
    value = vector_point_id("chunk-a", "embedding-v1")
    assert value == vector_point_id("chunk-a", "embedding-v1")
    assert value != vector_point_id("chunk-a", "embedding-v2")
    import uuid

    uuid.UUID(value)
