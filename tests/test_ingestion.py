import pytest

from fri.ingestion.metadata import parse_doc_name
from fri.schemas import DocType


def test_parse_doc_name_10k():
    assert parse_doc_name("3M_2018_10K") == ("3M", 2018, DocType.TEN_K)


def test_parse_doc_name_with_underscores():
    assert parse_doc_name("AMERICANEXPRESS_2022_10K")[1] == 2022


def test_parse_doc_name_invalid():
    with pytest.raises(ValueError):
        parse_doc_name("rapport.pdf")
