"""Fact-check domain models (spec 002 §4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..contracts._time import AwareDatetime, JsonValue
from ..contracts.documents import Citation

Verdict = Literal[
    "supported",
    "mostly_supported",
    "insufficient",
    "disputed",
    "mostly_refuted",
    "refuted",
]
EvidenceSufficiency = Literal["high", "medium", "low"]
Checkability = Literal["pending", "checkable", "not_checkable"]
EvidenceRelation = Literal["supports", "contradicts"]
SourceNature = Literal["primary", "secondary", "unknown"]


class FactCheck(BaseModel):
    fact_check_id: str
    task_id: str
    claim: str
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    understanding: str = ""
    questions: list[str] = Field(default_factory=list)
    checkability: Checkability = "pending"
    checkability_reason: str | None = None
    verdict: Verdict | None = None
    evidence_sufficiency: EvidenceSufficiency | None = None
    rationale: str = ""
    limitations: list[str] = Field(default_factory=list)
    independent_sources: int = Field(default=0, ge=0)
    primary_sources: int = Field(default=0, ge=0)
    counter_evidence: int = Field(default=0, ge=0)


class FactEvidence(BaseModel):
    evidence_id: str
    fact_check_id: str
    relation: EvidenceRelation
    quote: str
    citation: Citation
    publisher_key: str | None = None
    independence_group: str | None = None
    source_nature: SourceNature = "unknown"
    attribution_basis: str = ""
    source_title: str = ""


class FactCheckView(BaseModel):
    """Read projection of a fact check plus its task state and evidence."""

    fact_check: FactCheck
    status: str
    phase: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: JsonValue | None = None
    evidence: list[FactEvidence] = Field(default_factory=list)
