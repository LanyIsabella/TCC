"""Orquestração independente do agente acadêmico V2."""

from __future__ import annotations

import re
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
from src.app.grounding import INSUFFICIENT_EVIDENCE
from src.app.query_planner import (
    contextualize_query,
    is_broad_question,
    is_contextual_follow_up,
    normalize_text,
)
from src.app.scope_guard import GREETING_MESSAGE, has_academic_term

from .grounding_adapter import (
    conversational_result,
    failed_normative_result,
    generated_result,
    grounded_result,
    grounding_claim_classifier,
    grounding_verifier,
    retrieval_error_code,
)
from .planner import Planner
from .schemas import (
    LimitationCode,
    PlannerDecision,
    ResponseMode,
    SynthesisResponse,
    ToolExecution,
)
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
        self._grounding_verifier = grounding_verifier(model)
        self._claim_classifier = grounding_claim_classifier(model)
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
        if self._is_explicit_topic_change(question):
            history = []
        plan = self._plan(planning_question, history)
        if planning_question != question and plan.needs_retrieval:
            plan = plan.model_copy(update={"retrieval_queries": [planning_question]})

        if plan.effective_mode() in {
            ResponseMode.GENERAL,
            ResponseMode.CLARIFY,
            ResponseMode.OUT_OF_SCOPE,
        }:
            if plan.mode == ResponseMode.GENERAL and not (
                plan.intent == ConversationIntent.CONVERSATIONAL
                and self._is_safe_conversational_reply(plan.reply)
            ):
                result = self._general_turn(
                    conversation_id, turn_id, question, planning_question, history, plan
                )
            else:
                result = self._conversational_turn(
                    conversation_id, turn_id, question, plan
                )
            return self._finish_turn(
                conversation_id, question, result, plan, turn_id
            )

        execution = self._execute_searches(
            planning_question,
            history,
            conversation_id,
            turn_id,
            plan.retrieval_queries,
        )
        if self._retrieval_failed(execution):
            if plan.effective_mode() == ResponseMode.MIXED:
                result = self._mixed_turn_without_evidence(
                    question,
                    planning_question,
                    history,
                    execution,
                    plan,
                    turn_id,
                    conversation_id,
                )
            else:
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
        if isinstance(plan, PlannerDecision):
            plan = plan.model_copy()
            if (
                plan.mode is not None
                or plan.needs_retrieval
                or plan.intent == ConversationIntent.NORMATIVE_QUERY
            ):
                Planner._normalize_retrieval_flag(plan)
        if (
            plan.needs_retrieval
            and plan.intent != ConversationIntent.NORMATIVE_QUERY
        ):
            return plan.model_copy(
                update={
                    "intent": ConversationIntent.NORMATIVE_QUERY,
                    "mode": plan.mode or ResponseMode.NORMATIVE,
                }
            )
        return plan

    def _general_turn(
        self,
        conversation_id: str,
        turn_id: str,
        question: str,
        planning_question: str,
        history: list[Any],
        plan: PlannerDecision,
    ) -> AgentResult:
        if not plan.use_parametric_knowledge:
            return self._general_failure(
                conversation_id,
                turn_id,
                question,
                plan,
                "parametric_knowledge_disabled",
            )
        try:
            synthesis = self._synthesize(
                planning_question, history, {}, plan
            )
        except SynthesisFailure:
            return self._general_failure(
                conversation_id, turn_id, question, plan, "synthesis_failed"
            )
        return generated_result(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            synthesis=synthesis,
            planner=plan,
            verifier=self._grounding_verifier,
            claim_classifier=self._claim_classifier,
        )

    def _general_failure(
        self,
        conversation_id: str,
        turn_id: str,
        question: str,
        plan: PlannerDecision,
        error: str,
    ) -> AgentResult:
        result = generated_result(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            synthesis=SynthesisResponse(
                answer=(
                    "A síntese geral não foi publicada porque não pôde ser "
                    "validada com segurança."
                ),
                limitations=[LimitationCode.SYNTHESIS_FAILED],
            ),
            planner=plan,
            verifier=self._grounding_verifier,
            claim_classifier=self._claim_classifier,
        )
        return replace(
            result,
            completion_type="technical_failure",
            errors=(*result.errors, error),
        )

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

    @staticmethod
    def _is_safe_conversational_reply(reply: str | None) -> bool:
        if not reply:
            return False
        normalized = normalize_text(reply).strip()
        return bool(
            re.fullmatch(
                r"(?:ola|oi|bom dia|boa tarde|boa noite)[!.]?"
                r"(?: posso ajudar(?: com [^.!?]+)?[!.]?)?",
                normalized,
            )
        )

    def _execute_search(
        self,
        question: str,
        history: list[Any],
        conversation_id: str,
        turn_id: str,
        query: str | None = None,
    ) -> ToolExecution:
        query = query or contextualize_query(question, history)
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

    def _execute_searches(
        self,
        question: str,
        history: list[Any],
        conversation_id: str,
        turn_id: str,
        queries: list[str],
    ) -> ToolExecution:
        candidates = [item.strip() for item in queries[:2] if item.strip()]
        if not candidates:
            candidates = [""]
        executions: list[ToolExecution] = []
        run_all_queries = len(candidates) > 1 and is_broad_question(question)
        for query in candidates:
            execution = self._execute_search(
                question, history, conversation_id, turn_id, query=query or None
            )
            executions.append(execution)
            if not run_all_queries and self._retrieval_sufficient(execution, question):
                break
        if len(executions) == 1:
            return executions[0]
        successful = next(
            (item for item in executions if not self._retrieval_failed(item)),
            executions[-1],
        )
        merged = dict(successful.raw_result)
        documents_by_key: dict[str, dict[str, Any]] = {}
        document_order: list[str] = []
        for execution in executions:
            for document in execution.raw_result.get("documents", []):
                if not isinstance(document, Mapping):
                    continue
                key = self._document_identity(document)
                if key not in documents_by_key:
                    documents_by_key[key] = dict(document)
                    document_order.append(key)
                    for field in ("pages", "matched_pages", "evidence"):
                        value = document.get(field)
                        if isinstance(value, list):
                            documents_by_key[key][field] = list(value)
                else:
                    self._merge_document(
                        documents_by_key[key], document
                    )
        documents = [documents_by_key[key] for key in document_order]
        merged["documents"] = documents
        merged["evidence_found"] = bool(documents)
        return successful.model_copy(update={"raw_result": merged})

    @staticmethod
    def _document_identity(document: Mapping[str, Any]) -> str:
        for field in ("rag_document_id", "document_id", "standard_id"):
            value = document.get(field)
            if value not in (None, ""):
                return f"{field}:{value}"
        return "title-version:" + "|".join(
            str(document.get(field) or "") for field in ("title", "version")
        )

    @classmethod
    def _merge_document(
        cls, target: dict[str, Any], incoming: Mapping[str, Any]
    ) -> None:
        for field in ("pages", "matched_pages", "evidence"):
            values = incoming.get(field)
            if not isinstance(values, list):
                continue
            existing = target.setdefault(field, [])
            if not isinstance(existing, list):
                target[field] = existing = []
            seen = {
                cls._record_identity(field, item)
                for item in existing
            }
            for item in values:
                marker = cls._record_identity(field, item)
                if marker not in seen:
                    existing.append(item)
                    seen.add(marker)

    @staticmethod
    def _record_identity(field: str, item: Any) -> str:
        if isinstance(item, Mapping):
            if field == "evidence" and item.get("evidence_id"):
                return f"evidence:{item['evidence_id']}"
            if field == "evidence":
                return "evidence:" + "|".join(
                    str(item.get(key) or "")
                    for key in ("page_number", "text", "matched_text")
                )
            if item.get("page_number") is not None:
                return f"{field}-page:{item['page_number']}"
            return f"{field}:{item.get('text') or item.get('matched_text') or item}"
        return f"{field}:{item}"

    def _synthesize(
        self,
        question: str,
        history: list[Any],
        retrieval: Mapping[str, Any],
        plan: PlannerDecision,
    ) -> Any:
        synthesize = self._synthesizer.synthesize
        try:
            return synthesize(
                question,
                history,
                retrieval,
                mode=plan.effective_mode(),
                objective=plan.objective,
                use_parametric_knowledge=plan.use_parametric_knowledge,
            )
        except TypeError as error:
            if "unexpected keyword" not in str(error):
                raise
            return synthesize(question, history, retrieval)

    @staticmethod
    def _retrieval_failed(execution: ToolExecution) -> bool:
        return (
            execution.status != "success"
            or execution.raw_result.get("evidence_found") is False
        )

    @staticmethod
    def _retrieval_sufficient(execution: ToolExecution, question: str) -> bool:
        if AgentV2._retrieval_failed(execution):
            return False
        generic_terms = {
            "abnt",
            "academico",
            "academicos",
            "formatacao",
            "principal",
            "principais",
            "regra",
            "regras",
            "norma",
            "normas",
            "tcc",
            "trabalho",
            "trabalhos",
        }
        terms = {
            term.strip(".,?!;:()[]{}")
            for term in normalize_text(question).split()
        }
        terms = {
            term
            for term in terms
            if len(term) >= 4
            and term
            not in {"qual", "quais", "como", "para", "segundo", "sobre"}
            and term not in generic_terms
        }
        for document in execution.raw_result.get("documents", []):
            if not isinstance(document, Mapping):
                continue
            for evidence in document.get("evidence", []):
                if not isinstance(evidence, Mapping):
                    continue
                text = normalize_text(str(evidence.get("text") or ""))
                overlap = any(term in text for term in terms)
                if evidence.get("direct_match") and overlap:
                    return True
                if evidence.get("matched_text") and overlap:
                    return True
        return False

    def _mixed_turn_without_evidence(
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
            synthesis = self._synthesize(
                planning_question, history, {"documents": []}, plan
            )
        except SynthesisFailure:
            synthesis = SynthesisResponse(
                answer=INSUFFICIENT_EVIDENCE,
                evidence_ids=[],
                limitations=[
                    LimitationCode.EVIDENCE_UNAVAILABLE,
                    LimitationCode.SYNTHESIS_FAILED,
                ],
            )
        else:
            if LimitationCode.EVIDENCE_UNAVAILABLE not in synthesis.limitations:
                synthesis = synthesis.model_copy(
                    update={
                        "limitations": [
                            *synthesis.limitations,
                            LimitationCode.EVIDENCE_UNAVAILABLE,
                        ]
                    }
                )
        return grounded_result(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            grounding_question=planning_question,
            synthesis=synthesis,
            execution=execution,
            planner=plan,
            verifier=self._grounding_verifier,
            claim_classifier=self._claim_classifier,
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
            synthesis = self._synthesize(
                planning_question, history, execution.raw_result, plan
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
            grounding_question=planning_question,
            synthesis=synthesis,
            execution=execution,
            planner=plan,
            verifier=self._grounding_verifier,
            claim_classifier=self._claim_classifier,
        )
        if (
            self._is_underspecified_broad_question(question, history)
            and result.grounding_status in {"unsupported", "partial"}
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
    def _is_underspecified_broad_question(
        question: str, history: list[Any] | None = None
    ) -> bool:
        normalized = normalize_text(question)
        terms = normalized.split()
        if (
            is_contextual_follow_up(question, history)
            and any(
                marker in normalized
                for marker in (
                    "autor",
                    "element",
                    "format",
                    "recuo",
                    "margem",
                    "fonte",
                    "citac",
                )
            )
        ):
            return False
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
            pending = self._implicit_pending_clarification(question, history)
        if pending is None:
            return question
        normalized = normalize_text(question)
        if (
            len(normalized.split()) > 8
            or self._is_self_contained_question(question)
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
    def _implicit_pending_clarification(
        question: str, history: list[Any]
    ) -> PendingClarification | None:
        """Recupera um pedido de esclarecimento ainda visível no histórico."""

        if not is_contextual_follow_up(question, history):
            return None
        prompt_index = None
        prompt = ""
        for index in range(len(history) - 1, -1, -1):
            message = history[index]
            role = (
                message.get("role")
                if isinstance(message, Mapping)
                else getattr(message, "role", getattr(message, "type", None))
            )
            content = (
                message.get("content", "")
                if isinstance(message, Mapping)
                else getattr(message, "content", "")
            )
            normalized = normalize_text(str(content))
            if (
                role in {"assistant", "ai"}
                and "?" in str(content)
                and any(
                    marker in normalized
                    for marker in ("qual", "aspecto", "elemento", "orientacao", "tipo")
                )
            ):
                prompt_index = index
                prompt = str(content).strip()
                break
        if prompt_index is None:
            return None
        if AgentV2._has_new_normative_topic(history[prompt_index + 1 :]):
            return None
        for message in reversed(history[:prompt_index]):
            role = (
                message.get("role")
                if isinstance(message, Mapping)
                else getattr(message, "role", getattr(message, "type", None))
            )
            content = (
                message.get("content", "")
                if isinstance(message, Mapping)
                else getattr(message, "content", "")
            )
            original = str(content).strip()
            if role in {"user", "human"} and is_broad_question(original):
                return PendingClarification(original, prompt)
        return None

    @staticmethod
    def _has_new_normative_topic(history: list[Any]) -> bool:
        for message in history:
            role = (
                message.get("role")
                if isinstance(message, Mapping)
                else getattr(message, "role", getattr(message, "type", None))
            )
            if role not in {"user", "human"}:
                continue
            content = (
                message.get("content", "")
                if isinstance(message, Mapping)
                else getattr(message, "content", "")
            )
            text = str(content).strip()
            if AgentV2._is_self_contained_question(text):
                return True
            if AgentV2._is_explicit_topic_change(text) and has_academic_term(text):
                return True
        return False

    @staticmethod
    def _is_self_contained_question(question: str) -> bool:
        normalized = normalize_text(question)
        if normalized.startswith(("e ", "como fica")):
            return False
        terms = normalized.rstrip("?.!").split()
        return (
            len(terms) >= 3
            and has_academic_term(question)
            and normalized.startswith(("como ", "qual ", "quais ", "segundo "))
        )

    @staticmethod
    def _is_explicit_topic_change(question: str) -> bool:
        return normalize_text(question).startswith(
            ("na verdade", "na realidade", "quero saber", "prefiro saber")
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
