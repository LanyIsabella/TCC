"""Síntese estruturada independente de tool calling de AgentAnswer."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from src.app.query_planner import focused_query

from .schemas import LimitationCode, ResponseMode, SynthesisResponse

logger = logging.getLogger(__name__)
_INLINE_EVIDENCE_ID = re.compile(
    r"\bevidence_id\s*:\s*([A-Za-z0-9][A-Za-z0-9:._-]*)",
    flags=re.IGNORECASE,
)


class SynthesisFailure(RuntimeError):
    """A LLM não produziu uma síntese estruturada validável."""


class Synthesizer:
    """Gera JSON estruturado com no máximo uma nova tentativa controlada."""

    def __init__(self, model: Any | None) -> None:
        self._model = model
        self._structured = None
        if model is not None:
            try:
                self._structured = model.with_structured_output(
                    SynthesisResponse,
                    method="json_schema",
                    include_raw=True,
                )
            except Exception:
                logger.exception("synthesis_structured_output_unavailable=True")

    def synthesize(
        self,
        question: str,
        history: list[Any],
        retrieval: Mapping[str, Any],
        *,
        mode: ResponseMode | str = ResponseMode.NORMATIVE,
        objective: str | None = None,
        use_parametric_knowledge: bool = True,
    ) -> SynthesisResponse:
        if self._structured is None:
            raise SynthesisFailure("Saída estruturada indisponível.")
        prompt = self._prompt(
            question,
            history,
            retrieval,
            mode=mode,
            objective=objective,
            use_parametric_knowledge=use_parametric_knowledge,
        )
        evidence = _prompt_evidence(retrieval, focus=question)
        for attempt in range(2):
            parsed = self._attempt(prompt, attempt)
            if parsed is not None:
                parsed = _canonicalize_evidence_ids(parsed, evidence)
                if attempt == 0 and _needs_multi_source_retry(parsed, evidence):
                    prompt = _retry_prompt(prompt, multi_source=True)
                    continue
                if attempt == 1:
                    parsed = _mark_multi_source_limit(parsed, evidence)
                return parsed
            prompt = _retry_prompt(prompt)
        raise SynthesisFailure("A síntese não produziu um contrato válido.")

    def _attempt(self, prompt: str, attempt: int) -> SynthesisResponse | None:
        try:
            value = self._structured.invoke(
                [{"role": "system", "content": prompt}]
            )
            return self._parsed(value)
        except Exception:
            logger.exception("synthesis_attempt_failed attempt=%d", attempt + 1)
            return None

    def _prompt(
        self,
        question: str,
        history: list[Any],
        retrieval: Mapping[str, Any],
        *,
        mode: ResponseMode | str = ResponseMode.NORMATIVE,
        objective: str | None = None,
        use_parametric_knowledge: bool = True,
    ) -> str:
        context = [
            {
                "role": str(item.get("role", ""))
                if isinstance(item, Mapping)
                else str(getattr(item, "role", getattr(item, "type", ""))),
                "content": str(
                    item.get("content", "")
                    if isinstance(item, Mapping)
                    else getattr(item, "content", "")
                )[:1200],
            }
            for item in history[-8:]
        ]
        evidence = _prompt_evidence(retrieval, focus=question)
        selected_mode = ResponseMode(mode)
        if selected_mode == ResponseMode.GENERAL:
            policy = (
                "Explique de forma natural usando conhecimento paramétrico para "
                "conceitos, procedimentos, exemplos e comparações gerais. Não "
                "apresente regra específica de ABNT como verificada sem evidência. "
                "Marque exemplos inventados como 'Exemplo ilustrativo:' e não crie "
                "citações ou IDs documentais. Sem trechos RAG, não use "
                "evidence_unavailable apenas por falta de documentos; use uma lista "
                "de limitações vazia quando a explicação geral for válida."
            )
        elif selected_mode == ResponseMode.MIXED:
            policy = (
                "Combine explicação geral, passos e exemplos claramente marcados "
                "com regras documentais dos trechos. Somente afirmações normativas "
                "devem usar evidence_id; não transforme relação temática em prova."
            )
        else:
            policy = (
                "Use somente o texto dos trechos fornecidos para afirmações "
                "normativas e não complete informação ausente."
            )
        return (
            "Você é o sintetizador de um assistente acadêmico ABNT. "
            + policy
            + " Responda de forma clara e natural. Pode explicar e combinar regras "
            "pertinentes, mas preserve integralmente "
            "números, unidades, obrigações, permissões, negações, condições e "
            "exceções; não copie fragmentos que não respondam ao aspecto perguntado. "
             "Quando a pergunta combinar temas ou documentos, associe cada "
             "afirmação aos trechos que a sustentam e use mais de um evidence_id "
             "quando necessário; não atribua a um único trecho uma relação que "
             "exige outra fonte. Separe afirmações sustentadas por fontes distintas "
             "em frases diferentes. O título, o nome da norma, a similaridade lexical "
             "e o marcador direct_match não são prova factual. Para cada afirmação "
             "normativa "
            "sustentada, selecione um evidence_id existente. Se os trechos não "
            "responderem, use evidence_ids=[] e "
            "limitations=[\"evidence_unavailable\"]. "
            "Use partial_support quando a resposta for explicitamente parcial e "
            "synthesis_failed somente se o contrato não puder ser produzido. "
            "Retorne somente JSON com answer, evidence_ids e limitations.\n\n"
            f"Histórico contextual: {json.dumps(context, ensure_ascii=False)}\n"
            f"Modo: {selected_mode.value}\n"
            "Conhecimento paramétrico autorizado: "
            f"{'sim' if use_parametric_knowledge else 'não'}; "
            "isso permite elaborar explicações e exemplos, mas nunca funciona "
            "como autoridade factual normativa. A autoridade factual é somente "
            "o texto dos trechos fornecidos.\n"
            f"Objetivo: {objective or question}\n"
            f"Pergunta: {question}\n"
            f"Trechos documentais: {json.dumps(evidence, ensure_ascii=False)}"
        )

    def _parsed(self, value: Any) -> SynthesisResponse | None:
        parsed = self._coerce(value)
        return _normalize_inline_evidence_ids(parsed)

    @staticmethod
    def _coerce(value: Any) -> SynthesisResponse | None:
        if isinstance(value, SynthesisResponse):
            return value
        if not isinstance(value, Mapping):
            return None
        parsed = value.get("parsed", value)
        if isinstance(parsed, SynthesisResponse):
            return parsed
        if not isinstance(parsed, Mapping) or "answer" not in parsed:
            return None
        return SynthesisResponse.model_validate(parsed)


def _normalize_inline_evidence_ids(
    parsed: SynthesisResponse | None,
) -> SynthesisResponse | None:
    if parsed is None:
        return None
    inline_ids = list(dict.fromkeys(_INLINE_EVIDENCE_ID.findall(parsed.answer)))
    if not inline_ids:
        return parsed
    updates: dict[str, Any] = {"answer": _without_inline_ids(parsed.answer)}
    if not parsed.evidence_ids:
        updates["evidence_ids"] = inline_ids
    return parsed.model_copy(update=updates)


def _prompt_evidence(
    retrieval: Mapping[str, Any], *, focus: str | None = None
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for document in retrieval.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        document_key = str(
            document.get("rag_document_id")
            or document.get("document_id")
            or document.get("standard_id")
            or document.get("title")
            or ""
        )
        for item in document.get("evidence", []):
            if not isinstance(item, Mapping):
                continue
            text = _compact_evidence_text(item, focus=focus)
            if not text:
                continue
            candidates.append(
                {
                    "evidence_id": str(item.get("evidence_id") or ""),
                    "standard": str(
                        document.get("standard_label")
                        or document.get("standard_id")
                        or document.get("title")
                        or ""
                    ),
                    "page": item.get("page_number"),
                    "direct_match": bool(item.get("direct_match")),
                    "text": text[:1000],
                    "_document_key": document_key,
                }
            )
    direct = [item for item in candidates if item["direct_match"]]
    if direct:
        selected = list(direct)
        direct_pages = {
            (item["_document_key"], int(item["page"]))
            for item in direct
            if str(item["page"]).isdigit()
        }
        for item in candidates:
            if len(selected) >= 4 or item["direct_match"]:
                continue
            if not str(item["page"]).isdigit():
                continue
            page = int(item["page"])
            if any(
                item["_document_key"] == document_key
                and abs(page - direct_page) == 1
                for document_key, direct_page in direct_pages
            ):
                selected.append(item)
    else:
        selected = candidates
    selected.sort(
        key=lambda item: (
            not item["direct_match"],
            not bool(item["evidence_id"]),
            str(item["evidence_id"]),
        )
    )
    return [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in selected[:4]
    ]


def _compact_evidence_text(
    item: Mapping[str, Any], limit: int = 1000, *, focus: str | None = None
) -> str:
    text = str(item.get("text") or "").strip()
    if len(text) <= limit:
        return text
    if focus:
        lowered = text.casefold()
        terms = sorted(
            set(focused_query(focus).split()), key=len, reverse=True
        )
        for term in terms:
            start = lowered.find(term.casefold())
            if start < 0:
                continue
            window_start = max(0, start - 200)
            window_end = min(len(text), window_start + limit)
            if window_end - window_start < limit:
                window_start = max(0, window_end - limit)
            return text[window_start:window_end].strip()
    matched = str(item.get("matched_text") or "").strip()
    if matched and (start := text.find(matched)) >= 0:
        window_start = max(0, start - 200)
        window_end = min(len(text), window_start + limit)
        if window_end - window_start < limit:
            window_start = max(0, window_end - limit)
        return text[window_start:window_end].strip()
    return text[:limit]


def _retry_prompt(prompt: str, *, multi_source: bool = False) -> str:
    retry = (
        prompt
        + "\nA tentativa anterior falhou. Retorne obrigatoriamente apenas "
        "os campos answer, evidence_ids e limitations; nunca invente IDs."
    )
    if multi_source:
        retry += (
            " Há fontes distintas disponíveis: associe cada afirmação à fonte "
            "correspondente e separe as afirmações em frases diferentes. Inclua "
            "todos os evidence_id usados; se uma fonte não sustentar uma parte, "
            "omita essa parte e registre evidence_unavailable."
        )
    return retry


def _needs_multi_source_retry(
    parsed: SynthesisResponse, evidence: list[dict[str, Any]]
) -> bool:
    return _distinct_source_count(evidence) > 1 and (
        len(set(parsed.evidence_ids)) < 2 or _answer_sentence_count(parsed.answer) < 2
    )


def _distinct_source_count(evidence: list[dict[str, Any]]) -> int:
    return len(
        {
            str(item.get("standard") or "").strip()
            for item in evidence
            if str(item.get("standard") or "").strip()
        }
    )


def _answer_sentence_count(answer: str) -> int:
    return len(
        [
            part
            for part in re.split(
                r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])|\n+", answer
            )
            if part.strip()
        ]
    )


def _canonicalize_evidence_ids(
    parsed: SynthesisResponse, evidence: list[dict[str, Any]]
) -> SynthesisResponse:
    candidates = {
        str(item.get("evidence_id"))
        for item in evidence
        if str(item.get("evidence_id") or "").strip()
    }
    aliases: dict[str, str] = {}
    for candidate in candidates:
        prefix, marker, page = candidate.rpartition(":page:")
        if marker and prefix and page.isdigit():
            aliases[f"{prefix}:{page}"] = candidate
    normalized = [
        aliases.get(identifier, identifier) for identifier in parsed.evidence_ids
    ]
    if normalized == parsed.evidence_ids:
        return parsed
    return parsed.model_copy(update={"evidence_ids": list(dict.fromkeys(normalized))})


def _mark_multi_source_limit(
    parsed: SynthesisResponse, evidence: list[dict[str, Any]]
) -> SynthesisResponse:
    if _distinct_source_count(evidence) <= 1 or len(set(parsed.evidence_ids)) >= 2:
        return parsed
    if LimitationCode.EVIDENCE_UNAVAILABLE in parsed.limitations:
        return parsed
    return parsed.model_copy(
        update={
            "limitations": [
                *parsed.limitations,
                LimitationCode.EVIDENCE_UNAVAILABLE,
            ]
        }
    )


def _without_inline_ids(answer: str) -> str:
    cleaned = _INLINE_EVIDENCE_ID.sub("", answer)
    cleaned = re.sub(r"(?m)^[ \t]+(?=\r?$)", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


__all__ = ["SynthesisFailure", "Synthesizer"]
