from rag_eval.baseline.metrics import locator_metrics


def test_retention_is_only_scored_when_source_excerpt_was_in_retrieved_text():
    case = {
        "reference_status": "pending_human_review",
        "references": [
            {
                "standard_id": "abnt_nbr_6028",
                "physical_page": 4,
                "source_excerpt": "regra no final",
            }
        ],
    }
    doc = {
        "standard_id": "abnt_nbr_6028",
        "page_context": [
            {
                "page_number": 4,
                "page_text": "texto anterior; regra no final",
            }
        ],
    }
    payload = {
        "documents": [
            {
                "standard_id": "abnt_nbr_6028",
                "evidence": [
                    {
                        "page_number": 4,
                        "text": "texto anterior",
                    }
                ],
            }
        ]
    }
    result = locator_metrics(case, [{"documents": [doc]}], payload)
    assert result["document_locator_coverage"] == 1
    assert result["page_locator_coverage"] == 1
    assert result["literal_excerpt_retention"] == 0
    assert result["human_validated"] is False
    assert result["claim_support"] is None
    doc["page_context"][0]["page_text"] = "extração distinta do original"
    assert (
        locator_metrics(case, [{"documents": [doc]}], payload)[
            "literal_excerpt_retention"
        ]
        is None
    )


def test_absent_reference_is_not_scored_as_perfect_recall():
    result = locator_metrics({"references": []}, [], {"documents": []})
    assert result["document_locator_coverage"] is None
    assert result["page_locator_coverage"] is None
