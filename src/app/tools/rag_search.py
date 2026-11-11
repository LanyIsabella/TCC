"""Ferramenta de recuperação hierárquica para o agente principal."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from typing import Any

from data.rag_pipeline import estimated_token_count, search_documents
from langchain.tools import tool
from pydantic import BaseModel, Field

from src.app.query_planner import is_broad_question, plan_queries

logger = logging.getLogger(__name__)
MAX_FULL_TEXT_CHARS = 6_000
MAX_PAGE_TEXT_CHARS = 1_800
MAX_CONTEXT_CHARS = 5_000
MAX_CONTEXT_TOKENS = 1_200
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


def _standard_label(standard_id: Any, title: str) -> str:
    """Converte o identificador interno em um nome legível para citação."""
    normalized = str(standard_id or "").strip().lower()
    if normalized.startswith("abnt_nbr_"):
        number = normalized.removeprefix("abnt_nbr_")
        if number.isdigit():
            return f"ABNT NBR {number}"
    return str(standard_id or title or "Documento normativo").strip()


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


def _match_spans(text: str, question: str) -> list[tuple[int, int]]:
    prefixes = _match_prefixes(question)
    if not prefixes:
        return []

    normalized_text, positions = _normalized_with_positions(text)
    pattern = re.compile(
        rf"\b(?:{'|'.join(re.escape(prefix) for prefix in prefixes)})\w*",
        flags=re.UNICODE,
    )
    return [
        (
            positions[match.start()],
            positions[match.end() - 1] + 1,
        )
        for match in pattern.finditer(normalized_text)
    ]


def _matched_text(text: str, question: str) -> str | None:
    """Retorna um recorte original em torno do primeiro match da consulta."""

    spans = _match_spans(text, question)
    if not spans:
        return None

    original_start, original_end = spans[0]
    window_start = max(0, original_start - MATCH_WINDOW_CHARS // 2)
    window_end = min(len(text), original_end + MATCH_WINDOW_CHARS // 2)
    return text[window_start:window_end].strip()


def _semantic_units(text: str) -> list[tuple[int, int]]:
    """Divide o texto em unidades contíguas sem criar conteúdo novo."""

    units: list[tuple[int, int]] = []
    start = 0
    for boundary in re.finditer(r"\n\s*\n|(?<=[.!?])\s+|\n", text):
        end = boundary.start()
        if text[start:end].strip():
            units.append((start, end))
        start = boundary.end()
    if text[start:].strip():
        units.append((start, len(text)))
    return units or ([(0, len(text))] if text else [])


def _semantic_excerpt(
    text: str,
    question: str,
    max_chars: int,
    max_tokens: int,
) -> str:
    """Preserva unidades próximas da consulta dentro do orçamento local."""

    if not text:
        return ""
    units = _semantic_units(text)
    spans = _match_spans(text, question)
    target = spans[0][0] if spans else 0
    target_index = next(
        (
            index
            for index, (start, end) in enumerate(units)
            if start <= target < end
        ),
        0,
    )
    selected = [target_index]
    while True:
        candidates = [
            index
            for index in (target_index + 1, target_index - 1)
            if 0 <= index < len(units) and index not in selected
        ]
        if not candidates:
            break
        candidate = candidates[0]
        start = min(units[index][0] for index in [*selected, candidate])
        end = max(units[index][1] for index in [*selected, candidate])
        if end - start > max_chars:
            break
        selected.append(candidate)
    start = min(units[index][0] for index in selected)
    end = max(units[index][1] for index in selected)
    excerpt = text[start:end].strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip()
        cut = excerpt.rfind(" ")
        if cut > 0:
            excerpt = excerpt[:cut].rstrip()
    while estimated_token_count(excerpt) > max_tokens:
        cut = excerpt.rfind(" ")
        excerpt = excerpt[:cut].rstrip() if cut > 0 else excerpt[:-1]
    return excerpt


def _document_merge_key(document: dict[str, Any]) -> str:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    identity = (
        document.get("id")
        or document.get("rag_document_id")
        or document.get("document_id")
        or metadata.get("id")
        or document.get("title")
    )
    return str(identity or "document-without-id").strip()


def _numeric_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _merge_page_context(
    current: list[Any], incoming: list[Any]
) -> list[dict[str, Any]]:
    pages: dict[int, dict[str, Any]] = {}
    for item in [*current, *incoming]:
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item.get("page_number"))
        except (TypeError, ValueError):
            continue
        if page_number <= 0:
            continue
        candidate = dict(item)
        previous = pages.get(page_number)
        if previous is None or len(str(candidate.get("page_text") or "")) > len(
            str(previous.get("page_text") or "")
        ):
            pages[page_number] = candidate
        elif item.get("direct_match"):
            previous["direct_match"] = True
    return [pages[number] for number in sorted(pages)]


def _merge_matched_pages(
    current: list[Any], incoming: list[Any]
) -> list[dict[str, Any]]:
    pages: dict[int, dict[str, Any]] = {}
    for item in [*current, *incoming]:
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item.get("page_number"))
        except (TypeError, ValueError):
            continue
        if page_number <= 0:
            continue
        previous = pages.setdefault(page_number, {"page_number": page_number})
        previous["direct_match"] = bool(
            previous.get("direct_match") or item.get("direct_match")
        )
        for key in ("rrf_score", "semantic_distance", "textual_rank"):
            if key in item and key not in previous:
                previous[key] = item[key]
    return list(pages.values())


def _merge_documents(
    result_groups: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Consolida consultas adaptativas sem somar RRF de escalas distintas.

    A política é: documentos encontrados por mais consultas têm prioridade;
    em empate, a consulta original vem antes das expansões; depois usamos a
    melhor pontuação RRF individual. A pontuação nunca é somada entre
    consultas independentes.
    """

    merged: dict[str, dict[str, Any]] = {}
    order = 0
    for query_index, (query, documents) in enumerate(result_groups):
        for document in documents:
            if not isinstance(document, dict):
                continue
            key = _document_merge_key(document)
            current = merged.get(key)
            if current is None:
                current = dict(document)
                current["pages"] = list(document.get("pages") or [])
                current["matched_pages"] = list(
                    document.get("matched_pages") or []
                )
                current["page_context"] = list(document.get("page_context") or [])
                current["retrieval_queries"] = []
                current["retrieval_hits"] = 0
                current["_query_indexes"] = set()
                current["_first_query_index"] = query_index
                current["_best_query_index"] = query_index
                current["_best_rrf_score"] = _numeric_score(
                    document.get("rrf_score")
                )
                current["_merge_order"] = order
                merged[key] = current
                order += 1

            query_indexes = current["_query_indexes"]
            if query_index not in query_indexes:
                query_indexes.add(query_index)
                current["retrieval_hits"] += 1
                current["retrieval_queries"].append(query)

            score = _numeric_score(document.get("rrf_score"))
            if score >= current["_best_rrf_score"]:
                current["_best_query_index"] = query_index
            current["_best_rrf_score"] = max(current["_best_rrf_score"], score)
            current["rrf_score"] = current["_best_rrf_score"]
            current["pages"] = list(
                dict.fromkeys(
                    [
                        *current.get("pages", []),
                        *(document.get("pages") or []),
                    ]
                )
            )
            current["matched_pages"] = _merge_matched_pages(
                current.get("matched_pages", []),
                document.get("matched_pages") or [],
            )
            current["page_context"] = _merge_page_context(
                current.get("page_context", []),
                document.get("page_context") or [],
            )
            if not current.get("full_text") and document.get("full_text"):
                current["full_text"] = document["full_text"]
            if isinstance(document.get("metadata"), dict):
                metadata = current.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    for metadata_key, metadata_value in document["metadata"].items():
                        metadata.setdefault(metadata_key, metadata_value)

    documents = list(merged.values())
    documents.sort(
        key=lambda document: (
            -int(document.get("retrieval_hits", 0)),
            -_numeric_score(document.get("rrf_score")),
            -int(document.get("_best_query_index", 0)),
            int(document.get("_first_query_index", 0)),
            int(document.get("_merge_order", 0)),
        )
    )
    for document in documents:
        document.pop("_query_indexes", None)
        document.pop("_first_query_index", None)
        document.pop("_best_query_index", None)
        document.pop("_best_rrf_score", None)
        document.pop("_merge_order", None)
    return documents


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

    original_full_text = document.get("full_text")
    full_text = (
        original_full_text
        if isinstance(original_full_text, str) and original_full_text.strip()
        else None
    )
    full_text_fits = bool(
        full_text
        and len(full_text) <= MAX_FULL_TEXT_CHARS
        and estimated_token_count(full_text) <= MAX_CONTEXT_TOKENS
    )
    raw_page_context = document.get("page_context")
    if not isinstance(raw_page_context, list):
        raw_page_context = []
    if full_text and not full_text_fits and not raw_page_context:
        fallback_page = pages[0] if len(pages) == 1 else None
        raw_page_context = [
            {
                "page_number": page_number or fallback_page,
                "page_text": text,
                "direct_match": False,
            }
            for page_number, text in _full_text_parts(full_text)
        ]
    if not full_text_fits:
        full_text = None

    page_context: list[dict[str, Any]] = []
    context_chars = 0
    context_tokens = 0
    source_chars = 0
    retained_chars = 0
    omitted_pages: list[int] = []

    def page_sort_key(item: dict[str, Any]) -> tuple[bool, bool, int]:
        text = str(item.get("page_text") or "")
        try:
            number = int(item.get("page_number", 0) or 0)
        except (TypeError, ValueError):
            number = 0
        return (
            not bool(item.get("direct_match", False)),
            not bool(_match_spans(text, question)),
            number,
        )

    ordered_page_context = sorted(
        (item for item in raw_page_context if isinstance(item, dict)),
        key=page_sort_key,
    )
    for item in ordered_page_context:
        raw_text = str(item.get("page_text") or "").strip()
        if not raw_text:
            continue
        source_chars += len(raw_text)
        try:
            page_number = int(item.get("page_number"))
        except (TypeError, ValueError):
            page_number = None
        if page_number is not None and page_number <= 0:
            continue
        remaining_chars = MAX_CONTEXT_CHARS - context_chars
        remaining_tokens = MAX_CONTEXT_TOKENS - context_tokens
        if remaining_chars <= 0 or remaining_tokens <= 0:
            if page_number is not None:
                omitted_pages.append(page_number)
            continue
        text = _semantic_excerpt(
            raw_text,
            question,
            min(MAX_PAGE_TEXT_CHARS, remaining_chars),
            remaining_tokens,
        )
        if not text:
            if page_number is not None:
                omitted_pages.append(page_number)
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
        context_tokens += estimated_token_count(text)
        retained_chars += len(text)
        if len(text) < len(raw_text) and page_number is not None:
            omitted_pages.append(page_number)

    if full_text:
        source_chars = len(full_text)
        retained_chars = len(full_text)

    omitted_characters = max(source_chars - retained_chars, 0)
    omitted_content = {
        "characters": omitted_characters,
        "pages": sorted(set(omitted_pages)),
    }

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
        "standard_label": _standard_label(metadata.get("id"), title),
        "version": document.get("version") or metadata.get("version"),
        "issuer": metadata.get("issuer"),
        "status": metadata.get("status"),
        "source_extractor": document.get("source_extractor"),
        "quality_score": document.get("quality_score"),
        "rrf_score": document.get("rrf_score"),
        "retrieval_hits": document.get("retrieval_hits", 1),
        "retrieval_queries": document.get("retrieval_queries", []),
        "pages": pages,
        "matched_pages": matched_pages,
        "full_text": full_text,
        "page_context": page_context,
        "evidence": evidence,
        "omitted_content": omitted_content,
        "context_warning": document.get("context_warning"),
    }
    return compact


def _validated_result(
    documents: Any,
    question: str,
    *,
    retrieval_queries: list[str] | None = None,
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
            "retrieval_queries": retrieval_queries or [question],
            "message": "Nenhuma evidência textual correspondente foi localizada.",
        }
    model_documents = [_model_document(document) for document in compact_documents]
    return {
        "status": "success",
        "evidence_found": True,
        "query": question,
        "documents_found": len(model_documents),
        "documents": model_documents,
        "retrieval_queries": retrieval_queries or [question],
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
            "standard_label",
            "version",
            "issuer",
            "status",
            "source_extractor",
            "quality_score",
            "rrf_score",
            "retrieval_hits",
            "retrieval_queries",
            "pages",
            "matched_pages",
            "omitted_content",
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
    broad = is_broad_question(question)
    queries = plan_queries(question)
    search_documents_limit = max(documents_limit, 3) if broad else documents_limit
    search_pages_limit = max(pages_limit, 10) if broad else pages_limit
    search_neighbor_radius = 1 if broad else 0
    logger.info(
        "rag_search_start question=%r broad=%s query_count=%d "
        "documents_limit=%d pages_limit=%d",
        question[:240],
        broad,
        len(queries),
        search_documents_limit,
        search_pages_limit,
    )

    try:
        result_groups: list[tuple[str, list[dict[str, Any]]]] = []
        query_errors: list[Exception] = []
        for query_index, query in enumerate(queries):
            try:
                result_groups.append(
                    (
                        query,
                        search_documents(
                            question=query,
                            pages_limit=search_pages_limit,
                            documents_limit=search_documents_limit,
                            full_documents_limit=0,
                            neighbor_radius=search_neighbor_radius,
                        ),
                    )
                )
            except Exception as error:
                query_errors.append(error)
                logger.warning(
                    "adaptive_query_failed query_index=%d error=%s",
                    query_index,
                    error,
                )
        if not result_groups:
            if query_errors:
                raise query_errors[-1]
            raise RuntimeError("Nenhuma consulta adaptativa foi executada.")
        documents = (
            _merge_documents(result_groups)[:search_documents_limit]
            if broad
            else result_groups[0][1]
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
        result = _validated_result(
            documents,
            question,
            retrieval_queries=queries,
        )
        result["adaptive_retrieval"] = broad
        logger.info(
            "rag_search_complete status=%s documents=%d adaptive=%s",
            result.get("status"),
            result.get("documents_found", 0),
            broad,
        )
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
