"""Rotas HTTP relacionadas a interacao com o agente."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.api.dependencies import get_agent_service
from src.api.schemas.agent import AgentChatRequest, AgentChatResponse
from src.api.schemas.common import ErrorResponse
from src.api.services.agent_service import AgentService

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    summary="Executa uma interacao com o agente",
)
def chat_agent(
    payload: AgentChatRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentChatResponse:
    """Executa uma conversa com o agente a partir da mensagem recebida.

    Args:
        payload: Corpo da requisicao contendo mensagem atual e historico.
        service: Servico injetado responsavel pela chamada ao agente.

    Returns:
        AgentChatResponse: Resposta final do assistente e mensagens
        normalizadas da conversa.
    """

    return service.chat(payload)
