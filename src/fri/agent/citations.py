"""Formatage et extraction des citations [Société, Année, p. X]."""

from __future__ import annotations

import re

from fri.schemas import Citation, SearchResult

_CITATION_RE = re.compile(r"\[(?P<company>[^,\]]+),\s*(?P<year>\d{4}),\s*p\.\s*(?P<page>\d+)\]")


def citation_from_result(result: SearchResult) -> Citation:
    meta = result.chunk.metadata
    return Citation(company=meta.company, year=meta.year, page=meta.page, doc_name=meta.doc_name)


def extract_citations(text: str) -> list[Citation]:
    """Retrouve les citations présentes dans une réponse générée."""
    return [
        Citation(company=m["company"].strip(), year=int(m["year"]), page=int(m["page"]))
        for m in _CITATION_RE.finditer(text)
    ]


def format_context(results: list[SearchResult]) -> str:
    """Met les passages dans le prompt, chacun précédé de la citation à recopier."""
    blocks = []
    for i, result in enumerate(results, start=1):
        cite = citation_from_result(result)
        blocks.append(f"Passage {i} {cite}\n{result.chunk.text.strip()}")
    return "\n\n".join(blocks)


def keep_valid_citations(cited: list[Citation], results: list[SearchResult]) -> list[Citation]:
    """Garde les citations qui pointent vers un passage fourni au LLM, sans doublon.

    Une citation inventée par le LLM (page ou année absente des passages) est retirée.
    Le nom du PDF est repris du passage correspondant.
    """
    sources: dict[tuple[str, int, int], Citation] = {}
    for result in results:
        cite = citation_from_result(result)
        sources.setdefault((cite.company.casefold(), cite.year, cite.page), cite)

    kept: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    for cite in cited:
        key = (cite.company.casefold(), cite.year, cite.page)
        if key in sources and key not in seen:
            seen.add(key)
            kept.append(sources[key])
    return kept
