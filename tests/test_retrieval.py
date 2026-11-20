import pytest

from fri.ingestion.chunking import search_text
from fri.retrieval.bm25 import BM25Retriever, tokenize
from fri.retrieval.filters import matches, normalize_filters
from fri.retrieval.fusion import reciprocal_rank_fusion
from fri.retrieval.hybrid import HybridRetriever
from fri.retrieval.reranker import Reranker, rerank
from fri.schemas import Chunk, ChunkMetadata, DocType, SearchResult
from tests.conftest import FakeEmbedder


def make_chunk(cid: str, text: str, company="3M", year=2018, page=1) -> Chunk:
    meta = ChunkMetadata(
        company=company,
        year=year,
        doc_type=DocType.TEN_K,
        doc_name=f"{company}_{year}_10K",
        page=page,
    )
    return Chunk(id=cid, text=text, metadata=meta)


CHUNKS = [
    make_chunk("3m-18-rev", "Net sales total revenue was $32,765 million", page=42),
    make_chunk("3m-18-capex", "Purchases of property, plant and equipment (capex) 1,577", page=58),
    make_chunk("3m-18-risk", "Risk factors: foreign currency exchange rates", page=12),
    make_chunk("3m-17-rev", "Net sales total revenue was $31,657 million", year=2017, page=40),
    make_chunk(
        "amex-22-rev",
        "Total revenues net of interest expense $52,862 million",
        company="AMERICANEXPRESS",
        year=2022,
        page=50,
    ),
]


# --------------------------------------------------------------------------- #
# Fusion RRF
# --------------------------------------------------------------------------- #


def test_rrf_favors_documents_in_both_rankings(result_factory):
    bm25 = [result_factory("a"), result_factory("b")]
    vector = [result_factory("b"), result_factory("c")]
    fused = reciprocal_rank_fusion([bm25, vector])
    assert fused[0].chunk.id == "b"
    assert {r.chunk.id for r in fused} == {"a", "b", "c"}


def test_rrf_top_n(result_factory):
    fused = reciprocal_rank_fusion([[result_factory(x) for x in "abcd"]], top_n=2)
    assert len(fused) == 2


def test_rrf_score_formula(result_factory):
    fused = reciprocal_rank_fusion([[result_factory("a")], [result_factory("a")]], k=60)
    assert fused[0].score == pytest.approx(2 / 61)
    assert fused[0].source == "hybrid"


# --------------------------------------------------------------------------- #
# Filtres et BM25
# --------------------------------------------------------------------------- #


def test_tokenize_keeps_numbers_and_drops_stopwords():
    assert tokenize("What was the FY2022 revenue of $32,765.5 million?") == [
        "fy2022",
        "revenue",
        "32,765.5",
        "million",
    ]


def test_normalize_filters():
    assert normalize_filters({"company": "American Express", "year": 2022}) == {
        "company_key": "americanexpress",
        "year": 2022,
    }
    assert normalize_filters({"company": " ", "year": None}) == {}
    assert normalize_filters(None) == {}
    with pytest.raises(ValueError):
        normalize_filters({"sector": "tech"})


def test_matches_uses_normalized_company():
    meta = CHUNKS[4].metadata
    assert matches(meta, normalize_filters({"company": "American Express"}))
    assert not matches(meta, normalize_filters({"company": "American Express", "year": 2021}))


def test_bm25_finds_exact_terms():
    results = BM25Retriever(CHUNKS).search("capex property plant equipment", k=3)
    assert results[0].chunk.id == "3m-18-capex"
    assert results[0].source == "bm25"


def test_bm25_filters_company_and_year():
    bm25 = BM25Retriever(CHUNKS)
    results = bm25.search("total revenue", k=5, filters={"company": "3m", "year": 2017})
    assert [r.chunk.id for r in results] == ["3m-17-rev"]
    results = bm25.search("total revenue", k=5, filters={"company": "American Express"})
    assert [r.chunk.id for r in results] == ["amex-22-rev"]


def test_bm25_ignores_chunks_without_common_words():
    assert BM25Retriever(CHUNKS).search("goodwill impairment", k=5) == []
    assert BM25Retriever(CHUNKS).search("the of", k=5) == []


def test_bm25_needs_chunks():
    with pytest.raises(ValueError):
        BM25Retriever([])


# --------------------------------------------------------------------------- #
# Recherche vectorielle (ChromaDB, faux modèle d'embeddings)
# --------------------------------------------------------------------------- #


@pytest.fixture
def vector(tmp_path):
    pytest.importorskip("chromadb")
    from fri.retrieval.vector import VectorRetriever

    retriever = VectorRetriever(tmp_path, "fake", embedder=FakeEmbedder())
    retriever.add(CHUNKS, batch_size=2)
    return retriever


def test_vector_search_returns_chunks_with_metadata(vector):
    assert len(vector) == len(CHUNKS)
    results = vector.search("capex purchases of property", k=2)
    assert results[0].chunk == CHUNKS[1]
    assert results[0].source == "vector"
    assert results[0].score > results[1].score


def test_vector_search_filters_with_where(vector):
    results = vector.search("total revenue", k=5, filters={"company": "3M", "year": 2017})
    assert [r.chunk.id for r in results] == ["3m-17-rev"]
    results = vector.search("total revenue", k=5, filters={"company": "American Express"})
    assert {r.chunk.metadata.company for r in results} == {"AMERICANEXPRESS"}


def test_vector_add_twice_does_not_duplicate(vector):
    vector.add(CHUNKS)
    assert len(vector) == len(CHUNKS)


def test_vector_reset_empties_the_collection(vector, tmp_path):
    from fri.retrieval.vector import VectorRetriever

    fresh = VectorRetriever(
        tmp_path, "fake", embedder=FakeEmbedder(), client=vector.client, reset=True
    )
    assert len(fresh) == 0
    assert fresh.search("revenue") == []


def test_bge_query_prefix():
    from fri.retrieval.vector import BGE_QUERY_PREFIX, default_query_prefix

    assert default_query_prefix("BAAI/bge-small-en-v1.5") == BGE_QUERY_PREFIX
    assert default_query_prefix("sentence-transformers/all-MiniLM-L6-v2") == ""


# --------------------------------------------------------------------------- #
# HybridRetriever et reranker
# --------------------------------------------------------------------------- #


class RecordingRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, k=8, filters=None):
        self.calls.append({"query": query, "k": k, "filters": filters})
        return self.results[:k]


def as_results(*chunks, source="x"):
    return [SearchResult(chunk=c, score=1.0, source=source) for c in chunks]


def test_hybrid_passes_filters_and_fuses():
    bm25 = RecordingRetriever(as_results(CHUNKS[0], CHUNKS[1]))
    vec = RecordingRetriever(as_results(CHUNKS[1], CHUNKS[2]))
    results = HybridRetriever(bm25, vec).search("revenue", company="3M", year=2018, k=2)
    assert [r.chunk.id for r in results] == ["3m-18-capex", "3m-18-rev"]
    assert bm25.calls == [{"query": "revenue", "k": 4, "filters": {"company": "3M", "year": 2018}}]
    assert vec.calls[0]["filters"] == {"company": "3M", "year": 2018}


def test_hybrid_without_filters():
    bm25 = RecordingRetriever([])
    HybridRetriever(bm25, RecordingRetriever([])).search("revenue")
    assert bm25.calls[0]["filters"] == {}


class FakeCrossEncoder:
    """Note = nombre de fois où le mot 'capex' apparaît."""

    def predict(self, pairs):
        return [text.lower().count("capex") for _, text in pairs]


def test_rerank_reorders_and_cuts():
    results = as_results(CHUNKS[0], CHUNKS[1], CHUNKS[2])
    reranked = rerank("capex", results, top_n=2, model=FakeCrossEncoder())
    assert reranked[0].chunk.id == "3m-18-capex"
    assert len(reranked) == 2
    assert reranked[0].source == "rerank"
    assert rerank("capex", [], model=FakeCrossEncoder()) == []


def test_hybrid_with_reranker_gets_more_candidates():
    bm25 = RecordingRetriever(as_results(*CHUNKS))
    vec = RecordingRetriever(as_results(*CHUNKS))
    hybrid = HybridRetriever(bm25, vec, reranker=Reranker(model=FakeCrossEncoder()), candidates=10)
    results = hybrid.search("capex", k=1)
    assert bm25.calls[0]["k"] == 10
    assert [r.chunk.id for r in results] == ["3m-18-capex"]


def test_search_text_is_what_bm25_sees():
    # La société n'est pas dans le texte du chunk, seulement dans l'en-tête indexé.
    assert "AMERICANEXPRESS" in search_text(CHUNKS[4])
    results = BM25Retriever(CHUNKS).search("americanexpress revenues", k=1)
    assert results[0].chunk.id == "amex-22-rev"
