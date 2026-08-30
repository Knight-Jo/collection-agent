"""Data models for the intelligence collection agent (port of model.ts)."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import UTC, date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceType = Literal[
    "news",
    "official",
    "encyclopedia",
    "industry",
    "academic",
    "social",
    "government",
    "software",
    "other",
]
EvidenceRole = Literal["primary", "supporting", "secondary"]
TaskStage = Literal["collect", "assess", "challenge", "done"]
QuestionStatus = Literal["covered", "partial", "gap"]
SupportVerdict = Literal["full", "partial", "irrelevant", "contradicts"]
ReportDepth = Literal["brief", "standard", "deep"]
ClaimType = Literal["primary", "corroborated", "reported"]
AnswerStatus = Literal["answered", "partial", "unanswered", "conflicted"]
MessageRole = Literal["user", "assistant"]
MessageStatus = Literal[
    "accepted", "processing", "completed", "failed", "cancelled"
]
ActionRequestStatus = Literal[
    "proposed",
    "queued",
    "executing",
    "succeeded",
    "failed",
    "rejected",
    "expired",
    "cancelled",
]
ResearchRunStatus = Literal[
    "queued",
    "running",
    "stopping",
    "stopped",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
]
CheckpointStatus = Literal["started", "committed", "failed", "cancelled"]
ReportVersionStatus = Literal["draft", "published", "superseded", "abandoned"]
ActionType = Literal[
    "continue_research",
    "search_gap",
    "search_specific_topic",
    "modify_search_plan",
    "generate_report",
    "regenerate_report",
]
DialogueIntent = Literal[
    "greeting",
    "ask_evidence",
    "ask_task_status",
    "ask_methodology",
    "continue_research",
    "search_gap",
    "search_specific_topic",
    "generate_report",
    "regenerate_report",
    "new_topic",
]
CommittedAssetType = Literal["document", "fact", "evidence"]
SUPPORT_REVIEW_PROMPT_VERSION = "support-entailment-v2"


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
    link_relevance: dict[str, float] = Field(default_factory=dict)
    processor: str | None = None
    error: str | None = None
    title: str = ""
    publish_time: str | None = None
    publish_time_source: Literal["meta", "time-element", "unknown"] = "unknown"


class CrawlEntry(BaseModel):
    canonical_url: str
    parent_url: str | None = None
    depth: int = Field(ge=0)
    relevance: float = 0
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
    outbound_links: list[str] = Field(default_factory=list)
    outbound_relevance: dict[str, float] = Field(default_factory=dict)
    render_reason: str | None = None
    render_error: str | None = None
    # Provider-declared provenance from vertical search results; takes
    # precedence over hostname classification at archive time.
    source_type_hint: SourceType | None = None
    evidence_role: EvidenceRole | None = None
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
    min_independent_sources: int = 2
    min_high_quality_sources: int = 1
    recency_days: int = 90
    require_recency: bool = False


class ResearchScope(BaseModel):
    time_range: str = ""
    geography: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class ResearchBrief(BaseModel):
    """Versioned intake result used to create one research task."""

    schema_version: Literal["1"] = "1"
    topic: str
    objective: str = ""
    key_questions: list[str] = Field(default_factory=list, max_length=6)
    scope: ResearchScope = Field(default_factory=ResearchScope)
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    requested_outputs: list[str] = Field(
        default_factory=lambda: ["research_report"]
    )


class IntelQuestion(BaseModel):
    id: str
    text: str
    time_range: str = ""


class TaskOutputBinding(BaseModel):
    coverage_id: str
    coverage_fingerprint: str
    path: str
    content_sha256: str
    created_at: str
    document_hashes: dict[str, str] = Field(default_factory=dict)


class CollectionState(BaseModel):
    search_attempts: int = 0
    search_stop_reason: Literal["search_budget_exhausted"] | None = None
    fetch_attempts_since_evidence: int = 0
    evidence_count: int = 0
    stop_reason: Literal["fetch_without_evidence"] | None = None


class TaskOutputs(BaseModel):
    package: TaskOutputBinding | None = None
    assessment: TaskOutputBinding | None = None
    report: TaskOutputBinding | None = None


class IntelTask(BaseModel):
    """A collection task: topic, questions, budgets, stage, and output bindings."""

    id: str
    topic: str
    stage: TaskStage
    questions: list[IntelQuestion]
    criteria: SufficiencyCriteria
    objective: str = ""
    scope: ResearchScope = Field(default_factory=ResearchScope)
    report_depth: ReportDepth = "standard"
    deep_crawl: bool = False
    completion_status: Literal["sufficient", "with_gaps"] | None = None
    collection: CollectionState = Field(default_factory=CollectionState)
    outputs: TaskOutputs = Field(default_factory=TaskOutputs)
    challenge_round: int = 0
    created_at: str
    updated_at: str


class Conversation(BaseModel):
    """One user-visible conversation, optionally bound to a research task."""

    id: str
    task_id: str | None = None
    status: Literal["intake", "active", "archived"] = "active"
    title: str = "新对话"
    active_epoch_id: str | None = None
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_task_binding(self) -> Self:
        if self.status == "active" and self.task_id is None:
            raise ValueError("active conversation requires task_id")
        return self


class ConversationEpoch(BaseModel):
    """One visible context segment without deleting prior audit history."""

    id: str
    conversation_id: str
    sequence: int = Field(ge=1)
    summary: str = ""
    summary_through_sequence: int = Field(default=0, ge=0)
    summary_updated_at: str | None = None
    started_at: str
    archived_at: str | None = None


class Message(BaseModel):
    """An immutable user request or completed assistant response."""

    id: str
    conversation_id: str
    epoch_id: str
    sequence: int = Field(ge=1)
    client_message_id: str | None = None
    role: MessageRole
    content: str
    status: MessageStatus
    intent: dict[str, object] | None = None
    reply_to_id: str | None = None
    created_at: str
    completed_at: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_role_fields(self) -> Self:
        if self.role == "user":
            if not self.client_message_id:
                raise ValueError("user message requires client_message_id")
            return self
        if self.client_message_id is not None:
            raise ValueError("assistant message cannot have client_message_id")
        if self.status != "completed" or not self.reply_to_id:
            raise ValueError("assistant message must be a completed reply")
        if self.completed_at is None:
            raise ValueError("assistant message requires completed_at")
        return self


class MessageProcessingAttempt(BaseModel):
    """One processing attempt for an accepted user message."""

    id: str
    user_message_id: str
    attempt: int = Field(ge=1)
    status: Literal[
        "accepted", "processing", "completed", "failed", "cancelled"
    ]
    assistant_message_id: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    started_at: str
    completed_at: str | None = None


class CitationDraft(BaseModel):
    """A task-scoped citation before it is attached to a message."""

    citation_kind: Literal["verified_evidence", "material_clue"]
    document_id: str
    evidence_id: str | None = None
    fact_id: str | None = None
    title: str
    source_url: str
    quote_text: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    source_content_hash: str

    @model_validator(mode="after")
    def validate_line_range(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("citation line_end must not precede line_start")
        return self


class MessageCitation(CitationDraft):
    """A citation durably attached to one assistant message."""

    id: str
    task_id: str
    message_id: str
    sequence: int = Field(ge=1)
    created_at: str


class ActionRequest(BaseModel):
    """One proposed or explicitly requested task action."""

    id: str
    task_id: str
    trigger_message_id: str
    action_type: ActionType
    immutable_payload: dict[str, object]
    request_mode: Literal["explicit_message", "confirmed_proposal"] | None = (
        None
    )
    request_message_id: str | None = None
    precondition_committed_state_version: int = Field(ge=0)
    precondition_search_plan_version_id: str | None = None
    status: ActionRequestStatus
    created_at: str
    confirmed_at: str | None = None
    queued_at: str | None = None
    executing_at: str | None = None
    completed_at: str | None = None
    created_research_run_id: str | None = None
    target_research_run_id: str | None = None
    applied_search_plan_version_id: str | None = None
    applied_checkpoint_id: str | None = None
    created_report_version_id: str | None = None
    error: str | None = None
    expires_at: str | None = None

    @model_validator(mode="after")
    def validate_request_fields(self) -> Self:
        if self.status == "proposed":
            if self.request_mode is not None or self.request_message_id:
                raise ValueError("proposed action cannot have request fields")
        elif self.status in {"rejected", "expired"} and (
            self.request_mode is None and self.request_message_id is None
        ):
            pass
        elif self.request_mode is None or not self.request_message_id:
            raise ValueError(
                "queued or terminal action requires request fields"
            )
        if (
            self.action_type == "modify_search_plan"
            and not self.precondition_search_plan_version_id
        ):
            raise ValueError(
                "modify_search_plan requires a plan version precondition"
            )
        return self


class ResearchRun(BaseModel):
    """One auditable execution attempt for a research task."""

    id: str
    task_id: str
    run_type: Literal["initial", "continue_research", "retry", "legacy_import"]
    provenance: Literal["native", "migrated"] = "native"
    trigger_message_id: str | None = None
    action_request_id: str | None = None
    retry_of_run_id: str | None = None
    input_committed_state_version: int = Field(ge=0)
    input_snapshot: dict[str, object]
    initial_search_plan_version_id: str | None = None
    active_search_plan_version_id: str | None = None
    status: ResearchRunStatus
    phase: (
        Literal["planning", "collecting", "assessing", "checkpointing"] | None
    ) = None
    outcome: Literal["sufficient", "with_gaps"] | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        terminal = {
            "stopped",
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }
        if self.status in terminal and self.completed_at is None:
            raise ValueError("terminal run requires completed_at")
        if self.run_type == "retry" and not self.retry_of_run_id:
            raise ValueError("retry run requires retry_of_run_id")
        return self


class SearchPlanVersion(BaseModel):
    """An immutable search plan version used by one research run."""

    id: str
    task_id: str
    research_run_id: str
    sequence: int = Field(ge=1)
    plan: dict[str, object]
    trigger_message_id: str | None = None
    action_request_id: str | None = None
    created_at: str


AssetType = Literal[
    "document",
    "fact",
    "evidence",
    "review",
    "conflict",
    "coverage",
    "material_digest",
    "task_revision",
]


class AssetRevisionRef(BaseModel):
    """Immutable reference to one logical asset revision."""

    asset_type: AssetType
    logical_id: str
    revision_id: str
    content_sha256: str
    task_id: str


class CommittedResearchSnapshot(BaseModel):
    """Fixed committed read view for one task version."""

    task_id: str
    version: int = Field(ge=0)
    checkpoint_id: str | None = None
    asset_manifest: list[AssetRevisionRef] = Field(default_factory=list)
    fingerprint: str
    created_at: str


class RunWorkspace(BaseModel):
    """Staged revisions visible only to one research run."""

    run_id: str
    task_id: str
    base_version: int = Field(ge=0)
    staged_revisions: list[AssetRevisionRef] = Field(default_factory=list)
    status: Literal["open", "committed", "abandoned"]


class ResearchOutcome(BaseModel):
    """Durable outcome of a run and its version effect."""

    run_id: str
    task_id: str
    outcome: Literal[
        "committed",
        "no_progress",
        "failed",
        "cancelled",
        "stopped",
        "interrupted",
    ]
    committed_state_version: int = Field(ge=0)
    snapshot_fingerprint: str | None = None
    created_at: str


class ResearchCheckpoint(BaseModel):
    """A durable boundary that commits research state atomically."""

    id: str
    task_id: str
    research_run_id: str
    sequence: int = Field(ge=1)
    search_plan_version_id: str | None = None
    input_committed_state_version: int = Field(ge=0)
    output_committed_state_version: int | None = Field(default=None, ge=0)
    status: CheckpointStatus
    trigger_action_request_id: str | None = None
    reason: str
    started_at: str
    committed_at: str | None = None

    @model_validator(mode="after")
    def validate_commit_fields(self) -> Self:
        if self.status == "committed" and (
            self.output_committed_state_version is None
            or self.committed_at is None
        ):
            raise ValueError("committed checkpoint requires output and time")
        if self.status != "committed" and (
            self.output_committed_state_version is not None
            or self.committed_at is not None
        ):
            raise ValueError("uncommitted checkpoint cannot expose output")
        return self


class ReportVersion(BaseModel):
    """An immutable task report bound to one committed research state."""

    id: str
    task_id: str
    version: int = Field(ge=1)
    status: ReportVersionStatus
    content_path: str
    content_sha256: str
    based_on_checkpoint_id: str | None = None
    based_on_committed_state_version: int = Field(ge=0)
    snapshot_fingerprint: str | None = None
    publication_origin: Literal["native", "legacy_migration"] = "native"
    created_at: str
    published_at: str | None = None
    abandoned_at: str | None = None

    @model_validator(mode="after")
    def validate_status_times(self) -> Self:
        if self.status in {"published", "superseded"}:
            if self.published_at is None:
                raise ValueError("published report requires published_at")
        elif self.published_at is not None:
            raise ValueError("unpublished report cannot have published_at")
        if self.status == "abandoned" and self.abandoned_at is None:
            raise ValueError("abandoned report requires abandoned_at")
        if self.status != "abandoned" and self.abandoned_at is not None:
            raise ValueError("active report cannot have abandoned_at")
        return self


class TimelineEntry(BaseModel):
    """Rebuildable display projection with its own cursor."""

    id: str
    conversation_id: str
    timeline_sequence: int = Field(ge=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    entry_type: str
    data: dict[str, object] = Field(default_factory=dict)
    created_at: str


class ConversationEvent(BaseModel):
    """One durable event in a task conversation."""

    id: int = Field(ge=1)
    conversation_id: str
    sequence: int = Field(ge=1)
    event_type: str
    data: dict[str, object] = Field(default_factory=dict)
    message_id: str | None = None
    action_request_id: str | None = None
    research_run_id: str | None = None
    created_at: str


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
    extraction_status: Literal["complete", "unavailable", "failed"] = (
        "complete"
    )
    collection_method: Literal["http", "browser", "archive"] = "http"
    # Provider-declared role when the source came from a vertical search
    # (e.g. GitHub release -> primary, issue -> supporting); recorded for
    # the future quality model, not yet consumed by coverage scoring.
    evidence_role: EvidenceRole | None = None
    rendered_url: str | None = None
    rendered_path: str | None = None
    rendered_sha256: str | None = None
    render_error: str | None = None
    injection_warnings: list[str] = Field(default_factory=list)


class MaterialReview(BaseModel):
    task_id: str
    canonical_url: str
    document_id: str | None = None
    rating: int = Field(ge=1, le=5)
    description: str = Field(max_length=120)
    question_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


class MaterialDigest(BaseModel):
    task_id: str
    overview: str = ""
    key_points: list[str] = Field(default_factory=list)
    priority_materials: list[str] = Field(default_factory=list)
    reading_guide: dict[str, list[str]] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    materials: list[MaterialReview] = Field(default_factory=list)
    created_at: str
    updated_at: str


class Fact(BaseModel):
    """A canonical atomic statement; superseded facts keep history for audit."""

    id: str
    task_id: str
    question_id: str
    statement: str
    claim_type: ClaimType = "corroborated"
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
    in_scope_sources: int = 0
    time_scope_gap: int = 0
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
    answer_status: AnswerStatus | None = None
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


class ResearchReportedConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reported"] = "reported"
    fact_id: str


class ResearchInferenceConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["inference"] = "inference"
    statement: str
    confidence: Literal["high", "medium", "low"]
    fact_ids: list[str]


ResearchConclusion = (
    FactConclusion | ResearchReportedConclusion | ResearchInferenceConclusion
)


class ResearchReportSection(BaseModel):
    question_id: str
    conclusions: list[ResearchConclusion] = Field(default_factory=list)


class ResearchReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[ResearchReportSection] = Field(default_factory=list)
    overall_conclusions: list[ResearchConclusion] = Field(default_factory=list)


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

    def __init__(self, code: str, message: str, *, downloaded_bytes: int = 0):
        super().__init__(message)
        self.code = code
        self.name = "IntelError"
        self.downloaded_bytes = downloaded_bytes


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
