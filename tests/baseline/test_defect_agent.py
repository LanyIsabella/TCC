"""Deterministic F6/F10-F13 witnesses using real agent/evidence/API code."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from src.api.schemas.agent import AgentChatRequest
from src.api.services.agent_service import AgentService
from src.app.evidence import extract_agent_result
from src.app.grounding import INSUFFICIENT_EVIDENCE
from src.app.tools.rag_search import _compact_document

NORMATIVE_ANSWER = "A margem direita deve medir 7 cm."
QUESTION = "Como formatar as margens de um TCC segundo a ABNT?"
LATE_RULE = "REGRA SINTÉTICA: a margem direita mede 2 cm."


class RecordingAgent:
    def __init__(self):
        self.payload = None

    def invoke(self, payload):
        self.payload = payload
        return {
            "messages": [
                *payload["messages"],
                {"role": "assistant", "content": NORMATIVE_ANSWER},
            ]
        }


@pytest.fixture
def scoped_agent_class(monkeypatch):
    # agente.py builds a global model at import; replace construction, never invoke it.
    import langchain.agents
    from src.app import client

    monkeypatch.setattr(
        client, "Client", lambda: SimpleNamespace(return_model=lambda: object())
    )
    monkeypatch.setattr(langchain.agents, "create_agent", lambda **_: RecordingAgent())
    return importlib.import_module("src.app.agente").ScopedAgent


@pytest.fixture(params=["late-in-page", "late-in-document"])
def compacted_late_rule(request):
    if request.param == "late-in-page":
        contexts = [
            {
                "page_number": 1,
                "direct_match": True,
                "page_text": "Introdução sintética. " * 100 + LATE_RULE,
            }
        ]
    else:
        contexts = [
            {
                "page_number": number,
                "direct_match": True,
                "page_text": f"Página {number}. " + "texto neutro " * 150,
            }
            for number in range(1, 4)
        ]
        contexts.append(
            {"page_number": 4, "direct_match": True, "page_text": LATE_RULE}
        )
    document = {
        "document_id": 9001,
        "title": "Fixture sintética, sem valor normativo",
        "full_text": "x" * 6100 + LATE_RULE,
        "page_context": contexts,
        "pages": [context["page_number"] for context in contexts],
    }
    return _compact_document(document, "Qual a margem direita?")


def test_f6_compaction_preserves_late_rule_and_records_omission(compacted_late_rule):
    compact = compacted_late_rule
    assert compact is not None
    assert compact["full_text"] is None
    assert compact["evidence"]
    assert all(len(page["page_text"]) <= 1800 for page in compact["page_context"])
    assert sum(len(page["page_text"]) for page in compact["page_context"]) <= 5000
    assert LATE_RULE in json.dumps(compact, ensure_ascii=False)
    assert compact["omitted_content"]["characters"] > 0


def test_f6_contract_answer_bearing_rule_survives_compaction(compacted_late_rule):
    assert compacted_late_rule is not None
    assert any(
        LATE_RULE in evidence["text"] for evidence in compacted_late_rule["evidence"]
    )


@pytest.fixture
def no_evidence_recovery(monkeypatch, scoped_agent_class):
    calls = []

    def search(payload):
        calls.append(payload)
        return json.dumps(
            {"status": "no_evidence", "evidence_found": False, "documents": []}
        )

    monkeypatch.setattr(
        "src.app.agente.rag_document_search", SimpleNamespace(invoke=search)
    )
    inner = RecordingAgent()
    agent = scoped_agent_class(inner, fallback_model=object())
    result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
    assert calls == [{"question": QUESTION}]
    return result


def test_f10_regression_current_answer_reports_documentary_limitation(
    no_evidence_recovery,
):
    extracted = extract_agent_result(no_evidence_recovery)
    assert extracted.answer == INSUFFICIENT_EVIDENCE
    assert extracted.evidences == []


def test_f10_contract_empty_recovery_withholds_normative_answer(no_evidence_recovery):
    assert no_evidence_recovery["messages"][-1]["content"] == INSUFFICIENT_EVIDENCE


@pytest.fixture
def contradictory_result():
    evidence = {
        "evidence_id": "synthetic:9001:page:1",
        "page_number": 1,
        "text": "A margem direita deve medir 2 cm.",
        "matched_text": "A margem direita deve medir 2 cm.",
    }
    return {
        "messages": [
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {"title": "Fixture sintética", "evidence": [evidence]}
                        ],
                    }
                ),
            }
        ],
        "structured_response": {
            "answer": NORMATIVE_ANSWER,
            "evidence_ids": [evidence["evidence_id"]],
        },
    }


def test_f11_regression_literal_supported_rule_remains_available(
    contradictory_result,
):
    contradictory_result["structured_response"]["answer"] = (
        "A margem direita deve medir 2 cm."
    )
    result = extract_agent_result(contradictory_result)
    assert result.answer == "A margem direita deve medir 2 cm."
    assert [item["text"] for item in result.evidences] == [
        "A margem direita deve medir 2 cm."
    ]


def test_f11_contract_contradictory_evidence_cannot_validate_answer(
    contradictory_result,
):
    result = extract_agent_result(contradictory_result)
    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidences == []


def test_f11_regression_clarification_without_evidence_is_preserved():
    answer = "Você se refere à margem direita ou esquerda?"
    result = extract_agent_result(
        {"structured_response": {"answer": answer, "evidence_ids": []}}
    )
    assert result.answer == answer
    assert result.evidences == []


def test_f11_contract_no_evidence_requires_abstention_or_rejection():
    result = extract_agent_result(
        {"structured_response": {"answer": NORMATIVE_ANSWER, "evidence_ids": []}}
    )
    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidences == []


@pytest.fixture
def recovery_after_previous_turn(monkeypatch, scoped_agent_class):
    calls = []

    def search(payload):
        calls.append(payload)
        return json.dumps({"status": "no_evidence", "documents": []})

    monkeypatch.setattr(
        "src.app.agente.rag_document_search", SimpleNamespace(invoke=search)
    )
    agent = scoped_agent_class(RecordingAgent(), fallback_model=object())
    previous_tool = {
        "role": "tool",
        "name": "rag_document_search",
        "content": json.dumps(
            {
                "status": "success",
                "documents": [
                    {
                        "title": "Fixture sintética: referências",
                        "evidence": [
                            {
                                "evidence_id": "old:page:1",
                                "text": "Referências de livros.",
                            }
                        ],
                    }
                ],
            }
        ),
    }
    messages = [
        {
            "role": "user",
            "content": "Como apresentar referências de livros segundo a ABNT?",
        },
        previous_tool,
        {"role": "assistant", "content": "Consulte as referências de livros."},
        {"role": "user", "content": QUESTION},
    ]
    result = agent.invoke({"messages": messages})
    return calls, result


def test_f12_regression_previous_conversation_remains_context(
    recovery_after_previous_turn,
):
    calls, result = recovery_after_previous_turn
    assert len(calls) == 1
    assert (
        result["messages"][0]["content"]
        == "Como apresentar referências de livros segundo a ABNT?"
    )
    assert extract_agent_result(result).evidences == []


def test_f12_contract_new_question_triggers_current_retrieval(
    recovery_after_previous_turn,
):
    calls, _ = recovery_after_previous_turn
    assert calls == [
        {
            "question": QUESTION + " Contexto da pergunta anterior: "
            "Como apresentar referências de livros segundo a ABNT?"
        }
    ]


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_f13_regression_public_client_history_reaches_agent(role):
    message = {"role": role, "content": "Histórico sintético fornecido pelo cliente."}
    request = AgentChatRequest(message=QUESTION, history=[message])
    inner = RecordingAgent()
    AgentService(inner).chat(request)
    assert inner.payload["messages"][0] == message


@pytest.mark.parametrize("role", ["system", "tool"])
def test_f13_contract_public_history_rejects_privileged_roles(role):
    with pytest.raises(ValidationError):
        AgentChatRequest(
            message=QUESTION,
            history=[{"role": role, "content": "Histórico sintético."}],
        )
