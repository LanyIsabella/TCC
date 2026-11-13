"""Contratos e validação das evidências retornadas pelo agente RAG."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .conversation import (
    ConversationIntent,
    ConversationTrace,
    completion_for,
    new_conversation_id,
    validate_conversation_id,
)
from .grounding import (
    INSUFFICIENT_EVIDENCE,
    PARTIAL_LIMITATION,
    GroundingDecision,
    Verifier,
    ground_answer,
    needs_support,
)
from .scope_guard import (
    ACTION_UNAVAILABLE_MESSAGE,
    CLARIFICATION_MESSAGE,
    GREETING_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    ScopeDecision,
    classify_messages,
    normalize_text,
)

logger = logging.getLogger(__name__)


class AgentAnswer(BaseModel):
    """Saída estruturada produzida pelo agente após consultar o RAG."""

    answer: str = Field(
        min_length=1,
        description=(
            "Resposta final em Markdown, sem rodapé, fontes ou referências "
            "documentais adicionadas manualmente."
        ),
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "IDs exatos das evidências do resultado RAG que fundamentam a "
            "resposta. Use uma lista vazia quando não houver evidência."
        ),
    )


EvidenceRecord = dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    """Resposta textual e evidências validadas para a interface."""

    answer: str
    evidences: list[EvidenceRecord]
    grounding_status: str = "unsupported"
    limitations: tuple[str, ...] = ()
    conversation_id: str | None = None
    turn_id: str | None = None
    intent: str = ConversationIntent.UNKNOWN
    completion_type: str | None = None
    available_evidence_ids: tuple[str, ...] = ()
    selected_evidence_ids: tuple[str, ...] = ()
    published_evidence_ids: tuple[str, ...] = ()
    tool_provenance: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()


PUBLIC_EVIDENCE_FIELDS = (
    "evidence_id",
    "conversation_id",
    "document_id",
    "title",
    "standard_id",
    "version",
    "issuer",
    "page_number",
    "section",
    "text",
    "matched_text",
    "turn_id",
    "tool_call_id",
    "execution_id",
    "query",
)


def public_evidence(record: Mapping[str, Any]) -> EvidenceRecord:
    """Remove IDs internos, ranking e caminhos antes da publicação externa."""

    public = {
        key: record[key]
        for key in PUBLIC_EVIDENCE_FIELDS
        if record.get(key) is not None
    }
    omitted = record.get("omitted_content")
    if isinstance(omitted, Mapping):
        safe_omitted = {
            key: omitted[key]
            for key in ("characters", "pages")
            if key in omitted
        }
        if safe_omitted:
            public["omitted_content"] = safe_omitted
    return public


def _public_grounding_status(status: str) -> str:
    return "unsupported" if status == "insufficient" else status


def _grounding_limitations(status: str) -> tuple[str, ...]:
    if status == "partial":
        return (PARTIAL_LIMITATION,)
    if status == "insufficient":
        return (INSUFFICIENT_EVIDENCE,)
    return ()


@dataclass(frozen=True)
class EvidenceTurn:
    id: str
    question: str
    question_sha256: str
    conversation_id: str | None = None


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, Mapping):
        return message.get(key)
    return getattr(message, key, None)


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if isinstance(item, Mapping):
                value = item.get("text") or item.get("content")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        return "\n".join(parts).strip()

    return str(content).strip() if content is not None else ""


def message_role(message: Any) -> str:
    return str(_message_value(message, "role") or _message_value(message, "type") or "")


def begin_turn(payload: Mapping[str, Any]) -> tuple[dict[str, Any], EvidenceTurn]:
    messages = list(payload["messages"])
    index = next(
        i
        for i in range(len(messages) - 1, -1, -1)
        if message_role(messages[i]) in {"user", "human"}
    )
    message = messages[index]
    question = _normalize_content(_message_value(message, "content"))
    raw_conversation_id = payload.get("conversation_id")
    conversation_id = (
        validate_conversation_id(raw_conversation_id)
        if raw_conversation_id is not None
        else new_conversation_id()
    )
    turn = EvidenceTurn(
        uuid4().hex,
        question,
        hashlib.sha256(question.encode()).hexdigest(),
        conversation_id,
    )
    if isinstance(message, Mapping):
        messages[index] = {**message, "id": turn.id}
    elif hasattr(message, "model_copy"):
        messages[index] = message.model_copy(update={"id": turn.id})
    else:
        messages[index] = {
            "role": "user",
            "content": _message_value(message, "content"),
            "id": turn.id,
        }
    return {**payload, "messages": messages}, turn


def bind_turn(
    result: Any, payload: dict[str, Any], turn: EvidenceTurn
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise RuntimeError("O agente retornou um formato de resposta invalido.")
    bound = {**result, "_turn": turn}
    if not any(
        _message_value(message, "id") == turn.id
        for message in result.get("messages", [])
    ):
        # Unbound tool events cannot prove which invocation produced them.
        bound["messages"] = [
            *payload["messages"],
            {"role": "assistant", "content": _extract_answer(result)},
        ]
    return bound


def current_turn_messages(result: Mapping[str, Any]) -> list[Any]:
    messages = result.get("messages", [])
    if not isinstance(messages, list):
        return []
    turn = result.get("_turn")
    index = next(
        (
            i
            for i in range(len(messages) - 1, -1, -1)
            if message_role(messages[i]) in {"user", "human"}
        ),
        -1,
    )
    if isinstance(turn, EvidenceTurn):
        if index < 0:
            return []
        current = messages[index]
        if (
            _message_value(current, "id") != turn.id
            or _normalize_content(_message_value(current, "content")) != turn.question
        ):
            return []
    return messages[index + 1 :]


def _structured_data(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    structured = result.get("structured_response")
    if structured is None:
        return None
    if isinstance(structured, Mapping):
        return structured
    if hasattr(structured, "model_dump"):
        data = structured.model_dump()
        return data if isinstance(data, Mapping) else None
    return None


def _selected_evidence_ids(result: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Retorna a seleção explícita; ausência de estrutura não é uma seleção."""

    identifiers = result.get("_synthesis_evidence_ids")
    if identifiers is None:
        structured = _structured_data(result)
        if structured is None:
            return None
        identifiers = structured.get("evidence_ids", [])
    if not isinstance(identifiers, (list, tuple)):
        return ()
    return tuple(
        dict.fromkeys(
            identifier for identifier in identifiers if isinstance(identifier, str)
        )
    )


def _parse_tool_content(content: Any) -> Mapping[str, Any] | None:
    if isinstance(content, Mapping):
        return content
    try:
        payload = json.loads(_normalize_content(content))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _rag_event(
    message: Any, calls: Mapping[str, Any], bound: bool
) -> Mapping[str, Any] | None:
    name = _message_value(message, "name")
    if message_role(message) != "tool" or name != "rag_document_search":
        return None
    call_id = _message_value(message, "tool_call_id")
    if bound and not call_id:
        return None
    if call_id is not None and calls.get(call_id, {}).get("name") != name:
        return None
    return _parse_tool_content(_message_value(message, "content"))


def _execution(
    turn: Any, call_id: str | None, call: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict:
    args = call.get("args")
    if not isinstance(args, Mapping):
        args = {}
    turn_id = turn.id if isinstance(turn, EvidenceTurn) else None
    query = args.get("question", payload.get("query"))
    execution_seed = json.dumps(
        {
            "conversation_id": turn.conversation_id
            if isinstance(turn, EvidenceTurn)
            else None,
            "turn_id": turn_id,
            "tool_call_id": call_id,
            "query": query,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return {
        "execution_id": hashlib.sha256(execution_seed.encode()).hexdigest(),
        "conversation_id": turn.conversation_id
        if isinstance(turn, EvidenceTurn)
        else None,
        "turn_id": turn_id,
        "question_sha256": turn.question_sha256
        if isinstance(turn, EvidenceTurn)
        else None,
        "tool_call_id": call_id,
        "query": query,
    }


def _tool_payloads(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payloads = []
    calls = {}
    turn = result.get("_turn")
    for message in current_turn_messages(result):
        for call in _message_value(message, "tool_calls") or []:
            if isinstance(call, Mapping):
                calls[call.get("id")] = call
        payload = _rag_event(message, calls, isinstance(turn, EvidenceTurn))
        if payload is not None:
            call_id = _message_value(message, "tool_call_id")
            payloads.append(
                {
                    **payload,
                    "_execution": _execution(
                        turn, call_id, calls.get(call_id, {}), payload
                    ),
                }
            )
    return payloads


def _document_evidences(payload: Mapping[str, Any]):
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        raw = document.get("evidence")
        if isinstance(raw, list):
            for evidence in raw:
                if isinstance(evidence, Mapping):
                    yield document, evidence


def _evidence_record(
    document: Mapping[str, Any], evidence: Mapping[str, Any], execution: dict
) -> EvidenceRecord | None:
    identifier, text = evidence.get("evidence_id"), evidence.get("text")
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    metadata = {
        key: document[key]
        for key in (
            "document_id",
            "rag_document_id",
            "title",
            "standard_id",
            "version",
            "issuer",
        )
        if document.get(key) is not None
    }
    record = {
        **metadata,
        **evidence,
        "evidence_id": identifier.strip(),
        "text": text,
        **execution,
    }
    omitted_content = document.get("omitted_content")
    if isinstance(omitted_content, Mapping):
        record["omitted_content"] = dict(omitted_content)
    return record


def _collect_evidences(result: Mapping[str, Any]) -> dict[str, EvidenceRecord]:
    evidences = {}
    for payload in _tool_payloads(result):
        if payload.get("status") != "success" or payload.get("evidence_found") is False:
            continue
        for document, evidence in _document_evidences(payload):
            record = _evidence_record(document, evidence, payload.get("_execution", {}))
            if record is not None:
                evidences.setdefault(record["evidence_id"], record)
    return evidences


def looks_like_guarded_answer(answer: str) -> bool:
    normalized = normalize_text(answer)
    normalized = " ".join(normalized.split())
    return (
        ("por favor" in normalized and "pergunta" in normalized)
        or "meu foco" in normalized
        or "fora do escopo" in normalized
        or "nao consigo orientar" in normalized
        or "estou pronto para ajudar" in normalized
        or "posso ajudar" in normalized
        or "sou seu assistente" in normalized
        or "como posso te auxiliar" in normalized
    )


def _has_normative_assertion(answer: str) -> bool:
    normalized = normalize_text(answer)
    return bool(
        (
            re.search(
                r"\b(?:deve\w*|obrigatori\w*|permitid\w*|proibid\w*|"
                r"vedad\w*|necessari\w*|exig\w*|requer\w*|mede|medir)\b",
                normalized,
            )
            and re.search(
                r"\b(?:margem|fonte|citac\w*|referenc\w*|recuo|espac\w*|"
                r"norma\w*|regra\w*|abnt|nbr)\b",
                normalized,
            )
        )
        or re.search(
            r"\b(?:\d+(?:[.,]\d+)?|um|uma|dois|duas|tres|três|"
            r"quatro|cinco|seis|sete|oito|nove|dez)\s*"
            r"(?:cm|mm|pt|pontos?|centimetros?|milimetros?)\b",
            normalized,
        )
        or re.search(
            r"\b(citac\w*|referenc\w*|margens?|folha|resumo|regra\w*|"
            r"norma\w*)\b[^.!?]{0,100}\b(fica\w*|ficam\w*|usa\w*|"
            r"utiliza\w*|apresenta\w*|aparece\w*|aparecem\w*|"
            r"consiste\w*|corresponde\w*|seguem?)\b",
            normalized,
        )
    )


def _classified_normative_assertion(
    classifier: Callable[[str, list[str]], Any] | None,
    question: str,
    answer: str,
) -> bool | None:
    if classifier is None:
        return None
    try:
        raw = classifier(question, [answer])
        if isinstance(raw, str):
            raw = json.loads(raw)
        entries = raw.get("claims", []) if isinstance(raw, Mapping) else []
        if not isinstance(entries, list) or len(entries) != 1:
            return None
        if not any(
            isinstance(item, Mapping)
            and str(item.get("index")) == "0"
            and str(item.get("kind") or "").casefold()
            in {"normative", "general", "example"}
            for item in entries
        ):
            return None
        return str(entries[0].get("kind") or "").casefold() == "normative"
    except Exception:
        logger.warning("grounding_claim_classification_invalid=True")
        return None


def _is_safe_non_normative_response(
    answer: str, intent: ConversationIntent, completion_type: str | None
) -> bool:
    normalized = " ".join(normalize_text(answer).split())
    known_safe = {
        " ".join(normalize_text(message).split())
        for message in (
            ACTION_UNAVAILABLE_MESSAGE,
            CLARIFICATION_MESSAGE,
            GREETING_MESSAGE,
            OUT_OF_SCOPE_MESSAGE,
        )
    }
    if normalized in known_safe:
        return True
    if (
        intent == ConversationIntent.AMBIGUOUS
        and completion_type == "clarification_requested"
        and answer.rstrip().endswith("?")
        and not _has_unsafe_clarification_preface(answer)
    ):
        return True
    if intent == ConversationIntent.CONVERSATIONAL and re.fullmatch(
        r"(?:ola|oi|bom dia|boa tarde|boa noite)[!.]?\s*"
        r"(?:posso ajudar(?: com seu tcc)?[!.]?)?",
        normalized,
    ):
        return True
    if intent == ConversationIntent.CONVERSATIONAL and re.fullmatch(
        r"(?:ola|oi|bom dia|boa tarde|boa noite)[!.]?\s*"
        r"posso ajudar com "
        r"(?:normas abnt|citacoes|referencias|formatacao|"
        r"estrutura de trabalhos academicos)"
        r"(?:\s*(?:,|e)\s*(?:normas abnt|citacoes|referencias|formatacao|"
        r"estrutura de trabalhos academicos))*[!.]?",
        normalized,
    ):
        return True
    return False


def _has_unsafe_clarification_preface(answer: str) -> bool:
    prefix = answer.rstrip()[:-1].strip()
    clauses = [
        clause.strip()
        for clause in re.split(r"(?<=[.!?])\s+", prefix)
        if clause.strip()
    ]
    preface = " ".join(clauses[:-1]).strip()
    if not preface:
        return False
    return not _is_safe_non_normative_response(
        preface, ConversationIntent.CONVERSATIONAL, None
    )


def _is_interrogative_clause(clause: str) -> bool:
    normalized = " ".join(normalize_text(clause).split())
    return bool(
        re.match(
            r"^(?:voce\s+(?:quer|gostaria|sabe|pode|deveria)|"
            r"qual|como|quando|onde|por que)\b",
            normalized,
        )
    )


def _is_isolated_clarification_question(answer: str) -> bool:
    parts = [part.strip() for part in answer.splitlines() if part.strip()]
    if not parts:
        return False
    for part in parts:
        if not part.endswith("?"):
            return False
        body = part[:-1].rstrip()
        if re.search(r"[.!;]", body):
            return False
        if "," in body:
            clauses = [clause.strip() for clause in body.split(",")]
            normative_clauses = [
                index
                for index, clause in enumerate(clauses)
                if _has_normative_assertion(clause)
            ]
            if any(index > 0 for index in normative_clauses):
                return False
            if normative_clauses and not _is_interrogative_clause(clauses[0]):
                return False
    return True


def _extract_answer(result: Mapping[str, Any]) -> str:
    structured = _structured_data(result)
    if structured is not None:
        answer = _normalize_content(structured.get("answer"))
        if answer:
            return answer

    for message in reversed(current_turn_messages(result)):
        if message_role(message) in {"assistant", "ai"}:
            answer = _normalize_content(_message_value(message, "content"))
            if answer:
                return answer
    raise RuntimeError("O agente nao retornou uma resposta do assistente.")


@dataclass(frozen=True)
class GroundingSeal:
    fingerprint: str
    decision: GroundingDecision


def last_user_question(messages: list[Any]) -> str:
    message = next(
        (m for m in reversed(messages) if message_role(m) in {"user", "human"}), None
    )
    return _normalize_content(_message_value(message, "content"))


def _fingerprint(
    result: Mapping[str, Any], answer: str, available: Mapping[str, Any]
) -> str:
    turn = result.get("_turn")
    data = {
        "turn_id": turn.id if isinstance(turn, EvidenceTurn) else None,
        "question": last_user_question(result.get("messages", [])),
        "answer": answer,
        "evidences": available,
        "selected_evidence_ids": _selected_evidence_ids(result),
        "normative_context": _normative_context(result),
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _normative_context(result: Mapping[str, Any]) -> bool:
    conversation = result.get("_conversation")
    if isinstance(conversation, Mapping):
        mode = str(conversation.get("response_mode") or "")
        if mode == "general":
            return False
        if mode in {"normative", "mixed"}:
            return True
    if isinstance(conversation, Mapping) and conversation.get("intent") in {
        ConversationIntent.CONVERSATIONAL,
        ConversationIntent.AMBIGUOUS,
        ConversationIntent.ACTION_REQUEST,
        ConversationIntent.OUT_OF_SCOPE,
    }:
        return False
    if (
        isinstance(conversation, Mapping)
        and conversation.get("intent") == ConversationIntent.NORMATIVE_QUERY
    ):
        return True
    return classify_messages(result.get("messages", [])) == ScopeDecision.IN_SCOPE


def _trace_metadata(
    result: Mapping[str, Any],
    decision: GroundingDecision,
    available: Mapping[str, EvidenceRecord],
) -> ConversationTrace:
    conversation = result.get("_conversation")
    conversation = conversation if isinstance(conversation, Mapping) else {}
    turn = result.get("_turn")
    selected = _selected_evidence_ids(result)
    published = tuple(decision.evidence_ids)
    status = _public_grounding_status(decision.status)
    intent = str(conversation.get("intent") or ConversationIntent.UNKNOWN)
    return ConversationTrace(
        conversation_id=str(
            conversation.get("conversation_id")
            or (turn.conversation_id if isinstance(turn, EvidenceTurn) else "")
            or ""
        ),
        turn_id=(
            turn.id
            if isinstance(turn, EvidenceTurn)
            else str(conversation.get("turn_id") or "") or None
        ),
        intent=intent,
        completion_type=str(
            conversation.get("completion_type") or completion_for(intent, status)
        ),
        grounding_state=status,
        available_evidence_ids=tuple(available),
        selected_evidence_ids=tuple(selected or ()),
        published_evidence_ids=published,
        limitations=_grounding_limitations(decision.status),
        errors=tuple(conversation.get("errors") or ()),
        tool_provenance=tuple(
            execution
            for payload in _tool_payloads(result)
            if isinstance((execution := payload.get("_execution")), Mapping)
        ),
    )


def _decision(
    result: Mapping[str, Any],
    verifier: Verifier | None = None,
    claim_classifier: Callable[[str, list[str]], Any] | None = None,
    question: str | None = None,
) -> GroundingDecision:
    answer = _extract_answer(result)
    available = _collect_evidences(result)
    selected = _selected_evidence_ids(result)
    original_question = last_user_question(result.get("messages", []))
    question = original_question if question is None else question
    seal = result.get("_grounding")
    if (
        question == original_question
        and isinstance(seal, GroundingSeal)
        and seal.fingerprint == _fingerprint(result, answer, available)
    ):
        return seal.decision
    support_available = (
        available
        if selected is None
        else {
            identifier: available[identifier]
            for identifier in selected
            if identifier in available
        }
    )
    conversation = result.get("_conversation")
    v2_normative_turn = (
        isinstance(conversation, Mapping)
        and conversation.get("intent") == ConversationIntent.NORMATIVE_QUERY
    )
    if (
        selected is None
        and available
        and _normative_context(result)
        and v2_normative_turn
        and not result.get("_textual_synthesis")
    ):
        # Texto livre após a tool não é uma seleção verificável do agente.
        support_available = {}
    intent = conversation.get("intent") if isinstance(conversation, Mapping) else None
    if intent in {
        ConversationIntent.CONVERSATIONAL,
        ConversationIntent.AMBIGUOUS,
        ConversationIntent.ACTION_REQUEST,
        ConversationIntent.OUT_OF_SCOPE,
    }:
        completion_type = conversation.get("completion_type")
        clarification_question = (
            intent == ConversationIntent.AMBIGUOUS
            and answer.rstrip().endswith("?")
        )
        explicitly_non_normative = (
            intent in {
                ConversationIntent.ACTION_REQUEST,
                ConversationIntent.OUT_OF_SCOPE,
            }
            or completion_type
            in {"action_unavailable", "out_of_scope"}
            or (
                completion_type == "clarification_requested"
                and answer.rstrip().endswith("?")
            )
            or clarification_question
        )
        classified_normative = _classified_normative_assertion(
            claim_classifier, question, answer
        )
        normative_assertion = _has_normative_assertion(answer) or (
            classified_normative is True
        )
        safe_non_normative = _is_safe_non_normative_response(
            answer, intent, completion_type
        )
        clarification_source = (
            conversation.get("clarification_source")
            if isinstance(conversation, Mapping)
            else None
        )
        trusted_clarification = clarification_source in {
            "structured",
            "legacy_structured",
        }
        general_mode = (
            isinstance(conversation, Mapping)
            and str(conversation.get("response_mode") or "") == "general"
        )
        untrusted_clarification = (
            intent == ConversationIntent.AMBIGUOUS
            and completion_type == "clarification_requested"
            and not trusted_clarification
        )
        if trusted_clarification:
            isolated_question = (
                clarification_question
                and _is_isolated_clarification_question(answer)
            )
            if isolated_question:
                normative_assertion = False
            safe_non_normative = not normative_assertion
        if (
            untrusted_clarification
            or normative_assertion
            or (
                not general_mode
                and not safe_non_normative
                and needs_support(answer, question)
            )
        ):
            decision = GroundingDecision(INSUFFICIENT_EVIDENCE, (), "insufficient")
        elif (
            explicitly_non_normative
            or safe_non_normative
            or general_mode
            or not needs_support(answer, question)
        ):
            decision = GroundingDecision(answer, (), "conversational")
        else:
            decision = GroundingDecision(INSUFFICIENT_EVIDENCE, (), "insufficient")
    else:
        decision = ground_answer(
            answer,
            support_available,
            question,
            verifier,
            normative_context=_normative_context(result),
            response_mode=(
                str(conversation.get("response_mode"))
                if isinstance(conversation, Mapping)
                else None
            ),
            claim_classifier=claim_classifier,
        )
    logger.info(
        "grounding status=%s available=%d supported=%d",
        decision.status,
        len(available),
        len(decision.evidence_ids),
    )
    return decision


def finalize_grounding(
    result: dict[str, Any],
    verifier: Verifier | None = None,
    claim_classifier: Callable[[str, list[str]], Any] | None = None,
    *,
    question: str | None = None,
) -> dict[str, Any]:
    """Só publica a decisão central; eventos internos mantêm os pares de tools."""
    try:
        decision = _decision(
            result, verifier, claim_classifier, question=question
        )
    except RuntimeError:
        decision = GroundingDecision(INSUFFICIENT_EVIDENCE, (), "insufficient")
    current_ids = {id(message) for message in current_turn_messages(result)}
    messages = []
    for message in result.get("messages", []):
        if id(message) in current_ids and message_role(message) in {"ai", "assistant"}:
            if not _message_value(message, "tool_calls"):
                continue
            message = _without_content(message)
        messages.append(message)
    finalized = {
        **result,
        "messages": [*messages, {"role": "assistant", "content": decision.answer}],
        "structured_response": AgentAnswer(
            answer=decision.answer, evidence_ids=list(decision.evidence_ids)
        ),
    }
    finalized["_grounding"] = GroundingSeal(
        _fingerprint(finalized, decision.answer, _collect_evidences(finalized)),
        decision,
    )
    return finalized


def _without_content(message: Any) -> Any:
    if isinstance(message, Mapping):
        return {**message, "content": ""}
    return message.model_copy(update={"content": ""})


def extract_agent_result(result: Any, *, question: str | None = None) -> AgentResult:
    """Aplica a mesma política para UI, API, terminal e adaptadores isolados."""
    if not isinstance(result, Mapping):
        raise RuntimeError("O agente retornou um formato de resposta invalido.")
    decision = _decision(result, question=question)
    available = _collect_evidences(result)
    trace = _trace_metadata(result, decision, available)
    return AgentResult(
        decision.answer,
        [available[key] for key in decision.evidence_ids],
        grounding_status=_public_grounding_status(decision.status),
        limitations=_grounding_limitations(decision.status),
        conversation_id=trace.conversation_id or None,
        turn_id=trace.turn_id,
        intent=trace.intent,
        completion_type=trace.completion_type,
        available_evidence_ids=trace.available_evidence_ids,
        selected_evidence_ids=trace.selected_evidence_ids,
        published_evidence_ids=trace.published_evidence_ids,
        tool_provenance=tuple(dict(item) for item in trace.tool_provenance),
        errors=trace.errors,
    )


__all__ = [
    "AgentAnswer",
    "AgentResult",
    "EvidenceRecord",
    "extract_agent_result",
    "looks_like_guarded_answer",
    "public_evidence",
]
