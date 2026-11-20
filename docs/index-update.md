# Mettre à jour l'index sans le reconstruire

Construire l'index des 37 rapports prend environ 36 minutes (28 000 chunks). Pour ajouter,
remplacer ou retirer **un** rapport, `--update` ne recalcule que ce qui a changé.

```bash
python -m fri.ingestion.indexer --update                       # PDF nouveaux ou modifiés
python -m fri.ingestion.indexer --update --docs 3M_2018_10K    # forcer un rapport
python -m fri.ingestion.indexer --remove PFIZER_2021_10K       # retirer un rapport
python -m fri.ingestion.indexer --update --prune               # + retirer les PDF supprimés
```

Exemple de sortie :

```
Mise à jour de l'index data/index avec les PDF de data/pdfs
Ajoutés : AMD_2023_10K
Mis à jour : aucun
Retirés : aucun
Inchangés : 37. Index : 38 documents, 29150 chunks.
Redémarrez l'API ou le serveur MCP pour qu'ils relisent l'index.
```

## Comment ça marche

`manifest.json` garde, pour chaque rapport, l'**empreinte SHA-256** du PDF, son nombre de pages et
de chunks (`files`). À chaque `--update` :

| Cas | Ce qui se passe |
|---|---|
| PDF dans `data/pdfs` mais pas dans l'index | **ajouté** : lecture, chunks, embeddings |
| PDF dont l'empreinte a changé | **remplacé** : ses anciens chunks sont supprimés (Chroma + `chunks.jsonl`), puis la nouvelle version est ajoutée |
| `--docs X` | X est réindexé même s'il n'a pas changé |
| `--remove X` | X est retiré, et le prochain `--update` ne le rajoute pas (liste `excluded` du manifeste) ; `--update --docs X` le fait revenir |
| PDF supprimé du dossier | signalé et **gardé** ; retiré seulement avec `--prune` (un PDF déplacé par erreur ne vide pas l'index) |
| Rien n'a changé | rien n'est recalculé (moins d'une seconde) |

Garanties :

- **Mêmes réglages** : `--update` reprend le modèle d'embeddings, la taille et le chevauchement des
  chunks de l'index existant. Pour changer de réglages, reconstruire (`python -m fri.ingestion.indexer`).
- **Pas d'index à moitié modifié** : le manifeste est retiré au début de la mise à jour et réécrit à
  la fin. Si la mise à jour est coupée, l'API et le serveur MCP voient un index absent (message clair)
  au lieu d'un index incohérent ; relancer la reconstruction complète.
- **PDF illisible** : signalé et ignoré ; l'ancienne version du rapport reste dans l'index.
- **Index construit avant cette version** (sans empreintes) : le premier `--update` enregistre les
  empreintes actuelles sans rien recalculer.

L'API et le serveur MCP chargent l'index au démarrage : il faut les relancer après une mise à jour.

## Mesures

Sur 10 rapports (10 840 chunks), avec un petit modèle d'embeddings sur CPU :

| Opération | Durée |
|---|---|
| `--update` sans changement | 0,2 s |
| `--remove VERIZON_2022_10K` (763 chunks) | 1,2 s |
| `--update --docs VERIZON_2022_10K` (rajout) | 66 s, contre plusieurs minutes pour tout reconstruire |

Après le rajout, l'index contient de nouveau 10 840 chunks, identiques dans Chroma et dans BM25, et la
recherche `wireless service revenue` filtrée sur Verizon 2022 renvoie bien des pages de Verizon.

## Tests

`tests/test_indexer.py` : empreintes dans le manifeste, mise à jour sans changement, ajout, remplacement
(un seul chunk reste pour la nouvelle version), `--remove` puis `--prune`, ancien index sans empreintes,
erreurs (rapport inconnu, index absent), ligne de commande.
