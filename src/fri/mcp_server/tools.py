"""Logique des 3 outils MCP, indépendante du transport (testable sans serveur).

Le retriever est remplaçable : les tests et la démo utilisent un retriever en
mémoire (`set_retriever`). Sinon, `get_retriever()` charge le vrai `HybridRetriever`
(BM25 + ChromaDB) construit par `python -m fri.ingestion.indexer`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fri.ingestion.metadata import company_key
from fri.schemas import MetricValue, SearchResult, YearComparison


class Retriever(Protocol):
    """Ce que les outils attendent d'un retriever (c'est l'interface de HybridRetriever)."""

    def search(
        self, query: str, company: str | None = None, year: int | None = None, k: int = 8
    ) -> list[SearchResult]: ...


# extracteur(company, year, metric, results) -> MetricExtraction | None (voir fri.agent.metrics)
MetricExtractor = Callable[[str, int, str, list[SearchResult]], Any]


class MetricNotFoundError(LookupError):
    """La valeur demandée n'a pas été trouvée dans les passages."""


_retriever: Retriever | None = None
_extractor: MetricExtractor | None = None


def set_metric_extractor(extractor: MetricExtractor | None) -> None:
    """Choisit l'extracteur de valeurs (None = le LLM du .env)."""
    global _extractor
    _extractor = extractor


def get_metric_extractor() -> MetricExtractor:
    global _extractor
    if _extractor is None:
        from fri.agent.metrics import LLMMetricExtractor

        _extractor = LLMMetricExtractor()
    return _extractor


def set_retriever(retriever: Retriever | None) -> None:
    """Choisit le retriever utilisé par les outils (None = revenir au vrai index)."""
    global _retriever
    _retriever = retriever


def get_retriever() -> Retriever:
    """Renvoie le retriever courant ; charge le vrai index au premier appel."""
    global _retriever
    if _retriever is None:
        _retriever = _load_index_retriever()
    return _retriever


def _load_index_retriever() -> Retriever:
    """Charge le HybridRetriever construit par `python -m fri.ingestion.indexer`."""
    from fri.config import settings
    from fri.ingestion.indexer import MANIFEST
    from fri.retrieval.hybrid import HybridRetriever

    if not (settings.index_dir / MANIFEST).is_file():
        raise RuntimeError(
            f"Index introuvable dans {settings.index_dir}. Lance d'abord "
            "`python -m fri.ingestion.indexer`, ou utilise la démo : "
            "`python -m fri.mcp_server.server --demo`."
        )
    return HybridRetriever.load(settings.index_dir)


def _same_company(a: str, b: str) -> bool:
    """'American Express' et 'AMERICANEXPRESS' désignent la même société."""
    return company_key(a) == company_key(b)


def search_filings(
    query: str, company: str | None = None, year: int | None = None, k: int = 5
) -> list[SearchResult]:
    """Renvoie les passages pertinents avec leur page, filtrés par société et année."""
    query = query.strip()
    if not query:
        raise ValueError("La question (query) est vide.")
    if k < 1:
        raise ValueError(f"k doit être >= 1, reçu {k}")
    company = company.strip() if company and company.strip() else None

    results = get_retriever().search(query, company=company, year=year, k=k)

    # Garde-fou : on ne renvoie jamais un passage d'une autre société ou d'une autre
    # année que celles demandées, même si le retriever filtre mal.
    kept = [
        r
        for r in results
        if (company is None or _same_company(r.chunk.metadata.company, company))
        and (year is None or r.chunk.metadata.year == year)
    ]
    return kept[:k]


def get_financial_metric(
    company: str,
    year: int,
    metric: str,
    k: int = 5,
    extractor: MetricExtractor | None = None,
) -> MetricValue:
    """Renvoie une valeur chiffrée avec sa source.

    Cherche les passages de la société et de l'année, puis l'extracteur (le LLM par
    défaut) lit la valeur. La citation pointe le passage d'où vient la valeur.
    Lève MetricNotFoundError si la valeur n'est pas trouvée.
    """
    from fri.agent.citations import citation_from_result

    metric = metric.strip()
    if not metric:
        raise ValueError("La métrique (metric) est vide.")
    if not company or not company.strip():
        raise ValueError("La société (company) est obligatoire.")

    results = search_filings(metric, company=company, year=year, k=k)
    if not results:
        raise MetricNotFoundError(f"Aucun passage pour {company} {year} sur « {metric} ».")

    found = (extractor or get_metric_extractor())(company, year, metric, results)
    if found is None:
        raise MetricNotFoundError(f"« {metric} » introuvable pour {company} {year}.")

    source = results[found.passage - 1]
    return MetricValue(
        company=source.chunk.metadata.company,
        year=year,
        metric=metric,
        value=found.value,
        unit=found.unit,
        citation=citation_from_result(source),
    )


def compute_comparison(a: MetricValue, b: MetricValue) -> YearComparison:
    """Calcule l'écart et le pourcentage d'évolution entre deux valeurs."""
    delta = b.value - a.value
    pct = None if a.value == 0 else delta / abs(a.value) * 100
    return YearComparison(
        company=a.company, metric=a.metric, year_a=a, year_b=b, delta=delta, pct_change=pct
    )


def compare_years(
    company: str,
    metric: str,
    year_a: int,
    year_b: int,
    extractor: MetricExtractor | None = None,
) -> YearComparison:
    """Compare une métrique d'une société entre deux années (year_a = année de référence)."""
    if year_a == year_b:
        raise ValueError("Les deux années à comparer doivent être différentes.")
    a = get_financial_metric(company, year_a, metric, extractor=extractor)
    b = get_financial_metric(company, year_b, metric, extractor=extractor)
    if a.unit.casefold() != b.unit.casefold():
        raise ValueError(f"Unités différentes : {a.unit} ({year_a}) et {b.unit} ({year_b}).")
    return compute_comparison(a, b)
