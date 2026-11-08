from fri.agent.citations import extract_citations


def test_extract_citations():
    text = "Le CA est de 32,7 Md$ [3M, 2018, p. 42] et 32,1 Md$ [3M, 2017, p. 40]."
    cites = extract_citations(text)
    assert [(c.year, c.page) for c in cites] == [(2018, 42), (2017, 40)]
