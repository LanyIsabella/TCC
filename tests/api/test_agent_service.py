from types import SimpleNamespace

import pytest
from src.api.core.exceptions import AgentExecutionError, AgentResponseError
from src.api.schemas.agent import AgentChatRequest
from src.api.services.agent_service import AgentService
from src.app.evidence import AgentAnswer


class SuccessfulExecutor:
    def invoke(self, _payload: dict[str, object]) -> dict[str, object]:
        return {
            "messages": [
                {"role": "user", "content": "Pergunta original"},
                SimpleNamespace(type="ai", content=[{"text": "Resposta final"}]),
            ]
        }


class BrokenExecutor:
    def invoke(self, _payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")


class InvalidResponseExecutor:
    def invoke(self, _payload: dict[str, object]) -> dict[str, object]:
        return {"messages": [{"role": "tool", "content": "busca"}]}


class ToolCallingExecutor:
    def invoke(self, _payload: dict[str, object]) -> dict[str, object]:
        return {
            "messages": [
                {"role": "user", "content": "Pergunta original"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"name": "rag_document_search"}],
                },
                {
                    "role": "tool",
                    "content": (
                        '{"status":"success","evidence_found":true,'
                        '"documents":[{"standard_label":"ABNT NBR 10520",'
                        '"version":"2023","matched_pages":[{"page_number":12}]}]}'
                    ),
                },
                {"role": "assistant", "content": "Resposta fundamentada"},
            ]
        }


class StructuredExecutor:
    def invoke(self, _payload: dict[str, object]) -> dict[str, object]:
        return {
            "messages": [
                {"role": "user", "content": "Pergunta original"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"name": "AgentAnswer"}],
                },
            ],
            "structured_response": AgentAnswer(answer="Resposta estruturada."),
        }


def test_agent_service_normalizes_messages() -> None:
    service = AgentService(agent=SuccessfulExecutor())

    response = service.chat(AgentChatRequest(message="Olá"))

    assert response.answer == "Resposta final"
    assert response.messages[0].role == "user"
    assert response.messages[1].role == "assistant"
    assert response.messages[1].content == "Resposta final"


def test_agent_service_wraps_execution_errors() -> None:
    service = AgentService(agent=BrokenExecutor())

    with pytest.raises(AgentExecutionError):
        service.chat(AgentChatRequest(message="Explique ABNT"))


def test_agent_service_requires_assistant_answer() -> None:
    service = AgentService(agent=InvalidResponseExecutor())

    with pytest.raises(AgentResponseError):
        service.chat(AgentChatRequest(message="Explique ABNT"))


def test_agent_service_hides_internal_tool_events() -> None:
    service = AgentService(agent=ToolCallingExecutor())

    response = service.chat(AgentChatRequest(message="Explique ABNT"))

    assert response.answer == (
        "Resposta fundamentada\n\n"
        "### Base normativa\n\n"
        "- ABNT NBR 10520:2023, p. 12."
    )
    assert [message.role for message in response.messages] == ["user", "assistant"]


def test_agent_service_exposes_structured_answer_as_public_message() -> None:
    service = AgentService(agent=StructuredExecutor())

    response = service.chat(AgentChatRequest(message="Explique ABNT"))

    assert response.answer == "Resposta estruturada."
    assert [message.role for message in response.messages] == ["user", "assistant"]
    assert response.messages[-1].content == "Resposta estruturada."
