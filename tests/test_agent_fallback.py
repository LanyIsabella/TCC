"""Testes do fallback de síntese após ToolMessage mal interpretado."""

import json

from src.app.agente import ScopedAgent


class FailingAgent:
    def invoke(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "messages": [
                *payload["messages"],
                {
                    "role": "tool",
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
                                                "Elementos de referências de livros."
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
                {"role": "assistant", "content": "Resposta contextual."},
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


def test_scoped_agent_adds_contextual_retrieval_hint_without_rewriting_user_message(
) -> None:
    inner = RecordingAgent()
    agent = ScopedAgent(inner)
    messages = [
        {"role": "user", "content": "Como formatar um TCC segundo a ABNT?"},
        {"role": "assistant", "content": "A formatação inclui recuos."},
        {"role": "user", "content": "Qual o tamanho do recuo necessário?"},
    ]

    result = agent.invoke({"messages": messages})

    assert result["messages"][-1]["content"] == "Resposta contextual."
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
                                    "text": "O recuo deve ser verificado na norma.",
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


def test_scoped_agent_retries_once_when_answer_is_related_but_not_adherent() -> None:
    class OffTopicAgent:
        def invoke(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "messages": [
                    *payload["messages"],
                    {
                        "role": "tool",
                        "name": "rag_document_search",
                        "content": json.dumps(
                            {
                                "status": "success",
                                "documents": [
                                    {
                                        "title": "Trabalhos acadêmicos",
                                        "evidence": [
                                            {
                                                "evidence_id": "document:14724:page:11",
                                                "text": (
                                                    "As margens devem ser esquerda "
                                                    "e superior de 3 cm."
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
                        "content": "A resposta trata apenas de lombadas.",
                    },
                ]
            }

    class CorrectiveModel:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _messages: list[dict[str, str]]) -> object:
            self.calls += 1
            return type(
                "Response",
                (),
                {
                    "content": (
                        "A formatação geral inclui margens, fonte, espaçamento "
                        "e paginação, conforme as passagens recuperadas."
                    )
                },
            )()

    corrective_model = CorrectiveModel()
    agent = ScopedAgent(
        OffTopicAgent(),
        corrective_model,
        "Você é um assistente acadêmico.",
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Quais são as principais regras de formatação de um TCC?"
                    ),
                }
            ]
        }
    )

    assert corrective_model.calls == 1
    assert "margens" in result["messages"][-1]["content"]
