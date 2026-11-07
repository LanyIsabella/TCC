"""Contratos e validação das evidências retornadas pelo agente RAG."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

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

EVIDENCE_STOPWORDS = {
    "a",
    "as",
    "ao",
    "aos",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "entre",
    "essa",
    "esse",
    "esta",
    "este",
    "academico",
    "academica",
    "acordo",
    "apresentacao",
    "deve",
    "devem",
    "documento",
    "documentos",
    "elemento",
    "elementos",
    "forma",
    "informacao",
    "item",
    "itens",
    "mais",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "qual",
    "que",
    "se",
    "sem",
    "ser",
    "sao",
    "segundo",
    "sobre",
    "norma",
    "normas",
    "pode",
    "podem",
    "trabalho",
    "trabalhos",
    "um",
    "uma",
}


@dataclass(frozen=True)
class AgentResult:
    """Resposta textual e evidências validadas para a interface."""

    answer: str
    evidences: list[EvidenceRecord]


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


def _tool_payloads(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payloads: list[Mapping[str, Any]] = []
    messages = result.get("messages")
    if not isinstance(messages, list):
        return payloads

    for message in messages:
        role = str(
            _message_value(message, "role")
            or _message_value(message, "type")
            or ""
        )
        name = _message_value(message, "name")
        if role != "tool" or (name and name != "rag_document_search"):
            continue

        content = _message_value(message, "content")
        if isinstance(content, Mapping):
            payload = content
        else:
            text = _normalize_content(content)
            try:
                payload = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if isinstance(payload, Mapping):
            payloads.append(payload)
    return payloads


def _collect_evidences(result: Mapping[str, Any]) -> dict[str, EvidenceRecord]:
    evidences: dict[str, EvidenceRecord] = {}
    for payload in _tool_payloads(result):
        documents = payload.get("documents")
        if not isinstance(documents, list):
            continue
        for document in documents:
            if not isinstance(document, Mapping):
                continue
            raw_evidences = document.get("evidence")
            if not isinstance(raw_evidences, list):
                continue
            for evidence in raw_evidences:
                if not isinstance(evidence, Mapping):
                    continue
                evidence_id = evidence.get("evidence_id")
                text = evidence.get("text")
                if not isinstance(evidence_id, str) or not evidence_id.strip():
                    continue
                if not isinstance(text, str) or not text.strip():
                    continue
                document_metadata = {
                    key: document.get(key)
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
                evidences.setdefault(
                    evidence_id,
                    {
                        **document_metadata,
                        **dict(evidence),
                        "evidence_id": evidence_id.strip(),
                        "text": text,
                    },
                )
    return evidences


def _normalized_terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFD", value.casefold())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return {
        term
        for term in re.findall(r"[\wÀ-ÿ]{4,}", normalized, flags=re.UNICODE)
        if term not in EVIDENCE_STOPWORDS
    }


def looks_like_guarded_answer(answer: str) -> bool:
    normalized = unicodedata.normalize("NFD", answer.casefold())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    normalized = " ".join(normalized.split())
    return (
        ("por favor" in normalized and "pergunta" in normalized)
        or "meu foco" in normalized
        or "fora do escopo" in normalized
        or "nao consigo orientar" in normalized
        or "estou pronto para ajudar" in normalized
        or "sou seu assistente" in normalized
        or "como posso te auxiliar" in normalized
    )


def _fallback_evidence_ids(
    answer: str, available: Mapping[str, EvidenceRecord]
) -> list[str]:
    """Seleciona evidências por sobreposição textual quando o modelo não retorna IDs."""

    if looks_like_guarded_answer(answer):
        return []
    answer_terms = _normalized_terms(answer)
    if len(answer_terms) < 2:
        return []

    ranked: list[tuple[float, int, str]] = []
    for position, (evidence_id, evidence) in enumerate(available.items()):
        evidence_text = " ".join(
            str(evidence.get(key) or "")
            for key in (
                "title",
                "standard_id",
                "version",
                "section",
                "matched_text",
                "text",
            )
        )
        evidence_terms = _normalized_terms(evidence_text)
        overlap = answer_terms & evidence_terms
        if len(overlap) < 2:
            continue
        precision = len(overlap) / max(len(evidence_terms), 1)
        recall = len(overlap) / max(len(answer_terms), 1)
        score = (precision * 0.65) + (recall * 0.35)
        if score >= 0.08:
            ranked.append((score, position, evidence_id))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [evidence_id for _, _, evidence_id in ranked[:3]]


def _supports_answer(answer: str, evidence: EvidenceRecord) -> bool:
    """Aplica uma validação conservadora para IDs escolhidos pelo modelo."""

    if str(evidence.get("matched_text") or "").strip():
        return True
    answer_terms = _normalized_terms(answer)
    evidence_terms = _normalized_terms(
        " ".join(
            str(evidence.get(key) or "")
            for key in ("title", "standard_id", "version", "section", "text")
        )
    )
    overlap = answer_terms & evidence_terms
    return len(overlap) >= 2


def _extract_answer(result: Mapping[str, Any]) -> str:
    structured = _structured_data(result)
    if structured is not None:
        answer = _normalize_content(structured.get("answer"))
        if answer:
            return answer

    messages = result.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            role = str(
                _message_value(message, "role")
                or _message_value(message, "type")
                or ""
            )
            if role in {"assistant", "ai"}:
                answer = _normalize_content(_message_value(message, "content"))
                if answer:
                    return answer
    raise RuntimeError("O agente nao retornou uma resposta do assistente.")


def extract_agent_result(result: Any) -> AgentResult:
    """Extrai a resposta e aceita somente evidências retornadas e selecionadas."""

    if not isinstance(result, Mapping):
        raise RuntimeError("O agente retornou um formato de resposta invalido.")

    answer = _extract_answer(result)
    structured = _structured_data(result)
    available = _collect_evidences(result)
    if structured is None:
        selected_ids = _fallback_evidence_ids(answer, available)
    else:
        selected_ids = structured.get("evidence_ids", [])
        if not isinstance(selected_ids, list):
            selected_ids = []
    validated: list[EvidenceRecord] = []
    seen_ids: set[str] = set()
    rejected_ids: list[str] = []
    for evidence_id in selected_ids:
        if not isinstance(evidence_id, str):
            continue
        evidence_id = evidence_id.strip()
        if evidence_id in seen_ids:
            continue
        if evidence_id not in available:
            rejected_ids.append(evidence_id)
            continue
        if structured is not None and not _supports_answer(
            answer, available[evidence_id]
        ):
            rejected_ids.append(evidence_id)
            continue
        seen_ids.add(evidence_id)
        validated.append(available[evidence_id])

    if rejected_ids:
        logger.warning(
            "evidence_ids_rejected count=%d ids=%s",
            len(rejected_ids),
            rejected_ids[:5],
        )
    logger.info(
        "evidence_selection available=%d selected=%d structured=%s",
        len(available),
        len(validated),
        structured is not None,
    )

    return AgentResult(answer=answer, evidences=validated)


__all__ = [
    "AgentAnswer",
    "AgentResult",
    "EvidenceRecord",
    "extract_agent_result",
    "looks_like_guarded_answer",
]
