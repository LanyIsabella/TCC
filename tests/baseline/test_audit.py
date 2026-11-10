import hashlib

from rag_eval.baseline.audit import audit_snapshot


def test_flags_are_enumerated_without_claiming_text_loss_or_quality():
    text = "Texto existente"
    state = {
        "documents": [
            {
                "document_id": 1,
                "standard_id": "abnt_nbr_6034",
                "standard_version": "2005",
            }
        ],
        "gold_variants": [
            {
                "is_active": True,
                "document_id": 1,
                "title": None,
                "version": None,
                "metadata": {"title": "Índice", "version": "2005"},
            }
        ],
        "pages": [
            {
                "document_id": 1,
                "physical_page": 5,
                "active_gold_extraction_id": 3,
                "extractions": [
                    {
                        "id": 9,
                        "extraction_id": 3,
                        "extracted_text": text,
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "structured_output": {"completion_unconfirmed": True},
                        "quality_metrics": {"requires_manual_review": True},
                    }
                ],
            }
        ],
    }
    queries = [
        {
            "references": [
                {"standard_id": "abnt_nbr_6034", "standard_label": "ABNT NBR 6034:2004"}
            ]
        }
    ]
    report = audit_snapshot(state, queries)
    assert len(report["active_manual_review_pages"]) == 1
    assert len(report["active_completion_unconfirmed_pages"]) == 1
    assert report["text_hash_mismatches"] == []
    assert report["edition_discrepancies"][0]["pdf_locator_edition"] == "2004"
    assert len(report["gold_metadata_discrepancies"]) == 2
    assert report["document_quality_validated"] is False


def test_missing_pdf_locator_cannot_create_an_edition_discrepancy():
    state = {
        "documents": [
            {
                "document_id": 1,
                "standard_id": "abnt_nbr_6034",
                "standard_version": "2005",
            }
        ],
        "pages": [],
        "gold_variants": [],
    }
    report = audit_snapshot(state, [{"references": []}])
    assert report["edition_discrepancies"] == []
