"""Recherche vectorielle (ChromaDB + sentence-transformers)."""

from __future__ import annotations

from fri.schemas import SearchResult


class VectorRetriever:
    def __init__(self, index_dir: str, embedding_model: str) -> None:
        self.index_dir = index_dir
        self.embedding_model = embedding_model
        # TODO(Rôle 1) : charger la collection Chroma

    def search(self, query: str, k: int = 8, filters: dict | None = None) -> list[SearchResult]:
        # TODO(Rôle 1) : filtrer par société / année avec `where`
        raise NotImplementedError
