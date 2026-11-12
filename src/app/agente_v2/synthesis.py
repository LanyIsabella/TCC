"""Síntese estruturada independente de tool calling de AgentAnswer."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from .schemas import SynthesisResponse

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
    ) -> SynthesisResponse:
        if self._structured is None:
            raise SynthesisFailure("Saída estruturada indisponível.")
        prompt = self._prompt(question, history, retrieval)
        for attempt in range(2):
            parsed = self._attempt(prompt, attempt)
            if parsed is not None:
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
        evidence = _prompt_evidence(retrieval)
        return (
            "Você é o sintetizador de um assistente acadêmico ABNT. Responda de "
            "forma clara e natural usando somente o texto dos trechos fornecidos. "
            "Pode explicar e combinar regras pertinentes, mas preserve integralmente "
            "números, unidades, obrigações, permissões, negações, condições e "
            "exceções; não copie fragmentos que não respondam ao aspecto perguntado. "
            "O título, o nome da norma, a similaridade lexical e o marcador "
            "direct_match não são prova factual. Para cada afirmação normativa "
            "sustentada, selecione um evidence_id existente. Se os trechos não "
            "responderem, use evidence_ids=[] e "
            "limitations=[\"evidence_unavailable\"]. "
            "Use partial_support quando a resposta for explicitamente parcial e "
            "synthesis_failed somente se o contrato não puder ser produzido. "
            "Retorne somente JSON com answer, evidence_ids e limitations.\n\n"
            f"Histórico contextual: {json.dumps(context, ensure_ascii=False)}\n"
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


def _prompt_evidence(retrieval: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for document in retrieval.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        for item in document.get("evidence", []):
            if not isinstance(item, Mapping):
                continue
            text = str(item.get("text") or "").strip()
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
                }
            )
    direct = [item for item in candidates if item["direct_match"]]
    selected = direct or candidates
    selected.sort(
        key=lambda item: (
            not item["direct_match"],
            not bool(item["evidence_id"]),
            str(item["evidence_id"]),
        )
    )
    return selected[:4]


def _retry_prompt(prompt: str) -> str:
    return (
        prompt
        + "\nA tentativa anterior falhou. Retorne obrigatoriamente apenas "
        "os campos answer, evidence_ids e limitations; nunca invente IDs."
    )


def _without_inline_ids(answer: str) -> str:
    cleaned = _INLINE_EVIDENCE_ID.sub("", answer)
    cleaned = re.sub(r"(?m)^[ \t]+(?=\r?$)", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


__all__ = ["SynthesisFailure", "Synthesizer"]
