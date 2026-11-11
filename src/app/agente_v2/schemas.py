"""Contratos estruturados usados pela orquestração V2."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.conversation import ConversationIntent


class PlannerDecision(BaseModel):
    """Decisão interpretativa da LLM antes de qualquer recuperação."""

    model_config = ConfigDict(extra="forbid")

    intent: ConversationIntent = ConversationIntent.UNKNOWN
    needs_clarification: bool = False
    needs_retrieval: bool = False
    reply: str | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    action: str | None = None

    @field_validator("clarification_questions")
    @classmethod
    def _validate_clarification_questions(cls, value: list[str]) -> list[str]:
        cleaned = []
        for question in value:
            text = question.strip()
            if not is_structured_clarification(text):
                raise ValueError(
                    "cada esclarecimento deve ser uma pergunta isolada"
                )
            cleaned.append(text)
        return cleaned


def is_structured_clarification(value: str) -> bool:
    """Aceita apenas uma pergunta isolada, sem prefácio declarativo."""

    text = value.strip()
    return bool(text) and text.endswith("?") and text.count("?") == 1 and not any(
        marker in text[:-1] for marker in ".!"
    )


class SynthesisResponse(BaseModel):
    """Resposta da síntese sem depender de AgentAnswer como tool call."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ToolExecution(BaseModel):
    """Proveniência mínima de uma execução controlada pelo orquestrador."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    conversation_id: str
    turn_id: str
    query: str
    status: str
    raw_result: dict[str, Any]


__all__ = [
    "PlannerDecision",
    "SynthesisResponse",
    "ToolExecution",
    "is_structured_clarification",
]
