"""Ferramenta de recuperação hierárquica para o agente principal."""

from __future__ import annotations

import json

from data.rag_pipeline import search_documents
from langchain.tools import tool


@tool
def rag_document_search(
    question: str, pages_limit: int = 12, documents_limit: int = 5
) -> str:
    """Localiza documentos da Gold e retorna o texto integral dos mais relevantes.

    As páginas recuperadas servem somente para explicar a localização. O campo
    full_text de cada documento é sempre retornado para compor o contexto final.
    """
    try:
        documents = search_documents(question, pages_limit, documents_limit)
    except Exception as error:
        return f"Busca RAG indisponível: {error}"
    return json.dumps(documents, ensure_ascii=False, default=str)


__all__ = ["rag_document_search"]
