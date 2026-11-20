# data/

Ce dossier est ignoré par Git (sauf ce fichier et le script) : les PDF et l'index sont trop lourds.

```bash
python data/download_financebench.py --companies 15
```

Après exécution :

```
data/
├── financebench_open_source.jsonl   # 150 questions annotées
├── pdfs/                            # rapports 10-K / 10-Q
├── cache/pages/                     # texte des PDF déjà parsés (généré)
└── index/                           # index ChromaDB + chunks BM25 (généré)
```

Construire l'index : `python -m fri.ingestion.indexer` (voir `docs/retrieval.md`).
