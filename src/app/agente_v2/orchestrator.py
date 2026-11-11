"""Orquestração independente do agente acadêmico V2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from src.app.client import Client
from src.app.conversation import ConversationIntent, ConversationStore
from src.app.evidence import AgentResult, public_evidence
from src.app.query_planner import contextualize_query

from .grounding_adapter import (
    conversational_result,
    failed_normative_result,
    grounded_result,
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
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ValueError("messages deve ser uma lista.")
        question = self._last_user_question(messages)
        if not question:
            raise ValueError("A requisição precisa conter uma mensagem de usuário.")
        # A mensagem atual é processada neste turno; somente o histórico anterior
        # pode inicializar uma conversa nova.
        conversation_id = self._store.ensure(
            payload.get("conversation_id"), messages[:-1]
        )
        turn_id = uuid4().hex
        history = self._store.context(conversation_id)
        plan = self._planner.plan(question, history)
        if (
            plan.needs_retrieval
            and plan.intent != ConversationIntent.NORMATIVE_QUERY
        ):
            plan = plan.model_copy(
                update={"intent": ConversationIntent.NORMATIVE_QUERY}
            )

        if not plan.needs_retrieval:
            answer = (
                "\n".join(plan.clarification_questions)
                if plan.needs_clarification and plan.clarification_questions
                else plan.reply
                or "Por favor, envie uma pergunta acadêmica mais específica."
            )
            result = conversational_result(
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                answer=answer,
                planner=plan,
            )
            self._append_turn(conversation_id, question, result.answer)
            return self._public(result, plan, turn_id)

        query = contextualize_query(question, history)
        execution = self._tools.execute(
            "rag_document_search",
            {"question": query},
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        if isinstance(execution, Mapping):
            execution = ToolExecution(
                tool_name="rag_document_search",
                conversation_id=conversation_id,
                turn_id=turn_id,
                query=query,
                status=str(execution.get("status") or "error"),
                raw_result=dict(execution),
            )
        if (
            execution.status != "success"
            or execution.raw_result.get("evidence_found") is False
        ):
            result = failed_normative_result(
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                execution=execution,
                planner=plan,
                error_code=LimitationCode.EVIDENCE_UNAVAILABLE,
            )
            self._append_turn(conversation_id, question, result.answer)
            return self._public(result, plan, turn_id)

        try:
            synthesis = self._synthesizer.synthesize(
                question, history, execution.raw_result
            )
        except SynthesisFailure:
            result = failed_normative_result(
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                execution=execution,
                planner=plan,
                error_code=LimitationCode.SYNTHESIS_FAILED,
            )
        else:
            result = grounded_result(
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                synthesis=synthesis,
                execution=execution,
                planner=plan,
            )
        self._append_turn(conversation_id, question, result.answer)
        return self._public(result, plan, turn_id)

    def _append_turn(self, conversation_id: str, question: str, answer: str) -> None:
        self._store.append(
            conversation_id,
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
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
