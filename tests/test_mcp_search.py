"""Tests de search_filings et du serveur MCP, avec le retriever de démo (sans index)."""

import pytest

from fri.mcp_server import tools
from fri.mcp_server.demo import DEMO_CHUNKS, InMemoryRetriever, demo_retriever
from fri.schemas import SearchResult


@pytest.fixture(autouse=True)
def demo_index():
    tools.set_retriever(demo_retriever())
    yield
    tools.set_retriever(None)


def test_search_filings_returns_pages():
    results = tools.search_filings("total revenue 3M 2018")
    assert results
    top = results[0].chunk.metadata
    assert (top.company, top.year, top.page) == ("3M", 2018, 42)


def test_search_filings_filters_company_and_year():
    results = tools.search_filings("total revenue", company="3M", year=2017)
    assert results
    assert all(r.chunk.metadata.company == "3M" for r in results)
    assert all(r.chunk.metadata.year == 2017 for r in results)


def test_search_filings_company_is_case_insensitive():
    results = tools.search_filings("net revenue", company="amd")
    assert [r.chunk.metadata.doc_name for r in results] == ["AMD_2022_10K"]


def test_search_filings_respects_k():
    assert len(tools.search_filings("revenue million", k=1)) == 1


def test_search_filings_drops_results_outside_filters():
    """Même si le retriever filtre mal, aucun passage d'une autre société ne sort."""

    class LeakyRetriever(InMemoryRetriever):
        def search(self, query, company=None, year=None, k=8):
            return super().search(query, k=k)  # ignore les filtres

    tools.set_retriever(LeakyRetriever(DEMO_CHUNKS))
    results = tools.search_filings("revenue", company="AMD", year=2022)
    assert results
    assert {r.chunk.metadata.company for r in results} == {"AMD"}


def test_search_filings_unknown_company_returns_nothing():
    assert tools.search_filings("revenue", company="Apple") == []


@pytest.mark.parametrize("query, k", [("", 5), ("   ", 5), ("revenue", 0)])
def test_search_filings_rejects_bad_input(query, k):
    with pytest.raises(ValueError):
        tools.search_filings(query, k=k)


def test_search_filings_without_index_explains_what_to_do(tmp_path, monkeypatch):
    from fri import config

    tools.set_retriever(None)
    monkeypatch.setattr(config, "settings", config.Settings(index_dir=tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="indexer"):
        tools.search_filings("revenue")


def test_mcp_tool_returns_json_ready_dicts():
    pytest.importorskip("mcp")
    from fri.mcp_server import server

    rows = server.search_filings("total revenue", company="3M", year=2018, k=2)
    assert rows and isinstance(rows[0], dict)
    SearchResult.model_validate(rows[0])
    assert rows[0]["chunk"]["metadata"]["doc_type"] == "10-K"
