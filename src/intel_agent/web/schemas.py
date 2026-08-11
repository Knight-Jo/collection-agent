"""Typed API read models for the local Web workbench."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import (
    ChallengeRound,
    CoverageSnapshot,
    EvidenceConflict,
    FactCoverage,
    IntelTask,
    QuestionCoverage,
    SufficiencyCriteria,
    SupportReview,
)
from ..runner import TaskRunSpec

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class RunCreate(BaseModel):
    topic: str
    questions: list[str]
    criteria: SufficiencyCriteria = Field(
        default_factory=lambda: SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        )
    )

    def to_spec(self) -> TaskRunSpec:
        return TaskRunSpec.model_validate(self.model_dump())


class UsageView(BaseModel):
    requests: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class RunErrorView(BaseModel):
    code: str
    message: str


class RunEvent(BaseModel):
    id: int
    type: str
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunView(BaseModel):
    run_id: str
    status: RunStatus
    task_id: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: str | None = None
    error: RunErrorView | None = None
    usage: UsageView | None = None


class ServiceStatus(BaseModel):
    name: str
    configured: bool


class SystemStatus(BaseModel):
    model: ServiceStatus
    audit: ServiceStatus
    search: ServiceStatus


class TaskSummary(BaseModel):
    id: str
    topic: str
    stage: str
    updated_at: str
    coverage_level: str | None = None
    gap_score: int | None = None
    evidence_count: int = 0


class DocumentSummary(BaseModel):
    id: str
    title: str
    final_url: str
    source_type: str
    source_group: str
    publish_time: str | None = None
    content_type: str
    text_sha256: str
    injection_warnings: list[str] = Field(default_factory=list)


class EvidenceView(BaseModel):
    id: str
    relation: str
    quote: str
    line_start: int
    line_end: int
    notes: str
    document: DocumentSummary
    review: SupportReview | None = None


class FactView(BaseModel):
    id: str
    statement: str
    status: str
    superseded_by: list[str]
    supersession_reason: str
    coverage: FactCoverage | None = None
    evidence: list[EvidenceView]


class QuestionView(BaseModel):
    id: str
    text: str
    coverage: QuestionCoverage | None = None
    facts: list[FactView]


class TaskView(BaseModel):
    task: IntelTask
    coverage: CoverageSnapshot | None = None
    questions: list[QuestionView]
    conflicts: list[EvidenceConflict]
    challenges: list[ChallengeRound]


class ArtifactView(BaseModel):
    kind: Literal["assessment", "package"]
    path: str
    content: str
    content_sha256: str
