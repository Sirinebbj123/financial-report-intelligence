# finetuning/ (Rôle 3, optionnel)

Fine-tuning de `BAAI/bge-small-en-v1.5` sur les paires question–passage de FinanceBench
(MultipleNegativesRankingLoss de sentence-transformers). Le modèle remplace celui de l'index
seulement si `evaluation/retrieval_eval.py` montre un gain.

Attention : séparer train / test par société pour ne pas évaluer sur les questions d'entraînement.

Les modèles sont sauvegardés dans `finetuning/models/` (ignoré par Git).
