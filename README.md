# Financial Report Intelligence

Assistant RAG + LLM qui répond à des questions financières sur les rapports annuels (10-K, 10-Q) du jeu de données [FinanceBench](https://github.com/patronus-ai/financebench), **cite la page source** et **compare les chiffres d'une société entre deux années**.

## Fonctionnalités

| Exigence | Notre réponse |
|---|---|
| RAG, métadonnées, citations | Ingestion PDF page par page, métadonnées société / année / type / page, réponses citées `[Société, Année, p. X]` |
| Tool Calling / MCP | Serveur MCP : `search_filings`, `get_financial_metric`, `compare_years` |
| LangChain / LangGraph | LangChain pour le retrieval, LangGraph pour l'agent (routage simple / calcul / comparaison) |
| Benchmarking | Retrieval : Recall@k, MRR, page hit rate. Génération : exactitude, fidélité, citations correctes |
| Interface Web | FastAPI + Streamlit (ou Next.js) |
| Fine-tuning (optionnel) | Fine-tuning d'un modèle d'embeddings (bge-small) sur FinanceBench |

## Architecture

```
PDF FinanceBench ──> ingestion (pages, chunks, métadonnées) ──> index vectoriel + BM25
                                                                       │
Question (web/API) ──> agent LangGraph ──> outils MCP ──> retrieval hybride (RRF)
                              │
                              └──> réponse + citations [Société, Année, p. X]
```

Détails : [`docs/architecture.md`](docs/architecture.md).

## Structure du dépôt

```
financial-report-intelligence/
├── README.md
├── pyproject.toml / requirements.txt
├── .env.example              # clés API (jamais le vrai .env)
├── .github/                  # CI + modèle de PR
├── data/                     # ignoré par Git (PDF), script de téléchargement
├── src/fri/
│   ├── schemas.py            # contrats partagés : Chunk, SearchResult, Answer...
│   ├── config.py
│   ├── ingestion/            # Rôle 1 : parsing PDF, chunking, métadonnées, index
│   ├── retrieval/            # Rôle 1 : BM25 + vectoriel + fusion RRF + reranker
│   ├── agent/                # Rôle 2 : graphe LangGraph, prompts, citations
│   ├── mcp_server/           # Rôle 2 : search_filings, get_financial_metric, compare_years
│   └── api/                  # Rôle 4 : FastAPI
├── evaluation/               # Rôle 3 : benchmark retrieval + génération
├── finetuning/               # Rôle 3 : fine-tuning embeddings
├── web/                      # Rôle 4 : interface
├── notebooks/                # exploration
├── tests/                    # tests unitaires
└── docs/                     # architecture, rapport, décisions
```

## Répartition des rôles

| Rôle | Membre | Dossiers |
|---|---|---|
| 1. Data & Retrieval | Maryem | `src/fri/ingestion/`, `src/fri/retrieval/` |
| 2. Agent & MCP | Sirine | `src/fri/agent/`, `src/fri/mcp_server/` |
| 3. Évaluation & Fine-tuning | Membre 3 | `evaluation/`, `finetuning/` |
| 4. API, Web & DevOps | Membre 4 | `src/fri/api/`, `web/`, `.github/`, `Dockerfile` |

## Installation

```bash
git clone https://github.com/Sirinebbj123/financial-report-intelligence.git
cd financial-report-intelligence
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env    # puis renseigner vos clés API
python data/download_financebench.py --companies 15
```

## Lancer

```bash
python -m fri.ingestion.indexer          # construit l'index
uvicorn fri.api.main:app --reload        # API sur http://localhost:8000
streamlit run web/app.py                 # interface
python -m fri.mcp_server.server          # serveur MCP (stdio)
pytest                                   # tests
```

## Workflow Git

1. **`main` protégée** : pas de push direct, une PR + 1 approbation + CI verte.
2. **Une branche par tâche** : `feat/ingestion-pdf`, `feat/mcp-compare-years`, `fix/citation-pages`, `docs/rapport-eval`.
3. **Conventional Commits** : `feat(retrieval): add BM25 + RRF fusion`, `test(mcp): cover get_financial_metric`, `docs: update README setup`.
4. **Une issue par tâche**, liée à la PR (`Closes #12`), suivie dans GitHub Projects.
5. **Tags par jalon** : `v0.1-mvp`, `v0.2-eval`, `v1.0-final`.

Ne jamais commiter les PDF ni le fichier `.env`.
