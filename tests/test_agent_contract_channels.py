"""Contratos de publicação: o mesmo texto seguro em todos os consumidores."""

import json
from pathlib import Path

import pytest
from src.api.schemas.agent import AgentChatRequest
from src.api.services.agent_service import AgentService
from src.app.evidence import extract_agent_result, finalize_grounding
from src.app.grounding import INSUFFICIENT_EVIDENCE

QUESTION = "Qual a margem do TCC segundo a ABNT?"
UNSUPPORTED = "A margem direita deve medir 7 cm."
SOURCE = "A margem direita deve medir 2 cm."


def result(answer=UNSUPPORTED, text=SOURCE):
    return {
        "messages": [
            {"role": "user", "content": QUESTION},
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {"evidence": [{"evidence_id": "e1", "text": text}]}
                        ],
                    }
                ),
            },
            {"role": "assistant", "content": answer},
        ],
        "structured_response": {"answer": answer, "evidence_ids": ["e1"]},
    }


def test_api_does_not_leak_raw_structured_or_intermediate_unsupported_answers():
    class Executor:
        def invoke(self, payload):
            value = result()
            value["messages"].insert(
                -1, {"role": "assistant", "content": "A fonte deve ter 99 pontos."}
            )
            return value

    response = AgentService(Executor()).chat(AgentChatRequest(message=QUESTION))
    assert response.answer == INSUFFICIENT_EVIDENCE
    assert [m.content for m in response.messages] == [QUESTION, INSUFFICIENT_EVIDENCE]


def test_terminal_consumes_the_validated_answer(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src" / "terminal")
    )
    from src.terminal.main import ChatSession

    class Executor:
        def invoke(self, payload):
            return result()

    session = ChatSession(Executor())
    assert session.ask(QUESTION) == INSUFFICIENT_EVIDENCE
    assert session.history[-1]["content"] == INSUFFICIENT_EVIDENCE


def test_faithful_paraphrase_is_validated_once_and_reused_by_consumers():
    answer = "A margem direita mede dois centímetros."
    calls = []

    def verifier(*args):
        calls.append(args)
        return {
            "claims": [
                {"index": 0, "supported": True, "evidence_id": "e1", "quote": SOURCE}
            ]
        }

    value = finalize_grounding(result(answer), verifier)
    assert extract_agent_result(value).answer == answer
    assert extract_agent_result(value).evidences[0]["evidence_id"] == "e1"
    assert len(calls) == 1
    assert value["messages"][-1]["content"] == answer


@pytest.mark.parametrize("change", ["answer", "evidence", "question", "seal"])
def test_old_validation_cannot_approve_changed_response_inputs(change):
    value = finalize_grounding(result(SOURCE))
    if change == "answer":
        value["structured_response"].answer = UNSUPPORTED
    elif change == "evidence":
        value["messages"][1]["content"] = json.dumps(
            {"status": "no_evidence", "documents": []}
        )
    elif change == "question":
        value["messages"].extend(
            [
                {"role": "user", "content": "Qual a fonte do TCC?"},
                {"role": "assistant", "content": UNSUPPORTED},
            ]
        )
        value["structured_response"].answer = UNSUPPORTED
    else:
        value = result()
        value["_grounding"] = {"answer": UNSUPPORTED, "status": "supported"}
    assert extract_agent_result(value).answer == INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("status", ["no_evidence", "error", "malformed", "exception"])
def test_failed_recovery_never_preserves_candidate_or_prior_unsupported_rule(
    monkeypatch, status
):
    from types import SimpleNamespace

    from src.app.agente import ScopedAgent

    class Inner:
        def invoke(self, payload):
            return {
                "messages": [
                    *payload["messages"],
                    {"role": "assistant", "content": UNSUPPORTED},
                ]
            }

    def search(_payload):
        if status == "exception":
            raise TimeoutError("fixture")
        if status == "malformed":
            return "[]"
        return json.dumps({"status": status, "documents": []})

    monkeypatch.setattr(
        "src.app.agente.rag_document_search", SimpleNamespace(invoke=search)
    )
    value = ScopedAgent(Inner(), object()).invoke(
        {
            "messages": [
                {"role": "user", "content": QUESTION},
                {"role": "assistant", "content": UNSUPPORTED},
                {"role": "user", "content": QUESTION},
            ]
        }
    )
    assert extract_agent_result(value).answer == INSUFFICIENT_EVIDENCE
    assert value["messages"][-1]["content"] == INSUFFICIENT_EVIDENCE
    assert value["_grounding"].decision.status == "insufficient"
    if status in {"malformed", "exception"}:
        from src.app.evidence import _tool_payloads

        events = _tool_payloads(value)
        assert events[-1]["status"] == "error"
        assert events[-1]["evidence_found"] is False


def test_existing_model_verifies_paraphrase_with_current_execution_and_no_extra_tool(
    monkeypatch,
):
    from types import SimpleNamespace

    from src.app.agente import ScopedAgent

    answer = "A margem direita mede dois centímetros."

    class Inner:
        def invoke(self, payload):
            value = result(answer)
            value["messages"][0] = payload["messages"][-1]
            value["messages"].insert(
                1,
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-current",
                            "name": "rag_document_search",
                            "args": {"question": QUESTION},
                        }
                    ],
                },
            )
            value["messages"][2]["tool_call_id"] = "call-current"
            return value

    class Model:
        def __init__(self):
            self.calls = []

        def invoke(self, messages):
            self.calls.append(messages)
            data = json.loads(messages[-1]["content"])
            assert data["claims"] == [answer]
            assert data["evidences"]["e1"]["tool_call_id"] == "call-current"
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "claims": [
                            {
                                "index": 0,
                                "supported": True,
                                "evidence_id": "e1",
                                "quote": SOURCE,
                            }
                        ]
                    }
                )
            )

    def unexpected(_payload):
        pytest.fail("A execução atual já recuperou evidências; não repetir tool")

    monkeypatch.setattr(
        "src.app.agente.rag_document_search", SimpleNamespace(invoke=unexpected)
    )
    model = Model()
    response = ScopedAgent(Inner(), model).invoke(
        {"messages": [{"role": "user", "content": QUESTION}]}
    )
    assert extract_agent_result(response).answer == answer
    assert len(model.calls) == 1
    assert (
        extract_agent_result(response).evidences[0]["question_sha256"]
        == response["_turn"].question_sha256
    )


def test_api_validates_short_answer_against_actual_request():
    class Executor:
        def invoke(self, payload):
            return {"messages": [{"role": "assistant", "content": "Arial."}]}

    response = AgentService(Executor()).chat(
        AgentChatRequest(message="Qual a fonte do TCC?")
    )
    assert response.answer == INSUFFICIENT_EVIDENCE


def test_implicit_followup_still_needs_evidence_from_current_turn():
    from src.app.agente import ScopedAgent

    class Inner:
        def invoke(self, payload):
            return {
                "messages": [
                    *payload["messages"],
                    {"role": "assistant", "content": "Arial."},
                ]
            }

    value = ScopedAgent(Inner()).invoke(
        {
            "messages": [
                {"role": "user", "content": "Como formatar um TCC segundo a ABNT?"},
                {"role": "assistant", "content": "Podemos consultar a norma."},
                {"role": "user", "content": "E nesse caso?"},
            ]
        }
    )
    assert extract_agent_result(value).answer == INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("stage", ["invoke", "empty_messages", "empty_answer"])
def test_terminal_retains_error_history_when_validation_fails(monkeypatch, stage):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "src" / "terminal")
    )
    from src.terminal.main import ChatSession

    class Executor:
        def invoke(self, payload):
            if stage == "invoke":
                raise RuntimeError("fixture: invoke")
            if stage == "empty_messages":
                return {"messages": []}
            return {"messages": [{"role": "assistant", "content": ""}]}

    session = ChatSession(Executor())
    with pytest.raises(RuntimeError):
        session.ask(QUESTION)
    assert session.history[-1]["entry_type"] == "error"
    assert session.history[-1]["stage"] == (
        "invoke" if stage == "invoke" else "validation"
    )
    if stage == "empty_messages":
        assert "sem mensagens" in session.history[-1]["message"]
