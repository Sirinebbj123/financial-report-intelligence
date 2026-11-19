"""Tests de get_financial_metric et compare_years (retriever de démo, faux LLM)."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402

from fri.agent.metrics import (  # noqa: E402
    LLMMetricExtractor,
    RegexMetricExtractor,
    parse_json_reply,
    to_number,
)
from fri.mcp_server import tools  # noqa: E402
from fri.mcp_server.demo import demo_retriever  # noqa: E402


@pytest.fixture(autouse=True)
def demo_index():
    tools.set_retriever(demo_retriever())
    tools.set_metric_extractor(RegexMetricExtractor())
    yield
    tools.set_retriever(None)
    tools.set_metric_extractor(None)


def llm_extractor(*replies: str) -> LLMMetricExtractor:
    return LLMMetricExtractor(FakeListChatModel(responses=list(replies)))


# --- lecture des réponses du LLM -------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (32765, 32765.0),
        ("32,765", 32765.0),
        ("$1,577.5", 1577.5),
        ("(1,200)", -1200.0),
        (None, None),
        ("n/a", None),
        (True, None),
    ],
)
def test_to_number(raw, expected):
    assert to_number(raw) == expected


def test_parse_json_reply_tolerates_code_fences():
    text = 'Voici :\n```json\n{"value": 32765, "unit": "USD millions", "passage": 1}\n```'
    assert parse_json_reply(text) == {"value": 32765, "unit": "USD millions", "passage": 1}


def test_parse_json_reply_returns_none_on_garbage():
    assert parse_json_reply("pas de JSON ici") is None
    assert parse_json_reply("{cassé") is None


# --- get_financial_metric ----------------------------------------------------------


def test_get_financial_metric_with_llm():
    ext = llm_extractor('{"value": "32,765", "unit": "USD millions", "passage": 1}')
    m = tools.get_financial_metric("3M", 2018, "total revenue", extractor=ext)
    assert (m.company, m.year, m.value, m.unit) == ("3M", 2018, 32765.0, "USD millions")
    assert (m.citation.page, m.citation.doc_name) == (42, "3M_2018_10K")


def test_citation_follows_the_passage_chosen_by_the_llm():
    results = tools.search_filings("revenue million", company="3M", year=2018)
    assert len(results) >= 2
    ext = llm_extractor('{"value": 1577, "unit": "USD millions", "passage": 2}')
    m = tools.get_financial_metric("3M", 2018, "revenue million", extractor=ext)
    assert m.citation.page == results[1].chunk.metadata.page


@pytest.mark.parametrize(
    "reply",
    [
        '{"value": null, "unit": "USD millions", "passage": 1}',
        '{"value": 10, "passage": 99}',
        "je ne sais pas",
    ],
)
def test_llm_without_usable_value_raises_not_found(reply):
    with pytest.raises(tools.MetricNotFoundError):
        tools.get_financial_metric("3M", 2018, "total revenue", extractor=llm_extractor(reply))


def test_no_passage_raises_not_found():
    with pytest.raises(tools.MetricNotFoundError):
        tools.get_financial_metric("Apple", 2018, "total revenue")


@pytest.mark.parametrize("company, metric", [("3M", " "), ("", "total revenue")])
def test_get_financial_metric_rejects_bad_input(company, metric):
    with pytest.raises(ValueError):
        tools.get_financial_metric(company, 2018, metric)


def test_regex_extractor_converts_billions():
    from fri.mcp_server.demo import InMemoryRetriever, _chunk

    tools.set_retriever(InMemoryRetriever([_chunk("X_2020_10K", 3, "Revenue was $1.5 billion.")]))
    assert tools.get_financial_metric("X", 2020, "revenue").value == 1500.0


# --- compare_years -------------------------------------------------------------------


def test_compare_years_demo():
    comp = tools.compare_years("3M", "total revenue", 2017, 2018)
    assert (comp.year_a.value, comp.year_b.value) == (31657.0, 32765.0)
    assert comp.delta == 1108.0
    assert round(comp.pct_change, 2) == 3.5
    assert (comp.year_a.citation.page, comp.year_b.citation.page) == (40, 42)


def test_compare_years_rejects_same_year():
    with pytest.raises(ValueError):
        tools.compare_years("3M", "total revenue", 2018, 2018)


def test_compare_years_rejects_different_units():
    ext = llm_extractor(
        '{"value": 31657, "unit": "USD millions", "passage": 1}',
        '{"value": 32.8, "unit": "USD billions", "passage": 1}',
    )
    with pytest.raises(ValueError, match="Unités"):
        tools.compare_years("3M", "total revenue", 2017, 2018, extractor=ext)


def test_mcp_server_tools_in_demo_mode():
    pytest.importorskip("mcp")
    from fri.mcp_server import server

    metric = server.get_financial_metric("3M", 2018, "total revenue")
    assert metric["value"] == 32765.0 and metric["citation"]["page"] == 42
    comp = server.compare_years("3M", "total revenue", 2017, 2018)
    assert comp["delta"] == 1108.0
