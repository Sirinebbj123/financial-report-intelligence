# Ingestion : lecture des PDF page par page

Modules : [`pdf_parser.py`](../src/fri/ingestion/pdf_parser.py) (API, moteurs, cache, CLI) · [`layout.py`](../src/fri/ingestion/layout.py) (lignes et colonnes) · [`tables.py`](../src/fri/ingestion/tables.py) (tableaux de chiffres)

Tests : [`tests/test_pdf_parser.py`](../tests/test_pdf_parser.py) · [`tests/test_layout_tables.py`](../tests/test_layout_tables.py)

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

pages = parse_pdf("data/pdfs/3M_2018_10K.pdf", tables=True, cache_dir="data/cache/pages")
table = pages[59].tables[0]                             # état des flux de trésorerie, p. 60
table.header                                            # ('(Millions)', '2018', '2017', '2016')
print(table.to_markdown())

from fri.ingestion.tables import parse_number
parse_number("(1,577)")                                 # -1577.0
```

En ligne de commande, pour inspecter une page :

```bash
python -m fri.ingestion.pdf_parser data/pdfs/3M_2018_10K.pdf --show 60
python -m fri.ingestion.pdf_parser data/pdfs/3M_2018_10K.pdf --tables --show 60
python -m fri.ingestion.pdf_parser data/pdfs --tables --cache-dir data/cache/pages
python -m fri.ingestion.pdf_parser data/pdfs --strip-boilerplate --jsonl data/pages.jsonl
```

## Options

| Paramètre | Défaut | Rôle |
|---|---|---|
| `engine` | `auto` | `pymupdf` (rapide) ; `pdfplumber` (secours) ; `auto` prend PyMuPDF s'il est installé |
| `mode` | `layout` | `layout` reconstruit les lignes visuelles ; `raw` renvoie le texte brut du moteur |
| `skip_empty` | `True` | Ignore les pages sans texte, **sans renuméroter** les autres |
| `strip_boilerplate` | `False` | Retire les en-têtes / pieds de page répétés (`Table of Contents`, numéros de page) |
| `columns` | `True` | En mode `layout`, lit les zones à plusieurs colonnes de texte colonne par colonne |
| `tables` | `False` | Remplit `Page.tables` avec les tableaux de chiffres (lignes x colonnes) |
| `cache_dir` | `None` | Dossier du cache JSONL : un PDF déjà lu n'est pas reparsé (`parse_pdf`, `parse_directory`) |
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

**5. Pages à plusieurs colonnes de texte (`layout.order_blocks`).** Sur une page en deux colonnes, la lecture ligne par ligne mélange les deux textes. On cherche une « gouttière » : une bande verticale vide qui coupe plusieurs lignes consécutives. La zone est lue colonne par colonne (gauche entière, puis droite ; récursivement pour 3 colonnes ou plus) seulement si chaque côté ressemble à du texte courant : au moins 6 lignes, au moins 6 mots par ligne, 70 % de mots alphabétiques, et des lignes qui remplissent la largeur de la colonne. Ces garde-fous évitent de casser les tableaux de chiffres et les tableaux « nom / fonction », dont chaque ligne doit rester entière. Sur les 5 194 pages du jeu de validation, seules 12 pages sont lues autrement (par exemple le tableau comparatif Delaware / Jersey d'Amcor ou un contrat bilingue d'AMD) ; toutes les autres sont identiques à avant.

**6. Tableaux de chiffres (`tables.py`).** `Page.tables` contient les tableaux de la page sous forme `Table(header, rows)`, chaque ligne valant `[libellé, valeur1, valeur2, ...]`. Une ligne de tableau est un libellé suivi de nombres (`1,488`, `(1,577)`, `12.5%`, `—`) ; un tableau compte au moins 3 lignes avec 2 valeurs ou plus. Les colonnes sont retrouvées en regroupant les bords droits des nombres (alignés à droite), une colonne présente sur moins de 25 % des lignes est rendue au libellé (numéro de page, note « (1) »), et un nombre collé au libellé (« December 31 ») en fait partie. L'en-tête est détecté quand une des deux premières lignes ne contient que des années. `parse_number` convertit une cellule en nombre ; `Table.to_markdown()` donne un texte lisible par un LLM. On n'utilise pas `page.find_tables()` de PyMuPDF : sur ces PDF il colle les mots (`Depreciationandamortization`) et coupe les nombres (`5363\n,`). Résultat : 2 181 tableaux sur les 37 documents.

**7. Cache JSONL.** Avec `cache_dir`, `parse_pdf` écrit les pages (et leurs tableaux) dans `<cache_dir>/<doc_name>.<clé>.jsonl` et les relit ensuite : 0,2 s au lieu de 1,1 s pour 3M_2018_10K. La clé est un SHA-256 du contenu du PDF, des options et de `CACHE_VERSION` : modifier le PDF, changer une option ou faire évoluer le parser (incrémenter `CACHE_VERSION`) invalide le cache. L'écriture est atomique, les anciennes versions du même document sont supprimées, et un cache illisible est ignoré (le PDF est reparsé). Le dossier `data/` est ignoré par Git.

**8. Robustesse.** Fichier absent : `FileNotFoundError`. PDF corrompu ou protégé par mot de passe : `PDFParsingError`. Une page dont l'extraction échoue est journalisée et traitée comme vide, sans arrêter le document. `parse_directory` journalise et ignore un PDF illisible.

## Validation sur FinanceBench

Validation sur les **37 documents des 15 sociétés** du plan (10-K, 10-Q, 8-K et communiqués de résultats, de 2015 à 2024, soit 5 194 pages avec texte) : pour les **92 preuves sur 92** de FinanceBench, la page `evidence_page_num + 1` extraite contient au moins 95 % des mots de la preuve, et c'est la page du document qui ressemble le plus à la preuve. Les 37 PDF sont lus sans erreur. Ce résultat est identique avec la détection des colonnes activée.

Le test `test_financebench_evidence_is_on_cited_page` refait cette vérification sur tous les PDF présents dans `data/pdfs` (environ 15 s pour les 37 documents) ; il est sauté si les données ne sont pas téléchargées. Il échoue bien si on oublie le décalage 0-indexé / 1-indexé (92 preuves mal placées sur 92). Certaines preuves FinanceBench collent les mots (`cashandcashequivalents`) : la comparaison se fait donc sans espaces ni ponctuation.

| Moteur | Temps pour 3M_2018_10K (160 pages) |
|---|---|
| PyMuPDF | ~1 s (colonnes et tableaux compris) |
| PyMuPDF, depuis le cache | ~0,2 s |
| pdfplumber | ~30 s |

## Limites connues

- PDF scanné sans couche texte : pages vides (un avertissement est journalisé). Il faudrait un OCR, inutile pour FinanceBench.
- Colonnes de texte : la détection est volontairement prudente. Une zone dont la gouttière est très étroite (moins d'une hauteur de mot) ou interrompue par une ligne pleine largeur reste lue ligne par ligne. On peut désactiver la détection avec `columns=False`.
- Tableaux : un en-tête sur plusieurs lignes (« December 31, » puis « 2022 2021 ») n'est reconnu que si la ligne des années est dans les deux premières lignes du tableau ; un tableau sans nombres (texte seul) n'est pas extrait.
- Certains PDF contiennent des espaces parasites dans les mots (`Cash Flow s`) : ils viennent du PDF lui-même, et la preuve FinanceBench a le même défaut.

## Tests

```bash
pytest tests/test_pdf_parser.py tests/test_layout_tables.py -v
pytest tests/test_pdf_parser.py tests/test_layout_tables.py --cov=fri.ingestion   # layout 100 %, tables 97 %, pdf_parser 94 %
```

Les PDF de test sont générés à la volée avec PyMuPDF (pas de binaire commité), et les tests de mise en page utilisent des boîtes de mots synthétiques. Ils couvrent : numérotation, page vide, lignes de tableau, mode brut, en-têtes répétés, PDF corrompu et chiffré, dossier avec un PDF illisible, CLI et export JSONL (pour les deux moteurs) ; lecture de deux colonnes de texte et non-découpage des tableaux ; extraction des tableaux, `parse_number`, Markdown ; cache réutilisé, invalidé par une option ou un nouveau contenu, et cache corrompu ignoré.
