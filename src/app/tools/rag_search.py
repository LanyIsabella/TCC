"""Ferramenta de recuperação hierárquica para o agente principal."""

from __future__ import annotations

import json
import logging
from typing import Any

from data.rag_pipeline import search_documents
from langchain.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
MAX_FULL_TEXT_CHARS = 6_000
MAX_PAGE_TEXT_CHARS = 1_800
MAX_CONTEXT_CHARS = 5_000


class RagDocumentSearchInput(BaseModel):
    """Parâmetros aceitos pela ferramenta de consulta documental."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=1_000,
        description="Pergunta ou tema pesquisado nos documentos acadêmicos.",
    )
    pages_limit: int = Field(
        default=6,
        ge=1,
        le=50,
        description="Quantidade máxima de páginas candidatas por mecanismo.",
    )
    documents_limit: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Quantidade máxima de documentos candidatos retornados.",
    )


def _compact_document(document: Any) -> dict[str, Any] | None:
    """Valida e reduz um resultado do RAG para o contexto do modelo."""
    if not isinstance(document, dict):
        return None

    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    title = str(
        document.get("title") or metadata.get("title") or "Documento sem título"
    ).strip()

    pages: list[int] = []
    raw_pages = document.get("pages")
    if isinstance(raw_pages, (list, tuple)):
        for page in raw_pages:
            try:
                number = int(page)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in pages:
                pages.append(number)

    matched_pages: list[dict[str, Any]] = []
    raw_matched_pages = document.get("matched_pages")
    if isinstance(raw_matched_pages, list):
        for item in raw_matched_pages:
            if not isinstance(item, dict):
                continue
            try:
                page_number = int(item.get("page_number"))
            except (TypeError, ValueError):
                continue
            if page_number <= 0:
                continue
            matched_pages.append(
                {
                    "page_number": page_number,
                    "direct_match": bool(item.get("direct_match", False)),
                }
            )

    page_context: list[dict[str, Any]] = []
    context_chars = 0
    raw_page_context = document.get("page_context")
    if isinstance(raw_page_context, list):
        def page_sort_key(item: dict[str, Any]) -> tuple[bool, int]:
            try:
                number = int(item.get("page_number", 0) or 0)
            except (TypeError, ValueError):
                number = 0
            return (not bool(item.get("direct_match", False)), number)

        ordered_page_context = sorted(
            (item for item in raw_page_context if isinstance(item, dict)),
            key=page_sort_key,
        )
        for item in ordered_page_context:
            try:
                page_number = int(item.get("page_number"))
            except (TypeError, ValueError):
                continue
            text = str(item.get("page_text") or "").strip()
            if page_number <= 0 or not text or context_chars >= MAX_CONTEXT_CHARS:
                continue
            remaining = MAX_CONTEXT_CHARS - context_chars
            text = text[: min(MAX_PAGE_TEXT_CHARS, remaining)].strip()
            if not text:
                continue
            page_context.append(
                {
                    "page_number": page_number,
                    "direct_match": bool(item.get("direct_match", False)),
                    "page_text": text,
                }
            )
            context_chars += len(text)

    full_text = document.get("full_text")
    if isinstance(full_text, str) and len(full_text) > MAX_FULL_TEXT_CHARS:
        full_text = None
    elif not isinstance(full_text, str):
        full_text = None

    if not full_text and not page_context:
        return None

    compact: dict[str, Any] = {
        "document_id": document.get("document_id"),
        "title": title,
        "standard_id": metadata.get("id"),
        "version": document.get("version") or metadata.get("version"),
        "issuer": metadata.get("issuer"),
        "status": metadata.get("status"),
        "source_extractor": document.get("source_extractor"),
        "quality_score": document.get("quality_score"),
        "pages": pages,
        "matched_pages": matched_pages,
        "full_text": full_text,
        "page_context": page_context,
        "context_warning": document.get("context_warning"),
    }
    return compact


def _validated_result(
    documents: Any,
    question: str,
) -> dict[str, Any]:
    """Monta um contrato estável para o modelo consumir."""
    if not isinstance(documents, list):
        raise ValueError("A busca RAG não retornou uma lista de documentos.")

    compact_documents = [
        compact
        for document in documents
        if (compact := _compact_document(document)) is not None
    ]
    if not compact_documents:
        return {
            "status": "no_evidence",
            "evidence_found": False,
            "query": question,
            "documents_found": 0,
            "documents": [],
            "message": "Nenhuma evidência textual correspondente foi localizada.",
        }
    return {
        "status": "success",
        "evidence_found": True,
        "query": question,
        "documents_found": len(compact_documents),
        "documents": compact_documents,
    }
@tool(args_schema=RagDocumentSearchInput)
def rag_document_search(
    question: str,
    pages_limit: int = 6,
    documents_limit: int = 1,
) -> str:
    """Pesquisa normas acadêmicas nos documentos indexados.

    Use quando a resposta depender das normas armazenadas no projeto. A busca
    combina identificadores exatos de normas, texto integral indexado e
    embeddings de páginas.

    O resultado informa os documentos encontrados, as páginas responsáveis
    pela recuperação e as páginas vizinhas. O documento mais relevante é
    retornado integralmente somente quando couber no orçamento de contexto.
    """
    try:
        documents = search_documents(
            question=question,
            pages_limit=pages_limit,
            documents_limit=documents_limit,
            full_documents_limit=0,
            neighbor_radius=0,
        )
    except Exception:
        logger.exception("Erro durante a busca RAG.")
        return json.dumps(
            {
                "status": "error",
                "evidence_found": False,
                "message": "A busca documental está indisponível.",
                "documents": [],
            },
            ensure_ascii=False,
        )

    try:
        result = _validated_result(documents, question)
    except (TypeError, ValueError) as error:
        logger.exception("Resultado RAG inválido: %s", error)
        result = {
            "status": "error",
            "evidence_found": False,
            "query": question,
            "documents_found": 0,
            "documents": [],
            "message": "A busca retornou um formato documental inválido.",
        }
    return json.dumps(result, ensure_ascii=False, default=str)


__all__ = ["rag_document_search"]
