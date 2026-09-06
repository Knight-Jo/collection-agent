"""Media analysis domain models (spec 002 §5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..contracts._time import AwareDatetime, JsonValue
from ..contracts.documents import BlockSpan, CoverageUnit, Locator

MediaKind = Literal["audio", "video"]
MediaRelation = Literal["mentions", "supports", "contradicts"]
VerificationStatus = Literal["unverified"]


class MediaJob(BaseModel):
    media_job_id: str
    task_id: str
    resource_id: str
    artifact_id: str | None = None
    filename: str
    kind: MediaKind
    media_type: str = ""
    size_bytes: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    limitations: list[str] = Field(default_factory=list)
    coverage: list[CoverageUnit] = Field(default_factory=list)


class MediaSegment(BaseModel):
    """Read-only projection of a transcribed evidence block."""

    segment_id: str
    media_job_id: str
    artifact_id: str
    block_id: str
    locator: Locator = Field(default_factory=Locator)
    text: str = ""
    speaker: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("locator")
    @classmethod
    def _has_time_range(cls, value: Locator) -> Locator:
        if value.start_ms is None or value.end_ms is None:
            raise ValueError("media segment locator requires start_ms/end_ms")
        if value.start_ms >= value.end_ms:
            raise ValueError("media segment time range must be ordered")
        return value


class MediaFact(BaseModel):
    fact_id: str
    media_job_id: str
    statement: str
    segment_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = "unverified"


class MediaEvidence(BaseModel):
    evidence_id: str
    media_job_id: str
    fact_id: str
    segment_id: str
    artifact_id: str
    block_span: BlockSpan
    locator: Locator = Field(default_factory=Locator)
    quote: str
    relation: MediaRelation = "mentions"


class MediaJobView(BaseModel):
    """Read projection of a media job plus its task state and products."""

    job: MediaJob
    status: str
    phase: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: JsonValue | None = None
    segments: list[MediaSegment] = Field(default_factory=list)
    facts: list[MediaFact] = Field(default_factory=list)
    evidence: list[MediaEvidence] = Field(default_factory=list)
