"""Extraction backends."""

from .html import BeautifulSoupBackend, TrafilaturaBackend
from .ocr import TesseractBackend
from .office import OfficeBackend
from .pdf import PdfplumberBackend, PyMuPDFBackend

__all__ = [
    "BeautifulSoupBackend",
    "OfficeBackend",
    "PdfplumberBackend",
    "PyMuPDFBackend",
    "TesseractBackend",
    "TrafilaturaBackend",
]
