"""Recherche lexicale BM25 (rank_bm25) : termes exacts comme 'total revenue', 'FY2022'."""

from __future__ import annotations

from fri.schemas import Chunk, SearchResult


class BM25Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        # TODO(Rôle 1) : self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks])

    def search(self, query: str, k: int = 8, filters: dict | None = None) -> list[SearchResult]:
        # TODO(Rôle 1)
        raise NotImplementedError
