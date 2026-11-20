"""Recherche lexicale BM25 (rank_bm25) : termes exacts comme 'total revenue', 'FY2022'."""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from fri.ingestion.chunking import search_text
from fri.retrieval.filters import matches, normalize_filters
from fri.schemas import Chunk, SearchResult

# Mots ou nombres ; "32,765" et "3.5" restent un seul jeton.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")

# Mots vides anglais les plus fréquents : ils ne servent pas à classer les passages.
STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the this to
    was were will with what which who how did does do our we""".split()
)


def tokenize(text: str) -> list[str]:
    """Minuscules, mots et nombres, sans mots vides.

    ``"FY2022 Total Revenue"`` -> ``["fy2022", "total", "revenue"]``.
    """
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


class BM25Retriever:
    """Index BM25 en mémoire, reconstruit à partir des chunks (quelques secondes)."""

    def __init__(self, chunks: list[Chunk]) -> None:
        if not chunks:
            raise ValueError("BM25Retriever a besoin d'au moins un chunk.")
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(search_text(c)) or ["_"] for c in chunks])

    def search(self, query: str, k: int = 8, filters: dict | None = None) -> list[SearchResult]:
        """Les ``k`` chunks les mieux notés qui respectent les filtres (société, année)."""
        tokens = tokenize(query)
        if not tokens or k < 1:
            return []
        normalized = normalize_filters(filters)
        scores = self.bm25.get_scores(tokens)
        candidates = [
            (float(scores[i]), chunk)
            for i, chunk in enumerate(self.chunks)
            if scores[i] > 0 and matches(chunk.metadata, normalized)
        ]
        candidates.sort(key=lambda sc: sc[0], reverse=True)
        return [SearchResult(chunk=c, score=s, source="bm25") for s, c in candidates[:k]]
