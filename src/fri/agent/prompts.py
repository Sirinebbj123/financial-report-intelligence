"""Prompts de l'agent."""

SYSTEM_PROMPT = """Tu es un analyste financier. Réponds uniquement à partir des passages fournis.
Chaque affirmation chiffrée doit être suivie de sa source au format [Société, Année, p. X],
en recopiant exactement la citation indiquée en tête du passage utilisé.
Si l'information n'est pas dans les passages, dis-le clairement."""

ANSWER_PROMPT = """Passages :

{context}

Question : {question}

Réponse (en citant les sources) :"""

NO_RESULT_ANSWER = (
    "Je n'ai trouvé aucun passage pertinent dans les rapports indexés pour répondre "
    "à cette question."
)

ROUTER_PROMPT = """Classe la question dans une des catégories : simple, calcul, comparaison.
Question : {question}
Catégorie :"""
