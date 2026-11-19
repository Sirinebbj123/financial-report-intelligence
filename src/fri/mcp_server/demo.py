"""Retriever en mémoire pour la démo et les tests, en attendant le vrai index.

Il classe les passages par nombre de mots communs avec la question. Ce n'est pas
un vrai moteur de recherche : il sert seulement à faire tourner les outils MCP
et l'agent de bout en bout avant que l'index vectoriel + BM25 soit prêt.
"""

from __future__ import annotations

import re

from fri.schemas import Chunk, ChunkMetadata, DocType, SearchResult

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


class InMemoryRetriever:
    """Même interface que HybridRetriever : search(query, company, year, k)."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks

    def search(
        self, query: str, company: str | None = None, year: int | None = None, k: int = 8
    ) -> list[SearchResult]:
        q = _tokens(query)
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            meta = chunk.metadata
            if company and meta.company.casefold() != company.casefold():
                continue
            if year and meta.year != year:
                continue
            overlap = len(q & _tokens(chunk.text))
            if overlap:
                scored.append((overlap / len(q), chunk))
        scored.sort(key=lambda sc: sc[0], reverse=True)
        return [SearchResult(chunk=c, score=s, source="demo") for s, c in scored[:k]]


def _chunk(doc_name: str, page: int, text: str) -> Chunk:
    company, year, _ = doc_name.split("_")
    meta = ChunkMetadata(
        company=company, year=int(year), doc_type=DocType.TEN_K, doc_name=doc_name, page=page
    )
    return Chunk(id=f"{doc_name}-p{page}-c0", text=text, metadata=meta)


# Passages de démonstration (chiffres arrondis, à remplacer par le vrai index).
DEMO_CHUNKS: list[Chunk] = [
    _chunk(
        "3M_2018_10K",
        42,
        "Net sales: total revenue for 3M in 2018 was $32,765 million, "
        "an increase of 3.5 percent compared to 2017.",
    ),
    _chunk(
        "3M_2018_10K",
        58,
        "Capital expenditures (purchases of property, plant and equipment) "
        "were $1,577 million in 2018.",
    ),
    _chunk(
        "3M_2017_10K",
        40,
        "Net sales: total revenue for 3M in 2017 was $31,657 million.",
    ),
    _chunk(
        "AMD_2022_10K",
        51,
        "Net revenue for AMD in 2022 was $23,601 million, up 44% from 2021, "
        "primarily driven by the Xilinx acquisition.",
    ),
]


def demo_retriever() -> InMemoryRetriever:
    return InMemoryRetriever(DEMO_CHUNKS)
