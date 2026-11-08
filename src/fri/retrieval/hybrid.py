"""Point d'entrée du retrieval : BM25 + vecteurs, filtres métadonnées, fusion RRF."""

from __future__ import annotations

from fri.retrieval.fusion import reciprocal_rank_fusion
from fri.schemas import SearchResult


class HybridRetriever:
    def __init__(self, bm25, vector) -> None:
        self.bm25 = bm25
        self.vector = vector

    def search(
        self, query: str, company: str | None = None, year: int | None = None, k: int = 8
    ) -> list[SearchResult]:
        filters = {key: v for key, v in {"company": company, "year": year}.items() if v}
        rankings = [
            self.bm25.search(query, k=k * 2, filters=filters),
            self.vector.search(query, k=k * 2, filters=filters),
        ]
        return reciprocal_rank_fusion(rankings, top_n=k)
