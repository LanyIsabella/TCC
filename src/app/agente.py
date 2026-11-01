from functools import lru_cache
import json
import re
from typing import Any

from langchain.agents import create_agent

from .client import Client
from .prompt import load_prompt_sys
from .scope_guard import ScopeDecision, classify_messages, guarded_response
from .tools.rag_search import rag_document_search

NORMATIVE_TERMS = (
    "abnt", "norma", "citação", "citacao", "referência", "referencia",
    "formatação", "formatacao", "tcc", "sumário", "sumario", "resumo",
    "lombada", "seção", "secao",
)
STANDARD_PATTERN = re.compile(r"\b(?:ABNT\s+)?NBR\s+\d{4,5}\b", re.IGNORECASE)


class ScopedAgent:
    """Impede chamadas ao modelo para mensagens fora do escopo definido."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        decision = classify_messages(messages)
        if decision in {ScopeDecision.GREETING, ScopeDecision.OUT_OF_SCOPE}:
            return guarded_response(messages, decision)
        result = self._agent.invoke(payload)
        return self._ensure_normative_grounding(payload, result)

    def _ensure_normative_grounding(
        self, payload: dict[str, Any], result: Any
    ) -> dict[str, Any]:
        """Aplica a garantia de citação também no UI e no terminal."""
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            return result
        question = self._last_user_message(payload.get("messages", []))
        if not any(term in question.casefold() for term in NORMATIVE_TERMS):
            return result

        evidence = self._extract_evidence(result["messages"])
        assistant = self._last_assistant(result["messages"])
        if assistant is None:
            return result
        answer = self._content(assistant)
        if not evidence:
            self._set_content(
                assistant,
                "Não localizei evidência suficiente nos documentos normativos "
                "disponíveis para responder com segurança.",
            )
        elif not (
            "base normativa" in answer.casefold()
            and STANDARD_PATTERN.search(answer)
        ):
            self._set_content(
                assistant,
                f"{answer.rstrip()}\n\n{self._citation_block(evidence[0])}",
            )
        return result

    def _last_user_message(self, messages: Any) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if self._role(message) == "user":
                return self._content(message)
        return ""

    def _extract_evidence(self, messages: list[Any]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for message in messages:
            if self._role(message) != "tool":
                continue
            try:
                tool_result = json.loads(self._content(message))
            except (TypeError, ValueError):
                continue
            if not isinstance(tool_result, dict) or not tool_result.get("evidence_found"):
                continue
            documents = tool_result.get("documents")
            if isinstance(documents, list):
                evidence.extend(doc for doc in documents if isinstance(doc, dict))
        return evidence

    def _last_assistant(self, messages: list[Any]) -> Any | None:
        for message in reversed(messages):
            if self._role(message) == "assistant" and self._content(message):
                return message
        return None

    def _role(self, message: Any) -> str:
        if isinstance(message, dict):
            return {"ai": "assistant", "human": "user"}.get(
                str(message.get("role") or message.get("type")),
                str(message.get("role") or message.get("type") or ""),
            )
        return {"ai": "assistant", "human": "user"}.get(
            str(getattr(message, "role", None) or getattr(message, "type", None)),
            str(getattr(message, "role", None) or getattr(message, "type", None) or ""),
        )

    def _content(self, message: Any) -> str:
        raw = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, list):
            return "\n".join(
                item if isinstance(item, str) else str(item.get("text") or item.get("content") or "")
                for item in raw
                if isinstance(item, str) or isinstance(item, dict)
            ).strip()
        return str(raw or "").strip()

    def _set_content(self, message: Any, content: str) -> None:
        if isinstance(message, dict):
            message["content"] = content
        else:
            message.content = content

    def _citation_block(self, document: dict[str, Any]) -> str:
        standard = str(
            document.get("standard_label")
            or document.get("standard_id")
            or document.get("title")
            or "Documento normativo"
        ).strip()
        version = str(document.get("version") or "").strip()
        pages = []
        matched_pages = document.get("matched_pages")
        if isinstance(matched_pages, list):
            pages = [
                str(item.get("page_number"))
                for item in matched_pages
                if isinstance(item, dict) and item.get("page_number")
            ]
        if not pages and isinstance(document.get("pages"), list):
            pages = [str(page) for page in document["pages"] if page]
        label = f"- {standard}"
        if version:
            label += f":{version}"
        if pages:
            label += f", p. {', '.join(pages)}"
        return f"### Base normativa\n\n{label}."


@lru_cache(maxsize=1)
def build_agent():
    client = Client()
    system_prompt = load_prompt_sys()

    return ScopedAgent(
        create_agent(
            model=client.return_model(),
            tools=[rag_document_search],
            system_prompt=system_prompt,
        )
    )


agent = build_agent()

__all__ = ["agent", "build_agent"]
