"""Ferramenta de recuperação hierárquica para o agente principal."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from typing import Any

from data.rag_pipeline import search_documents
from langchain.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
MAX_FULL_TEXT_CHARS = 6_000
MAX_PAGE_TEXT_CHARS = 1_800
MAX_CONTEXT_CHARS = 5_000
MATCH_WINDOW_CHARS = 240
PAGE_MARKER_PATTERN = re.compile(r"<<<PÁGINA\s+(\d+)(?:\s+—[^>]*)?>>>")
MATCH_TERM_PATTERN = re.compile(r"[\wÀ-ÿ]{4,}", flags=re.UNICODE)

MATCH_STOPWORDS = {
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
    "entre",
    "essa",
    "esse",
    "esta",
    "este",
    "fazer",
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
    "sem",
    "sobre",
    "uma",
    "um",
}


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


def _evidence_identity(
    document: dict[str, Any], title: str, document_id: Any
) -> str:
    """Gera a parte estável do identificador de uma evidência."""

    raw_identity = (
        document.get("id")
        or document.get("rag_document_id")
        or document_id
        or title
    )
    identity = str(raw_identity).strip()
    if not identity:
        identity = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"document:{identity}"


def _full_text_parts(full_text: str) -> list[tuple[int | None, str]]:
    """Divide o texto integral nos marcadores de página já persistidos."""

    markers = list(PAGE_MARKER_PATTERN.finditer(full_text))
    if not markers:
        return [(None, full_text)]

    parts: list[tuple[int | None, str]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(full_text)
        text = full_text[marker.end() : end].strip()
        if text:
            parts.append((int(marker.group(1)), text))
    return parts


def _normalized_with_positions(value: str) -> tuple[str, list[int]]:
    """Normaliza acentos sem perder a posição no texto original."""

    normalized: list[str] = []
    positions: list[int] = []
    for position, character in enumerate(value):
        decomposed = unicodedata.normalize("NFD", character.casefold())
        for item in decomposed:
            if unicodedata.category(item) == "Mn":
                continue
            normalized.append(item)
            positions.append(position)
    return "".join(normalized), positions


def _match_prefixes(question: str) -> list[str]:
    normalized_question, _ = _normalized_with_positions(question)
    prefixes: set[str] = set()
    for term in MATCH_TERM_PATTERN.findall(normalized_question):
        if term in MATCH_STOPWORDS:
            continue
        prefix_length = max(4, len(term) - 2)
        prefixes.add(term[:prefix_length])
    return sorted(prefixes, key=lambda value: (-len(value), value))


def _matched_text(text: str, question: str) -> str | None:
    """Retorna um recorte original em torno do primeiro match da consulta."""

    prefixes = _match_prefixes(question)
    if not prefixes:
        return None

    normalized_text, positions = _normalized_with_positions(text)
    pattern = re.compile(
        rf"\b(?:{'|'.join(re.escape(prefix) for prefix in prefixes)})\w*",
        flags=re.UNICODE,
    )
    match = pattern.search(normalized_text)
    if match is None:
        return None

    original_start = positions[match.start()]
    original_end = positions[match.end() - 1] + 1
    window_start = max(0, original_start - MATCH_WINDOW_CHARS // 2)
    window_end = min(len(text), original_end + MATCH_WINDOW_CHARS // 2)
    return text[window_start:window_end].strip()


def _compact_document(
    document: Any,
    question: str = "",
) -> dict[str, Any] | None:
    """Valida e reduz um resultado do RAG para o contexto do modelo."""
    if not isinstance(document, dict):
        return None

    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    title = str(
        document.get("title") or metadata.get("title") or "Documento sem título"
    ).strip()
    document_id = document.get("document_id")
    rag_document_id = document.get("id") or document.get("rag_document_id")
    default_section = document.get("section") or metadata.get("section")
    default_section = str(default_section).strip() if default_section else None

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
            page_item = {
                "page_number": page_number,
                "direct_match": bool(item.get("direct_match", False)),
                "page_text": text,
            }
            if item.get("section"):
                page_item["section"] = str(item["section"]).strip()
            page_context.append(page_item)
            context_chars += len(text)

    full_text = document.get("full_text")
    if isinstance(full_text, str) and len(full_text) > MAX_FULL_TEXT_CHARS:
        full_text = None
    elif not isinstance(full_text, str):
        full_text = None

    if not full_text and not page_context:
        return None

    evidence_identity = _evidence_identity(document, title, document_id)
    evidence: list[dict[str, Any]] = []
    seen_text: set[str] = set()

    def add_evidence(
        text: str,
        page_number: int | None,
        *,
        section: Any = None,
        direct_match: bool = False,
        source: str,
    ) -> None:
        normalized_text = text.strip()
        if not normalized_text:
            return
        duplicate_key = " ".join(normalized_text.split())
        if duplicate_key in seen_text:
            return
        seen_text.add(duplicate_key)
        evidence_id = (
            f"{evidence_identity}:page:{page_number}"
            if page_number is not None
            else f"{evidence_identity}:text:"
            f"{hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()[:16]}"
        )
        evidence_item: dict[str, Any] = {
            "evidence_id": evidence_id,
            "document_id": document_id,
            "rag_document_id": rag_document_id,
            "title": title,
            "version": document.get("version") or metadata.get("version"),
            "issuer": metadata.get("issuer") or document.get("issuer"),
            "page_number": page_number,
            "text": normalized_text,
            "direct_match": direct_match,
            "source": source,
        }
        evidence_item["matched_text"] = (
            _matched_text(normalized_text, question) or ""
        )
        resolved_section = section or default_section
        if resolved_section:
            evidence_item["section"] = str(resolved_section).strip()
        evidence.append(evidence_item)

    if full_text:
        for page_number, text in _full_text_parts(full_text):
            add_evidence(text, page_number, source="full_document")
    else:
        for page in page_context:
            add_evidence(
                page["page_text"],
                page["page_number"],
                section=page.get("section"),
                direct_match=page["direct_match"],
                source="page_window",
            )

    compact: dict[str, Any] = {
        "document_id": document_id,
        "rag_document_id": rag_document_id,
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
        "evidence": evidence,
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
        if (compact := _compact_document(document, question)) is not None
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
    model_documents = [_model_document(document) for document in compact_documents]
    return {
        "status": "success",
        "evidence_found": True,
        "query": question,
        "documents_found": len(model_documents),
        "documents": model_documents,
    }


def _model_document(document: dict[str, Any]) -> dict[str, Any]:
    """Reduz o payload sem duplicar o texto integral e os trechos de páginas."""

    model_document = {
        key: document.get(key)
        for key in (
            "document_id",
            "rag_document_id",
            "title",
            "standard_id",
            "version",
            "issuer",
            "status",
            "source_extractor",
            "quality_score",
            "pages",
            "matched_pages",
            "context_warning",
        )
    }
    evidence_fields = {
        "evidence_id",
        "page_number",
        "section",
        "text",
        "matched_text",
        "direct_match",
        "source",
    }
    model_document["evidence"] = [
        {
            key: evidence[key]
            for key in evidence_fields
            if key in evidence
        }
        for evidence in document.get("evidence", [])
    ]
    return model_document
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
