"""ContextManager: scoped recall, token budget, citations (spec §11)."""

from __future__ import annotations

from ..contracts.documents import Chunk
from ..contracts.research import ContextPackage, ContextRequest
from ..indexing.quality import is_junk_chunk
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

        chunks: list[Chunk]
        warnings: list[str] = []
        if self._fits(all_chunks, request.max_tokens):
            chunks = all_chunks
        elif self.hybrid is not None:
            hits, warnings = await self.hybrid.retrieve(
                request.query,
                scope,
                top_k=60,
                vector_profile_id=self.vector_profile_id,
            )
            chunks = [hit.chunk for hit in hits]
        else:
            hits = await self.direct.retrieve(request.query, scope, 60)
            chunks = [hit.chunk for hit in hits]
            warnings.append("no hybrid retriever; used direct recall")

        # Junk chunks (link lists, citation backlink soup) rank high on
        # lexical signal precisely because they are keyword-stuffed; drop
        # them before they crowd real prose out of the budget.
        kept = [c for c in chunks if not is_junk_chunk(c.text)]
        filtered = len(chunks) - len(kept)
        chunks = kept
        chunks = self._diversify(chunks, self.config.max_chunks_per_artifact)
        if filtered:
            warnings.append(f"filtered {filtered} low-quality chunks")

        chunks = self._diversify(chunks, self.config.max_chunks_per_artifact)
        return self._assemble(
            request.task_id,
            request.query,
            scope.scope_id,
            chunks,
            request.max_tokens,
            warnings,
            filtered,
        )

    def merge_packages(
        self,
        task_id: str,
        query: str,
        packages: list[ContextPackage],
        max_tokens: int,
    ) -> ContextPackage:
        """Merge per-question packages into one deduplicated evidence block.

        Chunks selected for several questions appear once; rank order follows
        package order (first question's picks first). Citations are rebuilt
        over the merged list so ids stay unique across the whole block.
        """
        if not packages:
            return ContextPackage(task_id=task_id, query=query, scope_id="")
        seen: set[str] = set()
        merged: list[Chunk] = []
        warnings: list[str] = []
        for package in packages:
            warnings.extend(package.warnings)
            for chunk in package.selected_chunks:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    merged.append(chunk)
        return self._assemble(
            task_id, query, packages[0].scope_id, merged, max_tokens, warnings
        )

    def _assemble(
        self,
        task_id: str,
        query: str,
        scope_id: str,
        chunks: list[Chunk],
        max_tokens: int,
        warnings: list[str],
        filtered: int = 0,
    ) -> ContextPackage:
        source_by_artifact = self._source_by_artifact(
            [c.artifact_id for c in chunks]
        )
        chunks = self._trim(chunks, max_tokens)
        citations = build_citations(chunks, source_by_artifact)
        formatted = format_context(chunks, citations)
        token_count = self.counter.count(formatted)
        return ContextPackage(
            task_id=task_id,
            query=query,
            scope_id=scope_id,
            selected_chunks=chunks,
            citations=citations,
            formatted_text=formatted,
            token_count=token_count,
            warnings=warnings,
            coverage_summary={
                "chunks": len(chunks),
                "filtered_junk": filtered,
                "artifacts": len({c.artifact_id for c in chunks}),
            },
        )

    @staticmethod
    def _diversify(chunks: list[Chunk], cap: int) -> list[Chunk]:
        """Re-rank so one artifact cannot monopolize the budget.

        The first ``cap`` chunks of each artifact keep their rank order; a
        page's extra chunks move behind everyone else's first picks and only
        fill whatever budget remains.
        """
        per_artifact: dict[str, int] = {}
        head: list[Chunk] = []
        tail: list[Chunk] = []
        for chunk in chunks:
            artifact = chunk.artifact_id
            used = per_artifact.get(artifact, 0)
            if used < cap:
                per_artifact[artifact] = used + 1
                head.append(chunk)
            else:
                tail.append(chunk)
        return head + tail

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
