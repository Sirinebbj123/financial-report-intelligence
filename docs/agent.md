# Agent et outil `search_filings`

Ce document décrit la première version de l'agent (tâche 3) : l'outil MCP `search_filings` et une chaîne RAG LangGraph qui répond en citant ses sources `[Société, Année, p. X]`.

## Vue d'ensemble

```
question ──> retrieve (search_filings) ──> answer (LLM + citations) ──> Answer
```

- **`retrieve`** appelle `fri.mcp_server.tools.search_filings(question, company, year, k)`. L'agent et le serveur MCP passent par la même fonction, donc ils trouvent les mêmes passages.
- **`answer`** donne au LLM le `SYSTEM_PROMPT` et les passages, chacun précédé de sa citation (`Passage 1 [3M, 2018, p. 42]`). Le LLM recopie ces citations dans sa réponse.
- Les citations de la réponse sont relues par `extract_citations`, puis filtrées par `keep_valid_citations` : une citation qui ne correspond à aucun passage fourni (page inventée) est retirée, et les doublons sont fusionnés.
- Si aucun passage n'est trouvé, l'agent répond qu'il n'a rien trouvé, sans appeler le LLM.

## Utilisation

```python
from fri.agent.graph import ask

answer = ask("What was 3M's total revenue in 2018?", company="3M", year=2018)
print(answer.answer)       # "... $32,765 million [3M, 2018, p. 42]"
print(answer.citations)    # [Citation(company='3M', year=2018, page=42, doc_name='3M_2018_10K')]
```

Le LLM est choisi dans `.env` (`LLM_PROVIDER` = `openai`, `groq`, `mistral` ou `ollama`, et `LLM_MODEL`). Voir `fri/agent/llm.py`. On peut aussi passer un modèle LangChain directement : `ask(question, llm=mon_modele)`.

## Le retriever est remplaçable

Tant que l'index (chunking + Chroma + BM25, rôle 1) n'est pas prêt, les outils tournent sur un retriever en mémoire avec quelques passages de démo (`fri/mcp_server/demo.py`).

```python
from fri.mcp_server import tools
from fri.mcp_server.demo import demo_retriever

tools.set_retriever(demo_retriever())   # démo / tests
tools.set_retriever(None)               # revenir au vrai index
```

Quand `fri.ingestion.indexer` sera terminé, il restera à compléter `_load_index_retriever()` dans `tools.py` pour renvoyer `HybridRetriever(bm25, vector)`. L'agent, le serveur MCP et les tests ne changent pas.

`search_filings` refiltre toujours les résultats par société (sans tenir compte des majuscules) et par année : un passage d'une autre société ne peut pas sortir, même si le retriever filtre mal.

## Démo MCP

```bash
pip install "mcp>=1.2,<2"
python -m fri.mcp_server.server --demo     # passages de démo, sans index
```

Pour tester avec MCP Inspector :

```bash
npx @modelcontextprotocol/inspector python -m fri.mcp_server.server --demo
```

Dans Claude Desktop, ajouter dans `claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "financial-report-intelligence": {
      "command": "python",
      "args": ["-m", "fri.mcp_server.server", "--demo"]
    }
  }
}
```

Attention : le serveur utilise `FastMCP`, qui a été renommé dans `mcp` 2.x. D'où la contrainte `mcp>=1.2,<2` dans `requirements.txt`.

## Tests

`tests/test_mcp_search.py` et `tests/test_agent_graph.py` tournent sans index ni clé API : le retriever de démo remplace l'index et `FakeListChatModel` (LangChain) remplace le LLM.

Ce qui est vérifié : filtres société / année, garde-fou contre un retriever qui filtre mal, entrées invalides, message clair quand l'index manque, réponse JSON du serveur MCP, citations valides gardées, citations inventées retirées, doublons fusionnés, pas d'appel au LLM sans passage, contenu du prompt.

## Prochaine étape (tâche 4)

- `get_financial_metric` : `search_filings` puis extraction de la valeur par le LLM (sortie structurée `MetricValue`).
- Routage `simple | calcul | comparaison` dans le graphe, avec `compare_years` pour les comparaisons.
