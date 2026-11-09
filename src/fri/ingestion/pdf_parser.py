"""Extraction du texte des rapports financiers PDF, page par page.

Chaque page du PDF devient un objet :class:`Page` qui garde son numéro (1-indexé).
Ce numéro est la base des citations ``[Société, Année, p. X]`` : il n'est jamais
renuméroté, même quand des pages vides sont ignorées.

Deux moteurs sont pris en charge :

* ``pymupdf`` (par défaut) : rapide (~1 s pour un 10-K de 160 pages) ;
* ``pdfplumber`` : plus lent, utilisé en secours si PyMuPDF n'est pas installé.

Deux modes d'extraction :

* ``layout`` (par défaut) : les mots sont regroupés par ligne *visuelle* à partir de
  leurs coordonnées. Les lignes des tableaux financiers restent sur une seule ligne
  (``Depreciation and amortization 1,488 1,544 1,474``) au lieu d'avoir une cellule
  par ligne, ce qui aide beaucoup le chunking, BM25 et l'extraction de métriques ;
* ``raw`` : le texte tel que le renvoie le moteur (ordre du flux PDF).

Options complémentaires :

* ``columns=True`` (par défaut) : une zone à plusieurs colonnes de texte est lue colonne
  par colonne (voir :mod:`fri.ingestion.layout`) ;
* ``tables=True`` : les tableaux de chiffres sont extraits en lignes x colonnes dans
  ``Page.tables`` (voir :mod:`fri.ingestion.tables`) ;
* ``cache_dir=...`` : les pages sont mises en cache en JSONL et ne sont plus reparsées.

Correspondance avec FinanceBench : ``evidence_page_num`` est 0-indexé, donc
``Page.page == evidence_page_num + 1`` (voir :attr:`Page.index`).

Usage en ligne de commande ::

    python -m fri.ingestion.pdf_parser data/pdfs/3M_2018_10K.pdf --show 60
    python -m fri.ingestion.pdf_parser data/pdfs/3M_2018_10K.pdf --tables --show 60
    python -m fri.ingestion.pdf_parser data/pdfs --cache-dir data/cache/pages
    python -m fri.ingestion.pdf_parser data/pdfs --jsonl data/pages.jsonl
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from fri.ingestion.layout import WordBox, words_to_text
from fri.ingestion.tables import Table, extract_tables

logger = logging.getLogger(__name__)

Engine = Literal["auto", "pymupdf", "pdfplumber"]
Mode = Literal["layout", "raw"]


__all__ = [
    "CACHE_VERSION",
    "Page",
    "PDFParsingError",
    "Table",
    "clean_text",
    "iter_pages",
    "parse_directory",
    "parse_pdf",
    "remove_repeated_lines",
    "words_to_text",
]


class PDFParsingError(RuntimeError):
    """Le PDF ne peut pas être lu (fichier corrompu, chiffré, ou pas un PDF)."""


@dataclass(frozen=True, slots=True)
class Page:
    """Le texte d'une page de PDF et sa position dans le document."""

    doc_name: str
    page: int  # 1-indexé, sert à la citation
    text: str
    tables: tuple[Table, ...] = ()  # rempli seulement avec tables=True

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"Le numéro de page est 1-indexé, reçu {self.page}")

    @property
    def index(self) -> int:
        """Numéro 0-indexé, comme ``evidence_page_num`` dans FinanceBench."""
        return self.page - 1

    @property
    def is_empty(self) -> bool:
        """Vrai si la page n'a pas de texte (page blanche ou scannée sans OCR)."""
        return not self.text.strip()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"doc_name": self.doc_name, "page": self.page, "text": self.text}
        if self.tables:
            data["tables"] = [t.to_dict() for t in self.tables]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Page:
        return cls(
            doc_name=data["doc_name"],
            page=int(data["page"]),
            text=data["text"],
            tables=tuple(Table.from_dict(t) for t in data.get("tables", ())),
        )


# --------------------------------------------------------------------------- #
# Nettoyage du texte
# --------------------------------------------------------------------------- #

# Caractères de contrôle, sauf \t et \n (qui portent la mise en forme).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPACES_RE = re.compile(r"[ \t  -​  　]+")
_ZERO_WIDTH = dict.fromkeys(map(ord, "­‌‍⁠﻿"))


def clean_text(text: str) -> str:
    """Normalise le texte extrait sans changer son sens.

    * Unicode NFKC : ligatures (``ﬁ`` -> ``fi``), espaces insécables, chiffres pleine chasse ;
    * suppression des caractères de contrôle, des césures invisibles et des espaces de largeur 0 ;
    * espaces multiples réduits à un seul, espaces en début / fin de ligne retirés ;
    * au plus une ligne vide consécutive (frontière de paragraphe), aucune au début ni à la fin.

    Les retours à la ligne sont conservés : ils séparent les lignes des tableaux.
    """
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)

    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = _SPACES_RE.sub(" ", raw_line).strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Moteurs d'extraction
# --------------------------------------------------------------------------- #

# Ce que chaque moteur renvoie pour une page : (numéro, boîtes de mots, texte brut).
_RawPage = tuple[int, list[WordBox], str]


def _import_pymupdf() -> Any:
    try:
        import pymupdf  # PyMuPDF >= 1.24
    except ImportError:
        import fitz as pymupdf  # anciennes versions de PyMuPDF
    return pymupdf


def _available(engine: str) -> bool:
    try:
        if engine == "pymupdf":
            _import_pymupdf()
        else:
            import pdfplumber  # noqa: F401
    except ImportError:
        return False
    return True


def _resolve_engine(engine: Engine) -> str:
    if engine == "auto":
        for candidate in ("pymupdf", "pdfplumber"):
            if _available(candidate):
                return candidate
        raise ImportError("Aucun moteur PDF installé : pip install pymupdf (ou pdfplumber)")
    if engine not in ("pymupdf", "pdfplumber"):
        raise ValueError(f"Moteur inconnu : {engine!r} (auto, pymupdf ou pdfplumber)")
    if not _available(engine):
        raise ImportError(f"Le moteur {engine!r} n'est pas installé : pip install {engine}")
    return engine


def _iter_raw_pymupdf(path: Path, need_words: bool, need_text: bool) -> Iterator[_RawPage]:
    pymupdf = _import_pymupdf()
    try:
        doc = pymupdf.open(path)
    except Exception as err:  # FileDataError, RuntimeError selon les versions
        raise PDFParsingError(f"{path.name} : PDF illisible ({err})") from err
    with doc:
        if doc.needs_pass:
            raise PDFParsingError(f"{path.name} : PDF protégé par mot de passe")
        for number, page in enumerate(doc, start=1):
            try:
                words = [tuple(w[:5]) for w in page.get_text("words")] if need_words else []
                text = page.get_text("text") if need_text else ""
            except Exception as err:
                logger.warning("%s p. %d : extraction impossible (%s)", path.name, number, err)
                words, text = [], ""
            yield number, words, text


def _iter_raw_pdfplumber(path: Path, need_words: bool, need_text: bool) -> Iterator[_RawPage]:
    import pdfplumber

    try:
        pdf = pdfplumber.open(path)
    except Exception as err:  # PDFSyntaxError, PdfminerException, PDFPasswordIncorrect...
        raise PDFParsingError(f"{path.name} : PDF illisible ({err})") from err
    with pdf:
        for number, page in enumerate(pdf.pages, start=1):
            try:
                words = (
                    [
                        (w["x0"], w["top"], w["x1"], w["bottom"], w["text"])
                        for w in page.extract_words()
                    ]
                    if need_words
                    else []
                )
                text = (page.extract_text() or "") if need_text else ""
            except Exception as err:
                logger.warning("%s p. %d : extraction impossible (%s)", path.name, number, err)
                words, text = [], ""
            finally:
                page.flush_cache()  # limite la mémoire sur les gros 10-K
            yield number, words, text


# --------------------------------------------------------------------------- #
# API publique
# --------------------------------------------------------------------------- #


def iter_pages(
    path: str | Path,
    *,
    engine: Engine = "auto",
    mode: Mode = "layout",
    skip_empty: bool = True,
    columns: bool = True,
    tables: bool = False,
    doc_name: str | None = None,
) -> Iterator[Page]:
    """Lit un PDF page par page, sans charger tout le document en mémoire.

    Args:
        path: chemin du PDF.
        engine: ``auto`` (PyMuPDF si installé, sinon pdfplumber), ``pymupdf`` ou ``pdfplumber``.
        mode: ``layout`` (lignes reconstruites, recommandé pour les tableaux) ou ``raw``.
        skip_empty: ignore les pages sans texte. Les numéros des autres pages ne changent pas.
        columns: en mode ``layout``, lit les zones à plusieurs colonnes de texte colonne par
            colonne (voir :func:`fri.ingestion.layout.order_blocks`).
        tables: extrait aussi les tableaux de chiffres en lignes x colonnes (``Page.tables``).
        doc_name: nom du document ; par défaut le nom du fichier sans extension
            (ex. ``3M_2018_10K``), comme dans FinanceBench.

    Raises:
        FileNotFoundError: le fichier n'existe pas.
        PDFParsingError: le fichier n'est pas un PDF lisible ou il est chiffré.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF introuvable : {path}")
    if mode not in ("layout", "raw"):
        raise ValueError(f"Mode inconnu : {mode!r} (layout ou raw)")

    backend = _resolve_engine(engine)
    reader = _iter_raw_pymupdf if backend == "pymupdf" else _iter_raw_pdfplumber
    name = doc_name or path.stem
    need_words = mode == "layout" or tables

    for number, words, raw_text in reader(path, need_words, mode == "raw"):
        if mode == "layout":
            raw_text = words_to_text(words, detect_columns=columns)
        page_tables: tuple[Table, ...] = ()
        if tables and words:
            page_tables = tuple(_finalize_table(t, name, number) for t in extract_tables(words))
        page = Page(doc_name=name, page=number, text=clean_text(raw_text), tables=page_tables)
        if page.is_empty:
            logger.debug("%s p. %d : page vide", name, number)
            if skip_empty:
                continue
        yield page


def _finalize_table(table: Table, doc_name: str, page: int) -> Table:
    """Nettoie chaque cellule et rattache le tableau à sa page (pour la citation)."""

    def clean_cells(cells: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(clean_text(c) for c in cells)

    return replace(
        table,
        header=clean_cells(table.header),
        rows=tuple(clean_cells(r) for r in table.rows),
        doc_name=doc_name,
        page=page,
    )


def parse_pdf(
    path: str | Path,
    *,
    engine: Engine = "auto",
    mode: Mode = "layout",
    skip_empty: bool = True,
    strip_boilerplate: bool = False,
    columns: bool = True,
    tables: bool = False,
    doc_name: str | None = None,
    cache_dir: str | Path | None = None,
) -> list[Page]:
    """Retourne une :class:`Page` par page du PDF, en gardant le numéro pour les citations.

    ``strip_boilerplate=True`` retire en plus les en-têtes / pieds de page répétés
    (``Table of Contents``, numéros de page...) via :func:`remove_repeated_lines`.

    ``cache_dir`` : si donné, le résultat est enregistré en JSONL dans ce dossier et relu
    aux appels suivants au lieu de reparser le PDF. La clé du cache dépend du contenu du
    PDF, des options et de la version du parser : changer l'un d'eux invalide le cache.

    Les autres arguments sont décrits dans :func:`iter_pages`.
    """
    path = Path(path)
    options: dict[str, Any] = {
        "mode": mode,
        "skip_empty": skip_empty,
        "strip_boilerplate": strip_boilerplate,
        "columns": columns,
        "tables": tables,
        "doc_name": doc_name or path.stem,
    }
    cache_file: Path | None = None
    if cache_dir is not None:
        if not path.is_file():
            raise FileNotFoundError(f"PDF introuvable : {path}")
        options["engine"] = _resolve_engine(engine)
        cache_file = _cache_file(path, Path(cache_dir), options)
        cached = _read_cache(cache_file)
        if cached is not None:
            logger.info("%s : %d pages lues depuis le cache", path.name, len(cached))
            return cached

    pages = list(
        iter_pages(
            path,
            engine=engine,
            mode=mode,
            skip_empty=skip_empty,
            columns=columns,
            tables=tables,
            doc_name=doc_name,
        )
    )
    if strip_boilerplate:
        pages = remove_repeated_lines(pages)
        if skip_empty:
            pages = [p for p in pages if not p.is_empty]

    n_chars = sum(len(p.text) for p in pages)
    logger.info("%s : %d pages avec texte, %d caractères", path.name, len(pages), n_chars)
    if not pages:
        logger.warning("%s : aucun texte extrait (PDF scanné ? OCR nécessaire)", path.name)
    if cache_file is not None:
        _write_cache(cache_file, pages, options["doc_name"])
    return pages


# --------------------------------------------------------------------------- #
# Cache JSONL
# --------------------------------------------------------------------------- #

# À incrémenter quand le texte produit par le parser change : invalide les anciens caches.
CACHE_VERSION = 2


def _cache_file(path: Path, cache_dir: Path, options: dict[str, Any]) -> Path:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    digest.update(json.dumps({**options, "version": CACHE_VERSION}, sort_keys=True).encode())
    return cache_dir / f"{options['doc_name']}.{digest.hexdigest()[:16]}.jsonl"


def _read_cache(cache_file: Path) -> list[Page] | None:
    if not cache_file.is_file():
        return None
    try:
        with cache_file.open(encoding="utf-8") as f:
            return [Page.from_dict(json.loads(line)) for line in f if line.strip()]
    except (OSError, ValueError, KeyError, TypeError) as err:
        logger.warning("Cache illisible, le PDF sera reparsé : %s (%s)", cache_file.name, err)
        return None


def _write_cache(cache_file: Path, pages: list[Page], doc_name: str) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for page in pages:
            f.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")
    os.replace(tmp, cache_file)  # écriture atomique : jamais de cache à moitié écrit
    for old in cache_file.parent.glob(f"{glob.escape(doc_name)}.*.jsonl"):
        if old != cache_file:
            old.unlink(missing_ok=True)  # ancienne version du même document


_DIGITS_RE = re.compile(r"\d+")


def _line_signature(line: str) -> str:
    """Forme normalisée d'une ligne : 'Page 12 of 160' et 'Page 13 of 160' se ressemblent."""
    return _DIGITS_RE.sub("#", line.strip().lower())


def remove_repeated_lines(
    pages: Sequence[Page],
    *,
    zone: int = 3,
    min_ratio: float = 0.5,
    min_pages: int = 3,
) -> list[Page]:
    """Retire les en-têtes et pieds de page répétés sur la majorité des pages.

    Une ligne est considérée comme du « boilerplate » si, une fois ses chiffres masqués,
    elle apparaît dans les ``zone`` premières ou dernières lignes d'au moins ``min_ratio``
    des pages. Seules ces zones sont nettoyées (au plus un tiers des lignes de chaque bord) :
    le corps de la page n'est jamais modifié.
    Rien n'est fait pour un document de moins de ``min_pages`` pages.
    """
    if len(pages) < min_pages:
        return list(pages)

    def edge_indices(lines: list[str]) -> set[int]:
        n = len(lines)
        k = max(1, min(zone, n // 3))
        return set(range(min(k, n))) | set(range(max(n - k, 0), n))

    counts: Counter[str] = Counter()
    for page in pages:
        lines = page.text.split("\n")
        counts.update({_line_signature(lines[i]) for i in edge_indices(lines) if lines[i]})

    threshold = max(2, min_ratio * len(pages))
    repeated = {sig for sig, count in counts.items() if count >= threshold}
    if not repeated:
        return list(pages)
    logger.debug("Lignes répétées retirées : %s", sorted(repeated))

    cleaned: list[Page] = []
    for page in pages:
        lines = page.text.split("\n")
        drop = {i for i in edge_indices(lines) if _line_signature(lines[i]) in repeated}
        kept = "\n".join(line for i, line in enumerate(lines) if i not in drop)
        cleaned.append(replace(page, text=clean_text(kept)))
    return cleaned


def parse_directory(
    pdf_dir: str | Path,
    pattern: str = "*.pdf",
    **kwargs: Any,
) -> dict[str, list[Page]]:
    """Parse tous les PDF d'un dossier. Un PDF illisible est signalé puis ignoré.

    Retourne ``{doc_name: [Page, ...]}`` trié par nom de document.
    Les ``kwargs`` sont transmis à :func:`parse_pdf`.
    """
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {pdf_dir}")

    documents: dict[str, list[Page]] = {}
    for path in sorted(pdf_dir.glob(pattern)):
        try:
            documents[path.stem] = parse_pdf(path, **kwargs)
        except PDFParsingError as err:
            logger.error("Ignoré : %s", err)
    return documents


# --------------------------------------------------------------------------- #
# Ligne de commande (inspection / débogage)
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extrait le texte des PDF page par page (inspection de l'ingestion)."
    )
    parser.add_argument("path", type=Path, help="un fichier PDF ou un dossier de PDF")
    parser.add_argument("--engine", choices=["auto", "pymupdf", "pdfplumber"], default="auto")
    parser.add_argument("--mode", choices=["layout", "raw"], default="layout")
    parser.add_argument("--keep-empty", action="store_true", help="garder les pages vides")
    parser.add_argument(
        "--strip-boilerplate", action="store_true", help="retirer en-têtes et pieds de page"
    )
    parser.add_argument(
        "--no-columns", action="store_true", help="ne pas lire les colonnes de texte séparément"
    )
    parser.add_argument("--tables", action="store_true", help="extraire les tableaux de chiffres")
    parser.add_argument("--cache-dir", type=Path, help="dossier du cache JSONL des pages")
    parser.add_argument("--show", type=int, metavar="N", help="afficher le texte de la page N")
    parser.add_argument("--jsonl", type=Path, help="écrire toutes les pages dans ce fichier JSONL")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Console Windows (cp1252) : un caractère non affichable ne doit pas faire planter la CLI.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    options: dict[str, Any] = {
        "engine": args.engine,
        "mode": args.mode,
        "skip_empty": not args.keep_empty,
        "strip_boilerplate": args.strip_boilerplate,
        "columns": not args.no_columns,
        "tables": args.tables,
        "cache_dir": args.cache_dir,
    }
    try:
        if args.path.is_dir():
            documents = parse_directory(args.path, **options)
        else:
            documents = {args.path.stem: parse_pdf(args.path, **options)}
    except (FileNotFoundError, NotADirectoryError, PDFParsingError, ImportError) as err:
        print(f"Erreur : {err}", file=sys.stderr)
        return 1

    for name, pages in documents.items():
        n_chars = sum(len(p.text) for p in pages)
        n_tables = sum(len(p.tables) for p in pages)
        summary = f"{name} : {len(pages)} pages, {n_chars:,} caractères"
        print(summary + (f", {n_tables} tableaux" if args.tables else ""))
        if args.show is not None:
            match = next((p for p in pages if p.page == args.show), None)
            print(f"--- p. {args.show} ---\n{match.text if match else '(page absente ou vide)'}")
            for i, table in enumerate(match.tables if match else (), start=1):
                print(f"--- tableau {i} ({len(table.rows)} lignes) ---\n{table.to_markdown()}")

    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl.open("w", encoding="utf-8") as f:
            for pages in documents.values():
                for page in pages:
                    f.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")
        print(f"Pages écrites dans {args.jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
