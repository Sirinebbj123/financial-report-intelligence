"""Construit l'index vectoriel (ChromaDB) et l'index BM25 à partir des PDF.

Usage : python -m fri.ingestion.indexer
"""

from __future__ import annotations

from fri.config import settings


def build_index() -> None:
    # TODO(Rôle 1) : parse_pdf -> chunk_page -> embeddings -> Chroma + BM25 (pickle)
    raise NotImplementedError


if __name__ == "__main__":
    print(f"Indexation des PDF de {settings.data_dir / 'pdfs'} vers {settings.index_dir}")
    build_index()
