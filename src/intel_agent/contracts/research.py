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
TaskKind = Literal["research", "monitor", "factcheck", "media"]
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


class SearchDirection(BaseModel):
    """A search direction: one query plus which engines to route it to."""

    query: SearchQuery
    provider_names: list[str] = Field(default_factory=list)
    reason: str = ""


class ResearchBrief(BaseModel):
    """The user-facing brief subset, generated before research starts."""

    goal: str = ""
    scope: str = ""
    questions: list[str] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    suggested_sources: list[str] = Field(default_factory=list)

    def brief(self) -> dict:
        return self.model_dump(mode="json")


class ResearchPlan(ResearchBrief):
    """The planner's output: a brief plus concrete search directions."""

    directions: list[SearchDirection] = Field(default_factory=list)

    def brief(self) -> dict:
        """The user-facing brief subset (no internal search directions)."""
        return self.model_dump(mode="json", exclude={"directions"})


class QuestionCoverage(BaseModel):
    question_id: str
    question: str
    status: Literal["pending", "researching", "answered", "blocked"] = (
        "pending"
    )
    evidence_count: int = Field(default=0, ge=0)
    coverage_note: str = ""


class ResearchGap(BaseModel):
    question_id: str
    reason: str


class CoverageAssessment(BaseModel):
    sufficiency: Literal["high", "medium", "low"]
    questions: list[QuestionCoverage] = Field(default_factory=list)
    gaps: list[ResearchGap] = Field(default_factory=list)
    summary: str = ""


class EvidenceItem(BaseModel):
    claim: str
    relation: Literal["supports", "contradicts"]
    quote: str = ""
    citation_id: str = ""
    source_title: str = ""


class Conflict(BaseModel):
    claim: str
    description: str = ""
    citation_ids: list[str] = Field(default_factory=list)


class EvidenceReview(BaseModel):
    claims: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    summary: str = ""


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
    content: str | None = None
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
    kind: TaskKind = "research"
    round: int = Field(default=0, ge=0)
    phase: str | None = None
    cancel_requested: bool = False
    error: JsonValue | None = None
    attempt: int = Field(default=0, ge=0)
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


class TimelineEntry(BaseModel):
    """A persisted progress/phase marker scoped to a task."""

    entry_id: str
    task_id: str
    sequence: int = Field(ge=0)
    attempt: int = Field(default=0, ge=0)
    phase: str = ""
    state: str = ""
    summary: str = ""
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class ReportSection(BaseModel):
    heading: str
    body: str


class ResearchReport(BaseModel):
    """The writer's structured final report (spec §12)."""

    title: str = ""
    sections: list[ReportSection] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)

    def markdown(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(f"# {self.title}")
        for section in self.sections:
            parts.append(f"## {section.heading}")
            parts.append(section.body.strip())
        if self.conclusions:
            parts.append("## 结论")
            parts.extend(f"- {c}" for c in self.conclusions)
        if self.limitations:
            parts.append("## 局限")
            parts.extend(f"- {lim}" for lim in self.limitations)
        return "\n\n".join(p for p in parts if p)


class ResearchDecision(BaseModel):
    action: Literal["search", "finish"]
    directions: list[SearchDirection] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    reason: str
    citation_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _action_constraints(self) -> ResearchDecision:
        if self.action == "search" and not self.directions:
            raise ValueError("search decision requires at least one direction")
        if self.action == "finish" and self.directions:
            raise ValueError("finish decision must have empty directions")
        return self


class ResearchResult(BaseModel):
    task_id: str
    status: ResultStatus
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stop_reason: StopReason
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    report: ResearchReport | None = None


class ResearchAssessment(BaseModel):
    """Typed evaluation output of the research loop (spec 002 §2.3).

    Produced by the loop and consumed by report generation, Monitor, and
    FactCheck alike. It carries the scope, coverage, evidence review, and the
    fully-resolved citations; report writing is a separate, optional step.
    """

    task_id: str
    scope_id: str = ""
    coverage: CoverageAssessment
    evidence_review: EvidenceReview
    citations: list[Citation] = Field(default_factory=list)
    accepted_artifact_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stop_reason: StopReason
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
