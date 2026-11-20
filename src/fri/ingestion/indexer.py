"""Construit l'index vectoriel (ChromaDB) et l'index BM25 à partir des PDF.

Usage :
    python -m fri.ingestion.indexer
    python -m fri.ingestion.indexer --docs 3M_2018_10K AMD_2022_10K
    python -m fri.ingestion.indexer --limit 3          # essai rapide sur 3 PDF

Contenu de ``data/index/`` après exécution :

* ``chroma/`` : la collection ChromaDB (embeddings + texte + métadonnées) ;
* ``chunks.jsonl`` : tous les chunks, relus au chargement pour reconstruire BM25 ;
* ``manifest.json`` : modèle d'embeddings, réglages du découpage, nombre de chunks.

Chaque lancement reconstruit l'index de zéro : pas de mélange entre deux réglages.
Le texte des PDF est mis en cache (``data/cache/pages``) : relancer est rapide,
seul le calcul des embeddings prend du temps.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fri.config import settings
from fri.ingestion.chunking import chunk_pages
from fri.ingestion.pdf_parser import PDFParsingError, parse_pdf
from fri.schemas import Chunk

logger = logging.getLogger(__name__)

MANIFEST = "manifest.json"
CHUNKS = "chunks.jsonl"
INDEX_VERSION = 1


def save_chunks(chunks: Sequence[Chunk], index_dir: Path) -> Path:
    path = index_dir / CHUNKS
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk.model_dump_json() + "\n")
    os.replace(tmp, path)
    return path


def load_chunks(index_dir: str | Path) -> list[Chunk]:
    path = Path(index_dir) / CHUNKS
    with path.open(encoding="utf-8") as f:
        return [Chunk.model_validate_json(line) for line in f if line.strip()]


def read_manifest(index_dir: str | Path) -> dict[str, Any]:
    """Lit ``manifest.json`` ; erreur claire si l'index n'a pas été construit."""
    path = Path(index_dir) / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(
            f"Index introuvable dans {index_dir} (pas de {MANIFEST}). "
            "Lance d'abord `python -m fri.ingestion.indexer`."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != INDEX_VERSION:
        raise RuntimeError(
            f"Index construit avec une autre version ({manifest.get('version')}), "
            "relance `python -m fri.ingestion.indexer`."
        )
    return manifest


def find_pdfs(pdf_dir: Path, docs: Sequence[str] | None = None, limit: int | None = None):
    if not pdf_dir.is_dir():
        raise NotADirectoryError(
            f"Dossier introuvable : {pdf_dir}. Lance `python data/download_financebench.py`."
        )
    paths = sorted(pdf_dir.glob("*.pdf"))
    if docs:
        wanted = set(docs)
        paths = [p for p in paths if p.stem in wanted]
        missing = wanted - {p.stem for p in paths}
        if missing:
            raise FileNotFoundError(f"PDF absents de {pdf_dir} : {sorted(missing)}")
    return paths[:limit] if limit else paths


def build_index(
    pdf_dir: str | Path | None = None,
    index_dir: str | Path | None = None,
    *,
    embedding_model: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
    docs: Sequence[str] | None = None,
    limit: int | None = None,
    cache_dir: str | Path | None = None,
    embedder=None,
) -> dict[str, Any]:
    """PDF -> pages -> chunks -> Chroma (embeddings) + chunks.jsonl (BM25).

    Un PDF illisible ou mal nommé est signalé puis ignoré. Renvoie le manifeste.
    """
    from fri.retrieval.vector import VectorRetriever, default_query_prefix, load_embedder

    pdf_dir = Path(pdf_dir or settings.data_dir / "pdfs")
    index_dir = Path(index_dir or settings.index_dir)
    cache_dir = Path(cache_dir or settings.data_dir / "cache" / "pages")
    embedding_model = embedding_model or settings.embedding_model
    chunk_size = chunk_size or settings.chunk_size
    overlap = settings.chunk_overlap if overlap is None else overlap
    query_prefix = getattr(embedder, "query_prefix", default_query_prefix(embedding_model))
    embedder = embedder or load_embedder(embedding_model, query_prefix)

    start = time.perf_counter()
    paths = find_pdfs(pdf_dir, docs, limit)
    if not paths:
        raise FileNotFoundError(f"Aucun PDF dans {pdf_dir}")

    chunks: list[Chunk] = []
    indexed: list[str] = []
    for i, path in enumerate(paths, start=1):
        try:
            pages = parse_pdf(path, cache_dir=cache_dir)
            doc_chunks = chunk_pages(pages, chunk_size, overlap)
        except (PDFParsingError, ValueError) as err:
            logger.error("Ignoré : %s (%s)", path.name, err)
            continue
        chunks.extend(doc_chunks)
        indexed.append(path.stem)
        logger.info(
            "[%d/%d] %s : %d pages, %d chunks",
            i,
            len(paths),
            path.stem,
            len(pages),
            len(doc_chunks),
        )
    if not chunks:
        raise RuntimeError("Aucun chunk produit : rien à indexer.")

    # Repartir de zéro : un ancien index avec d'autres réglages ne doit pas rester.
    # Le manifeste est écrit en dernier : sans lui, l'index est considéré comme absent.
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / MANIFEST).unlink(missing_ok=True)
    save_chunks(chunks, index_dir)
    logger.info("Calcul des embeddings de %d chunks avec %s...", len(chunks), embedding_model)
    vector = VectorRetriever(index_dir, embedding_model, embedder=embedder, reset=True)
    vector.add(chunks)

    manifest = {
        "version": INDEX_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "embedding_model": embedding_model,
        "query_prefix": query_prefix,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "documents": indexed,
        "n_documents": len(indexed),
        "n_chunks": len(chunks),
        "seconds": round(time.perf_counter() - start, 1),
    }
    (index_dir / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construit l'index BM25 + ChromaDB.")
    parser.add_argument("--pdf-dir", type=Path, default=settings.data_dir / "pdfs")
    parser.add_argument("--index-dir", type=Path, default=settings.index_dir)
    parser.add_argument("--docs", nargs="+", metavar="DOC", help="ex. 3M_2018_10K AMD_2022_10K")
    parser.add_argument("--limit", type=int, help="seulement les N premiers PDF (essai)")
    parser.add_argument("--chunk-size", type=int, default=settings.chunk_size)
    parser.add_argument("--overlap", type=int, default=settings.chunk_overlap)
    parser.add_argument("--embedding-model", default=settings.embedding_model)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # pas de log par requête HTTP

    print(f"Indexation des PDF de {args.pdf_dir} vers {args.index_dir}")
    manifest = build_index(
        args.pdf_dir,
        args.index_dir,
        embedding_model=args.embedding_model,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        docs=args.docs,
        limit=args.limit,
    )
    print(
        f"Terminé : {manifest['n_documents']} documents, {manifest['n_chunks']} chunks "
        f"en {manifest['seconds']} s -> {args.index_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
