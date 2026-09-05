"""Context layer: scope, retrieval, formatting, and citations (spec §11)."""

from .formatter import (
    build_citations,
    format_context,
    validate_citation_ids,
)
from .manager import ContextManager
from .retrieval import (
    DirectRetriever,
    HybridRetriever,
    LexicalRetriever,
    VectorRetriever,
)

__all__ = [
    "ContextManager",
    "DirectRetriever",
    "HybridRetriever",
    "LexicalRetriever",
    "VectorRetriever",
    "build_citations",
    "format_context",
    "validate_citation_ids",
]
