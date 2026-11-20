"""Indexation de bout en bout : PDF générés -> index -> recherche."""

import json

import pytest

from fri.ingestion.indexer import CHUNKS, MANIFEST, build_index, load_chunks, read_manifest
from tests.conftest import FakeEmbedder

pytest.importorskip("chromadb")
fitz = pytest.importorskip("fitz")

DOCS = {
    "3M_2018_10K": [
        "Risk factors: competition and foreign currency.",
        "Net sales: total revenue was $32,765 million in 2018.",
        "Purchases of property, plant and equipment 1,577",
    ],
    "AMERICANEXPRESS_2022_10K": [
        "Card member loans and receivables.",
        "Total revenues net of interest expense were $52,862 million.",
    ],
}


def write_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


@pytest.fixture
def pdf_dir(tmp_path):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    for name, pages in DOCS.items():
        write_pdf(folder / f"{name}.pdf", pages)
    return folder


@pytest.fixture
def index(tmp_path, pdf_dir):
    index_dir = tmp_path / "index"
    manifest = build_index(
        pdf_dir,
        index_dir,
        embedding_model="fake",
        cache_dir=tmp_path / "cache",
        embedder=FakeEmbedder(),
    )
    return index_dir, manifest


def test_build_index_writes_chunks_chroma_and_manifest(index):
    index_dir, manifest = index
    assert (index_dir / CHUNKS).is_file() and (index_dir / "chroma").is_dir()
    saved = json.loads((index_dir / MANIFEST).read_text(encoding="utf-8"))
    assert saved == manifest
    assert manifest["embedding_model"] == "fake"
    assert manifest["documents"] == sorted(DOCS)
    assert manifest["n_chunks"] == 5
    chunks = load_chunks(index_dir)
    assert {(c.metadata.doc_name, c.metadata.page) for c in chunks} == {
        ("3M_2018_10K", 1),
        ("3M_2018_10K", 2),
        ("3M_2018_10K", 3),
        ("AMERICANEXPRESS_2022_10K", 1),
        ("AMERICANEXPRESS_2022_10K", 2),
    }


def test_loaded_retriever_finds_the_right_page(index):
    from fri.retrieval.hybrid import HybridRetriever

    retriever = HybridRetriever.load(index[0], embedder=FakeEmbedder(), use_reranker=False)
    [best] = retriever.search("total revenue", company="3M", year=2018, k=1)
    assert (best.chunk.metadata.doc_name, best.chunk.metadata.page) == ("3M_2018_10K", 2)
    assert best.source == "hybrid"
    results = retriever.search("total revenues", company="American Express", year=2022, k=5)
    assert results and {r.chunk.metadata.company for r in results} == {"AMERICANEXPRESS"}


def test_rebuild_replaces_the_previous_index(index, pdf_dir, tmp_path):
    from fri.retrieval.hybrid import HybridRetriever

    index_dir, _ = index
    manifest = build_index(
        pdf_dir, index_dir, embedding_model="fake", docs=["3M_2018_10K"], embedder=FakeEmbedder()
    )
    assert manifest["documents"] == ["3M_2018_10K"]
    retriever = HybridRetriever.load(index_dir, embedder=FakeEmbedder(), use_reranker=False)
    assert len(retriever.vector) == 3
    assert retriever.search("total revenues", company="American Express") == []


def test_badly_named_pdf_is_skipped(pdf_dir, tmp_path):
    write_pdf(pdf_dir / "rapport.pdf", ["Total revenue"])
    manifest = build_index(
        pdf_dir, tmp_path / "idx", embedding_model="fake", embedder=FakeEmbedder()
    )
    assert "rapport" not in manifest["documents"]
    assert manifest["n_documents"] == 2


def test_missing_documents_are_reported(pdf_dir, tmp_path):
    with pytest.raises(FileNotFoundError, match="NIKE_2018_10K"):
        build_index(pdf_dir, tmp_path / "idx", docs=["NIKE_2018_10K"], embedder=FakeEmbedder())


def test_read_manifest_without_index(tmp_path):
    with pytest.raises(FileNotFoundError, match="indexer"):
        read_manifest(tmp_path)


def test_command_line_search(index, monkeypatch, capsys):
    from fri import config
    from fri.retrieval import hybrid, vector

    monkeypatch.setattr(config, "settings", config.Settings(index_dir=index[0], use_reranker=False))
    monkeypatch.setattr(vector, "load_embedder", lambda name, prefix=None: FakeEmbedder())
    assert hybrid.main(["total revenue", "--company", "3M", "--year", "2018", "-k", "1"]) == 0
    out = capsys.readouterr().out
    assert "1. [3M, 2018, p. 2]" in out and "$32,765 million" in out
