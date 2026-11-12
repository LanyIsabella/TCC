import pytest
from pydantic import ValidationError
from src.app.agente_v2.orchestrator import AgentV2
from src.app.agente_v2.planner import Planner
from src.app.agente_v2.schemas import (
    LimitationCode,
    PlannerDecision,
    SynthesisResponse,
)
from src.app.agente_v2.synthesis import SynthesisFailure
from src.app.conversation import ConversationIntent, ConversationStore
from src.app.grounding import INSUFFICIENT_EVIDENCE, PARTIAL_LIMITATION
from src.app.scope_guard import GREETING_MESSAGE

SOURCE = "A citação direta longa deve observar a norma aplicável."


class FakePlanner:
    def __init__(self, decision: PlannerDecision):
        self.decision = decision
        self.calls = []

    def plan(self, question, history):
        self.calls.append((question, history))
        return self.decision


class FakeSynthesizer:
    def __init__(self, response: SynthesisResponse):
        self.response = response
        self.calls = []

    def synthesize(self, question, history, retrieval):
        self.calls.append((question, history, retrieval))
        return self.response


class FakeTools:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, name, arguments, *, conversation_id, turn_id):
        self.calls.append((name, arguments, conversation_id, turn_id))
        return self.payload


class FakeStructuredModel:
    def __init__(self, decision: PlannerDecision):
        self.decision = decision
        self.calls = []

    def with_structured_output(self, *_args, **_kwargs):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return {"parsed": self.decision}


def rag_payload():
    return {
        "status": "success",
        "evidence_found": True,
        "documents": [
            {
                "document_id": 10520,
                "title": "ABNT NBR 10520",
                "version": "2023",
                "evidence": [{"evidence_id": "e1", "text": SOURCE}],
            }
        ],
    }


def test_planner_uses_context_for_ambiguous_follow_up() -> None:
    model = FakeStructuredModel(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    planner = Planner(model)

    decision = planner.plan(
        "Como formatar isso?",
        [{"role": "user", "content": "Tenho uma citação direta longa."}],
    )

    assert decision.intent == ConversationIntent.NORMATIVE_QUERY
    assert decision.needs_retrieval is True
    assert model.calls


def test_planner_keeps_ambiguous_without_relevant_history() -> None:
    model = FakeStructuredModel(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    planner = Planner(model)

    decision = planner.plan("Como formatar isso?", [])

    assert decision.intent == ConversationIntent.AMBIGUOUS
    assert decision.needs_clarification is True
    assert decision.clarification_questions
    assert model.calls == []


def test_contextual_follow_up_reaches_normative_retrieval() -> None:
    model = FakeStructuredModel(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=Planner(model),
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
        ),
        tools=tools,
    )

    result = agent.invoke(
        {
            "messages": [
                {"role": "user", "content": "Tenho uma citação direta longa."},
                {"role": "assistant", "content": "Entendi."},
                {"role": "user", "content": "Como formatar isso?"},
            ]
        }
    )

    assert tools.calls
    assert result["intent"] == ConversationIntent.NORMATIVE_QUERY
    assert result["grounding_status"] == "supported"


def test_conversational_turn_does_not_call_rag() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.CONVERSATIONAL,
            needs_clarification=False,
            needs_retrieval=False,
            reply="Olá! Posso ajudar com seu TCC.",
        )
    )
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=tools,
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Olá"}]})

    assert result["answer"] == "Olá! Posso ajudar com seu TCC."
    assert result["grounding_status"] == "conversational"
    assert tools.calls == []


def test_conversational_plan_without_reply_uses_greeting() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.CONVERSATIONAL,
            needs_clarification=False,
            needs_retrieval=False,
        )
    )
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=tools,
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Olá"}]})

    assert result["answer"] == GREETING_MESSAGE
    assert result["grounding_status"] == "conversational"
    assert tools.calls == []


def test_normative_turn_retrieves_and_publishes_validated_evidence() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    tools = FakeTools(rag_payload())
    synthesizer = FakeSynthesizer(
        SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
    )
    agent = AgentV2(planner=planner, synthesizer=synthesizer, tools=tools)

    result = agent.invoke(
        {
            "conversation_id": "v2-conversation",
            "messages": [{"role": "user", "content": "Como citar?"}],
        }
    )

    assert result["grounding_status"] == "supported"
    assert [item["evidence_id"] for item in result["evidences"]] == ["e1"]
    assert result["published_evidence_ids"] == ["e1"]
    assert tools.calls[0][0] == "rag_document_search"
    assert synthesizer.calls


def test_normative_turn_accepts_literal_evidence_after_page_header() -> None:
    answer = (
        "O autor deve ser indicado pelo último sobrenome, em letras maiúsculas, "
        "seguido do prenome e outros sobrenomes, abreviados ou não, conforme "
        "consta no documento."
    )
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    tools = FakeTools(
        {
            "status": "success",
            "evidence_found": True,
            "documents": [
                {
                    "rag_document_id": 32,
                    "standard_id": "abnt_nbr_6023",
                    "evidence": [
                        {
                            "evidence_id": "document:32:page:40",
                            "page_number": 40,
                            "text": (
                                "ABNT NBR 6023:2025\n\n8.1.1 Pessoa física\n\n"
                                + answer
                            ),
                        }
                    ],
                }
            ],
        }
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=answer, evidence_ids=["document:32:page:40"])
        ),
        tools=tools,
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Como indicar autores nas referências?",
                }
            ]
        }
    )

    assert result["grounding_status"] == "supported"
    assert result["published_evidence_ids"] == ["document:32:page:40"]


def test_normative_turn_without_evidence_fails_closed() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    tools = FakeTools(
        {"status": "success", "evidence_found": False, "documents": []}
    )
    synthesizer = FakeSynthesizer(SynthesisResponse(answer="nunca"))
    agent = AgentV2(planner=planner, synthesizer=synthesizer, tools=tools)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como citar?"}]}
    )

    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["grounding_status"] == "unsupported"
    assert result["completion_type"] == "unsupported"
    assert result["available_evidence_ids"] == []
    assert result["published_evidence_ids"] == []
    assert synthesizer.calls == []


def test_retrieval_flag_routes_unknown_intent_to_rag() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.UNKNOWN,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    tools = FakeTools(rag_payload())
    synthesizer = FakeSynthesizer(
        SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
    )
    agent = AgentV2(planner=planner, synthesizer=synthesizer, tools=tools)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual é a regra?"}]}
    )

    assert tools.calls
    assert result["intent"] == ConversationIntent.NORMATIVE_QUERY
    assert result["grounding_status"] == "supported"


def test_normative_answer_misclassified_as_conversational_fails_closed() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.CONVERSATIONAL,
            needs_clarification=False,
            needs_retrieval=False,
            reply="A margem deve medir 2 cm.",
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Olá"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["evidences"] == []


@pytest.mark.parametrize(
    "intent, question",
    [
        (ConversationIntent.CONVERSATIONAL, "Olá"),
        (ConversationIntent.AMBIGUOUS, "Como formatar?"),
        (ConversationIntent.ACTION_REQUEST, "Formate minha margem"),
    ],
)
def test_conversational_prefix_cannot_bypass_normative_grounding(
    intent: ConversationIntent, question: str
) -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=intent,
            needs_clarification=intent == ConversationIntent.AMBIGUOUS,
            needs_retrieval=False,
            reply="Posso ajudar. A margem deve medir 9 cm.",
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": question}]})

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["evidences"] == []


def test_conversational_prefix_with_unlisted_normative_claim_fails_closed() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.CONVERSATIONAL,
            needs_clarification=False,
            needs_retrieval=False,
            reply="Posso ajudar. As citações diretas longas exigem recuo.",
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Olá"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["evidences"] == []


def test_greeting_with_academic_capabilities_remains_conversational() -> None:
    reply = "Olá! Posso ajudar com citações e referências."
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.CONVERSATIONAL,
            needs_clarification=False,
            needs_retrieval=False,
            reply=reply,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Olá"}]})

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == reply


def test_clarification_with_normative_preface_fails_closed() -> None:
    reply = "As citações diretas longas exigem recuo. Qual trecho você quer formatar?"
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            needs_retrieval=False,
            reply=reply,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar?"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["evidences"] == []


def test_structured_clarification_with_academic_terms_remains_conversational() -> None:
    reply = "Qual trecho de citações ou referências você quer formatar?"
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            needs_retrieval=False,
            clarification_questions=[reply],
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar?"}]}
    )

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == reply


def test_multiple_structured_clarification_questions_remain_conversational() -> None:
    questions = [
        "Você quer formatar citações ou referências?",
        "Qual trecho do trabalho deseja analisar?",
    ]
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            needs_retrieval=False,
            clarification_questions=questions,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar?"}]}
    )

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == "\n".join(questions)


def test_clarification_contract_rejects_normative_preface() -> None:
    with pytest.raises(ValidationError):
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[
                (
                    "As citações diretas longas exigem recuo. "
                    "Qual trecho você quer formatar?"
                )
            ],
        )


def test_clarification_contract_rejects_normative_semicolon_clause() -> None:
    with pytest.raises(ValidationError):
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[
                (
                    "As citações diretas longas exigem recuo; "
                    "qual trecho você quer formatar?"
                )
            ],
        )


def test_malformed_clarification_cannot_reach_public_agent_output() -> None:
    malformed = (
        "As citações diretas longas exigem recuo; "
        "qual trecho você quer formatar?"
    )
    planner = FakePlanner(
        PlannerDecision.model_construct(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            needs_retrieval=False,
            clarification_questions=[malformed],
            reply=None,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar?"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert malformed not in result["answer"]


def test_normative_answer_misclassified_as_ambiguous_fails_closed() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            needs_retrieval=False,
            reply="A margem deve medir 2 cm.",
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar?"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["evidences"] == []


def test_legitimate_clarification_remains_conversational() -> None:
    reply = "Qual elemento acadêmico você deseja formatar: citações ou referências?"
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            needs_retrieval=False,
            reply=reply,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar?"}]}
    )

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == reply


def test_invalid_selected_evidence_fails_closed() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer="Regra não comprovada.", evidence_ids=["fake"])
        ),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual é a regra?"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["evidences"] == []


def test_blocked_normative_answer_does_not_leak_through_limitations() -> None:
    invalid = "A margem deve medir 2 cm."
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse.model_construct(answer=invalid, limitations=[invalid])
        ),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual é a margem?"}]}
    )

    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert invalid not in result["limitations"]
    assert invalid not in result["errors"]


def test_synthesis_limitation_contract_rejects_free_text() -> None:
    with pytest.raises(ValidationError):
        SynthesisResponse(
            answer=SOURCE,
            limitations=["A margem deve medir 2 cm."],
        )


def test_controlled_limitation_is_preserved_without_free_text() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer=SOURCE,
                evidence_ids=["e1"],
                limitations=[LimitationCode.PARTIAL_SUPPORT],
            )
        ),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como citar?"}]}
    )

    assert result["grounding_status"] == "supported"
    assert PARTIAL_LIMITATION in result["limitations"]


def test_synthesis_error_publishes_only_controlled_code() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_clarification=False,
            needs_retrieval=True,
        )
    )

    class FailingSynthesizer:
        def synthesize(self, question, history, retrieval):
            raise SynthesisFailure("A margem deve medir 2 cm.")

    agent = AgentV2(
        planner=planner,
        synthesizer=FailingSynthesizer(),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como citar?"}]}
    )

    assert result["errors"] == [LimitationCode.SYNTHESIS_FAILED.value]
    assert all("margem" not in item.lower() for item in result["limitations"])


def test_conversation_store_isolates_v2_contexts() -> None:
    store = ConversationStore()
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.CONVERSATIONAL,
            needs_clarification=False,
            needs_retrieval=False,
            reply="Contexto recebido.",
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
        store=store,
    )

    first = agent.invoke(
        {"conversation_id": "first", "messages": [{"role": "user", "content": "A"}]}
    )
    second = agent.invoke(
        {"conversation_id": "second", "messages": [{"role": "user", "content": "B"}]}
    )

    assert first["conversation_id"] == "first"
    assert second["conversation_id"] == "second"
    assert store.history("first") != store.history("second")
