"""Contrats partagés entre les briques.

Chacun code contre ces modèles avec des données factices dès la semaine 1,
puis on branche les vraies briques. Toute modification passe par une PR relue
par au moins deux rôles.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DocType(StrEnum):
    TEN_K = "10-K"
    TEN_Q = "10-Q"
    EIGHT_K = "8-K"
    EARNINGS = "earnings"
    OTHER = "other"


class ChunkMetadata(BaseModel):
    company: str
    year: int
    doc_type: DocType
    doc_name: str = Field(description="Nom du PDF FinanceBench, ex. 3M_2018_10K")
    page: int = Field(ge=1, description="Numéro de page (1-indexé) pour la citation")


class Chunk(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata


class SearchResult(BaseModel):
    chunk: Chunk
    score: float
    source: str = Field(default="hybrid", description="bm25 | vector | hybrid | rerank")


class Citation(BaseModel):
    company: str
    year: int
    page: int
    doc_name: str | None = None

    def __str__(self) -> str:
        return f"[{self.company}, {self.year}, p. {self.page}]"


class MetricValue(BaseModel):
    company: str
    year: int
    metric: str
    value: float
    unit: str = "USD millions"
    citation: Citation


class YearComparison(BaseModel):
    company: str
    metric: str
    year_a: MetricValue
    year_b: MetricValue
    delta: float
    pct_change: float | None = Field(description="None si la valeur de year_a vaut 0")


class Answer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    route: str | None = Field(default=None, description="simple | calcul | comparaison")
