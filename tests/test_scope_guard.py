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
