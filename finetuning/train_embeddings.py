"""Fine-tuning du modèle d'embeddings sur FinanceBench."""

from __future__ import annotations


def build_pairs():
    """Construit les paires (question, passage de la page de preuve)."""
    # TODO(Rôle 3)
    raise NotImplementedError


def train(base_model: str = "BAAI/bge-small-en-v1.5", output_dir: str = "finetuning/models"):
    # TODO(Rôle 3) : SentenceTransformer + MultipleNegativesRankingLoss
    raise NotImplementedError


if __name__ == "__main__":
    train()
