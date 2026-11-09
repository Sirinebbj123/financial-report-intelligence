# Ingestion : lecture des PDF page par page

Module : [`src/fri/ingestion/pdf_parser.py`](../src/fri/ingestion/pdf_parser.py) · Tests : [`tests/test_pdf_parser.py`](../tests/test_pdf_parser.py)

C'est la première brique du pipeline RAG : elle transforme chaque rapport FinanceBench (10-K, 10-Q) en une liste de pages de texte propre. Le numéro de page est conservé tel quel, car c'est lui qui permet la citation `[Société, Année, p. X]`.

```
data/pdfs/3M_2018_10K.pdf ──parse_pdf()──> [Page(doc_name="3M_2018_10K", page=1, text=...), ...]
                                                   │
                                                   └──> chunking.chunk_page() ──> Chunk + ChunkMetadata(page=...)
```

## Utilisation

```python
from fri.ingestion.pdf_parser import parse_pdf, iter_pages, parse_directory

pages = parse_pdf("data/pdfs/3M_2018_10K.pdf")          # list[Page]
pages[0].doc_name, pages[0].page, pages[0].text[:80]

for page in iter_pages("data/pdfs/AMD_2022_10K.pdf"):  # lecture paresseuse (mémoire constante)
    ...

docs = parse_directory("data/pdfs")                     # {doc_name: [Page, ...]}, ignore les PDF illisibles
```

En ligne de commande, pour inspecter une page :

```bash
python -m fri.ingestion.pdf_parser data/pdfs/3M_2018_10K.pdf --show 60
python -m fri.ingestion.pdf_parser data/pdfs --strip-boilerplate --jsonl data/pages.jsonl
```

## Options

| Paramètre | Défaut | Rôle |
|---|---|---|
| `engine` | `auto` | `pymupdf` (rapide) ; `pdfplumber` (secours) ; `auto` prend PyMuPDF s'il est installé |
| `mode` | `layout` | `layout` reconstruit les lignes visuelles ; `raw` renvoie le texte brut du moteur |
| `skip_empty` | `True` | Ignore les pages sans texte, **sans renuméroter** les autres |
| `strip_boilerplate` | `False` | Retire les en-têtes / pieds de page répétés (`Table of Contents`, numéros de page) |
| `doc_name` | nom du fichier | `3M_2018_10K.pdf` donne `3M_2018_10K`, compatible avec `metadata.parse_doc_name` |

## Choix techniques

**1. Numérotation des pages.** `Page.page` est 1-indexé, comme dans un lecteur PDF. FinanceBench donne `evidence_page_num` en 0-indexé : `Page.index` (= `page - 1`) fait la correspondance. Une page vide est sautée mais ne décale jamais la suivante.

**2. Mode `layout`.** En mode brut, PyMuPDF sort une cellule de tableau par ligne :

```
Depreciation and amortization
1,488
1,544
1,474
```

Le mode `layout` regroupe les mots par ligne visuelle à partir de leurs coordonnées (tolérance = la moitié de la hauteur médiane d'un mot) et insère une ligne vide quand l'écart vertical indique un nouveau paragraphe :

```
Depreciation and amortization 1,488 1,544 1,474
```

Le libellé et ses valeurs restent dans le même chunk, ce qui aide BM25, les embeddings et surtout `get_financial_metric`. La fonction `words_to_text` est pure (indépendante du moteur), donc testée sans PDF.

**3. Nettoyage (`clean_text`).** Normalisation Unicode NFKC (ligatures `ﬁ`, espaces insécables), suppression des caractères de contrôle et de largeur nulle, espaces réduits, au plus une ligne vide consécutive. Les retours à la ligne sont gardés.

**4. En-têtes et pieds de page.** `remove_repeated_lines` masque les chiffres (`Page 12` et `Page 13` deviennent `page #`) et retire les lignes présentes en haut ou en bas d'au moins 50 % des pages. Le corps des pages n'est jamais touché. L'option est désactivée par défaut ; on l'activera à l'indexation si le benchmark retrieval montre un gain.

**5. Robustesse.** Fichier absent : `FileNotFoundError`. PDF corrompu ou protégé par mot de passe : `PDFParsingError`. Une page dont l'extraction échoue est journalisée et traitée comme vide, sans arrêter le document. `parse_directory` journalise et ignore un PDF illisible.

## Validation sur FinanceBench

Validation sur les **37 documents des 15 sociétés** du plan (10-K, 10-Q, 8-K et communiqués de résultats, de 2015 à 2024, soit 5 194 pages avec texte) : pour les **92 preuves sur 92** de FinanceBench, la page `evidence_page_num + 1` extraite contient au moins 95 % des mots de la preuve, et c'est la page du document qui ressemble le plus à la preuve. Les 37 PDF sont lus sans erreur.

Le test `test_financebench_evidence_is_on_cited_page` refait cette vérification sur tous les PDF présents dans `data/pdfs` (environ 15 s pour les 37 documents) ; il est sauté si les données ne sont pas téléchargées. Il échoue bien si on oublie le décalage 0-indexé / 1-indexé (92 preuves mal placées sur 92). Certaines preuves FinanceBench collent les mots (`cashandcashequivalents`) : la comparaison se fait donc sans espaces ni ponctuation.

| Moteur | Temps pour 3M_2018_10K (160 pages) |
|---|---|
| PyMuPDF | ~0,5 s |
| pdfplumber | ~30 s |

## Limites connues

- PDF scanné sans couche texte : pages vides (un avertissement est journalisé). Il faudrait un OCR, inutile pour FinanceBench.
- Mise en page sur deux colonnes : le mode `layout` peut fusionner deux colonnes sur la même ligne. Les 10-K sont sur une colonne ; sinon utiliser `mode="raw"`.
- Certains PDF contiennent des espaces parasites dans les mots (`Cash Flow s`) : ils viennent du PDF lui-même, et la preuve FinanceBench a le même défaut.

## Tests

```bash
pytest tests/test_pdf_parser.py -v
pytest tests/test_pdf_parser.py --cov=fri.ingestion.pdf_parser   # ~93 % de couverture
```

Les PDF de test sont générés à la volée avec PyMuPDF (pas de binaire commité). Les tests couvrent : numérotation, page vide, lignes de tableau, mode brut, en-têtes répétés, PDF corrompu et chiffré, dossier avec un PDF illisible, CLI et export JSONL, pour les deux moteurs.
