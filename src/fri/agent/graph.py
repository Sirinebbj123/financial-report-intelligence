"""Graphe LangGraph de l'agent.

Version actuelle (tâche 3) : retrieve -> answer, réponse citée [Société, Année, p. X].
Prochaine étape (tâche 4) : router -> retrieve -> (calcul | comparaison) -> answer.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from fri.agent.citations import extract_citations, format_context, keep_valid_citations
from fri.agent.prompts import ANSWER_PROMPT, NO_RESULT_ANSWER, SYSTEM_PROMPT
from fri.config import settings
from fri.mcp_server import tools
from fri.schemas import Answer, SearchResult


class AgentState(TypedDict, total=False):
    question: str
    company: str | None
    year: int | None
    route: str  # simple | calcul | comparaison
    results: list[SearchResult]
    answer: Answer


def _content(message: Any) -> str:
    """Texte d'une réponse de LLM (message LangChain ou simple chaîne)."""
    content = getattr(message, "content", message)
    if isinstance(content, list):  # certains fournisseurs renvoient des blocs
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content).strip()


def build_graph(llm: Any | None = None, k: int | None = None):
    """Construit et compile le graphe. `llm` : modèle de chat LangChain (sinon celui du .env)."""
    k = k or settings.top_k

    def retrieve(state: AgentState) -> dict:
        results = tools.search_filings(
            state["question"], company=state.get("company"), year=state.get("year"), k=k
        )
        return {"results": results, "route": state.get("route") or "simple"}

    def answer(state: AgentState) -> dict:
        question, results = state["question"], state.get("results", [])
        if not results:
            text, citations = NO_RESULT_ANSWER, []
        else:
            model = llm if llm is not None else _default_llm()
            prompt = ANSWER_PROMPT.format(context=format_context(results), question=question)
            reply = model.invoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(prompt)])
            text = _content(reply)
            citations = keep_valid_citations(extract_citations(text), results)
        return {
            "answer": Answer(
                question=question, answer=text, citations=citations, route=state.get("route")
            )
        }

    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


def _default_llm():
    from fri.agent.llm import get_chat_model

    return get_chat_model()


def ask(
    question: str, company: str | None = None, year: int | None = None, llm: Any | None = None
) -> Answer:
    """Point d'entrée utilisé par l'API et l'interface."""
    if not question.strip():
        raise ValueError("La question est vide.")
    state = build_graph(llm=llm).invoke({"question": question, "company": company, "year": year})
    return state["answer"]
