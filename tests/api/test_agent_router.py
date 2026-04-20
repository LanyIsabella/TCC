from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from src.api.core.exceptions import AgentExecutionError
from src.api.dependencies import get_agent_service
from src.api.main import create_app
from src.api.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    ConversationMessage,
)


class FakeAgentService:
    def __init__(self, *, response: AgentChatResponse | None = None) -> None:
        self._response = response

    def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        if self._response is not None:
            return self._response

        return AgentChatResponse(
            answer="Resposta gerada",
            messages=[
                *request.history,
                ConversationMessage(role="user", content=request.message),
                ConversationMessage(role="assistant", content="Resposta gerada"),
            ],
        )


class ExplodingAgentService:
    def chat(self, _request: AgentChatRequest) -> AgentChatResponse:
        raise AgentExecutionError("Falha ao executar o agente.")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_chat_agent_returns_response(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_service] = lambda: FakeAgentService()

    response = client.post(
        "/api/v1/agent/chat",
        json={
            "message": "Como faco uma citacao direta curta?",
            "history": [
                {
                    "role": "assistant",
                    "content": "Posso ajudar com normas ABNT.",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Resposta gerada",
        "messages": [
            {
                "role": "assistant",
                "content": "Posso ajudar com normas ABNT.",
            },
            {
                "role": "user",
                "content": "Como faco uma citacao direta curta?",
            },
            {
                "role": "assistant",
                "content": "Resposta gerada",
            },
        ],
    }


def test_chat_agent_validates_empty_message(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_service] = lambda: FakeAgentService()

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "   ", "history": []},
    )

    assert response.status_code == 422


def test_chat_agent_maps_service_errors(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_service] = lambda: ExplodingAgentService()

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "Teste de falha", "history": []},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Falha ao executar o agente."}
