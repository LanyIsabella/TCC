from data.gold_policy import assess_promotion


def page(**overrides):
    value = {
        "page_extraction_id": 1,
        "page_number": 1,
        "evaluation_status": "success",
        "evaluation_id": "eval-1",
        "evaluation_method": "page_image",
        "quality_score": 90,
        "quality_metrics": {
            "cer": 0.01,
            "wer": 0.02,
            "normalized_similarity": 0.98,
            "evaluation": {"requires_manual_review": False},
        },
        "result_fingerprint": "result-1",
        "evaluation_input_fingerprint": "result-1",
        "evaluation_config_fingerprint": "config-1",
        "evaluation_config": {"engine_version": "v1"},
    }
    value.update(overrides)
    return value


def test_success_alone_is_not_promotion_evidence():
    decision = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[{"evaluation_status": "success"}],
        expected_config_fingerprint="config-1",
    )
    assert decision.status == "blocked_provenance"
    assert not decision.eligible

    incomplete = assess_promotion(
        processing_status="processing",
        total_pages=1,
        successful_pages=0,
        pages=None,
    )
    assert incomplete.status == "awaiting_evaluation"

    blank = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(quality_score=None, quality_metrics={"blank_page": True})],
        expected_config_fingerprint="config-1",
    )
    assert blank.status == "approved"


def test_technical_eligibility_without_independent_validation_cannot_promote():
    decision = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[
            page(
                quality_metrics={
                    "cer": 0.01,
                    "wer": 0.02,
                    "normalized_similarity": 0.98,
                    "automatic_quality": {
                        "eligible": True,
                        "critical_failures": [],
                        "reference_status": "unavailable",
                        "reference_is_ground_truth": False,
                    },
                }
            )
        ],
        expected_config_fingerprint="config-1",
        alternatives_available=False,
    )

    assert decision.status == "quarantined"
    assert not decision.eligible


def test_review_signal_requests_automatic_retry_not_human_operation():
    pending = page(
        quality_metrics={"evaluation": {"requires_manual_review": True}}
    )
    decision = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[pending],
        expected_config_fingerprint="config-1",
    )
    assert decision.status == "retry_required"

    quarantined = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[pending],
        expected_config_fingerprint="config-1",
        alternatives_available=False,
    )
    assert quarantined.status == "quarantined"

    approved = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[pending],
        expected_config_fingerprint="config-1",
        human_reviews={
            1: [
                {
                    "review_id": "review-1",
                    "reviewer": "human",
                    "decision": "approved",
                    "result_fingerprint": "result-1",
                    "evaluation_id": "eval-1",
                    "evaluation_config_fingerprint": "config-1",
                    "criteria": {"fidelity": "checked"},
                    "provenance": {"source": "pilot"},
                }
            ]
        },
    )
    assert approved.status == "approved"

    evaluator_marked_review = page(
        evaluation_status="error",
        quality_metrics={"evaluation": {"requires_manual_review": True}},
    )
    approved_error = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[evaluator_marked_review],
        expected_config_fingerprint="config-1",
        human_reviews={
            1: [
                {
                    "review_id": "review-1",
                    "reviewer": "human",
                    "decision": "approved",
                    "result_fingerprint": "result-1",
                    "evaluation_id": "eval-1",
                    "evaluation_config_fingerprint": "config-1",
                    "criteria": {"fidelity": "checked"},
                    "provenance": {"source": "pilot"},
                }
            ]
        },
    )
    assert approved_error.status == "approved"


def test_fallback_and_stale_identity_are_not_quality_approval():
    fallback = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(evaluation_method="deterministic_fallback")],
        expected_config_fingerprint="config-1",
    )
    assert fallback.status == "technical_failure"

    stale = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(evaluation_input_fingerprint="old-result")],
        expected_config_fingerprint="config-1",
    )
    assert stale.status == "blocked_provenance"

    unknown_method = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(evaluation_method="legacy_manual")],
        expected_config_fingerprint="config-1",
    )
    assert unknown_method.status == "technical_failure"

    critical = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(quality_metrics={"critical_failure": True})],
        expected_config_fingerprint="config-1",
    )
    assert critical.status == "quality_rejected"

    technical = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(evaluation_status="error")],
        expected_config_fingerprint="config-1",
    )
    assert technical.status == "technical_failure"

    missing_automated_metrics = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[page(quality_metrics={"evaluation": {"requires_manual_review": False}})],
        expected_config_fingerprint="config-1",
    )
    assert missing_automated_metrics.status == "retry_required"


def test_metric_presence_does_not_prove_quality():
    decision = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[
            page(
                quality_metrics={
                    "cer": 0.95,
                    "wer": 0.9,
                    "normalized_similarity": 0.05,
                }
            )
        ],
        expected_config_fingerprint="config-1",
        alternatives_available=False,
    )

    assert decision.status == "quarantined"
    assert not decision.eligible


def test_native_or_peer_reference_is_not_ground_truth():
    for reference_type, reference_status in (
        ("native_pdf_text", "trusted"),
        ("peer_extraction", "trusted"),
        ("independent_reference", "corrupt"),
    ):
        decision = assess_promotion(
            processing_status="success",
            total_pages=1,
            successful_pages=1,
            pages=[
                page(
                    quality_metrics={
                        "cer": 0.01,
                        "wer": 0.02,
                        "normalized_similarity": 0.98,
                        "deterministic_validation": {
                            "status": "passed",
                            "reference_type": reference_type,
                            "reference_fingerprint": "reference-1",
                            "reference_status": reference_status,
                            "result_fingerprint": "result-1",
                        },
                    }
                )
            ],
            expected_config_fingerprint="config-1",
            alternatives_available=False,
        )

        assert decision.status == "quarantined"
        assert not decision.eligible


def test_failed_or_contradictory_deterministic_indicators_cannot_promote():
    failed = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[
            page(
                quality_metrics={
                    "cer": 0.95,
                    "deterministic_validation": {
                        "status": "failed",
                        "reference_type": "independent_reference",
                        "reference_fingerprint": "reference-1",
                        "reference_status": "trusted",
                        "result_fingerprint": "result-1",
                    },
                }
            )
        ],
        expected_config_fingerprint="config-1",
    )
    assert failed.status == "quality_rejected"

    contradictory = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[
            page(
                quality_metrics={
                    "cer": 0,
                    "wer": 0.8,
                    "normalized_similarity": 1,
                    "deterministic_validation": {
                        "status": "passed",
                        "reference_type": "independent_reference",
                        "reference_fingerprint": "reference-1",
                        "reference_status": "trusted",
                        "result_fingerprint": "result-1",
                    },
                }
            )
        ],
        expected_config_fingerprint="config-1",
        alternatives_available=False,
    )
    assert contradictory.status == "quarantined"


def test_independent_validated_metrics_can_promote_without_a_numeric_threshold():
    decision = assess_promotion(
        processing_status="success",
        total_pages=1,
        successful_pages=1,
        pages=[
            page(
                quality_metrics={
                    "cer": 0.01,
                    "wer": 0.02,
                    "normalized_similarity": 0.98,
                    "deterministic_validation": {
                        "status": "passed",
                        "reference_type": "independent_reference",
                        "reference_fingerprint": "reference-1",
                        "reference_status": "trusted",
                        "result_fingerprint": "result-1",
                    },
                }
            )
        ],
        expected_config_fingerprint="config-1",
    )

    assert decision.status == "approved"
    assert decision.eligible
