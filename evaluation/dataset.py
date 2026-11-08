"""Chargement du jeu de test FinanceBench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvalItem:
    question: str
    answer: str
    company: str
    doc_name: str
    evidence_pages: list[int]


def load_financebench(path: Path) -> list[EvalItem]:
    # TODO(Rôle 3) : lire le JSONL, champs question / answer / evidence
    raise NotImplementedError
