"""Multi-provider search (spec §6)."""

from .dedup import dedup_key
from .service import SearchService

__all__ = ["SearchService", "dedup_key"]
