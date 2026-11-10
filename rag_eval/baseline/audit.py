"""Reverifica o snapshot preservado, sem consultar ou modificar produção."""

import argparse
import json
from pathlib import Path

from rag_eval.baseline.snapshot import text_sha256, write_json


def _page_flags(state) -> dict:
    report = {
        "text_hash_mismatches": [],
        "active_manual_review_pages": [],
        "active_completion_unconfirmed_pages": [],
    }
    for page in state["pages"]:
        for extraction in page["extractions"]:
            record = {
                "document_id": page["document_id"],
                "physical_page": page["physical_page"],
                "page_extraction_id": extraction["id"],
            }
            if (
                text_sha256(extraction.get("extracted_text"))
                != extraction["text_sha256"]
            ):
                report["text_hash_mismatches"].append(record)
            if extraction["extraction_id"] != page["active_gold_extraction_id"]:
                continue
            if (extraction.get("quality_metrics") or {}).get("requires_manual_review"):
                report["active_manual_review_pages"].append(record)
            if (extraction.get("structured_output") or {}).get(
                "completion_unconfirmed"
            ):
                report["active_completion_unconfirmed_pages"].append(record)
    return report


def _metadata_discrepancies(state) -> list:
    discrepancies = []
    for variant in state["gold_variants"]:
        if variant["is_active"]:
            for key in ("title", "version"):
                if variant.get(key) != variant["metadata"].get(key):
                    discrepancies.append(
                        {
                            "document_id": variant["document_id"],
                            "field": key,
                            "column": variant.get(key),
                            "metadata": variant["metadata"].get(key),
                        }
                    )
    return discrepancies


def _edition_discrepancies(state, queries) -> list:
    discrepancies = []
    labels = {
        ref["standard_id"]: ref["standard_label"].rsplit(":", 1)[-1]
        for query in queries
        for ref in query["references"]
    }
    for document in state["documents"]:
        edition = labels.get(document["standard_id"])
        if edition and edition != document["standard_version"]:
            discrepancies.append(
                {
                    "document_id": document["document_id"],
                    "standard_id": document["standard_id"],
                    "manifest_edition": document["standard_version"],
                    "pdf_locator_edition": edition,
                }
            )
    return discrepancies


def audit_snapshot(state, queries) -> dict:
    return {
        "document_quality_validated": False,
        **_page_flags(state),
        "gold_metadata_discrepancies": _metadata_discrepancies(state),
        "edition_discrepancies": _edition_discrepancies(state, queries),
        "interpretation": "Indicadores não comprovam perda de texto ou qualidade.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_snapshot(
        json.loads(args.snapshot.read_text(encoding="utf-8")),
        json.loads(args.queries.read_text(encoding="utf-8")),
    )
    write_json(args.output, report)
    print(
        json.dumps(
            {
                key: len(value)
                for key, value in report.items()
                if isinstance(value, list)
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
