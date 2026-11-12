"""Interpretação contextual da V2 com fallback conservador."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from src.app.conversation import (
    ConversationIntent,
    interpret_intent,
)
from src.app.query_planner import is_contextual_follow_up
from src.app.scope_guard import (
    ACTION_UNAVAILABLE_MESSAGE,
    CLARIFICATION_MESSAGE,
    GREETING_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    has_academic_term,
)

from .schemas import PlannerDecision, is_structured_clarification

logger = logging.getLogger(__name__)


class Planner:
    """Deixa a LLM interpretar, usando heurísticas apenas como guarda de segurança."""

    def __init__(self, model: Any | None) -> None:
        self._model = model
        self._structured = None
        if model is not None:
            try:
                self._structured = model.with_structured_output(
                    PlannerDecision,
                    method="json_schema",
                    include_raw=True,
                )
            except Exception:
                logger.exception("planner_structured_output_unavailable=True")

    def plan(self, question: str, history: list[Any]) -> PlannerDecision:
        fallback = self._fallback(question, history)
        if fallback.intent == ConversationIntent.AMBIGUOUS and not (
            is_contextual_follow_up(question)
            and any(
                has_academic_term(
                    str(
                        message.get("content", "")
                        if isinstance(message, Mapping)
                        else getattr(message, "content", "")
                    )
                )
                for message in history
                if (
                    str(
                        message.get("role", "")
                        if isinstance(message, Mapping)
                        else getattr(message, "role", getattr(message, "type", ""))
                    )
                    in {"user", "human"}
                )
            )
        ):
            return fallback
        if self._structured is None:
            return fallback

        prompt = self._prompt(question, history)
        try:
            value = self._structured.invoke(
                [{"role": "system", "content": prompt}]
            )
            parsed = self._parsed(value)
            if parsed is None:
                return fallback
            return self._safe_decision(parsed, fallback)
        except Exception:
            logger.exception("planner_execution_failed=True")
            return fallback

    def _prompt(self, question: str, history: list[Any]) -> str:
        context = [
            {
                "role": str(message.get("role", ""))
                if isinstance(message, Mapping)
                else str(getattr(message, "role", getattr(message, "type", ""))),
                "content": str(
                    message.get("content", "")
                    if isinstance(message, Mapping)
                    else getattr(message, "content", "")
                )[:1200],
            }
            for message in history[-8:]
        ]
        return (
            "Você é o planejador de um assistente acadêmico ABNT. Interprete a "
            "mensagem atual usando o contexto. Não invente regra normativa. "
            "Escolha uma intenção entre conversational, ambiguous, normative_query, "
            "action_request, out_of_scope e unknown. Use needs_retrieval=true apenas "
            "quando a resposta exigir documento normativo. Para ambiguous, escreva "
            "uma ou mais perguntas isoladas em clarification_questions, sem prefácios "
            "ou afirmações. Para action_request, não simule "
            "a ferramenta. Retorne somente o objeto estruturado.\n\n"
            f"Histórico: {json.dumps(context, ensure_ascii=False)}\n"
            f"Pergunta atual: {question}"
        )

    def _parsed(self, value: Any) -> PlannerDecision | None:
        if isinstance(value, PlannerDecision):
            return value
        if isinstance(value, Mapping):
            parsed = value.get("parsed")
            if isinstance(parsed, PlannerDecision):
                return parsed
            if isinstance(parsed, Mapping):
                return PlannerDecision.model_validate(parsed)
            if "intent" in value:
                return PlannerDecision.model_validate(value)
        return None

    def _safe_decision(
        self, decision: PlannerDecision, fallback: PlannerDecision
    ) -> PlannerDecision:
        if (
            decision.needs_retrieval
            and decision.intent == ConversationIntent.UNKNOWN
        ):
            decision.intent = ConversationIntent.NORMATIVE_QUERY
        if decision.intent in {
            ConversationIntent.CONVERSATIONAL,
            ConversationIntent.AMBIGUOUS,
            ConversationIntent.ACTION_REQUEST,
            ConversationIntent.OUT_OF_SCOPE,
        }:
            decision.needs_retrieval = False
        if decision.intent == ConversationIntent.NORMATIVE_QUERY:
            decision.needs_retrieval = True
        if decision.intent == ConversationIntent.AMBIGUOUS:
            decision.needs_clarification = True
            if not decision.clarification_questions:
                if decision.reply and is_structured_clarification(decision.reply):
                    decision.clarification_questions = [decision.reply.strip()]
                else:
                    decision.clarification_questions = (
                        fallback.clarification_questions or [CLARIFICATION_MESSAGE]
                    )
            decision.reply = None
        if decision.intent == ConversationIntent.UNKNOWN and fallback.intent == (
            ConversationIntent.NORMATIVE_QUERY
        ):
            decision.needs_retrieval = True
        if decision.intent == ConversationIntent.UNKNOWN and not decision.reply:
            return fallback
        return decision

    def _fallback(self, question: str, history: list[Any]) -> PlannerDecision:
        decision = interpret_intent([*history, {"role": "user", "content": question}])
        reply = None
        if decision.intent == ConversationIntent.AMBIGUOUS:
            clarification_questions = [CLARIFICATION_MESSAGE]
        else:
            clarification_questions = []
        if decision.intent == ConversationIntent.ACTION_REQUEST:
            reply = ACTION_UNAVAILABLE_MESSAGE
        elif decision.intent == ConversationIntent.OUT_OF_SCOPE:
            reply = OUT_OF_SCOPE_MESSAGE
        elif decision.intent == ConversationIntent.CONVERSATIONAL:
            reply = GREETING_MESSAGE
        return PlannerDecision(
            intent=decision.intent,
            needs_clarification=decision.needs_clarification,
            needs_retrieval=decision.intent == ConversationIntent.NORMATIVE_QUERY,
            reply=reply,
            clarification_questions=clarification_questions,
        )


__all__ = ["Planner"]
