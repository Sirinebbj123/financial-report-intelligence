"""Découpage des pages en chunks qui gardent leurs métadonnées."""

from __future__ import annotations

from fri.ingestion.pdf_parser import Page
from fri.schemas import Chunk


def chunk_page(page: Page, chunk_size: int = 800, overlap: int = 100) -> list[Chunk]:
    """Découpe une page en chunks ; chaque chunk garde la page d'origine."""
    # TODO(Rôle 1) : découpage (RecursiveCharacterTextSplitter de LangChain par ex.)
    raise NotImplementedError
