"""Graphe LangGraph de l'agent.

    router ──> simple | calcul ──> retrieve ──> answer
           └─> comparaison ──> compare ──(échec)──> retrieve ──> answer

- `router` classe la question (règles simples, sans appel au LLM).
- `retrieve` + `answer` : RAG classique, réponse citée [Société, Année, p. X] ;
  pour un calcul, le LLM doit montrer les valeurs utilisées et le calcul.
- `compare` : le LLM lit la société et la métrique dans la question, les années sont
  lues par regex, puis l'outil `compare_years` calcule l'écart. Si ça échoue (année
  manquante, valeur introuvable), on retombe sur le RAG classique.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from fri.agent.citations import extract_citations, format_context, keep_valid_citations
from fri.agent.metrics import LLMMetricExtractor, message_text, parse_json_reply
from fri.agent.prompts import (
    ANSWER_PROMPT,
    CALC_INSTRUCTIONS,
    COMPARE_PARAMS_PROMPT,
    NO_RESULT_ANSWER,
    SYSTEM_PROMPT,
)
from fri.config import settings
from fri.mcp_server import tools
from fri.schemas import Answer, SearchResult, YearComparison

ROUTES = ("simple", "calcul", "comparaison")

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_COMPARE_WORDS = re.compile(
    r"\b(compar\w*|vs\.?|versus|évolu\w*|evolu\w*|chang\w*|increas\w*|decreas\w*|"
    r"grow\w*|growth|augment\w*|baiss\w*|hausse|diminu\w*|between|entre|"
    r"par rapport|from \d{4} to \d{4}|de \d{4} à \d{4})",
    re.I,
)
_CALC_WORDS = re.compile(
    r"(%|\b(ratio\w*|margin\w*|marge\w*|percent\w*|pourcent\w*|calcul\w*|compute\w*|"
    r"average|moyenne|sum|somme|total of|difference|différence|divided|divisé|"
    r"per share|par action|rate|taux)\b)",
    re.I,
)


def find_years(text: str) -> list[int]:
    """Années distinctes citées dans la question, dans l'ordre d'apparition."""
    years: list[int] = []
    for match in _YEAR_RE.finditer(text):
        year = int(match.group(0))
        if year not in years:
            years.append(year)
    return years


def classify_question(question: str) -> str:
    """simple | calcul | comparaison, par règles (rapide, gratuit, testable)."""
    if len(find_years(question)) >= 2:
        return "comparaison"  # deux années citées : on compare une métrique entre elles
    if _CALC_WORDS.search(question) or _COMPARE_WORDS.search(question):
        return "calcul"
    return "simple"


def _fmt(value: float) -> str:
    """32765.0 -> '32 765' ; 12.5 -> '12,5' (format français)."""
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    return text.replace(",", " ").replace(".", ",")


def format_comparison(comp: YearComparison) -> str:
    """Réponse rédigée à partir du résultat de compare_years (pas de LLM : chiffres exacts)."""
    a, b = comp.year_a, comp.year_b
    sign = "+" if comp.delta >= 0 else "-"
    pct = (
        f" ({'+' if comp.pct_change >= 0 else '-'}{_fmt(abs(comp.pct_change))} %)"
        if comp.pct_change is not None
        else ""
    )
    return (
        f"{comp.metric} de {comp.company} : {_fmt(a.value)} {a.unit} en {a.year} {a.citation}, "
        f"contre {_fmt(b.value)} {b.unit} en {b.year} {b.citation}. "
        f"Écart : {sign}{_fmt(abs(comp.delta))} {b.unit}{pct}."
    )


class AgentState(TypedDict, total=False):
    question: str
    company: str | None
    year: int | None
    route: str  # simple | calcul | comparaison
    results: list[SearchResult]
    comparison: YearComparison
    answer: Answer


def build_graph(llm: Any | None = None, k: int | None = None):
    """Construit et compile le graphe. `llm` : modèle de chat LangChain (sinon celui du .env)."""
    k = k or settings.top_k
    model_holder: dict[str, Any] = {"llm": llm}

    def model():
        if model_holder["llm"] is None:
            model_holder["llm"] = _default_llm()
        return model_holder["llm"]

    def router(state: AgentState) -> dict:
        route = state.get("route")
        if route not in ROUTES:
            route = classify_question(state["question"])
        return {"route": route}

    def compare(state: AgentState) -> dict:
        question = state["question"]
        years = find_years(question)
        if len(years) < 2:
            return {}
        reply = model().invoke([HumanMessage(COMPARE_PARAMS_PROMPT.format(question=question))])
        params = parse_json_reply(message_text(reply)) or {}
        company = state.get("company") or params.get("company")
        metric = params.get("metric")
        if not company or not metric or str(company).lower() == "null":
            return {}
        year_a, year_b = sorted(years[:2])
        try:
            comp = tools.compare_years(
                str(company), str(metric), year_a, year_b, extractor=LLMMetricExtractor(model())
            )
        except (LookupError, ValueError):
            return {}
        answer = Answer(
            question=question,
            answer=format_comparison(comp),
            citations=[comp.year_a.citation, comp.year_b.citation],
            route="comparaison",
        )
        return {"comparison": comp, "answer": answer}

    def after_compare(state: AgentState) -> str:
        return END if state.get("answer") else "retrieve"

    def retrieve(state: AgentState) -> dict:
        results = tools.search_filings(
            state["question"], company=state.get("company"), year=state.get("year"), k=k
        )
        return {"results": results}

    def answer(state: AgentState) -> dict:
        question, results = state["question"], state.get("results", [])
        route = state.get("route") or "simple"
        if not results:
            text, citations = NO_RESULT_ANSWER, []
        else:
            system = SYSTEM_PROMPT + (CALC_INSTRUCTIONS if route == "calcul" else "")
            prompt = ANSWER_PROMPT.format(context=format_context(results), question=question)
            text = message_text(model().invoke([SystemMessage(system), HumanMessage(prompt)]))
            citations = keep_valid_citations(extract_citations(text), results)
        return {"answer": Answer(question=question, answer=text, citations=citations, route=route)}

    graph = StateGraph(AgentState)
    graph.add_node("router", router)
    graph.add_node("compare", compare)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        lambda s: "compare" if s["route"] == "comparaison" else "retrieve",
        ["compare", "retrieve"],
    )
    graph.add_conditional_edges("compare", after_compare, ["retrieve", END])
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


def _default_llm():
    from fri.agent.llm import get_chat_model

    return get_chat_model()


def ask(
    question: str,
    company: str | None = None,
    year: int | None = None,
    llm: Any | None = None,
    route: str | None = None,
) -> Answer:
    """Point d'entrée utilisé par l'API et l'interface. `route` force le routage (optionnel)."""
    if not question.strip():
        raise ValueError("La question est vide.")
    state = build_graph(llm=llm).invoke(
        {"question": question, "company": company, "year": year, "route": route}
    )
    return state["answer"]
