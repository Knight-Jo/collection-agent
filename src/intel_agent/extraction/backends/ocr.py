"""Tesseract OCR backend with TSV boxes and confidence (spec §8.4/§8.5)."""

from __future__ import annotations

import csv
import io
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from ...contracts.documents import CoverageUnit, Locator
from ...contracts.errors import DomainError
from ...runtime.execution import Executor
from ..models import Availability, BackendOutput, BackendRequest
from ._base import BaseBackend
from ._util import make_block


class TesseractBackend(BaseBackend):
    backend_id = "tesseract"
    version = "5"
    capabilities = ("ocr",)
    media_types = ("image/png", "image/jpeg")

    def __init__(
        self,
        resource_store,
        executor: Executor,
        languages: str = "chi_sim+eng",
    ) -> None:
        super().__init__(resource_store)
        self.executor = executor
        self.languages = languages

    def availability(self) -> Availability:
        if shutil.which("tesseract") is None:
            return "missing_dependency"
        return "available"

    async def run(self, request: BackendRequest) -> BackendOutput:
        data = self.read_bytes(request.resource_id)
        try:
            image = Image.open(io.BytesIO(data))
            width, height = image.size
        except Exception as error:  # noqa: BLE001
            return BackendOutput(
                coverage=[
                    CoverageUnit(
                        unit_type="document",
                        locator=Locator(),
                        status="failed",
                        reason=f"image decode: {error}",
                    )
                ],
                warnings=[f"image decode failed: {error}"],
            )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.png"
            input_path.write_bytes(data)
            result = await self.executor.run_process(
                [
                    "tesseract",
                    str(input_path),
                    "stdout",
                    "-l",
                    self.languages,
                    "tsv",
                ],
                timeout_seconds=request.remaining_seconds,
            )
        if result.timed_out or result.returncode != 0:
            raise DomainError(
                "EXTRACTION_FAILED",
                "tesseract failed",
                stage="extraction",
                safe_details={"stderr": result.stderr.decode()[:200]},
            )
        blocks, confidence = self._parse_tsv(
            result.stdout.decode("utf-8", errors="replace"),
            width,
            height,
            request,
        )
        status = "success" if blocks else "empty"
        return BackendOutput(
            blocks=blocks,
            coverage=[
                CoverageUnit(
                    unit_type="document",
                    locator=request.locator or Locator(),
                    status=status,
                )
            ],
            metrics={"ocr_confidence": confidence},
        )

    def _parse_tsv(self, text: str, width: int, height: int, request):
        rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
        # Group level-5 (word) rows into lines; tesseract 4.x leaves line
        # (level 4) text empty and keeps the text at word level.
        lines: dict[tuple, dict] = {}
        for row in rows:
            if row.get("level") != "5":
                continue
            word_text = (row.get("text") or "").strip()
            if not word_text:
                continue
            try:
                key = (
                    row["page_num"],
                    row["block_num"],
                    row["par_num"],
                    row["line_num"],
                )
                left = int(row["left"])
                top = int(row["top"])
                w = int(row["width"])
                h = int(row["height"])
                conf = float(row["conf"])
            except (KeyError, ValueError):
                continue
            line = lines.setdefault(
                key, {"words": [], "bbox": None, "confs": []}
            )
            line["words"].append(word_text)
            line["confs"].append(conf)
            if line["bbox"] is None:
                line["bbox"] = [left, top, left + w, top + h]
            else:
                x0, y0, x1, y1 = line["bbox"]
                line["bbox"] = [
                    min(x0, left),
                    min(y0, top),
                    max(x1, left + w),
                    max(y1, top + h),
                ]
        blocks = []
        confidences: list[float] = []
        for ordinal, (_, line) in enumerate(sorted(lines.items()), start=1):
            x0, y0, x1, y1 = line["bbox"]
            confs = line["confs"]
            # tesseract conf is a 0–100 percentage; EvidenceBlock uses 0–1.
            confidence = sum(confs) / len(confs) / 100.0
            confidences.append(confidence)
            bbox = (
                max(0.0, min(1.0, x0 / width)),
                max(0.0, min(1.0, y0 / height)),
                max(0.0, min(1.0, x1 / width)),
                max(0.0, min(1.0, y1 / height)),
            )
            locator = (
                request.locator.model_copy() if request.locator else Locator()
            )
            locator.bbox = bbox
            blocks.append(
                make_block(
                    self.backend_id,
                    self.version,
                    ordinal,
                    " ".join(line["words"]),
                    "paragraph",
                    locator=locator,
                    origin_method="ocr",
                    confidence=confidence,
                )
            )
        mean_conf = (
            sum(confidences) / len(confidences) if confidences else None
        )
        return blocks, mean_conf
