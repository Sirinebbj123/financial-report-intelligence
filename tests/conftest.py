import pytest

from fri.schemas import Chunk, ChunkMetadata, DocType, SearchResult


def make_result(cid: str, score: float = 1.0, page: int = 1) -> SearchResult:
    meta = ChunkMetadata(
        company="3M", year=2018, doc_type=DocType.TEN_K, doc_name="3M_2018_10K", page=page
    )
    return SearchResult(chunk=Chunk(id=cid, text=f"texte {cid}", metadata=meta), score=score)


@pytest.fixture
def result_factory():
    return make_result
