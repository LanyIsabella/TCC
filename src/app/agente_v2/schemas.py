"""Contratos estruturados usados pela orquestração V2."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.conversation import ConversationIntent


class ResponseMode(StrEnum):
    """Modo publicável decidido antes da recuperação."""

    GENERAL = "general"
    NORMATIVE = "normative"
    MIXED = "mixed"
    CLARIFY = "clarify"
    OUT_OF_SCOPE = "out_of_scope"


def _from_llm_value(
    model_type: type[BaseModel], value: Any, required_field: str
) -> BaseModel | None:
    if isinstance(value, model_type):
        return value
    if not isinstance(value, Mapping):
        return None
    parsed = value.get("parsed", value)
    if isinstance(parsed, model_type):
        return parsed
    if isinstance(parsed, Mapping) and required_field in parsed:
        return model_type.model_validate(parsed)
    return None


class PlannerDecision(BaseModel):
    """Decisão interpretativa da LLM antes de qualquer recuperação."""

    model_config = ConfigDict(extra="forbid")

    intent: ConversationIntent = ConversationIntent.UNKNOWN
    needs_clarification: bool = False
    needs_retrieval: bool = False
    reply: str | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    action: str | None = None
    mode: ResponseMode | None = None
    objective: str | None = None
    retrieval_queries: list[str] = Field(default_factory=list)
    use_parametric_knowledge: bool = True

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

    @classmethod
    def from_llm_value(cls, value: Any) -> PlannerDecision | None:
        return _from_llm_value(cls, value, "intent")  # type: ignore[return-value]

    def effective_mode(self) -> ResponseMode:
        if self.mode is not None:
            return self.mode
        if self.intent == ConversationIntent.NORMATIVE_QUERY or self.needs_retrieval:
            return ResponseMode.NORMATIVE
        if self.intent == ConversationIntent.AMBIGUOUS or self.needs_clarification:
            return ResponseMode.CLARIFY
        if self.intent in {
            ConversationIntent.ACTION_REQUEST,
            ConversationIntent.OUT_OF_SCOPE,
        }:
            return ResponseMode.OUT_OF_SCOPE
        return ResponseMode.GENERAL


class ClarificationResolution(BaseModel):
    """Consulta autossuficiente derivada de um esclarecimento respondido."""

    model_config = ConfigDict(extra="forbid")

    resolved_question: str = Field(min_length=8)

    @classmethod
    def from_llm_value(cls, value: Any) -> ClarificationResolution | None:
        return _from_llm_value(cls, value, "resolved_question")  # type: ignore[return-value]


def is_structured_clarification(value: str) -> bool:
    """Aceita apenas uma pergunta isolada, sem prefácio declarativo."""

    text = value.strip()
    return bool(text) and text.endswith("?") and text.count("?") == 1 and not any(
        marker in text[:-1] for marker in ".!;"
    )


class LimitationCode(StrEnum):
    """Categorias publicáveis de limitações controladas pela aplicação."""

    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    PARTIAL_SUPPORT = "partial_support"
    SYNTHESIS_FAILED = "synthesis_failed"


class SynthesisResponse(BaseModel):
    """Resposta da síntese sem depender de AgentAnswer como tool call."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[LimitationCode] = Field(default_factory=list)


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
    "ResponseMode",
    "ClarificationResolution",
    "SynthesisResponse",
    "ToolExecution",
    "is_structured_clarification",
    "LimitationCode",
]
