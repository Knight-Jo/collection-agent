"""Indexing contracts: embeddings, vectors, and index reports (spec §5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IndexState = Literal["pending", "ready", "failed", "degraded"]


class EmbeddingBatch(BaseModel):
    profile_id: str
    dimension: int = Field(gt=0)
    vectors: list[list[float]] = Field(default_factory=list)


class VectorPoint(BaseModel):
    point_id: str
    chunk_id: str
    artifact_id: str
    vector: list[float]
    payload: dict = Field(default_factory=dict)


class VectorMatch(BaseModel):
    point_id: str
    chunk_id: str
    artifact_id: str
    score: float


class LexicalIndexState(BaseModel):
    status: IndexState = "pending"
    error: str | None = None


class VectorIndexState(BaseModel):
    status: IndexState = "pending"
    error: str | None = None


class IndexReport(BaseModel):
    artifact_id: str
    chunk_profile_id: str
    embedding_profile_id: str | None = None
    chunk_count: int = Field(ge=0)
    lexical: LexicalIndexState = Field(default_factory=LexicalIndexState)
    vector: VectorIndexState = Field(default_factory=VectorIndexState)
    warnings: list[str] = Field(default_factory=list)


class AcquisitionReport(BaseModel):
    task_id: str
    work_item_id: str
    artifact_id: str | None = None
    stage: str
    status: Literal["success", "partial", "failed"]
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
