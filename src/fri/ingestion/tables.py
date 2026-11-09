"""Extraction structurée des tableaux de chiffres (lignes x colonnes).

Les états financiers d'un 10-K sont des tableaux « libellé + valeurs » ::

    (Millions)                                   2018      2017      2016
    Depreciation and amortization               1,488     1,544     1,474
    Purchases of property, plant and equipment (1,577)   (1,373)   (1,420)

On les reconstruit à partir des lignes visuelles (:func:`fri.ingestion.layout.group_rows`) :
une ligne de tableau = un libellé suivi de valeurs numériques, et les colonnes sont
retrouvées en regroupant les bords droits des nombres (alignés à droite dans les PDF).
Cette approche ne dépend pas des traits du tableau, souvent absents des PDF FinanceBench,
et sort des cellules propres (``1,488``), là où ``page.find_tables()`` de PyMuPDF colle les
mots (``Depreciationandamortization``) sur ces documents.

:func:`parse_number` convertit une cellule en nombre (``(1,577)`` -> ``-1577.0``), ce qui
servira à ``get_financial_metric``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from fri.ingestion.layout import Row, WordBox, group_rows

__all__ = ["Table", "extract_tables", "parse_number", "tables_from_rows"]

# Nombre financier : 1,488 | (1,577) | -23 | 12.5 | 12.5% | $5,363 | 2018
_NUMBER_RE = re.compile(r"^[(\-]?\$?\d(?:[\d,]*\d)?(?:\.\d+)?%?\)?$")
_EMPTY_VALUES = {"—", "–", "-", "−"}  # une cellule vide est souvent un tiret
_YEAR_RE = re.compile(r"^(19|20)\d\d$")

_MIN_NUMERIC_ROWS = 3  # au moins 3 lignes avec 2 valeurs ou plus
_MAX_LABEL_ONLY_RUN = 3  # titres de section ("Cash Flows from ...") tolérés dans un tableau
_COLUMN_TOLERANCE = 1.2  # en hauteurs de mot : écart max entre bords droits d'une colonne
_MIN_COLUMN_SUPPORT = 0.25  # une colonne a des valeurs sur au moins 25 % des lignes


def parse_number(cell: str | None) -> float | None:
    """Convertit une cellule de tableau financier en nombre.

    ``"1,488"`` -> 1488.0 ; ``"(1,577)"`` -> -1577.0 ; ``"$5,363"`` -> 5363.0 ;
    ``"12.5%"`` -> 12.5 ; ``"—"`` ou ``""`` -> None.
    """
    if cell is None:
        return None
    text = cell.strip().replace("$", "").replace(" ", "")
    if not text or text in _EMPTY_VALUES:
        return None
    negative = text.startswith("(") and text.endswith(")") or text.startswith(("-", "−"))
    text = text.strip("()").lstrip("-−").rstrip("%").replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _is_value(token: str) -> bool:
    return bool(_NUMBER_RE.match(token)) or token in _EMPTY_VALUES


@dataclass(frozen=True, slots=True)
class Table:
    """Un tableau de chiffres : en-tête éventuel, puis des lignes ``[libellé, v1, v2, ...]``."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    doc_name: str = ""
    page: int = 0
    n_cols: int = field(init=False)

    def __post_init__(self) -> None:
        widths = [len(self.header)] + [len(r) for r in self.rows]
        object.__setattr__(self, "n_cols", max(widths))

    def to_markdown(self) -> str:
        """Le tableau en Markdown (lisible par un LLM, utilisable dans un chunk)."""

        def line(cells: Sequence[str]) -> str:
            padded = list(cells) + [""] * (self.n_cols - len(cells))
            return "| " + " | ".join(c.replace("|", "/") for c in padded) + " |"

        header = self.header or ("",) * self.n_cols
        out = [line(header), "|" + "---|" * self.n_cols]
        out.extend(line(r) for r in self.rows)
        return "\n".join(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_name": self.doc_name,
            "page": self.page,
            "header": list(self.header),
            "rows": [list(r) for r in self.rows],
            "bbox": list(self.bbox),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Table:
        return cls(
            header=tuple(data["header"]),
            rows=tuple(tuple(r) for r in data["rows"]),
            bbox=tuple(data["bbox"]),  # type: ignore[arg-type]
            doc_name=data.get("doc_name", ""),
            page=data.get("page", 0),
        )


@dataclass
class _ParsedRow:
    words: Row
    label: str
    values: list[tuple[str, float]]  # (texte, bord droit x1)


def _parse_row(row: Row, ref_height: float) -> _ParsedRow:
    """Sépare une ligne en libellé (à gauche) et valeurs numériques (à droite).

    Un nombre collé au libellé (moins d'une hauteur de mot d'écart) en fait partie :
    « December 31 », une note « (1) » ou « allowances of $174 » ne sont pas des valeurs.
    """
    # Fusionne "%" isolé avec le nombre qui précède : "12.5 %" -> "12.5%"
    merged: list[WordBox] = []
    for word in row:
        if word[4] == "%" and merged and _NUMBER_RE.match(merged[-1][4]):
            prev = merged.pop()
            merged.append((prev[0], prev[1], word[2], prev[3], prev[4] + "%"))
        else:
            merged.append(word)

    i = len(merged)
    while i > 0 and (merged[i - 1][4] == "$" or _is_value(merged[i - 1][4])):
        i -= 1
    # Le premier « nombre » trop proche du libellé appartient au libellé.
    while i < len(merged) and i > 0:
        gap = merged[i][0] - merged[i - 1][2]
        if merged[i - 1][4] == "$" or gap >= ref_height:
            break
        i += 1
    values = [(w[4].replace("$", ""), w[2]) for w in merged[i:] if w[4] != "$"]
    label = " ".join(w[4] for w in merged[:i] if w[4] != "$")
    return _ParsedRow(words=row, label=label, values=values)


def _cluster_columns(edges: list[float], tolerance: float) -> list[float]:
    """Regroupe les bords droits des nombres en colonnes ; retourne le bord moyen de chacune."""
    groups: list[list[float]] = []
    for x in sorted(edges):
        if groups and x - groups[-1][-1] <= tolerance:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


def _build_table(block: list[_ParsedRow], ref_height: float) -> Table | None:
    edges = [x for r in block for text, x in r.values if not _YEAR_RE.match(text)]
    if not edges:
        edges = [x for r in block for _, x in r.values]
    columns = _cluster_columns(edges, _COLUMN_TOLERANCE * ref_height)
    # Une vraie colonne a des valeurs sur une bonne partie des lignes ; les autres
    # (numéro de page, nombre isolé dans une phrase) retournent dans le libellé.
    numeric_rows = sum(1 for r in block if r.values)

    def nearest(x: float) -> int:
        return min(range(len(columns)), key=lambda j: abs(columns[j] - x))

    support = [0] * len(columns)
    for r in block:
        for k in {nearest(x) for _, x in r.values}:
            support[k] += 1
    keep = [k for k, n in enumerate(support) if n >= max(2, _MIN_COLUMN_SUPPORT * numeric_rows)]
    if len(keep) < 2:
        return None
    for r in block:
        stray = [t for t, x in r.values if nearest(x) not in keep]
        if stray:
            r.label = " ".join([r.label, *stray]).strip()
            r.values = [(t, x) for t, x in r.values if nearest(x) in keep]
    columns = [columns[k] for k in keep]

    def place(row: _ParsedRow) -> list[str]:
        cells = [""] * len(columns)
        for text, x in row.values:
            k = min(range(len(columns)), key=lambda j: abs(columns[j] - x))
            cells[k] = f"{cells[k]} {text}".strip()
        return cells

    header: tuple[str, ...] = ()
    body = block
    # En-tête : une des deux premières lignes dont toutes les valeurs sont des années.
    for idx, row in enumerate(block[:2]):
        if len(row.values) >= 2 and all(_YEAR_RE.match(t) for t, _ in row.values):
            header = (row.label, *place(row))
            body = block[:idx] + block[idx + 1 :]
            break

    rows = tuple((r.label, *place(r)) for r in body)
    words = [w for r in block for w in r.words]
    bbox = (
        min(w[0] for w in words),
        min(w[1] for w in words),
        max(w[2] for w in words),
        max(w[3] for w in words),
    )
    return Table(header=header, rows=rows, bbox=bbox)


def tables_from_rows(rows: list[Row], ref_height: float) -> list[Table]:
    """Détecte les tableaux de chiffres parmi des lignes visuelles déjà regroupées."""
    parsed = [_parse_row(r, ref_height) for r in rows]
    tables: list[Table] = []
    block: list[_ParsedRow] = []
    label_only = 0

    def flush() -> None:
        nonlocal block
        while block and len(block[-1].values) < 2:
            block.pop()  # pas de titre orphelin ni de numéro de page à la fin
        if sum(1 for r in block if len(r.values) >= 2) >= _MIN_NUMERIC_ROWS:
            table = _build_table(block, ref_height)
            if table is not None:
                tables.append(table)
        block = []

    for row in parsed:
        if row.values:
            block.append(row)
            label_only = 0
        elif block and label_only < _MAX_LABEL_ONLY_RUN:
            block.append(row)
            label_only += 1
        else:
            flush()
            label_only = 0
    flush()
    return tables


def extract_tables(words: list[WordBox], line_tolerance: float = 0.5) -> list[Table]:
    """Tableaux de chiffres d'une page, à partir des boîtes de mots du moteur PDF."""
    rows, ref_height = group_rows(words, line_tolerance)
    return tables_from_rows(rows, ref_height) if rows else []
