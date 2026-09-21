"""Camada de servico responsavel por adaptar a chamada ao agente.

Este modulo recebe os dados validados pela API, monta o payload esperado
pela implementacao do agente e normaliza a resposta para os schemas HTTP.
"""

from typing import Any, Protocol

from src.api.core.exceptions import AgentExecutionError, AgentResponseError
from src.api.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    ConversationMessage,
)

ROLE_MAP = {"ai": "assistant", "human": "user"}
VALID_ROLES = {"assistant", "system", "tool", "user"}


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
        normalized_messages = [
            self._normalize_message(message)
            for message in messages
            if not self._is_internal_tool_event(message)
        ]
        answer = self._extract_answer(normalized_messages)
        public_messages = [
            message for message in normalized_messages if message.role != "tool"
        ]

        return AgentChatResponse(answer=answer, messages=public_messages)

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
