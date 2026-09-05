"""Public ports: the genuinely replaceable seams (spec §5)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from ..extraction.models import (
    BackendDescriptor,
    BackendOutput,
    BackendRequest,
)
from ..indexing.models import EmbeddingBatch, VectorMatch, VectorPoint
from .documents import ExtractResult
from .research import (
    ContextPackage,
    MaterialScope,
    ResearchDecision,
    ResearchTask,
    SearchHit,
    SearchQuery,
    SourceType,
)
from .resources import Resource


class FilterCapability(BaseModel):
    supported: bool = False
    reliable_postfilter: bool = False


class ProviderCapabilities(BaseModel):
    source_types: list[SourceType] = Field(default_factory=list)
    dates: FilterCapability = Field(default_factory=FilterCapability)
    language: FilterCapability = Field(default_factory=FilterCapability)
    domains: FilterCapability = Field(default_factory=FilterCapability)
    exclude_domains: FilterCapability = Field(default_factory=FilterCapability)


class SearchProvider(Protocol):
    name: str

    def capabilities(self) -> ProviderCapabilities: ...

    async def search(
        self, query: SearchQuery, limit: int
    ) -> list[SearchHit]: ...


class DecisionResponse(BaseModel):
    decision: ResearchDecision
    model_id: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class LLMClient(Protocol):
    async def generate_decision(
        self,
        task: ResearchTask,
        context: ContextPackage,
        remaining_output_tokens: int,
        repair_hint: str | None = None,
    ) -> DecisionResponse: ...


class EmbeddingClient(Protocol):
    async def embed(
        self, texts: list[str], profile_id: str
    ) -> EmbeddingBatch: ...


class TokenCounter(Protocol):
    model_id: str
    tokenizer_version: str

    def count(self, text: str) -> int: ...


class VectorIndex(Protocol):
    async def upsert(
        self, points: list[VectorPoint], profile_id: str
    ) -> None: ...

    async def search(
        self,
        vector: list[float],
        scope: MaterialScope,
        profile_id: str,
        top_k: int,
    ) -> list[VectorMatch]: ...

    async def delete(self, point_ids: list[str], profile_id: str) -> None: ...


class Extractor(Protocol):
    async def extract(
        self, resource: Resource, profile_id: str
    ) -> ExtractResult: ...


class Backend(Protocol):
    async def run(self, request: BackendRequest) -> BackendOutput: ...


class BackendRegistry(Protocol):
    def list_capabilities(self) -> list[BackendDescriptor]: ...

    def get(self, backend_id: str) -> Backend: ...
