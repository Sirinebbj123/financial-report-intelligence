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
