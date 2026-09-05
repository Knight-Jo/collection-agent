"""Evidence, locator, and versioned-document contracts (spec §4.3, §4.4)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ._time import AwareDatetime, JsonValue, require_aware

if TYPE_CHECKING:  # pragma: no cover - resolved via model_rebuild
    from .research import SearchOccurrence

OriginMethod = Literal["native_text", "ocr", "subtitle", "asr"]
BlockType = str
CoverageUnitType = Literal["page", "slide", "sheet", "time_range", "document"]
CoverageStatus = Literal["success", "empty", "partial", "failed", "skipped"]
ExtractStatus = Literal["success", "partial", "empty"]
DocumentStatus = Literal["success", "partial", "empty"]


class Locator(BaseModel):
    """Position within a source: page/section/paragraph/slide/sheet/time/bbox.

    Ordinals (page/paragraph/slide) are 1-based. Media times are integer
    milliseconds with half-open interval [start_ms, end_ms). bbox is
    (x0, y0, x1, y1) normalized to the source page/image in [0, 1].
    """

    page: int | None = Field(default=None, ge=1)
    section_path: list[str] = Field(default_factory=list)
    paragraph: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    cell_range: str | None = None
    dom_path: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    bbox: tuple[float, float, float, float] | None = None
    frame_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_ranges(self) -> Locator:
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and self.start_ms >= self.end_ms
        ):
            raise ValueError("start_ms must be < end_ms")
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if not (0.0 <= x0 <= x1 <= 1.0 and 0.0 <= y0 <= y1 <= 1.0):
                raise ValueError("bbox must be normalized and ordered")
        return self


class EvidenceBlock(BaseModel):
    block_id: str
    text: str
    block_type: BlockType
    locator: Locator = Field(default_factory=Locator)
    origin_method: OriginMethod
    backend_id: str
    backend_version: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: JsonValue = Field(default_factory=dict)


class CoverageUnit(BaseModel):
    unit_type: CoverageUnitType
    locator: Locator = Field(default_factory=Locator)
    status: CoverageStatus
    reason: str | None = None


class BackendAttempt(BaseModel):
    backend_id: str
    backend_version: str
    capability: str
    target: str | None = None
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    status: Literal["success", "failed", "timeout", "cancelled"]
    error: str | None = None
    fallback_reason: str | None = None


class ExtractResult(BaseModel):
    resource_id: str
    title: str | None = None
    blocks: list[EvidenceBlock] = Field(default_factory=list)
    coverage: list[CoverageUnit] = Field(default_factory=list)
    status: ExtractStatus
    attempts: list[BackendAttempt] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extraction_profile_id: str


class DocumentIdentity(BaseModel):
    document_id: str
    source_key: str
    aliases: list[str] = Field(default_factory=list)


class NormalizationInput(BaseModel):
    result: ExtractResult
    resource_id: str
    identity: DocumentIdentity
    revision_id: str
    provenance: list[SearchOccurrence] = Field(default_factory=list)
    published_at: datetime | None = None
    language: str | None = None


class NormalizedDocument(BaseModel):
    document_id: str
    revision_id: str
    artifact_id: str
    resource_id: str
    title: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    blocks: list[EvidenceBlock] = Field(default_factory=list)
    coverage: list[CoverageUnit] = Field(default_factory=list)
    attempts: list[BackendAttempt] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: list[SearchOccurrence] = Field(default_factory=list)
    extraction_profile_id: str
    normalizer_version: str
    status: DocumentStatus

    @field_validator("published_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class BlockSpan(BaseModel):
    block_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> BlockSpan:
        if self.char_start >= self.char_end:
            raise ValueError("char_start must be < char_end")
        return self


class Chunk(BaseModel):
    chunk_id: str
    artifact_id: str
    document_id: str
    revision_id: str
    text: str
    block_spans: list[BlockSpan] = Field(default_factory=list)
    locators: list[Locator] = Field(default_factory=list)
    chunk_profile_id: str
    ordinal: int = Field(ge=1)


class RetrievalHit(BaseModel):
    chunk: Chunk
    rank: int = Field(ge=1)
    score: float | None = None
    retrieval_method: Literal["direct", "lexical", "vector", "hybrid"] = (
        "direct"
    )


class Citation(BaseModel):
    citation_id: str
    chunk_id: str
    artifact_id: str
    document_id: str
    revision_id: str
    source_url: str | None = None
    resource_id: str
    locators: list[Locator] = Field(default_factory=list)
    block_spans: list[BlockSpan] = Field(default_factory=list)
