"""Tests de la mise en page (colonnes de texte) et de l'extraction des tableaux.

Les pages sont décrites par des boîtes de mots synthétiques (x0, y0, x1, y1, texte) :
aucun PDF n'est nécessaire.
"""

from __future__ import annotations

import pytest

from fri.ingestion.layout import group_rows, order_blocks, words_to_text
from fri.ingestion.tables import Table, extract_tables, parse_number

H = 10.0  # hauteur d'un mot


def line(x: float, y: float, text: str, width: float = 25.0, space: float = 4.0) -> list:
    """Boîtes de mots d'une ligne commençant en x."""
    boxes = []
    for word in text.split():
        boxes.append((x, y, x + width, y + H, word))
        x += width + space
    return boxes


def right_aligned(x1: float, y: float, text: str, width: float = 30.0) -> tuple:
    return (x1 - width, y, x1, y + H, text)


LEFT = [f"left{i} alpha beta gamma delta epsilon zeta" for i in range(8)]
RIGHT = [f"right{i} one two three four five six" for i in range(8)]


def two_column_page(with_title: bool = True) -> list:
    words = []
    y = 50.0
    if with_title:
        words += line(50, 20, "Full width title of the page that spans both columns entirely")
    for left, right in zip(LEFT, RIGHT, strict=True):
        words += line(50, y, left) + line(320, y, right)
        y += 12
    return words


# --------------------------------------------------------------------------- #
# Colonnes de texte
# --------------------------------------------------------------------------- #


def test_two_text_columns_are_read_one_after_the_other():
    text = words_to_text(two_column_page())
    lines = [ln for ln in text.splitlines() if ln]
    assert lines[0].startswith("Full width title")
    assert lines[1:9] == LEFT  # toute la colonne de gauche...
    assert lines[9:17] == RIGHT  # ...puis toute la colonne de droite


def test_columns_can_be_disabled():
    text = words_to_text(two_column_page(), detect_columns=False)
    assert f"{LEFT[0]} {RIGHT[0]}" in text.splitlines()


def test_full_width_sentence_is_not_split():
    # Une phrase pleine largeur n'a que des espaces simples : pas de gouttière.
    words = []
    for i in range(8):
        words += line(50, 50 + 12 * i, f"row{i} " + "word " * 15)
    assert len(order_blocks(*group_rows(words))) == 1


def test_financial_table_is_not_split_into_columns():
    words = []
    for i in range(8):
        y = 50 + 12 * i
        words += line(50, y, f"Line item number {i} of the statement")
        words += [right_aligned(400, y, f"{i},123"), right_aligned(470, y, f"({i},456)")]
    text = words_to_text(words)
    assert "Line item number 3 of the statement 3,123 (3,456)" in text.splitlines()


def test_key_value_table_is_not_split():
    # Nom | fonction : cellules courtes, la correspondance par ligne doit rester.
    words = []
    for i in range(8):
        y = 50 + 12 * i
        words += line(50, y, f"Person{i} Name") + line(300, y, f"Chief Officer {i}")
    assert "Person2 Name Chief Officer 2" in words_to_text(words).splitlines()


def test_group_rows_empty():
    assert group_rows([]) == ([], 0.0)
    assert words_to_text([]) == ""


# --------------------------------------------------------------------------- #
# parse_number
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("1,488", 1488.0),
        ("(1,577)", -1577.0),
        ("$5,363", 5363.0),
        ("12.5%", 12.5),
        ("-23%", -23.0),
        ("0.375", 0.375),
        ("—", None),
        ("", None),
        (None, None),
        ("n/a", None),
    ],
)
def test_parse_number(cell, expected):
    assert parse_number(cell) == expected


# --------------------------------------------------------------------------- #
# Tableaux
# --------------------------------------------------------------------------- #


def cash_flow_words() -> list:
    rows = [
        ("(Millions)", ["2018", "2017", "2016"]),
        ("Cash Flows from Operating Activities", []),
        (
            "Net income including noncontrolling interest",
            ["$", "5,363", "$", "4,869", "$", "5,058"],
        ),
        ("Depreciation and amortization", ["1,488", "1,544", "1,474"]),
        ("Inventories", ["(509)", "(387)", "57"]),
        ("Other — net", ["120", "—", "76"]),
    ]
    words = line(50, 20, "Consolidated Statement of Cash Flows")
    for i, (label, values) in enumerate(rows):
        y = 50 + 12 * i
        words += line(50, y, label)
        numbers = [v for v in values if v != "$"]
        for k, value in enumerate(numbers):
            x1 = 330 + 70 * k
            words.append(right_aligned(x1, y, value))
            if "$" in values:
                words.append((x1 - 60, y, x1 - 52, y + H, "$"))
    words += line(50, 200, "The accompanying notes are an integral part of this statement.")
    return words


def test_extract_cash_flow_table():
    tables = extract_tables(cash_flow_words())
    assert len(tables) == 1
    table = tables[0]
    assert table.header == ("(Millions)", "2018", "2017", "2016")
    assert table.rows[0] == ("Cash Flows from Operating Activities", "", "", "")
    assert table.rows[1] == (
        "Net income including noncontrolling interest",
        "5,363",
        "4,869",
        "5,058",
    )
    assert table.rows[3] == ("Inventories", "(509)", "(387)", "57")
    assert table.rows[4] == ("Other — net", "120", "—", "76")
    assert table.n_cols == 4
    assert parse_number(table.rows[3][1]) == -509.0


def test_number_glued_to_label_stays_in_label():
    words = []
    for i, label in enumerate(["Balance at December 31", "Granted shares note (1)", "Exercised"]):
        y = 50 + 12 * i
        words += line(50, y, label)
        words += [right_aligned(330, y, f"{i + 1},000"), right_aligned(400, y, f"{i + 5}.50")]
    table = extract_tables(words)[0]
    assert [r[0] for r in table.rows] == [
        "Balance at December 31",
        "Granted shares note (1)",
        "Exercised",
    ]
    assert table.n_cols == 3


def test_prose_with_numbers_is_not_a_table():
    words = []
    for i in range(6):
        words += line(
            50, 50 + 12 * i, f"In fiscal 2018 the company employed {i}3,516 people worldwide"
        )
    assert extract_tables(words) == []


def test_table_markdown_and_roundtrip():
    table = Table(
        header=("", "2022", "2021"), rows=(("Revenue", "10", "9"), ("Net | income", "2", ""))
    )
    assert table.to_markdown().splitlines() == [
        "|  | 2022 | 2021 |",
        "|---|---|---|",
        "| Revenue | 10 | 9 |",
        "| Net / income | 2 |  |",
    ]
    assert Table.from_dict(table.to_dict()) == table
