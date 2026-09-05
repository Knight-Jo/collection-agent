"""Search, task, decision, and context-flow contracts (spec §4.1, §4.5)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ._time import AwareDatetime, JsonValue, require_aware
from .documents import Chunk, Citation

SourceType = Literal["web", "academic", "news", "custom"]
ProviderStatus = Literal["success", "failed", "timeout", "disabled"]
BatchStatus = Literal["success", "partial", "failed"]
TaskStatus = Literal[
    "queued",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "interrupted",
]
ResultStatus = Literal["completed", "partial", "failed", "cancelled"]
StopReason = Literal[
    "evidence_sufficient",
    "max_rounds",
    "deadline",
    "llm_budget",
    "material_budget",
    "no_progress",
    "cancelled",
    "fatal_error",
]


class SearchQuery(BaseModel):
    text: str
    domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    language: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    source_types: list[SourceType] = Field(default_factory=list)

    @model_validator(mode="after")
    def _date_range(self) -> SearchQuery:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must not follow end_date")
        return self


class SearchRequest(BaseModel):
    query: SearchQuery
    provider_names: list[str] = Field(default_factory=list)
    per_provider_limit: int = Field(gt=0)
    total_limit: int = Field(gt=0)


class SearchOccurrence(BaseModel):
    provider: str
    query_id: str
    provider_rank: int | None = Field(default=None, ge=1)
    provider_score: float | None = None
    observed_at: AwareDatetime
    original_url: str
    channel: str

    metadata: JsonValue = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class SearchHit(BaseModel):
    hit_id: str
    url: str
    dedup_key: str
    title: str | None = None
    snippet: str | None = None
    published_at: datetime | None = None
    source_types: list[SourceType] = Field(default_factory=list)
    occurrences: list[SearchOccurrence] = Field(default_factory=list)

    @field_validator("published_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class ProviderReport(BaseModel):
    provider: str
    status: ProviderStatus
    elapsed_ms: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SearchBatch(BaseModel):
    hits: list[SearchHit] = Field(default_factory=list)
    provider_reports: list[ProviderReport] = Field(default_factory=list)
    status: BatchStatus


class ContextFilter(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    language: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    include_unknown_dates: bool = False


class MaterialScope(BaseModel):
    scope_id: str
    task_id: str
    artifact_ids: list[str] = Field(default_factory=list)
    created_at: AwareDatetime


class ContextRequest(BaseModel):
    task_id: str
    query: str
    filters: ContextFilter = Field(default_factory=ContextFilter)
    max_tokens: int = Field(gt=0)


class ContextPackage(BaseModel):
    task_id: str
    query: str
    scope_id: str
    selected_chunks: list[Chunk] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    formatted_text: str = ""
    token_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    coverage_summary: JsonValue = Field(default_factory=dict)


class BudgetUsage(BaseModel):
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class Checkpoint(BaseModel):
    task_id: str
    round: int = Field(ge=0)
    plan: list[SearchQuery] = Field(default_factory=list)
    accepted_artifact_ids: list[str] = Field(default_factory=list)
    budget_used: BudgetUsage = Field(default_factory=BudgetUsage)
    stop_reason: StopReason | None = None
    updated_at: AwareDatetime


class ResearchTask(BaseModel):
    task_id: str
    question: str
    status: TaskStatus = "queued"
    round: int = Field(default=0, ge=0)
    budget_used: BudgetUsage = Field(default_factory=BudgetUsage)
    checkpoint: Checkpoint | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deadline_at: AwareDatetime | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)

    @field_validator("deadline_at")
    @classmethod
    def _aware_opt(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class ResearchDecision(BaseModel):
    action: Literal["search", "finish"]
    queries: list[SearchQuery] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    reason: str
    draft_answer: str | None = None
    citation_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _action_constraints(self) -> ResearchDecision:
        if self.action == "search" and not self.queries:
            raise ValueError("search decision requires at least one query")
        if self.action == "finish":
            if not self.draft_answer:
                raise ValueError("finish decision requires draft_answer")
            if self.queries:
                raise ValueError("finish decision must have empty queries")
        return self


class ResearchResult(BaseModel):
    task_id: str
    status: ResultStatus
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stop_reason: StopReason
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
