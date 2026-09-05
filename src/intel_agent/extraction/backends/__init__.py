"""Extraction backends."""

from .asr import WhisperBackend
from .html import BeautifulSoupBackend, TrafilaturaBackend
from .media import FFmpegBackend
from .ocr import TesseractBackend
from .office import OfficeBackend
from .pdf import PdfplumberBackend, PyMuPDFBackend

__all__ = [
    "BeautifulSoupBackend",
    "FFmpegBackend",
    "OfficeBackend",
    "PdfplumberBackend",
    "PyMuPDFBackend",
    "TesseractBackend",
    "TrafilaturaBackend",
    "WhisperBackend",
]
