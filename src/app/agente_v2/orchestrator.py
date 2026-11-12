"""Orquestração independente do agente acadêmico V2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from src.app.client import Client
from src.app.conversation import (
    ConversationIntent,
    ConversationStore,
    PendingClarification,
)
from src.app.evidence import AgentResult, public_evidence
from src.app.query_planner import contextualize_query, is_broad_question, normalize_text
from src.app.scope_guard import GREETING_MESSAGE

from .grounding_adapter import (
    conversational_result,
    failed_normative_result,
    grounded_result,
    retrieval_error_code,
)
from .planner import Planner
from .schemas import LimitationCode, PlannerDecision, ToolExecution
from .synthesis import SynthesisFailure, Synthesizer
from .tools import ToolRegistry


class AgentV2:
    """Fluxo explícito: planejar, recuperar, sintetizar, validar e publicar."""

    def __init__(
        self,
        *,
        model: Any | None = None,
        planner: Any | None = None,
        synthesizer: Any | None = None,
        tools: Any | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        if model is None and (planner is None or synthesizer is None):
            model = Client().return_model()
        self._planner = planner or Planner(model)
        self._synthesizer = synthesizer or Synthesizer(model)
        self._tools = tools or ToolRegistry()
        self._store = store or ConversationStore()

    def invoke(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        messages, question = self._validated_request(payload)
        # A mensagem atual é processada neste turno; somente o histórico anterior
        # pode inicializar uma conversa nova.
        conversation_id = self._store.ensure(
            payload.get("conversation_id"), messages[:-1]
        )
        turn_id = uuid4().hex
        history = self._store.context(conversation_id)
        pending = self._store.pending_clarification(conversation_id)
        planning_question = self._resolve_pending_clarification(
            question, pending, history
        )
        if pending is not None:
            self._store.clear_pending_clarification(conversation_id)
        plan = self._plan(planning_question, history)

        if not plan.needs_retrieval:
            result = self._conversational_turn(
                conversation_id, turn_id, question, plan
            )
            return self._finish_turn(
                conversation_id, question, result, plan, turn_id
            )

        execution = self._execute_search(
            planning_question, history, conversation_id, turn_id
        )
        if self._retrieval_failed(execution):
            result = failed_normative_result(
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                execution=execution,
                planner=plan,
                error_code=LimitationCode.EVIDENCE_UNAVAILABLE,
                error_detail=retrieval_error_code(execution),
            )
            return self._finish_turn(
                conversation_id,
                question,
                result,
                plan,
                turn_id,
                remember_clarification=False,
            )

        result = self._normative_turn(
            question,
            planning_question,
            history,
            execution,
            plan,
            turn_id,
            conversation_id,
        )
        return self._finish_turn(conversation_id, question, result, plan, turn_id)

    @staticmethod
    def _validated_request(payload: Mapping[str, Any]) -> tuple[list[Any], str]:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ValueError("messages deve ser uma lista.")
        question = AgentV2._last_user_question(messages)
        if not question:
            raise ValueError("A requisição precisa conter uma mensagem de usuário.")
        return messages, question

    def _plan(self, question: str, history: list[Any]) -> PlannerDecision:
        plan = self._planner.plan(question, history)
        if plan.needs_retrieval and plan.intent != ConversationIntent.NORMATIVE_QUERY:
            return plan.model_copy(
                update={"intent": ConversationIntent.NORMATIVE_QUERY}
            )
        return plan

    def _conversational_turn(
        self,
        conversation_id: str,
        turn_id: str,
        question: str,
        plan: PlannerDecision,
    ) -> AgentResult:
        answer = self._conversational_answer(plan)
        return conversational_result(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            answer=answer,
            planner=plan,
        )

    @staticmethod
    def _conversational_answer(plan: PlannerDecision) -> str:
        if plan.needs_clarification and plan.clarification_questions:
            return "\n".join(plan.clarification_questions)
        if plan.reply:
            return plan.reply
        if plan.intent == ConversationIntent.CONVERSATIONAL:
            return GREETING_MESSAGE
        return "Por favor, envie uma pergunta acadêmica mais específica."

    def _execute_search(
        self,
        question: str,
        history: list[Any],
        conversation_id: str,
        turn_id: str,
    ) -> ToolExecution:
        query = contextualize_query(question, history)
        execution = self._tools.execute(
            "rag_document_search",
            {"question": query},
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        if isinstance(execution, Mapping):
            return ToolExecution(
                tool_name="rag_document_search",
                conversation_id=conversation_id,
                turn_id=turn_id,
                query=query,
                status=str(execution.get("status") or "error"),
                raw_result=dict(execution),
            )
        return execution

    @staticmethod
    def _retrieval_failed(execution: ToolExecution) -> bool:
        return (
            execution.status != "success"
            or execution.raw_result.get("evidence_found") is False
        )

    def _normative_turn(
        self,
        question: str,
        planning_question: str,
        history: list[Any],
        execution: ToolExecution,
        plan: PlannerDecision,
        turn_id: str,
        conversation_id: str,
    ) -> AgentResult:
        try:
            synthesis = self._synthesizer.synthesize(
                planning_question, history, execution.raw_result
            )
        except SynthesisFailure:
            return failed_normative_result(
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                execution=execution,
                planner=plan,
                error_code=LimitationCode.SYNTHESIS_FAILED,
            )
        result = grounded_result(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            synthesis=synthesis,
            execution=execution,
            planner=plan,
        )
        if (
            self._is_underspecified_broad_question(question)
            and result.grounding_status == "unsupported"
        ):
            return self._clarification_after_unsupported_broad_query(result, question)
        return result

    def _finish_turn(
        self,
        conversation_id: str,
        question: str,
        result: AgentResult,
        plan: PlannerDecision,
        turn_id: str,
        *,
        remember_clarification: bool = True,
    ) -> dict[str, Any]:
        self._append_turn(conversation_id, question, result.answer)
        if (
            remember_clarification
            and result.completion_type == "clarification_requested"
        ):
            self._store.set_pending_clarification(
                conversation_id, question, result.answer
            )
        return self._public(result, plan, turn_id)

    @staticmethod
    def _is_underspecified_broad_question(question: str) -> bool:
        normalized = normalize_text(question)
        terms = normalized.split()
        return (
            is_broad_question(question)
            and len(terms) <= 5
            and any(
                marker in normalized
                for marker in ("referenc", "citac", "margens", "formatacao")
            )
            and not any(
                marker in normalized
                for marker in (
                    "autor",
                    "nome",
                    "element",
                    "direta",
                    "indireta",
                    "recuo",
                )
            )
            and not any(term in terms for term in ("abnt", "nbr", "segundo"))
            and not any(character.isdigit() for character in normalized)
        )

    @staticmethod
    def _clarification_after_unsupported_broad_query(
        result: AgentResult, question: str
    ) -> AgentResult:
        normalized = normalize_text(question)
        if "citacoes" in normalized:
            answer = (
                "Você se refere a citações diretas, indiretas ou citações de "
                "fontes?"
            )
        elif "referencias" in normalized:
            answer = (
                "Você deseja orientação sobre autoria, elementos ou formatação "
                "das referências?"
            )
        else:
            answer = "Qual aspecto da formatação acadêmica você deseja consultar?"
        return replace(
            result,
            answer=answer,
            grounding_status="conversational",
            completion_type="clarification_requested",
            limitations=(),
            selected_evidence_ids=(),
            published_evidence_ids=(),
        )

    def _append_turn(self, conversation_id: str, question: str, answer: str) -> None:
        self._store.append(
            conversation_id,
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        )

    def _resolve_pending_clarification(
        self,
        question: str,
        pending: PendingClarification | None,
        history: list[Any],
    ) -> str:
        if pending is None:
            return question
        normalized = normalize_text(question)
        if (
            len(normalized.split()) > 8
            or normalized.startswith(
                ("na verdade", "na realidade", "quero saber", "prefiro saber")
            )
            or normalized in {"oi", "ola", "obrigado", "obrigada"}
        ):
            return question
        resolver = getattr(self._planner, "resolve_clarification", None)
        if callable(resolver):
            resolved = resolver(
                question,
                pending.original_question,
                pending.prompt,
                history,
            )
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        return (
            f"{question.strip()} Contexto da pergunta original: "
            f"{pending.original_question.strip()}"
        )

    @staticmethod
    def _last_user_question(messages: list[Any]) -> str:
        for message in reversed(messages):
            role = (
                message.get("role")
                if isinstance(message, Mapping)
                else getattr(message, "role", None)
            )
            if role in {"user", "human"}:
                value = (
                    message.get("content")
                    if isinstance(message, Mapping)
                    else getattr(message, "content", "")
                )
                return str(value or "").strip()
        return ""

    def _public(
        self, result: AgentResult, plan: PlannerDecision, turn_id: str
    ) -> dict[str, Any]:
        return {
            "answer": result.answer,
            "evidences": [public_evidence(item) for item in result.evidences],
            "grounding_status": result.grounding_status,
            "limitations": list(result.limitations),
            "conversation_id": result.conversation_id,
            "turn_id": result.turn_id or turn_id,
            "intent": result.intent or plan.intent,
            "completion_type": result.completion_type,
            "available_evidence_ids": list(result.available_evidence_ids),
            "selected_evidence_ids": list(result.selected_evidence_ids),
            "published_evidence_ids": list(result.published_evidence_ids),
            "tool_provenance": list(result.tool_provenance),
            "errors": list(result.errors),
            "messages": self._store.history(result.conversation_id or ""),
        }


__all__ = ["AgentV2"]
