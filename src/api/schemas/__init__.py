"""Modelos Pydantic compartilhados pelas rotas da API."""

from src.api.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    ConversationMessage,
)
from src.api.schemas.common import APIInfoResponse, ErrorResponse
from src.api.schemas.health import HealthResponse

__all__ = [
    "APIInfoResponse",
    "AgentChatRequest",
    "AgentChatResponse",
    "ConversationMessage",
    "ErrorResponse",
    "HealthResponse",
]
