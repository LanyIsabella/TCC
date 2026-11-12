"""Interpretação contextual da V2 com fallback conservador."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from src.app.conversation import (
    ConversationIntent,
    interpret_intent,
)
from src.app.query_planner import (
    is_broad_question,
    is_contextual_follow_up,
    normalize_text,
)
from src.app.scope_guard import (
    ACTION_UNAVAILABLE_MESSAGE,
    CLARIFICATION_MESSAGE,
    GREETING_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    has_academic_term,
)

from .schemas import (
    ClarificationResolution,
    PlannerDecision,
    ResponseMode,
    is_structured_clarification,
)

logger = logging.getLogger(__name__)

_CLARIFICATION_STOPWORDS = {
    "a",
    "as",
    "ao",
    "aos",
    "de",
    "do",
    "dos",
    "da",
    "das",
    "em",
    "e",
    "o",
    "os",
    "um",
    "uma",
}


def _is_underspecified_question(question: str) -> bool:
    normalized = normalize_text(question).strip().rstrip("?.!")
    return bool(
        re.fullmatch(
            r"(?:qual (?:e |deve ser )?|como deve ser )"
            r"(?:o|a) (?:recuo|margem|fonte|espacamento)",
            normalized,
        )
    )


def _is_general_knowledge_question(question: str) -> bool:
    normalized = normalize_text(question).strip().rstrip("?.!")
    if not normalized.startswith(
        (
            "o que e ",
            "explique ",
            "qual a importancia ",
            "como funciona ",
            "como fazer ",
            "como posso melhorar ",
            "como melhorar ",
            "como escrever ",
        )
    ):
        return False
    return not any(
        marker in normalized
        for marker in (
            "abnt",
            "nbr",
            "norma",
            "regra",
            "deve",
            "obrigatori",
            "permitid",
            "recuo",
            "margem",
            "citac",
            "referenc",
            "espacamento",
        )
    )


class Planner:
    """Deixa a LLM interpretar, usando heurísticas apenas como guarda de segurança."""

    def __init__(self, model: Any | None) -> None:
        self._model = model
        self._structured = None
        self._clarification_structured = None
        if model is not None:
            try:
                self._structured = model.with_structured_output(
                    PlannerDecision,
                    method="json_schema",
                    include_raw=True,
                )
                self._clarification_structured = model.with_structured_output(
                    ClarificationResolution,
                    method="json_schema",
                    include_raw=True,
                )
            except Exception:
                logger.exception("planner_structured_output_unavailable=True")

    def resolve_clarification(
        self,
        answer: str,
        original_question: str,
        prompt: str,
        history: list[Any],
    ) -> str | None:
        deterministic = self._deterministic_clarification_query(
            answer, original_question
        )
        if deterministic is not None:
            return deterministic
        if self._clarification_structured is None:
            return None
        try:
            value = self._clarification_structured.invoke(
                [
                    {
                        "role": "system",
                        "content": self._clarification_prompt(
                            answer, original_question, prompt, history
                        ),
                    }
                ]
            )
            resolution = ClarificationResolution.from_llm_value(value)
            if resolution is not None:
                return self._validated_clarification(
                    resolution.resolved_question.strip(), answer, original_question
                )
        except Exception:
            logger.exception("clarification_resolution_failed=True")
        return None

    @staticmethod
    def _clarification_prompt(
        answer: str,
        original_question: str,
        prompt: str,
        history: list[Any],
    ) -> str:
        context = [
            {
                "role": str(
                    message.get("role", "")
                    if isinstance(message, Mapping)
                    else getattr(message, "role", getattr(message, "type", ""))
                ),
                "content": str(
                    message.get("content", "")
                    if isinstance(message, Mapping)
                    else getattr(message, "content", "")
                )[:800],
            }
            for message in history[-6:]
        ]
        return (
            "Você resolve uma resposta curta a um pedido de esclarecimento de um "
            "assistente acadêmico ABNT. Gere uma única pergunta autossuficiente "
            "para recuperação documental. Preserve o assunto original, incorpore "
            "o aspecto respondido literalmente e não produza a resposta normativa. "
            "Não troque o aspecto por outro. Retorne "
            "somente {resolved_question}.\n\n"
            f"Pergunta original: {original_question}\n"
            f"Pedido de esclarecimento: {prompt}\n"
            f"Resposta curta: {answer}\n"
            f"Histórico: {json.dumps(context, ensure_ascii=False)}"
        )

    @staticmethod
    def _deterministic_clarification_query(
        answer: str, original_question: str
    ) -> str | None:
        aspect = normalize_text(answer)
        original = normalize_text(original_question)
        if "referenc" in original:
            if any(term in aspect for term in ("autor", "respons", "nome")):
                return (
                    "Segundo a ABNT NBR 6023, como indicar o nome do autor "
                    "nas referências bibliográficas?"
                )
            if any(term in aspect for term in ("element", "compon", "dado")):
                return (
                    "Segundo a ABNT NBR 6023, quais são os elementos necessários "
                    "para elaborar referências bibliográficas?"
                )
            if any(term in aspect for term in ("format", "apresent", "estilo")):
                return (
                    "Segundo a ABNT NBR 6023, quais são as regras de formatação "
                    "das referências?"
                )
        if (
            "recuo" in original
            and "citac" in aspect
            and "direta" in aspect
            and "longa" in aspect
        ):
            return (
                "Segundo a ABNT NBR 10520, qual é o recuo de citação direta "
                "longa?"
            )
        return None

    @staticmethod
    def _validated_clarification(
        candidate: str, answer: str, original_question: str
    ) -> str:
        candidate_terms = set(normalize_text(candidate).split())
        aspect_terms = {
            normalize_text(term)[:5]
            for term in re.findall(r"[\wÀ-ÿ]+", answer)
            if normalize_text(term) not in _CLARIFICATION_STOPWORDS
            and len(normalize_text(term)) >= 5
        }
        if any(
            term in " ".join(candidate_terms)
            for term in aspect_terms
        ):
            return candidate
        return f"{original_question.rstrip(' ?.!')} — aspecto: {answer.strip()}"

    def plan(self, question: str, history: list[Any]) -> PlannerDecision:
        fallback = self._fallback(question, history)
        if fallback.intent == ConversationIntent.AMBIGUOUS and not (
            (
                is_contextual_follow_up(question)
                or _is_underspecified_question(question)
            )
            and self._history_has_academic_term(history)
        ):
            return fallback
        if self._structured is None:
            return fallback
        try:
            value = self._structured.invoke(
                [{"role": "system", "content": self._prompt(question, history)}]
            )
            parsed = self._parsed(value)
            if parsed is None:
                return fallback
            decision = self._safe_decision(parsed, fallback)
            return self._repair_contextual_decision(
                question, history, decision, fallback
            )
        except Exception:
            logger.exception("planner_execution_failed=True")
            return fallback

    @staticmethod
    def _history_has_academic_term(history: list[Any]) -> bool:
        return any(
            has_academic_term(
                str(
                    message.get("content", "")
                    if isinstance(message, Mapping)
                    else getattr(message, "content", "")
                )
            )
            for message in history
            if str(
                message.get("role", "")
                if isinstance(message, Mapping)
                else getattr(message, "role", getattr(message, "type", ""))
            )
            in {"user", "human"}
        )

    def _repair_contextual_decision(
        self,
        question: str,
        history: list[Any],
        decision: PlannerDecision,
        fallback: PlannerDecision,
    ) -> PlannerDecision:
        if self._requires_normative_route(question, history, decision, fallback):
            return self._as_normative_query(decision)
        return decision

    def _requires_normative_route(
        self,
        question: str,
        history: list[Any],
        decision: PlannerDecision,
        fallback: PlannerDecision,
    ) -> bool:
        if is_contextual_follow_up(
            question, history
        ) and self._history_has_academic_term(history):
            return True
        if (
            _is_underspecified_question(question)
            and self._history_has_academic_term(history)
        ):
            return True
        if self._is_explicit_topic_change(question) and has_academic_term(question):
            return True
        return (
            is_broad_question(question)
            and fallback.intent == ConversationIntent.NORMATIVE_QUERY
            and decision.intent
            in {
                ConversationIntent.ACTION_REQUEST,
                ConversationIntent.CONVERSATIONAL,
                ConversationIntent.UNKNOWN,
            }
        )

    @staticmethod
    def _as_normative_query(decision: PlannerDecision) -> PlannerDecision:
        return decision.model_copy(
            update={
                "intent": ConversationIntent.NORMATIVE_QUERY,
                "mode": ResponseMode.NORMATIVE,
                "needs_clarification": False,
                "needs_retrieval": True,
                "reply": None,
                "clarification_questions": [],
            }
        )

    def _prompt(self, question: str, history: list[Any]) -> str:
        context = self._prompt_context(history)
        return (
            "Você é o planejador de um assistente acadêmico ABNT. Interprete a "
            "mensagem atual usando o contexto. Não invente regra normativa. "
            "Escolha um modo entre general, normative, mixed, clarify e out_of_scope "
            "e uma intenção entre conversational, ambiguous, normative_query, "
            "action_request, out_of_scope e unknown. Use general para explicações "
            "conceituais ou procedurais sem regra normativa específica; normative "
            "quando toda afirmação normativa exigir documento; mixed quando uma "
            "explicação geral puder acompanhar regras documentais. Use clarify quando "
            "faltarem dados e out_of_scope para pedidos não suportados. "
            "Pedidos de estratégia pessoal, redação ou melhoria de uma introdução "
            "são general quando não pedirem um requisito específico de norma. "
            "needs_retrieval deve ser true em normative ou mixed e false em general, "
            "clarify e out_of_scope. Em retrieval_queries, forneça no máximo duas "
            "consultas autossuficientes quando forem necessárias. Para ambiguous, "
            "escreva "
            "uma ou mais perguntas isoladas em clarification_questions, sem prefácios "
            "ou afirmações. Quando a pergunta normativa for ampla e puder se referir "
            "a aspectos diferentes, como autoria, elementos ou formatação, prefira "
            "ambiguous e peça um único esclarecimento específico. Para "
            "action_request, não simule a ferramenta. Retorne somente o objeto "
            "estruturado, incluindo mode, objective, retrieval_queries e "
            "use_parametric_knowledge.\n\n"
            f"Histórico: {json.dumps(context, ensure_ascii=False)}\n"
            f"Pergunta atual: {question}"
        )

    @staticmethod
    def _prompt_context(history: list[Any]) -> list[dict[str, str]]:
        return [
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

    def _parsed(self, value: Any) -> PlannerDecision | None:
        return PlannerDecision.from_llm_value(value)

    def _safe_decision(
        self, decision: PlannerDecision, fallback: PlannerDecision
    ) -> PlannerDecision:
        self._normalize_retrieval_flag(decision)
        if decision.intent == ConversationIntent.AMBIGUOUS:
            self._normalize_ambiguous_decision(decision, fallback)
        return self._resolve_unknown_decision(decision, fallback)

    @staticmethod
    def _normalize_retrieval_flag(decision: PlannerDecision) -> None:
        normative_signal = (
            decision.intent == ConversationIntent.NORMATIVE_QUERY
            or decision.needs_retrieval
        )
        if decision.mode == ResponseMode.GENERAL:
            if normative_signal:
                decision.mode = ResponseMode.NORMATIVE
                decision.intent = ConversationIntent.NORMATIVE_QUERY
            elif decision.intent == ConversationIntent.AMBIGUOUS:
                decision.mode = ResponseMode.CLARIFY
            elif decision.intent in {
                ConversationIntent.ACTION_REQUEST,
                ConversationIntent.OUT_OF_SCOPE,
            }:
                decision.mode = ResponseMode.OUT_OF_SCOPE
        elif decision.mode == ResponseMode.MIXED:
            decision.intent = ConversationIntent.NORMATIVE_QUERY
        elif decision.mode == ResponseMode.NORMATIVE:
            decision.intent = ConversationIntent.NORMATIVE_QUERY
        elif decision.mode == ResponseMode.CLARIFY:
            if normative_signal:
                decision.mode = ResponseMode.NORMATIVE
                decision.intent = ConversationIntent.NORMATIVE_QUERY
        elif decision.mode == ResponseMode.OUT_OF_SCOPE:
            if normative_signal:
                decision.mode = ResponseMode.NORMATIVE
                decision.intent = ConversationIntent.NORMATIVE_QUERY
        elif normative_signal:
            decision.mode = ResponseMode.NORMATIVE
            decision.intent = ConversationIntent.NORMATIVE_QUERY
        elif decision.intent == ConversationIntent.AMBIGUOUS:
            decision.mode = ResponseMode.CLARIFY
        elif decision.intent in {
            ConversationIntent.ACTION_REQUEST,
            ConversationIntent.OUT_OF_SCOPE,
        }:
            decision.mode = ResponseMode.OUT_OF_SCOPE
        else:
            decision.mode = ResponseMode.GENERAL

        decision.needs_retrieval = decision.mode in {
            ResponseMode.NORMATIVE,
            ResponseMode.MIXED,
        }
        if decision.mode in {ResponseMode.NORMATIVE, ResponseMode.OUT_OF_SCOPE}:
            decision.use_parametric_knowledge = False

    @staticmethod
    def _normalize_ambiguous_decision(
        decision: PlannerDecision, fallback: PlannerDecision
    ) -> None:
        decision.needs_clarification = True
        if not decision.clarification_questions:
            if decision.reply and is_structured_clarification(decision.reply):
                decision.clarification_questions = [decision.reply.strip()]
            else:
                decision.clarification_questions = (
                    fallback.clarification_questions or [CLARIFICATION_MESSAGE]
                )
        decision.reply = None

    @staticmethod
    def _resolve_unknown_decision(
        decision: PlannerDecision, fallback: PlannerDecision
    ) -> PlannerDecision:
        if decision.intent == ConversationIntent.UNKNOWN and fallback.intent == (
            ConversationIntent.NORMATIVE_QUERY
        ):
            decision.needs_retrieval = True
        if decision.intent == ConversationIntent.UNKNOWN and not decision.reply:
            return fallback
        return decision

    @staticmethod
    def _is_explicit_topic_change(question: str) -> bool:
        normalized = normalize_text(question)
        return normalized.startswith(
            ("na verdade", "na realidade", "quero saber", "prefiro saber")
        )

    def _fallback(self, question: str, history: list[Any]) -> PlannerDecision:
        if _is_general_knowledge_question(question):
            return PlannerDecision(
                intent=ConversationIntent.CONVERSATIONAL,
                mode=ResponseMode.GENERAL,
            )
        decision = interpret_intent([*history, {"role": "user", "content": question}])
        if _is_underspecified_question(question):
            return PlannerDecision(
                intent=ConversationIntent.AMBIGUOUS,
                needs_clarification=True,
                clarification_questions=[
                    (
                        "Você se refere ao recuo de citações, referências ou "
                        "outro elemento?"
                    )
                ],
            )
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
            mode={
                ConversationIntent.NORMATIVE_QUERY: ResponseMode.NORMATIVE,
                ConversationIntent.AMBIGUOUS: ResponseMode.CLARIFY,
                ConversationIntent.ACTION_REQUEST: ResponseMode.OUT_OF_SCOPE,
                ConversationIntent.OUT_OF_SCOPE: ResponseMode.OUT_OF_SCOPE,
            }.get(decision.intent, ResponseMode.GENERAL),
        )


__all__ = ["Planner"]
