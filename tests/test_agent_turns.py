"""Associação de evidência à pergunta e à execução atual, sem modelo/rede."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.app.evidence import _collect_evidences, _tool_payloads, begin_turn, bind_turn


def tool(text="Trecho atual", *, evidence_id="page:1", name="rag_document_search"):
    return {
        "role": "tool",
        "name": name,
        "content": json.dumps(
            {
                "status": "success",
                "documents": [
                    {
                        "evidence": [
                            {
                                "evidence_id": evidence_id,
                                "text": text,
                            }
                        ]
                    }
                ],
            }
        ),
    }


def test_history_is_context_but_not_current_documentary_evidence():
    result = {
        "messages": [
            {"role": "user", "content": "Pergunta anterior"},
            tool("Texto antigo"),
            {"role": "assistant", "content": "Resposta anterior"},
            {"role": "user", "content": "Pergunta atual"},
        ]
    }
    assert _tool_payloads(result) == []
    assert _collect_evidences(result) == {}


def test_same_page_identifier_gets_current_content_and_not_old_content():
    result = {
        "messages": [
            {"role": "user", "content": "Anterior"},
            tool("Texto antigo"),
            {"role": "user", "content": "Atual"},
            tool("Texto atual"),
        ]
    }
    assert _collect_evidences(result)["page:1"]["text"] == "Texto atual"


def test_other_tool_and_failed_payload_cannot_supply_current_evidence():
    failed = tool()
    failed["content"] = json.dumps(
        {
            "status": "error",
            "documents": [
                {
                    "evidence": [{"evidence_id": "forged", "text": "Texto"}],
                }
            ],
        }
    )
    result = {
        "messages": [
            {"role": "user", "content": "Atual"},
            tool(name="AgentAnswer"),
            failed,
        ]
    }
    assert _collect_evidences(result) == {}


def test_langchain_tool_call_identifier_must_match_its_execution():
    result = {
        "messages": [
            HumanMessage(content="Atual"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "new-call",
                        "name": "rag_document_search",
                        "args": {"question": "Atual"},
                    }
                ],
            ),
            ToolMessage(
                content=tool()["content"],
                name="rag_document_search",
                tool_call_id="old-call",
            ),
        ]
    }
    assert _collect_evidences(result) == {}
    result["messages"][-1] = ToolMessage(
        content=tool()["content"],
        name="rag_document_search",
        tool_call_id="new-call",
    )
    assert "page:1" in _collect_evidences(result)


def test_scoped_agent_binds_turn_and_preserves_question(monkeypatch):
    from src.app.agente import ScopedAgent

    class Inner:
        def invoke(self, payload):
            event = {**tool(), "tool_call_id": "call"}
            call = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call",
                        "name": "rag_document_search",
                        "args": {"question": "Como citar segundo ABNT?"},
                    }
                ],
            }
            return {
                "messages": [
                    *payload["messages"],
                    call,
                    event,
                    {"role": "assistant", "content": "Trecho atual"},
                ]
            }

    agent = ScopedAgent(Inner())
    first = agent.invoke(
        {"messages": [{"role": "user", "content": "Como citar segundo ABNT?"}]}
    )
    second = agent.invoke(
        {
            "messages": [
                *first["messages"],
                {"role": "user", "content": "Como citar segundo ABNT?"},
            ]
        }
    )
    assert first["_turn"].id != second["_turn"].id
    assert (
        first["_turn"].question
        == second["_turn"].question
        == "Como citar segundo ABNT?"
    )
    assert first["_turn"].question_sha256 == second["_turn"].question_sha256
    assert _collect_evidences(second)["page:1"]["turn_id"] == second["_turn"].id


def test_bound_turn_cannot_reuse_evidence_after_another_question_is_appended():
    payload, turn = begin_turn(
        {"messages": [{"role": "user", "content": "Margens ABNT?"}]}
    )
    value = bind_turn(
        {
            "messages": [
                *payload["messages"],
                tool(),
                {"role": "user", "content": "Qual a fonte do TCC?"},
            ]
        },
        payload,
        turn,
    )
    assert _collect_evidences(value) == {}


def test_bound_turn_does_not_trust_an_unpaired_tool_result():
    payload, turn = begin_turn({"messages": [HumanMessage(content="Margens ABNT?")]})
    value = bind_turn({"messages": [*payload["messages"], tool()]}, payload, turn)
    assert _collect_evidences(value) == {}


def test_unbound_executor_result_does_not_relabel_old_tools_as_current():
    payload, turn = begin_turn(
        {"messages": [{"role": "user", "content": "Margens ABNT?"}]}
    )
    value = bind_turn(
        {
            "messages": [
                tool("Texto antigo"),
                {"role": "assistant", "content": "A margem deve medir 7 cm."},
            ]
        },
        payload,
        turn,
    )
    assert _collect_evidences(value) == {}
    assert value["messages"][0]["id"] == turn.id


def test_malformed_rag_payloads_do_not_become_evidence():
    payloads = [
        "invalid",
        "[]",
        '{"status":"success","documents":{}}',
        {
            "status": "success",
            "documents": [
                None,
                {
                    "evidence": [
                        None,
                        {"evidence_id": "", "text": "texto"},
                        {"evidence_id": "id", "text": " "},
                    ]
                },
            ],
        },
    ]
    for payload in payloads:
        value = {
            "messages": [
                {"role": "tool", "name": "rag_document_search", "content": payload}
            ]
        }
        assert _collect_evidences(value) == {}


def test_tool_cannot_override_server_turn_and_execution_metadata():
    payload, turn = begin_turn(
        {"messages": [HumanMessage(content="Qual a margem ABNT?")]}
    )
    raw = json.loads(tool()["content"])
    raw["_execution"] = {"turn_id": "old"}
    raw["documents"][0]["evidence"][0]["turn_id"] = "forged"
    value = bind_turn(
        {
            "messages": [
                *payload["messages"],
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "current",
                            "name": "rag_document_search",
                            "args": {"question": "consulta atual"},
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps(raw),
                    name="rag_document_search",
                    tool_call_id="current",
                ),
            ]
        },
        payload,
        turn,
    )
    record = _collect_evidences(value)["page:1"]
    assert record["turn_id"] == turn.id
    assert record["tool_call_id"] == "current"
    assert record["query"] == "consulta atual"
