import json

from src.api.schemas.agent import AgentChatRequest
from src.api.services.agent_service import AgentService
from src.app.evidence import EvidenceTurn
from src.app.grounding import PARTIAL_LIMITATION

QUESTION = "Qual a margem direita segundo a ABNT?"
RULE = "A margem direita mede 2 cm."


def _result(*, omitted: bool = False, answer: str = RULE) -> dict:
    turn = EvidenceTurn("turn-current", QUESTION, "q-hash")
    document = {
        "document_id": 8,
        "rag_document_id": 99,
        "title": "ABNT NBR 14724",
        "standard_id": "abnt_nbr_14724",
        "version": "2024",
        "issuer": "ABNT",
        "quality_score": 99,
        "source": "page_window",
        "evidence": [
            {
                "evidence_id": "document:99:page:14",
                "page_number": 14,
                "section": "Margens",
                "text": RULE,
                "matched_text": RULE,
            }
        ],
    }
    if omitted:
        document["omitted_content"] = {"characters": 42, "pages": [14]}
    return {
        "_turn": turn,
        "messages": [
            {"role": "user", "content": QUESTION, "id": turn.id},
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
            {
                "role": "tool",
                "name": "rag_document_search",
                "tool_call_id": "call-current",
                "content": json.dumps(
                    {
                        "status": "success",
                        "evidence_found": True,
                        "documents": [document],
                    }
                ),
            },
            {"role": "assistant", "content": answer},
        ],
        "structured_response": {
            "answer": answer,
            "evidence_ids": ["document:99:page:14"],
        },
    }


class Executor:
    def __init__(self, result: dict):
        self.result = result

    def invoke(self, _payload):
        return self.result


def test_api_exposes_public_evidence_and_grounding_metadata() -> None:
    response = AgentService(Executor(_result(omitted=True))).chat(
        AgentChatRequest(message=QUESTION)
    )

    assert response.grounding_status == "partial"
    assert PARTIAL_LIMITATION in response.limitations
    evidence = response.evidences[0]
    assert evidence.evidence_id == "document:99:page:14"
    assert evidence.document_id == 8
    assert evidence.standard_id == "abnt_nbr_14724"
    assert evidence.version == "2024"
    assert evidence.page_number == 14
    assert evidence.text == RULE
    assert evidence.turn_id == "turn-current"
    assert evidence.tool_call_id == "call-current"
    assert evidence.query == QUESTION
    assert evidence.omitted_content == {"characters": 42, "pages": [14]}
    public = evidence.model_dump()
    assert "rag_document_id" not in public
    assert "source" not in public
    assert "quality_score" not in public


def test_api_exposes_unsupported_without_evidence() -> None:
    result = _result(answer="A margem direita mede 7 cm.")
    result["messages"][2]["content"] = json.dumps(
        {"status": "no_evidence", "evidence_found": False, "documents": []}
    )
    response = AgentService(Executor(result)).chat(AgentChatRequest(message=QUESTION))

    assert response.grounding_status == "unsupported"
    assert response.evidences == []
    assert response.limitations


def test_api_rejects_free_text_after_retrieval_without_structured_selection() -> None:
    result = _result()
    result.pop("structured_response")

    response = AgentService(Executor(result)).chat(
        AgentChatRequest(message=QUESTION)
    )

    assert response.grounding_status == "unsupported"
    assert response.evidences == []
    assert response.answer.startswith("Não foi possível fundamentar")


def test_api_preserves_multiple_page_evidences_without_internal_fields() -> None:
    result = _result()
    question = "Quais são as margens segundo a ABNT?"
    result["_turn"] = EvidenceTurn("turn-current", question, "q-hash")
    result["messages"][0]["content"] = question
    document = json.loads(result["messages"][2]["content"])["documents"][0]
    document["evidence"].append(
        {
            "evidence_id": "document:99:page:15",
            "page_number": 15,
            "section": "Recuo",
            "text": "A margem esquerda mede 3 cm.",
        }
    )
    result["messages"][2]["content"] = json.dumps(
        {"status": "success", "evidence_found": True, "documents": [document]}
    )
    result["structured_response"]["evidence_ids"].append("document:99:page:15")
    result["structured_response"]["answer"] = (
        "A margem direita mede 2 cm. A margem esquerda mede 3 cm."
    )
    result["messages"][-1]["content"] = result["structured_response"]["answer"]
    response = AgentService(Executor(result)).chat(AgentChatRequest(message=question))

    assert [item.page_number for item in response.evidences] == [14, 15]
    assert all(
        "rag_document_id" not in item.model_dump() for item in response.evidences
    )
