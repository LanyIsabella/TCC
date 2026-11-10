"""Testes do fallback de síntese após ToolMessage mal interpretado."""

import json

from src.app.agente import ScopedAgent


class FailingAgent:
    def invoke(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "messages": [
                *payload["messages"],
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "rag-call",
                            "name": "rag_document_search",
                            "args": {"question": "Referências de livros"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "rag-call",
                    "name": "rag_document_search",
                    "content": json.dumps(
                        {
                            "status": "success",
                            "documents": [
                                {
                                    "title": "ABNT NBR 6023",
                                    "evidence": [
                                        {
                                            "evidence_id": "document:1:page:7",
                                            "page_number": 7,
                                            "text": (
                                                "Use a ABNT NBR 6023 "
                                                "para organizar as referências."
                                            ),
                                        }
                                    ],
                                }
                            ],
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Por favor, apresente sua pergunta sobre normas acadêmicas."
                    ),
                },
            ]
        }


class SynthesisModel:
    def invoke(self, _messages: list[dict[str, str]]) -> object:
        return type(
            "Response",
            (),
            {"content": "Use a ABNT NBR 6023 para organizar as referências."},
        )()


class RecordingAgent:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def invoke(self, payload: dict[str, object]) -> dict[str, object]:
        self.payload = payload
        return {
            "messages": [
                *payload["messages"],
                {
                    "role": "assistant",
                    "content": "Você se refere ao recuo de parágrafo ou de citação?",
                },
            ]
        }


def test_scoped_agent_recovers_from_generic_answer_after_successful_rag() -> None:
    agent = ScopedAgent(FailingAgent(), SynthesisModel(), "Você é um assistente.")

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Como montar as referências de um livro?",
                }
            ]
        }
    )

    assert result["messages"][-1]["content"].startswith("Use a ABNT NBR 6023")


def test_contextual_hint_preserves_user_question() -> None:
    inner = RecordingAgent()
    agent = ScopedAgent(inner)
    messages = [
        {"role": "user", "content": "Como formatar um TCC segundo a ABNT?"},
        {"role": "assistant", "content": "A formatação inclui recuos."},
        {"role": "user", "content": "Qual o tamanho do recuo necessário?"},
    ]

    result = agent.invoke({"messages": messages})

    assert (
        result["messages"][-1]["content"]
        == "Você se refere ao recuo de parágrafo ou de citação?"
    )
    assert inner.payload is not None
    payload_messages = inner.payload["messages"]
    assert any(
        message.get("role") == "system"
        and "Como formatar um TCC" in message.get("content", "")
        for message in payload_messages
    )
    assert payload_messages[-1]["content"] == "Qual o tamanho do recuo necessário?"


def test_scoped_agent_recovers_rag_even_when_model_answer_is_not_generic(
    monkeypatch,
) -> None:
    class AnsweringAgent:
        def invoke(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "messages": [
                    *payload["messages"],
                    {"role": "assistant", "content": "O recuo é de 1,25 cm."},
                ]
            }

    class RecoverySearch:
        def invoke(self, _payload: dict[str, object]) -> str:
            return json.dumps(
                {
                    "status": "success",
                    "documents": [
                        {
                            "title": "ABNT NBR 14724",
                            "evidence": [
                                {
                                    "evidence_id": "document:1:page:14",
                                    "text": (
                                        "A orientação deve ser confirmada "
                                        "na ABNT NBR 14724."
                                    ),
                                }
                            ],
                        }
                    ],
                }
            )

    class GroundedModel:
        def invoke(self, _messages: list[dict[str, str]]) -> object:
            return type(
                "Response",
                (),
                {"content": "A orientação deve ser confirmada na ABNT NBR 14724."},
            )()

    monkeypatch.setattr("src.app.agente.rag_document_search", RecoverySearch())
    agent = ScopedAgent(AnsweringAgent(), GroundedModel(), "Você é um assistente.")

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar um TCC?"}]}
    )

    assert result["messages"][-1]["content"].startswith(
        "A orientação deve ser confirmada"
    )
