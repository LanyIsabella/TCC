"""Referência humana é entrada explícita, nunca produzida pelo avaliador."""

import json
import sys

import pytest
from rag_eval.baseline.review import evaluate_pages, review_template


@pytest.fixture
def state():
    return {
        "documents": [{"document_id": 1, "sha256": "original-hash"}],
        "pages": [
            {
                "document_id": 1,
                "standard_id": "abnt_nbr_6028",
                "physical_page": 4,
                "extractions": [{"id": 12, "extracted_text": "abc de"}],
            }
        ],
    }


def test_all_pages_get_pending_templates_without_generated_transcriptions(state):
    template = review_template(state)
    assert len(template) == len(state["pages"])
    assert template[0]["transcription"] is None
    assert template[0]["review_status"] == "pending_human_review"


def test_pending_review_has_no_fabricated_quality_score(state):
    rows = evaluate_pages(state, review_template(state))
    assert rows[0]["status"] == "pending_human_review"
    assert rows[0]["cer"] is None
    assert rows[0]["wer"] is None


def test_only_attested_human_reference_is_used_and_errors_are_exact(state):
    review = review_template(state)[0]
    review.update(
        review_status="reviewed",
        transcription="abc df",
        reviewer="reviewer-01",
        reviewed_at="2026-11-09T18:00:00Z",
        transcription_origin="human",
    )
    result = evaluate_pages(state, [review])[0]
    assert result["cer"] == pytest.approx(1 / 6)
    assert result["wer"] == pytest.approx(1 / 2)
    assert result["status"] == "scored_against_attested_human_reference"


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewer", None),
        ("transcription_origin", "llm"),
        ("document_sha256", "different-original"),
        ("transcription", None),
    ],
)
def test_unattested_or_mismatched_reference_is_rejected(state, field, value):
    review = review_template(state)[0]
    review.update(
        review_status="reviewed",
        transcription="abc df",
        reviewer="reviewer-01",
        reviewed_at="2026-11-09T18:00:00Z",
        transcription_origin="human",
    )
    review[field] = value
    with pytest.raises(ValueError):
        evaluate_pages(state, [review])


def test_review_cli_generates_then_evaluates_pending_reference(
    state, tmp_path, monkeypatch
):
    from rag_eval.baseline import review

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(state), encoding="utf-8")
    reference = tmp_path / "reference.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["review", "--snapshot", str(snapshot_path), "--output", str(reference)],
    )
    review.main()
    output = tmp_path / "evaluation.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review",
            "--snapshot",
            str(snapshot_path),
            "--reviews",
            str(reference),
            "--output",
            str(output),
        ],
    )
    review.main()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["experimental_validation_complete"] is False
    assert result["extractions"][0]["cer"] is None
