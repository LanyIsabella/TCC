"""Contratos mínimos para contexto conversacional efêmero e seguro."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4

from .scope_guard import (
    ScopeDecision,
    classify_messages,
    has_academic_term,
    normalize_text,
)

CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DEFAULT_MAX_CONTEXT_MESSAGES = 12
DEFAULT_MAX_CONTEXT_CHARS = 6_000


class InvalidConversationId(ValueError):
    """Identificador externo ausente, longo demais ou com caracteres perigosos."""


class ConversationIntent(StrEnum):
    """Dimensão interpretativa, independente do encerramento e do grounding."""

    CONVERSATIONAL = "conversational"
    AMBIGUOUS = "ambiguous"
    NORMATIVE_QUERY = "normative_query"
    ACTION_REQUEST = "action_request"
    OUT_OF_SCOPE = "out_of_scope"
    TECHNICAL_FAILURE = "technical_failure"
    UNKNOWN = "unknown"


class CompletionType(StrEnum):
    """Modo pelo qual um turno terminou."""

    CONVERSATIONAL = "conversational"
    CLARIFICATION_REQUESTED = "clarification_requested"
    GROUNDED_ANSWER = "grounded_answer"
    PARTIAL_ANSWER = "partial_answer"
    UNSUPPORTED = "unsupported"
    OUT_OF_SCOPE = "out_of_scope"
    ACTION_UNAVAILABLE = "action_unavailable"
    TECHNICAL_FAILURE = "technical_failure"


class GroundingState(StrEnum):
    """Estado factual, separado da intenção e do encerramento."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONVERSATIONAL = "conversational"


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    needs_clarification: bool = False


@dataclass(frozen=True)
class ConversationTrace:
    conversation_id: str
    turn_id: str | None = None
    intent: str = ConversationIntent.UNKNOWN
    completion_type: str | None = None
    grounding_state: str | None = None
    available_evidence_ids: tuple[str, ...] = ()
    selected_evidence_ids: tuple[str, ...] = ()
    published_evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    tool_provenance: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class PendingClarification:
    """Esclarecimento solicitado no turno anterior, mantido apenas em memória."""

    original_question: str
    prompt: str


@dataclass
class _ConversationState:
    conversation_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    pending_clarification: PendingClarification | None = None


def new_conversation_id() -> str:
    """Gera um identificador não sequencial para uma conversa efêmera."""

    return uuid4().hex


def validate_conversation_id(value: Any) -> str:
    """Valida IDs externos sem aceitar caminhos, controle ou strings vazias."""

    if not isinstance(value, str) or not CONVERSATION_ID_PATTERN.fullmatch(value):
        raise InvalidConversationId("conversation_id invalido.")
    return value


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, Mapping):
        return message.get(key)
    return getattr(message, key, None)


def _public_message(message: Any) -> dict[str, str] | None:
    role = str(_message_value(message, "role") or _message_value(message, "type") or "")
    if role == "human":
        role = "user"
    if role == "ai":
        role = "assistant"
    content = _message_value(message, "content")
    if role not in {"user", "assistant"} or not isinstance(content, str):
        return None
    content = content.strip()
    if not content:
        return None
    return {"role": role, "content": content}


def _copy_messages(messages: Iterable[Any]) -> list[dict[str, str]]:
    return [
        message
        for raw in messages
        if (message := _public_message(raw)) is not None
    ]


def _is_ambiguous_format_request(question: str) -> bool:
    normalized = normalize_text(question).strip("?.! ")
    return normalized in {"como formatar", "como formatar isso", "como formatar isto"}


def _is_action_request(question: str) -> bool:
    normalized = normalize_text(question)
    return (
        any(
            term in normalized
            for term in ("formate ", "formatar para mim", "aplique ")
        )
        and any(
            term in normalized
            for term in ("citacao", "referencia", "documento", "texto")
        )
    )


def _is_conversational(question: str) -> bool:
    normalized = normalize_text(question).strip("?.! ")
    if normalized.replace(",", " ").startswith(("ola ", "oi ")) and any(
        marker in normalized for marker in ("ajuda", "pode ajudar", "preciso de ajuda")
    ):
        return True
    return normalized in {
        "oi",
        "ola",
        "tudo bem",
        "voce entende isso",
        "quem e voce",
        "o que voce faz",
        "obrigado",
        "obrigada",
    }


def interpret_intent(messages: list[Any]) -> IntentDecision:
    """Interpreta intenção com contexto e forma, sem rotear só por palavra."""

    user_messages = _user_messages(messages)
    if not user_messages:
        return IntentDecision(ConversationIntent.OUT_OF_SCOPE)
    question = str(_message_value(user_messages[-1], "content") or "").strip()
    return _classify_intent(messages, question, user_messages)


def _user_messages(messages: list[Any]) -> list[Any]:
    return [
        message
        for message in messages
        if str(_message_value(message, "role") or _message_value(message, "type") or "")
        in {"user", "human"}
    ]


def _classify_intent(
    messages: list[Any], question: str, user_messages: list[Any]
) -> IntentDecision:
    scope = classify_messages(messages)
    if scope == ScopeDecision.GREETING or _is_conversational(question):
        return IntentDecision(ConversationIntent.CONVERSATIONAL)
    if scope == ScopeDecision.OUT_OF_SCOPE:
        return IntentDecision(ConversationIntent.OUT_OF_SCOPE)
    if _is_ambiguous_format_request(question):
        return IntentDecision(ConversationIntent.AMBIGUOUS, needs_clarification=True)
    if _is_action_request(question):
        return IntentDecision(ConversationIntent.ACTION_REQUEST)
    if _has_academic_context(question, user_messages):
        return IntentDecision(ConversationIntent.NORMATIVE_QUERY)
    return IntentDecision(ConversationIntent.UNKNOWN)


def _has_academic_context(question: str, user_messages: list[Any]) -> bool:
    return has_academic_term(question) or any(
        has_academic_term(str(_message_value(message, "content") or ""))
        for message in user_messages[:-1]
    )


def completion_for(intent: str, grounding_status: str | None) -> str:
    fixed = {
        ConversationIntent.CONVERSATIONAL: CompletionType.CONVERSATIONAL,
        ConversationIntent.AMBIGUOUS: CompletionType.CLARIFICATION_REQUESTED,
        ConversationIntent.ACTION_REQUEST: CompletionType.ACTION_UNAVAILABLE,
        ConversationIntent.OUT_OF_SCOPE: CompletionType.OUT_OF_SCOPE,
        ConversationIntent.TECHNICAL_FAILURE: CompletionType.TECHNICAL_FAILURE,
    }
    if intent in fixed:
        return fixed[intent]
    return {
        "supported": CompletionType.GROUNDED_ANSWER,
        "partial": CompletionType.PARTIAL_ANSWER,
        "conversational": CompletionType.CONVERSATIONAL,
    }.get(grounding_status or "", CompletionType.UNSUPPORTED)


class ConversationStore:
    """Armazena conversas somente em memória e limita o contexto enviado ao LLM."""

    def __init__(
        self,
        *,
        max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ) -> None:
        if max_context_messages < 1 or max_context_chars < 1:
            raise ValueError("Os limites de contexto devem ser positivos.")
        self.max_context_messages = max_context_messages
        self.max_context_chars = max_context_chars
        self._states: dict[str, _ConversationState] = {}
        self._lock = RLock()

    def create(self, messages: Iterable[Any] = ()) -> str:
        conversation_id = new_conversation_id()
        with self._lock:
            self._states[conversation_id] = _ConversationState(
                conversation_id, _copy_messages(messages)
            )
        return conversation_id

    def ensure(self, conversation_id: str | None, messages: Iterable[Any] = ()) -> str:
        """Cria ou recupera uma conversa; histórico externo só inicializa IDs novos."""

        if conversation_id is None:
            return self.create(messages)
        conversation_id = validate_conversation_id(conversation_id)
        with self._lock:
            self._states.setdefault(
                conversation_id,
                _ConversationState(conversation_id, _copy_messages(messages)),
            )
        return conversation_id

    def history(self, conversation_id: str) -> list[dict[str, str]]:
        conversation_id = validate_conversation_id(conversation_id)
        with self._lock:
            state = self._states.get(conversation_id)
            return [dict(message) for message in state.messages] if state else []

    def context(self, conversation_id: str) -> list[dict[str, str]]:
        messages = self.history(conversation_id)[-self.max_context_messages :]
        remaining = self.max_context_chars
        bounded: list[dict[str, str]] = []
        for message in reversed(messages):
            content = message["content"][:remaining]
            if not content:
                continue
            bounded.append({"role": message["role"], "content": content})
            remaining -= len(content)
            if remaining <= 0:
                break
        return list(reversed(bounded))

    def append(self, conversation_id: str, user: Any, assistant: Any) -> None:
        conversation_id = validate_conversation_id(conversation_id)
        messages = _copy_messages((user, assistant))
        if len(messages) != 2:
            raise ValueError("Um turno precisa conter usuário e assistente válidos.")
        with self._lock:
            state = self._states.setdefault(
                conversation_id, _ConversationState(conversation_id)
            )
            state.messages.extend(messages)

    def set_pending_clarification(
        self, conversation_id: str, original_question: str, prompt: str
    ) -> None:
        conversation_id = validate_conversation_id(conversation_id)
        original_question = original_question.strip()
        prompt = prompt.strip()
        if not original_question or not prompt:
            raise ValueError("O esclarecimento pendente precisa de conteúdo.")
        with self._lock:
            state = self._states.setdefault(
                conversation_id, _ConversationState(conversation_id)
            )
            state.pending_clarification = PendingClarification(
                original_question, prompt
            )

    def pending_clarification(
        self, conversation_id: str
    ) -> PendingClarification | None:
        conversation_id = validate_conversation_id(conversation_id)
        with self._lock:
            state = self._states.get(conversation_id)
            return state.pending_clarification if state else None

    def clear_pending_clarification(self, conversation_id: str) -> None:
        conversation_id = validate_conversation_id(conversation_id)
        with self._lock:
            state = self._states.get(conversation_id)
            if state:
                state.pending_clarification = None

    def clear(self, conversation_id: str) -> None:
        conversation_id = validate_conversation_id(conversation_id)
        with self._lock:
            self._states.pop(conversation_id, None)


__all__ = [
    "CompletionType",
    "ConversationIntent",
    "ConversationStore",
    "ConversationTrace",
    "GroundingState",
    "IntentDecision",
    "InvalidConversationId",
    "PendingClarification",
    "completion_for",
    "interpret_intent",
    "new_conversation_id",
    "validate_conversation_id",
]
