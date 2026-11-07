import json

from src.app.query_planner import is_broad_question, plan_queries


def test_broad_question_gets_generic_expansion() -> None:
    question = "Quais são as principais regras de formatação de um TCC?"

    assert is_broad_question(question)
    queries = plan_queries(question)

    assert len(queries) == 2
    assert "trabalhos acadêmicos" in queries[1]
    assert "estrutura" in queries[1]


def test_specific_question_is_not_expanded() -> None:
    queries = plan_queries("Qual é o item 7.1 da ABNT NBR 10520?")

    assert queries == ["Qual é o item 7.1 da ABNT NBR 10520?"]


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
