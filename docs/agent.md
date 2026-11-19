# Agent et outils MCP

Ce document décrit l'agent LangGraph et les 3 outils MCP : `search_filings` (tâche 3), `get_financial_metric` et `compare_years` avec le routage simple / calcul / comparaison (tâche 4). Toutes les réponses citent leurs sources `[Société, Année, p. X]`.

## Vue d'ensemble

```
question ──> router ──> simple | calcul ──> retrieve (search_filings) ──> answer (LLM + citations)
                   └──> comparaison ──> compare (compare_years) ──(échec)──> retrieve ──> answer
```

- **`router`** classe la question par règles, sans appel au LLM (`classify_question`) :
  deux années citées → `comparaison` ; un mot de calcul (ratio, marge, %, taux, moyenne…) → `calcul` ; sinon `simple`. On peut forcer la route : `ask(question, route="calcul")`.

- **`retrieve`** appelle `fri.mcp_server.tools.search_filings(question, company, year, k)`. L'agent et le serveur MCP passent par la même fonction, donc ils trouvent les mêmes passages.
- **`answer`** donne au LLM le `SYSTEM_PROMPT` et les passages, chacun précédé de sa citation (`Passage 1 [3M, 2018, p. 42]`). Le LLM recopie ces citations dans sa réponse.
- Les citations de la réponse sont relues par `extract_citations`, puis filtrées par `keep_valid_citations` : une citation qui ne correspond à aucun passage fourni (page inventée) est retirée, et les doublons sont fusionnés.
- Si aucun passage n'est trouvé, l'agent répond qu'il n'a rien trouvé, sans appeler le LLM.
- Route **`calcul`** : même chemin, mais le prompt demande en plus les valeurs utilisées (avec leur source), le calcul étape par étape, puis le résultat.
- Route **`comparaison`** : le nœud `compare` lit les années dans la question (regex), demande au LLM la société et la métrique (JSON), puis appelle `compare_years`. La réponse est rédigée par le code, pas par le LLM, pour que les chiffres soient exacts : « total revenue de 3M : 31 657 USD millions en 2017 [3M, 2017, p. 40], contre 32 765 USD millions en 2018 [3M, 2018, p. 42]. Écart : +1 108 USD millions (+3,5 %). » Si une étape échoue (société inconnue, valeur introuvable, unités différentes), l'agent retombe sur le RAG classique.

## `get_financial_metric` et `compare_years`

```python
from fri.mcp_server import tools

m = tools.get_financial_metric("3M", 2018, "total revenue")
# MetricValue(value=32765.0, unit='USD millions', citation=[3M, 2018, p. 42])

c = tools.compare_years("3M", "total revenue", 2017, 2018)
# YearComparison(delta=1108.0, pct_change=3.5, ...)
```

1. `search_filings(metric, company, year)` trouve les passages de la bonne société et de la bonne année.
2. Un **extracteur** lit la valeur (`fri/agent/metrics.py`) :
   - `LLMMetricExtractor` (par défaut) : le LLM répond en JSON `{"value": 32765, "unit": "USD millions", "passage": 1}`. La valeur est convertie en millions de dollars ; `null` si elle n'est pas dans les passages.
   - `RegexMetricExtractor` : premier montant « $X million / billion » trouvé. Il sert à la démo et aux tests hors ligne, pas en production.
3. La citation est celle du passage indiqué par l'extracteur.

Garde-fous : `MetricNotFoundError` si aucun passage ou aucune valeur ; réponse JSON du LLM invalide ou numéro de passage hors limites = valeur introuvable ; `compare_years` refuse deux années identiques et deux unités différentes. `year_a` est l'année de référence : `delta = valeur(year_b) - valeur(year_a)`.


## Utilisation

```python
from fri.agent.graph import ask

answer = ask("What was 3M's total revenue in 2018?", company="3M", year=2018)
print(answer.answer)       # "... $32,765 million [3M, 2018, p. 42]"
print(answer.citations)    # [Citation(company='3M', year=2018, page=42, doc_name='3M_2018_10K')]
```

Le LLM est choisi dans `.env` (`LLM_PROVIDER` = `openai`, `groq`, `mistral` ou `ollama`, et `LLM_MODEL`). Voir `fri/agent/llm.py`. On peut aussi passer un modèle LangChain directement : `ask(question, llm=mon_modele)`.

## Le retriever est remplaçable

Tant que l'index (chunking + Chroma + BM25, rôle 1) n'est pas prêt, les outils tournent sur un retriever en mémoire avec quelques passages de démo (`fri/mcp_server/demo.py`). De même, l'extracteur de valeurs se remplace avec `tools.set_metric_extractor(...)`.

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
python -m fri.mcp_server.server --demo     # passages de démo, sans index ni clé API
```

Pour tester avec MCP Inspector :

```bash
npx @modelcontextprotocol/inspector@latest python -m fri.mcp_server.server --demo
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

En mode démo, les 3 outils marchent sans clé API : `get_financial_metric("3M", 2018, "total revenue")` renvoie 32 765 (p. 42) et `compare_years("3M", "total revenue", 2017, 2018)` renvoie un écart de +1 108 (+3,5 %).

Sous Windows, utiliser l'Inspector v2 (`@latest`) : l'interface web de la v0.15 renvoie « Invalid request parameters » sur `tools/list`. Si `npx` échoue avec `ENOENT ... AppData\Roaming\npm`, créer ce dossier (`mkdir "$env:APPDATA\npm"`).

Attention : le serveur utilise `FastMCP`, qui a été renommé dans `mcp` 2.x. D'où la contrainte `mcp>=1.2,<2` dans `requirements.txt`.

## Tests

`tests/test_mcp_search.py`, `tests/test_agent_graph.py`, `tests/test_metrics.py` et `tests/test_agent_routing.py` tournent sans index ni clé API : le retriever de démo remplace l'index et `FakeListChatModel` (LangChain) remplace le LLM.

Ce qui est vérifié : filtres société / année, garde-fou contre un retriever qui filtre mal, entrées invalides, message clair quand l'index manque, réponse JSON du serveur MCP, citations valides gardées, citations inventées retirées, doublons fusionnés, pas d'appel au LLM sans passage, contenu du prompt ; lecture des nombres et du JSON du LLM, citation du bon passage, valeur introuvable, conversion des milliards, écart et pourcentage, unités différentes ; classement des questions, route comparaison de bout en bout, repli sur le RAG, consignes de calcul, route forcée.

## Suite

- Brancher le vrai index dans `_load_index_retriever()` dès que `fri.ingestion.indexer` est prêt.
- Mesurer avec FinanceBench (rôle 3) : exactitude des valeurs extraites et taux de bonnes routes ; si les règles du routeur se trompent souvent, passer à un routeur LLM (`ROUTER_PROMPT`).
