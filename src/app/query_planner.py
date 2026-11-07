"""Planejamento genérico de consultas, sem regras por documento."""

from __future__ import annotations

import re

BROAD_QUERY_TERMS = {
    "principais", "regras", "regra", "aspectos", "orientações",
    "orientacoes", "formatação", "formatacao", "estrutura", "organizar",
    "organização", "organizacao", "quais", "tcc", "trabalho", "trabalhos",
}


def is_broad_question(question: str) -> bool:
    """Identifica perguntas que precisam de maior cobertura de recuperação."""
    normalized = question.casefold()
    terms = set(re.findall(r"[\wÀ-ÿ]+", normalized))
    return (
        len(terms & BROAD_QUERY_TERMS) >= 2
        or "tcc" in terms
        or ("quais" in terms and len(terms) >= 6)
    )


def plan_queries(question: str) -> list[str]:
    """Gera a consulta original e uma expansão semântica genérica."""
    question = question.strip()
    if not is_broad_question(question):
        return [question]
    normalized = question.casefold()
    if "formatacao" in normalized or "formatação" in normalized:
        expansion = (
            "trabalhos acadêmicos estrutura formato margens fonte "
            "espaçamento paginação"
        )
    else:
        expansion = (
            f"{question} trabalhos acadêmicos apresentação requisitos "
            "estrutura"
        )
    return [question, expansion]


__all__ = ["is_broad_question", "plan_queries"]
