"""Síntese estruturada independente de tool calling de AgentAnswer."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from .schemas import SynthesisResponse

logger = logging.getLogger(__name__)


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
            try:
                value = self._structured.invoke(
                    [{"role": "system", "content": prompt}]
                )
                parsed = self._parsed(value)
                if parsed is not None:
                    return parsed
            except Exception:
                logger.exception("synthesis_attempt_failed attempt=%d", attempt + 1)
            prompt = (
                prompt
                + "\nA tentativa anterior falhou. Retorne obrigatoriamente apenas "
                "os campos answer, evidence_ids e limitations; nunca invente IDs."
            )
        raise SynthesisFailure("A síntese não produziu um contrato válido.")

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
        return (
            "Você é o sintetizador de um assistente acadêmico. Responda à pergunta "
            "usando somente as evidências documentais fornecidas. Para cada afirmação "
            "normativa, prefira copiar literalmente uma frase completa da evidência "
            "(incluindo o identificador da seção quando houver) e selecione seu "
            "evidence_id. Não invente IDs, números, condições ou exceções. Se não "
            "houver suporte, escreva uma limitação e deixe evidence_ids vazio. "
            "Retorne somente o contrato estruturado.\n\n"
            f"Histórico contextual: {json.dumps(context, ensure_ascii=False)}\n"
            f"Pergunta: {question}\n"
            f"Recuperação: {json.dumps(retrieval, ensure_ascii=False)}"
        )

    def _parsed(self, value: Any) -> SynthesisResponse | None:
        if isinstance(value, SynthesisResponse):
            return value
        if isinstance(value, Mapping):
            parsed = value.get("parsed")
            if isinstance(parsed, SynthesisResponse):
                return parsed
            if isinstance(parsed, Mapping):
                return SynthesisResponse.model_validate(parsed)
            if "answer" in value:
                return SynthesisResponse.model_validate(value)
        return None


__all__ = ["SynthesisFailure", "Synthesizer"]
