"""Avalia extrações existentes contra transcrições humanas declaradas."""

import argparse
import json
from pathlib import Path
from typing import Any

from data.rag_pipeline import deterministic_metrics


def review_template(state: dict[str, Any]) -> list[dict[str, Any]]:
    hashes = {doc["document_id"]: doc["sha256"] for doc in state["documents"]}
    return [
        {
            "document_id": page["document_id"],
            "standard_id": page["standard_id"],
            "document_sha256": hashes[page["document_id"]],
            "physical_page": page["physical_page"],
            "printed_page_confirmed": None,
            "transcription": None,
            "transcription_origin": None,
            "reviewer": None,
            "reviewed_at": None,
            "review_status": "pending_human_review",
        }
        for page in state["pages"]
    ]


def _attested(review: dict) -> bool:
    return all(
        (
            isinstance(review.get("transcription"), str),
            review.get("transcription_origin") == "human",
            bool(review.get("reviewer")),
            bool(review.get("reviewed_at")),
        )
    )


def checked_reviews(state, reviews) -> dict[tuple[int, int], dict]:
    known = {
        (row["document_id"], row["physical_page"]): row
        for row in review_template(state)
    }
    result = {}
    for review in reviews:
        key = (review["document_id"], review["physical_page"])
        if key not in known or key in result:
            raise ValueError("Página desconhecida ou revisão duplicada")
        if review.get("document_sha256") != known[key]["document_sha256"]:
            raise ValueError("Revisão corresponde a outro documento original")
        if review["review_status"] == "reviewed" and not _attested(review):
            raise ValueError(
                "Transcrição exige origem humana e autoria/data declaradas"
            )
        if review["review_status"] not in {"reviewed", "pending_human_review"}:
            raise ValueError("Estado de revisão desconhecido")
        result[key] = review
    return result


def evaluate_pages(state, reviews) -> list[dict[str, Any]]:
    references = checked_reviews(state, reviews)
    results = []
    for page in state["pages"]:
        review = references.get((page["document_id"], page["physical_page"]))
        for extraction in page["extractions"]:
            row = {
                "document_id": page["document_id"],
                "physical_page": page["physical_page"],
                "extraction_id": extraction.get("id"),
                "extractor": extraction.get("extractor"),
                "status": "pending_human_review",
                "cer": None,
                "wer": None,
            }
            if review and review["review_status"] == "reviewed":
                metrics = deterministic_metrics(
                    review["transcription"],
                    extraction.get("extracted_text") or "",
                )
                row.update(
                    status="scored_against_attested_human_reference",
                    cer=metrics["cer"],
                    wer=metrics["wer"],
                    reviewer=review["reviewer"],
                    reviewed_at=review["reviewed_at"],
                )
            results.append(row)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if args.reviews:
        reviews = json.loads(args.reviews.read_text(encoding="utf-8"))
        rows = reviews["pages"] if isinstance(reviews, dict) else reviews
        output = {
            "experimental_validation_complete": False,
            "extractions": evaluate_pages(state, rows),
        }
    else:
        output = {"status": "pending_human_review", "pages": review_template(state)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Resultado: {args.output}")


if __name__ == "__main__":
    main()
