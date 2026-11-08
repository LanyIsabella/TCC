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

from src.app.query_planner import (
    is_broad_question,
    meaningful_terms,
    normalize_text,
    plan_queries,
)

logger = logging.getLogger(__name__)
MAX_FULL_TEXT_CHARS = 6_000
MAX_PAGE_TEXT_CHARS = 2_200
MAX_CONTEXT_CHARS = 4_000
MAX_TOTAL_CONTEXT_CHARS = 9_000
MAX_CONTEXT_PAGES = 5
MATCH_WINDOW_CHARS = 240
LOW_INFORMATION_MARKERS = (
    "todos os direitos reservados",
    "documento impresso",
    "prefacio",
    "sumario",
    "indice remissivo",
    "sede da abnt",
    "www.abnt",
    "tel.:",
)
RERANK_STOPWORDS = {
    "abnt",
    "acad",
    "academica",
    "academicas",
    "academico",
    "academicos",
    "apresentacao",
    "como",
    "deve",
    "devem",
    "documento",
    "documentos",
    "formatacao",
    "mais",
    "norma",
    "normas",
    "principais",
    "regras",
    "trabalho",
    "trabalhos",
}
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
    paragraph_start = text.rfind("\n\n", 0, original_start)
    paragraph_end = text.find("\n\n", original_end)
    paragraph_start = 0 if paragraph_start < 0 else paragraph_start + 2
    paragraph_end = len(text) if paragraph_end < 0 else paragraph_end
    excerpt = text[paragraph_start:paragraph_end].strip()
    if excerpt:
        return _complete_text_excerpt(excerpt, MATCH_WINDOW_CHARS * 3)
    window_start = max(0, original_start - MATCH_WINDOW_CHARS // 2)
    window_end = min(len(text), original_end + MATCH_WINDOW_CHARS // 2)
    return _complete_text_excerpt(text[window_start:window_end], MATCH_WINDOW_CHARS)


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


def _document_terms(document: dict[str, Any]) -> set[str]:
    metadata = document.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    values = [
        document.get("title"),
        metadata.get("title"),
        metadata.get("id"),
        document.get("section"),
    ]
    return meaningful_terms(" ".join(str(value or "") for value in values))


def _document_context_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in document.get("page_context") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("page_text") or ""))
    return " ".join(parts)


def _prefix_overlap(query_terms: set[str], text_terms: set[str]) -> float:
    if not query_terms or not text_terms:
        return 0.0
    matches = sum(
        any(
            term == candidate
            or term[: max(4, min(len(term), len(candidate)) - 2)]
            == candidate[: max(4, min(len(term), len(candidate)) - 2)]
            for candidate in text_terms
        )
        for term in query_terms
    )
    return matches / len(query_terms)


def _rerank_document(
    document: dict[str, Any],
    question: str,
    queries: list[str],
) -> tuple[float, dict[str, float]]:
    """Calcula pertinencia posterior sem alterar o RRF produzido pelo banco."""

    original_terms = meaningful_terms(question) - RERANK_STOPWORDS
    original_terms.update(
        {"trabalho", "trabalhos", "academico", "academicos"}
        if "tcc" in original_terms
        else set()
    )
    title_terms = _document_terms(document)
    page_terms = meaningful_terms(_document_context_text(document))
    title_relevance = _prefix_overlap(original_terms, title_terms)
    page_relevance = _prefix_overlap(original_terms, page_terms)

    facet_scores: list[float] = []
    for query in queries:
        query_terms = meaningful_terms(query)
        facet_scores.append(
            0.65 * _prefix_overlap(query_terms, title_terms)
            + 0.35 * _prefix_overlap(query_terms, page_terms)
        )
    facet_relevance = max(facet_scores, default=0.0)

    title_text = normalize_text(
        " ".join(
            str(value or "")
            for value in (
                document.get("title"),
                (document.get("metadata") or {}).get("title"),
            )
        )
    )
    question_text = normalize_text(question)
    scope_mismatch = 0.0
    if "tcc" in original_terms or "trabalho" in original_terms:
        mismatch_hints = {
            "lombada": 1.0,
            "lombadas": 1.0,
            "artigo": 0.8,
            "projeto de pesquisa": 0.7,
            "indice": 0.7,
        }
        scope_mismatch = max(
            (
                weight
                for hint, weight in mismatch_hints.items()
                if hint in title_text and hint not in question_text
            ),
            default=0.0,
        )

    query_scores = document.get("retrieval_query_scores") or []
    original_score = 0.0
    original_rank = 0.0
    best_score = 0.0
    for item in query_scores:
        if not isinstance(item, dict):
            continue
        score = _numeric_score(item.get("rrf_score"))
        if score == float("-inf"):
            continue
        best_score = max(best_score, score)
        if int(item.get("query_index", -1)) == 0:
            original_score = score
            rank = int(item.get("rank", 0) or 0)
            original_rank = 1.0 / max(rank, 1)

    score_reference = max(
        _numeric_score(item.get("rrf_score"))
        for item in query_scores
        if isinstance(item, dict)
    )
    if score_reference == float("-inf"):
        score_reference = 1.0
    original_rrf = original_score / max(score_reference, 1e-9)
    best_rrf = best_score / max(score_reference, 1e-9)
    retrieval_hit_signal = min(int(document.get("retrieval_hits", 0)), 3) / 3

    components = {
        "original_rank": original_rank,
        "original_rrf": original_rrf,
        "best_rrf": best_rrf,
        "title_relevance": title_relevance,
        "page_relevance": page_relevance,
        "facet_relevance": facet_relevance,
        "scope_mismatch": scope_mismatch,
        "retrieval_hit_signal": retrieval_hit_signal,
    }
    total = (
        0.08 * original_rank
        + 0.08 * original_rrf
        + 0.10 * best_rrf
        + 0.35 * title_relevance
        + 0.20 * page_relevance
        + 0.16 * facet_relevance
        - 0.18 * scope_mismatch
        + 0.03 * retrieval_hit_signal
    )
    return total, components


def _rerank_documents(
    documents: list[dict[str, Any]],
    question: str,
    queries: list[str],
) -> list[dict[str, Any]]:
    """Ordena candidatos pela intenção e pelo conteúdo, após a recuperação."""

    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for position, document in enumerate(documents):
        score, components = _rerank_document(document, question, queries)
        candidate = dict(document)
        candidate["rerank_score"] = round(score, 6)
        candidate["rerank_components"] = components
        ranked.append((score, position, candidate))
    ranked.sort(
        key=lambda item: (
            -item[0],
            -_numeric_score(item[2].get("rrf_score")),
            item[1],
        )
    )
    compatible_count = sum(
        item[2].get("rerank_components", {}).get("scope_mismatch", 0.0) < 0.7
        for item in ranked
    )
    if compatible_count >= 4:
        ranked = [
            item
            for item in ranked
            if item[2].get("rerank_components", {}).get("scope_mismatch", 0.0)
            < 0.7
        ]
    return [document for _, _, document in ranked]


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
        for document_rank, document in enumerate(documents, start=1):
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
                current["_query_scores"] = {}
                current["_merge_order"] = order
                merged[key] = current
                order += 1

            query_indexes = current["_query_indexes"]
            if query_index not in query_indexes:
                query_indexes.add(query_index)
                current["retrieval_hits"] += 1
                current["retrieval_queries"].append(query)

            score = _numeric_score(document.get("rrf_score"))
            current["_query_scores"][query_index] = {
                "query_index": query_index,
                "query": query,
                "rank": document_rank,
                "rrf_score": score,
            }
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
    documents.sort(key=lambda document: int(document.get("_merge_order", 0)))
    for document in documents:
        document["retrieval_query_scores"] = list(
            document.pop("_query_scores", {}).values()
        )
        document.pop("_query_indexes", None)
        document.pop("_first_query_index", None)
        document.pop("_best_query_index", None)
        document.pop("_best_rrf_score", None)
        document.pop("_merge_order", None)
    return documents


def _page_is_low_information(text: str) -> bool:
    normalized = normalize_text(text)
    if any(
        normalized.startswith(marker)
        or (marker in normalized and len(normalized) < 800)
        for marker in LOW_INFORMATION_MARKERS
    ):
        return True
    if len(normalized) < 120 and not re.search(
        r"\b(deve|devem|recomenda-se|estabelece|compreende|inclui)\b",
        normalized,
    ):
        return True
    definition_count = len(re.findall(r"\b3\.\d+\b", normalized))
    return definition_count >= 2 and not re.search(
        r"\b(deve|devem|recomenda-se|estabelece|compreende|inclui)\b",
        normalized,
    )


def _page_match_score(
    text: str,
    question: str,
    retrieval_queries: list[str],
    direct_match: bool,
) -> float:
    page_terms = meaningful_terms(text)
    queries = [question, *retrieval_queries]
    query_scores = [
        _prefix_overlap(meaningful_terms(query) - RERANK_STOPWORDS, page_terms)
        for query in queries
        if query
    ]
    score = max(query_scores, default=0.0)
    normalized = normalize_text(text)
    if re.search(
        r"\b(deve|devem|recomenda-se|estabelece|compreende|inclui)\b",
        normalized,
    ):
        score += 0.18
    if direct_match:
        score += 0.05
    if _page_is_low_information(text):
        score -= 0.35
    return score


def _complete_text_excerpt(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    candidate = text[:max_chars]
    boundaries = [candidate.rfind("\n"), candidate.rfind(". "), candidate.rfind("; ")]
    boundary = max(boundaries)
    if boundary >= max_chars // 2:
        return candidate[: boundary + 1].strip()
    return candidate.rstrip(" ,:;-") + " [...]"


def _relevant_page_excerpt(
    text: str,
    question: str,
    retrieval_queries: list[str],
    max_chars: int,
) -> str:
    """Seleciona blocos completos antes de aplicar o limite de caracteres."""

    if len(text) <= max_chars:
        return text.strip()
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]
    if not blocks:
        return _complete_text_excerpt(text, max_chars)

    ranked_blocks = sorted(
        enumerate(blocks),
        key=lambda item: (
            -_page_match_score(
                item[1], question, retrieval_queries, direct_match=False
            ),
            item[0],
        ),
    )
    selected: list[tuple[int, str]] = []
    used = 0
    for index, block in ranked_blocks:
        if used + len(block) + (2 if selected else 0) > max_chars:
            continue
        selected.append((index, block))
        used += len(block) + (2 if selected else 0)
    if not selected:
        return _complete_text_excerpt(blocks[0], max_chars)
    selected.sort()
    return "\n\n".join(block for _, block in selected).strip()


def _compact_document(
    document: Any,
    question: str = "",
    context_budget: int | None = None,
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
    context_budget = max(
        1_200,
        min(int(context_budget or MAX_CONTEXT_CHARS), MAX_CONTEXT_CHARS),
    )
    retrieval_queries = [
        str(item).strip()
        for item in document.get("retrieval_queries", [])
        if str(item).strip()
    ]
    raw_page_context = document.get("page_context")
    if isinstance(raw_page_context, list):
        def page_sort_key(item: dict[str, Any]) -> tuple[float, int]:
            try:
                number = int(item.get("page_number", 0) or 0)
            except (TypeError, ValueError):
                number = 0
            text = str(item.get("page_text") or "").strip()
            score = _page_match_score(
                text,
                question,
                retrieval_queries,
                bool(item.get("direct_match", False)),
            )
            return (-score, number)

        page_items = [item for item in raw_page_context if isinstance(item, dict)]
        has_useful_page = any(
            str(item.get("page_text") or "").strip()
            and not _page_is_low_information(str(item.get("page_text") or ""))
            for item in page_items
        )
        ordered_page_context = sorted(
            (
                item
                for item in page_items
                if not has_useful_page
                or not _page_is_low_information(
                    str(item.get("page_text") or "")
                )
            ),
            key=page_sort_key,
        )
        for item in ordered_page_context:
            try:
                page_number = int(item.get("page_number"))
            except (TypeError, ValueError):
                continue
            text = str(item.get("page_text") or "").strip()
            if (
                page_number <= 0
                or not text
                or context_chars >= context_budget
                or len(page_context) >= MAX_CONTEXT_PAGES
            ):
                continue
            remaining = context_budget - context_chars
            text = _relevant_page_excerpt(
                text,
                question,
                retrieval_queries,
                min(MAX_PAGE_TEXT_CHARS, remaining),
            )
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
        matched_text = _matched_text(
            normalized_text,
            " ".join([question, *retrieval_queries]),
        )
        if matched_text:
            evidence_item["matched_text"] = matched_text
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
        "retrieval_query_scores": document.get("retrieval_query_scores", []),
        "rerank_score": document.get("rerank_score"),
        "rerank_components": document.get("rerank_components", {}),
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
    *,
    retrieval_queries: list[str] | None = None,
) -> dict[str, Any]:
    """Monta um contrato estável para o modelo consumir."""
    if not isinstance(documents, list):
        raise ValueError("A busca RAG não retornou uma lista de documentos.")

    per_document_budget = max(
        1_200,
        min(
            MAX_CONTEXT_CHARS,
            MAX_TOTAL_CONTEXT_CHARS // max(len(documents), 1),
        ),
    )
    compact_documents = [
        compact
        for document in documents
        if (
            compact := _compact_document(
                document,
                question,
                context_budget=per_document_budget,
            )
        )
        is not None
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
            "retrieval_query_scores",
            "rerank_score",
            "rerank_components",
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
    broad = is_broad_question(question)
    queries = plan_queries(question)
    search_documents_limit = max(documents_limit, 4) if broad else documents_limit
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
                query_documents = search_documents(
                            question=query,
                            pages_limit=search_pages_limit,
                            documents_limit=search_documents_limit,
                            full_documents_limit=0,
                            neighbor_radius=search_neighbor_radius,
                        )
                result_groups.append((query, query_documents))
                logger.info(
                    "rag_query_result index=%d query=%r documents=%s",
                    query_index,
                    query[:240],
                    [
                        {
                            "rank": rank,
                            "standard_id": (item.get("metadata") or {}).get("id"),
                            "title": item.get("title")
                            or (item.get("metadata") or {}).get("title"),
                            "rrf_score": item.get("rrf_score"),
                            "pages": item.get("pages"),
                        }
                        for rank, item in enumerate(query_documents, start=1)
                    ],
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
        if broad:
            merged_documents = _merge_documents(result_groups)
            documents = _rerank_documents(
                merged_documents,
                question,
                queries,
            )[:search_documents_limit]
            logger.info(
                "rag_reranked_order=%s",
                [
                    {
                        "rank": rank,
                        "standard_id": item.get("standard_id")
                        or (item.get("metadata") or {}).get("id"),
                        "rrf_score": item.get("rrf_score"),
                        "retrieval_hits": item.get("retrieval_hits"),
                        "rerank_score": item.get("rerank_score"),
                        "pages": item.get("pages"),
                    }
                    for rank, item in enumerate(documents, start=1)
                ],
            )
        else:
            documents = result_groups[0][1]
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
