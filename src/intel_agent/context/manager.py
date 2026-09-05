"""ContextManager: scoped recall, token budget, citations (spec §11)."""

from __future__ import annotations

from ..contracts.documents import Chunk
from ..contracts.research import ContextPackage, ContextRequest
from ..runtime.config import ContextConfig
from ..storage.materials import MaterialStore
from .formatter import build_citations, format_context
from .retrieval import DirectRetriever, HybridRetriever

_OVERHEAD_PER_CHUNK = 12


class ContextManager:
    def __init__(
        self,
        store: MaterialStore,
        counter,
        config: ContextConfig,
        direct: DirectRetriever | None = None,
        hybrid: HybridRetriever | None = None,
        vector_profile_id: str | None = None,
    ) -> None:
        self.store = store
        self.counter = counter
        self.config = config
        self.direct = direct or DirectRetriever(store)
        self.hybrid = hybrid
        self.vector_profile_id = vector_profile_id

    def _source_by_artifact(self, artifact_ids: list[str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for artifact_id in artifact_ids:
            try:
                document = self.store.get_document(artifact_id)
            except Exception:  # noqa: BLE001
                continue
            for occurrence in document.provenance:
                if occurrence.original_url:
                    mapping[artifact_id] = occurrence.original_url
                    break
        return mapping

    async def build(self, request: ContextRequest) -> ContextPackage:
        scope = self.store.resolve_scope(request.task_id, request.filters)
        if request.max_tokens <= 0:
            return ContextPackage(
                task_id=request.task_id,
                query=request.query,
                scope_id=scope.scope_id,
                warnings=["zero token budget"],
            )
        all_chunks = self.store.read_chunks(scope)
        source_by_artifact = self._source_by_artifact(scope.artifact_ids)

        chunks: list[Chunk]
        warnings: list[str] = []
        if self._fits(all_chunks, request.max_tokens):
            chunks = all_chunks
        elif self.hybrid is not None:
            hits, warnings = await self.hybrid.retrieve(
                request.query,
                scope,
                top_k=30,
                vector_profile_id=self.vector_profile_id,
            )
            chunks = [hit.chunk for hit in hits]
        else:
            hits = await self.direct.retrieve(request.query, scope, 30)
            chunks = [hit.chunk for hit in hits]
            warnings.append("no hybrid retriever; used direct recall")

        chunks = self._trim(chunks, request.max_tokens)
        citations = build_citations(chunks, source_by_artifact)
        formatted = format_context(chunks, citations)
        token_count = self.counter.count(formatted)
        return ContextPackage(
            task_id=request.task_id,
            query=request.query,
            scope_id=scope.scope_id,
            selected_chunks=chunks,
            citations=citations,
            formatted_text=formatted,
            token_count=token_count,
            warnings=warnings,
            coverage_summary={"chunks": len(chunks)},
        )

    def _fits(self, chunks: list[Chunk], max_tokens: int) -> bool:
        total = 0
        for chunk in chunks:
            total += self.counter.count(chunk.text) + _OVERHEAD_PER_CHUNK
            if total > max_tokens:
                return False
        return True

    def _trim(self, chunks: list[Chunk], max_tokens: int) -> list[Chunk]:
        kept: list[Chunk] = []
        total = 0
        for chunk in chunks:
            cost = self.counter.count(chunk.text) + _OVERHEAD_PER_CHUNK
            if total + cost > max_tokens:
                break
            kept.append(chunk)
            total += cost
        return kept
