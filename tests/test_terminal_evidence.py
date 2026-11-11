import json
import sys
from pathlib import Path

from src.app.evidence import AgentResult, EvidenceTurn

sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "terminal"))

from src.terminal.main import ChatSession, format_grounding_result  # noqa: E402

QUESTION = "Qual a margem direita segundo a ABNT?"


def _result() -> dict:
    turn = EvidenceTurn("turn-terminal", QUESTION, "question-hash")
    return {
        "_turn": turn,
        "messages": [
            {"role": "user", "content": QUESTION, "id": turn.id},
            {
                "role": "tool",
                "name": "rag_document_search",
                "tool_call_id": "call-terminal",
                "content": json.dumps({"status": "success", "documents": []}),
            },
            {"role": "assistant", "content": "A margem direita mede 7 cm."},
        ],
        "structured_response": {
            "answer": "A margem direita mede 7 cm.",
            "evidence_ids": [],
        },
    }


def test_terminal_keeps_validated_evidence_and_status() -> None:
    class Executor:
        def invoke(self, _payload):
            return _result()

    session = ChatSession(Executor())
    assert session.ask(QUESTION)
    assert session.last_result.grounding_status == "unsupported"
    assert session.last_result.evidences == []
    rendered = format_grounding_result(session.last_result)
    assert "não fundamentada" in rendered.lower()


def test_terminal_labels_partial_answers_without_claiming_complete_support() -> None:
    result = AgentResult(
        "Resposta parcial.",
        [
            {
                "evidence_id": "document:99:page:14",
                "document_id": 8,
                "standard_id": "abnt_nbr_14724",
                "version": "2024",
                "page_number": 14,
                "text": "Trecho original.",
                "turn_id": "turn-terminal",
                "tool_call_id": "call-terminal",
            }
        ],
        grounding_status="partial",
        limitations=("Há conteúdo omitido.",),
    )

    rendered = format_grounding_result(result)

    assert "parcial" in rendered.lower()
    assert "Trecho original." in rendered
    assert "fundamentação completa" not in rendered.lower()
    assert "turn-terminal" in rendered
    assert "call-terminal" in rendered
    assert "rag_document_id" not in rendered
    assert "quality_score" not in rendered
