"""OpenAI-compatible HTTP embedding client (spec §5, §10.2)."""

from __future__ import annotations

import httpx

from ..contracts.errors import DomainError
from .models import EmbeddingBatch


class HttpEmbeddingClient:
    """Embeds text via an OpenAI-compatible /embeddings endpoint.

    Works with local vLLM (``--convert embed``) or hosted embedding APIs. The
    vector dimension is read from the response and validated for consistency.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        model_id: str,
        *,
        profile_id: str,
        dimension: int | None = None,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.profile_id = profile_id
        self.dimension = dimension

    async def embed(self, texts: list[str], profile_id: str) -> EmbeddingBatch:
        response = await self.client.post(
            "/embeddings",
            json={"model": self.model_id, "input": texts},
        )
        if response.status_code != 200:
            raise DomainError(
                "BACKEND_UNAVAILABLE",
                f"embedding endpoint {response.status_code}",
                stage="indexing",
                safe_details={"body": response.text[:200]},
            )
        data = response.json()["data"]
        vectors = [item["embedding"] for item in data]
        dimension = len(vectors[0]) if vectors else (self.dimension or 0)
        if self.dimension is not None and dimension != self.dimension:
            raise DomainError(
                "BACKEND_UNAVAILABLE",
                f"embedding dimension mismatch: {dimension} != "
                f"{self.dimension}",
                stage="indexing",
            )
        return EmbeddingBatch(
            profile_id=self.profile_id, dimension=dimension, vectors=vectors
        )
