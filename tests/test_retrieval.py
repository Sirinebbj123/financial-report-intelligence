from fri.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_favors_documents_in_both_rankings(result_factory):
    bm25 = [result_factory("a"), result_factory("b")]
    vector = [result_factory("b"), result_factory("c")]
    fused = reciprocal_rank_fusion([bm25, vector])
    assert fused[0].chunk.id == "b"
    assert {r.chunk.id for r in fused} == {"a", "b", "c"}


def test_rrf_top_n(result_factory):
    fused = reciprocal_rank_fusion([[result_factory(x) for x in "abcd"]], top_n=2)
    assert len(fused) == 2
