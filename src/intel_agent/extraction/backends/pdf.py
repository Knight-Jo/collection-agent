"""Dual real PDF backends: PyMuPDF and pdfplumber (spec §8.4)."""

from __future__ import annotations

import io

from ...contracts.documents import CoverageUnit, Locator
from ..models import Availability, BackendOutput, BackendRequest
from ._base import BaseBackend
from ._util import make_block


def _normalized_bbox(x0, y0, x1, y1, width, height) -> tuple:
    return (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, y0 / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
    )


class PyMuPDFBackend(BaseBackend):
    backend_id = "pymupdf"
    version = "1.28"
    capabilities = ("pdf_text", "pdf_structure")
    media_types = ("application/pdf",)

    def availability(self) -> Availability:
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            return "missing_dependency"
        return "available"

    async def run(self, request: BackendRequest) -> BackendOutput:
        import pymupdf

        data = self.read_bytes(request.resource_id)
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as error:  # noqa: BLE001
            return BackendOutput(
                coverage=[
                    CoverageUnit(
                        unit_type="document",
                        locator=Locator(),
                        status="failed",
                        reason=str(error),
                    )
                ],
                warnings=[f"pdf open failed: {error}"],
            )
        blocks = []
        coverage: list[CoverageUnit] = []
        ordinal = 1
        page_count = doc.page_count
        try:
            for page_num in range(1, doc.page_count + 1):
                page = doc[page_num - 1]
                rect = page.rect
                page_blocks = page.get_text("blocks") or []
                text_blocks = [b for b in page_blocks if b[6] == 0]
                if not text_blocks:
                    coverage.append(
                        CoverageUnit(
                            unit_type="page",
                            locator=Locator(page=page_num),
                            status="empty",
                        )
                    )
                    continue
                for block in text_blocks:
                    x0, y0, x1, y1, text = (
                        block[0],
                        block[1],
                        block[2],
                        block[3],
                        block[4],
                    )
                    text = text.strip()
                    if not text:
                        continue
                    blocks.append(
                        make_block(
                            self.backend_id,
                            self.version,
                            ordinal,
                            text,
                            "paragraph",
                            locator=Locator(
                                page=page_num,
                                bbox=_normalized_bbox(
                                    x0, y0, x1, y1, rect.width, rect.height
                                ),
                            ),
                        )
                    )
                    ordinal += 1
                coverage.append(
                    CoverageUnit(
                        unit_type="page",
                        locator=Locator(page=page_num),
                        status="success",
                    )
                )
        finally:
            doc.close()
        return BackendOutput(
            blocks=blocks,
            coverage=coverage,
            metrics={"backend": self.backend_id, "pages": page_count},
        )


class PdfplumberBackend(BaseBackend):
    backend_id = "pdfplumber"
    version = "0.11"
    capabilities = ("pdf_text", "pdf_structure")
    media_types = ("application/pdf",)

    def availability(self) -> Availability:
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            return "missing_dependency"
        return "available"

    async def run(self, request: BackendRequest) -> BackendOutput:
        import pdfplumber

        data = self.read_bytes(request.resource_id)
        blocks = []
        coverage: list[CoverageUnit] = []
        ordinal = 1
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    lines = [
                        ln.strip() for ln in text.split("\n") if ln.strip()
                    ]
                    for line in lines:
                        blocks.append(
                            make_block(
                                self.backend_id,
                                self.version,
                                ordinal,
                                line,
                                "paragraph",
                                locator=Locator(page=page_num),
                            )
                        )
                        ordinal += 1
                    for table in page.extract_tables() or []:
                        rows = [
                            " | ".join(c or "" for c in row) for row in table
                        ]
                        if rows:
                            blocks.append(
                                make_block(
                                    self.backend_id,
                                    self.version,
                                    ordinal,
                                    "\n".join(rows),
                                    "table",
                                    locator=Locator(page=page_num),
                                )
                            )
                            ordinal += 1
                    coverage.append(
                        CoverageUnit(
                            unit_type="page",
                            locator=Locator(page=page_num),
                            status="success" if lines or table else "empty",
                        )
                    )
        except Exception as error:  # noqa: BLE001
            return BackendOutput(
                coverage=[
                    CoverageUnit(
                        unit_type="document",
                        locator=Locator(),
                        status="failed",
                        reason=str(error),
                    )
                ],
                warnings=[f"pdf open failed: {error}"],
            )
        return BackendOutput(
            blocks=blocks,
            coverage=coverage,
            metrics={"backend": self.backend_id},
        )
