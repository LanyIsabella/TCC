import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent

from .client import Client
from .evidence import AgentAnswer, looks_like_guarded_answer
from .prompt import load_prompt_sys
from .query_planner import contextualize_query
from .scope_guard import (
    ScopeDecision,
    classify_messages,
    guarded_response,
)
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
        logger.info(
            "scope_decision=%s message_count=%d",
            decision,
            len(messages),
        )
        if decision in {ScopeDecision.GREETING, ScopeDecision.OUT_OF_SCOPE}:
            return guarded_response(messages, decision)

        agent_payload = self._with_retrieval_hint(payload, messages)
        result = self._agent.invoke(agent_payload)
        if self._needs_retrieval_recovery(result, decision):
            result = self._recover_retrieval(
                payload,
                result,
                self._retrieval_query(messages),
            )
        if self._needs_synthesis(result):
            return self._synthesize_from_retrieval(payload, result)
        return result

    def _last_user_question(self, messages: list[Any]) -> str:
        for message in reversed(messages):
            role = str(
                getattr(message, "role", None)
                or getattr(message, "type", None)
                or (message.get("role") if isinstance(message, Mapping) else "")
                or (message.get("type") if isinstance(message, Mapping) else "")
                or ""
            )
            if role not in {"user", "human"}:
                continue
            content = (
                message.get("content")
                if isinstance(message, Mapping)
                else getattr(message, "content", None)
            )
            if isinstance(content, str) and content.strip():
                return content.strip()
        return ""

    def _content_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif isinstance(item, Mapping):
                    value = item.get("text") or item.get("content")
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
            return "\n".join(parts).strip()
        return str(content).strip() if content is not None else ""

    def _retrieval_query(self, messages: list[Any]) -> str:
        question = self._last_user_question(messages)
        current_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if str(
                    getattr(messages[index], "role", None)
                    or getattr(messages[index], "type", None)
                    or (
                        messages[index].get("role")
                        if isinstance(messages[index], Mapping)
                        else ""
                    )
                    or ""
                )
                in {"user", "human"}
            ),
            len(messages),
        )
        return contextualize_query(question, messages[:current_index])

    def _with_retrieval_hint(
        self,
        payload: dict[str, Any],
        messages: list[Any],
    ) -> dict[str, Any]:
        question = self._last_user_question(messages)
        retrieval_query = self._retrieval_query(messages)
        if not question or retrieval_query == question:
            return payload

        current_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if str(
                    getattr(messages[index], "role", None)
                    or getattr(messages[index], "type", None)
                    or (
                        messages[index].get("role")
                        if isinstance(messages[index], Mapping)
                        else ""
                    )
                    or ""
                )
                in {"user", "human"}
            ),
            len(messages),
        )
        hinted_messages = [
            *messages[:current_index],
            {
                "role": "system",
                "content": (
                    "Para a recuperação documental desta pergunta complementar, "
                    f"use esta consulta contextualizada: {retrieval_query}. "
                    "Preserve a pergunta original na resposta."
                ),
            },
            *messages[current_index:],
        ]
        logger.info("retrieval_context_hint_added=True")
        return {**payload, "messages": hinted_messages}

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
            content = self._content_text(content)
            if not content:
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
            content = self._content_text(content)
            if content:
                return content
        return ""

    def _needs_synthesis(self, result: Any) -> bool:
        tool_payloads = self._tool_payloads(result)
        if self._fallback_model is None or not tool_payloads:
            return False
        if isinstance(result, Mapping) and result.get("_force_synthesis"):
            return True
        structured = (
            result.get("structured_response")
            if isinstance(result, Mapping)
            else None
        )
        if structured is not None:
            structured_answer = (
                structured.get("answer")
                if isinstance(structured, Mapping)
                else getattr(structured, "answer", None)
            )
            if isinstance(structured_answer, str) and structured_answer.strip():
                return looks_like_guarded_answer(structured_answer)
        answer = self._last_assistant_text(result)
        logger.info(
            "synthesis_check tool_payloads=%d answer_chars=%d",
            len(tool_payloads),
            len(answer),
        )
        return not answer or looks_like_guarded_answer(answer)

    def _needs_retrieval_recovery(
        self,
        result: Any,
        decision: ScopeDecision,
    ) -> bool:
        if self._fallback_model is None or self._tool_payloads(result):
            return False
        if decision == ScopeDecision.IN_SCOPE:
            return True
        if isinstance(result, Mapping):
            structured = result.get("structured_response")
            structured_answer = (
                structured.get("answer")
                if isinstance(structured, Mapping)
                else getattr(structured, "answer", None)
            )
            if isinstance(structured_answer, str) and structured_answer.strip():
                return looks_like_guarded_answer(structured_answer)
        answer = self._last_assistant_text(result)
        return looks_like_guarded_answer(answer) or not answer

    def _recover_retrieval(
        self,
        payload: dict[str, Any],
        result: dict[str, Any],
        retrieval_query: str,
    ) -> dict[str, Any]:
        """Executa uma única recuperação quando o modelo pulou a ferramenta."""

        if not retrieval_query:
            return result
        try:
            tool_content = rag_document_search.invoke(
                {"question": retrieval_query}
            )
            parsed = json.loads(tool_content)
        except Exception:
            logger.exception("retrieval_recovery_failed=True")
            return result
        if not isinstance(parsed, Mapping) or parsed.get("status") != "success":
            logger.info("retrieval_recovery_without_evidence=True")
            return result
        logger.info(
            "retrieval_recovery=True documents=%d",
            len(parsed.get("documents", [])),
        )
        recovered = dict(result)
        recovered["messages"] = [
            *result.get("messages", []),
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": tool_content,
            },
        ]
        recovered["_force_synthesis"] = True
        return recovered

    def _synthesize_from_retrieval(
        self, payload: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """Recupera a síntese quando o modelo falha após receber ToolMessage."""

        tool_payloads = self._tool_payloads(result)
        original_messages = payload.get("messages", [])
        question = self._last_user_question(original_messages)
        history = [
            {
                "role": str(
                    getattr(message, "role", None)
                    or getattr(message, "type", None)
                    or (message.get("role") if isinstance(message, Mapping) else "")
                    or ""
                ),
                "content": str(
                    message.get("content")
                    if isinstance(message, Mapping)
                    else getattr(message, "content", "")
                )[:1500],
            }
            for message in original_messages
            if str(
                getattr(message, "role", None)
                or getattr(message, "type", None)
                or (message.get("role") if isinstance(message, Mapping) else "")
                or ""
            )
            in {"user", "human", "assistant", "ai"}
        ][-6:]
        if history and history[-1]["role"] in {"user", "human"}:
            history = history[:-1]
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
            *[
                {
                    "role": "assistant" if message["role"] == "ai" else message["role"],
                    "content": message["content"],
                }
                for message in history
            ],
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

        answer = self._content_text(getattr(response, "content", None))
        if not answer:
            return result
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
        recovered.pop("_force_synthesis", None)
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
