"""Medições automáticas de localização; não substituem julgamento humano."""

import re
from typing import Any


def standard_key(value: str) -> str:
    match = re.search(r"nbr[_\s]+(\d+)", value, flags=re.IGNORECASE)
    return match[1] if match else value.casefold()


def normalized(text: str) -> str:
    return " ".join(text.split())


def _page_contexts(traces) -> dict[tuple[str, int], str]:
    before: dict[tuple[str, int], str] = {}
    for trace in traces:
        for doc in trace["documents"]:
            key = standard_key(str(doc.get("standard_id", "")))
            for page in doc.get("page_context", []):
                before[key, page["page_number"]] = normalized(page["page_text"])
    return before


def _retention(references, before, after) -> dict[str, Any]:
    page_matches = 0
    retained = 0
    comparable = 0
    for ref in references:
        key = (standard_key(ref["standard_id"]), ref["physical_page"])
        page_matches += key in after
        excerpt = normalized(ref["source_excerpt"])
        if excerpt and excerpt in before.get(key, ""):
            comparable += 1
            retained += excerpt in after.get(key, "")
    return {
        "page_locator_coverage": page_matches / len(references) if references else None,
        "literal_excerpts_comparable": comparable,
        "literal_excerpt_retention": retained / comparable if comparable else None,
    }


def locator_metrics(
    case: dict[str, Any],
    traces: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    references = case.get("references", [])
    expected = {standard_key(ref["standard_id"]) for ref in references}
    documents = payload.get("documents", [])
    found = {standard_key(str(doc.get("standard_id", ""))) for doc in documents}
    after = {
        (
            standard_key(str(doc.get("standard_id", ""))),
            evidence["page_number"],
        ): normalized(evidence["text"])
        for doc in documents
        for evidence in doc.get("evidence", [])
        if evidence.get("page_number") is not None
    }
    return {
        "reference_status": case.get("reference_status"),
        "human_validated": False,
        "document_locator_coverage": len(expected & found) / len(expected)
        if expected
        else None,
        **_retention(references, _page_contexts(traces), after),
        "factual_correctness": None,
        "claim_support": None,
    }
