# Client MCP de démonstration

Le cahier des charges demande de démontrer le serveur MCP **avec un client**. On en a deux :

- **MCP Inspector** (client graphique officiel) :
  `npx @modelcontextprotocol/inspector@latest python -m fri.mcp_server.server` ;
- **`fri.mcp_server.client`** : un client Python (SDK `mcp`), reproductible en une commande et testé en CI.

```bash
python -m fri.mcp_server.client --demo                     # sans index ni clé API
python -m fri.mcp_server.client                            # vrai index + LLM du .env
python -m fri.mcp_server.client --company AMD --metric "total revenue" \
    --year-a 2021 --year-b 2022 --query "data center segment"
python -m fri.mcp_server.client --markdown docs/mcp_demo.md   # trace Markdown pour le rapport
```

## Ce que fait le client

1. Il lance le serveur comme le ferait Claude Desktop : `python -m fri.mcp_server.server` en
   sous-processus, dialogue JSON-RPC sur stdio (`initialize`).
2. `tools/list` : il affiche les outils exposés et leurs paramètres.
3. `tools/call` sur les 3 outils : `search_filings`, `get_financial_metric`, `compare_years`.
4. Il affiche un résumé lisible (citations `[Société, Année, p. X]`, valeurs, écart) et, avec
   `--markdown`, écrit la trace complète.

Sortie en mode démo :

```
Serveur MCP : python -m fri.mcp_server.server --demo  (financial-report-intelligence)

Outils exposés (3) :
  - search_filings(query, company, year, k) : Recherche des passages dans les rapports financiers (10-K, 10-Q).
  - get_financial_metric(company, year, metric) : Renvoie la valeur d'une métrique financière (ex. "total revenue") et sa source.
  - compare_years(company, metric, year_a, year_b) : Compare une métrique entre deux années : écart et pourcentage d'évolution.

[1] search_filings {"query": "total revenue", "company": "3M", "year": 2018, "k": 3}  (0.01 s)
    1 passage(s)
      [3M, 2018, p. 42] score 1.000 : Net sales: total revenue for 3M in 2018 was $32,765 million, ...

[2] get_financial_metric {"company": "3M", "year": 2018, "metric": "total revenue"}  (0.0 s)
    total revenue = 32 765 M$  [3M, 2018, p. 42]

[3] compare_years {"company": "3M", "metric": "total revenue", "year_a": 2017, "year_b": 2018}  (0.0 s)
    2017 : 31 657 M$  [3M, 2017, p. 40]
    2018 : 32 765 M$  [3M, 2018, p. 42]
    écart : +1 108 M$  (+3.5 %)

3/3 appels réussis.
```

Sans `--demo`, la ligne `[fri] Index chargé (N chunks).` confirme que le serveur lit le vrai index.
Sans clé de LLM, `search_filings` marche et les deux autres outils renvoient une erreur explicite
(le client l'affiche au lieu de planter).

Valeurs par défaut : 3M, `total revenue`, 2017 → 2018 en démo ; 2018 → 2022 sur le vrai index
(les deux 10-K de 3M de FinanceBench). Le client transmet l'environnement au serveur : `INDEX_DIR`,
`LLM_PROVIDER` et les clés API du terminal sont pris en compte.

## Tests

`tests/test_mcp_client.py` lance le vrai serveur en mode démo et vérifie la liste des 3 outils,
les 3 appels (page 42, valeur 32 765, écart +1 108), le résumé, la trace Markdown et la ligne de commande.
