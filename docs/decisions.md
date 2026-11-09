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
