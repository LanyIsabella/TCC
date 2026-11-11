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
    PublicEvidence,
)
from src.app.evidence import extract_agent_result, public_evidence


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

        self._extract_messages(result)
        try:
            extracted = extract_agent_result(result, question=request.message)
        except RuntimeError as exc:
            raise AgentResponseError(str(exc)) from exc
        public_messages = [
            *request.history,
            ConversationMessage(role="user", content=request.message),
            ConversationMessage(role="assistant", content=extracted.answer),
        ]
        return AgentChatResponse(
            answer=extracted.answer,
            messages=public_messages,
            evidences=[
                PublicEvidence.model_validate(public_evidence(evidence))
                for evidence in extracted.evidences
            ],
            grounding_status=extracted.grounding_status,
            limitations=list(extracted.limitations),
        )

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
