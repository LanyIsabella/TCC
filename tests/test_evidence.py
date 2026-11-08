"""Testes do contrato de rastreabilidade entre resposta e RAG."""

import json

from src.app.evidence import AgentAnswer, extract_agent_result
from src.app.tools.rag_search import _compact_document, _matched_text


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
                                        "text": "Trecho original",
                                        "matched_text": "Trecho original",
                                    }
                                ]
                            }
                        ],
                    }
                ),
            }
        ],
        "structured_response": AgentAnswer(
            answer="Resposta fundamentada.",
            evidence_ids=["document:42:page:4", "inventado", "document:42:page:4"],
        ),
    }

    extracted = extract_agent_result(result)

    assert extracted.answer == "Resposta fundamentada."
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
                    "Para montar referências bibliográficas de livros, siga a "
                    "ABNT NBR 6023 e informe os elementos essenciais."
                ),
            },
        ]
    }

    extracted = extract_agent_result(result)

    assert [item["evidence_id"] for item in extracted.evidences] == [
        "document:32:page:7"
    ]


def test_extract_agent_result_rejects_semantically_unrelated_selected_evidence(
) -> None:
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


def test_extract_agent_result_rejects_matched_text_without_semantic_support() -> None:
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
                                "title": "ABNT NBR 12225 — Lombada",
                                "evidence": [
                                    {
                                        "evidence_id": "document:12225:page:5",
                                        "text": (
                                            "A lombada identifica o trabalho "
                                            "encadernado."
                                        ),
                                        "matched_text": "margens e espaçamento",
                                    }
                                ],
                            }
                        ],
                    }
                ),
            }
        ],
        "structured_response": AgentAnswer(
            answer="As margens e o espaçamento devem seguir a formatação geral.",
            evidence_ids=["document:12225:page:5"],
        ),
    }

    assert extract_agent_result(result).evidences == []


def test_compact_document_prefers_normative_page_over_summary() -> None:
    document = _compact_document(
        {
            "id": 7,
            "document_id": 7,
            "title": "Trabalhos acadêmicos — Apresentação",
            "page_context": [
                {
                    "page_number": 3,
                    "direct_match": True,
                    "page_text": "Sumário\n\n4 Formatação e margens",
                },
                {
                    "page_number": 11,
                    "direct_match": False,
                    "page_text": (
                        "As margens devem ser: esquerda e superior de 3 cm, "
                        "e direita e inferior de 2 cm."
                    ),
                },
            ],
        },
        "Quais são as regras de formatação de um TCC?",
    )

    assert document is not None
    assert document["evidence"][0]["page_number"] == 11
    assert "As margens devem ser" in document["evidence"][0]["text"]
