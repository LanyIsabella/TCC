"""Schemas Pydantic para entrada e saida da rota do agente."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AllowedRole = Literal["user", "assistant", "system", "tool"]


def _nonempty_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} nao pode ser vazio.")
    return normalized


class ConversationMessage(BaseModel):
    """Representa uma mensagem individual dentro do historico da conversa."""

    model_config = ConfigDict(extra="forbid")

    role: AllowedRole
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """Garante que o texto da mensagem nao seja vazio."""

        return _nonempty_text(value, "content")


class PublicConversationMessage(ConversationMessage):
    """Histórico externo sem autoridade de mensagens internas do agente."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")
    role: Literal["user", "assistant"]

    @model_validator(mode="before")
    @classmethod
    def accept_existing_message(cls, value):
        if isinstance(value, ConversationMessage):
            return value.model_dump()
        return value


class AgentChatRequest(BaseModel):
    """Corpo aceito pela rota de conversa com o agente."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    history: list[PublicConversationMessage] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """Garante que a mensagem principal nao seja vazia."""

        return _nonempty_text(value, "message")


class AgentChatResponse(BaseModel):
    """Estrutura devolvida pela rota apos a execucao do agente."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    messages: list[ConversationMessage]
