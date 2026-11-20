# Index et recherche hybride

Cette partie transforme les PDF en passages (« chunks ») et retrouve les plus utiles pour une question, avec leur page pour la citation `[Société, Année, p. X]`.

```
PDF ─► pages (pdf_parser) ─► chunks (chunking) ─► chunks.jsonl ─► BM25 (en mémoire)
                                              └─► embeddings bge-small ─► ChromaDB
question ─► BM25 + vecteurs (filtrés société / année) ─► fusion RRF ─► (reranker) ─► passages
```

## Construire l'index

```bash
python data/download_financebench.py --companies 15
python -m fri.ingestion.indexer                         # tous les PDF de data/pdfs
python -m fri.ingestion.indexer --limit 3               # essai rapide sur 3 PDF
python -m fri.ingestion.indexer --docs 3M_2018_10K AMD_2022_10K
```

Le premier lancement télécharge `BAAI/bge-small-en-v1.5` (~130 Mo). Compter quelques minutes sur CPU pour une dizaine de rapports (environ 1 000 chunks par 10-K). Le texte des PDF est mis en cache dans `data/cache/pages/` : relancer ne reparse pas les PDF.

Chaque lancement **reconstruit l'index de zéro**. Contenu de `data/index/` :

| Fichier | Rôle |
|---|---|
| `chroma/` | collection ChromaDB `filings` : embeddings, texte et métadonnées de chaque chunk |
| `chunks.jsonl` | tous les chunks ; relus au chargement pour reconstruire BM25 (quelques secondes) |
| `manifest.json` | modèle d'embeddings, préfixe des questions, taille des chunks, documents indexés. Écrit en dernier : sans lui, l'index est considéré comme absent |

## Mettre à jour l'index

Pas besoin de tout reconstruire pour ajouter, remplacer ou retirer un rapport :

```bash
python -m fri.ingestion.indexer --update                      # PDF nouveaux ou modifiés
python -m fri.ingestion.indexer --remove PFIZER_2021_10K      # retirer un rapport
```

Détails : [`index-update.md`](index-update.md).

## Chunks et métadonnées (`fri.ingestion.chunking`)

- `chunk_page(page, chunk_size=800, overlap=100)` : un chunk ne dépasse jamais une page, donc sa page est toujours la bonne page à citer.
- Découpe d'abord entre paragraphes, puis lignes, puis phrases, puis mots. Les lignes de tableau du parser (`Net sales 32,765 31,657`) restent entières.
- Deux chunks qui se suivent partagent jusqu'à 100 caractères (des lignes ou phrases entières).
- Métadonnées déduites du nom du PDF : `3M_2018_10K` → société `3M`, année `2018`, type `10-K`, plus `doc_name` et `page`.
- Identifiant stable : `3M_2018_10K-p42-c0`.
- `search_text(chunk)` ajoute un en-tête `3M 2018 10-K` au texte **indexé** (BM25 et embeddings), pas au texte cité.

## Recherche (`fri.retrieval`)

| Module | Ce qu'il fait |
|---|---|
| `bm25.py` | `BM25Retriever` (rank_bm25) : termes exacts (`capex`, `FY2022`, `32,765`). Mots vides anglais retirés |
| `vector.py` | `VectorRetriever` : ChromaDB (distance cosinus) + sentence-transformers. Les questions reçoivent le préfixe BGE `Represent this sentence for searching relevant passages: ` |
| `filters.py` | filtres `company` / `year` communs aux deux, appliqués **avant** le classement (`where` de Chroma) |
| `fusion.py` | fusion RRF : `score = Σ 1 / (60 + rang)` |
| `reranker.py` | cross-encoder `BAAI/bge-reranker-base` sur les 20 meilleurs candidats ; désactivé par défaut (`USE_RERANKER=1`) |
| `hybrid.py` | `HybridRetriever.search(query, company, year, k)` et `HybridRetriever.load()` |

La société est comparée sous forme normalisée (`company_key`) : `American Express`, `americanexpress` et `AMERICANEXPRESS` désignent la même société, tout comme `Johnson & Johnson` et `JOHNSON_JOHNSON`.

```python
from fri.retrieval.hybrid import HybridRetriever

retriever = HybridRetriever.load()            # lit data/index
for r in retriever.search("capital expenditure", company="3M", year=2018, k=5):
    print(r.chunk.metadata.page, round(r.score, 4), r.chunk.text[:80])
```

En ligne de commande :

```bash
python -m fri.retrieval.hybrid "capital expenditure" --company 3M --year 2018
python -m fri.retrieval.hybrid "total revenue" --company "American Express" -k 3 --rerank
```

`HybridRetriever` a la même interface que le retriever de démo des outils MCP (`search(query, company, year, k)`) : il suffit de le renvoyer dans `_load_index_retriever()` de `fri/mcp_server/tools.py` pour que l'agent et le serveur MCP lisent le vrai index.

## Réglages (`.env`)

| Variable | Défaut | Note |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | utilisé à l'indexation ; la recherche reprend le modèle écrit dans `manifest.json` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `100` | en caractères ; réindexer après un changement |
| `USE_RERANKER` | `0` | `1` pour activer le cross-encoder (~1 Go, plus lent sur CPU) |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | |

## Premier essai sur de vraies données

10 rapports 10-K de FinanceBench (3M 2018 et 2022, AMD, American Express, Boeing, Coca-Cola, J&J, PepsiCo 2022, Pfizer 2021, Verizon 2022) : 2 086 pages, **10 840 chunks**. Lecture des PDF, découpage et écriture dans Chroma en 20 s (avec un faux modèle d'embeddings, donc sans le temps du vrai modèle), chargement de l'index en 0,6 s.

Sur les 41 questions FinanceBench de ces rapports, **BM25 seul** (filtre société + année) trouve une page de preuve dans les 5 premiers résultats pour 17 % des questions, et dans les 8 premiers pour 24 %. Les questions FinanceBench sont longues et formulées en phrases, ce qui pénalise BM25 : c'est la recherche vectorielle qui doit faire la différence. Le score de l'hybride avec bge-small reste à mesurer avec `evaluation/retrieval_eval.py` (le modèle n'a pas pu être téléchargé pendant cet essai).

## Tests

`tests/test_chunking.py`, `tests/test_retrieval.py`, `tests/test_indexer.py` : PDF générés à la volée, faux modèle d'embeddings et faux cross-encoder, donc aucun téléchargement. `tests/test_indexer.py` construit un vrai index Chroma à partir de PDF générés et le relit.
