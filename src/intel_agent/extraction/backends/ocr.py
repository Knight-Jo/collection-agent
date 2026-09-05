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
from ..models import Availability, BackendRequest, BackendOutput
from ._base import BaseBackend
from ._util import make_block


class TesseractBackend(BaseBackend):
    backend_id = "tesseract"
    version = "5"
    capabilities = ("ocr",)
    media_types = ("image/png", "image/jpeg")

    def __init__(self, resource_store, executor: Executor, languages: str = "chi_sim+eng") -> None:
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
                        unit_type="document", locator=Locator(),
                        status="failed", reason=f"image decode: {error}",
                    )
                ],
                warnings=[f"image decode failed: {error}"],
            )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.png"
            input_path.write_bytes(data)
            result = await self.executor.run_process(
                [
                    "tesseract", str(input_path), "stdout",
                    "-l", self.languages, "tsv",
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
            width, height, request,
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
        line_conf: dict[tuple, list[float]] = {}
        for row in rows:
            if row.get("level") == "5" and row.get("conf", "-1") not in (
                "-1", "", None,
            ):
                try:
                    line_conf[
                        (row["page_num"], row["block_num"], row["par_num"],
                         row["line_num"])
                    ].append(float(row["conf"]))
                except (KeyError, ValueError):
                    continue
        blocks = []
        ordinal = 1
        confidences: list[float] = []
        for row in rows:
            if row.get("level") != "4":
                continue
            line_text = (row.get("text") or "").strip()
            if not line_text:
                continue
            try:
                left = int(row["left"])
                top = int(row["top"])
                w = int(row["width"])
                h = int(row["height"])
            except (KeyError, ValueError):
                continue
            key = (row["page_num"], row["block_num"], row["par_num"],
                   row["line_num"])
            confs = line_conf.get(key, [])
            confidence = sum(confs) / len(confs) if confs else None
            if confidence is not None:
                confidences.append(confidence)
            bbox = (
                max(0.0, min(1.0, left / width)),
                max(0.0, min(1.0, top / height)),
                max(0.0, min(1.0, (left + w) / width)),
                max(0.0, min(1.0, (top + h) / height)),
            )
            locator = request.locator.model_copy() if request.locator else Locator()
            locator.bbox = bbox
            blocks.append(
                make_block(
                    self.backend_id, self.version, ordinal, line_text,
                    "paragraph", locator=locator, origin_method="ocr",
                    confidence=confidence,
                )
            )
            ordinal += 1
        mean_conf = (
            sum(confidences) / len(confidences) if confidences else None
        )
        return blocks, mean_conf
