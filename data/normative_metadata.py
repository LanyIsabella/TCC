"""Small, deterministic model for normative-document identity metadata."""

from __future__ import annotations

import re
from typing import Any


def normalize_standard_identifier(value: Any) -> dict[str, str | None]:
    """Return a stable identity without treating a filename as evidence."""
    text = " ".join(str(value or "").strip().replace("_", " ").split())
    edition_match = re.search(r":\s*(\d{4})$", text)
    edition = edition_match.group(1) if edition_match else None
    body = text[: edition_match.start()].strip() if edition_match else text
    body = re.sub(r"^ABNT\s+", "", body, flags=re.IGNORECASE).upper()
    if not body:
        return {"issuer": None, "code": None, "edition": edition, "canonical": None}
    if body.startswith("NBR "):
        issuer, code, canonical = "ABNT", body, f"ABNT {body}"
    elif re.match(r"^(?:ISO/IEC|ISO|IEC)\s+", body):
        issuer = "ISO/IEC" if body.startswith("ISO/IEC ") else body.split()[0]
        code = canonical = body
    else:
        return {"issuer": None, "code": body, "edition": edition, "canonical": body}
    return {
        "issuer": issuer,
        "code": code,
        "edition": edition,
        "canonical": canonical,
    }


def _date(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    match = re.fullmatch(r"(\d{2})[-/](\d{2})[-/](\d{4})", text)
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" if match else text


def _provenance(value: Any, source_layer: str, source_field: str) -> dict[str, str]:
    return {
        "status": "direct" if value not in (None, "") else "unknown",
        "source_layer": source_layer,
        "source_field": source_field,
    }


def build_normative_metadata(
    raw: dict[str, Any], *, source_layer: str
) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    identity = normalize_standard_identifier(raw.get("id") or raw.get("standard_id"))
    edition = str(raw.get("version") or identity["edition"] or "").strip() or None
    title = raw.get("title")
    title = str(title).strip() if title not in (None, "") else None
    publication = _date(raw.get("publication_date"))
    effective = _date(raw.get("effective_date"))
    metadata = {
        "schema_version": "normative-metadata-v1",
        "identity": identity,
        "title": title,
        "edition": edition,
        "issuer": raw.get("issuer") or identity["issuer"],
        "document_type": raw.get("document_type"),
        "status": raw.get("status"),
        "dates": {
            "publication": publication,
            "effective": effective,
        },
        "provenance": {
            "identity": _provenance(
                raw.get("id") or raw.get("standard_id"), source_layer, "id"
            ),
            "title": _provenance(title, source_layer, "title"),
            "edition": _provenance(edition, source_layer, "version"),
            "issuer": _provenance(
                raw.get("issuer") or identity["issuer"], source_layer, "issuer"
            ),
            "dates.publication": _provenance(
                publication, source_layer, "publication_date"
            ),
            "dates.effective": _provenance(effective, source_layer, "effective_date"),
        },
    }
    return metadata


def metadata_conflicts(*layers: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    for field in ("title", "version", "edition", "issuer"):
        values = {
            str(layer.get(field)).strip()
            for layer in layers
            if layer.get(field) not in (None, "")
        }
        if len(values) > 1:
            conflicts.append(field)
    return conflicts
