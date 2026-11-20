"""Configuration centrale, lue depuis l'environnement (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Racine du dépôt (là où se trouve pyproject.toml), si le paquet est installé en mode -e.
_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = _ROOT if (_ROOT / "pyproject.toml").is_file() else None


def project_path(value: str) -> Path:
    """Chemin relatif -> relatif à la racine du dépôt (et non au dossier courant).

    Claude Desktop lance le serveur MCP depuis un autre dossier : sans cela,
    ``data/index`` pointerait au mauvais endroit.
    """
    path = Path(value).expanduser()
    if path.is_absolute() or PROJECT_ROOT is None:
        return path
    return PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )
    data_dir: Path = field(default_factory=lambda: project_path(os.getenv("DATA_DIR", "data")))
    index_dir: Path = field(
        default_factory=lambda: project_path(os.getenv("INDEX_DIR", "data/index"))
    )
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "8")))
    chunk_size: int = field(default_factory=lambda: int(os.getenv("CHUNK_SIZE", "800")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "100")))
    use_reranker: bool = field(
        default_factory=lambda: (
            os.getenv("USE_RERANKER", "0").strip().lower() in {"1", "true", "yes", "oui"}
        )
    )
    reranker_model: str = field(
        default_factory=lambda: os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
    )


settings = Settings()
