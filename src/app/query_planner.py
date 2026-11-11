"""Planejamento contextual de consultas documentais."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

BROAD_QUERY_TERMS = {
    "principais",
    "regras",
    "regra",
    "orientacoes",
    "formatacao",
    "estrutura",
    "organizar",
    "organizacao",
    "quais",
    "trabalho",
    "trabalhos",
}
QUESTION_WORDS = {
    "como",
    "qual",
    "quais",
    "quanto",
    "quando",
    "onde",
    "por",
}
FOLLOW_UP_TERMS = {
    "isso",
    "isto",
    "aquilo",
    "esse",
    "essa",
    "nesse",
    "nessa",
    "disso",
    "dessa",
    "deste",
    "desta",
    "tambem",
    "entao",
}
MAX_CONTEXT_MESSAGE_CHARS = 500


def normalize_text(value: str) -> str:
    """Normaliza caixa, acentos e espaços para o planejamento."""

    normalized = unicodedata.normalize("NFD", value.casefold())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(normalized.split())


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, Mapping):
        return message.get(key)
    return getattr(message, key, None)


def _user_history(history: list[Any] | None) -> list[str]:
    if not history:
        return []
    return [
        str(_message_value(message, "content") or "").strip()
        for message in history
        if str(
            _message_value(message, "role")
            or _message_value(message, "type")
            or ""
        )
        in {"user", "human"}
        and str(_message_value(message, "content") or "").strip()
    ]


def is_broad_question(question: str) -> bool:
    """Identifica perguntas que precisam de maior cobertura de recuperação."""

    terms = set(re.findall(r"[\wÀ-ÿ]+", normalize_text(question)))
    return (
        len(terms & BROAD_QUERY_TERMS) >= 2
        or ("quais" in terms and len(terms) >= 6)
    )


def is_contextual_follow_up(question: str) -> bool:
    """Detecta perguntas curtas que dependem da mensagem anterior."""

    normalized = normalize_text(question)
    terms = normalized.split()
    if not terms or len(terms) > 12:
        return False
    return (
        bool(set(terms) & QUESTION_WORDS)
        or bool(set(terms) & FOLLOW_UP_TERMS)
        or normalized.startswith(("e ", "qual o ", "qual a ", "como fica"))
    )


def contextualize_query(
    question: str,
    history: list[Any] | None = None,
) -> str:
    """Acrescenta contexto mínimo à consulta sem alterar a pergunta original."""

    current = question.strip()
    previous_messages = _user_history(history)
    if not current or not previous_messages or not (
        is_contextual_follow_up(current)
        or _is_clarification_follow_up(current, previous_messages)
    ):
        return current

    previous = next(
        (
            message
            for message in reversed(previous_messages)
            if len(normalize_text(message).split()) >= 2
        ),
        "",
    )
    if not previous:
        return current

    contextual = (
        f"{current} Contexto da pergunta anterior: "
        f"{previous[:MAX_CONTEXT_MESSAGE_CHARS]}"
    )
    logger.info(
        "contextual_query_rewrite current_terms=%d previous_chars=%d",
        len(normalize_text(current).split()),
        len(previous),
    )
    return contextual


def _is_clarification_follow_up(current: str, previous_messages: list[str]) -> bool:
    """Reconhece complemento curto após uma pergunta de esclarecimento."""

    current_terms = normalize_text(current).rstrip("?.!").split()
    if not current_terms or len(current_terms) > 6:
        return False
    previous = normalize_text(previous_messages[-1]).rstrip("?.!")
    return previous in {"como formatar", "como formatar isso", "como formatar isto"}


def plan_queries(
    question: str,
    history: list[Any] | None = None,
) -> list[str]:
    """Gera consultas semânticas preservando a intenção original."""

    question = question.strip()
    if not question:
        return []

    retrieval_question = contextualize_query(question, history)
    if not is_broad_question(question):
        return [retrieval_question]

    normalized = normalize_text(question)
    if "formatacao" in normalized:
        expansion = (
            "trabalhos acadêmicos estrutura formato margens fonte "
            "espaçamento paginação citações referências"
        )
    else:
        expansion = (
            f"{retrieval_question} trabalhos acadêmicos apresentação "
            "requisitos estrutura"
        )
    return [retrieval_question, expansion]


__all__ = [
    "contextualize_query",
    "is_broad_question",
    "is_contextual_follow_up",
    "normalize_text",
    "plan_queries",
]
