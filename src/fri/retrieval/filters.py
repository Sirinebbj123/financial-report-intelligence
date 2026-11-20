"""Filtres de métadonnées communs à BM25 et à la recherche vectorielle."""

from __future__ import annotations

from typing import Any

from fri.ingestion.metadata import company_key
from fri.schemas import ChunkMetadata


def normalize_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Garde seulement ``company`` et ``year`` renseignés ; normalise la société.

    ``{"company": "American Express", "year": 2022}``
    -> ``{"company_key": "americanexpress", "year": 2022}``.
    """
    filters = filters or {}
    unknown = set(filters) - {"company", "year"}
    if unknown:
        raise ValueError(f"Filtres inconnus : {sorted(unknown)} (company, year)")
    out: dict[str, Any] = {}
    company = filters.get("company")
    if company and company.strip():
        out["company_key"] = company_key(company)
    if filters.get("year") is not None:
        out["year"] = int(filters["year"])
    return out


def matches(metadata: ChunkMetadata, normalized: dict[str, Any]) -> bool:
    """Vrai si le chunk respecte les filtres déjà normalisés."""
    if "company_key" in normalized and company_key(metadata.company) != normalized["company_key"]:
        return False
    return "year" not in normalized or metadata.year == normalized["year"]
