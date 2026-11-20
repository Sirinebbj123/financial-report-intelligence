"""Les outils MCP lisent le vrai index (BM25 + ChromaDB) construit par l'indexeur."""

import pytest

from fri import config
from fri.ingestion.indexer import build_index
from fri.mcp_server import tools
from fri.retrieval import hybrid, vector
from tests.conftest import FakeEmbedder

pytest.importorskip("chromadb")
fitz = pytest.importorskip("fitz")

DOCS = {
    "3M_2018_10K": ["Risk factors.", "Net sales: total revenue was $32,765 million in 2018."],
    "AMERICANEXPRESS_2022_10K": [
        "Card member loans.",
        "Total revenues net of interest expense were $52,862 million.",
    ],
}


@pytest.fixture
def real_index(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for name, pages in DOCS.items():
        doc = fitz.open()
        for text in pages:
            doc.new_page().insert_text((72, 72), text, fontsize=11)
        doc.save(pdf_dir / f"{name}.pdf")
        doc.close()
    index_dir = tmp_path / "index"
    build_index(pdf_dir, index_dir, embedding_model="fake", embedder=FakeEmbedder())

    monkeypatch.setattr(
        config, "settings", config.Settings(index_dir=index_dir, use_reranker=False)
    )
    monkeypatch.setattr(vector, "load_embedder", lambda name, prefix=None: FakeEmbedder())
    tools.set_retriever(None)
    yield index_dir
    tools.set_retriever(None)


def test_get_retriever_loads_the_hybrid_index(real_index):
    assert isinstance(tools.get_retriever(), hybrid.HybridRetriever)


def test_search_filings_reads_the_real_index(real_index):
    [best] = tools.search_filings("total revenue", company="3M", year=2018, k=1)
    assert (best.chunk.metadata.doc_name, best.chunk.metadata.page) == ("3M_2018_10K", 2)


def test_company_names_are_normalized(real_index):
    results = tools.search_filings("total revenues", company="American Express", year=2022)
    assert results and results[0].chunk.metadata.company == "AMERICANEXPRESS"
    assert results[0].chunk.metadata.page == 2


@pytest.mark.parametrize(
    "a, b, same",
    [
        ("3M", "3m", True),
        ("Johnson & Johnson", "JOHNSON_JOHNSON", True),
        ("American Express", "AMERICANEXPRESS", True),
        ("AMD", "3M", False),
    ],
)
def test_same_company(a, b, same):
    assert tools._same_company(a, b) is same


def test_index_without_manifest_is_reported(tmp_path, monkeypatch):
    (tmp_path / "chroma").mkdir()  # index à moitié construit
    monkeypatch.setattr(config, "settings", config.Settings(index_dir=tmp_path))
    tools.set_retriever(None)
    with pytest.raises(RuntimeError, match="indexer"):
        tools.get_retriever()


def test_server_preloads_the_index(real_index, capsys):
    pytest.importorskip("mcp")
    from fri.mcp_server import server

    assert server.preload_index() is True
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout est réservé au protocole MCP
    assert "Index chargé (4 chunks)" in captured.err


def test_server_starts_even_without_index(tmp_path, monkeypatch, capsys):
    pytest.importorskip("mcp")
    from fri.mcp_server import server

    monkeypatch.setattr(config, "settings", config.Settings(index_dir=tmp_path / "absent"))
    tools.set_retriever(None)
    assert server.preload_index() is False
    assert "python -m fri.ingestion.indexer" in capsys.readouterr().err


def test_relative_paths_are_resolved_from_the_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # comme Claude Desktop, qui démarre ailleurs
    assert config.project_path("data/index") == config.PROJECT_ROOT / "data" / "index"
    assert config.project_path(str(tmp_path)) == tmp_path
    monkeypatch.setenv("INDEX_DIR", "data/index")
    assert config.Settings().index_dir.is_absolute()
