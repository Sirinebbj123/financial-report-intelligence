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
└── index/                           # index vectoriel + BM25 (généré)
```
