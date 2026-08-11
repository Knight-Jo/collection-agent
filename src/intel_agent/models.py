"""Data models for the intelligence collection agent (port of model.ts)."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

SourceType = Literal[
    "news",
    "official",
    "encyclopedia",
    "industry",
    "academic",
    "social",
    "government",
    "other",
]
TaskStage = Literal["collect", "assess", "challenge", "done"]
QuestionStatus = Literal["covered", "partial", "gap"]
SupportVerdict = Literal["full", "partial", "irrelevant", "contradicts"]
SUPPORT_REVIEW_PROMPT_VERSION = "support-entailment-v1"


class CrawlValidators(BaseModel):
    etag: str | None = None
    last_modified: str | None = None


class ExtractionState(BaseModel):
    status: Literal[
        "pending", "complete", "unavailable", "failed", "skipped"
    ] = "pending"
    processor: str | None = None
    text_path: str | None = None
    error: str | None = None


class ExtractionResult(BaseModel):
    status: Literal["complete", "unavailable", "failed", "skipped"]
    text: str = ""
    links: list[str] = Field(default_factory=list)
    processor: str | None = None
    error: str | None = None


class CrawlEntry(BaseModel):
    canonical_url: str
    parent_url: str | None = None
    depth: int = Field(ge=0)
    priority: float
    status: Literal[
        "queued",
        "fetching",
        "complete",
        "reused",
        "skipped_robots",
        "skipped_http",
        "skipped_limit",
        "skipped_unsupported",
        "failed",
    ] = "queued"
    attempts: int = 0
    downloaded_bytes: int = 0
    document_id: str | None = None
    error: str | None = None
    mime_type: str | None = None
    size: int | None = None
    extraction: ExtractionState = Field(default_factory=ExtractionState)
    validators: CrawlValidators = Field(default_factory=CrawlValidators)
    created_at: str
    updated_at: str


class CrawlSnapshot(BaseModel):
    task_id: str
    status: Literal["running", "complete", "paused"] = "running"
    entries: list[CrawlEntry] = Field(default_factory=list)
    downloaded_bytes: int = 0
    config: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class SufficiencyCriteria(BaseModel):
    min_independent_sources: int
    min_high_quality_sources: int
    recency_days: int
    require_recency: bool


class IntelQuestion(BaseModel):
    id: str
    text: str


class TaskOutputBinding(BaseModel):
    coverage_id: str
    coverage_fingerprint: str
    path: str
    content_sha256: str
    created_at: str


class CollectionState(BaseModel):
    search_attempts: int = 0
    search_stop_reason: Literal["search_budget_exhausted"] | None = None
    fetch_attempts_since_evidence: int = 0
    evidence_count: int = 0
    stop_reason: Literal["fetch_without_evidence"] | None = None


class TaskOutputs(BaseModel):
    package: TaskOutputBinding | None = None
    assessment: TaskOutputBinding | None = None


class IntelTask(BaseModel):
    """A collection task: topic, questions, budgets, stage, and output bindings."""

    id: str
    topic: str
    stage: TaskStage
    questions: list[IntelQuestion]
    criteria: SufficiencyCriteria
    collection: CollectionState = Field(default_factory=CollectionState)
    outputs: TaskOutputs = Field(default_factory=TaskOutputs)
    challenge_round: int = 0
    created_at: str
    updated_at: str


class IntelDocument(BaseModel):
    id: str
    requested_url: str
    final_url: str
    canonical_url: str
    title: str
    content_type: str
    publish_time: str | None = None
    publish_time_source: Literal["meta", "time-element", "unknown"] = "unknown"
    collected_at: str
    source_type: SourceType
    source_group: str
    raw_path: str
    raw_sha256: str
    text_path: str
    text_sha256: str
    injection_warnings: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    """A canonical atomic statement; superseded facts keep history for audit."""

    id: str
    task_id: str
    question_id: str
    statement: str
    status: Literal["active", "superseded"]
    superseded_by: list[str] = Field(default_factory=list)
    supersession_reason: str = ""
    created_at: str
    updated_at: str


class EvidenceSupport(BaseModel):
    """An exact quote from an archived document linked to a fact (supports/contradicts)."""

    id: str
    task_id: str
    fact_id: str
    document_id: str
    relation: Literal["supports", "contradicts"]
    quote: str
    line_start: int
    line_end: int
    notes: str = ""
    created_at: str


class SupportReview(BaseModel):
    """Immutable judge verdict for one evidence; only full counts toward coverage."""

    id: str
    task_id: str
    fact_id: str
    evidence_id: str
    verdict: SupportVerdict
    reason: str
    unsupported_parts: list[str] = Field(default_factory=list)
    judge_provider: str
    judge_model: str
    prompt_version: str = SUPPORT_REVIEW_PROMPT_VERSION
    created_at: str


class EvidenceConflict(BaseModel):
    id: str
    task_id: str
    fact_id: str
    evidence_ids: list[str]
    resolution: Literal["unresolved", "resolved"]
    note: str = ""
    created_at: str
    updated_at: str


class FactCoverage(BaseModel):
    fact_id: str
    statement: str
    status: QuestionStatus
    candidate_supports_count: int
    supports_count: int
    pending_reviews: int
    partial_reviews: int
    irrelevant_reviews: int
    contradictory_reviews: int
    contradicts_count: int
    independent_sources: int
    source_groups: list[str]
    high_quality_sources: int
    recent_count: int
    unknown_publish_time: int
    unresolved_conflicts: int
    unresolved_contradictions: int
    gap_score: int
    notes: list[str] = Field(default_factory=list)


class QuestionCoverage(BaseModel):
    question_id: str
    question: str
    status: QuestionStatus
    fact_count: int
    covered_fact_count: int
    facts: list[FactCoverage]
    notes: list[str] = Field(default_factory=list)


class CoverageSnapshot(BaseModel):
    """Point-in-time coverage state; outputs bind to it via fingerprint."""

    id: str
    task_id: str
    created_at: str
    fingerprint: str
    gap_score: int
    no_progress_rounds: int
    stop_reason: Literal["sufficient", "no_progress"] | None = None
    level: Literal["sufficient", "mostly_sufficient", "insufficient"]
    per_question: list[QuestionCoverage]


class CoverageHistory(BaseModel):
    task_id: str
    snapshots: list[CoverageSnapshot]


class FactConclusion(BaseModel):
    kind: Literal["fact"] = "fact"
    fact_id: str


class ReportedConclusion(BaseModel):
    kind: Literal["reported"] = "reported"
    fact_id: str
    attribution: str


class InferenceConclusion(BaseModel):
    kind: Literal["inference"] = "inference"
    statement: str
    rationale: str
    confidence: Literal["high", "medium", "low"]
    fact_ids: list[str]


AssessmentConclusion = Annotated[
    FactConclusion | ReportedConclusion | InferenceConclusion,
    Field(discriminator="kind"),
]


class ChallengePoint(BaseModel):
    id: str
    question_ids: list[str]
    category: str
    challenge: str
    gap_action: str
    status: Literal["open", "addressed", "dismissed"]
    reason: str = ""
    new_evidence_ids: list[str] = Field(default_factory=list)


class ChallengeRound(BaseModel):
    id: str
    task_id: str
    round: int
    status: Literal["open", "confirmed"]
    evidence_ids_before: list[str]
    points: list[ChallengePoint]
    accepted_partial_questions: list[dict[str, str]] = Field(
        default_factory=list
    )
    converged: bool = False
    created_at: str
    confirmed_at: str | None = None


class IntelError(Exception):
    """Error carrying a stable machine-readable code (e.g. UNSAFE_URL)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.name = "IntelError"


def new_id(prefix: str) -> str:
    """Random ID for non-content-addressed records; collision assumed negligible."""
    return f"{prefix}-{uuid.uuid4()}"


def normalized_statement(value: str) -> str:
    """NFKC-normalize and collapse whitespace so equal facts get equal IDs."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def is_valid_calendar_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
