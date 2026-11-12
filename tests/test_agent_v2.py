import pytest
from pydantic import ValidationError
from src.app.agente_v2.orchestrator import AgentV2
from src.app.agente_v2.planner import Planner
from src.app.agente_v2.schemas import (
    ClarificationResolution,
    LimitationCode,
    PlannerDecision,
    SynthesisResponse,
)
from src.app.agente_v2.synthesis import SynthesisFailure, Synthesizer
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


class FakeSynthesisModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def with_structured_output(self, *_args, **_kwargs):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeGroundingVerifierModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.response


class FakeClarificationResolutionModel:
    def with_structured_output(self, *_args, **_kwargs):
        return self

    def invoke(self, _messages):
        return {
            "parsed": {
                "resolved_question": (
                    "Quais são os elementos necessários para elaborar referências?"
                )
            }
        }


class ClarificationSequencePlanner:
    def __init__(self):
        self.calls = []

    def resolve_clarification(self, answer, original_question, _prompt, _history):
        return Planner._deterministic_clarification_query(
            answer, original_question
        )

    def plan(self, question, history):
        self.calls.append((question, history))
        if len(self.calls) == 1:
            return PlannerDecision(
                intent=ConversationIntent.AMBIGUOUS,
                needs_clarification=True,
                clarification_questions=[
                    "Você deseja orientação sobre qual aspecto das referências?"
                ],
            )
        if question in {"Autoria", "Elementos", "Formatação", "Citação direta longa"}:
            return PlannerDecision(
                intent=ConversationIntent.CONVERSATIONAL,
                reply=GREETING_MESSAGE,
            )
        return PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )


def references_payload():
    source = "A referência deve ser apresentada conforme os elementos necessários."
    return {
        "status": "success",
        "evidence_found": True,
        "documents": [
            {
                "document_id": 6023,
                "title": "ABNT NBR 6023",
                "standard_id": "abnt_nbr_6023",
                "evidence": [{"evidence_id": "ref-1", "text": source}],
            }
        ],
    }, source


def test_clarification_resolution_preserves_the_answered_aspect():
    planner = Planner(FakeClarificationResolutionModel())

    resolved = planner.resolve_clarification(
        "Autoria",
        "Como formatar referências?",
        "Você deseja orientação sobre qual aspecto?",
        [],
    )

    assert resolved is not None
    assert "autor" in resolved.casefold()
    assert "referências" in resolved.casefold()


@pytest.mark.parametrize(
    ("answer", "original_question", "expected"),
    [
        ("Elementos", "Como formatar referências?", "elementos"),
        ("Formatação", "Como formatar referências?", "formatação"),
        ("Citação direta longa", "Qual é o recuo?", "recuo"),
        ("Outro assunto", "Como formatar referências?", None),
    ],
)
def test_deterministic_clarification_queries_cover_known_aspects(
    answer, original_question, expected
):
    resolved = Planner._deterministic_clarification_query(answer, original_question)

    if expected is None:
        assert resolved is None
    else:
        assert expected in resolved.casefold()


def test_structured_clarification_falls_back_when_model_loses_the_aspect():
    planner = Planner(FakeClarificationResolutionModel())

    resolved = planner.resolve_clarification(
        "Outro aspecto",
        "Como organizar referências?",
        "Você deseja orientação sobre qual aspecto?",
        [],
    )

    assert resolved == "Como organizar referências — aspecto: Outro aspecto"


def test_structured_contract_parsers_accept_raw_and_typed_values():
    planner_decision = PlannerDecision(intent=ConversationIntent.NORMATIVE_QUERY)
    clarification = ClarificationResolution(
        resolved_question="Como indicar autores nas referências?"
    )

    assert PlannerDecision.from_llm_value(planner_decision) is planner_decision
    assert PlannerDecision.from_llm_value({"intent": "normative_query"})
    assert PlannerDecision.from_llm_value({"parsed": {}}) is None
    assert ClarificationResolution.from_llm_value(clarification) is clarification
    assert ClarificationResolution.from_llm_value(
        {"resolved_question": clarification.resolved_question}
    )
    assert ClarificationResolution.from_llm_value([]) is None


def test_synthesizer_retries_invalid_contract_and_returns_valid_response():
    model = FakeSynthesisModel(
        [
            {"parsed": {}},
            {
                "parsed": {
                    "answer": "A regra é aplicada.",
                    "evidence_ids": ["e1"],
                    "limitations": [],
                }
            },
        ]
    )

    result = Synthesizer(model).synthesize("Qual é a regra?", [], {})

    assert result.answer == "A regra é aplicada."
    assert len(model.calls) == 2
    assert "tentativa anterior falhou" in model.calls[1][0]["content"]


def test_synthesis_parser_accepts_typed_and_wrapped_contracts():
    typed = SynthesisResponse(answer="Resposta", evidence_ids=["e1"])
    synthesizer = Synthesizer(None)

    assert synthesizer._parsed(typed) is typed
    assert synthesizer._parsed({"parsed": typed}) is typed
    assert synthesizer._parsed({"answer": "Resposta"}).answer == "Resposta"
    assert synthesizer._parsed("invalid") is None


def test_synthesis_prompt_prefers_natural_relevant_evidence():
    prompt = Synthesizer(None)._prompt(
        "Como formatar uma citação direta longa?",
        [],
        {
            "documents": [
                {
                    "standard_label": "ABNT NBR 10520",
                    "evidence": [
                        {
                            "evidence_id": "e1",
                            "direct_match": True,
                            "page_number": 16,
                            "text": "A citação direta deve observar o recuo.",
                        },
                        {
                            "evidence_id": "e2",
                            "direct_match": False,
                            "page_number": 3,
                            "text": "Trecho não pertinente.",
                        },
                    ],
                }
            ]
        },
    )

    assert "forma clara e natural" in prompt
    assert "prefira copiar literalmente" not in prompt
    assert '"evidence_id": "e1"' in prompt
    assert '"evidence_id": "e2"' not in prompt


def test_synthesis_prompt_keeps_adjacent_page_context():
    prompt = Synthesizer(None)._prompt(
        "Qual é a regra completa?",
        [],
        {
            "documents": [
                {
                    "document_id": 14724,
                    "standard_id": "abnt_nbr_14724",
                    "evidence": [
                        {
                            "evidence_id": "page-10",
                            "page_number": 10,
                            "direct_match": True,
                            "text": "A regra começa nesta página.",
                        },
                        {
                            "evidence_id": "page-11",
                            "page_number": 11,
                            "direct_match": False,
                            "text": "A regra continua com uma exceção.",
                        },
                    ],
                }
            ]
        },
    )

    assert "A regra começa nesta página." in prompt
    assert "A regra continua com uma exceção." in prompt


def test_planner_prompt_requests_specific_clarification_for_broad_normative_questions():
    prompt = Planner(None)._prompt("Como formatar referências?", [])

    assert "autoria" in prompt
    assert "esclarecimento específico" in prompt


def test_v2_uses_semantic_verifier_only_after_deterministic_support_fails():
    verifier_model = FakeGroundingVerifierModel(
        '{"claims":[{"index":0,"supported":true,"evidence_id":"e1",'
        '"quote":"A margem direita deve medir 2 cm."}]}'
    )
    agent = AgentV2(
        model=verifier_model,
        planner=FakePlanner(
            PlannerDecision(
                intent=ConversationIntent.NORMATIVE_QUERY,
                needs_retrieval=True,
            )
        ),
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer="É obrigatório deixar dois centímetros na margem direita.",
                evidence_ids=["e1"],
            )
        ),
        tools=FakeTools(
            {
                "status": "success",
                "evidence_found": True,
                "documents": [
                    {
                        "document_id": 1,
                        "evidence": [
                            {
                                "evidence_id": "e1",
                                "text": "A margem direita deve medir 2 cm.",
                            }
                        ],
                    }
                ],
            }
        ),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual a margem direita?"}]}
    )

    assert result["grounding_status"] == "supported"
    assert result["published_evidence_ids"] == ["e1"]
    assert len(verifier_model.calls) == 1


def test_synthesis_recovers_inline_evidence_ids_when_structured_list_is_empty():
    parsed = Synthesizer(None)._parsed(
        {
            "answer": "A regra é aplicada. evidence_id: document:32:page:11",
            "evidence_ids": [],
            "limitations": [],
        }
    )

    assert parsed is not None
    assert parsed.answer == "A regra é aplicada."
    assert parsed.evidence_ids == ["document:32:page:11"]


def test_inline_evidence_metadata_is_removed_before_grounding():
    parsed = Synthesizer(None)._parsed(
        {
            "answer": "A margem direita deve medir 2 cm. evidence_id: e1",
            "evidence_ids": [],
            "limitations": [],
        }
    )
    assert parsed is not None
    agent = AgentV2(
        planner=FakePlanner(
            PlannerDecision(
                intent=ConversationIntent.NORMATIVE_QUERY,
                needs_retrieval=True,
            )
        ),
        synthesizer=FakeSynthesizer(parsed),
        tools=FakeTools(
            {
                "status": "success",
                "evidence_found": True,
                "documents": [
                    {
                        "document_id": 1,
                        "evidence": [
                            {
                                "evidence_id": "e1",
                                "text": "A margem direita deve medir 2 cm.",
                            }
                        ],
                    }
                ],
            }
        ),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual a margem direita?"}]}
    )

    assert result["grounding_status"] == "supported"
    assert result["published_evidence_ids"] == ["e1"]
    assert "evidence_id" not in result["answer"]


def test_safe_decision_normalizes_ambiguous_and_unknown_contracts():
    planner = Planner(None)
    fallback = PlannerDecision(
        intent=ConversationIntent.AMBIGUOUS,
        clarification_questions=["Qual aspecto você deseja consultar?"],
    )
    ambiguous = PlannerDecision(
        intent=ConversationIntent.AMBIGUOUS,
        reply="Qual aspecto você deseja consultar?",
    )

    normalized = planner._safe_decision(ambiguous, fallback)
    assert normalized.needs_clarification is True
    assert normalized.clarification_questions == [
        "Qual aspecto você deseja consultar?"
    ]
    assert normalized.reply is None

    unknown = PlannerDecision(intent=ConversationIntent.UNKNOWN)
    normative_fallback = PlannerDecision(
        intent=ConversationIntent.NORMATIVE_QUERY,
        needs_retrieval=True,
    )
    assert planner._safe_decision(unknown, normative_fallback).needs_retrieval is True


def test_safe_decision_uses_default_clarification_when_no_question_exists():
    planner = Planner(None)
    decision = PlannerDecision(intent=ConversationIntent.AMBIGUOUS)

    normalized = planner._safe_decision(
        decision, PlannerDecision(intent=ConversationIntent.UNKNOWN)
    )

    assert normalized.clarification_questions
    assert normalized.reply is None


@pytest.mark.parametrize("answer", ["Autoria", "Elementos", "Formatação"])
def test_planner_routes_short_clarification_answer_to_normative_retrieval(answer):
    model = FakeStructuredModel(
        PlannerDecision(intent=ConversationIntent.ACTION_REQUEST)
    )
    planner = Planner(model)
    history = [
        {"role": "user", "content": "Como formatar referências?"},
        {
            "role": "assistant",
            "content": "Você deseja orientação sobre autoria, elementos ou formatação?",
        },
        {"role": "user", "content": "Autoria"},
        {"role": "assistant", "content": "Resposta fundamentada sobre autoria."},
    ]

    decision = planner.plan(answer, history)

    assert decision.intent == ConversationIntent.NORMATIVE_QUERY
    assert decision.needs_retrieval is True


@pytest.mark.parametrize("answer", ["Autoria", "Elementos", "Formatação"])
def test_clarification_answer_resolves_reference_context(answer):
    planner = ClarificationSequencePlanner()
    tools = FakeTools(references_payload()[0])
    source = references_payload()[1]
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=source, evidence_ids=["ref-1"])
        ),
        tools=tools,
    )

    first = agent.invoke(
        {
            "conversation_id": "clarification-reference",
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    second = agent.invoke(
        {
            "conversation_id": "clarification-reference",
            "messages": [
                *first["messages"],
                {"role": "user", "content": answer},
            ],
        }
    )

    assert first["completion_type"] == "clarification_requested"
    assert second["answer"] != GREETING_MESSAGE
    assert second["grounding_status"] == "supported"
    assert second["published_evidence_ids"] == ["ref-1"]
    assert tools.calls[-1][1]["question"] != answer
    assert "refer" in tools.calls[-1][1]["question"].casefold()
    assert any(message["content"] == first["answer"] for message in second["messages"])


def test_clarification_answer_for_margin_retrieves_citation_context():
    planner = ClarificationSequencePlanner()
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
        ),
        tools=tools,
    )

    first = agent.invoke(
        {
            "conversation_id": "clarification-margin",
            "messages": [{"role": "user", "content": "Qual é o recuo?"}],
        }
    )
    second = agent.invoke(
        {
            "conversation_id": "clarification-margin",
            "messages": [
                *first["messages"],
                {"role": "user", "content": "Citação direta longa"},
            ],
        }
    )

    assert first["completion_type"] == "clarification_requested"
    assert second["answer"] != GREETING_MESSAGE
    assert second["grounding_status"] == "supported"
    assert "recuo" in tools.calls[-1][1]["question"].casefold()


def test_follow_up_keeps_reference_topic_after_clarification_resolution():
    planner = ClarificationSequencePlanner()
    tools = FakeTools(references_payload()[0])
    source = references_payload()[1]
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=source, evidence_ids=["ref-1"])
        ),
        tools=tools,
    )
    first = agent.invoke(
        {
            "conversation_id": "clarification-follow-up",
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    second = agent.invoke(
        {
            "conversation_id": "clarification-follow-up",
            "messages": [
                *first["messages"],
                {"role": "user", "content": "Autoria"},
            ],
        }
    )
    third = agent.invoke(
        {
            "conversation_id": "clarification-follow-up",
            "messages": [
                *second["messages"],
                {"role": "user", "content": "E quanto aos elementos?"},
            ],
        }
    )

    assert third["grounding_status"] == "supported"
    assert "refer" in tools.calls[-1][1]["question"].casefold()
    assert "element" in tools.calls[-1][1]["question"].casefold()


def test_short_aspect_after_answer_reuses_visible_clarification_context():
    tools = FakeTools(references_payload()[0])
    agent = AgentV2(
        planner=ClarificationSequencePlanner(),
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer=references_payload()[1], evidence_ids=["ref-1"]
            )
        ),
        tools=tools,
    )
    conversation_id = "implicit-clarification-context"

    first = agent.invoke(
        {
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    agent.invoke(
        {
            "conversation_id": conversation_id,
            "messages": [
                *first["messages"],
                {"role": "user", "content": "Elementos"},
            ],
        }
    )
    agent.invoke(
        {
            "conversation_id": conversation_id,
            "messages": [
                *first["messages"],
                {"role": "user", "content": "Elementos"},
                {"role": "assistant", "content": "Resposta sobre elementos."},
                {"role": "user", "content": "Formatação"},
            ],
        }
    )

    query = tools.calls[-1][1]["question"].casefold()
    assert "6023" in query
    assert "formata" in query


def test_implicit_clarification_is_ignored_after_a_new_normative_topic():
    history = [
        {"role": "user", "content": "Como formatar referências?"},
        {
            "role": "assistant",
            "content": "Você deseja orientação sobre autoria, elementos ou formatação?",
        },
        {"role": "user", "content": "Elementos"},
        {"role": "assistant", "content": "Resposta sobre elementos."},
        {
            "role": "user",
            "content": "Como formatar uma citação direta longa?",
        },
        {"role": "assistant", "content": "Resposta sobre citação direta longa."},
    ]

    assert AgentV2._implicit_pending_clarification("Formatação", history) is None


def test_new_normative_subject_does_not_inherit_pending_reference_context():
    planner = ClarificationSequencePlanner()
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
        ),
        tools=tools,
    )
    first = agent.invoke(
        {
            "conversation_id": "clarification-new-subject",
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    second = agent.invoke(
        {
            "conversation_id": "clarification-new-subject",
            "messages": [
                *first["messages"],
                {
                    "role": "user",
                    "content": (
                        "Segundo a NBR 10520, como formatar uma citação direta longa?"
                    ),
                },
            ],
        }
    )

    assert second["grounding_status"] == "supported"
    assert "refer" not in tools.calls[-1][1]["question"].casefold()
    assert "10520" in tools.calls[-1][1]["question"]


def test_pending_clarification_can_be_abandoned_for_new_subject():
    planner = ClarificationSequencePlanner()
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
        ),
        tools=tools,
    )

    first = agent.invoke(
        {
            "conversation_id": "clarification-abandon",
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    second = agent.invoke(
        {
            "conversation_id": "clarification-abandon",
            "messages": [
                *first["messages"],
                {
                    "role": "user",
                    "content": "Na verdade, quero saber sobre as margens do trabalho.",
                },
            ],
        }
    )

    assert second["answer"] != GREETING_MESSAGE
    assert "referências" not in tools.calls[-1][1]["question"].casefold()


def test_self_contained_normative_question_bypasses_pending_clarification():
    tools = FakeTools(rag_payload())
    agent = AgentV2(
        planner=Planner(None),
        synthesizer=FakeSynthesizer(
            SynthesisResponse(answer=SOURCE, evidence_ids=["e1"])
        ),
        tools=tools,
    )

    first = agent.invoke(
        {
            "conversation_id": "clarification-self-contained",
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    agent.invoke(
        {
            "conversation_id": "clarification-self-contained",
            "messages": [
                *first["messages"],
                {
                    "role": "user",
                    "content": "Como formatar citação direta longa?",
                },
            ],
        }
    )

    assert tools.calls[-1][1]["question"] == "Como formatar citação direta longa?"


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


@pytest.mark.parametrize(
    "question",
    ["Como fazer citações?", "Como formatar referências?"],
)
def test_planner_does_not_route_broad_academic_questions_to_actions(
    question: str,
) -> None:
    model = FakeStructuredModel(
        PlannerDecision(intent=ConversationIntent.ACTION_REQUEST)
    )
    planner = Planner(model)

    decision = planner.plan(question, [])

    assert decision.intent == ConversationIntent.NORMATIVE_QUERY
    assert decision.needs_retrieval is True


def test_planner_requests_clarification_for_underspecified_margin_question() -> None:
    model = FakeStructuredModel(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    planner = Planner(model)

    decision = planner.plan("Qual é o recuo?", [])

    assert decision.intent == ConversationIntent.AMBIGUOUS
    assert decision.needs_clarification is True
    assert decision.clarification_questions


def test_planner_routes_explicit_academic_topic_change_to_retrieval() -> None:
    model = FakeStructuredModel(
        PlannerDecision(intent=ConversationIntent.ACTION_REQUEST)
    )
    planner = Planner(model)

    decision = planner.plan(
        "Na verdade, quero saber sobre as margens do trabalho.", []
    )

    assert decision.intent == ConversationIntent.NORMATIVE_QUERY
    assert decision.needs_retrieval is True


def test_planner_routes_academic_contextual_follow_up_to_retrieval() -> None:
    model = FakeStructuredModel(
        PlannerDecision(intent=ConversationIntent.ACTION_REQUEST)
    )
    planner = Planner(model)

    decision = planner.plan(
        "E quanto aos elementos?",
        [{"role": "user", "content": "Como indicar autoria nas referências?"}],
    )

    assert decision.intent == ConversationIntent.NORMATIVE_QUERY
    assert decision.needs_retrieval is True


def test_planner_uses_academic_history_for_underspecified_follow_up() -> None:
    model = FakeStructuredModel(
        PlannerDecision(intent=ConversationIntent.ACTION_REQUEST)
    )
    planner = Planner(model)

    decision = planner.plan(
        "Qual é o recuo?",
        [{"role": "user", "content": "Citação direta longa"}],
    )

    assert decision.intent == ConversationIntent.NORMATIVE_QUERY
    assert decision.needs_retrieval is True


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Citação direta longa", True),
        ("Citação indireta", False),
        ("Citação direta curta", False),
    ],
)
def test_recuo_resolution_preserves_explicit_citation_type(
    answer: str, expected: bool
) -> None:
    resolved = Planner._deterministic_clarification_query(
        answer, "Qual é o recuo?"
    )

    assert (resolved is not None) is expected


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


def test_short_clarification_grounds_against_resolved_question() -> None:
    planner = ClarificationSequencePlanner()
    answer = (
        "Os elementos essenciais para livro e/ou folheto são: autor, título, "
        "subtítulo (se houver), edição (se houver), local, editora e data de "
        "publicação."
    )
    tools = FakeTools(
        {
            "status": "success",
            "evidence_found": True,
            "documents": [
                {
                    "document_id": 6023,
                    "title": "ABNT NBR 6023",
                    "standard_id": "abnt_nbr_6023",
                    "evidence": [
                        {
                            "evidence_id": "ref-elements",
                            "text": (
                                "7.1.1 "
                                + answer
                                + " Quando necessário, acrescentam-se elementos "
                                "complementares à referência."
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
            SynthesisResponse(answer=answer, evidence_ids=["ref-elements"])
        ),
        tools=tools,
    )

    first = agent.invoke(
        {
            "conversation_id": "short-clarification-grounding",
            "messages": [{"role": "user", "content": "Como formatar referências?"}],
        }
    )
    second = agent.invoke(
        {
            "conversation_id": first["conversation_id"],
            "messages": [
                *first["messages"],
                {"role": "user", "content": "Elementos"},
            ],
        }
    )

    assert second["grounding_status"] == "supported"
    assert second["published_evidence_ids"] == ["ref-elements"]
    assert "NBR 6023" in tools.calls[-1][1]["question"]


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
    assert result["errors"] == [LimitationCode.EVIDENCE_UNAVAILABLE.value]
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


def test_structured_clarification_question_can_contain_normative_terms() -> None:
    reply = "Você quer saber se as citações devem ter recuo?"
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[reply],
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como formatar?"}]})

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == reply


def test_structured_clarification_with_comma_normative_prefix_fails_closed() -> None:
    reply = (
        "As citações diretas longas devem ter recuo, qual trecho você quer formatar?"
    )
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[reply],
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como formatar?"}]})

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE


def test_structured_clarification_with_comma_normative_suffix_fails_closed() -> None:
    reply = (
        "Qual trecho você quer formatar, já que as citações diretas longas "
        "devem ter recuo?"
    )
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[reply],
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como formatar?"}]})

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE


def test_structured_clarification_with_embedded_normative_clause_fails_closed() -> None:
    reply = (
        "Qual trecho você quer formatar, já que as citações diretas longas "
        "devem ter recuo, no seu trabalho?"
    )
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[reply],
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como formatar?"}]})

    assert result["grounding_status"] == "unsupported"
    assert result["answer"] == INSUFFICIENT_EVIDENCE


def test_structured_clarification_with_normative_alternatives_remains_conversational(
) -> None:
    reply = (
        "Você quer saber se as citações devem ter recuo, fonte menor ou "
        "espaçamento simples?"
    )
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=[reply],
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como formatar?"}]})

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == reply


def test_multiple_structured_questions_allow_normative_question_terms() -> None:
    questions = [
        "Você quer saber se as citações devem ter recuo?",
        "Qual trecho você quer formatar?",
    ]
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.AMBIGUOUS,
            needs_clarification=True,
            clarification_questions=questions,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer="nunca")),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como formatar?"}]})

    assert result["grounding_status"] == "conversational"
    assert result["answer"] == "\n".join(questions)


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


def test_selected_evidence_ids_remain_auditable_after_grounding() -> None:
    answer = "A citação deve observar a norma aplicável."
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
            SynthesisResponse(answer=answer, evidence_ids=["e1", "e2"])
        ),
        tools=FakeTools(
            {
                "status": "success",
                "evidence_found": True,
                "documents": [
                    {
                        "evidence": [
                            {"evidence_id": "e1", "text": answer},
                            {"evidence_id": "e2", "text": "Outro trecho."},
                        ]
                    }
                ],
            }
        ),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Como citar?"}]})

    assert result["selected_evidence_ids"] == ["e1", "e2"]
    assert result["published_evidence_ids"] == ["e1"]


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


def test_grounding_rejection_is_distinguished_from_missing_evidence() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer="A margem direita deve medir 7 cm.", evidence_ids=["e1"]
            )
        ),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual é a margem?"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["errors"] == ["grounding_rejected"]


def test_unsupported_broad_citation_question_requests_clarification() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    store = ConversationStore()
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer="A citação deve observar regras não recuperadas.",
                evidence_ids=["e1"],
            )
        ),
        tools=FakeTools(rag_payload()),
        store=store,
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como fazer citações?"}]}
    )

    assert result["completion_type"] == "clarification_requested"
    assert result["grounding_status"] == "conversational"
    assert result["answer"].endswith("fontes?")
    assert result["published_evidence_ids"] == []
    assert result["errors"] == ["grounding_rejected"]
    assert store.pending_clarification(result["conversation_id"]) is not None


def test_partial_broad_reference_answer_requests_clarification() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    supported = (
        "As notas de referência devem ter numeração única e consecutiva para "
        "cada capítulo ou parte."
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer=(
                    f"{supported}\nA formatação deve seguir uma regra "
                    "não recuperada."
                ),
                evidence_ids=["e1"],
            )
        ),
        tools=FakeTools(
            {
                "status": "success",
                "evidence_found": True,
                "documents": [
                    {
                        "document_id": 10520,
                        "title": "ABNT NBR 10520",
                        "evidence": [{"evidence_id": "e1", "text": supported}],
                    }
                ],
            }
        ),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como formatar referências?"}]}
    )

    assert result["completion_type"] == "clarification_requested"
    assert result["grounding_status"] == "conversational"
    assert result["published_evidence_ids"] == []


def test_supported_broad_answer_is_not_replaced_by_clarification() -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(
            SynthesisResponse(
                answer=SOURCE,
                evidence_ids=["e1"],
            )
        ),
        tools=FakeTools(rag_payload()),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como fazer citações?"}]}
    )

    assert result["grounding_status"] == "supported"
    assert result["completion_type"] == "grounded_answer"
    assert result["published_evidence_ids"] == ["e1"]


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        ("ConnectionError", "retrieval_connection_error"),
        ("RuntimeError", "retrieval_tool_error"),
    ],
)
def test_retrieval_failures_have_distinct_internal_diagnostics(
    error_type: str, expected: str
) -> None:
    planner = FakePlanner(
        PlannerDecision(
            intent=ConversationIntent.NORMATIVE_QUERY,
            needs_retrieval=True,
        )
    )
    agent = AgentV2(
        planner=planner,
        synthesizer=FakeSynthesizer(SynthesisResponse(answer=SOURCE)),
        tools=FakeTools(
            {
                "status": "error",
                "evidence_found": False,
                "error_type": error_type,
                "documents": [],
            }
        ),
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Como citar?"}]}
    )

    assert result["grounding_status"] == "unsupported"
    assert result["errors"] == [expected]


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


def test_pending_clarification_state_isolated_and_consumed() -> None:
    store = ConversationStore()
    store.ensure("first")
    store.ensure("second")
    store.set_pending_clarification(
        "first", "Como formatar referências?", "Qual aspecto?"
    )

    assert store.pending_clarification("first") is not None
    assert store.pending_clarification("second") is None

    store.clear_pending_clarification("first")
    assert store.pending_clarification("first") is None
