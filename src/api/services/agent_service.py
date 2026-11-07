"""Camada de servico responsavel por adaptar a chamada ao agente.

Este modulo recebe os dados validados pela API, monta o payload esperado
pela implementacao do agente e normaliza a resposta para os schemas HTTP.
"""

import json
import re
from typing import Any, Protocol

from src.api.core.exceptions import AgentExecutionError, AgentResponseError
from src.api.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    ConversationMessage,
)
from src.app.citation_validator import grounded_answer

ROLE_MAP = {"ai": "assistant", "human": "user"}
VALID_ROLES = {"assistant", "system", "tool", "user"}
NORMATIVE_TERMS = (
    "abnt", "norma", "citação", "citacao", "referência", "referencia",
    "formatação", "formatacao", "tcc", "sumário", "sumario", "resumo",
    "lombada", "seção", "secao",
)
STANDARD_PATTERN = re.compile(r"\b(?:ABNT\s+)?NBR\s+\d{4,5}\b", re.IGNORECASE)


class AgentExecutor(Protocol):
    """Contrato minimo esperado de um executor de agente."""

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class AgentService:
    """Orquestra a chamada ao agente e o tratamento da resposta."""

    def __init__(self, agent: AgentExecutor) -> None:
        """Armazena a instancia concreta do agente utilizada nas rotas."""

        self._agent = agent

    def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        """Executa uma interacao completa com o agente.

        Args:
            request: Dados da conversa recebidos pela API.

        Returns:
            AgentChatResponse: Resposta final pronta para serializacao HTTP.

        Raises:
            AgentExecutionError: Se a execucao do agente falhar.
            AgentResponseError: Se o formato da resposta for invalido.
        """

        payload = {
            "messages": [
                *[message.model_dump() for message in request.history],
                {"role": "user", "content": request.message},
            ]
        }

        try:
            result = self._agent.invoke(payload)
        except Exception as exc:
            raise AgentExecutionError("Falha ao executar o agente.") from exc

        messages = self._extract_messages(result)
        evidence = self._extract_rag_evidence(messages)
        normalized_messages = [
            self._normalize_message(message)
            for message in messages
            if not self._is_internal_tool_event(message)
        ]
        structured_answer = self._extract_structured_answer(result)
        answer = structured_answer or self._extract_answer(normalized_messages)
        public_messages = [
            message for message in normalized_messages if message.role != "tool"
        ]
        if structured_answer and not any(
            message.role == "assistant" and message.content == structured_answer
            for message in public_messages
        ):
            public_messages.append(
                ConversationMessage(role="assistant", content=structured_answer)
            )

        return AgentChatResponse(answer=answer, messages=public_messages)

    def _extract_rag_evidence(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Extrai documentos válidos retornados pela ferramenta RAG."""
        evidence: list[dict[str, Any]] = []
        for message in messages:
            if self._extract_role(message) != "tool":
                continue
            try:
                payload = json.loads(self._extract_content(message))
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or not payload.get("evidence_found"):
                continue
            documents = payload.get("documents")
            if isinstance(documents, list):
                evidence.extend(
                    document for document in documents if isinstance(document, dict)
                )
        return evidence

    def _ensure_normative_grounding(
        self, question: str, answer: str, evidence: list[dict[str, Any]]
    ) -> str:
        """Garante que respostas normativas apresentem a fonte recuperada."""
        if not self._requires_normative_source(question):
            return answer
        return grounded_answer(answer, evidence, question)
        if not evidence:
            return (
                "Não localizei evidência suficiente nos documentos normativos "
                "disponíveis para responder com segurança."
            )
        if "base normativa" in answer.casefold() and STANDARD_PATTERN.search(answer):
            return answer
        return f"{answer.rstrip()}\n\n{self._citation_block(evidence[0])}"

    def _requires_normative_source(self, question: str) -> bool:
        normalized = question.casefold()
        return any(term in normalized for term in NORMATIVE_TERMS)

    def _citation_block(self, document: dict[str, Any]) -> str:
        standard = str(
            document.get("standard_label")
            or document.get("standard_id")
            or document.get("title")
            or "Documento normativo"
        ).strip()
        version = str(document.get("version") or "").strip()
        pages: list[str] = []
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

    def _extract_messages(self, result: Any) -> list[Any]:
        """Extrai a lista de mensagens do retorno bruto do agente."""

        if not isinstance(result, dict):
            raise AgentResponseError(
                "O agente retornou um formato de resposta invalido."
            )

        messages = result.get("messages")
        if not isinstance(messages, list) or not messages:
            raise AgentResponseError("O agente retornou uma resposta sem mensagens.")

        return messages

    def _normalize_message(self, message: Any) -> ConversationMessage:
        """Converte diferentes formatos de mensagem para o schema padrao."""

        if isinstance(message, ConversationMessage):
            return message

        if isinstance(message, str):
            content = message.strip()
            if not content:
                raise AgentResponseError("O agente retornou uma mensagem vazia.")
            return ConversationMessage(role="assistant", content=content)

        role = self._extract_role(message)
        content = self._extract_content(message)
        if not content:
            raise AgentResponseError("O agente retornou uma mensagem vazia.")

        return ConversationMessage(role=role, content=content)

    def _extract_role(self, message: Any) -> str:
        """Identifica e normaliza o papel da mensagem retornada."""

        if isinstance(message, dict):
            raw_role = message.get("role") or message.get("type")
        else:
            raw_role = getattr(message, "role", None) or getattr(message, "type", None)

        role = ROLE_MAP.get(str(raw_role), str(raw_role or "assistant"))
        if role not in VALID_ROLES:
            raise AgentResponseError(
                "O agente retornou uma mensagem com papel invalido."
            )

        return role

    def _extract_content(self, message: Any) -> str:
        """Extrai o conteudo textual de uma mensagem do agente."""

        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)

        return self._normalize_content(content)

    def _is_internal_tool_event(self, message: Any) -> bool:
        """Identifica eventos intermediários que não são conversa pública."""

        if isinstance(message, dict):
            raw_role = message.get("role") or message.get("type")
            content = message.get("content")
            tool_calls = message.get("tool_calls")
        else:
            raw_role = getattr(message, "role", None) or getattr(message, "type", None)
            content = getattr(message, "content", None)
            tool_calls = getattr(message, "tool_calls", None)

        if str(raw_role) == "tool":
            return True
        return bool(tool_calls) and not self._normalize_content(content)

    def _extract_answer(self, messages: list[ConversationMessage]) -> str:
        """Seleciona a ultima resposta do assistente no historico normalizado."""

        for message in reversed(messages):
            if message.role == "assistant" and message.content:
                return message.content

        raise AgentResponseError("O agente nao retornou uma resposta do assistente.")

    def _extract_structured_answer(self, result: Any) -> str | None:
        """Extrai o texto quando o agente usou a saída estruturada."""

        if not isinstance(result, dict):
            return None
        structured = result.get("structured_response")
        if structured is None:
            return None
        if isinstance(structured, dict):
            answer = structured.get("answer")
        else:
            answer = getattr(structured, "answer", None)
        if not isinstance(answer, str) or not answer.strip():
            return None
        return answer.strip()

    def _normalize_content(self, content: Any) -> str:
        """Normaliza conteudos de diferentes formatos para texto simples."""

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                    continue

                if isinstance(item, dict):
                    for key in ("text", "content"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
                            break

            return "\n".join(parts).strip()

        if content is None:
            return ""

        return str(content).strip()
