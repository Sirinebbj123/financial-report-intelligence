"""Métriques de retrieval : Recall@k, MRR, page hit rate."""

from __future__ import annotations


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(runs: list[tuple[list[str], set[str]]]) -> float:
    if not runs:
        return 0.0
    return sum(reciprocal_rank(r, rel) for r, rel in runs) / len(runs)


def page_hit(retrieved_pages: list[int], evidence_pages: list[int], k: int) -> bool:
    """Vrai si une des k premières pages retrouvées est une page de preuve."""
    return bool(set(retrieved_pages[:k]) & set(evidence_pages))


def run(k: int = 5) -> None:
    # TODO(Rôle 3) : rejouer les questions sur HybridRetriever et écrire results/retrieval.csv
    raise NotImplementedError


if __name__ == "__main__":
    run()
