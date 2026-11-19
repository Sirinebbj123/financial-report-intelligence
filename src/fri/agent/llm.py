"""Création du modèle de chat selon le fournisseur choisi dans .env (LLM_PROVIDER)."""

from __future__ import annotations

from importlib import import_module

from fri.config import settings

# fournisseur -> (module, classe, paquet pip)
_PROVIDERS = {
    "openai": ("langchain_openai", "ChatOpenAI", "langchain-openai"),
    "groq": ("langchain_groq", "ChatGroq", "langchain-groq"),
    "mistral": ("langchain_mistralai", "ChatMistralAI", "langchain-mistralai"),
    "ollama": ("langchain_ollama", "ChatOllama", "langchain-ollama"),
}


def get_chat_model(provider: str | None = None, model: str | None = None, temperature: float = 0):
    """Renvoie un modèle de chat LangChain (temperature 0 : réponses reproductibles)."""
    provider = (provider or settings.llm_provider).lower()
    model = model or settings.llm_model
    if provider not in _PROVIDERS:
        raise ValueError(f"LLM_PROVIDER inconnu : {provider} (choix : {', '.join(_PROVIDERS)})")
    module_name, class_name, package = _PROVIDERS[provider]
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise ImportError(f"Installe le paquet du fournisseur : pip install {package}") from exc
    return getattr(module, class_name)(model=model, temperature=temperature)
