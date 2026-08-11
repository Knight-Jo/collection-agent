"""Text and link extraction for resources archived by the crawler."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from importlib import import_module
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .document_extract import decode_body, extract_docx_text, extract_html
from .models import ExtractionResult

_REJECTED_SUFFIXES = {
    ".7z",
    ".apk",
    ".bat",
    ".bz2",
    ".cmd",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".gz",
    ".iso",
    ".jar",
    ".js",
    ".msi",
    ".ps1",
    ".rar",
    ".sh",
    ".tar",
    ".xz",
    ".zip",
}
_REJECTED_MIMES = {
    "application/gzip",
    "application/javascript",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/x-dosexec",
    "application/x-msdownload",
    "application/x-rar-compressed",
    "application/x-sh",
    "application/x-tar",
    "application/zip",
    "text/javascript",
}
_PLAIN_SUFFIXES = {".csv", ".txt"}
_IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
_AUDIO_SUFFIXES = {".flac", ".m4a", ".mp3", ".ogg", ".wav"}
_VIDEO_SUFFIXES = {".mov", ".mp4", ".webm"}
_OFFICE_MIMES = {
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            _append_link(self.links, href, self.base_url)


def _append_link(links: list[str], raw: str, base_url: str) -> None:
    url = urljoin(base_url, raw.strip())
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        url = parsed._replace(fragment="").geturl()
        if url not in links:
            links.append(url)


def _text_links(text: str, base_url: str) -> list[str]:
    links: list[str] = []
    for url in re.findall(r"https?://[^\s<>\]\[\"']+", text):
        _append_link(links, url.rstrip(".,);"), base_url)
    return links


def is_rejected_resource(mime_type: str, url: str) -> bool:
    """Reject active content, archives, and executables before processing."""
    mime = mime_type.split(";", 1)[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    return mime in _REJECTED_MIMES or suffix in _REJECTED_SUFFIXES


def is_supported_resource(mime_type: str, url: str) -> bool:
    mime = mime_type.split(";", 1)[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    return bool(
        mime in {"text/html", "application/xhtml+xml", "application/pdf"}
        or mime.startswith("text/plain")
        or mime == "text/csv"
        or mime in _OFFICE_MIMES
        or mime.startswith("image/")
        or mime.startswith("audio/")
        or mime.startswith("video/")
        or suffix
        in _PLAIN_SUFFIXES
        | _IMAGE_SUFFIXES
        | _AUDIO_SUFFIXES
        | _VIDEO_SUFFIXES
        | {".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx"}
    )


def _number_lines(text: str) -> str:
    return "\n".join(
        f"{number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), 1)
        if line.strip()
    )


def _ocr_image(raw: bytes, languages: str) -> str:
    pytesseract = import_module("pytesseract")
    image_module = import_module("PIL.Image")

    with image_module.open(BytesIO(raw)) as image:
        return str(pytesseract.image_to_string(image, lang=languages))


def _extract_pdf(raw: bytes, languages: str) -> tuple[str, list[str], str]:
    import fitz

    document = fitz.open(stream=raw, filetype="pdf")
    try:
        text = "\n".join(str(page.get_text("text")) for page in document)
        links: list[str] = []
        for page in document:
            for link in page.get_links():
                if uri := link.get("uri"):
                    _append_link(links, str(uri), "")
        normalized = "\n".join(
            line.strip() for line in text.splitlines() if line.strip()
        )
        if len(re.sub(r"\s", "", normalized)) >= 20:
            return normalized, links + _text_links(normalized, ""), "pymupdf"
        pages = []
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pages.append(_ocr_image(pixmap.tobytes("png"), languages))
        return _number_lines("\n".join(pages)), links, "tesseract"
    finally:
        document.close()


def _extract_docx(raw: bytes, base_url: str) -> tuple[str, list[str]]:
    from docx import Document

    document = Document(BytesIO(raw))
    links: list[str] = []
    for relationship in document.part.rels.values():
        if getattr(relationship, "is_external", False):
            _append_link(links, str(relationship.target_ref), base_url)
    text = extract_docx_text(raw)
    for link in _text_links(text, base_url):
        _append_link(links, link, base_url)
    return text, links


def _extract_xlsx(raw: bytes, base_url: str) -> tuple[str, list[str]]:
    openpyxl = import_module("openpyxl")

    workbook = openpyxl.load_workbook(
        BytesIO(raw), read_only=False, data_only=True
    )
    lines: list[str] = []
    links: list[str] = []
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        lines.append(
                            f"{sheet.title}!{cell.coordinate}: {cell.value}"
                        )
                    if cell.hyperlink and cell.hyperlink.target:
                        _append_link(links, cell.hyperlink.target, base_url)
    finally:
        workbook.close()
    text = "\n".join(lines)
    return text, links + _text_links(text, base_url)


def _extract_pptx(raw: bytes, base_url: str) -> tuple[str, list[str]]:
    presentation_class = import_module("pptx").Presentation

    presentation = presentation_class(BytesIO(raw))
    lines: list[str] = []
    links: list[str] = []
    for slide_number, slide in enumerate(presentation.slides, 1):
        for shape in slide.shapes:
            if text := getattr(shape, "text", "").strip():
                lines.append(f"Slide {slide_number}: {text}")
            click = getattr(shape, "click_action", None)
            if click and click.hyperlink.address:
                _append_link(links, click.hyperlink.address, base_url)
    text = "\n".join(lines)
    return text, links + _text_links(text, base_url)


def _convert_legacy_office(raw: bytes, suffix: str, target: str) -> bytes:
    executable = shutil.which("libreoffice")
    if not executable:
        raise FileNotFoundError("libreoffice")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / f"source.{suffix}"
        source.write_bytes(raw)
        subprocess.run(
            [
                executable,
                "--headless",
                "--convert-to",
                target,
                "--outdir",
                directory,
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        output = Path(directory) / f"source.{target}"
        if not output.exists():
            raise RuntimeError(f"LibreOffice did not create {target}")
        return output.read_bytes()


def _transcribe_media(
    raw: bytes, suffix: str, model_name: str
) -> list[tuple[float, float, str]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg")
    whisper_model_class = import_module("faster_whisper").WhisperModel

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / f"source{suffix or '.bin'}"
        audio = Path(directory) / "audio.wav"
        source.write_bytes(raw)
        subprocess.run(
            [
                ffmpeg,
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(audio),
            ],
            check=True,
            capture_output=True,
        )
        segments, _ = whisper_model_class(model_name).transcribe(str(audio))
        return [
            (
                float(segment.start),
                float(segment.end),
                str(segment.text).strip(),
            )
            for segment in segments
            if str(segment.text).strip()
        ]


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}.{milliseconds:03}"


def extract_resource(
    raw: bytes,
    mime_type: str,
    url: str,
    *,
    ocr_languages: str = "chi_sim+eng",
    whisper_model: str = "small",
) -> ExtractionResult:
    """Extract supported content without making optional processors mandatory."""
    mime = mime_type.split(";", 1)[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    if is_rejected_resource(mime, url):
        return ExtractionResult(
            status="skipped", error="rejected resource type"
        )
    if not is_supported_resource(mime, url):
        return ExtractionResult(
            status="skipped", error="unsupported resource type"
        )
    try:
        if mime in {"text/html", "application/xhtml+xml"} or suffix in {
            ".htm",
            ".html",
        }:
            decoded = decode_body(raw, mime_type)
            parser = _LinkParser(url)
            parser.feed(decoded)
            extracted = extract_html(decoded)
            return ExtractionResult(
                status="complete",
                text=extracted["text"],
                links=parser.links,
                processor="html",
            )
        if mime == "application/pdf" or suffix == ".pdf":
            text, links, processor = _extract_pdf(raw, ocr_languages)
            return ExtractionResult(
                status="complete", text=text, links=links, processor=processor
            )
        office_type = _OFFICE_MIMES.get(mime) or suffix.lstrip(".")
        if office_type == "doc":
            raw = _convert_legacy_office(raw, "doc", "docx")
            office_type = "docx"
        elif office_type == "xls":
            raw = _convert_legacy_office(raw, "xls", "xlsx")
            office_type = "xlsx"
        elif office_type == "ppt":
            raw = _convert_legacy_office(raw, "ppt", "pptx")
            office_type = "pptx"
        if office_type == "docx":
            text, links = _extract_docx(raw, url)
            return ExtractionResult(
                status="complete",
                text=text,
                links=links,
                processor="python-docx",
            )
        if office_type == "xlsx":
            text, links = _extract_xlsx(raw, url)
            return ExtractionResult(
                status="complete", text=text, links=links, processor="openpyxl"
            )
        if office_type == "pptx":
            text, links = _extract_pptx(raw, url)
            return ExtractionResult(
                status="complete",
                text=text,
                links=links,
                processor="python-pptx",
            )
        if mime.startswith("image/") or suffix in _IMAGE_SUFFIXES:
            return ExtractionResult(
                status="complete",
                text=_number_lines(_ocr_image(raw, ocr_languages)),
                processor="tesseract",
            )
        if (
            mime.startswith(("audio/", "video/"))
            or suffix in _AUDIO_SUFFIXES | _VIDEO_SUFFIXES
        ):
            segments = _transcribe_media(raw, suffix, whisper_model)
            text = "\n".join(
                f"[{_timestamp(start)} --> {_timestamp(end)}] {segment}"
                for start, end, segment in segments
            )
            return ExtractionResult(
                status="complete", text=text, processor="faster-whisper"
            )
        text = decode_body(raw, mime_type).replace("\r\n", "\n").strip()
        return ExtractionResult(
            status="complete",
            text=text,
            links=_text_links(text, url),
            processor="text",
        )
    except (
        ImportError,
        FileNotFoundError,
        subprocess.SubprocessError,
    ) as error:
        return ExtractionResult(status="unavailable", error=str(error))
    except Exception as error:
        return ExtractionResult(status="failed", error=str(error))
