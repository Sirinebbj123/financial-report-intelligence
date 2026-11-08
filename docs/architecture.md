# Architecture

L'agent LangGraph est le centre du système : il reçoit la question depuis l'interface, appelle les outils MCP qui interrogent l'index hybride, puis génère une réponse qui cite la société, l'année et la page.

## Flux

1. **Indexation** (`fri.ingestion`) : chaque page de PDF devient un ou plusieurs chunks qui gardent leurs métadonnées (société, année, type, page).
2. **Recherche hybride** (`fri.retrieval`) : BM25 pour les termes exacts, vecteurs pour le sens, fusion RRF, filtres société / année avant la recherche.
3. **Outils MCP** (`fri.mcp_server`) : `search_filings`, `get_financial_metric`, `compare_years`.
4. **Agent** (`fri.agent`) : routage simple / calcul / comparaison, réponse citée.
5. **Qualité** (`evaluation/`, `finetuning/`) : benchmark FinanceBench ; l'embedding fine-tuné remplace l'original s'il est meilleur.

## Contrats

Les modèles partagés sont dans `src/fri/schemas.py` : `Chunk`, `SearchResult`, `Citation`, `MetricValue`, `YearComparison`, `Answer`.
