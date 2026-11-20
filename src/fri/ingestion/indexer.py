"""Construit l'index vectoriel (ChromaDB) et l'index BM25 à partir des PDF.

Usage :
    python -m fri.ingestion.indexer
    python -m fri.ingestion.indexer --docs 3M_2018_10K AMD_2022_10K
    python -m fri.ingestion.indexer --limit 3          # essai rapide sur 3 PDF

Mise à jour sans tout reconstruire (voir ``update_index``) :

    python -m fri.ingestion.indexer --update                    # PDF nouveaux ou modifiés
    python -m fri.ingestion.indexer --update --docs 3M_2018_10K # forcer un rapport
    python -m fri.ingestion.indexer --remove PFIZER_2021_10K    # retirer un rapport
    python -m fri.ingestion.indexer --update --prune            # + retirer les PDF supprimés

Contenu de ``data/index/`` après exécution :

* ``chroma/`` : la collection ChromaDB (embeddings + texte + métadonnées) ;
* ``chunks.jsonl`` : tous les chunks, relus au chargement pour reconstruire BM25 ;
* ``manifest.json`` : modèle d'embeddings, réglages du découpage, nombre de chunks.

Sans ``--update`` / ``--remove``, l'index est reconstruit de zéro. Le manifeste garde
l'empreinte SHA-256 de chaque PDF : ``--update`` ne recalcule que les rapports nouveaux
ou modifiés, avec les réglages (modèle, découpage) de l'index existant.
Le texte des PDF est mis en cache (``data/cache/pages``) : relancer est rapide,
seul le calcul des embeddings prend du temps.
"""

from __future__ import annotations

import argparse
import hashlib
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_documents(
    paths: Sequence[Path], cache_dir: Path, chunk_size: int, overlap: int
) -> tuple[list[Chunk], dict[str, dict[str, Any]]]:
    """PDF -> chunks. Renvoie les chunks et, par document indexé, son empreinte."""
    chunks: list[Chunk] = []
    files: dict[str, dict[str, Any]] = {}
    for i, path in enumerate(paths, start=1):
        try:
            pages = parse_pdf(path, cache_dir=cache_dir)
            doc_chunks = chunk_pages(pages, chunk_size, overlap)
        except (PDFParsingError, ValueError) as err:
            logger.error("Ignoré : %s (%s)", path.name, err)
            continue
        chunks.extend(doc_chunks)
        files[path.stem] = {
            "sha256": file_sha256(path),
            "pages": len(pages),
            "chunks": len(doc_chunks),
            "indexed_at": _now(),
        }
        logger.info(
            "[%d/%d] %s : %d pages, %d chunks",
            i,
            len(paths),
            path.stem,
            len(pages),
            len(doc_chunks),
        )
    return chunks, files


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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

    chunks, files = _chunk_documents(paths, cache_dir, chunk_size, overlap)
    indexed = sorted(files)
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
        "created_at": _now(),
        "embedding_model": embedding_model,
        "query_prefix": query_prefix,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "documents": indexed,
        "n_documents": len(indexed),
        "n_chunks": len(chunks),
        "seconds": round(time.perf_counter() - start, 1),
        "files": files,
    }
    _write_manifest(index_dir, manifest)
    return manifest


def _write_manifest(index_dir: Path, manifest: dict[str, Any]) -> None:
    path = index_dir / MANIFEST
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def update_index(
    pdf_dir: str | Path | None = None,
    index_dir: str | Path | None = None,
    *,
    docs: Sequence[str] | None = None,
    remove: Sequence[str] | None = None,
    prune: bool = False,
    cache_dir: str | Path | None = None,
    embedder=None,
) -> dict[str, Any]:
    """Met à jour un index existant sans le reconstruire.

    * PDF absent de l'index -> ajouté ; PDF dont l'empreinte a changé -> remplacé ;
    * ``docs`` -> ces rapports sont réindexés même s'ils n'ont pas changé ;
    * ``remove`` -> ces rapports sont retirés, et ne reviennent pas au prochain ``update``
      tant qu'on ne les redemande pas avec ``docs`` ; ``prune`` -> retire aussi ceux dont le PDF
      a disparu du dossier (sinon ils sont seulement signalés).

    Les réglages (modèle d'embeddings, taille des chunks) sont ceux de l'index existant.
    Un index construit avant cette version n'a pas d'empreintes : elles sont enregistrées
    au premier ``--update`` et ses rapports sont considérés comme à jour.
    Renvoie le manifeste, avec un champ ``changes`` (added / updated / removed / unchanged).
    """
    from fri.retrieval.vector import VectorRetriever, load_embedder

    pdf_dir = Path(pdf_dir or settings.data_dir / "pdfs")
    index_dir = Path(index_dir or settings.index_dir)
    cache_dir = Path(cache_dir or settings.data_dir / "cache" / "pages")
    manifest = read_manifest(index_dir)
    start = time.perf_counter()

    files: dict[str, dict[str, Any]] = dict(manifest.get("files") or {})
    known = set(manifest.get("documents") or [])
    on_disk = {p.stem: p for p in find_pdfs(pdf_dir)} if pdf_dir.is_dir() else {}
    forced = set(docs or [])
    unknown = forced - set(on_disk)
    if unknown:
        raise FileNotFoundError(f"PDF absents de {pdf_dir} : {sorted(unknown)}")
    not_indexed = set(remove or []) - known
    if not_indexed:
        raise ValueError(f"Rapports absents de l'index : {sorted(not_indexed)}")

    # Rapports retirés avec --remove : le prochain --update ne les rajoute pas
    # (sauf s'ils sont redemandés avec --docs).
    excluded = (set(manifest.get("excluded") or []) | set(remove or [])) - forced
    to_remove = set(remove or [])
    vanished = known - set(on_disk) - to_remove
    if vanished:
        if prune:
            to_remove |= vanished
        else:
            logger.warning(
                "PDF disparus (gardés dans l'index, --prune pour les retirer) : %s",
                ", ".join(sorted(vanished)),
            )

    to_index: list[Path] = []
    added: list[str] = []
    updated: list[str] = []
    for name, path in sorted(on_disk.items()):
        if name in to_remove or (name in excluded and name not in known):
            continue
        if name not in known:
            to_index.append(path)
            added.append(name)
            continue
        sha = file_sha256(path)
        old = files.get(name, {}).get("sha256")
        if name in forced or (old is not None and old != sha):
            to_index.append(path)
            updated.append(name)
        elif old is None:  # ancien index : on enregistre l'empreinte actuelle
            files[name] = {"sha256": sha}
    unchanged = sorted(known - set(updated) - to_remove)

    excluded_list = sorted(excluded & set(on_disk))
    if not to_index and not to_remove:
        if files != (manifest.get("files") or {}) or excluded_list != manifest.get("excluded", []):
            manifest["files"] = files
            manifest["excluded"] = excluded_list
            _write_manifest(index_dir, manifest)
        manifest["changes"] = {"added": [], "updated": [], "removed": [], "unchanged": unchanged}
        return manifest

    new_chunks, new_files = _chunk_documents(
        to_index, cache_dir, manifest["chunk_size"], manifest["chunk_overlap"]
    )
    failed = {p.stem for p in to_index} - set(new_files)
    added = [d for d in added if d not in failed]
    updated = [d for d in updated if d not in failed]  # échec : l'ancienne version reste

    replaced = to_remove | set(updated)
    chunks = [c for c in load_chunks(index_dir) if c.metadata.doc_name not in replaced]
    chunks.extend(new_chunks)

    embedder = embedder or load_embedder(manifest["embedding_model"], manifest.get("query_prefix"))
    vector = VectorRetriever(index_dir, manifest["embedding_model"], embedder=embedder)

    # Pendant la mise à jour, pas de manifeste : un index à moitié modifié n'est jamais chargé.
    (index_dir / MANIFEST).unlink()
    for name in sorted(replaced):
        vector.collection.delete(where={"doc_name": name})
        files.pop(name, None)
    if new_chunks:
        logger.info("Calcul des embeddings de %d chunks...", len(new_chunks))
        vector.add(new_chunks)
    save_chunks(chunks, index_dir)

    files.update(new_files)
    documents = sorted({c.metadata.doc_name for c in chunks})
    manifest.update(
        {
            "updated_at": _now(),
            "documents": documents,
            "n_documents": len(documents),
            "n_chunks": len(chunks),
            "files": {d: files[d] for d in documents if d in files},
            "excluded": excluded_list,
        }
    )
    _write_manifest(index_dir, manifest)
    manifest["changes"] = {
        "added": added,
        "updated": updated,
        "removed": sorted(to_remove),
        "unchanged": unchanged,
        "seconds": round(time.perf_counter() - start, 1),
    }
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
    parser.add_argument(
        "--update",
        action="store_true",
        help="mettre à jour l'index existant : seulement les PDF nouveaux ou modifiés",
    )
    parser.add_argument("--remove", nargs="+", metavar="DOC", help="retirer ces rapports")
    parser.add_argument(
        "--prune", action="store_true", help="avec --update : retirer les PDF supprimés du dossier"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # pas de log par requête HTTP

    if args.update or args.remove:
        print(f"Mise à jour de l'index {args.index_dir} avec les PDF de {args.pdf_dir}")
        manifest = update_index(
            args.pdf_dir, args.index_dir, docs=args.docs, remove=args.remove, prune=args.prune
        )
        ch = manifest["changes"]
        for label, key in (("Ajoutés", "added"), ("Mis à jour", "updated"), ("Retirés", "removed")):
            print(f"{label} : {', '.join(ch[key]) or 'aucun'}")
        print(
            f"Inchangés : {len(ch['unchanged'])}. Index : {manifest['n_documents']} documents, "
            f"{manifest['n_chunks']} chunks."
        )
        if ch["added"] or ch["updated"] or ch["removed"]:
            print("Redémarrez l'API ou le serveur MCP pour qu'ils relisent l'index.")
        return 0

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
