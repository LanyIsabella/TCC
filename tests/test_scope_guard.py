import json

from src.app.agente import ScopedAgent
from src.app.scope_guard import (
    GREETING_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    ScopeDecision,
    classify_messages,
)


class CountingAgent:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {
            "messages": [
                *payload["messages"],
                {"role": "assistant", "content": "LLM"},
            ]
        }


def test_scope_guard_accepts_academic_questions() -> None:
    messages = [{"role": "user", "content": "Como fazer citações ABNT?"}]

    assert classify_messages(messages) == ScopeDecision.IN_SCOPE
    assert (
        classify_messages([{"role": "user", "content": "Como fazer referencias?"}])
        == ScopeDecision.IN_SCOPE
    )


def test_scope_guard_accepts_broad_tcc_formatting_question() -> None:
    question = (
        "Quais são as principais regras de formatação de um TCC segundo a ABNT?"
    )

    assert classify_messages([{"role": "user", "content": question}]) == (
        ScopeDecision.IN_SCOPE
    )


def test_scope_guard_rejects_unrelated_questions() -> None:
    messages = [{"role": "user", "content": "Qual a previsão do tempo?"}]

    assert classify_messages(messages) == ScopeDecision.OUT_OF_SCOPE


def test_scope_guard_rejects_ambiguous_terms_in_nonacademic_context() -> None:
    assert (
        classify_messages(
            [{"role": "user", "content": "Qual é o resumo do filme?"}]
        )
        == ScopeDecision.OUT_OF_SCOPE
    )
    assert (
        classify_messages(
            [{"role": "user", "content": "Qual é a margem de lucro?"}]
        )
        == ScopeDecision.OUT_OF_SCOPE
    )
    assert (
        classify_messages(
            [{"role": "user", "content": "Qual é a norma de trânsito?"}]
        )
        == ScopeDecision.OUT_OF_SCOPE
    )


def test_scope_guard_allows_academic_follow_up() -> None:
    messages = [
        {"role": "user", "content": "Explique a NBR 6028."},
        {"role": "assistant", "content": "Resumo acadêmico."},
        {"role": "user", "content": "E nesse caso?"},
    ]

    assert classify_messages(messages) == ScopeDecision.IN_SCOPE


def test_scoped_agent_does_not_call_model_outside_scope() -> None:
    inner = CountingAgent()
    agent = ScopedAgent(inner)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Faça uma receita de bolo."}]}
    )

    assert inner.calls == 0
    assert result["messages"][-1]["content"] == OUT_OF_SCOPE_MESSAGE


def test_scoped_agent_handles_greetings_without_model() -> None:
    inner = CountingAgent()
    agent = ScopedAgent(inner)

    result = agent.invoke({"messages": [{"role": "user", "content": "Oi, tudo bem?"}]})

    assert inner.calls == 0
    assert result["messages"][-1]["content"] == GREETING_MESSAGE


def test_scoped_agent_does_not_accept_placeholder_for_academic_question() -> None:
    class PlaceholderAgent:
        def invoke(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "messages": [
                    *payload["messages"],
                    {
                        "role": "assistant",
                        "content": (
                            "Por favor, faça sua pergunta. Estou pronto para ajudar "
                            "com suas dúvidas sobre normas acadêmicas e ABNT."
                        ),
                    },
                ]
            }

    question = (
        "Quais são as principais regras de formatação de um TCC segundo a ABNT?"
    )
    result = ScopedAgent(PlaceholderAgent()).invoke(
        {"messages": [{"role": "user", "content": question}]}
    )

    assert "faça sua pergunta" not in result["messages"][-1]["content"]
    assert "base normativa" in result["messages"][-1]["content"].casefold()


def test_scoped_agent_recovers_rag_when_model_skips_tool(monkeypatch) -> None:
    class RecoverySearch:
        def invoke(self, _payload: dict[str, object]) -> str:
            return json.dumps(
                {
                    "evidence_found": True,
                    "documents": [
                        {
                            "standard_label": "ABNT NBR 14724",
                            "version": "2024",
                            "pages": [14],
                            "page_context": [
                                {
                                    "page_number": 14,
                                    "page_text": (
                                        "As margens devem ser de 3 cm e 2 cm."
                                    ),
                                }
                            ],
                        }
                    ],
                }
            )

    class RecoveringAgent:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            content = "Por favor, faça sua pergunta."
            return {
                "messages": [
                    *payload["messages"],
                    {"role": "assistant", "content": content},
                ]
            }

    monkeypatch.setattr("src.app.agente.rag_document_search", RecoverySearch())
    inner = RecoveringAgent()
    question = (
        "Quais são as principais regras de formatação de um TCC segundo a ABNT?"
    )

    result = ScopedAgent(inner).invoke(
        {"messages": [{"role": "user", "content": question}]}
    )

    answer = result["messages"][-1]["content"]
    assert inner.calls == 0
    assert "Por favor" not in answer
    assert "ABNT NBR 14724" in answer, result["messages"]


def test_scoped_agent_rejects_full_greeting_placeholder() -> None:
    class PlaceholderAgent:
        def invoke(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "messages": [
                    *payload["messages"],
                    {
                        "role": "assistant",
                        "content": (
                            "Olá! Sou seu assistente de normas acadêmicas e ABNT. "
                            "Estou à disposição para ajudar com suas dúvidas sobre "
                            "formatação, citações, referências e estrutura de "
                            "trabalhos acadêmicos. Como posso te auxiliar hoje?"
                        ),
                    },
                ]
            }

    question = (
        "Quais são as principais regras de formatação de um TCC segundo a ABNT?"
    )
    result = ScopedAgent(PlaceholderAgent()).invoke(
        {"messages": [{"role": "user", "content": question}]}
    )

    answer = result["messages"][-1]["content"]
    assert "Sou seu assistente" not in answer
    assert "Base normativa" in answer
