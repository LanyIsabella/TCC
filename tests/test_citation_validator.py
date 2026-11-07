from src.app.citation_validator import (
    grounded_answer,
    supporting_excerpts,
    validate_answer_citations,
)


def evidence() -> list[dict[str, object]]:
    return [
        {
            "standard_label": "ABNT NBR 10520",
            "version": "2023",
            "matched_pages": [{"page_number": 12, "direct_match": True}],
            "page_context": [
                {
                    "page_number": 12,
                    "page_text": (
                        "Citações diretas no texto de até três linhas devem "
                        "estar contidas entre aspas duplas."
                    ),
                }
            ],
        }
    ]


def test_validates_standard_and_page_against_evidence() -> None:
    answer = (
        "Citações diretas curtas devem estar entre aspas.\n\n"
        "### Base normativa\n\n"
        "- ABNT NBR 10520:2023, p. 12."
    )

    result = validate_answer_citations(answer, evidence())

    assert result["valid"] is True
    assert result["issues"] == []


def test_rejects_page_not_returned_by_rag() -> None:
    answer = "### Base normativa\n\n- ABNT NBR 10520:2023, p. 99."

    result = validate_answer_citations(answer, evidence())

    assert result["valid"] is False
    assert "citation_page_not_in_evidence" in result["issues"]


def test_grounded_answer_replaces_unverified_literal_quote() -> None:
    answer = (
        '"Este trecho não existe na página recuperada e não deve ser usado."\n\n'
        "### Base normativa\n\n"
        "- ABNT NBR 10520:2023, p. 12."
    )

    result = grounded_answer(answer, evidence())

    assert "Não consegui validar o trecho literal" in result
    assert "ABNT NBR 10520:2023, p. 12" in result


def test_extracts_normative_supporting_excerpt_from_page_context() -> None:
    excerpts = supporting_excerpts(
        evidence(), query="citação direta curta segundo a ABNT NBR 10520"
    )

    assert len(excerpts) == 1
    assert "devem estar contidas" in excerpts[0]["text"]
    assert excerpts[0]["page"] == 12


def test_grounded_answer_renders_supporting_excerpt() -> None:
    answer = (
        "Citações diretas curtas devem estar entre aspas.\n\n"
        "### Base normativa\n\n"
        "- ABNT NBR 10520:2023, p. 12."
    )

    result = grounded_answer(
        answer, evidence(), query="citação direta curta segundo a ABNT NBR 10520"
    )

    assert "### Trechos que sustentam a resposta" in result
    assert "devem estar contidas" in result
