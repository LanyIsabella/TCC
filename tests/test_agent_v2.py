from src.app.agente_v2.orchestrator import AgentV2
from src.app.agente_v2.schemas import PlannerDecision, SynthesisResponse
from src.app.conversation import ConversationIntent, ConversationStore
from src.app.grounding import INSUFFICIENT_EVIDENCE

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


def test_legitimate_clarification_remains_conversational() -> None:
    reply = "Qual elemento você deseja formatar?"
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
