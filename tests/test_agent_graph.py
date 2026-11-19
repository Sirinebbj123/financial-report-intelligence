"""Tests de la chaîne RAG LangGraph, avec un faux LLM et le retriever de démo."""

import pytest

pytest.importorskip("langgraph")

from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402

from fri.agent.citations import format_context, keep_valid_citations  # noqa: E402
from fri.agent.graph import ask, build_graph  # noqa: E402
from fri.agent.prompts import NO_RESULT_ANSWER  # noqa: E402
from fri.mcp_server import tools  # noqa: E402
from fri.mcp_server.demo import demo_retriever  # noqa: E402
from fri.schemas import Citation  # noqa: E402


@pytest.fixture(autouse=True)
def demo_index():
    tools.set_retriever(demo_retriever())
    yield
    tools.set_retriever(None)


def fake_llm(*replies: str) -> FakeListChatModel:
    return FakeListChatModel(responses=list(replies))


def test_ask_returns_answer_with_citation():
    llm = fake_llm("Le chiffre d'affaires de 3M en 2018 est de 32 765 M$ [3M, 2018, p. 42].")
    answer = ask("Quel est le chiffre d'affaires de 3M en 2018 ?", company="3M", year=2018, llm=llm)
    assert answer.route == "simple"
    assert [(c.company, c.year, c.page) for c in answer.citations] == [("3M", 2018, 42)]
    assert answer.citations[0].doc_name == "3M_2018_10K"


def test_invented_citation_is_removed():
    llm = fake_llm("32 765 M$ [3M, 2018, p. 42], voir aussi [3M, 2018, p. 999].")
    answer = ask("total revenue 3M 2018", company="3M", year=2018, llm=llm)
    assert [c.page for c in answer.citations] == [42]


def test_duplicate_citations_are_merged():
    llm = fake_llm("A [3M, 2018, p. 42]. B [3M, 2018, p. 42].")
    answer = ask("total revenue 3M 2018", company="3M", year=2018, llm=llm)
    assert len(answer.citations) == 1


def test_no_passage_means_no_llm_call():
    llm = fake_llm()  # aucune réponse prévue : planterait s'il était appelé
    answer = ask("revenue", company="Apple", llm=llm)
    assert answer.answer == NO_RESULT_ANSWER
    assert answer.citations == []


def test_prompt_contains_passages_and_citations():
    seen = []

    class SpyLLM(FakeListChatModel):
        def invoke(self, messages, *args, **kwargs):
            seen.append(messages)
            return super().invoke(messages, *args, **kwargs)

    ask("total revenue", company="3M", year=2018, llm=SpyLLM(responses=["ok"]))
    prompt = seen[0][-1].content
    assert "[3M, 2018, p. 42]" in prompt
    assert "$32,765 million" in prompt
    assert "Question : total revenue" in prompt


def test_graph_state_keeps_results():
    state = build_graph(llm=fake_llm("ok"), k=2).invoke({"question": "total revenue 3M"})
    assert 0 < len(state["results"]) <= 2


def test_empty_question_is_rejected():
    with pytest.raises(ValueError):
        ask("  ", llm=fake_llm("ok"))


def test_format_context_numbers_passages():
    results = tools.search_filings("total revenue", company="3M")
    text = format_context(results)
    assert text.startswith("Passage 1 [3M, ")
    assert "Passage 2 [3M, " in text


def test_keep_valid_citations_is_case_insensitive():
    results = tools.search_filings("net revenue", company="AMD")
    kept = keep_valid_citations([Citation(company="amd", year=2022, page=51)], results)
    assert kept and kept[0].company == "AMD"
