import pytest

from fri.ingestion.chunking import chunk_page, chunk_pages, search_text, split_text
from fri.ingestion.metadata import company_key
from fri.ingestion.pdf_parser import Page
from fri.schemas import DocType

PARAGRAPH = " ".join(f"Sentence number {i} about net sales and margins." for i in range(40))


def test_short_page_is_one_chunk_with_its_metadata():
    page = Page(doc_name="3M_2018_10K", page=42, text="Net sales 32,765 31,657")
    [chunk] = chunk_page(page)
    assert chunk.id == "3M_2018_10K-p42-c0"
    assert chunk.text == "Net sales 32,765 31,657"
    meta = chunk.metadata
    assert (meta.company, meta.year, meta.doc_type, meta.page) == ("3M", 2018, DocType.TEN_K, 42)
    assert meta.doc_name == "3M_2018_10K"


def test_long_page_is_split_under_chunk_size_and_keeps_the_page():
    page = Page(doc_name="AMD_2022_10K", page=7, text="\n\n".join([PARAGRAPH] * 3))
    chunks = chunk_page(page, chunk_size=300, overlap=50)
    assert len(chunks) > 3
    assert all(len(c.text) <= 300 for c in chunks)
    assert all(c.metadata.page == 7 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_no_text_is_lost():
    words = PARAGRAPH.split()
    pieces = split_text(PARAGRAPH, chunk_size=200, overlap=40)
    joined = " ".join(pieces).split()
    assert set(words) <= set(joined)
    assert joined[0] == words[0] and joined[-1] == words[-1]


def test_consecutive_chunks_overlap_without_cutting_words():
    pieces = split_text(PARAGRAPH, chunk_size=200, overlap=60)
    for prev, nxt in zip(pieces, pieces[1:], strict=False):
        first_sentence = nxt.split(". ")[0]
        assert first_sentence in prev  # le début du suivant répète la fin du précédent
    assert all(p.startswith("Sentence") for p in pieces)


def test_table_lines_are_not_cut():
    rows = [f"Line item {i} {1000 + i:,} {2000 + i:,} {3000 + i:,}" for i in range(60)]
    pieces = split_text("\n".join(rows), chunk_size=250, overlap=0)
    lines = {line for p in pieces for line in p.split("\n")}
    assert lines == set(rows)


def test_overlap_zero_means_no_repetition():
    pieces = split_text(PARAGRAPH, chunk_size=200, overlap=0)
    assert sum(len(p) for p in pieces) <= len(PARAGRAPH)


def test_giant_word_is_cut_by_force():
    pieces = split_text("x" * 1000, chunk_size=300, overlap=0)
    assert "".join(pieces) == "x" * 1000
    assert all(len(p) <= 300 for p in pieces)


@pytest.mark.parametrize("size, overlap", [(0, 0), (100, 100), (100, -1)])
def test_bad_settings_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        split_text("abc", chunk_size=size, overlap=overlap)


def test_blank_text_gives_no_chunk():
    assert split_text("  \n\n ") == []


def test_unexpected_doc_name_is_rejected():
    with pytest.raises(ValueError):
        chunk_page(Page(doc_name="rapport", page=1, text="texte"))


def test_quarter_and_earnings_documents():
    q = chunk_page(Page(doc_name="3M_2023Q2_10Q", page=3, text="x"))[0].metadata
    e = chunk_page(Page(doc_name="AMCOR_2023Q4_EARNINGS", page=1, text="x"))[0].metadata
    assert (q.year, q.doc_type) == (2023, DocType.TEN_Q)
    assert e.doc_type == DocType.EARNINGS


def test_chunk_pages_keeps_document_order():
    pages = [Page(doc_name="3M_2018_10K", page=p, text=f"page {p}") for p in (1, 2, 5)]
    assert [c.metadata.page for c in chunk_pages(pages)] == [1, 2, 5]


def test_search_text_adds_company_year_and_type():
    chunk = chunk_page(Page(doc_name="3M_2018_10K", page=1, text="Net sales"))[0]
    assert search_text(chunk) == "3M 2018 10-K\nNet sales"


@pytest.mark.parametrize(
    "a, b",
    [
        ("American Express", "AMERICANEXPRESS"),
        ("Johnson & Johnson", "JOHNSON_JOHNSON"),
        ("Coca-Cola", "COCACOLA"),
        ("Pfizer", "PFIZER"),
    ],
)
def test_company_key_matches_question_and_file_names(a, b):
    assert company_key(a) == company_key(b)
