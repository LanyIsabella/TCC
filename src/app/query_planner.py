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
FOCUSED_TOPIC_TERMS = {
    "citacao",
    "citacoes",
    "referencia",
    "referencias",
    "lombada",
    "lombadas",
    "margem",
    "margens",
    "paginacao",
    "pagina",
    "sumario",
    "resumo",
    "capa",
    "folha",
    "folhas",
    "secao",
    "secoes",
}
ACADEMIC_SCOPE_TERMS = {
    "academico",
    "academicos",
    "tcc",
    "trabalho",
    "trabalhos",
    "monografia",
    "dissertacao",
    "tese",
}
PLANNER_STOPWORDS = {
    "a",
    "as",
    "ao",
    "aos",
    "com",
    "como",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "essa",
    "esse",
    "esta",
    "este",
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
    "uma",
    "um",
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
    """Normaliza caixa, acentos e espacos para o planejamento."""

    normalized = unicodedata.normalize("NFD", value.casefold())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(normalized.split())


def meaningful_terms(value: str) -> set[str]:
    """Retorna termos uteis para comparar intencao, contexto e resposta."""

    terms = set(re.findall(r"[\wÀ-ÿ]+", normalize_text(value)))
    return {
        term
        for term in terms
        if len(term) >= 3 and term not in PLANNER_STOPWORDS
    }


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
    """Identifica perguntas que precisam de maior cobertura de recuperacao."""

    normalized = normalize_text(question)
    terms = set(re.findall(r"[\wÀ-ÿ]+", normalized))
    if re.search(r"\b(?:abnt\s+)?nbr\s*\d{3,5}", normalized):
        return False

    focused_terms = terms & FOCUSED_TOPIC_TERMS
    has_academic_scope = bool(terms & ACADEMIC_SCOPE_TERMS)
    if focused_terms and not (
        "formatacao" in terms and has_academic_scope
    ):
        return False
    return (
        len(terms & BROAD_QUERY_TERMS) >= 2
        or ("quais" in terms and len(terms) >= 6)
    )


def _academic_scope_terms(question: str) -> set[str]:
    terms = meaningful_terms(question)
    if "tcc" in terms:
        terms.update({"trabalho", "trabalhos", "academico", "academicos"})
    if "formatacao" in terms:
        terms.add("apresentacao")
    return terms


def _term_matches(left: str, right: str) -> bool:
    if left == right:
        return True
    prefix_length = max(4, min(len(left), len(right)) - 2)
    return left[:prefix_length] == right[:prefix_length]


def answer_matches_question(question: str, answer: str) -> bool:
    """Verifica aderencia minima sem pedir uma segunda avaliacao ao modelo."""

    if not answer.strip() or not is_broad_question(question):
        return bool(answer.strip())

    expected_terms = _academic_scope_terms(" ".join(plan_queries(question)))
    answer_terms = meaningful_terms(answer)
    overlap = {
        expected
        for expected in expected_terms
        if any(_term_matches(expected, actual) for actual in answer_terms)
    }
    topical_terms = expected_terms - {
        "principais",
        "regras",
        "formatacao",
        "apresentacao",
        "trabalho",
        "trabalhos",
        "academico",
        "academicos",
    }
    topical_overlap = overlap & topical_terms
    base_match = len(topical_overlap) >= 2 or (
        len(overlap) >= 3 and bool(topical_overlap)
    )
    if not base_match:
        return False
    planned_queries = plan_queries(question)
    if len(planned_queries) <= 2:
        return True
    facet_stopwords = {
        "abnt",
        "academico",
        "academicos",
        "apresentacao",
        "pre",
        "pos",
        "textuais",
        "trabalho",
        "trabalhos",
    }
    facet_count = 0
    for facet_query in planned_queries[1:]:
        facet_terms = meaningful_terms(facet_query) - facet_stopwords
        if any(
            _term_matches(expected, actual)
            for expected in facet_terms
            for actual in answer_terms
        ):
            facet_count += 1
    return facet_count >= 2


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
    """Acrescenta contexto minimo a consulta sem alterar a pergunta original."""

    current = question.strip()
    previous_messages = _user_history(history)
    if not current or not previous_messages or not is_contextual_follow_up(current):
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


def plan_queries(
    question: str,
    history: list[Any] | None = None,
) -> list[str]:
    """Gera consultas semanticas preservando a intencao original."""

    question = question.strip()
    if not question:
        return []

    retrieval_question = contextualize_query(question, history)
    if not is_broad_question(question):
        return [retrieval_question]

    normalized = normalize_text(question)
    if "formatacao" in normalized:
        queries = [
            retrieval_question,
            (
                "trabalhos acadêmicos apresentação estrutura elementos "
                "pré-textuais textuais pós-textuais"
            ),
            (
                "trabalhos acadêmicos formatação margens fonte tamanho "
                "espaçamento paginação anverso verso"
            ),
            (
                "trabalhos acadêmicos citações referências "
                "ABNT NBR 10520 ABNT NBR 6023"
            ),
        ]
    else:
        queries = [
            retrieval_question,
            (
                f"{retrieval_question} trabalhos acadêmicos apresentação "
                "requisitos estrutura"
            ),
        ]
    return list(dict.fromkeys(queries))


__all__ = [
    "answer_matches_question",
    "contextualize_query",
    "is_broad_question",
    "is_contextual_follow_up",
    "meaningful_terms",
    "normalize_text",
    "plan_queries",
]
