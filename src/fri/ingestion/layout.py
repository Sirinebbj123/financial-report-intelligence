"""Reconstruction de la mise en page à partir des coordonnées des mots.

Fonctions pures, indépendantes du moteur PDF (PyMuPDF ou pdfplumber) : elles prennent
des « boîtes de mots » ``(x0, y0, x1, y1, texte)`` et sont donc testables sans fichier.

* :func:`group_rows` regroupe les mots en lignes visuelles (les lignes des tableaux
  financiers restent entières) ;
* :func:`order_blocks` détecte les pages à plusieurs colonnes de texte et renvoie les
  lignes dans l'ordre de lecture (colonne de gauche entière, puis colonne de droite) ;
* :func:`words_to_text` assemble le tout en texte.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence

# (x0, y0, x1, y1, texte), avec y qui croît vers le bas de la page.
WordBox = tuple[float, float, float, float, str]
Row = list[WordBox]

__all__ = ["Row", "WordBox", "group_rows", "order_blocks", "row_text", "words_to_text"]

# Réglages de la détection de colonnes (en multiples de la hauteur médiane d'un mot).
_MIN_GUTTER = 1.0  # largeur minimale de l'espace vide entre deux colonnes
_MIN_COLUMN_ROWS = 6  # une colonne de texte fait au moins 6 lignes
_MIN_WORDS_PER_LINE = 6  # une ligne de texte courant contient plusieurs mots
_MIN_FILLED_RATIO = 0.6  # part des lignes qui remplissent la largeur de la colonne
_FILLED_WIDTH = 0.75  # une ligne "remplie" couvre au moins 75 % de la largeur
_MIN_ALPHA_RATIO = 0.7  # part des mots alphabétiques : exclut les colonnes de chiffres
_MAX_DEPTH = 4  # 2 à 4 colonnes au plus par zone


def row_text(row: Sequence[WordBox]) -> str:
    return " ".join(w[4] for w in row)


def group_rows(words: Iterable[WordBox], line_tolerance: float = 0.5) -> tuple[list[Row], float]:
    """Regroupe les mots par ligne visuelle, de haut en bas puis de gauche à droite.

    Deux mots sont sur la même ligne si leurs centres verticaux sont à moins de
    ``line_tolerance`` x la hauteur médiane d'un mot. Retourne ``(lignes, hauteur médiane)``.
    """
    boxes = [w for w in words if w[4].strip()]
    if not boxes:
        return [], 0.0
    ref_height = statistics.median(max(w[3] - w[1], 0.1) for w in boxes)
    tol = line_tolerance * ref_height

    rows: list[Row] = []
    centers: list[float] = []
    for word in sorted(boxes, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center = (word[1] + word[3]) / 2
        if rows and abs(center - centers[-1]) <= tol:
            rows[-1].append(word)
        else:
            rows.append([word])
            centers.append(center)
    for row in rows:
        row.sort(key=lambda w: w[0])
    return rows, ref_height


# --------------------------------------------------------------------------- #
# Détection des colonnes de texte
# --------------------------------------------------------------------------- #


def _blocks_gutter(row: Row, x: float, min_gap: float) -> bool:
    """Vrai si la ligne empêche une gouttière en ``x`` : un mot la traverse, ou les mots
    de part et d'autre sont trop proches (simple espace entre deux mots d'une phrase)."""
    left_edge = max((w[2] for w in row if w[2] <= x), default=None)
    right_edge = min((w[0] for w in row if w[0] >= x), default=None)
    if any(w[0] < x < w[2] for w in row):
        return True
    return left_edge is not None and right_edge is not None and right_edge - left_edge < min_gap


def _is_text_column(parts: list[Row]) -> bool:
    """Vrai si ``parts`` ressemble à une colonne de texte courant (et pas à des chiffres)."""
    lines = [p for p in parts if p]
    if len(lines) < _MIN_COLUMN_ROWS:
        return False
    words = [w[4] for line in lines for w in line]
    if len(words) / len(lines) < _MIN_WORDS_PER_LINE:
        return False  # cellules courtes : tableau clé / valeur, pas une colonne de texte
    alpha = sum(any(c.isalpha() for c in word) for word in words)
    if alpha / len(words) < _MIN_ALPHA_RATIO:
        return False
    # Du texte courant remplit la largeur de sa colonne ; les cellules d'un tableau non.
    x0 = min(line[0][0] for line in lines)
    width = max(line[-1][2] for line in lines) - x0
    filled = sum(1 for line in lines if line[-1][2] - x0 >= _FILLED_WIDTH * width)
    return filled / len(lines) >= _MIN_FILLED_RATIO


def _find_split(rows: list[Row], ref_height: float) -> tuple[int, int, float] | None:
    """Cherche la plus longue suite de lignes coupées par une même gouttière verticale.

    Retourne ``(début, fin, x)`` de la meilleure zone à deux colonnes, ou ``None``.
    """
    min_gap = _MIN_GUTTER * ref_height
    candidates: set[float] = set()
    for row in rows:
        for left, right in zip(row, row[1:], strict=False):
            if right[0] - left[2] >= min_gap:
                candidates.add(round((left[2] + right[0]) / 2))
    best: tuple[int, int, float] | None = None
    for x in sorted(candidates):
        start = 0
        while start < len(rows):
            if _blocks_gutter(rows[start], x, min_gap):
                start += 1
                continue
            end = start
            while end < len(rows) and not _blocks_gutter(rows[end], x, min_gap):
                end += 1
            run = rows[start:end]
            if len(run) >= _MIN_COLUMN_ROWS and (best is None or end - start > best[1] - best[0]):
                left = [[w for w in r if w[2] <= x] for r in run]
                right = [[w for w in r if w[0] >= x] for r in run]
                both = sum(1 for lp, rp in zip(left, right, strict=True) if lp and rp)
                if both >= len(run) / 2 and _is_text_column(left) and _is_text_column(right):
                    best = (start, end, float(x))
            start = end
    return best


def order_blocks(rows: list[Row], ref_height: float, _depth: int = 0) -> list[list[Row]]:
    """Découpe les lignes en blocs dans l'ordre de lecture.

    Une zone à plusieurs colonnes de texte est lue colonne par colonne : toute la colonne
    de gauche, puis celle de droite (récursivement, pour 3 colonnes ou plus). Les tableaux
    de chiffres ne sont jamais découpés : leurs colonnes de droite ne sont pas du texte.
    """
    if _depth >= _MAX_DEPTH or len(rows) < _MIN_COLUMN_ROWS:
        return [rows] if rows else []
    split = _find_split(rows, ref_height)
    if split is None:
        return [rows]
    start, end, x = split
    run = rows[start:end]
    left = [p for p in ([w for w in r if w[2] <= x] for r in run) if p]
    right = [p for p in ([w for w in r if w[0] >= x] for r in run) if p]
    blocks: list[list[Row]] = []
    for part in (rows[:start], left, right, rows[end:]):
        blocks.extend(order_blocks(part, ref_height, _depth + 1))
    return blocks


def words_to_text(
    words: Iterable[WordBox],
    line_tolerance: float = 0.5,
    paragraph_gap: float = 1.2,
    detect_columns: bool = True,
) -> str:
    """Reconstruit le texte d'une page ligne visuelle par ligne visuelle.

    Un écart vertical supérieur à ``paragraph_gap`` x la hauteur médiane d'un mot insère
    une ligne vide (paragraphe), de même que le passage d'une colonne à la suivante.
    ``detect_columns=False`` désactive la lecture colonne par colonne.
    """
    rows, ref_height = group_rows(words, line_tolerance)
    if not rows:
        return ""
    blocks = order_blocks(rows, ref_height) if detect_columns else [rows]

    lines: list[str] = []
    for block in blocks:
        if lines:
            lines.append("")
        previous_bottom: float | None = None
        for row in block:
            top = min(w[1] for w in row)
            if previous_bottom is not None and top - previous_bottom > paragraph_gap * ref_height:
                lines.append("")
            lines.append(row_text(row))
            previous_bottom = max(w[3] for w in row)
    return "\n".join(lines)
