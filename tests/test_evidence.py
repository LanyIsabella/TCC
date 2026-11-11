"""Testes do contrato de rastreabilidade entre resposta e RAG."""

import json

from data.rag_pipeline import estimated_token_count
from src.app.evidence import AgentAnswer, extract_agent_result
from src.app.grounding import PARTIAL_LIMITATION
from src.app.tools.rag_search import _compact_document, _matched_text, _model_document


def test_compact_document_creates_stable_page_evidences() -> None:
    document = _compact_document(
        {
            "id": 42,
            "document_id": 8,
            "title": "ABNT NBR 6023",
            "version": "2023",
            "metadata": {"issuer": "ABNT"},
            "full_text": (
                "<<<PÁGINA 4>>>\nReferências devem ser organizadas.\n\n"
                "<<<PÁGINA 5>>>\nA lista deve ser apresentada ao final."
            ),
        }
    )

    assert document is not None
    assert [item["evidence_id"] for item in document["evidence"]] == [
        "document:42:page:4",
        "document:42:page:5",
    ]
    assert document["evidence"][0]["text"] == "Referências devem ser organizadas."
    assert document["evidence"][0]["title"] == "ABNT NBR 6023"


def test_compact_document_creates_a_query_match_excerpt() -> None:
    document = _compact_document(
        {
            "id": 42,
            "document_id": 8,
            "title": "ABNT NBR 6023",
            "full_text": (
                "<<<PÁGINA 4>>>\n"
                "Referências devem ser organizadas. Este conteúdo permanece "
                "disponível para o contexto do modelo."
            ),
        },
        "Como organizar as referências bibliográficas?",
    )

    assert document is not None
    evidence = document["evidence"][0]
    assert evidence["matched_text"]
    assert "Referências devem ser organizadas." in evidence["matched_text"]


def test_compaction_preserves_a_query_match_at_the_end_of_a_long_page() -> None:
    late_rule = "REGRA SINTÉTICA: a margem direita mede 2 cm."
    source = "Introdução sintética. " * 100 + late_rule

    document = _compact_document(
        {
            "id": 9001,
            "title": "Fixture F6",
            "page_context": [
                {"page_number": 1, "direct_match": True, "page_text": source}
            ],
        },
        "Qual a margem direita?",
    )

    assert document is not None
    evidence = document["evidence"][0]
    assert late_rule in evidence["text"]
    assert evidence["text"] in source
    assert document["omitted_content"]["characters"] > 0


def test_compaction_prioritizes_a_relevant_late_page() -> None:
    late_rule = "REGRA SINTÉTICA: a margem direita mede 2 cm."
    pages = [
        {
            "page_number": number,
            "direct_match": True,
            "page_text": f"Página {number}. " + "texto neutro " * 150,
        }
        for number in range(1, 4)
    ]
    pages.append(
        {"page_number": 4, "direct_match": True, "page_text": late_rule}
    )

    document = _compact_document(
        {"id": 9001, "title": "Fixture F6", "page_context": pages},
        "Qual a margem direita?",
    )

    assert document is not None
    assert any(
        evidence["page_number"] == 4 and late_rule in evidence["text"]
        for evidence in document["evidence"]
    )
    assert len({evidence["page_number"] for evidence in document["evidence"]}) > 1


def test_compaction_keeps_discontinuous_pages_as_individual_evidence() -> None:
    page_one = "Regra da margem: 2 cm."
    page_two = "A condição posterior exige revisão do caso."
    document = _compact_document(
        {
            "id": 9002,
            "title": "Fixture F6",
            "page_context": [
                {"page_number": 1, "direct_match": True, "page_text": page_one},
                {"page_number": 2, "direct_match": True, "page_text": page_two},
            ],
        },
        "Qual é a regra da margem e qual condição posterior se aplica?",
    )

    assert document is not None
    evidence = document["evidence"]
    assert [item["page_number"] for item in evidence] == [1, 2]
    assert all(item["text"] in {page_one, page_two} for item in evidence)
    assert evidence[0]["evidence_id"] != evidence[1]["evidence_id"]


def test_compaction_records_insufficient_context_without_fabricating_text() -> None:
    document = _compact_document(
        {
            "id": 9003,
            "title": "Fixture F6",
            "page_context": [
                {"page_number": 1, "direct_match": False, "page_text": "Fonte."}
            ],
        },
        "Qual regra inexistente?",
    )

    assert document is not None
    assert document["evidence"][0]["text"] == "Fonte."
    assert document["omitted_content"]["characters"] == 0


def test_compaction_returns_no_document_without_retrieved_text() -> None:
    assert _compact_document(
        {"id": 9010, "title": "Fixture vazia", "pages": [12]},
        "Qual regra?",
    ) is None


def test_compaction_keeps_a_condition_in_the_next_semantic_unit() -> None:
    rule = "1. A margem direita deve medir 2 cm."
    condition = "Esta medida aplica-se somente quando o trabalho for impresso."
    source = f"{rule}\n{condition}\n" + ("Observação geral. " * 160)

    document = _compact_document(
        {
            "id": 9004,
            "title": "Fixture normativa",
            "page_context": [{"page_number": 7, "page_text": source}],
        },
        "Qual a margem e em qual condição ela se aplica?",
    )

    assert document is not None
    text = document["evidence"][0]["text"]
    assert rule in text
    assert condition in text
    assert text in source


def test_compaction_preserves_a_numbered_item_without_synthetic_joining() -> None:
    items = [
        f"{number}. Requisito normativo {number} deve ser mantido."
        for number in range(1, 8)
    ]
    items[4] = "5. Exceção numérica deve ser mantida integralmente."
    source = "\n".join(items) + "\n" + ("Texto auxiliar. " * 150)

    document = _compact_document(
        {
            "id": 9005,
            "title": "Fixture de lista",
            "page_context": [{"page_number": 8, "page_text": source}],
        },
        "Exceção numérica",
    )

    assert document is not None
    text = document["evidence"][0]["text"]
    assert items[4] in text
    assert text in source
    assert estimated_token_count(text) <= 1_200


def test_compaction_keeps_a_late_table_row_intact() -> None:
    row = "| condição | impressão somente |"
    source = "| campo | valor |\n| margem | 2 cm |\n" + row + "\n" + (
        "| observação | auxiliar |\n" * 150
    )

    document = _compact_document(
        {
            "id": 9008,
            "title": "Fixture de tabela",
            "page_context": [{"page_number": 10, "page_text": source}],
        },
        "condição impressão",
    )

    assert document is not None
    text = document["evidence"][0]["text"]
    assert row in text
    assert text in source


def test_compaction_respects_token_budget_for_unbroken_text() -> None:
    source = "margem" + ("x" * 20_000)

    document = _compact_document(
        {
            "id": 9006,
            "title": "Fixture de orçamento",
            "page_context": [{"page_number": 9, "page_text": source}],
        },
        "Qual é a margem?",
    )

    assert document is not None
    text = document["evidence"][0]["text"]
    assert text in source
    assert estimated_token_count(text) <= 1_200
    assert document["omitted_content"]["characters"] > 0


def test_compaction_preserves_edition_page_and_numeric_source_text() -> None:
    source = "ABNT NBR 6023:2023 exige 2 cm na margem direita."
    document = _compact_document(
        {
            "id": 9007,
            "document_id": 77,
            "title": "ABNT NBR 6023",
            "version": "2023",
            "metadata": {"issuer": "ABNT"},
            "page_context": [{"page_number": 54, "page_text": source}],
        },
        "Qual a margem da ABNT NBR 6023?",
    )

    assert document is not None
    evidence = document["evidence"][0]
    assert evidence["page_number"] == 54
    assert evidence["version"] == "2023"
    assert evidence["text"] == source


def test_model_payload_exposes_omitted_content_to_grounding_layer() -> None:
    compact = _compact_document(
        {
            "id": 9009,
            "title": "Fixture de aviso",
            "page_context": [
                {
                    "page_number": 11,
                    "page_text": "margem " + ("texto auxiliar. " * 300),
                }
            ],
        },
        "margem",
    )

    assert compact is not None
    model_document = _model_document(compact)
    assert model_document["omitted_content"]["characters"] > 0
    assert model_document["evidence"]


def test_compaction_omission_reaches_grounding_as_a_partial_answer() -> None:
    question = "Qual a margem direita?"
    rule = "A margem direita deve medir 2 cm."
    source = rule + "\n" + ("Detalhe auxiliar. " * 180) + (
        "\n\nAplica-se somente quando o trabalho for impresso."
    )
    compact = _compact_document(
        {
            "id": 9011,
            "title": "Fixture de condição omitida",
            "page_context": [{"page_number": 1, "page_text": source}],
        },
        question,
    )
    assert compact is not None
    model_document = _model_document(compact)
    result = {
        "messages": [
            {"role": "user", "content": question},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "rag_document_search",
                        "args": {"question": question},
                    }
                ],
            },
            {
                "role": "tool",
                "name": "rag_document_search",
                "tool_call_id": "call-1",
                "content": json.dumps(
                    {
                        "status": "success",
                        "evidence_found": True,
                        "documents": [model_document],
                    },
                    ensure_ascii=False,
                ),
            },
            {"role": "assistant", "content": rule},
        ]
    }
    result["structured_response"] = AgentAnswer(
        answer=rule,
        evidence_ids=[model_document["evidence"][0]["evidence_id"]],
    )

    extracted = extract_agent_result(result)

    assert PARTIAL_LIMITATION in extracted.answer
    assert extracted.evidences[0]["omitted_content"]["characters"] > 0


def test_match_excerpt_preserves_the_original_text() -> None:
    text = "Referências devem ser organizadas conforme a norma vigente."

    assert _matched_text(text, "Como organizar as referências?") == text


def test_extract_agent_result_accepts_only_retrieved_evidence_ids() -> None:
    result = {
        "messages": [
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {
                                "evidence": [
                                    {
                                        "evidence_id": "document:42:page:4",
                                        "title": "ABNT NBR 6023",
                                        "page_number": 4,
                                        "text": "Referências devem ser organizadas.",
                                        "matched_text": (
                                            "Referências devem ser organizadas."
                                        ),
                                    }
                                ]
                            }
                        ],
                    }
                ),
            }
        ],
        "structured_response": AgentAnswer(
            answer="Referências devem ser organizadas.",
            evidence_ids=["document:42:page:4", "inventado", "document:42:page:4"],
        ),
    }

    extracted = extract_agent_result(result)

    assert extracted.answer == "Referências devem ser organizadas."
    assert [item["evidence_id"] for item in extracted.evidences] == [
        "document:42:page:4"
    ]


def test_extract_agent_result_hides_references_without_structured_selection() -> None:
    result = {
        "messages": [
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {
                                "evidence": [
                                    {
                                        "evidence_id": "document:42:page:4",
                                        "text": "Trecho original",
                                    }
                                ]
                            }
                        ],
                    }
                ),
            },
            {"role": "assistant", "content": "Resposta textual."},
        ]
    }

    extracted = extract_agent_result(result)

    assert extracted.answer == "Resposta textual."
    assert extracted.evidences == []


def test_structured_answer_without_selected_evidence_cannot_publish_available_text():
    result = {
        "messages": [
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {
                                "evidence": [
                                    {
                                        "evidence_id": "document:42:page:4",
                                        "text": "Referências devem ser organizadas.",
                                    }
                                ]
                            }
                        ],
                    }
                ),
            },
            {"role": "assistant", "content": "Referências devem ser organizadas."},
        ],
        "structured_response": AgentAnswer(
            answer="Referências devem ser organizadas.", evidence_ids=[]
        ),
    }

    extracted = extract_agent_result(result)

    assert "Não foi possível fundamentar" in extracted.answer
    assert extracted.evidences == []


def test_free_text_after_retrieval_cannot_be_published_as_normative_support():
    result = {
        "messages": [
            {"role": "user", "content": "Como organizar referências segundo a ABNT?"},
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {
                                "evidence": [
                                    {
                                        "evidence_id": "document:42:page:4",
                                        "text": "Referências devem ser organizadas.",
                                    }
                                ]
                            }
                        ],
                    }
                ),
            },
            {"role": "assistant", "content": "Referências devem ser organizadas."},
        ]
    }

    extracted = extract_agent_result(result)

    assert "Não foi possível fundamentar" in extracted.answer
    assert extracted.evidences == []


def test_extract_agent_result_links_relevant_evidence_without_model_ids() -> None:
    result = {
        "messages": [
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {
                                "document_id": 16,
                                "title": "Informação e documentação — Referências",
                                "standard_id": "abnt_nbr_6023",
                                "evidence": [
                                    {
                                        "evidence_id": "document:32:page:7",
                                        "page_number": 7,
                                        "text": (
                                            "Esta Norma estabelece os elementos "
                                            "a serem incluídos em referências de "
                                            "livros."
                                        ),
                                    },
                                    {
                                        "evidence_id": "document:32:page:11",
                                        "page_number": 11,
                                        "text": "Outro trecho sobre documentos.",
                                    },
                                ],
                            }
                        ],
                    }
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Esta Norma estabelece os elementos a serem incluídos "
                    "em referências de livros."
                ),
            },
        ]
    }

    extracted = extract_agent_result(result)

    assert [item["evidence_id"] for item in extracted.evidences] == [
        "document:32:page:7"
    ]


def test_extract_agent_result_rejects_semantically_unrelated_selected_evidence() -> (
    None
):
    result = {
        "messages": [
            {
                "role": "tool",
                "name": "rag_document_search",
                "content": json.dumps(
                    {
                        "status": "success",
                        "documents": [
                            {
                                "title": "ABNT NBR 14724 — Lombada",
                                "evidence": [
                                    {
                                        "evidence_id": "document:14724:page:1",
                                        "text": (
                                            "A lombada identifica o trabalho "
                                            "encadernado."
                                        ),
                                    }
                                ],
                            }
                        ],
                    }
                ),
            }
        ],
        "structured_response": AgentAnswer(
            answer=(
                "As margens e o espaçamento devem seguir a formatação geral "
                "do trabalho."
            ),
            evidence_ids=["document:14724:page:1"],
        ),
    }

    extracted = extract_agent_result(result)

    assert extracted.evidences == []
