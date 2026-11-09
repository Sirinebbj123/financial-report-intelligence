"""Tests de l'extraction PDF page par page (fri.ingestion.pdf_parser).

Les PDF de test sont générés à la volée avec PyMuPDF : aucun fichier binaire n'est
commité et les tests ne dépendent pas du réseau. Le dernier test compare l'extraction
aux pages de preuve de FinanceBench ; il ne tourne que si les données sont téléchargées.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fri.ingestion.pdf_parser import (
    Page,
    PDFParsingError,
    clean_text,
    iter_pages,
    parse_directory,
    parse_pdf,
    remove_repeated_lines,
    words_to_text,
)

DATA_DIR = Path(__file__).parents[1] / "data"


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #


def test_page_is_one_indexed_and_exposes_financebench_index():
    page = Page(doc_name="3M_2018_10K", page=60, text="Cash flow")
    assert page.index == 59  # evidence_page_num de FinanceBench
    assert not page.is_empty
    assert page.to_dict() == {"doc_name": "3M_2018_10K", "page": 60, "text": "Cash flow"}


def test_page_rejects_zero_or_negative_number():
    with pytest.raises(ValueError):
        Page(doc_name="x", page=0, text="")


def test_page_is_empty_for_whitespace():
    assert Page(doc_name="x", page=1, text=" \n ").is_empty


# --------------------------------------------------------------------------- #
# clean_text
# --------------------------------------------------------------------------- #


def test_clean_text_normalizes_unicode_and_spaces():
    raw = "Total revenue  of ﬁscal 2022\x00 \n  Net   income\t\t$ 5,363 "
    assert clean_text(raw) == "Total revenue of fiscal 2022\nNet income $ 5,363"


def test_clean_text_removes_soft_hyphen_and_zero_width():
    assert clean_text("non­controlling​ interest﻿") == "noncontrolling interest"


def test_clean_text_collapses_blank_lines_and_trims_edges():
    assert clean_text("\n \nA\n\n \n\nB\r\nC\n\n") == "A\n\nB\nC"


def test_clean_text_empty():
    assert clean_text("  \n\t ") == ""


# --------------------------------------------------------------------------- #
# words_to_text (reconstruction des lignes, sans PDF)
# --------------------------------------------------------------------------- #


def test_words_to_text_rebuilds_table_rows():
    # Une ligne de tableau dont les cellules ont des hauteurs légèrement différentes,
    # et des mots fournis dans le désordre.
    words = [
        (300, 101, 330, 111, "1,488"),
        (10, 100, 120, 110, "Depreciation"),
        (125, 100, 150, 110, "and"),
        (155, 100, 240, 110, "amortization"),
        (350, 100.5, 380, 110.5, "1,544"),
        (10, 114, 80, 124, "Inventories"),
        (300, 114, 330, 124, "(509)"),
    ]
    assert words_to_text(words) == ("Depreciation and amortization 1,488 1,544\nInventories (509)")


def test_words_to_text_inserts_paragraph_break_on_large_gap():
    words = [(10, 100, 50, 110, "Item"), (10, 112, 50, 122, "one"), (10, 160, 50, 170, "Two")]
    assert words_to_text(words) == "Item\none\n\nTwo"


def test_words_to_text_ignores_blank_words():
    assert words_to_text([(0, 0, 1, 1, " "), (0, 0, 1, 1, "")]) == ""
    assert words_to_text([]) == ""


# --------------------------------------------------------------------------- #
# remove_repeated_lines
# --------------------------------------------------------------------------- #


def _doc(texts: list[str]) -> list[Page]:
    return [Page("ACME_2022_10K", i, t) for i, t in enumerate(texts, start=1)]


def test_remove_repeated_lines_strips_headers_and_page_numbers():
    bodies = [f"Section {c}\nRevenue grew\nmargins improved\nOutlook {c}" for c in "ABCDEF"]
    pages = _doc([f"Table of Contents\nPage {i} of 6\n{b}\n{i}" for i, b in enumerate(bodies, 1)])
    cleaned = remove_repeated_lines(pages)
    assert [p.text for p in cleaned] == bodies
    assert [p.page for p in cleaned] == [p.page for p in pages]


def test_remove_repeated_lines_keeps_body_lines():
    # "Table of Contents" se répète mais au milieu de la page : ce n'est pas un en-tête.
    body = "l1\nl2\nl3\nl4\nTable of Contents\nl6\nl7\nl8\nl9"
    pages = _doc([body] * 5)
    assert remove_repeated_lines(pages)[0].text.count("Table of Contents") == 1


def test_remove_repeated_lines_skips_short_documents():
    pages = _doc(["Header\nA\nx\ny", "Header\nB\nz\nw"])
    assert remove_repeated_lines(pages) == pages


# --------------------------------------------------------------------------- #
# Extraction sur de vrais PDF générés
# --------------------------------------------------------------------------- #

ENGINES = ["pymupdf", "pdfplumber"]


def _require(engine: str) -> None:
    pytest.importorskip("pymupdf")  # nécessaire pour générer les PDF de test
    if engine == "pdfplumber":
        pytest.importorskip("pdfplumber")


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Rapport factice de 4 pages : texte, tableau, page blanche, ligature."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()

    page = doc.new_page()
    page.insert_text((72, 72), "Table of Contents")
    page.insert_text((72, 100), "ACME Corp annual report 2022")
    page.insert_text((300, 780), "1")

    page = doc.new_page()
    page.insert_text((72, 72), "Table of Contents")
    page.insert_text((72, 100), "Consolidated Statement of Cash Flows")
    page.insert_text((72, 120), "Depreciation and amortization")
    page.insert_text((400, 120), "1,488")
    page.insert_text((470, 120), "1,544")
    page.insert_text((72, 135), "Inventories")
    page.insert_text((400, 135), "(509)")
    page.insert_text((470, 135), "(387)")
    page.insert_text((300, 780), "2")

    doc.new_page()  # page 3 blanche (comme une page scannée sans OCR)

    page = doc.new_page()
    page.insert_text((72, 72), "Table of Contents")
    page.insert_text((72, 100), "Risk factors and net income")
    page.insert_text((300, 780), "4")

    path = tmp_path / "ACME_2022_10K.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize("engine", ENGINES)
def test_parse_pdf_keeps_page_numbers_and_skips_blank_page(sample_pdf, engine):
    _require(engine)
    pages = parse_pdf(sample_pdf, engine=engine)
    assert [p.page for p in pages] == [1, 2, 4]  # la page 3 est vide, pas de renumérotation
    assert {p.doc_name for p in pages} == {"ACME_2022_10K"}
    assert "ACME Corp annual report 2022" in pages[0].text
    assert "Risk factors and net income" in pages[2].text


@pytest.mark.parametrize("engine", ENGINES)
def test_parse_pdf_layout_mode_keeps_table_rows_together(sample_pdf, engine):
    _require(engine)
    text = parse_pdf(sample_pdf, engine=engine)[1].text
    assert "Depreciation and amortization 1,488 1,544" in text.splitlines()
    assert "Inventories (509) (387)" in text.splitlines()


@pytest.mark.parametrize("engine", ENGINES)
def test_parse_pdf_raw_mode_returns_same_words(sample_pdf, engine):
    _require(engine)
    layout = parse_pdf(sample_pdf, engine=engine)[1].text
    raw = parse_pdf(sample_pdf, engine=engine, mode="raw")[1].text
    assert sorted(raw.split()) == sorted(layout.split())


def test_parse_pdf_keep_empty_pages(sample_pdf):
    _require("pymupdf")
    pages = parse_pdf(sample_pdf, skip_empty=False)
    assert [p.page for p in pages] == [1, 2, 3, 4]
    assert pages[2].is_empty


def test_parse_pdf_strip_boilerplate(sample_pdf):
    _require("pymupdf")
    pages = parse_pdf(sample_pdf, strip_boilerplate=True)
    assert all("Table of Contents" not in p.text for p in pages)
    assert pages[0].text == "ACME Corp annual report 2022"  # numéro de page "1" retiré aussi


def test_parse_pdf_custom_doc_name_and_str_path(sample_pdf):
    _require("pymupdf")
    pages = parse_pdf(str(sample_pdf), doc_name="ACME_2022Q4_10Q")
    assert pages[0].doc_name == "ACME_2022Q4_10Q"


def test_iter_pages_is_lazy(sample_pdf):
    _require("pymupdf")
    iterator = iter_pages(sample_pdf)
    assert next(iterator).page == 1


def test_parse_pdf_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_pdf(tmp_path / "absent.pdf")


def test_parse_pdf_rejects_unknown_mode_and_engine(sample_pdf):
    _require("pymupdf")
    with pytest.raises(ValueError):
        parse_pdf(sample_pdf, mode="ocr")
    with pytest.raises(ValueError):
        parse_pdf(sample_pdf, engine="tesseract")


@pytest.mark.parametrize("engine", ENGINES)
def test_parse_pdf_corrupted_file(tmp_path, engine):
    _require(engine)
    bad = tmp_path / "BAD_2022_10K.pdf"
    bad.write_bytes(b"ceci n'est pas un PDF")
    with pytest.raises(PDFParsingError):
        parse_pdf(bad, engine=engine)


def test_parse_pdf_encrypted_file(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    path = tmp_path / "SECRET_2022_10K.pdf"
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    with pytest.raises(PDFParsingError, match="mot de passe"):
        parse_pdf(path, engine="pymupdf")


def test_parse_directory_skips_unreadable_pdf(sample_pdf, caplog):
    _require("pymupdf")
    (sample_pdf.parent / "BAD_2022_10K.pdf").write_bytes(b"pas un PDF")
    docs = parse_directory(sample_pdf.parent)
    assert list(docs) == ["ACME_2022_10K"]
    assert "BAD_2022_10K.pdf" in caplog.text


def test_parse_directory_missing_dir(tmp_path):
    with pytest.raises(NotADirectoryError):
        parse_directory(tmp_path / "absent")


def test_cli_writes_jsonl(sample_pdf, tmp_path, capsys):
    _require("pymupdf")
    from fri.ingestion.pdf_parser import main

    out = tmp_path / "pages.jsonl"
    assert main([str(sample_pdf), "--show", "2", "--jsonl", str(out)]) == 0
    assert "Depreciation and amortization 1,488 1,544" in capsys.readouterr().out
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["page"] for r in rows] == [1, 2, 4]


def test_cli_missing_file_returns_error(tmp_path):
    from fri.ingestion.pdf_parser import main

    assert main([str(tmp_path / "absent.pdf")]) == 1


# --------------------------------------------------------------------------- #
# Validation sur FinanceBench (seulement si les données sont téléchargées)
# --------------------------------------------------------------------------- #


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def test_financebench_evidence_is_on_cited_page():
    """La page de preuve FinanceBench (0-indexée) doit être notre page index + 1."""
    pytest.importorskip("pymupdf")
    questions_path = DATA_DIR / "financebench_open_source.jsonl"
    pdf_dir = DATA_DIR / "pdfs"
    if not questions_path.exists() or not pdf_dir.is_dir():
        pytest.skip("Données FinanceBench absentes (python data/download_financebench.py)")

    questions = [json.loads(line) for line in questions_path.read_text("utf-8").splitlines()]
    available = {p.stem for p in pdf_dir.glob("*.pdf")}
    evidences = [
        (q["doc_name"], e) for q in questions if q["doc_name"] in available for e in q["evidence"]
    ][:30]
    if not evidences:
        pytest.skip("Aucun PDF FinanceBench téléchargé")

    cache: dict[str, dict[int, Page]] = {}
    for doc_name, evidence in evidences:
        if doc_name not in cache:
            cache[doc_name] = {p.page: p for p in parse_pdf(pdf_dir / f"{doc_name}.pdf")}
        page = cache[doc_name].get(evidence["evidence_page_num"] + 1)
        assert page is not None, f"{doc_name} p. {evidence['evidence_page_num'] + 1} vide"
        expected = _tokens(evidence["evidence_text"])
        coverage = len(expected & _tokens(page.text)) / max(len(expected), 1)
        assert coverage > 0.9, f"{doc_name} p. {page.page} : couverture {coverage:.0%}"
