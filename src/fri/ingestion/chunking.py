"""Découpage des pages en chunks qui gardent leurs métadonnées.

Un chunk ne dépasse jamais une page : sa page d'origine est la page citée
``[Société, Année, p. X]``. Le découpage coupe d'abord entre les paragraphes, puis
entre les lignes, puis entre les phrases, et en dernier recours entre les mots.
Les lignes de tableau reconstruites par le parser (``Net sales 32,765 31,657``)
restent donc entières tant qu'elles tiennent dans un chunk.
"""

from __future__ import annotations

from collections.abc import Iterable

from fri.ingestion.metadata import parse_doc_name
from fri.ingestion.pdf_parser import Page
from fri.schemas import Chunk, ChunkMetadata

# Du plus « gros » au plus fin : paragraphe, ligne, phrase, mot.
SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ")


def split_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 100,
    separators: tuple[str, ...] = SEPARATORS,
) -> list[str]:
    """Découpe un texte en morceaux d'au plus ``chunk_size`` caractères.

    Deux morceaux qui se suivent partagent jusqu'à ``overlap`` caractères (des
    lignes ou des phrases entières, jamais un mot coupé), pour qu'une phrase à
    cheval sur deux chunks reste lisible dans au moins l'un des deux.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size doit être >= 1, reçu {chunk_size}")
    if not 0 <= overlap < chunk_size:
        raise ValueError(f"overlap doit être entre 0 et chunk_size - 1, reçu {overlap}")
    text = text.strip()
    if not text:
        return []
    return [c for c in _split(text, chunk_size, overlap, separators) if c.strip()]


def _split(text: str, size: int, overlap: int, separators: tuple[str, ...]) -> list[str]:
    if len(text) <= size:
        return [text]
    for i, sep in enumerate(separators):
        if sep in text:
            parts = [p for p in text.split(sep) if p.strip()]
            finer = separators[i + 1 :]
            break
    else:  # aucun séparateur : coupe brute (mot géant, rare)
        step = size - overlap
        return [text[i : i + size] for i in range(0, len(text), step)]

    pieces: list[str] = []
    for part in parts:
        if len(part) <= size:
            pieces.append(part)
        else:
            pieces.extend(_split(part, size, overlap, finer))
    return _merge(pieces, sep, size, overlap)


def _merge(pieces: list[str], sep: str, size: int, overlap: int) -> list[str]:
    """Regroupe les morceaux jusqu'à ``size`` caractères, avec chevauchement."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0  # longueur de sep.join(current)
    for piece in pieces:
        added = len(piece) + (len(sep) if current else 0)
        if current and length + added > size:
            chunks.append(sep.join(current).strip())
            # Garder la fin du chunk précédent (au plus `overlap` caractères).
            while current and (length > overlap or length + len(sep) + len(piece) > size):
                length -= len(current[0]) + (len(sep) if len(current) > 1 else 0)
                current.pop(0)
            added = len(piece) + (len(sep) if current else 0)
        current.append(piece)
        length += added
    if current:
        chunks.append(sep.join(current).strip())
    return chunks


def chunk_page(page: Page, chunk_size: int = 800, overlap: int = 100) -> list[Chunk]:
    """Découpe une page en chunks ; chaque chunk garde la page d'origine.

    Les métadonnées (société, année, type) viennent du nom du document
    (``3M_2018_10K``). L'identifiant ``<doc>-p<page>-c<i>`` est stable : réindexer
    le même PDF avec les mêmes réglages donne les mêmes identifiants.

    Raises:
        ValueError: le nom du document ne suit pas le format FinanceBench.
    """
    company, year, doc_type = parse_doc_name(page.doc_name)
    metadata = ChunkMetadata(
        company=company, year=year, doc_type=doc_type, doc_name=page.doc_name, page=page.page
    )
    return [
        Chunk(id=f"{page.doc_name}-p{page.page}-c{i}", text=text, metadata=metadata)
        for i, text in enumerate(split_text(page.text, chunk_size, overlap))
    ]


def chunk_pages(pages: Iterable[Page], chunk_size: int = 800, overlap: int = 100) -> list[Chunk]:
    """Découpe toutes les pages d'un document, dans l'ordre."""
    return [c for page in pages for c in chunk_page(page, chunk_size, overlap)]


def search_text(chunk: Chunk) -> str:
    """Texte indexé (BM25 et embeddings) : un en-tête société / année / type + le chunk.

    Le texte affiché et cité reste ``chunk.text`` ; l'en-tête aide seulement la
    recherche quand la question nomme la société ou l'année sans filtre.
    """
    m = chunk.metadata
    return f"{m.company} {m.year} {m.doc_type.value}\n{chunk.text}"
