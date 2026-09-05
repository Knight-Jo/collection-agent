"""IndexingService: idempotent chunk + lexical index (spec §5, §9.3)."""

from __future__ import annotations

from ..contracts.errors import DomainError
from ..runtime.config import IndexingConfig
from ..storage.materials import MaterialStore
from .chunking import chunk_document, chunk_profile_id
from .lexical import lexical_tokens
from .models import IndexReport, LexicalIndexState, VectorIndexState


class IndexingService:
    def __init__(
        self,
        store: MaterialStore,
        config: IndexingConfig,
        counter,
        embedding_client=None,
        vector_index=None,
    ) -> None:
        self.store = store
        self.config = config
        self.counter = counter
        self.embedding_client = embedding_client
        self.vector_index = vector_index

    def _chunk_config(self) -> dict:
        chunk = self.config.chunk
        return {
            "target_tokens": chunk.target_tokens,
            "hard_limit_tokens": chunk.hard_limit_tokens,
            "overlap_tokens": chunk.overlap_tokens,
            "tokenizer": self.counter.tokenizer_version,
        }

    async def index(self, artifact_id: str) -> IndexReport:
        document = self.store.get_document(artifact_id)
        config = self._chunk_config()
        pid = chunk_profile_id(config)
        chunks = chunk_document(document, config, self.counter)
        self.store.save_chunks(artifact_id, chunks)
        for chunk in chunks:
            terms = list(dict.fromkeys(lexical_tokens(chunk.text)))
            self.store.save_chunk_terms(chunk.chunk_id, terms)
        self.store.record_index(
            artifact_id,
            pid,
            lexical_status="ready",
            vector_status="pending",
            chunk_count=len(chunks),
        )
        report = IndexReport(
            artifact_id=artifact_id,
            chunk_profile_id=pid,
            chunk_count=len(chunks),
            lexical=LexicalIndexState(status="ready"),
            vector=VectorIndexState(status="pending"),
        )
        if self.embedding_client is not None and self.vector_index is not None:
            report = await self._index_vectors(
                self.embedding_client,
                self.vector_index,
                artifact_id,
                pid,
                chunks,
                report,
            )
        return report

    async def _index_vectors(
        self, embedding_client, vector_index, artifact_id, pid, chunks, report
    ) -> IndexReport:
        try:
            batch = await embedding_client.embed([c.text for c in chunks], pid)
            from ..indexing.models import VectorPoint
            from .qdrant import vector_point_id

            points = [
                VectorPoint(
                    point_id=vector_point_id(c.chunk_id, pid),
                    chunk_id=c.chunk_id,
                    artifact_id=artifact_id,
                    vector=vector,
                    payload={
                        "artifact_id": artifact_id,
                        "document_id": c.document_id,
                        "revision_id": c.revision_id,
                        "chunk_id": c.chunk_id,
                    },
                )
                for c, vector in zip(chunks, batch.vectors, strict=True)
            ]
            await vector_index.upsert(points, pid)
            self.store.record_index(
                artifact_id,
                pid,
                embedding_profile_id=pid,
                lexical_status="ready",
                vector_status="ready",
                chunk_count=len(chunks),
            )
            report.vector.status = "ready"
            report.embedding_profile_id = pid
        except DomainError as error:
            report.vector.status = "degraded"
            report.vector.error = error.code
            report.warnings.append(f"vector index degraded: {error.code}")
        return report
