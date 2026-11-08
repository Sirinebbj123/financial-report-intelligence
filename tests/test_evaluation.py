from evaluation.retrieval_eval import mean_reciprocal_rank, page_hit, recall_at_k


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], {"b", "z"}, k=2) == 0.5


def test_mrr():
    assert mean_reciprocal_rank([(["a", "b"], {"b"}), (["c"], {"c"})]) == 0.75


def test_page_hit():
    assert page_hit([3, 7, 9], [9], k=3)
    assert not page_hit([3, 7, 9], [9], k=2)
