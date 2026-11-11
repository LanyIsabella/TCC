"""Deterministic, auditable page-quality indicators and candidate selection."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

_NORMATIVE_REFERENCE = re.compile(
    r"\b(?:ABNT\s+)?NBR(?:\s+(?:ISO(?:/IEC)?|IEC))?\s+\d{3,5}(?::\s*\d{4})?\b",
    re.IGNORECASE,
)
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*+]\s+|[a-z]\)\s+|\d+[.)]\s+)")
_HEADING = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|\d+(?:\.\d+)*\s+\S)")
_TABLE = re.compile(r"(?m)^\s*\|.+\|\s*$")
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:\s*%|\s*[º°])?")


def _indicators(text: str, *, blank_page: bool) -> dict[str, Any]:
    characters = list(text)
    pua_count = sum(
        "PRIVATE USE" in unicodedata.name(character, "")
        or 0xE000 <= ord(character) <= 0xF8FF
        for character in characters
    )
    replacement_count = text.count("\ufffd")
    control_count = sum(
        unicodedata.category(character) == "Cc" and character not in "\n\r\t"
        for character in characters
    )
    words = text.split()
    return {
        "character_count": len(characters),
        "word_count": len(words),
        "line_count": len(text.splitlines()),
        "pua_count": pua_count,
        "pua_ratio": pua_count / max(len(characters), 1),
        "replacement_count": replacement_count,
        "control_count": control_count,
        "heading_count": len(_HEADING.findall(text)),
        "list_marker_count": len(_LIST_MARKER.findall(text)),
        "table_marker_count": len(_TABLE.findall(text)),
        "normative_reference_count": len(_NORMATIVE_REFERENCE.findall(text)),
        "numeric_token_count": len(_NUMBER.findall(text)),
        "blank_page": blank_page,
    }


def _critical_failures(
    candidate: dict[str, Any], text: str, indicators: dict[str, Any]
) -> list[str]:
    failures: list[str] = []
    if candidate.get("processing_status") not in (None, "success"):
        failures.append("technical_failure")
    if (candidate.get("structured_output") or {}).get("fallback"):
        failures.append("technical_fallback")
    if not text.strip() and not indicators["blank_page"]:
        failures.append("empty_text")
    if (candidate.get("structured_output") or {}).get("completion_unconfirmed"):
        failures.append("truncated_output")
    if indicators["pua_ratio"] > 0.01:
        failures.append("suspicious_unicode_density")
    return failures


def _consistency(
    independent_reference: str | None, text: str
) -> tuple[str, bool, dict[str, Any] | None]:
    if independent_reference is None:
        return "unavailable", False, None
    from data.rag_pipeline import deterministic_metrics

    return "independent", False, deterministic_metrics(independent_reference, text)


def assess_candidate(
    candidate: dict[str, Any],
    *,
    independent_reference: str | None = None,
) -> dict[str, Any]:
    text = str(candidate.get("text") or candidate.get("markdown") or "")
    blank_page = bool(candidate.get("blank_page"))
    indicators = _indicators(text, blank_page=blank_page)
    failures = _critical_failures(candidate, text, indicators)
    warnings: list[str] = []
    if (
        indicators["pua_count"]
        or indicators["replacement_count"]
        or indicators["control_count"]
    ):
        warnings.append("unicode_corruption")
    reference_status, reference_is_ground_truth, consistency = _consistency(
        independent_reference, text
    )
    return {
        "page_extraction_id": candidate.get("page_extraction_id"),
        "execution_id": candidate.get("execution_id"),
        "extractor": candidate.get("extractor"),
        "eligible": not failures,
        "critical_failures": failures,
        "warnings": warnings,
        "indicators": indicators,
        "reference_status": reference_status,
        "reference_is_ground_truth": reference_is_ground_truth,
        "consistency_metrics": consistency,
    }


def _rank(assessment: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
    indicators = assessment["indicators"]
    return (
        int(assessment["eligible"]),
        -len(assessment["critical_failures"]),
        -indicators["pua_count"],
        -indicators["replacement_count"],
        indicators["heading_count"]
        + indicators["list_marker_count"]
        + indicators["table_marker_count"],
        indicators["word_count"],
    )


def _same_peer_text(
    candidates: list[dict[str, Any]], eligible: list[dict[str, Any]]
) -> bool:
    extractors = {item["extractor"] for item in eligible}
    texts = {
        str(candidate.get("text") or candidate.get("markdown") or "")
        for candidate in candidates
        if candidate.get("extractor") in extractors
    }
    return len(texts) == 1


def _divergence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [
        (
            candidate.get("extractor"),
            str(candidate.get("text") or candidate.get("markdown") or ""),
        )
        for candidate in candidates
    ]
    return [
        {
            "left": left_name,
            "right": right_name,
            "normalized_similarity": round(
                SequenceMatcher(None, left, right).ratio(), 6
            ),
        }
        for index, (left_name, left) in enumerate(values)
        for right_name, right in values[index + 1 :]
    ]


def _quarantine_reason(
    eligible: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    independent_reference: str | None,
) -> str | None:
    if not eligible:
        return "no_eligible_candidate"
    if (
        len(eligible) > 1
        and independent_reference is None
        and _same_peer_text(candidates, eligible)
    ):
        return "peer_agreement_without_reference"
    ranked = sorted(eligible, key=_rank, reverse=True)
    if (
        independent_reference is None
        and len(ranked) > 1
        and _rank(ranked[0]) == _rank(ranked[1])
    ):
        return "insufficient_reference"
    return None


def _retryable(assessments: list[dict[str, Any]], reason: str | None) -> bool:
    if reason != "no_eligible_candidate" or not assessments:
        return False
    retryable = {"technical_failure", "technical_fallback", "truncated_output"}
    return all(set(item["critical_failures"]) & retryable for item in assessments)


def select_page_candidate(
    page_number: int,
    candidates: list[dict[str, Any]],
    *,
    independent_reference: str | None = None,
) -> dict[str, Any]:
    assessments = [
        assess_candidate(candidate, independent_reference=independent_reference)
        for candidate in candidates
    ]
    eligible = [assessment for assessment in assessments if assessment["eligible"]]
    base = {
        "page_number": page_number,
        "candidates": assessments,
        "divergence": _divergence(candidates),
        "reference_status": (
            "independent" if independent_reference is not None else "unavailable"
        ),
    }
    reason = _quarantine_reason(eligible, candidates, independent_reference)
    if reason:
        return {
            **base,
            "status": (
                "retry_required"
                if _retryable(assessments, reason)
                else "quarantined"
            ),
            "reason": reason,
            "extractor": None,
        }
    ranked = sorted(eligible, key=_rank, reverse=True)
    selected = ranked[0]
    return {
        **base,
        "status": "selected",
        "reason": (
            "independent_reference"
            if independent_reference
            else "deterministic_integrity_rank"
        ),
        "extractor": selected["extractor"],
        "selected_page_extraction_id": selected["page_extraction_id"],
    }
