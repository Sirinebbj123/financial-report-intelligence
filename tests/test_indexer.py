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


# ------------------------------------------------------------------ mise à jour
def _update(tmp_path, pdf_dir, index_dir, **kwargs):
    from fri.ingestion.indexer import update_index

    return update_index(
        pdf_dir, index_dir, cache_dir=tmp_path / "cache", embedder=FakeEmbedder(), **kwargs
    )


def _pages_in_chroma(index_dir):
    from fri.retrieval.vector import open_client

    collection = open_client(index_dir).get_collection("filings")
    records = collection.get(include=["metadatas"])["metadatas"]
    return sorted((r["doc_name"], r["page"]) for r in records)


def test_manifest_records_file_fingerprints(index):
    _, manifest = index
    files = manifest["files"]
    assert set(files) == set(DOCS)
    assert len(files["3M_2018_10K"]["sha256"]) == 64
    assert files["3M_2018_10K"]["chunks"] == 3


def test_update_without_changes_does_nothing(tmp_path, pdf_dir, index):
    index_dir, before = index
    manifest = _update(tmp_path, pdf_dir, index_dir)
    assert manifest["changes"]["added"] == manifest["changes"]["updated"] == []
    assert manifest["changes"]["unchanged"] == sorted(DOCS)
    assert manifest["n_chunks"] == before["n_chunks"]


def test_update_adds_a_new_report(tmp_path, pdf_dir, index):
    index_dir, _ = index
    write_pdf(pdf_dir / "AMD_2022_10K.pdf", ["Net revenue was $23,601 million in 2022."])
    manifest = _update(tmp_path, pdf_dir, index_dir)
    assert manifest["changes"]["added"] == ["AMD_2022_10K"]
    assert manifest["n_documents"] == 3 and manifest["n_chunks"] == 6
    assert read_manifest(index_dir)["documents"] == sorted([*DOCS, "AMD_2022_10K"])
    assert ("AMD_2022_10K", 1) in _pages_in_chroma(index_dir)

    from fri.retrieval.hybrid import HybridRetriever

    retriever = HybridRetriever.load(index_dir, embedder=FakeEmbedder(), use_reranker=False)
    [best] = retriever.search("net revenue", company="AMD", year=2022, k=1)
    assert best.chunk.metadata.doc_name == "AMD_2022_10K"


def test_update_replaces_a_modified_report(tmp_path, pdf_dir, index):
    index_dir, _ = index
    write_pdf(pdf_dir / "3M_2018_10K.pdf", ["Restated: total revenue was $33,000 million."])
    manifest = _update(tmp_path, pdf_dir, index_dir)
    assert manifest["changes"]["updated"] == ["3M_2018_10K"]
    texts = [c.text for c in load_chunks(index_dir) if c.metadata.doc_name == "3M_2018_10K"]
    assert len(texts) == 1 and "33,000" in texts[0]
    assert [p for p in _pages_in_chroma(index_dir) if p[0] == "3M_2018_10K"] == [("3M_2018_10K", 1)]
    assert manifest["n_chunks"] == 3


def test_remove_and_prune(tmp_path, pdf_dir, index):
    index_dir, _ = index
    manifest = _update(tmp_path, pdf_dir, index_dir, remove=["AMERICANEXPRESS_2022_10K"])
    assert manifest["changes"]["removed"] == ["AMERICANEXPRESS_2022_10K"]
    assert {d for d, _ in _pages_in_chroma(index_dir)} == {"3M_2018_10K"}

    (pdf_dir / "3M_2018_10K.pdf").unlink()
    kept = _update(tmp_path, pdf_dir, index_dir)  # sans --prune : gardé, seulement signalé
    assert kept["documents"] == ["3M_2018_10K"]  # le rapport retiré ne revient pas
    assert read_manifest(index_dir)["excluded"] == ["AMERICANEXPRESS_2022_10K"]
    write_pdf(pdf_dir / "AMD_2022_10K.pdf", ["Net revenue was $23,601 million in 2022."])
    pruned = _update(tmp_path, pdf_dir, index_dir, prune=True)
    assert pruned["changes"]["removed"] == ["3M_2018_10K"]
    assert pruned["documents"] == ["AMD_2022_10K"]
    back = _update(tmp_path, pdf_dir, index_dir, docs=["AMERICANEXPRESS_2022_10K"])
    assert back["changes"]["added"] == ["AMERICANEXPRESS_2022_10K"]
    assert read_manifest(index_dir)["excluded"] == []


def test_update_old_index_without_fingerprints(tmp_path, pdf_dir, index):
    index_dir, _ = index
    manifest = read_manifest(index_dir)
    del manifest["files"]
    (index_dir / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    first = _update(tmp_path, pdf_dir, index_dir)  # enregistre les empreintes, rien à recalculer
    assert first["changes"]["updated"] == []
    assert set(read_manifest(index_dir)["files"]) == set(DOCS)
    forced = _update(tmp_path, pdf_dir, index_dir, docs=["3M_2018_10K"])
    assert forced["changes"]["updated"] == ["3M_2018_10K"]
    assert forced["n_chunks"] == 5


def test_update_errors(tmp_path, pdf_dir, index):
    index_dir, _ = index
    with pytest.raises(FileNotFoundError):
        _update(tmp_path, pdf_dir, index_dir, docs=["NOPE_2020_10K"])
    with pytest.raises(ValueError):
        _update(tmp_path, pdf_dir, index_dir, remove=["NOPE_2020_10K"])
    with pytest.raises(FileNotFoundError):
        _update(tmp_path, pdf_dir, tmp_path / "pas-d-index")


def test_cli_update(tmp_path, pdf_dir, index, capsys, monkeypatch):
    from fri.ingestion import indexer

    index_dir, _ = index
    real = indexer.update_index
    monkeypatch.setattr(
        indexer,
        "update_index",
        lambda *a, **k: real(*a, cache_dir=tmp_path / "cache", embedder=FakeEmbedder(), **k),
    )
    write_pdf(pdf_dir / "AMD_2022_10K.pdf", ["Net revenue was $23,601 million in 2022."])
    code = indexer.main(["--pdf-dir", str(pdf_dir), "--index-dir", str(index_dir), "--update"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Ajoutés : AMD_2022_10K" in out
    assert "Redémarrez" in out
