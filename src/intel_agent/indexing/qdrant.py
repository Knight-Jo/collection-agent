"""Qdrant vector index adapter (spec §5, §10.2)."""

from __future__ import annotations

import json
import uuid

from ..contracts.research import MaterialScope
from .models import VectorMatch, VectorPoint


def vector_point_id(chunk_id: str, profile_id: str) -> str:
    """Deterministic UUID per (chunk, embedding profile)."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, json.dumps([profile_id, chunk_id])
        )
    )


class QdrantVectorIndex:
    """A real Qdrant backend; collections are isolated per profile."""

    def __init__(self, url: str) -> None:
        from qdrant_client import AsyncQdrantClient

        self._client = AsyncQdrantClient(url=url)
        self._dimensions: dict[str, int] = {}

    @staticmethod
    def _collection(profile_id: str) -> str:
        return f"chunks-{profile_id[:16]}"

    async def upsert(
        self, points: list[VectorPoint], profile_id: str
    ) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not points:
            return
        collection = self._collection(profile_id)
        dimension = len(points[0].vector)
        if dimension != self._dimensions.get(profile_id):
            try:
                await self._client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=dimension, distance=Distance.COSINE
                    ),
                )
            except Exception:  # noqa: BLE001 - already exists
                pass
            self._dimensions[profile_id] = dimension
        await self._client.upsert(
            collection_name=collection,
            points=[
                {
                    "id": p.point_id,
                    "vector": p.vector,
                    "payload": p.payload,
                }
                for p in points
            ],
            wait=True,
        )

    async def search(
        self,
        vector: list[float],
        scope: MaterialScope,
        profile_id: str,
        top_k: int,
    ) -> list[VectorMatch]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        collection = self._collection(profile_id)
        result = await self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=top_k,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="artifact_id",
                        match=MatchAny(any=scope.artifact_ids),
                    )
                ]
            ),
        )
        return [
            VectorMatch(
                point_id=str(point.id),
                chunk_id=point.payload.get("chunk_id", ""),
                artifact_id=point.payload.get("artifact_id", ""),
                score=point.score or 0.0,
            )
            for point in result.points
        ]

    async def delete(self, point_ids: list[str], profile_id: str) -> None:
        collection = self._collection(profile_id)
        await self._client.delete(
            collection_name=collection, points_selector=point_ids
        )

    async def close(self) -> None:
        await self._client.close()
