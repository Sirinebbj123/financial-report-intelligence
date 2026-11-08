"""Fusion des classements par Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from fri.schemas import SearchResult


def reciprocal_rank_fusion(
    rankings: list[list[SearchResult]], k: int = 60, top_n: int | None = None
) -> list[SearchResult]:
    """Fusionne plusieurs classements : score(d) = somme 1 / (k + rang(d))."""
    scores: dict[str, float] = {}
    by_id: dict[str, SearchResult] = {}
    for ranking in rankings:
        for rank, result in enumerate(ranking, start=1):
            cid = result.chunk.id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            by_id.setdefault(cid, result)

    fused = [
        SearchResult(chunk=by_id[cid].chunk, score=score, source="hybrid")
        for cid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return fused[:top_n] if top_n else fused
