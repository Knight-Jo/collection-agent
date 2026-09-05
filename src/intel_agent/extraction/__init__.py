"""Extraction layer: routing, backends, and coverage (spec §8)."""

from .models import (
    Availability,
    Backend,
    BackendDescriptor,
    BackendOutput,
    BackendRequest,
    Capability,
)
from .registry import BackendRegistry
from .service import ExtractionProfile, ExtractionService

__all__ = [
    "Availability",
    "Backend",
    "BackendDescriptor",
    "BackendOutput",
    "BackendRegistry",
    "BackendRequest",
    "Capability",
    "ExtractionProfile",
    "ExtractionService",
]
