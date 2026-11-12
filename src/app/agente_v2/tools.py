"""Registro controlado de ferramentas reutilizando as tools existentes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from src.app.tools.rag_search import rag_document_search

from .schemas import ToolExecution


class ToolRegistry:
    """Executa somente ferramentas registradas e preserva sua proveniência."""

    def __init__(self, tools: Mapping[str, Any] | None = None) -> None:
        self._tools = dict(tools or {"rag_document_search": rag_document_search})

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str,
        turn_id: str,
    ) -> ToolExecution:
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return ToolExecution(
                tool_name=name,
                conversation_id=conversation_id,
                turn_id=turn_id,
                query="",
                status="error",
                raw_result={
                    "status": "error",
                    "evidence_found": False,
                    "documents": [],
                    "message": "Consulta vazia.",
                },
            )
        tool = self._tools.get(name)
        if tool is None:
            return ToolExecution(
                tool_name=name,
                conversation_id=conversation_id,
                turn_id=turn_id,
                query=question,
                status="error",
                raw_result={
                    "status": "error",
                    "evidence_found": False,
                    "documents": [],
                    "message": "Ferramenta indisponível.",
                },
            )
        try:
            raw = tool.invoke(dict(arguments))
            parsed = raw if isinstance(raw, Mapping) else json.loads(str(raw))
            if not isinstance(parsed, Mapping):
                raise ValueError("Resultado da ferramenta não é um objeto.")
            status = str(parsed.get("status") or "error")
            return ToolExecution(
                tool_name=name,
                conversation_id=conversation_id,
                turn_id=turn_id,
                query=question,
                status=status,
                raw_result=dict(parsed),
            )
        except Exception as exc:
            return ToolExecution(
                tool_name=name,
                conversation_id=conversation_id,
                turn_id=turn_id,
                query=question,
                status="error",
                raw_result={
                    "status": "error",
                    "evidence_found": False,
                    "documents": [],
                    "message": "A ferramenta falhou.",
                    "error_type": type(exc).__name__,
                },
            )


__all__ = ["ToolRegistry"]
