"""Recherche vectorielle (ChromaDB + sentence-transformers).

Les embeddings sont calculés par nous (pas par Chroma) avec le même modèle à
l'indexation et à la recherche. Le modèle est remplaçable (``embedder=...``) : les
tests utilisent un faux modèle, sans téléchargement.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from fri.ingestion.chunking import search_text
from fri.ingestion.metadata import company_key
from fri.retrieval.filters import normalize_filters
from fri.schemas import Chunk, ChunkMetadata, DocType, SearchResult

logger = logging.getLogger(__name__)

COLLECTION = "filings"
BATCH_SIZE = 256

# Les modèles BGE anglais conseillent ce préfixe pour les questions (pas pour les passages).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def default_query_prefix(model_name: str) -> str:
    name = model_name.lower()
    return BGE_QUERY_PREFIX if "bge" in name and "-en" in name else ""


class SentenceTransformerEmbedder:
    """Embeddings normalisés (cosinus) avec sentence-transformers, chargé à la demande."""

    def __init__(self, model_name: str, query_prefix: str | None = None) -> None:
        self.model_name = model_name
        self.query_prefix = (
            default_query_prefix(model_name) if query_prefix is None else query_prefix
        )
        self._model: Any = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.model.encode(
            list(texts),
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode(self.query_prefix + text, normalize_embeddings=True)
        return vector.tolist()


def load_embedder(model_name: str, query_prefix: str | None = None) -> Embedder:
    return SentenceTransformerEmbedder(model_name, query_prefix)


def chunk_to_record(chunk: Chunk) -> dict[str, Any]:
    """Métadonnées Chroma : seulement des str / int (Chroma n'accepte pas les enums)."""
    m = chunk.metadata
    return {
        "company": m.company,
        "company_key": company_key(m.company),
        "year": m.year,
        "doc_type": m.doc_type.value,
        "doc_name": m.doc_name,
        "page": m.page,
    }


def record_to_chunk(chunk_id: str, text: str, record: dict[str, Any]) -> Chunk:
    metadata = ChunkMetadata(
        company=record["company"],
        year=int(record["year"]),
        doc_type=DocType(record["doc_type"]),
        doc_name=record["doc_name"],
        page=int(record["page"]),
    )
    return Chunk(id=chunk_id, text=text, metadata=metadata)


def to_where(normalized: dict[str, Any]) -> dict[str, Any] | None:
    """Filtres normalisés -> clause ``where`` de Chroma."""
    clauses = [{key: value} for key, value in normalized.items()]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def open_client(index_dir: str | Path) -> Any:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.PersistentClient(
        path=str(Path(index_dir) / "chroma"),
        settings=ChromaSettings(anonymized_telemetry=False),  # rien n'est envoyé à Chroma
    )


class VectorRetriever:
    def __init__(
        self,
        index_dir: str | Path,
        embedding_model: str,
        *,
        embedder: Embedder | None = None,
        client: Any = None,
        collection: str = COLLECTION,
        reset: bool = False,
    ) -> None:
        self.index_dir = Path(index_dir)
        self.embedding_model = embedding_model
        self.embedder = embedder or load_embedder(embedding_model)
        self.client = client or open_client(self.index_dir)
        if reset and collection in {getattr(c, "name", c) for c in self.client.list_collections()}:
            self.client.delete_collection(collection)
        # embedding_function=None : Chroma ne doit jamais calculer d'embeddings lui-même.
        self.collection = self.client.get_or_create_collection(
            collection, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )

    def __len__(self) -> int:
        return self.collection.count()

    def add(self, chunks: Sequence[Chunk], batch_size: int = BATCH_SIZE) -> None:
        """Ajoute (ou remplace, même id) des chunks dans la collection.

        Affiche l'avancement après chaque paquet (le calcul peut durer plusieurs minutes).
        """
        total = len(chunks)
        start_time = time.perf_counter()
        for start in range(0, total, batch_size):
            batch = list(chunks[start : start + batch_size])
            self.collection.upsert(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[chunk_to_record(c) for c in batch],
                embeddings=self.embedder.embed_documents([search_text(c) for c in batch]),
            )
            done = start + len(batch)
            elapsed = time.perf_counter() - start_time
            remaining = elapsed / done * (total - done)
            logger.info(
                "Embeddings : %d/%d chunks (%d %%), %.0f s écoulées, ~%.0f s restantes",
                done,
                total,
                done * 100 // total,
                elapsed,
                remaining,
            )

    def search(self, query: str, k: int = 8, filters: dict | None = None) -> list[SearchResult]:
        """Les ``k`` chunks les plus proches ; filtre société / année avec ``where``."""
        if not query.strip() or k < 1 or len(self) == 0:
            return []
        found = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=min(k, len(self)),
            where=to_where(normalize_filters(filters)),
            include=["documents", "metadatas", "distances"],
        )
        return [
            SearchResult(
                chunk=record_to_chunk(cid, text, record), score=1.0 - distance, source="vector"
            )
            for cid, text, record, distance in zip(
                found["ids"][0],
                found["documents"][0],
                found["metadatas"][0],
                found["distances"][0],
                strict=True,
            )
        ]
