import hashlib
import math

import pytest

from fri.retrieval.bm25 import tokenize
from fri.schemas import Chunk, ChunkMetadata, DocType, SearchResult


def make_result(cid: str, score: float = 1.0, page: int = 1) -> SearchResult:
    meta = ChunkMetadata(
        company="3M", year=2018, doc_type=DocType.TEN_K, doc_name="3M_2018_10K", page=page
    )
    return SearchResult(chunk=Chunk(id=cid, text=f"texte {cid}", metadata=meta), score=score)


@pytest.fixture
def result_factory():
    return make_result


class FakeEmbedder:
    """Sac de mots haché : deux textes qui partagent des mots ont des vecteurs proches."""

    query_prefix = ""
    dim = 64

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in tokenize(text):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v] if any(v) else [1.0 / math.sqrt(self.dim)] * self.dim

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)
