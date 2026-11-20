# Démonstration du serveur MCP

Trace produite par `python -m fri.mcp_server.client` : un client MCP (SDK `mcp`) lance le serveur sur stdio, liste ses outils et les appelle.

Serveur : `python -m fri.mcp_server.server  (financial-report-intelligence)`

| Outil | Paramètres | Description |
|---|---|---|
| `search_filings` | query, company, year, k | Recherche des passages dans les rapports financiers (10-K, 10-Q). |
| `get_financial_metric` | company, year, metric | Renvoie la valeur d'une métrique financière (ex. "total revenue") et sa source. |
| `compare_years` | company, metric, year_a, year_b | Compare une métrique entre deux années : écart et pourcentage d'évolution. |

## 1. `search_filings` (1.0 s)

```json
{
  "query": "total revenue",
  "company": "3M",
  "year": 2022,
  "k": 3
}
```

```text
3 passage(s)
  [3M, 2022, p. 59] score 0.033 : Deferred revenue primarily relates to revenue that is recognized over time for one-year software license contr...
  [3M, 2022, p. 60] score 0.032 : Table of Contents Disaggregated revenue information: The Company views the following disaggregated disclosures...
  [3M, 2022, p. 55] score 0.031 : expense and recorded in cost of sales. Product returns are recorded as a reduction to revenue based on anticip...
```

## 2. `get_financial_metric` (3.72 s)

```json
{
  "company": "3M",
  "year": 2022,
  "metric": "total revenue"
}
```

```text
total revenue = 34 229 M$  [3M, 2022, p. 48]
```

## 3. `compare_years` (2.13 s)

```json
{
  "company": "3M",
  "metric": "total revenue",
  "year_a": 2018,
  "year_b": 2022
}
```

```text
2018 : 32 765 M$  [3M, 2018, p. 56]
2022 : 34 229 M$  [3M, 2022, p. 48]
écart : +1 464 M$  (+4.5 %)
```
