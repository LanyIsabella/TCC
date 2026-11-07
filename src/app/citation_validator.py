"""Validação determinística de citações contra evidências recuperadas."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

STANDARD_RE = re.compile(
    r"\b(?:ABNT\s*)?NBR\s*(?:ISO(?:/IEC)?\s*)?"
    r"(\d{3,5}(?:-\d+)?)(?:\s*[:\-]\s*(\d{4}))?\b",
    re.IGNORECASE,
)
PAGE_RE = re.compile(r"\b(?:p\.?|p[aá]gina)\s*(\d+)\b", re.IGNORECASE)
QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{20,})[\"“”]")
NORMATIVE_MARKER_RE = re.compile(
    r"\b(?:deve|devem|deverá|deverão|não pode|não devem|"
    r"é obrigatório|são obrigatórios|recomenda-se|pode ser)\b",
    re.IGNORECASE,
)
BASE_SECTION_RE = re.compile(
    r"(?ims)^\s*#{1,6}\s*base\s+normativa\s*:?.*?(?=^\s*#{1,6}\s+|\Z)"
)
QUERY_STOPWORDS = {
    "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "essa", "esse", "esta", "este", "na", "nas",
    "no", "nos", "o", "os", "para", "por", "qual", "que", "se", "sem",
    "segundo", "sobre", "um", "uma", "como",
}


def normalize_for_match(value: str) -> str:
    """Normaliza texto para comparação robusta com OCR."""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00ad", "")
    value = re.sub(r"-\s*\n\s*", "", value)
    value = value.casefold()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _standard_key(value: str) -> str | None:
    match = STANDARD_RE.search(value.replace("_", " "))
    if not match:
        return None
    return f"NBR{match.group(1).replace('-', '')}".upper()


def _evidence_pages(document: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    for page in document.get("pages", []) or []:
        try:
            pages.add(int(page))
        except (TypeError, ValueError):
            continue
    for item in (
        document.get("matched_pages", []) or []
    ) + (document.get("page_context", []) or []):
        if isinstance(item, dict):
            try:
                pages.add(int(item.get("page_number")))
            except (TypeError, ValueError):
                continue
    return {page for page in pages if page > 0}


def _evidence_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(document.get("full_text"), str):
        parts.append(document["full_text"])
    for item in document.get("page_context", []) or []:
        if isinstance(item, dict) and isinstance(item.get("page_text"), str):
            parts.append(item["page_text"])
    return "\n".join(parts)


def _citation_section(answer: str) -> str:
    match = BASE_SECTION_RE.search(answer)
    return match.group(0) if match else ""


def _query_terms(query: str | None) -> set[str]:
    if not query:
        return set()
    return {
        term
        for term in re.findall(r"[\wÀ-ÿ]+", normalize_for_match(query))
        if len(term) > 2 and term not in QUERY_STOPWORDS and term not in {"abnt", "nbr"}
    }


def _term_matches(query_term: str, sentence_term: str) -> bool:
    query_term = "".join(
        char
        for char in unicodedata.normalize("NFKD", query_term)
        if unicodedata.category(char) != "Mn"
    )
    sentence_term = "".join(
        char
        for char in unicodedata.normalize("NFKD", sentence_term)
        if unicodedata.category(char) != "Mn"
    )
    return (
        query_term == sentence_term
        or query_term.startswith(sentence_term)
        or sentence_term.startswith(query_term)
        or (
            len(query_term) >= 5
            and len(sentence_term) >= 5
            and query_term[:5] == sentence_term[:5]
        )
    )


def validate_answer_citations(
    answer: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verifica se a base normativa aponta para evidência recuperada."""
    section = _citation_section(answer)
    citations = list(STANDARD_RE.finditer(section))
    issues: list[str] = []
    matched_documents: list[int] = []

    if not section:
        issues.append("missing_base_section")
    if not citations:
        issues.append("missing_standard")
    if not evidence:
        issues.append("missing_evidence")

    pages = {int(page) for page in PAGE_RE.findall(section)}
    for citation in citations:
        citation_key = _standard_key(citation.group(0))
        citation_version = citation.group(2)
        matching_document = None
        for index, document in enumerate(evidence):
            label = " ".join(
                str(document.get(key) or "")
                for key in ("standard_label", "standard_id", "title")
            )
            if _standard_key(label) != citation_key:
                continue
            version = str(document.get("version") or "")
            if citation_version and citation_version != version:
                continue
            matching_document = (index, document)
            break

        if matching_document is None:
            issues.append("citation_not_in_evidence")
            continue

        index, document = matching_document
        matched_documents.append(index)
        evidence_pages = _evidence_pages(document)
        if pages and not pages.intersection(evidence_pages):
            issues.append("citation_page_not_in_evidence")

    unsupported_quotes: list[str] = []
    evidence_text = normalize_for_match(
        "\n".join(_evidence_text(document) for document in evidence)
    )
    for quote in QUOTE_RE.findall(answer):
        if normalize_for_match(quote) not in evidence_text:
            unsupported_quotes.append(quote)
    if unsupported_quotes:
        issues.append("quoted_text_not_in_evidence")

    return {
        "valid": bool(section and citations and evidence and not issues),
        "issues": issues,
        "matched_documents": sorted(set(matched_documents)),
        "unsupported_quotes": unsupported_quotes,
    }


def citation_block(document: dict[str, Any]) -> str:
    """Renderiza a citação canônica do primeiro documento aprovado."""
    standard = str(
        document.get("standard_label")
        or document.get("standard_id")
        or document.get("title")
        or "Documento normativo"
    ).strip()
    version = str(document.get("version") or "").strip()
    pages = sorted(_evidence_pages(document))
    label = f"- {standard}"
    if version:
        label += f":{version}"
    if pages:
        label += f", p. {', '.join(str(page) for page in pages)}"
    return f"### Base normativa\n\n{label}."


def supporting_excerpts(
    evidence: list[dict[str, Any]],
    *,
    query: str | None = None,
    limit: int = 3,
    max_chars: int = 500,
) -> list[dict[str, Any]]:
    """Extrai frases normativas dos trechos OCR retornados pelo RAG."""
    query_terms = _query_terms(query)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for document in evidence:
        standard = str(
            document.get("standard_label")
            or document.get("standard_id")
            or document.get("title")
            or "Documento normativo"
        ).strip()
        version = str(document.get("version") or "").strip()
        for item in document.get("page_context", []) or []:
            if not isinstance(item, dict) or not isinstance(item.get("page_text"), str):
                continue
            page = item.get("page_number")
            text = item["page_text"].strip()
            sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
            for sentence in sentences:
                sentence = re.sub(r"\s+", " ", sentence).strip()
                if len(sentence) < 30 or not NORMATIVE_MARKER_RE.search(sentence):
                    continue
                sentence_terms = set(
                    re.findall(r"[\wÀ-ÿ]+", normalize_for_match(sentence))
                )
                matched_terms = {
                    term
                    for term in query_terms
                    if any(
                        _term_matches(term, candidate)
                        for candidate in sentence_terms
                    )
                }
                if query_terms and len(matched_terms) < 2:
                    continue
                score = len(matched_terms) / max(len(query_terms), 1)
                if item.get("direct_match"):
                    score += 0.05
                candidates.append(
                    (
                        score,
                        {
                            "text": sentence[:max_chars].rstrip(),
                            "standard": standard,
                            "version": version,
                            "page": page,
                            "match_score": round(min(score, 1.0), 3),
                        },
                    )
                )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in candidates[:limit]]


def supporting_excerpts_block(
    evidence: list[dict[str, Any]], query: str | None = None
) -> str:
    """Renderiza uma referência compacta aos trechos usados na resposta."""
    excerpts = supporting_excerpts(evidence, query=query)
    if not excerpts:
        return ""
    legacy_lines = ["### Trechos que sustentam a resposta", ""]
    for excerpt in excerpts:
        source = f"{excerpt['standard']}"
        if excerpt["version"]:
            source += f":{excerpt['version']}"
        if excerpt["page"]:
            source += f", p. {excerpt['page']}"
        text = excerpt["text"].replace("\n", " ").strip()
        legacy_lines.extend([f"> {text}", f"> \u2014 {source}", ""])
    return "\n".join(legacy_lines).rstrip()

    sources: dict[str, set[int]] = {}
    for excerpt in excerpts:
        source = str(excerpt["standard"])
        if excerpt["version"]:
            source += f":{excerpt['version']}"
        sources.setdefault(source, set())
        if excerpt.get("page"):
            sources[source].add(int(excerpt["page"]))
    if not sources:
        for document in evidence[:3]:
            source = str(
                document.get("standard_label")
                or document.get("standard_id")
                or document.get("title")
                or "Documento normativo"
            )
            if document.get("version"):
                source += f":{document['version']}"
            sources[source] = set(sorted(_evidence_pages(document))[:3])
    if not sources:
        return ""
    lines = ["### Fonte de referência", ""]
    for source, pages in sources.items():
        page_text = (
            f", p. {', '.join(str(page) for page in sorted(pages))}"
            if pages
            else ""
        )
        lines.append(f"- {source}{page_text}.")
    return "\n".join(lines).rstrip()


def grounded_answer(
    answer: str,
    evidence: list[dict[str, Any]],
    query: str | None = None,
) -> str:
    """Garante uma resposta normativa com citação verificável."""
    if not evidence:
        return (
            "Não localizei evidência suficiente nos documentos normativos "
            "disponíveis para responder com segurança."
        )

    validation = validate_answer_citations(answer, evidence)
    if validation["valid"]:
        if "trechos que sustentam a resposta" in answer.casefold():
            return answer
        evidence_block = supporting_excerpts_block(evidence, query=query)
        return f"{answer.rstrip()}\n\n{evidence_block}" if evidence_block else answer

    if validation["unsupported_quotes"]:
        safe_answer = (
            "Não consegui validar o trecho literal apresentado contra a "
            "evidência recuperada. Não vou tratá-lo como citação normativa.\n\n"
            + citation_block(evidence[0])
        )
        evidence_block = supporting_excerpts_block(evidence, query=query)
        return f"{safe_answer}\n\n{evidence_block}" if evidence_block else safe_answer

    answer_without_old_section = BASE_SECTION_RE.sub("", answer).rstrip()
    grounded = f"{answer_without_old_section}\n\n{citation_block(evidence[0])}"
    evidence_block = supporting_excerpts_block(evidence, query=query)
    return f"{grounded}\n\n{evidence_block}" if evidence_block else grounded


__all__ = [
    "citation_block",
    "grounded_answer",
    "normalize_for_match",
    "supporting_excerpts",
    "supporting_excerpts_block",
    "validate_answer_citations",
]
