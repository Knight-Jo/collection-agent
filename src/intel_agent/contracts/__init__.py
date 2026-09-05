"""Cross-module stable models and public ports (spec v0.1)."""

from .documents import (
    BlockSpan,
    Citation,
    CoverageUnit,
    DocumentIdentity,
    EvidenceBlock,
    ExtractResult,
    Locator,
    NormalizationInput,
    NormalizedDocument,
    RetrievalHit,
)
from .errors import DomainError
from .research import (
    BudgetUsage,
    Checkpoint,
    ContextFilter,
    ContextPackage,
    ContextRequest,
    MaterialScope,
    ProviderReport,
    ResearchDecision,
    ResearchResult,
    ResearchTask,
    SearchBatch,
    SearchHit,
    SearchOccurrence,
    SearchQuery,
    SearchRequest,
)
from .resources import FetchRequest, FetchResult, Resource, ResourceOrigin

# Resolve the provenance -> SearchOccurrence forward reference. SearchOccurrence
# lives in research.py (which in turn imports Citation/Chunk from documents),
# so the cross-module reference is materialized here after both are loaded.
_normalization_types = {"SearchOccurrence": SearchOccurrence}
NormalizationInput.model_rebuild(_types_namespace=_normalization_types)
NormalizedDocument.model_rebuild(_types_namespace=_normalization_types)

__all__ = [
    "BlockSpan",
    "BudgetUsage",
    "Checkpoint",
    "Citation",
    "ContextFilter",
    "ContextPackage",
    "ContextRequest",
    "CoverageUnit",
    "DocumentIdentity",
    "DomainError",
    "EvidenceBlock",
    "ExtractResult",
    "FetchRequest",
    "FetchResult",
    "Locator",
    "MaterialScope",
    "NormalizationInput",
    "NormalizedDocument",
    "ProviderReport",
    "ResearchDecision",
    "ResearchResult",
    "ResearchTask",
    "Resource",
    "ResourceOrigin",
    "RetrievalHit",
    "SearchBatch",
    "SearchHit",
    "SearchOccurrence",
    "SearchQuery",
    "SearchRequest",
]
