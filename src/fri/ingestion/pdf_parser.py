"""Extraction du texte page par page (PyMuPDF ou pdfplumber)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Page:
    doc_name: str
    page: int  # 1-indexé
    text: str


def parse_pdf(path: Path) -> list[Page]:
    """Retourne une Page par page du PDF, en gardant le numéro pour les citations."""
    # TODO(Rôle 1) : fitz.open(path) puis page.get_text()
    raise NotImplementedError
