"""Multi-format report export (markdown, PDF, Word)."""

from __future__ import annotations

from datetime import UTC, datetime

from ..contracts.research import ResearchReport
from .exporters import render_docx, render_markdown, render_pdf
from .references import ExportMeta, Reference, references_from_evidence

EXPORT_FORMATS = ("markdown", "pdf", "docx")

MEDIA_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
    "docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
}

EXTENSIONS = {"markdown": "md", "pdf": "pdf", "docx": "docx"}


def normalize_format(value: str) -> str:
    """Accept common aliases; raises ValueError on unknown formats."""
    folded = (value or "").strip().lower()
    aliases = {"md": "markdown", "word": "docx"}
    folded = aliases.get(folded, folded)
    if folded not in EXPORT_FORMATS:
        raise ValueError(f"unknown export format: {value!r}")
    return folded


def ascii_slug(text: str, fallback: str = "report") -> str:
    """ASCII-only filename stem (Content-Disposition is latin-1 safe)."""
    slug = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch == "-") else "-"
        for ch in text.lower()
    )
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or fallback


def export_filename(report: ResearchReport, fmt: str, meta: ExportMeta) -> str:
    stem = ascii_slug(report.title or meta.subject)
    return f"{stem}-{meta.generated_at:%Y%m%d}.{EXTENSIONS[fmt]}"


def render_report(
    report: ResearchReport,
    evidence: dict | None,
    fmt: str,
    *,
    subject: str = "",
    generated_at: datetime | None = None,
) -> bytes:
    """Render a stored report in the requested format.

    The references appendix is derived from the stored evidence review;
    the document header carries the subject and generation time.
    """
    fmt = normalize_format(fmt)
    meta = ExportMeta(
        subject=subject, generated_at=generated_at or datetime.now(UTC)
    )
    references = references_from_evidence(evidence)
    renderers = {
        "markdown": render_markdown,
        "pdf": render_pdf,
        "docx": render_docx,
    }
    return renderers[fmt](report, references, meta)


__all__ = [
    "EXPORT_FORMATS",
    "EXTENSIONS",
    "ExportMeta",
    "MEDIA_TYPES",
    "Reference",
    "ascii_slug",
    "export_filename",
    "normalize_format",
    "references_from_evidence",
    "render_markdown",
    "render_pdf",
    "render_docx",
    "render_report",
]
