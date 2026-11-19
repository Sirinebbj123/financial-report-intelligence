"""Logique des 3 outils MCP, indépendante du transport (testable sans serveur).

Le retriever est remplaçable : tant que l'index n'existe pas, les tests et la démo
utilisent un retriever en mémoire (`set_retriever`). Le jour où l'index est prêt,
`get_retriever()` charge le vrai `HybridRetriever` sans autre changement.
"""

from __future__ import annotations

from typing import Protocol

from fri.schemas import MetricValue, SearchResult, YearComparison


class Retriever(Protocol):
    """Ce que les outils attendent d'un retriever (c'est l'interface de HybridRetriever)."""

    def search(
        self, query: str, company: str | None = None, year: int | None = None, k: int = 8
    ) -> list[SearchResult]: ...


_retriever: Retriever | None = None


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

    if not settings.index_dir.exists():
        raise RuntimeError(
            f"Index introuvable dans {settings.index_dir}. Lance d'abord "
            "`python -m fri.ingestion.indexer`, ou utilise la démo : "
            "`python -m fri.mcp_server.server --demo`."
        )
    # TODO(Rôle 1 + 2) : charger BM25Retriever et VectorRetriever depuis l'index
    # une fois indexer.py terminé, puis renvoyer HybridRetriever(bm25, vector).
    raise NotImplementedError("Chargement de l'index : en attente de fri.ingestion.indexer")


def _same_company(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


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


def get_financial_metric(company: str, year: int, metric: str) -> MetricValue:
    """Renvoie une valeur chiffrée avec sa source."""
    # TODO(Rôle 2, tâche 4) : search_filings + extraction de la valeur par le LLM
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
