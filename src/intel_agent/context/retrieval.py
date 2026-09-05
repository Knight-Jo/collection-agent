"""Context retrieval: direct / lexical / vector / hybrid (spec §10)."""

from __future__ import annotations

from ..contracts.documents import Chunk, RetrievalHit
from ..contracts.research import MaterialScope
from ..indexing.lexical import lexical_tokens
from ..storage.materials import MaterialStore

RRF_CONSTANT = 60


class DirectRetriever:
    def __init__(self, store: MaterialStore) -> None:
        self.store = store

    async def retrieve(
        self, query: str, scope: MaterialScope, top_k: int
    ) -> list[RetrievalHit]:
        chunks = self.store.read_chunks(scope)
        return [
            RetrievalHit(chunk=chunk, rank=i + 1, retrieval_method="direct")
            for i, chunk in enumerate(chunks[:top_k])
        ]


class LexicalRetriever:
    def __init__(self, store: MaterialStore) -> None:
        self.store = store

    async def retrieve(
        self, query: str, scope: MaterialScope, top_k: int
    ) -> list[RetrievalHit]:
        terms = list(dict.fromkeys(lexical_tokens(query)))
        results = self.store.search_lexical(terms, scope, top_k)
        if not results:
            return []
        score_by_id = dict(results)
        chunks = {
            c.chunk_id: c for c in self.store.get_chunks(list(score_by_id))
        }
        return [
            RetrievalHit(
                chunk=chunks[chunk_id],
                rank=i + 1,
                score=score,
                retrieval_method="lexical",
            )
            for i, (chunk_id, score) in enumerate(results)
            if chunk_id in chunks
        ]


class VectorRetriever:
    def __init__(
        self, store: MaterialStore, embedding_client, vector_index
    ) -> None:
        self.store = store
        self.embedding_client = embedding_client
        self.vector_index = vector_index

    async def retrieve(
        self,
        query: str,
        scope: MaterialScope,
        profile_id: str,
        top_k: int,
    ) -> list[RetrievalHit]:
        batch = await self.embedding_client.embed([query], profile_id)
        matches = await self.vector_index.search(
            batch.vectors[0], scope, profile_id, top_k
        )
        chunks = {
            c.chunk_id: c
            for c in self.store.get_chunks([m.chunk_id for m in matches])
        }
        return [
            RetrievalHit(
                chunk=chunks[m.chunk_id],
                rank=i + 1,
                score=m.score,
                retrieval_method="vector",
            )
            for i, m in enumerate(matches)
            if m.chunk_id in chunks
        ]


class HybridRetriever:
    def __init__(
        self, lexical: LexicalRetriever, vector: VectorRetriever | None
    ) -> None:
        self.lexical = lexical
        self.vector = vector

    async def retrieve(
        self,
        query: str,
        scope: MaterialScope,
        top_k: int,
        vector_profile_id: str | None = None,
    ) -> tuple[list[RetrievalHit], list[str]]:
        warnings: list[str] = []
        lexical_hits = await self.lexical.retrieve(query, scope, top_k)
        vector_hits: list[RetrievalHit] = []
        if self.vector is not None and vector_profile_id:
            try:
                vector_hits = await self.vector.retrieve(
                    query, scope, vector_profile_id, top_k
                )
            except Exception as error:  # noqa: BLE001
                warnings.append(
                    f"vector degraded to lexical: {type(error).__name__}"
                )
        else:
            warnings.append("vector not configured; using lexical")
        return _rrf_fuse(lexical_hits, vector_hits, top_k), warnings


def _rrf_fuse(
    left: list[RetrievalHit], right: list[RetrievalHit], top_k: int
) -> list[RetrievalHit]:
    if not right:
        return _dedup(left)[:top_k]
    scores: dict[str, float] = {}
    by_chunk: dict[str, Chunk] = {}
    for hits in (left, right):
        for hit in hits:
            scores[hit.chunk.chunk_id] = scores.get(
                hit.chunk.chunk_id, 0.0
            ) + 1.0 / (RRF_CONSTANT + hit.rank)
            by_chunk[hit.chunk.chunk_id] = hit.chunk
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return [
        RetrievalHit(
            chunk=by_chunk[chunk_id],
            rank=i + 1,
            score=score,
            retrieval_method="hybrid",
        )
        for i, (chunk_id, score) in enumerate(ranked)
    ]


def _dedup(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    seen: set[str] = set()
    out: list[RetrievalHit] = []
    for hit in hits:
        if hit.chunk.chunk_id in seen:
            continue
        seen.add(hit.chunk.chunk_id)
        out.append(hit)
    return out
