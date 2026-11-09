"""Télécharge le jeu FinanceBench (questions + PDF) dans data/.

Rôle 1 (Data & Retrieval).

Usage :
    python data/download_financebench.py --companies 15
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent
REPO_RAW = "https://raw.githubusercontent.com/patronus-ai/financebench/main"
QUESTIONS_URL = f"{REPO_RAW}/data/financebench_open_source.jsonl"
PDF_URL = f"{REPO_RAW}/pdfs/{{doc_name}}.pdf"
TIMEOUT = 60


def download_questions(dest: Path) -> Path:
    """Télécharge le fichier des 150 questions annotées."""
    if dest.exists():
        print(f"Questions déjà présentes : {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(QUESTIONS_URL, timeout=TIMEOUT)
    response.raise_for_status()
    dest.write_bytes(response.content)
    print(f"Questions téléchargées : {dest}")
    return dest


def load_questions(questions_path: Path) -> list[dict]:
    """Lit le fichier JSONL (une question par ligne)."""
    with questions_path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def select_documents(questions_path: Path, n_companies: int) -> list[str]:
    """Choisit les doc_name des n premières sociétés couvertes par les questions."""
    companies: list[str] = []
    docs: list[str] = []
    for q in load_questions(questions_path):
        company, doc_name = q["company"], q["doc_name"]
        if company not in companies:
            if len(companies) >= n_companies:
                continue
            companies.append(company)
        if doc_name not in docs:
            docs.append(doc_name)
    print(f"{len(companies)} sociétés, {len(docs)} documents sélectionnés")
    return docs


def download_pdfs(doc_names: list[str], dest_dir: Path) -> None:
    """Télécharge chaque PDF s'il n'existe pas déjà."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for i, doc_name in enumerate(doc_names, start=1):
        dest = dest_dir / f"{doc_name}.pdf"
        if dest.exists():
            print(f"[{i}/{len(doc_names)}] déjà présent : {doc_name}")
            continue
        try:
            response = requests.get(PDF_URL.format(doc_name=doc_name), timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as err:
            print(f"[{i}/{len(doc_names)}] ÉCHEC {doc_name} : {err}")
            continue
        dest.write_bytes(response.content)
        print(f"[{i}/{len(doc_names)}] téléchargé : {doc_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", type=int, default=15)
    args = parser.parse_args()

    questions = download_questions(DATA_DIR / "financebench_open_source.jsonl")
    docs = select_documents(questions, args.companies)
    download_pdfs(docs, DATA_DIR / "pdfs")


if __name__ == "__main__":
    main()
