"""ExtractionService: media routing, backend fallback, coverage (spec §8)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from ..contracts.documents import (
    BackendAttempt,
    CoverageUnit,
    ExtractResult,
    Locator,
)
from ..contracts.errors import DomainError
from ..contracts.resources import Resource
from ..runtime._profile import profile_id as _hash
from ..runtime.config import ExtractionConfig
from ..runtime.execution import Executor
from .models import BackendOutput, BackendRequest
from .registry import BackendRegistry

DOCX = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PPTX = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExtractionProfile(BaseModel):
    name: str
    media_type: str
    preferred: str
    fallback: str | None = None
    ocr_languages: str = "chi_sim+eng"

    def id(self) -> str:
        return _hash(
            {
                "name": self.name,
                "media_type": self.media_type,
                "preferred": self.preferred,
                "fallback": self.fallback,
            }
        )


class ExtractionService:
    def __init__(
        self,
        registry: BackendRegistry,
        resource_store,
        executor: Executor,
        config: ExtractionConfig,
    ) -> None:
        self.registry = registry
        self.resource_store = resource_store
        self.executor = executor
        self.config = config
        self._profiles: dict[str, ExtractionProfile] = {}
        self._audio_extractor = None
        self._video_extractor = None

    def register_profile(self, profile: ExtractionProfile) -> str:
        pid = profile.id()
        self._profiles[pid] = profile
        return pid

    def profile_for(self, media_type: str) -> str | None:
        for pid, profile in self._profiles.items():
            if profile.media_type == media_type:
                return pid
        prefix = media_type.split("/")[0] + "/*"
        for pid, profile in self._profiles.items():
            if profile.media_type == prefix:
                return pid
        return None

    def default_profiles(self) -> list[ExtractionProfile]:
        return [
            ExtractionProfile(
                name="html",
                media_type="text/html",
                preferred="trafilatura",
                fallback="beautifulsoup",
            ),
            ExtractionProfile(
                name="pdf",
                media_type="application/pdf",
                preferred="pymupdf",
                fallback="pdfplumber",
            ),
            ExtractionProfile(
                name="image",
                media_type="image/*",
                preferred="tesseract",
            ),
            ExtractionProfile(
                name="docx", media_type=DOCX, preferred="office"
            ),
            ExtractionProfile(
                name="pptx", media_type=PPTX, preferred="office"
            ),
            ExtractionProfile(
                name="xlsx", media_type=XLSX, preferred="office"
            ),
        ]

    async def extract(
        self, resource: Resource, profile_id: str
    ) -> ExtractResult:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise DomainError(
                "INVALID_REQUEST",
                f"unknown profile: {profile_id}",
                stage="extraction",
            )
        media_type = resource.media_type
        if media_type == "text/html":
            return await self._extract_html(resource, profile)
        if media_type == "application/pdf":
            return await self._extract_pdf(resource, profile)
        if media_type.startswith("image/"):
            return await self._extract_image(resource, profile)
        if media_type in (DOCX, PPTX, XLSX):
            return await self._extract_office(resource, profile)
        if media_type.startswith("audio/"):
            return await self._extract_audio(resource, profile)
        if media_type.startswith("video/"):
            return await self._extract_video(resource, profile)
        raise DomainError(
            "UNSUPPORTED_MEDIA",
            f"unsupported media type: {media_type}",
            stage="extraction",
        )

    async def _run(
        self,
        backend_id: str,
        resource_id: str,
        capability,
        profile,
        locator: Locator | None = None,
    ) -> tuple[BackendOutput | None, BackendAttempt, str | None]:
        backend = self.registry.get(backend_id)
        if backend.availability() != "available":
            attempt = BackendAttempt(
                backend_id=backend_id,
                backend_version=backend.version,
                capability=capability,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                status="failed",
                error="backend unavailable",
            )
            return None, attempt, None
        request = BackendRequest(
            resource_id=resource_id,
            capability=capability,
            locator=locator,
            profile_id=profile.id(),
            remaining_seconds=self.config.resource_deadline_seconds,
        )
        started = datetime.now(UTC)
        try:
            output = await self.executor.run_backend(backend, request)
            attempt = BackendAttempt(
                backend_id=backend_id,
                backend_version=backend.version,
                capability=capability,
                started_at=started,
                ended_at=datetime.now(UTC),
                status="success",
            )
            return output, attempt, None
        except DomainError as error:
            attempt = BackendAttempt(
                backend_id=backend_id,
                backend_version=backend.version,
                capability=capability,
                started_at=started,
                ended_at=datetime.now(UTC),
                status="failed",
                error=error.code,
            )
            return None, attempt, error.code
        except Exception as error:  # noqa: BLE001
            attempt = BackendAttempt(
                backend_id=backend_id,
                backend_version=backend.version,
                capability=capability,
                started_at=started,
                ended_at=datetime.now(UTC),
                status="failed",
                error=str(error),
            )
            return None, attempt, str(error)

    async def _extract_html(self, resource, profile) -> ExtractResult:
        attempts = []
        warnings: list[str] = []
        preferred = profile.preferred
        output, attempt, error = await self._run(
            preferred, resource.resource_id, "html_structure", profile
        )
        attempts.append(attempt)
        if output is None or not output.blocks:
            if error:
                warnings.append(f"preferred backend failed: {error}")
            if profile.fallback:
                output2, attempt2, error2 = await self._run(
                    profile.fallback,
                    resource.resource_id,
                    "html_structure",
                    profile,
                )
                attempts.append(attempt2)
                if output2 is not None and output2.blocks:
                    output = output2
                    warnings.append(
                        f"fell back to {profile.fallback}: {error2}"
                    )
        blocks = output.blocks if output else []
        coverage = output.coverage if output else []
        title = next((b.text for b in blocks if b.block_type == "title"), None)
        return self._result(
            resource, profile, blocks, coverage, attempts, warnings, title
        )

    async def _extract_pdf(self, resource, profile) -> ExtractResult:
        attempts = []
        warnings: list[str] = []
        output, attempt, error = await self._run(
            profile.preferred, resource.resource_id, "pdf_text", profile
        )
        attempts.append(attempt)
        if output is None and profile.fallback:
            output2, attempt2, error2 = await self._run(
                profile.fallback,
                resource.resource_id,
                "pdf_text",
                profile,
            )
            attempts.append(attempt2)
            if output2 is not None:
                output = output2
                warnings.append(f"fell back to {profile.fallback}")
        if output is None:
            raise DomainError(
                "EXTRACTION_FAILED",
                "no PDF backend produced output",
                stage="extraction",
            )
        # Per-page OCR fallback for empty pages, when OCR is available.
        if self.registry.available("tesseract"):
            output = await self._ocr_empty_pages(
                resource, profile, output, attempts, warnings
            )
        return self._result(
            resource,
            profile,
            output.blocks,
            output.coverage,
            attempts,
            warnings,
            None,
        )

    async def _ocr_empty_pages(
        self, resource, profile, output, attempts, warnings
    ):
        import pymupdf

        empty_pages = [
            c.locator.page
            for c in output.coverage
            if c.unit_type == "page"
            and c.status == "empty"
            and c.locator.page is not None
        ]
        if not empty_pages:
            return output
        data = self.resource_store.blob_path(resource.resource_id).read_bytes()
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            ocr_blocks = []
            for page_num in empty_pages:
                page = doc[page_num - 1]
                pixmap = page.get_pixmap()
                import tempfile
                from pathlib import Path

                with tempfile.TemporaryDirectory() as tmp:
                    img = Path(tmp) / "page.png"
                    pixmap.save(str(img))
                    # Import image as a derived resource via a fresh stream.
                    from ..contracts.resources import ResourceOrigin

                    img_resource = await self.resource_store.write_stream(
                        self._file_chunks(img),
                        origin=ResourceOrigin(
                            requested_url=resource.origin.requested_url,
                            acquired_at=datetime.now(UTC),
                        ),
                        media_type="image/png",
                        parent_resource_id=resource.resource_id,
                        transform={"page": page_num},
                    )
                    output2, attempt2, _ = await self._run(
                        "tesseract",
                        img_resource.resource_id,
                        "ocr",
                        profile,
                        locator=Locator(page=page_num),
                    )
                    attempts.append(attempt2)
                    if output2 is not None:
                        ocr_blocks.extend(output2.blocks)
                        for i, cov in enumerate(output.coverage):
                            if (
                                cov.unit_type == "page"
                                and cov.locator.page == page_num
                            ):
                                output.coverage[i] = CoverageUnit(
                                    unit_type="page",
                                    locator=Locator(page=page_num),
                                    status="success",
                                )
                    else:
                        warnings.append(f"OCR failed for page {page_num}")
            return BackendOutput(
                blocks=list(output.blocks) + ocr_blocks,
                coverage=output.coverage,
                warnings=output.warnings + warnings,
            )
        finally:
            doc.close()

    @staticmethod
    async def _file_chunks(path):
        with path.open("rb") as fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    async def _extract_image(self, resource, profile) -> ExtractResult:
        attempts = []
        output, attempt, error = await self._run(
            "tesseract", resource.resource_id, "ocr", profile
        )
        attempts.append(attempt)
        warnings = [f"ocr failed: {error}"] if error else []
        blocks = output.blocks if output else []
        coverage = output.coverage if output else []
        return self._result(
            resource, profile, blocks, coverage, attempts, warnings, None
        )

    async def _extract_office(self, resource, profile) -> ExtractResult:
        capability = {
            DOCX: "docx_structure",
            PPTX: "pptx_structure",
            XLSX: "xlsx_structure",
        }[resource.media_type]
        attempts = []
        output, attempt, error = await self._run(
            "office", resource.resource_id, capability, profile
        )
        attempts.append(attempt)
        warnings = [f"office failed: {error}"] if error else []
        blocks = output.blocks if output else []
        coverage = output.coverage if output else []
        return self._result(
            resource, profile, blocks, coverage, attempts, warnings, None
        )

    async def _extract_audio(self, resource, profile) -> ExtractResult:
        if self._audio_extractor is None:
            from .audio import AudioExtractor

            self._audio_extractor = AudioExtractor(
                self.registry, self.resource_store, self.executor, self.config
            )
        return await self._audio_extractor.extract(resource, profile)

    async def _extract_video(self, resource, profile) -> ExtractResult:
        if self._video_extractor is None:
            from .video import VideoExtractor

            self._video_extractor = VideoExtractor(
                self.registry, self.resource_store, self.executor, self.config
            )
        return await self._video_extractor.extract(resource, profile)

    @staticmethod
    def _result(
        resource, profile, blocks, coverage, attempts, warnings, title
    ) -> ExtractResult:
        status = (
            "empty"
            if not blocks
            else "partial"
            if any(
                c.status in ("failed", "empty", "skipped") for c in coverage
            )
            else "success"
        )
        return ExtractResult(
            resource_id=resource.resource_id,
            title=title,
            blocks=blocks,
            coverage=coverage,
            status=status,
            attempts=attempts,
            warnings=warnings,
            extraction_profile_id=profile.id(),
        )
