"""Logique des 3 outils MCP, indépendante du transport (testable sans serveur)."""

from __future__ import annotations

from fri.schemas import MetricValue, SearchResult, YearComparison


def search_filings(
    query: str, company: str | None = None, year: int | None = None, k: int = 5
) -> list[SearchResult]:
    """Renvoie les passages pertinents avec leur page."""
    # TODO(Rôle 2) : déléguer à fri.retrieval.hybrid.HybridRetriever
    raise NotImplementedError


def get_financial_metric(company: str, year: int, metric: str) -> MetricValue:
    """Renvoie une valeur chiffrée avec sa source."""
    # TODO(Rôle 2) : search_filings + extraction de la valeur par le LLM
    raise NotImplementedError


def compute_comparison(a: MetricValue, b: MetricValue) -> YearComparison:
    """Calcule l'écart et le pourcentage d'évolution entre deux valeurs."""
    delta = b.value - a.value
    pct = None if a.value == 0 else delta / abs(a.value) * 100
    return YearComparison(
        company=a.company, metric=a.metric, year_a=a, year_b=b, delta=delta, pct_change=pct
    )


def compare_years(company: str, metric: str, year_a: int, year_b: int) -> YearComparison:
    """Compare une métrique d'une société entre deux années."""
    a = get_financial_metric(company, year_a, metric)
    b = get_financial_metric(company, year_b, metric)
    return compute_comparison(a, b)
