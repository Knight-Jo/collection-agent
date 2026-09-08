"""Renderers: ResearchReport -> markdown / PDF / Word bytes.

Bodies are LLM-generated markdown. Markdown passes through verbatim; docx and
PDF apply a light line-based conversion (headings, bullets, numbered lists,
bold/italic runs). Markdown tables have no structured equivalent here and are
kept as plain text.
"""

from __future__ import annotations

import io
import re
from contextlib import suppress

from docx import Document
from docx.document import Document as DocxDocument
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from ..contracts.research import ResearchReport
from .references import ExportMeta, Reference

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_BULLET_RE = re.compile(r"^\s*[-*]\s+")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")

_CJK_FONT = "STSong-Light"


# --- markdown ---------------------------------------------------------------


def render_markdown(
    report: ResearchReport, references: list[Reference], meta: ExportMeta
) -> bytes:
    parts = [f"# {report.title or '调研报告'}"]
    parts.append(_meta_line_markdown(meta))
    parts.extend(_body_markdown(report))
    if references:
        parts.append("## 参考文献")
        parts.append(
            "\n".join(
                f"{ref.index}. [{ref.title or ref.url}]({ref.url})"
                if ref.url
                else f"{ref.index}. {ref.title}"
                for ref in references
            )
        )
    return "\n\n".join(parts).encode("utf-8")


def _meta_line_markdown(meta: ExportMeta) -> str:
    stamp = meta.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    if meta.subject:
        return f"> 主题：{meta.subject}\n> 生成时间：{stamp}"
    return f"> 生成时间：{stamp}"


def _body_markdown(report: ResearchReport) -> list[str]:
    parts: list[str] = []
    for section in report.sections:
        parts.append(f"## {section.heading}")
        parts.append(section.body.strip())
    if report.conclusions:
        parts.append("## 结论")
        parts.append("\n".join(f"- {c}" for c in report.conclusions))
    if report.limitations:
        parts.append("## 局限")
        parts.append("\n".join(f"- {lim}" for lim in report.limitations))
    return [p for p in parts if p]


# --- docx -------------------------------------------------------------------


def render_docx(
    report: ResearchReport, references: list[Reference], meta: ExportMeta
) -> bytes:
    doc = Document()
    doc.add_heading(report.title or "调研报告", 0)

    meta_par = doc.add_paragraph()
    meta_par.add_run(_meta_text(meta)).italic = True

    for section in report.sections:
        doc.add_heading(section.heading, level=1)
        _docx_body(doc, section.body)

    if report.conclusions:
        doc.add_heading("结论", level=1)
        for item in report.conclusions:
            doc.add_paragraph(item, style="List Bullet")
    if report.limitations:
        doc.add_heading("局限", level=1)
        for item in report.limitations:
            doc.add_paragraph(item, style="List Bullet")
    if references:
        doc.add_heading("参考文献", level=1)
        for ref in references:
            entry = f"{ref.title} — {ref.url}" if ref.url else ref.title
            doc.add_paragraph(entry, style="List Number")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _meta_text(meta: ExportMeta) -> str:
    stamp = meta.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    subject = f"主题：{meta.subject}　" if meta.subject else ""
    return f"{subject}生成时间：{stamp}"


def _docx_body(doc: DocxDocument, body: str) -> None:
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if _BULLET_RE.match(line):
            _add_runs(
                doc.add_paragraph(style="List Bullet"),
                _BULLET_RE.sub("", line),
            )
        elif _NUMBERED_RE.match(line):
            _add_runs(
                doc.add_paragraph(style="List Number"),
                _NUMBERED_RE.sub("", line),
            )
        else:
            heading = _HEADING_RE.match(line)
            if heading:
                doc.add_heading(heading.group(2).strip(), level=3)
            else:
                _add_runs(doc.add_paragraph(), line)


def _add_runs(paragraph, text: str) -> None:
    """Split markdown bold/italic markers into styled runs."""
    segments = [(text, None)]
    for pattern, style in ((_BOLD_RE, "bold"), (_ITALIC_RE, "italic")):
        next_segments: list[tuple[str, str | None]] = []
        for chunk, current in segments:
            pos = 0
            for match in pattern.finditer(chunk):
                next_segments.append((chunk[pos : match.start()], current))
                next_segments.append((match.group(1), style))
                pos = match.end()
            next_segments.append((chunk[pos:], current))
        segments = next_segments
    for chunk, style in segments:
        if not chunk:
            continue
        run = paragraph.add_run(chunk)
        if style:
            setattr(run, style, True)


# --- pdf --------------------------------------------------------------------


def render_pdf(
    report: ResearchReport, references: list[Reference], meta: ExportMeta
) -> bytes:
    with suppress(KeyError):  # already registered in this process
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))

    base = ParagraphStyle(
        "body",
        fontName=_CJK_FONT,
        fontSize=10.5,
        leading=16,
        spaceAfter=6,
    )
    h1 = ParagraphStyle(
        "h1", parent=base, fontSize=15, leading=20, spaceBefore=12
    )
    title_style = ParagraphStyle("title", parent=base, fontSize=20, leading=26)
    meta_style = ParagraphStyle(
        "meta", parent=base, fontSize=9, textColor=colors.HexColor("#666666")
    )

    story: list[Flowable] = [
        Paragraph(_escape(report.title or "调研报告"), title_style),
        Paragraph(_escape(_meta_text(meta)), meta_style),
        Spacer(1, 4 * mm),
    ]
    for section in report.sections:
        story.append(Paragraph(_escape(section.heading), h1))
        story.extend(_pdf_body(section.body, base))
    if report.conclusions:
        story.append(Paragraph("结论", h1))
        for item in report.conclusions:
            story.append(Paragraph(_inline(item), base, bulletText="•"))
    if report.limitations:
        story.append(Paragraph("局限", h1))
        for item in report.limitations:
            story.append(Paragraph(_inline(item), base, bulletText="•"))
    if references:
        story.append(Paragraph("参考文献", h1))
        for ref in references:
            entry = f"{ref.index}. {_escape(ref.title)}"
            if ref.url:
                entry += f" — {_escape(ref.url)}"
            story.append(Paragraph(entry, base))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=report.title or "调研报告",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(story)
    return buffer.getvalue()


def _pdf_body(body: str, base: ParagraphStyle) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _BULLET_RE.match(stripped):
            text = _BULLET_RE.sub("", stripped)
            paragraphs.append(Paragraph(_inline(text), base, bulletText="•"))
        elif _NUMBERED_RE.match(stripped):
            text = _NUMBERED_RE.sub("", stripped)
            paragraphs.append(Paragraph(_inline(text), base))
        else:
            heading = _HEADING_RE.match(stripped)
            if heading:
                paragraphs.append(Paragraph(_escape(heading.group(2)), base))
            else:
                paragraphs.append(Paragraph(_inline(stripped), base))
    return paragraphs


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    """Markdown emphasis to reportlab's inline markup, after escaping."""
    escaped = _escape(text)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    return escaped


__all__ = ["render_markdown", "render_docx", "render_pdf"]
