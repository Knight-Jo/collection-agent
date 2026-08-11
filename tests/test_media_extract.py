"""Crawl resource extraction tests."""

from __future__ import annotations

import pytest

from intel_agent.extract import extract_resource, is_rejected_resource


def test_extract_html_text_links_and_plain_text():
    html = b'<html><body>Hello <a href="/next">next</a></body></html>'
    result = extract_resource(html, "text/html", "https://example.com/root")
    assert result.status == "complete"
    assert "Hello" in result.text
    assert result.links == ["https://example.com/next"]

    plain = extract_resource(
        b"name,value\na,1\n", "text/csv", "https://example.com/a.csv"
    )
    assert plain.text == "name,value\na,1"


def test_ocr_text_has_line_numbers(monkeypatch):
    monkeypatch.setattr(
        "intel_agent.extract._ocr_image",
        lambda raw, languages: "first\nsecond",
    )
    result = extract_resource(
        b"image", "image/png", "https://example.com/image.png"
    )
    assert result.text == "1: first\n2: second"
    assert result.processor == "tesseract"


def test_transcript_has_timestamps(monkeypatch):
    monkeypatch.setattr(
        "intel_agent.extract._transcribe_media",
        lambda raw, suffix, model: [(0.0, 1.25, "hello")],
    )
    result = extract_resource(
        b"audio", "audio/mpeg", "https://example.com/clip.mp3"
    )
    assert result.text == "[00:00:00.000 --> 00:00:01.250] hello"
    assert result.processor == "faster-whisper"


def test_missing_optional_processor_marks_extraction_unavailable(monkeypatch):
    def unavailable(raw, languages):
        raise ModuleNotFoundError("pytesseract")

    monkeypatch.setattr("intel_agent.extract._ocr_image", unavailable)
    result = extract_resource(
        b"original", "image/jpeg", "https://example.com/photo.jpg"
    )
    assert result.status == "unavailable"
    assert "pytesseract" in (result.error or "")


def test_missing_tesseract_executable_marks_extraction_unavailable(
    monkeypatch,
):
    def unavailable(raw, languages):
        raise OSError("tesseract executable was not found")

    monkeypatch.setattr("intel_agent.extract._ocr_image", unavailable)
    result = extract_resource(
        b"original", "image/png", "https://example.com/photo.png"
    )
    assert result.status == "unavailable"
    assert "tesseract" in (result.error or "")


@pytest.mark.parametrize(
    ("mime_type", "url"),
    [
        ("image/svg+xml", "https://example.com/image.svg"),
        ("image/gif", "https://example.com/image.gif"),
        ("audio/aac", "https://example.com/audio.aac"),
        ("video/x-msvideo", "https://example.com/video.avi"),
    ],
)
def test_rejects_unlisted_media_formats(mime_type, url):
    result = extract_resource(b"original", mime_type, url)
    assert result.status == "skipped"


@pytest.mark.parametrize(
    ("mime_type", "url"),
    [
        ("application/zip", "https://example.com/a.zip"),
        ("application/javascript", "https://example.com/a.js"),
        ("application/x-msdownload", "https://example.com/a.exe"),
        ("text/plain", "https://example.com/image.svg"),
    ],
)
def test_rejects_archives_scripts_and_executables(mime_type, url):
    assert is_rejected_resource(mime_type, url)
