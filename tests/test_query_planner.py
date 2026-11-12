import json

import pytest
from src.app.query_planner import (
    contextualize_query,
    focused_query,
    is_broad_question,
    plan_queries,
)


def test_broad_question_gets_generic_expansion() -> None:
    question = "Quais são as principais regras de formatação de um TCC?"

    assert is_broad_question(question)
    queries = plan_queries(question)

    assert len(queries) == 2
    assert "trabalhos acadêmicos" in queries[1]
    assert "estrutura" in queries[1]


def test_common_normative_topics_get_targeted_expansion() -> None:
    citation_queries = plan_queries("Como fazer citações?")
    reference_queries = plan_queries("Como formatar referências?")

    assert "NBR 10520" in citation_queries[1]
    assert "recuo" in citation_queries[1]
    assert "NBR 6023" in reference_queries[1]
    assert "autores" in reference_queries[1]


def test_specific_question_is_not_expanded() -> None:
    queries = plan_queries("Qual é o item 7.1 da ABNT NBR 10520?")

    assert queries == ["Qual é o item 7.1 da ABNT NBR 10520?"]


@pytest.mark.parametrize(
    "question",
    ["Como fazer citações?", "Como formatar referências?", "Qual é o recuo?"],
)
def test_common_academic_questions_use_broad_retrieval(question: str) -> None:
    assert is_broad_question(question)


def test_focused_query_preserves_normative_terms_without_question_scaffolding() -> None:
    question = (
        "Segundo a ABNT, como devem ser escritos os nomes dos autores "
        "nas referências bibliográficas? Devem ficar em letras maiúsculas?"
    )

    assert focused_query(question) == (
        "abnt (autores letras maiúsculas) OR "
        "nomes referências bibliográficas"
    )


def test_focused_query_preserves_multiple_normative_subjects() -> None:
    question = (
        "Qual a diferença entre referências bibliográficas e citações diretas "
        "segundo a ABNT?"
    )

    result = focused_query(question)

    assert "referências" in result
    assert "bibliográficas" in result
    assert "citações" in result
    assert "diretas" in result


def test_focused_query_preserves_name_and_reference_subjects() -> None:
    question = "Como apresentar os nomes dos autores nas referências segundo a ABNT?"

    result = focused_query(question)

    assert "nomes" in result
    assert "autores" in result
    assert "referências" in result


def test_focused_query_preserves_margin_and_spacing_subjects() -> None:
    question = (
        "Quais regras de margens e espaçamento devo usar em trabalhos "
        "acadêmicos segundo a ABNT?"
    )

    result = focused_query(question)

    assert "margens" in result
    assert "espaçamento" in result


def test_contextual_follow_up_keeps_original_intent_and_previous_topic() -> None:
    history = [
        {"role": "user", "content": "Como devo formatar um TCC segundo a ABNT?"},
        {"role": "assistant", "content": "A formatação inclui margens e recuos."},
    ]

    query = contextualize_query("Qual o tamanho do recuo necessário?", history)

    assert "Qual o tamanho do recuo necessário?" in query
    assert "formatar um TCC" in query
    assert plan_queries("Qual o tamanho do recuo necessário?", history) == [query]


def test_underspecified_recuo_follow_up_uses_academic_history() -> None:
    history = [
        {"role": "user", "content": "Citação direta longa"},
        {"role": "assistant", "content": "A citação deve ter recuo."},
    ]

    query = contextualize_query("Qual é o recuo?", history)

    assert "Qual é o recuo?" in query
    assert "citação direta longa" in query.casefold()


def test_specific_element_in_broad_previous_question_is_preserved() -> None:
    history = [
        {"role": "user", "content": "Como formatar citação direta longa?"},
        {"role": "assistant", "content": "A citação deve ter recuo."},
    ]

    query = contextualize_query("Qual é o recuo?", history)

    assert "citação direta longa" in query.casefold()


@pytest.mark.parametrize(
    "question",
    ["Qual deve ser o espaçamento?", "Como deve ser a fonte?"],
)
def test_equivalent_underspecified_follow_ups_keep_previous_topic(
    question: str,
) -> None:
    history = [
        {"role": "user", "content": "Como formatar citação direta longa?"},
        {"role": "assistant", "content": "A citação deve ter recuo."},
    ]

    query = contextualize_query(question, history)

    assert "Como formatar citação direta longa?" in query


@pytest.mark.parametrize(
    "question",
    ["Como formatar referências?", "Qual é o recuo?"],
)
def test_self_contained_questions_do_not_inherit_unrelated_context(
    question: str,
) -> None:
    history = [
        {"role": "user", "content": "Como fazer citações?"},
        {"role": "assistant", "content": "Resposta sobre citações."},
    ]

    assert contextualize_query(question, history) == question


def test_clarification_completion_is_contextualized_for_retrieval() -> None:
    query = contextualize_query(
        "As referências.",
        [
            {"role": "user", "content": "Como formatar?"},
            {"role": "assistant", "content": "Qual elemento?"},
        ],
    )

    assert query == "As referências. Contexto da pergunta anterior: Como formatar?"


def test_broad_rag_search_merges_adaptive_results(monkeypatch) -> None:
    from src.app.tools import rag_search

    def fake_search(question: str, **_kwargs):
        if "trabalhos acadêmicos" in question:
            return [
                {
                    "document_id": 14724,
                    "title": "Trabalhos acadêmicos",
                    "version": "2024",
                    "metadata": {"id": "abnt_nbr_14724"},
                    "rrf_score": 0.02,
                    "pages": [8],
                    "matched_pages": [{"page_number": 8, "direct_match": True}],
                    "page_context": [
                        {"page_number": 8, "page_text": "A apresentação deve..."}
                    ],
                }
            ]
        return [
            {
                "document_id": 6024,
                "title": "Numeração progressiva",
                "version": "2012",
                "metadata": {"id": "abnt_nbr_6024"},
                "rrf_score": 0.02,
                "pages": [6],
                "matched_pages": [{"page_number": 6, "direct_match": True}],
                "page_context": [
                    {"page_number": 6, "page_text": "A seção deve..."}
                ],
            }
        ]

    monkeypatch.setattr(rag_search, "search_documents", fake_search)
    result = json.loads(
        rag_search.rag_document_search.invoke(
            {"question": "Quais são as principais regras de formatação de um TCC?"}
        )
    )

    assert result["adaptive_retrieval"] is True
    assert result["retrieval_queries"]
    assert result["documents"][0]["standard_label"] == "ABNT NBR 14724"


def test_adaptive_search_keeps_first_result_when_expansion_fails(monkeypatch) -> None:
    from src.app.tools import rag_search

    calls = 0

    def flaky_search(question: str, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("embedding indisponível")
        return [
            {
                "document_id": 14724,
                "title": "Trabalhos acadêmicos",
                "version": "2024",
                "metadata": {"id": "abnt_nbr_14724"},
                "rrf_score": 0.02,
                "pages": [8],
                "page_context": [
                    {"page_number": 8, "page_text": "A apresentação deve..."}
                ],
            }
        ]

    monkeypatch.setattr(rag_search, "search_documents", flaky_search)
    result = json.loads(
        rag_search.rag_document_search.invoke(
            {"question": "Quais são as principais regras de formatação de um TCC?"}
        )
    )

    assert result["status"] == "success"
    assert result["documents"][0]["standard_label"] == "ABNT NBR 14724"


def test_adaptive_merge_deduplicates_documents_without_adding_rrf_scores(
    monkeypatch,
) -> None:
    from src.app.tools import rag_search

    def fake_search(question: str, **_kwargs):
        page = 8 if "primeira" in question else 9
        return [
            {
                "id": 32,
                "document_id": 14724,
                "title": "Trabalhos acadêmicos",
                "metadata": {"id": "abnt_nbr_14724"},
                "rrf_score": 0.02 if page == 8 else 0.01,
                "pages": [page],
                "page_context": [
                    {"page_number": page, "page_text": f"Trecho da página {page}."}
                ],
            }
        ]

    monkeypatch.setattr(rag_search, "search_documents", fake_search)
    monkeypatch.setattr(
        rag_search,
        "plan_queries",
        lambda _question: ["primeira consulta", "segunda consulta"],
    )

    result = json.loads(
        rag_search.rag_document_search.invoke(
            {"question": "Quais são as principais regras de formatação?"}
        )
    )

    document = result["documents"][0]
    assert len(result["documents"]) == 1
    assert document["retrieval_hits"] == 2
    assert document["retrieval_queries"] == [
        "primeira consulta",
        "segunda consulta",
    ]
    assert document["rrf_score"] == 0.02
    assert document["pages"] == [8, 9]
