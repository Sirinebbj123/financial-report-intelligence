"""Configuration centrale, lue depuis l'environnement (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))
    index_dir: Path = field(default_factory=lambda: Path(os.getenv("INDEX_DIR", "data/index")))
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "8")))


settings = Settings()
