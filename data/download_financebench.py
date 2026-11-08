"""Télécharge le jeu FinanceBench (questions + PDF) dans data/.

Rôle 1 (Data & Retrieval).

Usage :
    python data/download_financebench.py --companies 15
"""

from __future__ import annotations

import argparse
from pathlib import Path

DATA_DIR = Path(__file__).parent
REPO_RAW = "https://raw.githubusercontent.com/patronus-ai/financebench/main"
QUESTIONS_URL = f"{REPO_RAW}/data/financebench_open_source.jsonl"
PDF_URL = f"{REPO_RAW}/pdfs/{{doc_name}}.pdf"


def download_questions(dest: Path) -> Path:
    """Télécharge le fichier des 150 questions annotées."""
    # TODO(Rôle 1) : requests.get(QUESTIONS_URL) et écrire dans dest
    raise NotImplementedError


def select_documents(questions_path: Path, n_companies: int) -> list[str]:
    """Choisit les doc_name des n premières sociétés couvertes par les questions."""
    # TODO(Rôle 1)
    raise NotImplementedError


def download_pdfs(doc_names: list[str], dest_dir: Path) -> None:
    """Télécharge chaque PDF s'il n'existe pas déjà."""
    # TODO(Rôle 1)
    raise NotImplementedError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", type=int, default=15)
    args = parser.parse_args()

    questions = download_questions(DATA_DIR / "financebench_open_source.jsonl")
    docs = select_documents(questions, args.companies)
    download_pdfs(docs, DATA_DIR / "pdfs")


if __name__ == "__main__":
    main()
