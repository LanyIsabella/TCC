from data.extraction_quality import assess_candidate, select_page_candidate


def candidate(extractor, text, **extra):
    return {
        "extractor": extractor,
        "text": text,
        "processing_status": "success",
        **extra,
    }


def test_clean_page_is_eligible_but_without_reference_is_consistency_only():
    result = assess_candidate(candidate("docling", "## 1 Escopo\n- item 1\nTabela 1"))
    assert result["eligible"] is True
    assert result["reference_status"] == "unavailable"
    assert result["critical_failures"] == []


def test_completed_plausible_text_is_selectable_but_not_fidelity_evidence():
    plausible_error = candidate(
        "glm_ocr",
        "ABNT NBR 6028:2021\n\nAABNT chama a atenção para requisitos",
    )

    assessment = assess_candidate(plausible_error)
    selection = select_page_candidate(4, [plausible_error])

    assert assessment["eligible"] is True
    assert assessment["reference_status"] == "unavailable"
    assert assessment["reference_is_ground_truth"] is False
    assert selection["status"] == "selected"
    assert selection["reason"] == "deterministic_integrity_rank"


def test_pua_and_replacement_characters_are_reported_as_suspect():
    result = assess_candidate(candidate("pdf_reader", "A\ue000 B\ufffd C"))
    assert result["indicators"]["pua_count"] == 1
    assert result["indicators"]["replacement_count"] == 1
    assert "unicode_corruption" in result["warnings"]


def test_empty_and_truncated_candidates_are_not_eligible():
    empty = assess_candidate(candidate("glm_ocr", ""))
    truncated = assess_candidate(
        candidate(
            "glm_ocr",
            "texto",
            structured_output={"completion_unconfirmed": True},
        )
    )
    assert empty["eligible"] is False
    assert "empty_text" in empty["critical_failures"]
    assert truncated["eligible"] is False
    assert "truncated_output" in truncated["critical_failures"]


def test_independent_reference_is_explicit_and_does_not_use_native_implicitly():
    result = assess_candidate(
        candidate("docling", "ABNT NBR 6023:2025"),
        independent_reference="ABNT NBR 6023:2025",
    )
    assert result["reference_status"] == "independent"
    assert result["reference_is_ground_truth"] is False


def test_selection_quarantines_two_identical_candidates_without_reference():
    result = select_page_candidate(
        6,
        [candidate("docling", "mesmo erro"), candidate("glm_ocr", "mesmo erro")],
    )
    assert result["status"] == "quarantined"
    assert result["reason"] == "peer_agreement_without_reference"


def test_selection_can_choose_different_extractors_per_page():
    page_one = select_page_candidate(
        1,
        [candidate("pdf_reader", "texto limpo"), candidate("glm_ocr", "\ue000")],
    )
    page_two = select_page_candidate(
        2,
        [candidate("pdf_reader", ""), candidate("docling", "## Título\n- item")],
    )
    assert page_one["status"] == "selected"
    assert page_one["extractor"] == "pdf_reader"
    assert page_two["status"] == "selected"
    assert page_two["extractor"] == "docling"


def test_legitimate_blank_page_requires_explicit_blank_observation():
    result = assess_candidate(
        candidate("glm_ocr", "", blank_page=True),
    )
    assert result["eligible"] is True
    assert result["indicators"]["blank_page"] is True


def test_only_technical_failures_request_retry():
    result = select_page_candidate(
        8,
        [
            candidate("docling", "", processing_status="error"),
            candidate("glm_ocr", "", processing_status="processing"),
        ],
    )
    assert result["status"] == "retry_required"


def test_fallback_output_keeps_extractor_identity_but_cannot_be_selected():
    result = select_page_candidate(
        1,
        [
            candidate(
                "glm_ocr",
                "texto nativo usado como fallback",
                structured_output={
                    "fallback": "pdf_reader",
                    "error_type": "HTTPError",
                },
            ),
            candidate("docling", "texto Docling"),
        ],
    )

    glm = next(
        item for item in result["candidates"] if item["extractor"] == "glm_ocr"
    )
    assert glm["eligible"] is False
    assert "technical_fallback" in glm["critical_failures"]
    assert result["extractor"] == "docling"


def test_structural_indicators_cover_tables_lists_and_normative_numbers():
    result = assess_candidate(
        candidate(
            "docling",
            "## 4 Regras\n- a) item\n| coluna | valor |\nABNT NBR 6023:2025",
        )
    )
    indicators = result["indicators"]
    assert indicators["heading_count"] == 1
    assert indicators["list_marker_count"] >= 1
    assert indicators["table_marker_count"] >= 1
    assert indicators["normative_reference_count"] == 1
    assert indicators["numeric_token_count"] >= 2


def test_selection_records_pairwise_divergence_without_treating_it_as_truth():
    result = select_page_candidate(
        9,
        [candidate("docling", "um dois"), candidate("glm_ocr", "um três")],
    )
    assert result["divergence"][0]["left"] == "docling"
    assert 0 <= result["divergence"][0]["normalized_similarity"] <= 1
