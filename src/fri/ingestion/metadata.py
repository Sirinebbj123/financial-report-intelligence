"""Déduction des métadonnées (société, année, type) depuis le nom du document."""

from __future__ import annotations

import re

from fri.schemas import DocType

_DOC_RE = re.compile(r"^(?P<company>.+?)_(?P<year>\d{4})(?:Q\d)?_(?P<type>[0-9A-Z]+)", re.I)

_TYPES = {
    "10K": DocType.TEN_K,
    "10Q": DocType.TEN_Q,
    "8K": DocType.EIGHT_K,
    "EARNINGS": DocType.EARNINGS,
}


def parse_doc_name(doc_name: str) -> tuple[str, int, DocType]:
    """Ex. '3M_2018_10K' -> ('3M', 2018, DocType.TEN_K)."""
    match = _DOC_RE.match(doc_name)
    if not match:
        raise ValueError(f"Nom de document inattendu : {doc_name}")
    doc_type = _TYPES.get(match["type"].upper(), DocType.OTHER)
    return match["company"], int(match["year"]), doc_type
