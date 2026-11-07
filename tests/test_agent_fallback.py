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
