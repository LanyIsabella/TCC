"""Planejamento contextual de consultas documentais."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

BROAD_QUERY_TERMS = {
    "citacoes",
    "formatar",
    "principais",
    "referencias",
    "recuo",
    "margem",
    "margens",
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
FOCUSED_QUERY_STOPWORDS = {
    "a",
    "as",
    "ao",
    "aos",
    "como",
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
    "ficar",
    "fica",
    "ficam",
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
    "quais",
    "que",
    "segundo",
    "ser",
    "sao",
    "uma",
    "um",
    "deve",
    "devem",
    "escrita",
    "escritas",
    "escrito",
    "escritos",
}
TOPIC_FOCUSED_TERMS = {
    "bibliografica",
    "bibliograficas",
    "nome",
    "nomes",
    "referencia",
    "referencias",
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


def focused_query(question: str) -> str:
    """Reduz uma pergunta a termos normativos para uma única recuperação."""

    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in re.findall(r"[\wÀ-ÿ]+", question.casefold()):
        normalized_term = normalize_text(raw_term)
        if (
            len(normalized_term) < 3
            or normalized_term in FOCUSED_QUERY_STOPWORDS
            or normalized_term in seen
        ):
            continue
        terms.append(raw_term)
        seen.add(normalized_term)
    if len(terms) >= 5:
        topic_terms = [
            term
            for term in terms
            if normalize_text(term) in TOPIC_FOCUSED_TERMS
        ]
        core_terms = [
            term
            for term in terms
            if normalize_text(term) not in TOPIC_FOCUSED_TERMS
        ]
        anchors = [
            term
            for term in core_terms
            if normalize_text(term) in {"abnt", "nbr"} or term.isdigit()
        ]
        core_terms = [term for term in core_terms if term not in anchors]
        if topic_terms and core_terms:
            prefix = f"{' '.join(anchors)} " if anchors else ""
            return (
                f"{prefix}({' '.join(core_terms)}) OR "
                f"{' '.join(topic_terms)}"
            ).strip()
    return " ".join(terms)


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

    normalized = normalize_text(question)
    terms = set(re.findall(r"[\wÀ-ÿ]+", normalized))
    project_references_topic = (
        len(terms) <= 20
        and "projeto" in terms
        and any(term.startswith("referenc") for term in terms)
        and any(term.startswith("dissert") for term in terms)
    )
    specific_measure = bool(
        re.match(r"^(?:qual [oa] (?:tamanho|medida)|quanto (?:mede|e))\b", normalized)
    )
    return (
        (len(terms) <= 8 and len(terms & BROAD_QUERY_TERMS) >= 2)
        or ("quais" in terms and len(terms) >= 6)
        or project_references_topic
        or bool(
            len(terms) <= 8
            and not specific_measure
            and terms & BROAD_QUERY_TERMS
            and terms & QUESTION_WORDS
        )
    )


def is_contextual_follow_up(
    question: str, history: list[Any] | None = None
) -> bool:
    """Detecta perguntas curtas que dependem da mensagem anterior."""

    normalized = normalize_text(question)
    terms = normalized.rstrip("?.!").split()
    if not terms or len(terms) > 12:
        return False
    if bool(set(terms) & FOLLOW_UP_TERMS) or normalized.startswith(
        ("e ", "como fica")
    ):
        return True
    if normalized.startswith("como formatar ") and len(terms) >= 8:
        return True
    if _is_underspecified_contextual_question(question):
        return True
    if history and _is_short_clarification_answer(question, history):
        return True
    return normalized.startswith(
        ("qual o tamanho", "qual a medida", "quanto mede")
    )


def contextualize_query(
    question: str,
    history: list[Any] | None = None,
) -> str:
    """Acrescenta contexto mínimo à consulta sem alterar a pergunta original."""

    current = question.strip()
    previous_messages = _user_history(history)
    if (
        _is_underspecified_contextual_question(current)
        and previous_messages
        and is_broad_question(previous_messages[-1])
        and not _has_specific_academic_element(previous_messages[-1])
    ):
        return current
    if not current or not previous_messages or not (
        is_contextual_follow_up(current, history)
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


def _is_underspecified_contextual_question(question: str) -> bool:
    normalized = normalize_text(question).rstrip("?.!")
    return bool(
        re.fullmatch(
            r"(?:qual (?:e |deve ser )?|como deve ser )"
            r"(?:o|a) (?:recuo|margem|fonte|espacamento)",
            normalized,
        )
    )


def _is_short_clarification_answer(
    question: str, history: list[Any]
) -> bool:
    normalized = normalize_text(question).rstrip("?.!")
    terms = normalized.split()
    if not terms or len(terms) > 4:
        return False
    if normalized in {
        "oi",
        "ola",
        "obrigado",
        "obrigada",
        "outro assunto",
        "outra coisa",
        "novo assunto",
    }:
        return False
    if set(terms) & QUESTION_WORDS:
        return False
    clarification_prompt = any(
        str(_message_value(message, "role") or _message_value(message, "type") or "")
        in {"assistant", "ai"}
        and "?" in str(_message_value(message, "content") or "")
        and any(
            marker in normalize_text(str(_message_value(message, "content") or ""))
            for marker in ("qual", "aspecto", "elemento", "orientacao", "tipo")
        )
        for message in history
    )
    prior_academic_context = any(
        str(_message_value(message, "role") or _message_value(message, "type") or "")
        in {"user", "human"}
        and any(
            marker in normalize_text(str(_message_value(message, "content") or ""))
            for marker in (
                "abnt",
                "nbr",
                "referenc",
                "citac",
                "format",
                "margem",
                "recuo",
                "fonte",
                "espacamento",
            )
        )
        for message in history
    )
    return clarification_prompt and prior_academic_context


def _has_specific_academic_element(value: str) -> bool:
    normalized = normalize_text(value)
    return any(
        marker in normalized
        for marker in (
            "direta",
            "indireta",
            "recuo",
            "autoria",
            "autor",
            "element",
            "margem",
            "fonte",
            "espacamento",
            "longa",
            "curta",
        )
    )


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
    normalized = normalize_text(question)
    if "sistema" in normalized and "chamada" in normalized:
        return [
            "sistema de chamada citações ABNT NBR 10520",
            retrieval_question,
        ]
    if not is_broad_question(question):
        return [retrieval_question]

    if (
        "projeto" in normalized
        and "referenc" in normalized
        and "dissert" in normalized
    ):
        return [
            "projeto de pesquisa apresentacao referencias normativas",
            "trabalho academico monografia dissertacao",
        ]
    if "citacoes" in normalized:
        expansion = (
            "citações diretas indiretas chamadas recuo "
            "ABNT NBR 10520"
        )
    elif "referencias" in normalized:
        expansion = (
            "referências elaboração autores elementos essenciais "
            "ABNT NBR 6023"
        )
    elif "formatacao" in normalized:
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
    "focused_query",
    "is_broad_question",
    "is_contextual_follow_up",
    "normalize_text",
    "plan_queries",
]
