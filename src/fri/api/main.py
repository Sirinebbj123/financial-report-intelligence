"""API FastAPI.

Usage : uvicorn fri.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from fri.schemas import Answer

app = FastAPI(title="Financial Report Intelligence")


class AskRequest(BaseModel):
    question: str
    company: str | None = None
    year: int | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=Answer)
def ask(req: AskRequest) -> Answer:
    # TODO(Rôle 4) : appeler fri.agent.graph.ask(req.question)
    return Answer(question=req.question, answer="(réponse factice)", citations=[])
