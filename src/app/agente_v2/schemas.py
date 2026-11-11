"""Contratos estruturados usados pela orquestração V2."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.conversation import ConversationIntent


class PlannerDecision(BaseModel):
    """Decisão interpretativa da LLM antes de qualquer recuperação."""

    model_config = ConfigDict(extra="forbid")

    intent: ConversationIntent = ConversationIntent.UNKNOWN
    needs_clarification: bool = False
    needs_retrieval: bool = False
    reply: str | None = None
    action: str | None = None


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


__all__ = ["PlannerDecision", "SynthesisResponse", "ToolExecution"]
