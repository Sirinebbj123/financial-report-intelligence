"""Extraction du texte des rapports financiers PDF, page par page.

Chaque page du PDF devient un objet :class:`Page` qui garde son numéro (1-indexé).
Ce numéro est la base des citations ``[Société, Année, p. X]`` : il n'est jamais
renuméroté, même quand des pages vides sont ignorées.

Deux moteurs sont pris en charge :

* ``pymupdf`` (par défaut) : rapide (~0,5 s pour un 10-K de 160 pages) ;
* ``pdfplumber`` : plus lent, utilisé en secours si PyMuPDF n'est pas installé.

Deux modes d'extraction :

* ``layout`` (par défaut) : les mots sont regroupés par ligne *visuelle* à partir de
  leurs coordonnées. Les lignes des tableaux financiers restent sur une seule ligne
  (``Depreciation and amortization 1,488 1,544 1,474``) au lieu d'avoir une cellule
  par ligne, ce qui aide beaucoup le chunking, BM25 et l'extraction de métriques ;
* ``raw`` : le texte tel que le renvoie le moteur (ordre du flux PDF).

Correspondance avec FinanceBench : ``evidence_page_num`` est 0-indexé, donc
``Page.page == evidence_page_num + 1`` (voir :attr:`Page.index`).

Usage en ligne de commande ::

    python -m fri.ingestion.pdf_parser data/pdfs/3M_2018_10K.pdf --show 60
    python -m fri.ingestion.pdf_parser data/pdfs --jsonl data/pages.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

Engine = Literal["auto", "pymupdf", "pdfplumber"]
Mode = Literal["layout", "raw"]

# Une "boîte de mot" commune aux deux moteurs : (x0, y0, x1, y1, texte),
# avec y qui croît vers le bas de la page.
WordBox = tuple[float, float, float, float, str]

__all__ = [
    "Page",
    "PDFParsingError",
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
        return asdict(self)


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
# Reconstruction des lignes à partir des coordonnées des mots
# --------------------------------------------------------------------------- #


def words_to_text(
    words: Iterable[WordBox],
    line_tolerance: float = 0.5,
    paragraph_gap: float = 1.2,
) -> str:
    """Reconstruit le texte d'une page ligne visuelle par ligne visuelle.

    Deux mots appartiennent à la même ligne si leurs centres verticaux sont à moins de
    ``line_tolerance`` x la hauteur médiane d'un mot. Un écart vertical entre deux lignes
    supérieur à ``paragraph_gap`` x cette hauteur insère une ligne vide (paragraphe).

    Fonction pure (indépendante du moteur PDF), donc testable sans fichier.
    """
    boxes = [w for w in words if w[4].strip()]
    if not boxes:
        return ""

    heights = [max(w[3] - w[1], 0.1) for w in boxes]
    ref_height = statistics.median(heights)
    tol = line_tolerance * ref_height

    rows: list[list[WordBox]] = []
    row_centers: list[float] = []
    for word in sorted(boxes, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center = (word[1] + word[3]) / 2
        if rows and abs(center - row_centers[-1]) <= tol:
            rows[-1].append(word)
        else:
            rows.append([word])
            row_centers.append(center)

    lines: list[str] = []
    previous_bottom: float | None = None
    for row in rows:
        row.sort(key=lambda w: w[0])
        top = min(w[1] for w in row)
        if previous_bottom is not None and top - previous_bottom > paragraph_gap * ref_height:
            lines.append("")
        lines.append(" ".join(w[4] for w in row))
        previous_bottom = max(w[3] for w in row)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Moteurs d'extraction
# --------------------------------------------------------------------------- #


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


def _iter_raw_pymupdf(path: Path, mode: Mode) -> Iterator[tuple[int, str]]:
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
                if mode == "layout":
                    words = [tuple(w[:5]) for w in page.get_text("words")]
                    text = words_to_text(words)
                else:
                    text = page.get_text("text")
            except Exception as err:
                logger.warning("%s p. %d : extraction impossible (%s)", path.name, number, err)
                text = ""
            yield number, text


def _iter_raw_pdfplumber(path: Path, mode: Mode) -> Iterator[tuple[int, str]]:
    import pdfplumber

    try:
        pdf = pdfplumber.open(path)
    except Exception as err:  # PDFSyntaxError, PdfminerException, PDFPasswordIncorrect...
        raise PDFParsingError(f"{path.name} : PDF illisible ({err})") from err
    with pdf:
        for number, page in enumerate(pdf.pages, start=1):
            try:
                if mode == "layout":
                    words = [
                        (w["x0"], w["top"], w["x1"], w["bottom"], w["text"])
                        for w in page.extract_words()
                    ]
                    text = words_to_text(words)
                else:
                    text = page.extract_text() or ""
            except Exception as err:
                logger.warning("%s p. %d : extraction impossible (%s)", path.name, number, err)
                text = ""
            finally:
                page.flush_cache()  # limite la mémoire sur les gros 10-K
            yield number, text


# --------------------------------------------------------------------------- #
# API publique
# --------------------------------------------------------------------------- #


def iter_pages(
    path: str | Path,
    *,
    engine: Engine = "auto",
    mode: Mode = "layout",
    skip_empty: bool = True,
    doc_name: str | None = None,
) -> Iterator[Page]:
    """Lit un PDF page par page, sans charger tout le document en mémoire.

    Args:
        path: chemin du PDF.
        engine: ``auto`` (PyMuPDF si installé, sinon pdfplumber), ``pymupdf`` ou ``pdfplumber``.
        mode: ``layout`` (lignes reconstruites, recommandé pour les tableaux) ou ``raw``.
        skip_empty: ignore les pages sans texte. Les numéros des autres pages ne changent pas.
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

    for number, raw_text in reader(path, mode):
        page = Page(doc_name=name, page=number, text=clean_text(raw_text))
        if page.is_empty:
            logger.debug("%s p. %d : page vide", name, number)
            if skip_empty:
                continue
        yield page


def parse_pdf(
    path: str | Path,
    *,
    engine: Engine = "auto",
    mode: Mode = "layout",
    skip_empty: bool = True,
    strip_boilerplate: bool = False,
    doc_name: str | None = None,
) -> list[Page]:
    """Retourne une :class:`Page` par page du PDF, en gardant le numéro pour les citations.

    ``strip_boilerplate=True`` retire en plus les en-têtes / pieds de page répétés
    (``Table of Contents``, numéros de page...) via :func:`remove_repeated_lines`.
    Les autres arguments sont décrits dans :func:`iter_pages`.
    """
    pages = list(
        iter_pages(path, engine=engine, mode=mode, skip_empty=skip_empty, doc_name=doc_name)
    )
    if strip_boilerplate:
        pages = remove_repeated_lines(pages)
        if skip_empty:
            pages = [p for p in pages if not p.is_empty]

    n_chars = sum(len(p.text) for p in pages)
    logger.info("%s : %d pages avec texte, %d caractères", Path(path).name, len(pages), n_chars)
    if not pages:
        logger.warning("%s : aucun texte extrait (PDF scanné ? OCR nécessaire)", Path(path).name)
    return pages


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
        print(f"{name} : {len(pages)} pages, {n_chars:,} caractères")
        if args.show is not None:
            match = next((p for p in pages if p.page == args.show), None)
            print(f"--- p. {args.show} ---\n{match.text if match else '(page absente ou vide)'}")

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
