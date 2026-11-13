"""Verificação por afirmação: identidade, prova textual e contradições críticas."""

import json

import pytest
from src.app.grounding import INSUFFICIENT_EVIDENCE, PARTIAL_LIMITATION, ground_answer

QUESTION = "Qual a regra de formatação segundo a ABNT?"


def evidence(text):
    return {"e1": {"evidence_id": "e1", "text": text, "matched_text": text}}


def judge(quote, *, supported=True, evidence_id="e1"):
    return lambda *_args: {
        "claims": [
            {
                "index": 0,
                "supported": supported,
                "evidence_id": evidence_id,
                "quote": quote,
            }
        ]
    }


def test_literal_complete_rule_is_supported_even_without_model_ids():
    text = "A margem direita deve medir 2 cm."
    result = ground_answer(text, evidence(text), QUESTION)
    assert result.answer == text
    assert result.evidence_ids == ("e1",)


def test_mixed_mode_preserves_general_prose_while_grounding_normative_claims():
    answer = "A metodologia organiza as etapas. A margem direita deve medir 2 cm."
    result = ground_answer(
        answer,
        evidence("A margem direita deve medir 2 cm."),
        QUESTION,
        response_mode="mixed",
        normative_context=True,
    )

    assert result.status == "supported"
    assert result.answer == answer
    assert result.evidence_ids == ("e1",)


def test_mixed_mode_rejects_unsupported_normative_claim_but_keeps_general_prose():
    answer = "A metodologia organiza as etapas. A margem direita deve medir 9 cm."
    result = ground_answer(
        answer,
        evidence("A margem direita deve medir 2 cm."),
        QUESTION,
        response_mode="mixed",
        normative_context=True,
    )

    assert result.status == "partial"
    assert "A metodologia organiza" in result.answer
    assert PARTIAL_LIMITATION in result.answer


def test_mixed_mode_semantic_classifier_rejects_implicit_normative_claim():
    answer = "A citação direta curta fica entre aspas duplas."
    def classifier(*_args):
        return {"claims": [{"index": 0, "kind": "normative"}]}

    result = ground_answer(
        answer,
        evidence("A metodologia organiza as etapas."),
        "Como fazer uma citação direta curta segundo a ABNT?",
        response_mode="mixed",
        normative_context=True,
        claim_classifier=classifier,
    )

    assert result.status == "insufficient"
    assert result.answer == INSUFFICIENT_EVIDENCE


def _raising_classifier(*_args):
    raise RuntimeError("indisponível")


@pytest.mark.parametrize(
    "classifier",
    [
        None,
        _raising_classifier,
        lambda *_args: "invalid json",
        lambda *_args: {"claims": []},
        lambda *_args: {"claims": [{"index": 0, "kind": "general"}]},
    ],
)
def test_inconclusive_classifier_does_not_release_implicit_normative_claim(classifier):
    answer = "A citação curta aparece entre aspas duplas."

    result = ground_answer(
        answer,
        evidence("A metodologia organiza as etapas."),
        "Como fazer citações segundo a ABNT?",
        response_mode="mixed",
        normative_context=True,
        claim_classifier=classifier,
    )

    assert result.status == "insufficient"
    assert result.answer == INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "classifier",
    [
        None,
        lambda *_args: "invalid json",
        lambda *_args: {"claims": []},
        lambda *_args: {"claims": [{"index": 0, "kind": "unknown"}]},
    ],
)
def test_mixed_mode_rejects_unclassified_normative_statement_without_known_marker(
    classifier,
):
    result = ground_answer(
        "As referências bibliográficas incluem autor e título.",
        evidence("A metodologia organiza as etapas."),
        "Como formatar referências segundo a ABNT?",
        response_mode="mixed",
        normative_context=True,
        claim_classifier=classifier,
    )

    assert result.status == "insufficient"
    assert result.answer == INSUFFICIENT_EVIDENCE


def test_mixed_mode_keeps_conceptual_prose_when_classifier_is_unavailable():
    result = ground_answer(
        "A metodologia organiza as etapas do trabalho.",
        evidence("A margem deve medir 2 cm."),
        QUESTION,
        response_mode="mixed",
        normative_context=True,
    )

    assert result.status == "conversational"
    assert result.answer == "A metodologia organiza as etapas do trabalho."


def test_partial_classifier_keeps_general_claim_but_removes_unclassified_rule():
    answer = (
        "A metodologia organiza as etapas do trabalho. "
        "A citação curta aparece entre aspas duplas."
    )

    result = ground_answer(
        answer,
        evidence("A metodologia organiza as etapas do trabalho."),
        QUESTION,
        response_mode="mixed",
        normative_context=True,
        claim_classifier=lambda *_args: {
            "claims": [{"index": 0, "kind": "general"}]
        },
    )

    assert result.status == "partial"
    assert "A metodologia organiza" in result.answer
    assert "A citação curta aparece" not in result.answer
    assert PARTIAL_LIMITATION in result.answer


def test_mixed_mode_preserves_markdown_structure_when_removing_unsupported_rule():
    answer = (
        "A metodologia organiza as etapas.\n\n"
        "- A margem direita deve medir 2 cm.\n"
        "- A citação direta curta fica entre aspas duplas."
    )
    def classifier(*_args):
        return {
            "claims": [
                {"index": 0, "kind": "general"},
                {"index": 1, "kind": "normative"},
                {"index": 2, "kind": "normative"},
            ]
        }

    result = ground_answer(
        answer,
        evidence("A margem direita deve medir 2 cm."),
        "Como fazer citações segundo a ABNT?",
        response_mode="mixed",
        normative_context=True,
        claim_classifier=classifier,
    )

    assert result.status == "partial"
    assert "\n- A margem direita deve medir 2 cm." in result.answer
    assert "\n- A citação direta curta" not in result.answer
    assert PARTIAL_LIMITATION in result.answer


def test_literal_rule_from_reference_only_document_is_not_relevant_support():
    source = (
        "Os Documentos Técnicos ABNT podem ser objeto de citação em "
        "Regulamentos Técnicos."
    )
    available = {
        "e1": {
            "evidence_id": "e1",
            "title": "Informação e documentação — Trabalhos acadêmicos",
            "standard_id": "abnt_nbr_14724",
            "text": source,
        }
    }

    result = ground_answer(
        source,
        available,
        "Como fazer citações?",
        normative_context=True,
    )

    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == ()


def test_literal_rule_survives_page_header_and_section_paragraphs():
    source = (
        "ABNT NBR 6023:2025\n\n"
        "8.1.1 Pessoa física\n\n"
        "O autor deve ser indicado pelo último sobrenome, em letras maiúsculas, "
        "seguido do prenome e outros sobrenomes, abreviados ou não, conforme "
        "consta no documento."
    )
    answer = (
        "O autor deve ser indicado pelo último sobrenome, em letras maiúsculas, "
        "seguido do prenome e outros sobrenomes, abreviados ou não, conforme "
        "consta no documento."
    )

    result = ground_answer(
        answer,
        evidence(source),
        "Como devem ser indicados os autores nas referências?",
        normative_context=True,
    )

    assert result.answer == answer
    assert result.evidence_ids == ("e1",)


def test_literal_reference_format_rule_ignores_unrelated_following_condition():
    answer = (
        "As referências devem ser elaboradas em espaço simples, alinhadas à "
        "margem esquerda do texto e separadas entre si por uma linha em branco "
        "de espaço simples."
    )
    source = (
        "6.3 "
        + answer
        + " Quando aparecerem em notas de rodapé, devem ser alinhadas à margem "
        "esquerda do texto."
    )

    result = ground_answer(
        answer,
        evidence(source),
        "Segundo a ABNT NBR 6023, quais são as regras de formatação das referências?",
        normative_context=True,
    )

    assert result.answer == answer
    assert result.status == "supported"
    assert result.evidence_ids == ("e1",)


def test_citation_standard_is_not_relevant_to_reference_question_by_mention():
    source = (
        "A citação direta, com mais de três linhas, deve ser destacada com "
        "recuo padronizado. A ABNT NBR 6023 é uma referência normativa."
    )
    available = {
        "e1": {
            "evidence_id": "e1",
            "title": "Informação e documentação — Citações em documentos",
            "standard_id": "abnt_nbr_10520",
            "text": source,
        }
    }

    result = ground_answer(
        source,
        available,
        "Como formatar referências bibliográficas?",
        normative_context=True,
    )

    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == ()


def test_semantic_verifier_cannot_bypass_reference_topic_filter():
    source = (
        "As citações diretas no texto, de até três linhas, devem estar contidas "
        "entre aspas duplas."
    )
    available = {
        "e1": {
            "evidence_id": "e1",
            "title": "Informação e documentação — Citações em documentos",
            "standard_id": "abnt_nbr_10520",
            "text": source,
        }
    }

    result = ground_answer(
        "As citações devem estar entre aspas.",
        available,
        "Como formatar referências bibliográficas?",
        judge(source),
        normative_context=True,
    )

    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == ()


def test_reference_spacing_rule_from_academic_standard_is_relevant():
    source = (
        "As referências, ao final do trabalho, devem ser separadas entre si "
        "por um espaço simples em branco."
    )
    available = {
        "e1": {
            "evidence_id": "e1",
            "title": "Informação e documentação — Trabalhos acadêmicos",
            "standard_id": "abnt_nbr_14724",
            "text": source,
        }
    }

    result = ground_answer(
        source,
        available,
        "Qual é o espaçamento entre referências?",
        normative_context=True,
    )

    assert result.status == "supported"
    assert result.evidence_ids == ("e1",)


def test_following_restriction_of_the_same_rule_cannot_be_omitted():
    source = (
        "A margem deve medir 2 cm. "
        "Esta regra se aplica somente a trabalhos impressos."
    )

    result = ground_answer(
        "A margem deve medir 2 cm.", evidence(source), QUESTION
    )

    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == ()


def test_reference_author_rule_accepts_citar_verb_in_question():
    source = (
        "O autor deve ser indicado pelo último sobrenome, em letras maiúsculas, "
        "seguido do prenome."
    )
    available = {
        "e1": {
            "evidence_id": "e1",
            "title": "ABNT NBR 6023",
            "standard_id": "abnt_nbr_6023",
            "text": source,
        }
    }

    result = ground_answer(
        source,
        available,
        "Como citar autores nas referências?",
        normative_context=True,
    )

    assert result.status == "supported"
    assert result.evidence_ids == ("e1",)


def test_citation_rule_from_other_standard_is_relevant_support():
    source = (
        "As citações com mais de três linhas devem ser em tamanho menor e uniforme."
    )
    available = {
        "e1": {
            "evidence_id": "e1",
            "title": "Informação e documentação — Artigo em publicação periódica",
            "standard_id": "abnt_nbr_6022",
            "text": source,
        }
    }

    result = ground_answer(
        source,
        available,
        "Qual deve ser o tamanho da fonte das citações em artigos científicos?",
        normative_context=True,
    )

    assert result.status == "supported"
    assert result.evidence_ids == ("e1",)


def test_literal_rule_survives_truncated_page_sentence_punctuation():
    source = (
        "ABNT NBR 6023:2025\n\n"
        "8.1.1 Pessoa física\n\n"
        "O autor deve ser indicado pelo último sobrenome, em letras maiúsculas, "
        "seguido do prenome e outros sobrenome"
    )
    answer = source.rsplit("\n\n", 1)[-1] + "."

    result = ground_answer(
        answer,
        evidence(source),
        "Como devem ser indicados os autores nas referências?",
        normative_context=True,
    )

    assert result.answer == answer
    assert result.evidence_ids == ("e1",)


def test_paraphrase_can_be_supported_by_semantic_assessment_and_real_quote():
    source = "A margem direita deve medir 2 cm."
    answer = "É obrigatório deixar dois centímetros na margem direita."
    result = ground_answer(answer, evidence(source), QUESTION, judge(source))
    assert result.answer == answer
    assert result.status == "supported"


@pytest.mark.parametrize(
    "source,answer",
    [
        ("A margem direita deve medir 2 cm.", "A margem direita deve medir 7 cm."),
        ("A margem direita deve medir 2 mm.", "A margem direita deve medir 2 cm."),
        ("A fonte deve ter dois pontos.", "A fonte deve ter sete pontos."),
        ("Não se deve usar aspas.", "Deve-se usar aspas."),
        ("É permitido usar aspas.", "É proibido usar aspas."),
        ("O uso de negrito é opcional.", "O uso de negrito é obrigatório."),
        (
            "O resumo deve ter no mínimo 150 palavras.",
            "O resumo deve ter no máximo 150 palavras.",
        ),
        (
            "Se impresso, o texto deve ter margem de 2 cm.",
            "O texto deve ter margem de 2 cm.",
        ),
        (
            "A margem deve medir 2 cm, exceto em folhas especiais.",
            "A margem deve medir 2 cm.",
        ),
        (
            "Se impresso, o texto deve ter margem de 2 cm.",
            "A margem deve sempre medir 2 cm.",
        ),
    ],
)
def test_explicit_conflict_rejects_even_a_positive_semantic_judge(source, answer):
    result = ground_answer(answer, evidence(source), QUESTION, judge(source))
    assert result.answer == INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == ()


def test_equivalent_units_do_not_trigger_false_numeric_contradiction():
    source = "A margem deve medir 2 cm."
    answer = "A margem deve medir 20 mm."
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


def test_condition_can_be_carried_by_the_current_question():
    source = "Quando impresso, o texto deve ter margem de 2 cm."
    answer = "O texto deve ter margem de 2 cm."
    result = ground_answer(
        answer, evidence(source), "Quando impresso, qual a margem?", judge(source)
    )
    assert result.answer == answer


def test_quote_cannot_hide_condition_in_the_same_source_paragraph():
    source = "Quando impresso, o texto deve ter margem de 2 cm."
    quote = "o texto deve ter margem de 2 cm."
    answer = "O texto deve ter margem de 2 cm."
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(quote)).evidence_ids
        == ()
    )


@pytest.mark.parametrize(
    "quote,identifier",
    [("Texto inventado.", "e1"), ("A margem deve medir 2 cm.", "inventado")],
)
def test_model_cannot_fabricate_the_quote_or_evidence_identity(quote, identifier):
    result = ground_answer(
        "A margem mede dois centímetros.",
        evidence("A margem deve medir 2 cm."),
        QUESTION,
        judge(quote, evidence_id=identifier),
    )
    assert result.evidence_ids == ()
    assert result.answer == INSUFFICIENT_EVIDENCE


def test_unsupported_claim_is_removed_while_supported_part_remains():
    good = "A margem direita deve medir 2 cm."
    result = ground_answer(
        good + " A fonte deve ter 99 pontos.", evidence(good), QUESTION
    )
    assert good in result.answer
    assert "99" not in result.answer
    assert "não" in result.answer.lower()
    assert result.status == "partial"


def test_lexical_match_is_only_a_candidate_not_factual_proof():
    result = ground_answer(
        "A margem direita deve medir 7 cm.",
        evidence("A lombada deve medir 7 cm."),
        QUESTION,
    )
    assert result.evidence_ids == ()
    assert result.answer == INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "response",
    ["invalid json", {"claims": []}, {"claims": [{"index": 0, "supported": "yes"}]}],
)
def test_unverifiable_assessment_never_preserves_original_rule(response):
    result = ground_answer(
        "A margem mede dois centímetros.",
        evidence("A margem deve medir 2 cm."),
        QUESTION,
        lambda *_: response,
    )
    assert result.answer == INSUFFICIENT_EVIDENCE


def test_judge_failure_is_an_explicit_limitation_not_old_answer():
    def broken(*_args):
        raise TimeoutError("sem avaliador")

    result = ground_answer(
        "A margem mede dois centímetros.",
        evidence("A margem deve medir 2 cm."),
        QUESTION,
        broken,
    )
    assert result.answer == INSUFFICIENT_EVIDENCE


def test_greeting_and_clarification_do_not_need_documentary_proof():
    assert ground_answer("Olá!", {}, "Olá!").answer == "Olá!"
    question = "Você está perguntando sobre fonte ou margem?"
    assert ground_answer(question, {}, QUESTION).answer == question


def test_conversational_short_rule_still_requires_evidence():
    assert (
        ground_answer("Arial.", {}, "Qual a fonte para o TCC?").answer
        == INSUFFICIENT_EVIDENCE
    )


@pytest.mark.parametrize(
    "source,answer",
    [
        ("A citação deve aparecer sem aspas.", "A citação deve aparecer com aspas."),
        (
            "A fonte deve ter 12 pt.",
            "A fonte deve ter 12 pontos e a margem deve medir 7 cm.",
        ),
        (
            "A margem deve medir 2 cm.",
            "A margem deve medir 2 cm, salvo nas folhas especiais.",
        ),
    ],
)
def test_missing_or_added_critical_qualification_cannot_be_approved(source, answer):
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).status
        == "insufficient"
    )


@pytest.mark.parametrize(
    "source,answer",
    [
        ("É proibido usar aspas.", "Não se deve usar aspas."),
        ("O uso de negrito é opcional.", "Não é obrigatório usar negrito."),
        ("O uso de negrito não é obrigatório.", "É opcional usar negrito."),
        ("A fonte deve ter 12 pt.", "A fonte deve ter 12 pontos."),
        (
            "Quando impresso, a margem deve medir 2 cm.",
            "Quando impresso, a margem mede 2 cm.",
        ),
    ],
)
def test_faithful_qualified_paraphrases_are_not_false_refusals(source, answer):
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


def test_repeated_claim_indices_cannot_overwrite_disagreement():
    data = {
        "claims": [
            {"index": 0, "supported": False},
            {
                "index": 0,
                "supported": True,
                "evidence_id": "e1",
                "quote": "A margem mede 2 cm.",
            },
        ]
    }
    value = ground_answer(
        "A margem deve medir dois centímetros.",
        evidence("A margem mede 2 cm."),
        QUESTION,
        lambda *_: data,
    )
    assert value.status == "insufficient"


def test_adjacent_unrelated_negative_rule_does_not_invalidate_supported_sentence():
    source = "A margem direita deve medir 2 cm. Não se deve usar aspas."
    answer = "A margem direita mede dois centímetros."
    value = ground_answer(
        answer, evidence(source), QUESTION, judge("A margem direita deve medir 2 cm.")
    )
    assert value.answer == answer


def test_complete_literal_sentence_can_be_supported_inside_larger_paragraph():
    answer = "A margem direita deve medir 2 cm."
    source = answer + " A fonte deve ter 12 pontos."
    assert ground_answer(answer, evidence(source), QUESTION).answer == answer


@pytest.mark.parametrize(
    "source",
    [
        "Quando impresso, aplica-se esta regra. A margem deve medir 2 cm.",
        "A margem deve medir 2 cm. Exceto em folhas especiais.",
    ],
)
def test_adjacent_scope_or_exception_is_not_removed_from_quote_context(source):
    value = ground_answer(
        "A margem deve medir dois centímetros.",
        evidence(source),
        QUESTION,
        judge("A margem deve medir 2 cm."),
    )
    assert value.status == "insufficient"


@pytest.mark.parametrize(
    "quote,supported", [("", True), ("A margem deve medir 2 cm.", False)]
)
def test_negative_or_quoteless_assessment_does_not_approve_rule(quote, supported):
    value = ground_answer(
        "A margem mede dois centímetros.",
        evidence("A margem deve medir 2 cm."),
        QUESTION,
        judge(quote, supported=supported),
    )
    assert value.status == "insufficient"


@pytest.mark.parametrize("limit", ["mínimo", "máximo"])
def test_matching_numeric_limit_is_preserved(limit):
    source = f"O resumo deve ter no {limit} 150 palavras."
    answer = f"O resumo tem como limite {limit} 150 palavras."
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


@pytest.mark.parametrize("index", [-1, 1, 1000])
def test_out_of_range_claim_indices_are_ignored(index):
    raw = {
        "claims": [
            {
                "index": index,
                "supported": True,
                "evidence_id": "e1",
                "quote": "A margem deve medir 2 cm.",
            }
        ]
    }
    value = ground_answer(
        "A margem mede dois centímetros.",
        evidence("A margem deve medir 2 cm."),
        QUESTION,
        lambda *_: raw,
    )
    assert value.status == "insufficient"


def test_literal_and_empty_evidence_do_not_spend_a_model_verification_call():
    def unexpected(*_args):
        pytest.fail("Não há paráfrase com evidência para avaliar")

    source = "A margem deve medir 2 cm."
    assert (
        ground_answer(source, evidence(source), QUESTION, unexpected).answer == source
    )
    assert ground_answer(source, {}, QUESTION, unexpected).status == "insufficient"


def test_conversational_parts_are_preserved_in_academic_context():
    source = "A margem deve medir 2 cm."
    assert ground_answer("Olá!", {}, QUESTION, normative_context=True).answer == "Olá!"
    assert (
        ground_answer("Olá! " + source, evidence(source), QUESTION).answer
        == "Olá! " + source
    )
    assert ground_answer("Recebi sua mensagem.", {}).answer == "Recebi sua mensagem."


def test_explicit_exception_can_be_preserved_by_a_faithful_paraphrase():
    source = "A margem deve medir 2 cm, exceto em folhas especiais."
    answer = "A margem mede dois centímetros, exceto em folhas especiais."
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


def test_equivalent_condition_markers_are_not_new_exceptions():
    source = "Se impresso, a margem deve medir 2 cm."
    answer = "Quando impresso, a margem mede dois centímetros."
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


def test_fixed_conversational_responses_and_support_classification():
    from src.app.grounding import needs_support
    from src.app.scope_guard import GREETING_MESSAGE, OUT_OF_SCOPE_MESSAGE

    for answer in (GREETING_MESSAGE, OUT_OF_SCOPE_MESSAGE, INSUFFICIENT_EVIDENCE):
        value = ground_answer(answer, {}, QUESTION, normative_context=True)
        assert value.answer == answer
        assert value.status == "conversational"
    assert not needs_support("Obrigada!", QUESTION)
    assert needs_support("Arial.", "Qual a fonte do TCC?")


@pytest.mark.parametrize(
    "source,answer",
    [
        ("A margem direita deve medir 2 cm.", "A margem direita deve medir **2** cm."),
        (
            "Quando impresso, a margem deve medir 2 cm.",
            "**Quando impresso**, a margem deve medir 2 cm.",
        ),
        (
            "A margem deve medir 2 cm, exceto em folhas especiais.",
            "A margem deve medir 2 cm, **exceto em folhas especiais**.",
        ),
    ],
)
def test_inline_markdown_does_not_create_false_refusals(source, answer):
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


def test_markdown_does_not_hide_numeric_contradiction():
    source = "A margem direita deve medir 2 cm."
    value = ground_answer(
        "A margem direita deve medir **7** cm.",
        evidence(source),
        QUESTION,
        judge(source),
    )
    assert value.status == "insufficient"


def test_real_model_json_code_fence_is_a_valid_assessment_envelope():
    source = "A margem direita deve medir 2 cm."
    raw = (
        '```json\n{"claims":[{"index":0,"supported":true,"evidence_id":"e1",'
        '"quote":"A margem direita deve medir 2 cm."}]}\n```'
    )
    value = ground_answer(
        "A margem direita mede dois centímetros.",
        evidence(source),
        QUESTION,
        lambda *_: raw,
    )
    assert value.status == "supported"


@pytest.mark.parametrize(
    "raw",
    [
        'Texto livre ```json\n{"claims":[]}\n```',
        '```json\n{"claims":[]}\n``` texto adicional',
        "```json\nnot json\n```",
    ],
)
def test_code_fence_handling_does_not_accept_prose_or_invalid_payload(raw):
    source = "A margem direita deve medir 2 cm."
    assert (
        ground_answer(
            "A margem direita mede dois centímetros.",
            evidence(source),
            QUESTION,
            lambda *_: raw,
        ).status
        == "insufficient"
    )


def test_equivalent_unit_only_change_has_deterministic_literal_proof():
    source = "A margem direita deve medir 2 cm."
    answer = "A margem direita deve medir 20 mm."
    value = ground_answer(answer, evidence(source), QUESTION)
    assert value.answer == answer
    assert value.evidence_ids == ("e1",)


@pytest.mark.parametrize(
    "source,answer",
    [
        (
            "O resumo deve conter no mínimo 150 palavras.",
            "O resumo não deve conter menos de 150 palavras.",
        ),
        (
            "O resumo deve conter no máximo 500 palavras.",
            "O resumo não deve conter mais de 500 palavras.",
        ),
    ],
)
def test_equivalent_negated_numeric_limits_are_not_polarity_conflicts(source, answer):
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).answer
        == answer
    )


def test_negative_null_metadata_does_not_discard_a_supported_paraphrase_in_batch():
    source = "A margem direita deve medir 2 cm."
    good = "A margem direita mede dois centímetros."
    raw = {
        "claims": [
            {"index": 0, "supported": True, "evidence_id": "e1", "quote": source},
            {"index": 1, "supported": False, "evidence_id": None, "quote": None},
        ]
    }
    value = ground_answer(
        good + " A fonte deve ter 99 pontos.",
        evidence(source),
        QUESTION,
        lambda *_: raw,
    )
    assert value.status == "partial"
    assert good in value.answer
    assert "99" not in value.answer


@pytest.mark.parametrize(
    "identifier,quote",
    [(None, None), ("e1", None), (None, "A margem deve medir 2 cm.")],
)
def test_positive_assessment_cannot_use_null_proof(identifier, quote):
    raw = {
        "claims": [
            {"index": 0, "supported": True, "evidence_id": identifier, "quote": quote}
        ]
    }
    assert (
        ground_answer(
            "A margem mede dois centímetros.",
            evidence("A margem deve medir 2 cm."),
            QUESTION,
            lambda *_: raw,
        ).status
        == "insufficient"
    )


@pytest.mark.parametrize(
    "source,answer",
    [
        (
            "O resumo deve conter no mínimo 150 palavras.",
            "O resumo não deve conter mais de 150 palavras.",
        ),
        (
            "O resumo deve conter no máximo 500 palavras.",
            "O resumo não deve conter menos de 500 palavras.",
        ),
    ],
)
def test_opposite_negated_bounds_are_still_conflicting(source, answer):
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).status
        == "insufficient"
    )


@pytest.mark.parametrize(
    "source_unit,answer_unit",
    [
        ("cm", "centímetro"),
        ("pt", "ponto"),
        ("mm", "milímetro"),
        ("m", "metro"),
        ("palavras", "palavra"),
        ("linhas", "linha"),
    ],
)
def test_singular_units_and_one_in_words_have_literal_proof(source_unit, answer_unit):
    source = f"A medida deve ser 1 {source_unit}."
    number = "uma" if answer_unit in {"palavra", "linha"} else "um"
    answer = f"A medida deve ser {number} {answer_unit}."
    assert ground_answer(answer, evidence(source), QUESTION).answer == answer


def test_singular_unit_does_not_hide_a_numeric_contradiction():
    source = "A fonte deve ter sete pontos."
    answer = "A fonte deve ter um ponto."
    assert (
        ground_answer(answer, evidence(source), QUESTION, judge(source)).status
        == "insufficient"
    )


def test_pretty_printed_fenced_batch_keeps_supported_part():
    source = "A margem direita deve medir 2 cm."
    answer = "A margem direita mede dois centímetros."
    raw = {
        "claims": [
            {"index": 0, "supported": True, "evidence_id": "e1", "quote": source},
            {"index": 1, "supported": False, "evidence_id": None, "quote": None},
        ]
    }
    fenced = "```json\n" + json.dumps(raw, ensure_ascii=False, indent=2) + "\n```"
    value = ground_answer(
        answer + " A fonte deve ter 99 pontos.",
        evidence(source),
        QUESTION,
        lambda *_: fenced,
    )
    assert value.status == "partial"
    assert answer in value.answer and "99" not in value.answer


@pytest.mark.parametrize("item", ["itálico", "caixa alta", "negrito"])
def test_explicit_optional_use_entails_permission_without_a_model_vote(item):
    source = f"O uso de {item} é opcional."
    answer = f"Você pode usar {item}."
    assert (
        ground_answer(
            answer, evidence(source), QUESTION, judge(source, supported=False)
        ).answer
        == answer
    )


def test_permission_does_not_automatically_prove_optionality():
    source = "Você pode usar negrito."
    value = ground_answer(
        "O uso de negrito é opcional.",
        evidence(source),
        QUESTION,
        judge(source, supported=False),
    )
    assert value.status == "insufficient"


@pytest.mark.parametrize(
    "source,answer",
    [
        ("O uso de itálico é opcional.", "Você pode usar negrito."),
        ("O uso de negrito não é opcional.", "Você pode usar negrito."),
        ("O uso de negrito é opcional, exceto em títulos.", "Você pode usar negrito."),
        (
            "Quando impresso, aplica-se esta regra. O uso de negrito é opcional.",
            "Você pode usar negrito.",
        ),
    ],
)
def test_optional_permission_proof_preserves_object_polarity_and_scope(source, answer):
    assert (
        ground_answer(
            answer, evidence(source), QUESTION, judge(source, supported=False)
        ).status
        == "insufficient"
    )


def test_plain_user_text_rewrite_does_not_require_documentary_norms():
    question = (
        "Reescreva com clareza para o TCC: Esta pesquisa busca analisar entrevistas."
    )
    answer = "Esta pesquisa analisa entrevistas."
    value = ground_answer(answer, {}, question, normative_context=True)
    assert value.answer == answer
    assert value.evidence_ids == ()


@pytest.mark.parametrize(
    "question,answer",
    [
        (
            "Reescreva segundo a ABNT: A margem mede 7 cm.",
            "A margem direita deve medir 7 cm.",
        ),
        (
            "Reescreva para o TCC: Esta pesquisa analisa entrevistas.",
            "A fonte deve ter 99 pontos.",
        ),
        ("Reescreva para o TCC: A fonte é Arial.", "Arial."),
        ("Reescreva isso.", "Arial."),
        (
            "Reescreva para o TCC: A margem direita mede sete.",
            "A margem direita mede sete.",
        ),
        (
            "Reescreva para o TCC: A citação direta é livre.",
            "A citação direta é livre.",
        ),
    ],
)
def test_text_rewriting_cannot_bypass_normative_grounding(question, answer):
    assert (
        ground_answer(answer, {}, question, normative_context=True).status
        == "insufficient"
    )


@pytest.mark.parametrize(
    "question,answer",
    [
        ("Qual a fonte?", "Arial."),
        ("Qual o recuo?", "Dois centímetros."),
        ("Qual o tipo de letra?", "Arial."),
    ],
)
def test_implicit_normative_fields_still_need_current_evidence(question, answer):
    assert ground_answer(answer, {}, question).status == "insufficient"
