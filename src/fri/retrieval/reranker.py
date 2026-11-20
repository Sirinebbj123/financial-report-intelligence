"""Reranker cross-encoder (phase Optimisation).

Le cross-encoder lit la question et le passage ensemble : plus précis que les
embeddings, mais plus lent. On ne l'applique donc qu'aux meilleurs candidats de la
recherche hybride. Désactivé par défaut (``USE_RERANKER=1`` pour l'activer).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from fri.schemas import SearchResult

DEFAULT_RERANKER = "BAAI/bge-reranker-base"


class PairScorer(Protocol):
    """Interface de ``sentence_transformers.CrossEncoder`` utilisée ici."""

    def predict(self, pairs: list[tuple[str, str]]) -> Any: ...


@lru_cache(maxsize=2)
def load_cross_encoder(model_name: str = DEFAULT_RERANKER) -> PairScorer:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def rerank(
    query: str,
    results: list[SearchResult],
    top_n: int = 5,
    model: PairScorer | None = None,
) -> list[SearchResult]:
    """Renote les passages avec le cross-encoder et garde les ``top_n`` meilleurs."""
    if not results or top_n < 1:
        return []
    scorer = model or load_cross_encoder()
    scores = scorer.predict([(query, r.chunk.text) for r in results])
    rescored = [
        SearchResult(chunk=r.chunk, score=float(s), source="rerank")
        for r, s in zip(results, scores, strict=True)
    ]
    rescored.sort(key=lambda r: r.score, reverse=True)
    return rescored[:top_n]


class Reranker:
    """Reranker prêt à brancher dans :class:`fri.retrieval.hybrid.HybridRetriever`."""

    def __init__(self, model_name: str = DEFAULT_RERANKER, model: PairScorer | None = None):
        self.model_name = model_name
        self._model = model

    def __call__(self, query: str, results: list[SearchResult], top_n: int) -> list[SearchResult]:
        if self._model is None:
            self._model = load_cross_encoder(self.model_name)
        return rerank(query, results, top_n=top_n, model=self._model)
