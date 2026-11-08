"""Serveur MCP (SDK Python `mcp`, FastMCP).

Usage : python -m fri.mcp_server.server   (transport stdio, pour Claude Desktop ou un client MCP)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from fri.mcp_server import tools

mcp = FastMCP("financial-report-intelligence")


@mcp.tool()
def search_filings(query: str, company: str | None = None, year: int | None = None) -> list[dict]:
    """Recherche des passages dans les rapports financiers, avec société, année et page."""
    return [r.model_dump() for r in tools.search_filings(query, company, year)]


@mcp.tool()
def get_financial_metric(company: str, year: int, metric: str) -> dict:
    """Renvoie la valeur d'une métrique financière (ex. total revenue) et sa source."""
    return tools.get_financial_metric(company, year, metric).model_dump()


@mcp.tool()
def compare_years(company: str, metric: str, year_a: int, year_b: int) -> dict:
    """Compare une métrique entre deux années : écart et pourcentage d'évolution."""
    return tools.compare_years(company, metric, year_a, year_b).model_dump()


if __name__ == "__main__":
    mcp.run()
