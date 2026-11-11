"""Deterministic, auditable eligibility rules for promoting Silver to Gold."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from typing import Any

PROMOTION_STATES = (
    "approved",
    "awaiting_evaluation",
    "awaiting_human_review",
    "retry_required",
    "quarantined",
    "quality_rejected",
    "blocked_provenance",
    "technical_failure",
)
TRUSTED_EVALUATION_METHODS = {"page_image", "pdf_reader_text"}
TRUSTED_DETERMINISTIC_REFERENCES = {"human_verified", "independent_reference"}
DETERMINISTIC_METRIC_KEYS = ("cer", "wer", "normalized_similarity")


@dataclass(frozen=True)
class PromotionDecision:
    status: str
    eligible: bool
    reasons: tuple[str, ...]


def _review_identity_matches(page: dict[str, Any], review: dict[str, Any]) -> bool:
    return all(
        (
            review.get("result_fingerprint") == page.get("result_fingerprint"),
            str(review.get("evaluation_id")) == str(page.get("evaluation_id")),
            review.get("evaluation_config_fingerprint")
            == page.get("evaluation_config_fingerprint"),
        )
    )


def _review_has_audit_fields(review: dict[str, Any]) -> bool:
    return all(
        (
            review.get("review_id"),
            review.get("reviewer"),
            isinstance(review.get("criteria"), dict),
            review.get("criteria"),
            isinstance(review.get("provenance"), dict),
            review.get("provenance"),
        )
    )


def _review_for_page(
    page: dict[str, Any], human_reviews: dict[Any, Iterable[dict[str, Any]]]
) -> tuple[bool, str | None]:
    for review in human_reviews.get(page.get("page_extraction_id"), ()):
        if not _review_identity_matches(page, review) or not _review_has_audit_fields(
            review
        ):
            continue
        if review.get("decision") == "approved":
            return True, None
        if review.get("decision") == "rejected":
            return False, "human_review_rejected"
    return False, None


def _page_metrics(page: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    metrics = page.get("quality_metrics") or {}
    metrics = metrics if isinstance(metrics, dict) else {}
    evaluation = metrics.get("evaluation") or {}
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    blank_page = bool(metrics.get("blank_page") or evaluation.get("blank_page"))
    return metrics, evaluation, blank_page


def _page_status_decision(
    page: dict[str, Any],
    evaluation: dict[str, Any],
    reviewed: bool,
    review_reason: str | None,
    alternatives_available: bool,
) -> tuple[str | None, str | None]:
    status = page.get("evaluation_status")
    page_number = page.get("page_number")
    if status in ("pending", "reference_unavailable"):
        return "awaiting_evaluation", f"page_{page_number}:evaluation_pending"
    if status == "success":
        return None, None
    if review_reason == "human_review_rejected":
        return "quality_rejected", f"page_{page_number}:human_review_rejected"
    if evaluation.get("requires_manual_review") and reviewed:
        return "approved", None
    if evaluation.get("requires_manual_review"):
        return _uncertainty_decision(page_number, alternatives_available)
    return "technical_failure", f"page_{page_number}:evaluation_failed"


def _uncertainty_decision(
    page_number: Any, alternatives_available: bool
) -> tuple[str, str]:
    if alternatives_available:
        return "retry_required", f"page_{page_number}:automatic_retry_required"
    return "quarantined", f"page_{page_number}:no_trusted_alternative"


def _metric_values_are_valid(metrics: dict[str, Any], present: list[str]) -> bool:
    for key in present:
        value = metrics[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not isfinite(value) or value < 0:
            return False
        if key == "normalized_similarity" and value > 1:
            return False
    return True


def _metric_values_are_consistent(metrics: dict[str, Any]) -> bool:
    similarity = metrics.get("normalized_similarity")
    if similarity == 1 and any(metrics.get(key, 0) != 0 for key in ("cer", "wer")):
        return False
    if metrics.get("cer") == 0 and similarity is not None and similarity != 1:
        return False
    return True


def _validation_is_trusted(page: dict[str, Any], metrics: dict[str, Any]) -> str:
    validation = metrics.get("deterministic_validation")
    if not isinstance(validation, dict):
        return "unverified"
    status = validation.get("status")
    if status == "failed":
        return "failed"
    if status != "passed":
        return "unverified"
    if validation.get("reference_type") not in TRUSTED_DETERMINISTIC_REFERENCES:
        return "unverified"
    if (
        not validation.get("reference_fingerprint")
        or validation.get("reference_status") != "trusted"
    ):
        return "unverified"
    if (
        "result_fingerprint" in validation
        and validation.get("result_fingerprint") != page.get("result_fingerprint")
    ):
        return "mismatch"
    return "trusted"


def _deterministic_metrics_decision(
    page: dict[str, Any],
    metrics: dict[str, Any],
    alternatives_available: bool,
) -> tuple[str, str | None]:
    page_number = page.get("page_number")
    present = [key for key in DETERMINISTIC_METRIC_KEYS if key in metrics]
    if not present or not _metric_values_are_valid(metrics, present):
        return _uncertainty_decision(page_number, alternatives_available)
    if not _metric_values_are_consistent(metrics):
        return _uncertainty_decision(page_number, alternatives_available)
    validation = _validation_is_trusted(page, metrics)
    if validation == "failed":
        return "quality_rejected", f"page_{page_number}:deterministic_quality_failure"
    if validation == "mismatch":
        return "blocked_provenance", f"page_{page_number}:deterministic_result_mismatch"
    if validation != "trusted":
        return _uncertainty_decision(page_number, alternatives_available)
    return "approved", None


def _page_identity_decision(
    page: dict[str, Any], expected_config: str, blank_page: bool
) -> tuple[str | None, str | None]:
    page_number = page.get("page_number")
    identity_missing = any(
        (
            not page.get("evaluation_id"),
            not page.get("evaluation_method"),
            page.get("quality_score") is None and not blank_page,
            page.get("evaluation_input_fingerprint") != page.get("result_fingerprint"),
            page.get("evaluation_config_fingerprint") is None,
            page.get("evaluation_config_fingerprint") != expected_config,
        )
    )
    if identity_missing:
        return "blocked_provenance", f"page_{page_number}:evaluation_identity_untrusted"
    configuration = page.get("evaluation_config")
    if (
        not isinstance(configuration, dict)
        or configuration.get("historical_configuration") == "unknown"
    ):
        return (
            "blocked_provenance",
            f"page_{page_number}:evaluation_configuration_unknown",
        )
    method = page.get("evaluation_method")
    if method == "deterministic_fallback":
        return "technical_failure", f"page_{page_number}:deterministic_fallback"
    if method not in TRUSTED_EVALUATION_METHODS:
        return "technical_failure", f"page_{page_number}:unknown_evaluation_method"
    if page.get("evaluation_error"):
        return "technical_failure", f"page_{page_number}:evaluation_error"
    return None, None


def _page_quality_decision(
    page: dict[str, Any],
    metrics: dict[str, Any],
    evaluation: dict[str, Any],
    blank_page: bool,
    reviewed: bool,
    review_reason: str | None,
    alternatives_available: bool,
) -> tuple[str, str | None]:
    page_number = page.get("page_number")
    if metrics.get("critical_failure") or evaluation.get("critical_failure"):
        return "quality_rejected", f"page_{page_number}:critical_quality_failure"
    if evaluation.get("requires_manual_review") and not reviewed:
        return _uncertainty_decision(page_number, alternatives_available)
    if review_reason == "human_review_rejected":
        return "quality_rejected", f"page_{page_number}:human_review_rejected"
    if reviewed:
        return "approved", None
    if blank_page:
        return "approved", None
    return _deterministic_metrics_decision(page, metrics, alternatives_available)


def _page_decision(
    page: dict[str, Any],
    expected_config: str,
    human_reviews: dict[Any, Iterable[dict[str, Any]]],
    alternatives_available: bool,
) -> tuple[str, str | None]:
    metrics, evaluation, blank_page = _page_metrics(page)
    reviewed, review_reason = _review_for_page(page, human_reviews)
    state, reason = _page_status_decision(
        page, evaluation, reviewed, review_reason, alternatives_available
    )
    if state is not None:
        return state, reason
    state, reason = _page_identity_decision(page, expected_config, blank_page)
    if state is not None:
        return state, reason
    return _page_quality_decision(
        page,
        metrics,
        evaluation,
        blank_page,
        reviewed,
        review_reason,
        alternatives_available,
    )


def _aggregate_decision(states: list[str], reasons: list[str]) -> PromotionDecision:
    for state in (
        "quality_rejected",
        "technical_failure",
        "blocked_provenance",
        "quarantined",
        "retry_required",
        "awaiting_human_review",
        "awaiting_evaluation",
    ):
        if state in states:
            return PromotionDecision(state, False, tuple(reasons))
    return PromotionDecision("approved", True, tuple(reasons))


def _promotion_precondition(
    processing_status: str,
    total_pages: int,
    successful_pages: int,
    pages: list[dict[str, Any]] | None,
    expected_config_fingerprint: str | None,
) -> PromotionDecision | None:
    if processing_status in {"pending", "processing"}:
        return PromotionDecision(
            "awaiting_evaluation", False, ("processing_incomplete",)
        )
    if processing_status != "success":
        return PromotionDecision(
            "technical_failure", False, ("processing_not_success",)
        )
    if total_pages <= 0 or successful_pages != total_pages:
        return PromotionDecision("awaiting_evaluation", False, ("pages_incomplete",))
    if pages is None or len(pages) != total_pages:
        return PromotionDecision("awaiting_evaluation", False, ("evaluation_missing",))
    if expected_config_fingerprint is None:
        return PromotionDecision(
            "blocked_provenance", False, ("current_evaluation_identity_unknown",)
        )
    return None


def assess_promotion(
    *,
    processing_status: str,
    total_pages: int,
    successful_pages: int,
    pages: list[dict[str, Any]] | None,
    expected_config_fingerprint: str | None = None,
    human_reviews: dict[Any, Iterable[dict[str, Any]]] | None = None,
    alternatives_available: bool = True,
) -> PromotionDecision:
    """Evaluate promotion evidence without inventing quality thresholds."""
    precondition = _promotion_precondition(
        processing_status,
        total_pages,
        successful_pages,
        pages,
        expected_config_fingerprint,
    )
    if precondition is not None:
        return precondition

    reviews = human_reviews or {}
    states: list[str] = []
    reasons: list[str] = []
    for page in pages:
        state, reason = _page_decision(
            page,
            expected_config_fingerprint,
            reviews,
            alternatives_available,
        )
        states.append(state)
        if reason:
            reasons.append(reason)
    return _aggregate_decision(states, reasons)
