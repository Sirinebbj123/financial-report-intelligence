from fri.schemas import Citation


def test_citation_format():
    assert str(Citation(company="3M", year=2018, page=42)) == "[3M, 2018, p. 42]"
