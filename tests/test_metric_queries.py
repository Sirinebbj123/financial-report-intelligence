"""Recherche d'une métrique : synonymes (« net sales » pour « total revenue ») et fusion."""

from fri.mcp_server import tools
from fri.schemas import Chunk, ChunkMetadata, DocType, SearchResult


def test_metric_queries_add_synonyms_first():
    queries = tools.metric_queries("total revenue")
    assert queries[0].startswith("total revenue ")
    assert "net sales" in queries[0] and "statement of income" in queries[0]
    assert queries[1] == "total revenue"


def test_metric_queries_capex_and_unknown():
    assert "purchases of property plant and equipment" in tools.metric_queries("Capex")[0]
    assert tools.metric_queries("goodwill impairment") == ["goodwill impairment"]


def _result(page: int) -> SearchResult:
    meta = ChunkMetadata(
        company="3M", year=2022, doc_type=DocType.TEN_K, doc_name="3M_2022_10K", page=page
    )
    return SearchResult(chunk=Chunk(id=f"p{page}", text="x", metadata=meta), score=1.0)


class _Retriever:
    """Renvoie des pages différentes selon la requête, pour vérifier la fusion."""

    def __init__(self):
        self.queries = []

    def search(self, query, company=None, year=None, k=8):
        self.queries.append(query)
        pages = [48, 59] if "statement of income" in query else [59, 60, 55]
        return [_result(p) for p in pages]


def test_metric_search_merges_without_duplicates():
    retriever = _Retriever()
    tools.set_retriever(retriever)
    try:
        found = tools._search_metric("total revenue", "3M", 2022, k=8)
    finally:
        tools.set_retriever(None)
    assert [r.chunk.metadata.page for r in found] == [48, 59, 60, 55]
    assert len(retriever.queries) == 2


def test_get_financial_metric_reads_the_income_statement_page():
    retriever = _Retriever()
    seen = {}

    def extractor(company, year, metric, results):
        seen["pages"] = [r.chunk.metadata.page for r in results]
        return type("Found", (), {"value": 34229.0, "unit": "USD millions", "passage": 1})()

    tools.set_retriever(retriever)
    try:
        value = tools.get_financial_metric("3M", 2022, "total revenue", extractor=extractor)
    finally:
        tools.set_retriever(None)
    assert seen["pages"][0] == 48
    assert value.citation.page == 48 and value.value == 34229
