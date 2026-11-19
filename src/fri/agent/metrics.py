"""Extraction d'une valeur chiffrée (métrique financière) à partir de passages.

Deux extracteurs, avec la même interface `extractor(company, year, metric, results)` :
- `LLMMetricExtractor` : le LLM lit les passages et renvoie la valeur en JSON (le vrai) ;
- `RegexMetricExtractor` : prend le premier montant « $X million / billion » trouvé
  (démo et tests hors ligne, sans clé API).
Ils renvoient un `MetricExtraction`, ou None si la valeur n'est pas dans les passages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from fri.agent.citations import format_context
from fri.agent.prompts import METRIC_PROMPT, METRIC_SYSTEM_PROMPT
from fri.schemas import SearchResult


@dataclass(frozen=True)
class MetricExtraction:
    value: float
    unit: str
    passage: int  # 1-indexé : le passage d'où vient la valeur (pour la citation)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def message_text(message: Any) -> str:
    """Texte d'une réponse de LLM (message LangChain ou simple chaîne)."""
    content = getattr(message, "content", message)
    if isinstance(content, list):  # certains fournisseurs renvoient des blocs
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content).strip()


def parse_json_reply(text: str) -> dict | None:
    """Lit le premier objet JSON d'une réponse de LLM (tolère ```json et le texte autour)."""
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def to_number(raw: Any) -> float | None:
    """'32,765' -> 32765.0 ; '(1,200)' -> -1200.0 ; None ou texte -> None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    text = str(raw).strip().replace(",", "").replace("$", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    try:
        value = float(text.strip("()"))
    except ValueError:
        return None
    return -value if negative else value


class LLMMetricExtractor:
    """Demande au LLM la valeur de la métrique, en JSON, à partir des passages."""

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

    def _model(self):
        if self.llm is None:
            from fri.agent.llm import get_chat_model

            self.llm = get_chat_model()
        return self.llm

    def __call__(
        self, company: str, year: int, metric: str, results: list[SearchResult]
    ) -> MetricExtraction | None:
        prompt = METRIC_PROMPT.format(
            company=company, year=year, metric=metric, context=format_context(results)
        )
        reply = self._model().invoke([SystemMessage(METRIC_SYSTEM_PROMPT), HumanMessage(prompt)])
        data = parse_json_reply(message_text(reply))
        if not data:
            return None
        value = to_number(data.get("value"))
        try:
            passage = int(data.get("passage") or 1)
        except (TypeError, ValueError):
            return None
        if value is None or not 1 <= passage <= len(results):
            return None
        unit = str(data.get("unit") or "USD millions").strip()
        return MetricExtraction(value=value, unit=unit, passage=passage)


_AMOUNT_RE = re.compile(r"\$\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>million|billion)", re.I)


class RegexMetricExtractor:
    """Premier montant en dollars des passages, converti en millions. Démo seulement."""

    def __call__(
        self, company: str, year: int, metric: str, results: list[SearchResult]
    ) -> MetricExtraction | None:
        for i, result in enumerate(results, start=1):
            match = _AMOUNT_RE.search(result.chunk.text)
            if match:
                value = to_number(match["num"])
                if value is None:
                    continue
                if match["scale"].lower() == "billion":
                    value *= 1000
                return MetricExtraction(value=value, unit="USD millions", passage=i)
        return None
