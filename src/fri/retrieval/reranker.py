"""Reranker cross-encoder (phase Optimisation)."""

from __future__ import annotations

from fri.schemas import SearchResult


def rerank(query: str, results: list[SearchResult], top_n: int = 5) -> list[SearchResult]:
    # TODO(Rôle 1) : CrossEncoder("BAAI/bge-reranker-base")
    raise NotImplementedError
