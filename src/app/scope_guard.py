"""Classificação determinística do escopo de atuação do agente."""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Any


class ScopeDecision(StrEnum):
    """Decisões possíveis antes de chamar o modelo."""

    IN_SCOPE = "in_scope"
    GREETING = "greeting"
    OUT_OF_SCOPE = "out_of_scope"


EXPLICIT_ACADEMIC_TERMS = (
    "abnt",
    "nbr",
    "citacao",
    "citacoes",
    "bibliografia",
    "bibliografias",
    "bibliografica",
    "bibliografico",
    "tcc",
    "monografia",
    "dissertacao",
    "tese",
    "artigo academico",
    "artigo cientifico",
    "trabalho academico",
    "trabalho de conclusao",
    "academico",
    "academica",
    "escrita academica",
    "pesquisa academica",
    "projeto de pesquisa",
    "formatacao",
    "paginacao",
    "numeracao",
    "espacamento",
    "palavras-chave",
    "palavra-chave",
    "plagio",
    "revisao textual",
    "estrutura do trabalho",
)
AMBIGUOUS_ACADEMIC_TERMS = (
    "norma",
    "normas",
    "referencia",
    "referencias",
    "resumo",
    "resenha",
    "recensao",
    "sumario",
    "indice",
    "capa",
    "lombada",
    "folha de rosto",
    "margem",
    "secao",
    "metodologia",
    "introducao",
    "conclusao",
    "apresentacao",
)
NON_ACADEMIC_HINTS = (
    "bolo",
    "bitcoin",
    "capital",
    "clima",
    "codigo",
    "doenca",
    "filme",
    "futebol",
    "investimento",
    "jogo",
    "lucro",
    "noticia",
    "politica",
    "programacao",
    "receita",
    "remedio",
    "restaurante",
    "sintoma",
    "serie",
    "tempo",
    "transito",
    "viagem",
)
FOLLOW_UP_TERMS = (
    "isso",
    "essa norma",
    "esse norma",
    "esse trecho",
    "continue",
    "aplique",
    "ajuste",
    "corrija",
    "reescreva",
    "e quanto",
    "e nesse caso",
    "como fica",
)
GREETING_FORMS = {
    "oi",
    "oi tudo bem",
    "ola",
    "bom dia",
    "boa tarde",
    "boa noite",
    "tudo bem",
}

OUT_OF_SCOPE_MESSAGE = (
    "Entendo a pergunta, mas meu foco é ajudar com normas acadêmicas, ABNT, "
    "citações, referências, formatação e estrutura de trabalhos acadêmicos. "
    "Não consigo orientar sobre esse assunto; se quiser, posso ajudar com uma "
    "dúvida acadêmica."
)
GREETING_MESSAGE = (
    "Olá! Posso ajudar com normas ABNT, citações, referências, formatação "
    "e estrutura de trabalhos acadêmicos."
)


def normalize_text(value: str) -> str:
    """Normaliza acentos e caixa para classificação lexical."""
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )


def has_academic_term(value: str) -> bool:
    """Indica se o texto contém vocabulário do escopo acadêmico."""
    normalized = normalize_text(value)
    has_explicit_academic = any(
        term in normalized for term in EXPLICIT_ACADEMIC_TERMS
    )
    has_ambiguous_academic = any(
        term in normalized for term in AMBIGUOUS_ACADEMIC_TERMS
    )
    has_academic = has_explicit_academic or has_ambiguous_academic
    if has_academic and any(
        hint in normalized for hint in NON_ACADEMIC_HINTS
    ) and not has_explicit_academic:
        return False
    return has_academic


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def classify_messages(messages: list[Any]) -> ScopeDecision:
    """Classifica a mensagem atual usando o contexto acadêmico disponível."""
    user_messages = [
        str(_message_value(message, "content") or "")
        for message in messages
        if str(_message_value(message, "role") or _message_value(message, "type") or "")
        in {"user", "human"}
    ]
    if not user_messages:
        return ScopeDecision.OUT_OF_SCOPE

    current = user_messages[-1].strip()
    normalized_current = normalize_text(current)
    greeting_text = normalized_current.replace(",", " ")
    greeting_text = greeting_text.replace("!", " ").replace("?", " ")
    greeting_text = " ".join(greeting_text.replace(".", " ").split())
    if greeting_text in GREETING_FORMS:
        return ScopeDecision.GREETING
    if has_academic_term(current):
        return ScopeDecision.IN_SCOPE

    is_follow_up = any(term in normalized_current for term in FOLLOW_UP_TERMS)
    if is_follow_up and any(
        has_academic_term(message) for message in user_messages[:-1]
    ):
        return ScopeDecision.IN_SCOPE
    return ScopeDecision.OUT_OF_SCOPE


def guarded_response(messages: list[Any], decision: ScopeDecision) -> dict[str, Any]:
    """Cria uma resposta segura sem chamar o modelo para fora do escopo."""
    content = {
        ScopeDecision.GREETING: GREETING_MESSAGE,
        ScopeDecision.OUT_OF_SCOPE: OUT_OF_SCOPE_MESSAGE,
    }[decision]
    return {
        "messages": [
            *messages,
            {"role": "assistant", "content": content},
        ]
    }


__all__ = [
    "GREETING_MESSAGE",
    "OUT_OF_SCOPE_MESSAGE",
    "ScopeDecision",
    "classify_messages",
    "guarded_response",
    "has_academic_term",
    "normalize_text",
]
