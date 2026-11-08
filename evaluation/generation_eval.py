"""Métriques de génération : exactitude, fidélité, citations correctes (LLM-as-judge)."""

from __future__ import annotations

from fri.schemas import Citation


def citation_precision(cited: list[Citation], evidence_pages: list[int]) -> float:
    """Part des citations qui pointent vers une page de preuve."""
    if not cited:
        return 0.0
    return sum(c.page in evidence_pages for c in cited) / len(cited)


def judge_correctness(question: str, expected: str, predicted: str) -> bool:
    # TODO(Rôle 3) : LLM-as-judge
    raise NotImplementedError


def run() -> None:
    # TODO(Rôle 3) : rejouer les questions sur l'agent et écrire results/generation.csv
    raise NotImplementedError


if __name__ == "__main__":
    run()
