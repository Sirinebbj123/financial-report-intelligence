"""Graphe LangGraph : router -> retrieve -> (calcul | comparaison) -> answer."""

from __future__ import annotations

from typing import TypedDict

from fri.schemas import Answer, SearchResult


class AgentState(TypedDict, total=False):
    question: str
    route: str  # simple | calcul | comparaison
    results: list[SearchResult]
    answer: Answer


def build_graph():
    """Construit et compile le graphe LangGraph."""
    # TODO(Rôle 2) :
    #   graph = StateGraph(AgentState)
    #   graph.add_node("router", ...); graph.add_node("retrieve", ...); ...
    #   graph.add_conditional_edges("router", ...)
    raise NotImplementedError


def ask(question: str) -> Answer:
    """Point d'entrée utilisé par l'API et l'interface."""
    # TODO(Rôle 2) : build_graph().invoke({"question": question})["answer"]
    raise NotImplementedError
