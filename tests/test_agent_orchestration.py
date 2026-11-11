"""Regressões de recuperação/síntese: evitar chamadas e recusas indevidas."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from src.app.agente import ScopedAgent
from src.app.evidence import extract_agent_result
from src.app.grounding import INSUFFICIENT_EVIDENCE

QUESTION = "Qual a margem do TCC segundo a ABNT?"
SOURCE = "A margem direita deve medir 2 cm."
GUARDED = "Por favor, apresente sua pergunta."


def rag_payload(status="success", documents=None):
    if documents is None:
        documents = [{"evidence": [{"evidence_id": "e1", "text": SOURCE}]}]
    return {"status": status, "documents": documents}


class Inner:
    def __init__(self, answer=SOURCE, tool=None, structured=None):
        self.answer = answer
        self.tool = tool
        self.structured = structured
        self.payload = None

    def invoke(self, payload):
        self.payload = payload
        messages = [*payload["messages"]]
        if self.tool is not None:
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call",
                                "name": "rag_document_search",
                                "args": {"question": QUESTION},
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "name": "rag_document_search",
                        "tool_call_id": "call",
                        "content": json.dumps(self.tool),
                    },
                ]
            )
        if self.answer is not None:
            messages.append({"role": "assistant", "content": self.answer})
        result = {"messages": messages}
        if self.structured is not None:
            result["structured_response"] = self.structured
        return result


class Model:
    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=SOURCE)


@pytest.mark.parametrize(
    "structured", [None, {"answer": SOURCE, "evidence_ids": ["e1"]}]
)
def test_current_supported_answer_needs_no_hint_retrieval_or_synthesis(
    monkeypatch, structured
):
    model = Model()
    inner = Inner(
        answer=SOURCE if structured is None else GUARDED,
        tool=rag_payload(),
        structured=structured,
    )
    agent = ScopedAgent(inner, model)
    value = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
    expected = INSUFFICIENT_EVIDENCE if structured is None else SOURCE
    assert extract_agent_result(value).answer == expected
    assert model.calls == []
    assert [m["role"] for m in inner.payload["messages"]] == ["user"]


def test_orchestration_records_textual_completion_after_retrieval():
    value = ScopedAgent(Inner(SOURCE, rag_payload()), Model()).invoke(
        {"messages": [{"role": "user", "content": QUESTION}]}
    )

    assert value["_orchestration"] == {
        "completion_contract": "textual_after_retrieval",
        "completion_reason": "missing_structured_response_after_retrieval",
        "retrieval_recovery": "not_needed",
        "synthesis": "not_needed",
    }
    assert value["structured_response"].answer == INSUFFICIENT_EVIDENCE
    assert value["structured_response"].evidence_ids == []


def test_orchestration_records_scope_guard_without_retrieval():
    value = ScopedAgent(Inner()).invoke(
        {"messages": [{"role": "user", "content": "Qual a receita de bolo?"}]}
    )

    assert value["_orchestration"]["completion_contract"] == "scope_guard"
    assert value["_orchestration"]["retrieval_recovery"] == "not_needed"


def test_orchestration_records_invalid_structured_completion():
    value = ScopedAgent(
        Inner(
            SOURCE,
            rag_payload(),
            structured={"answer": SOURCE, "evidence_ids": "e1"},
        ),
        Model(),
    ).invoke({"messages": [{"role": "user", "content": QUESTION}]})

    assert value["_orchestration"]["completion_contract"] == "structured_invalid"


@pytest.mark.parametrize(
    "status,documents",
    [
        ("error", [{"evidence": [{"evidence_id": "e1", "text": SOURCE}]}]),
        ("success", []),
        ("success", {"malformed": True}),
    ],
)
def test_failed_or_empty_current_tool_does_not_trigger_synthesis(status, documents):
    model = Model()
    value = ScopedAgent(Inner(GUARDED, rag_payload(status, documents)), model).invoke(
        {"messages": [{"role": "user", "content": QUESTION}]}
    )
    assert extract_agent_result(value).answer == INSUFFICIENT_EVIDENCE
    assert model.calls == []


def test_uncertain_clarification_does_not_trigger_unnecessary_retrieval(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.app.agente.rag_document_search",
        SimpleNamespace(
            invoke=lambda payload: calls.append(payload) or json.dumps(rag_payload())
        ),
    )
    answer = "Você se refere à fonte ou à margem?"
    value = ScopedAgent(Inner(answer), Model()).invoke(
        {
            "messages": [{"role": "user", "content": "Você entende isso?"}],
        }
    )
    assert extract_agent_result(value).answer == answer
    assert calls == []


@pytest.mark.parametrize(
    "answer,question",
    [
        (None, "Explique isso."),
        (GUARDED, "Explique isso."),
        ("A margem deve medir 7 cm.", "Explique isso."),
        ("Recebi sua mensagem.", QUESTION),
    ],
)
def test_recovery_covers_missing_guarded_and_normative_candidates(
    monkeypatch, answer, question
):
    calls = []
    monkeypatch.setattr(
        "src.app.agente.rag_document_search",
        SimpleNamespace(
            invoke=lambda payload: calls.append(payload) or json.dumps(rag_payload())
        ),
    )
    model = Model()
    value = ScopedAgent(Inner(answer), model).invoke(
        {
            "messages": [{"role": "user", "content": question}],
        }
    )
    assert extract_agent_result(value).answer == SOURCE
    assert calls == [{"question": question}]
    assert len(model.calls) == 1


def test_missing_final_answer_after_current_tool_can_be_synthesized():
    model = Model()
    value = ScopedAgent(Inner(None, rag_payload()), model).invoke(
        {
            "messages": [{"role": "user", "content": QUESTION}],
        }
    )
    assert extract_agent_result(value).answer == SOURCE
    assert value["_orchestration"]["completion_contract"] == "textual_synthesis"
    assert (
        value["_orchestration"]["completion_reason"]
        == "controlled_textual_synthesis"
    )
    assert len(model.calls) == 1


def test_no_synthesis_is_attempted_without_configured_model(caplog):
    value = ScopedAgent(Inner(GUARDED, rag_payload())).invoke(
        {
            "messages": [{"role": "user", "content": QUESTION}],
        }
    )
    assert extract_agent_result(value).answer == INSUFFICIENT_EVIDENCE
    assert "Falha ao sintetizar" not in caplog.text


def test_synthesis_keeps_recent_context_and_message_roles():
    messages = [
        HumanMessage(content="Como formatar segundo a ABNT?"),
        AIMessage(content="Contexto 0"),
        HumanMessage(content="Como citar?"),
        AIMessage(content="Contexto 1"),
        HumanMessage(content="Como referenciar?"),
        AIMessage(content="Contexto 2"),
        HumanMessage(content=QUESTION),
    ]
    model = Model()
    value = ScopedAgent(Inner(GUARDED, rag_payload()), model).invoke(
        {"messages": messages}
    )
    assert extract_agent_result(value).answer == SOURCE
    assert model.calls[0][1:-1] == [
        {"role": "assistant", "content": "Contexto 0"},
        {"role": "human", "content": "Como citar?"},
        {"role": "assistant", "content": "Contexto 1"},
        {"role": "human", "content": "Como referenciar?"},
        {"role": "assistant", "content": "Contexto 2"},
    ]


def test_internal_langchain_prefill_is_kept_as_conversational_context():
    messages = [
        HumanMessage(content=QUESTION),
        AIMessage(content="Rascunho a continuar"),
    ]
    model = Model()
    value = ScopedAgent(Inner(GUARDED, rag_payload()), model).invoke(
        {"messages": messages}
    )
    assert extract_agent_result(value).answer == SOURCE
    assert model.calls[0][1:-1] == [
        {"role": "human", "content": QUESTION},
        {"role": "assistant", "content": "Rascunho a continuar"},
    ]


def test_short_font_question_recovers_documents_before_accepting_bare_answer(
    monkeypatch,
):
    calls = []
    source = "A fonte deve ser Arial."

    def search(payload):
        calls.append(payload)
        return json.dumps(
            rag_payload(
                documents=[{"evidence": [{"evidence_id": "e1", "text": source}]}]
            )
        )

    class FontModel(Model):
        def invoke(self, messages):
            self.calls.append(messages)
            return SimpleNamespace(content=source)

    monkeypatch.setattr(
        "src.app.agente.rag_document_search", SimpleNamespace(invoke=search)
    )
    model = FontModel()
    value = ScopedAgent(Inner("Arial."), model).invoke(
        {
            "messages": [{"role": "user", "content": "Qual a fonte?"}],
        }
    )
    assert calls == [{"question": "Qual a fonte?"}]
    assert extract_agent_result(value).answer == source
