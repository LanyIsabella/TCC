"""Adapta resultados V2 para o grounding e a proveniência existentes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from src.app.evidence import (
    AgentAnswer,
    AgentResult,
    EvidenceTurn,
    extract_agent_result,
    finalize_grounding,
)
from src.app.grounding import (
    INSUFFICIENT_EVIDENCE,
    PARTIAL_LIMITATION,
)

from .schemas import (
    LimitationCode,
    PlannerDecision,
    SynthesisResponse,
    ToolExecution,
    is_structured_clarification,
)

_LIMITATION_MESSAGES = {
    LimitationCode.EVIDENCE_UNAVAILABLE: INSUFFICIENT_EVIDENCE,
    LimitationCode.PARTIAL_SUPPORT: PARTIAL_LIMITATION,
    LimitationCode.SYNTHESIS_FAILED: (
        "A síntese estruturada não pôde ser validada com segurança."
    ),
}


def _limitation_messages(values: list[object]) -> tuple[str, ...]:
    messages = []
    for value in values:
        try:
            code = LimitationCode(value)
        except (TypeError, ValueError):
            continue
        message = _LIMITATION_MESSAGES[code]
        if message not in messages:
            messages.append(message)
    return tuple(messages)


def _turn(conversation_id: str, turn_id: str, question: str) -> EvidenceTurn:
    return EvidenceTurn(
        turn_id,
        question,
        hashlib.sha256(question.encode("utf-8")).hexdigest(),
        conversation_id,
    )


def conversational_result(
    *,
    conversation_id: str,
    turn_id: str,
    question: str,
    answer: str,
    planner: PlannerDecision,
) -> AgentResult:
    turn = _turn(conversation_id, turn_id, question)
    if planner.needs_clarification:
        if planner.clarification_questions:
            expected = "\n".join(planner.clarification_questions)
            clarification_source = (
                "structured"
                if answer == expected
                and all(
                    is_structured_clarification(question)
                    for question in planner.clarification_questions
                )
                else "untrusted"
            )
        elif planner.reply and is_structured_clarification(planner.reply):
            clarification_source = (
                "legacy_structured" if answer == planner.reply else "untrusted"
            )
        else:
            clarification_source = "untrusted"
    else:
        clarification_source = None
    result = {
        "messages": [
            {"role": "user", "content": question, "id": turn.id},
            {"role": "assistant", "content": answer},
        ],
        "_turn": turn,
        "_conversation": {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "intent": planner.intent,
            "completion_type": "clarification_requested"
            if planner.needs_clarification
            else "conversational",
            "clarification_source": clarification_source,
        },
    }
    return extract_agent_result(result, question=question)


def grounded_result(
    *,
    conversation_id: str,
    turn_id: str,
    question: str,
    synthesis: SynthesisResponse,
    execution: ToolExecution,
    planner: PlannerDecision,
) -> AgentResult:
    turn = _turn(conversation_id, turn_id, question)
    call_id = f"v2-{turn_id}"
    result = {
        "messages": [
            {"role": "user", "content": question, "id": turn.id},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "name": execution.tool_name,
                        "args": {"question": execution.query},
                    }
                ],
            },
            {
                "role": "tool",
                "name": execution.tool_name,
                "tool_call_id": call_id,
                "content": json.dumps(execution.raw_result, ensure_ascii=False),
            },
            {"role": "assistant", "content": synthesis.answer},
        ],
        "_turn": turn,
        "_conversation": {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "intent": planner.intent,
        },
        "structured_response": AgentAnswer(
            answer=synthesis.answer,
            evidence_ids=list(synthesis.evidence_ids),
        ),
    }
    finalized = finalize_grounding(result)
    extracted = extract_agent_result(finalized, question=question)
    if synthesis.limitations:
        extracted = replace(
            extracted,
            limitations=tuple(
                dict.fromkeys(
                    (
                        *extracted.limitations,
                        *_limitation_messages(synthesis.limitations),
                    )
                )
            ),
        )
    return extracted


def failed_normative_result(
    *,
    conversation_id: str,
    turn_id: str,
    question: str,
    execution: ToolExecution,
    planner: PlannerDecision,
    error_code: LimitationCode,
) -> AgentResult:
    result = grounded_result(
        conversation_id=conversation_id,
        turn_id=turn_id,
        question=question,
        synthesis=SynthesisResponse(
            answer=INSUFFICIENT_EVIDENCE,
            evidence_ids=[],
            limitations=[error_code],
        ),
        execution=execution,
        planner=planner,
    )
    return replace(result, errors=(error_code.value,))


__all__ = [
    "conversational_result",
    "failed_normative_result",
    "grounded_result",
]
