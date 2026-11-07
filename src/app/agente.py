import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent

from .client import Client
from .evidence import AgentAnswer, looks_like_guarded_answer
from .prompt import load_prompt_sys
from .scope_guard import ScopeDecision, classify_messages, guarded_response
from .tools.rag_search import rag_document_search

logger = logging.getLogger(__name__)


class ScopedAgent:
    """Impede chamadas ao modelo para mensagens fora do escopo definido."""

    def __init__(
        self,
        agent: Any,
        fallback_model: Any | None = None,
        system_prompt: str = "",
    ) -> None:
        self._agent = agent
        self._fallback_model = fallback_model
        self._system_prompt = system_prompt

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        decision = classify_messages(messages)
        if decision in {ScopeDecision.GREETING, ScopeDecision.OUT_OF_SCOPE}:
            return guarded_response(messages, decision)
        result = self._agent.invoke(payload)
        if self._needs_synthesis(result):
            return self._synthesize_from_retrieval(payload, result)
        return result

    def _tool_payloads(self, result: Any) -> list[Mapping[str, Any]]:
        if not isinstance(result, Mapping):
            return []
        messages = result.get("messages")
        if not isinstance(messages, list):
            return []

        payloads: list[Mapping[str, Any]] = []
        for message in messages:
            role = str(
                getattr(message, "role", None)
                or getattr(message, "type", None)
                or (message.get("role") if isinstance(message, Mapping) else "")
                or (message.get("type") if isinstance(message, Mapping) else "")
                or ""
            )
            if role != "tool":
                continue
            content = (
                message.get("content")
                if isinstance(message, Mapping)
                else getattr(message, "content", None)
            )
            if not isinstance(content, str):
                continue
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                continue
            if (
                isinstance(parsed, Mapping)
                and parsed.get("status") == "success"
                and isinstance(parsed.get("documents"), list)
                and parsed["documents"]
            ):
                payloads.append(parsed)
        return payloads

    def _last_assistant_text(self, result: Any) -> str:
        if not isinstance(result, Mapping):
            return ""
        messages = result.get("messages")
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            role = str(
                getattr(message, "role", None)
                or getattr(message, "type", None)
                or (message.get("role") if isinstance(message, Mapping) else "")
                or (message.get("type") if isinstance(message, Mapping) else "")
                or ""
            )
            if role not in {"assistant", "ai"}:
                continue
            content = (
                message.get("content")
                if isinstance(message, Mapping)
                else getattr(message, "content", None)
            )
            if isinstance(content, str) and content.strip():
                return content.strip()
        return ""

    def _needs_synthesis(self, result: Any) -> bool:
        if self._fallback_model is None or not self._tool_payloads(result):
            return False
        answer = self._last_assistant_text(result)
        return not answer or looks_like_guarded_answer(answer)

    def _synthesize_from_retrieval(
        self, payload: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """Recupera a síntese quando o modelo falha após receber ToolMessage."""

        tool_payloads = self._tool_payloads(result)
        question = next(
            (
                str(message.get("content", ""))
                for message in reversed(payload.get("messages", []))
                if isinstance(message, Mapping) and message.get("role") == "user"
            ),
            "",
        )
        context = json.dumps(
            {"status": "success", "documents": [
                document
                for tool_payload in tool_payloads
                for document in tool_payload.get("documents", [])
            ]},
            ensure_ascii=False,
        )
        synthesis_messages = [
            {
                "role": "system",
                "content": (
                    f"{self._system_prompt}\n\n"
                    "O ciclo de ferramenta já foi concluído. Responda diretamente "
                    "à pergunta usando exclusivamente o contexto RAG validado. "
                    "Não recuse uma pergunta acadêmica com evidência. Não escreva "
                    "fontes, rodapés ou chamadas de ferramentas no texto."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pergunta do usuário: {question}\n\n"
                    f"Contexto RAG validado:\n{context}"
                ),
            },
        ]
        try:
            response = self._fallback_model.invoke(synthesis_messages)
        except Exception:
            logger.exception("Falha ao sintetizar a resposta após a recuperação RAG.")
            return result

        answer = getattr(response, "content", None)
        if not isinstance(answer, str) or not answer.strip():
            return result
        answer = answer.strip()
        for marker in ("`rag_document_search`", "rag_document_search"):
            if answer.startswith(marker):
                answer = answer[len(marker) :].lstrip(" :\n")
                break

        recovered = dict(result)
        recovered["messages"] = [
            *result.get("messages", []),
            {"role": "assistant", "content": answer},
        ]
        recovered.pop("structured_response", None)
        return recovered


@lru_cache(maxsize=1)
def build_agent():
    client = Client()
    system_prompt = load_prompt_sys()
    model = client.return_model()

    return ScopedAgent(
        create_agent(
            model=model,
            tools=[rag_document_search],
            system_prompt=system_prompt,
            response_format=AgentAnswer,
        ),
        fallback_model=model,
        system_prompt=system_prompt,
    )


agent = build_agent()

__all__ = ["agent", "build_agent"]
