"""Tests du routage simple / calcul / comparaison de l'agent (faux LLM, sans index)."""

import pytest

pytest.importorskip("langgraph")

from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402

from fri.agent.graph import ask, classify_question, find_years, format_comparison  # noqa: E402
from fri.mcp_server import tools  # noqa: E402
from fri.mcp_server.demo import demo_retriever  # noqa: E402


@pytest.fixture(autouse=True)
def demo_index():
    tools.set_retriever(demo_retriever())
    yield
    tools.set_retriever(None)
    tools.set_metric_extractor(None)


def fake_llm(*replies: str) -> FakeListChatModel:
    return FakeListChatModel(responses=list(replies))


@pytest.mark.parametrize(
    "question, route",
    [
        ("What was 3M's total revenue in 2018?", "simple"),
        ("Quel est le chiffre d'affaires de 3M en 2018 ?", "simple"),
        ("What was 3M's operating margin in 2018?", "calcul"),
        ("Quel est le ratio dette / capitaux propres de AMD en 2022 ?", "calcul"),
        ("Compare 3M total revenue between 2017 and 2018", "comparaison"),
        ("Évolution du CA de 3M de 2017 à 2018 ?", "comparaison"),
        ("3M revenue 2017 vs 2018", "comparaison"),
    ],
)
def test_classify_question(question, route):
    assert classify_question(question) == route


def test_find_years_keeps_order_and_drops_duplicates():
    assert find_years("2018 vs 2017, puis 2018") == [2018, 2017]
    assert find_years("FY2022 en 12345") == []  # pas d'année isolée


def test_comparison_route_uses_compare_years():
    llm = fake_llm(
        '{"company": "3M", "metric": "total revenue"}',
        '{"value": 31657, "unit": "USD millions", "passage": 1}',
        '{"value": 32765, "unit": "USD millions", "passage": 1}',
    )
    answer = ask("Compare 3M total revenue between 2018 and 2017", llm=llm)
    assert answer.route == "comparaison"
    assert [(c.year, c.page) for c in answer.citations] == [(2017, 40), (2018, 42)]
    assert "31 657" in answer.answer and "32 765" in answer.answer
    assert "+1 108" in answer.answer and "+3,5 %" in answer.answer


def test_comparison_falls_back_to_rag_when_value_missing():
    llm = fake_llm(
        '{"company": "3M", "metric": "total revenue"}',
        '{"value": null, "unit": "USD millions", "passage": 1}',
        "Je n'ai pas la valeur exacte, voir [3M, 2018, p. 42].",
    )
    answer = ask("Compare 3M total revenue 2017 vs 2018", company="3M", llm=llm)
    assert answer.route == "comparaison"
    assert [c.page for c in answer.citations] == [42]


def test_comparison_falls_back_when_company_unknown():
    llm = fake_llm('{"company": null, "metric": "revenue"}', "Réponse RAG [3M, 2018, p. 42].")
    answer = ask("Revenue 2017 vs 2018 ?", llm=llm)
    assert "Réponse RAG" in answer.answer


def test_calc_route_adds_calculation_instructions():
    seen = []

    class SpyLLM(FakeListChatModel):
        def invoke(self, messages, *args, **kwargs):
            seen.append(messages)
            return super().invoke(messages, *args, **kwargs)

    answer = ask(
        "What was 3M's revenue growth rate in 2018?",
        company="3M",
        year=2018,
        llm=SpyLLM(responses=["+3,5 % [3M, 2018, p. 42]"]),
    )
    assert answer.route == "calcul"
    assert "calcul étape par étape" in seen[0][0].content


def test_route_can_be_forced():
    answer = ask("total revenue 3M 2017 2018", route="simple", llm=fake_llm("ok"))
    assert answer.route == "simple"


def test_format_comparison_negative_change():
    from fri.mcp_server.tools import compute_comparison
    from fri.schemas import Citation, MetricValue

    def mv(year, value):
        return MetricValue(
            company="3M",
            year=year,
            metric="net income",
            value=value,
            citation=Citation(company="3M", year=year, page=10),
        )

    text = format_comparison(compute_comparison(mv(2017, 200.0), mv(2018, 150.0)))
    assert "-50 USD millions (-25 %)" in text
