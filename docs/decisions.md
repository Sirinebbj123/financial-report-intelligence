# Journal des décisions

| Date | Décision | Raison |
|---|---|---|
| 2026-11 | Python 3.11, LangChain + LangGraph, ChromaDB + BM25, FastAPI | Plan du projet |
| | Fournisseur LLM : à choisir (OpenAI, Groq, Mistral ou Ollama) | Selon les crédits disponibles |
| | Interface : Streamlit (Next.js si le temps le permet) | |
| 2026-11 | Parsing PDF avec PyMuPDF, pdfplumber en secours | PyMuPDF lit un 10-K de 160 pages en ~0,5 s contre ~30 s pour pdfplumber, avec le même texte |
| | Mode `layout` par défaut : lignes reconstruites à partir des coordonnées des mots | Les lignes des tableaux financiers restent entières (libellé + valeurs), utile pour BM25 et l'extraction de métriques |
| | Numéro de page 1-indexé, jamais renuméroté (pages vides ignorées sans décalage) | La citation `[Société, Année, p. X]` doit pointer la bonne page ; FinanceBench `evidence_page_num` = `page - 1` |
| | Retrait des en-têtes / pieds de page répétés : optionnel (`strip_boilerplate`) | Garder le texte fidèle par défaut ; à activer à l'indexation si le benchmark montre un gain |
| | Détection des colonnes de texte par gouttière verticale, avec garde-fous « texte courant » | Lire une page en deux colonnes dans le bon ordre sans jamais casser une ligne de tableau (12 pages changées sur 5 194) |
| | Tableaux reconstruits à partir des mots (libellé + nombres alignés à droite), pas avec `find_tables()` | `find_tables()` colle les mots et coupe les nombres sur les PDF FinanceBench |
| | Cache JSONL des pages, clé = SHA-256 du PDF + options + `CACHE_VERSION` | Ne pas reparser les PDF à chaque indexation, sans risque de relire un cache périmé |
| 2026-11 | Agent v1 : graphe LangGraph `retrieve -> answer`, routage repoussé à la tâche 4 | Avoir une réponse citée de bout en bout avant d'ajouter calcul et comparaison |
| | L'agent appelle `search_filings`, la même fonction que l'outil MCP | Un seul chemin de recherche à tester et à évaluer |
| | Retriever remplaçable (`set_retriever`) + retriever de démo en mémoire | Avancer sur l'agent et le MCP sans attendre l'index ; tests sans index ni clé API |
| | Citations filtrées : seules celles qui pointent vers un passage fourni sont gardées | Une page inventée par le LLM ne doit jamais apparaître comme source |
| | `mcp>=1.2,<2` | `FastMCP` a été renommé `MCPServer` dans `mcp` 2.x |
| 2026-11 | Routeur par règles (années + mots-clés), pas par LLM | Gratuit, instantané et testable ; on passera au LLM si l'évaluation montre trop d'erreurs |
| | Valeurs extraites par le LLM en JSON (`value`, `unit`, `passage`), converties en millions de dollars | Comparer des valeurs dans la même unité ; la citation pointe le passage d'où vient le chiffre |
| | Réponse de comparaison rédigée par le code à partir de `compare_years` | Écart et pourcentage exacts, jamais recalculés par le LLM |
| | Repli sur le RAG classique quand la comparaison échoue | Toujours donner une réponse citée plutôt qu'une erreur |
| 2026-11 | Chunks de 800 caractères, chevauchement 100, jamais à cheval sur deux pages | La page du chunk est toujours la page citée ; les lignes de tableau restent entières |
| | Découpage maison (paragraphe > ligne > phrase > mot), sans LangChain | Même principe que `RecursiveCharacterTextSplitter`, sans dépendance de plus ni surprise de version |
| | En-tête `Société Année Type` ajouté au texte indexé, pas au texte cité | Aide BM25 et les embeddings quand la question nomme la société sans filtre |
| | Embeddings calculés par nous, `embedding_function=None` dans Chroma, distance cosinus | Même modèle garanti à l'indexation et à la recherche ; Chroma ne télécharge jamais son modèle par défaut |
| | Modèle d'embeddings lu dans `manifest.json` au chargement | Changer `EMBEDDING_MODEL` sans réindexer ne casse pas la recherche |
| | BM25 reconstruit au chargement depuis `chunks.jsonl`, pas de pickle | Quelques secondes, lisible, pas de souci de version de `rank_bm25` ni de pickle à charger |
| | Société comparée en forme normalisée (`company_key`) | `American Express` (questions) = `AMERICANEXPRESS` (noms des PDF) |
| | Reranker `bge-reranker-base` sur 20 candidats, désactivé par défaut | ~1 Go et lent sur CPU ; on l'active si l'évaluation montre un gain |
| 2026-11 | `_load_index_retriever()` renvoie `HybridRetriever.load()` ; index absent = pas de `manifest.json` | Un index à moitié construit n'est jamais chargé |
| | Le serveur MCP charge l'index et le modèle au démarrage, et démarre quand même si l'index manque | Premier appel rapide dans Claude Desktop ; erreur visible dans les logs, message clair dans l'outil |
| | `DATA_DIR` / `INDEX_DIR` relatifs résolus depuis la racine du dépôt | Claude Desktop lance le serveur depuis un autre dossier que le dépôt |

| 2026-11 | Mise à jour incrémentale : empreinte SHA-256 de chaque PDF dans `manifest.json`, `--update` ne recalcule que les rapports nouveaux ou modifiés | Ajouter un rapport prend une minute au lieu de reconstruire 28 000 chunks (~36 min) |
| | Un rapport est remplacé en entier (suppression de ses chunks dans Chroma et `chunks.jsonl`, puis ajout) | Ids de chunks stables et aucun reste de l'ancienne version, même si le nombre de pages change |
| | Réglages de l'index existant (modèle, taille des chunks) réutilisés par `--update` | Jamais deux réglages mélangés dans le même index |
| | Pas de manifeste pendant la mise à jour ; `--remove` mémorisé (`excluded`) ; PDF disparus retirés seulement avec `--prune` | Un index à moitié modifié n'est jamais chargé ; un rapport retiré ne revient pas tout seul ; pas de perte si un PDF est déplacé |

| 2026-11 | Client MCP en Python (`fri.mcp_server.client`, SDK `mcp`) en plus de MCP Inspector | Démonstration reproductible en une commande, testée en CI, avec une trace Markdown pour le rapport |
| | Le client lance le serveur comme Claude Desktop (sous-processus, stdio) et lui transmet l'environnement | Même chemin que les vrais clients ; `INDEX_DIR` et les clés API du terminal sont pris en compte |

