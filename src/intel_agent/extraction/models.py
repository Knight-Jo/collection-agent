"""Extraction backend contracts (spec §8.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

from ..contracts.documents import CoverageUnit, EvidenceBlock, Locator
from ..contracts.resources import Resource

Availability = Literal[
    "available", "missing_dependency", "missing_model", "disabled"
]

Capability = Literal[
    "html_structure",
    "pdf_text",
    "pdf_structure",
    "ocr",
    "docx_structure",
    "pptx_structure",
    "xlsx_structure",
    "media_probe",
    "audio_asr",
    "subtitle_extract",
    "video_frame",
]


class BackendDescriptor(BaseModel):
    backend_id: str
    version: str
    capabilities: list[Capability] = Field(default_factory=list)
    supported_media_types: list[str] = Field(default_factory=list)
    availability: Availability = "available"
    unavailable_reason: str | None = None


class BackendRequest(BaseModel):
    resource_id: str
    capability: Capability
    locator: Locator | None = None
    profile_id: str
    remaining_seconds: float = Field(default=120.0, gt=0)


class BackendOutput(BaseModel):
    blocks: list[EvidenceBlock] = Field(default_factory=list)
    derived_resources: list[Resource] = Field(default_factory=list)
    coverage: list[CoverageUnit] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Backend(ABC):
    """A concrete extraction backend; only the run() contract is fixed."""

    backend_id: str
    version: str
    capabilities: tuple[Capability, ...] = ()
    media_types: tuple[str, ...] = ()

    @abstractmethod
    def availability(self) -> Availability: ...

    @abstractmethod
    async def run(self, request: BackendRequest) -> BackendOutput: ...
