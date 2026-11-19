"""Serveur MCP (SDK Python `mcp`, FastMCP).

Usage :
    python -m fri.mcp_server.server          # vrai index (transport stdio)
    python -m fri.mcp_server.server --demo   # passages de démo, sans index
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
    """Renvoie la valeur d'une métrique financière (ex. total revenue) et sa source."""
    return tools.get_financial_metric(company, year, metric).model_dump(mode="json")


@mcp.tool()
def compare_years(company: str, metric: str, year_a: int, year_b: int) -> dict:
    """Compare une métrique entre deux années : écart et pourcentage d'évolution."""
    return tools.compare_years(company, metric, year_a, year_b).model_dump(mode="json")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if "--demo" in argv:
        from fri.mcp_server.demo import demo_retriever

        tools.set_retriever(demo_retriever())
    mcp.run()


if __name__ == "__main__":
    main()
