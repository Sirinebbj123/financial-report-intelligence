"""Point d'entrée du retrieval : BM25 + vecteurs, filtres métadonnées, fusion RRF.

Construire l'index : ``python -m fri.ingestion.indexer``.
Le charger : ``HybridRetriever.load()`` (c'est ce que font les outils MCP).
Essai : ``python -m fri.retrieval.hybrid "capital expenditure" --company 3M --year 2018``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fri.retrieval.fusion import reciprocal_rank_fusion
from fri.schemas import SearchResult

# reranker(query, results, top_n) -> results (voir fri.retrieval.reranker.Reranker)
RerankFn = Callable[[str, list[SearchResult], int], list[SearchResult]]


class HybridRetriever:
    def __init__(
        self, bm25, vector, reranker: RerankFn | None = None, candidates: int = 20
    ) -> None:
        self.bm25 = bm25
        self.vector = vector
        self.reranker = reranker
        self.candidates = candidates  # passages fusionnés donnés au reranker

    def search(
        self, query: str, company: str | None = None, year: int | None = None, k: int = 8
    ) -> list[SearchResult]:
        """Les ``k`` meilleurs passages ; société et année filtrent *avant* la recherche."""
        filters = {key: v for key, v in {"company": company, "year": year}.items() if v}
        depth = max(k * 2, self.candidates if self.reranker else 0)
        rankings = [
            self.bm25.search(query, k=depth, filters=filters),
            self.vector.search(query, k=depth, filters=filters),
        ]
        if self.reranker is None:
            return reciprocal_rank_fusion(rankings, top_n=k)
        fused = reciprocal_rank_fusion(rankings, top_n=max(k, self.candidates))
        return self.reranker(query, fused, k)

    @classmethod
    def load(
        cls,
        index_dir: str | Path | None = None,
        *,
        use_reranker: bool | None = None,
        embedder=None,
    ) -> HybridRetriever:
        """Charge l'index construit par ``fri.ingestion.indexer`` (BM25 + Chroma)."""
        from fri.config import settings
        from fri.ingestion.indexer import load_chunks, read_manifest
        from fri.retrieval.bm25 import BM25Retriever
        from fri.retrieval.reranker import Reranker
        from fri.retrieval.vector import VectorRetriever, load_embedder

        index_dir = Path(index_dir or settings.index_dir)
        manifest = read_manifest(index_dir)
        model = manifest["embedding_model"]  # le modèle de l'index, pas celui du .env
        if embedder is None:
            embedder = load_embedder(model, manifest.get("query_prefix"))
        bm25 = BM25Retriever(load_chunks(index_dir))
        vector = VectorRetriever(index_dir, model, embedder=embedder)
        if use_reranker is None:
            use_reranker = settings.use_reranker
        reranker = Reranker(settings.reranker_model) if use_reranker else None
        return cls(bm25, vector, reranker=reranker)


def main(argv: list[str] | None = None) -> int:
    """Essai rapide de la recherche sur l'index construit."""
    import argparse

    parser = argparse.ArgumentParser(description="Cherche des passages dans l'index hybride.")
    parser.add_argument("query", help='ex. "capital expenditure"')
    parser.add_argument("--company", help="ex. 3M ou 'American Express'")
    parser.add_argument("--year", type=int)
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--rerank", action="store_true", help="activer le cross-encoder")
    args = parser.parse_args(argv)

    retriever = HybridRetriever.load(use_reranker=args.rerank or None)
    results = retriever.search(args.query, company=args.company, year=args.year, k=args.k)
    if not results:
        print("Aucun passage trouvé.")
    for rank, r in enumerate(results, start=1):
        m = r.chunk.metadata
        text = " ".join(r.chunk.text.split())
        print(f"{rank}. [{m.company}, {m.year}, p. {m.page}] score={r.score:.4f}")
        print(f"   {text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
