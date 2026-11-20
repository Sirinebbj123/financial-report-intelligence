"""Serveur MCP (SDK Python `mcp`, FastMCP).

Usage :
    python -m fri.mcp_server.server          # vrai index (data/index, transport stdio)
    python -m fri.mcp_server.server --demo   # passages de démo, sans index ni clé API
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from fri.mcp_server import tools

mcp = FastMCP("financial-report-intelligence")


@mcp.tool()
def search_filings(
    query: str, company: str | None = None, year: int | None = None, k: int = 5
) -> list[dict]:
    """Recherche des passages dans les rapports financiers (10-K, 10-Q).

    Chaque passage renvoyé porte sa société, son année et sa page, à citer sous la
    forme [Société, Année, p. X]. Filtrer par `company` (ex. "3M") et `year`
    (ex. 2018) quand la question les précise.
    """
    return [r.model_dump(mode="json") for r in tools.search_filings(query, company, year, k)]


@mcp.tool()
def get_financial_metric(company: str, year: int, metric: str) -> dict:
    """Renvoie la valeur d'une métrique financière (ex. "total revenue") et sa source.

    La valeur est en millions de dollars ; `citation` donne la page à citer.
    """
    return tools.get_financial_metric(company, year, metric).model_dump(mode="json")


@mcp.tool()
def compare_years(company: str, metric: str, year_a: int, year_b: int) -> dict:
    """Compare une métrique entre deux années : écart et pourcentage d'évolution.

    `year_a` est l'année de référence : delta = valeur(year_b) - valeur(year_a).
    """
    return tools.compare_years(company, metric, year_a, year_b).model_dump(mode="json")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if "--demo" in argv:
        from fri.agent.metrics import RegexMetricExtractor
        from fri.mcp_server.demo import demo_retriever

        tools.set_retriever(demo_retriever())
        tools.set_metric_extractor(RegexMetricExtractor())  # pas de LLM en démo
    else:
        preload_index()
    mcp.run()


def preload_index() -> bool:
    """Charge l'index et le modèle au démarrage : le premier appel d'outil est rapide et
    une erreur (index absent) apparaît tout de suite dans les logs.

    Le serveur démarre quand même si l'index manque : chaque outil renverra alors le
    message qui explique quoi faire. Tout part sur stderr : stdout sert au protocole MCP.
    """
    try:
        retriever = tools.get_retriever()
        retriever.search("total revenue", k=1)  # charge aussi le modèle d'embeddings
    except Exception as err:  # index absent, modèle introuvable...
        print(f"[fri] Index non chargé : {err}", file=sys.stderr)
        return False
    n = len(getattr(retriever, "vector", ()) or ())
    print(f"[fri] Index chargé ({n} chunks).", file=sys.stderr)
    return True


if __name__ == "__main__":
    main()
