"""F1/F2: corrected persistence contracts on an isolated real PostgreSQL cluster."""

from pathlib import Path

import pytest
from data import rag_pipeline as pipeline


@pytest.fixture
def isolated_silver(isolated_pg):
    connect, _ = isolated_pg
    with connect() as database:
        yield database


@pytest.fixture
def legacy_evaluation(request):
    # Synthetic legacy state, including the historical successful fallback.
    return {"status": "success", **request.param}


LEGACY_EVALUATIONS = [
    pytest.param({"requires_manual_review": True, "quality_score": 90}, id="review"),
    pytest.param(
        {"requires_manual_review": False, "quality_score": None}, id="no-score"
    ),
    pytest.param(
        {
            "evaluation_method": "deterministic_fallback",
            "quality_score": 50,
            "requires_manual_review": True,
        },
        id="legacy-fallback",
    ),
]


@pytest.mark.parametrize("legacy_evaluation", LEGACY_EVALUATIONS, indirect=True)
def test_f1_contract_legacy_untrusted_evaluation_blocks_gold(legacy_evaluation):
    assert not pipeline.is_gold_ready("success", 1, 1, [legacy_evaluation["status"]])


@pytest.fixture
def forced_reextraction(monkeypatch, isolated_silver):
    database = isolated_silver
    original = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    database.execute(
        "UPDATE silver.silver_page_extractions SET processing_status='success', "
        "extracted_text='old text',content_hash=%s WHERE extraction_id=%s",
        (pipeline.text_hash("old text"), original),
    )
    database.execute(
        "UPDATE silver.silver_page_extractions SET evaluation_status='success', "
        "quality_score=97,evaluation_method='page_image',quality_metrics='{}' "
        "WHERE extraction_id=%s",
        (original,),
    )
    database.commit()
    monkeypatch.setattr(
        pipeline,
        "page_paths",
        lambda *_: [pipeline.ROOT / "data/page_cache/synthetic-baseline.pdf"],
    )
    monkeypatch.setattr(
        pipeline, "extract_page", lambda *_: ("new text", "new text", None)
    )
    monkeypatch.setattr(pipeline, "refresh_silver_document", lambda *_: None)
    monkeypatch.setattr(pipeline, "rebuild_extraction", lambda *_: None)
    pipeline.process_extractions(17, ["pdf_reader"], False, True)
    current = database.execute(
        "SELECT id FROM silver.silver_document_extractions ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    return database, current, original


def test_f2_regression_force_preserves_prior_evaluation(forced_reextraction):
    database, current, original = forced_reextraction
    assert current != original
    assert database.execute(
        (
            "SELECT extracted_text,quality_score FROM "
            "silver.silver_page_extractions WHERE extraction_id=%s"
        ),
        (original,),
    ).fetchone() == ("old text", 97)
    assert database.execute(
        "SELECT extracted_text,content_hash,evaluation_status,"
        "quality_score,attempt_count "
        "FROM silver.silver_page_extractions WHERE extraction_id=%s",
        (current,),
    ).fetchone() == ("new text", pipeline.text_hash("new text"), "pending", None, 1)


def test_f2_contract_changed_content_invalidates_score(forced_reextraction):
    database, current, _ = forced_reextraction
    assert database.execute(
        (
            "SELECT evaluation_status,quality_score FROM "
            "silver.silver_page_extractions WHERE extraction_id=%s"
        ),
        (current,),
    ).fetchone() == ("pending", None)


@pytest.fixture
def evaluation_after_force(monkeypatch, forced_reextraction):
    database, current, original = forced_reextraction
    evaluated = []
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "offline-stub")
    monkeypatch.setattr(pipeline, "native_page_text", lambda _: "new reference text")

    def evaluate(*args):
        evaluated.append(args)
        return {"overall_score": 81, "requires_manual_review": False}, "page_image"

    monkeypatch.setattr(pipeline, "evaluate_page", evaluate)
    monkeypatch.setattr(pipeline, "refresh_quality_aggregates", lambda: None)
    pipeline.evaluate_extractions(17, ["pdf_reader"], True)
    return database, evaluated, current, original


def test_f2_regression_evaluator_updates_only_current_text(evaluation_after_force):
    database, evaluated, current, original = evaluation_after_force
    assert len(evaluated) == 1
    assert database.execute(
        (
            "SELECT quality_score FROM "
            "silver.silver_page_extractions WHERE extraction_id=%s"
        ),
        (original,),
    ).fetchone() == (97,)
    assert database.execute(
        (
            "SELECT quality_score FROM "
            "silver.silver_page_extractions WHERE extraction_id=%s"
        ),
        (current,),
    ).fetchone() == (81,)


def test_f2_contract_force_content_is_evaluated_again(evaluation_after_force):
    database, evaluated, current, _ = evaluation_after_force
    assert len(evaluated) == 1
    assert database.execute(
        (
            "SELECT quality_score FROM "
            "silver.silver_page_extractions WHERE extraction_id=%s"
        ),
        (current,),
    ).fetchone() == (81,)


@pytest.fixture(params=["source-bytes", "extractor-config"])
def changed_extraction_identity(request, monkeypatch, isolated_silver, tmp_path):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic source A")
    isolated_silver.execute(
        ("UPDATE bronze.documents SET relative_path=%s WHERE record_id=17"),
        (str(source),),
    )
    isolated_silver.commit()
    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    monkeypatch.setenv("GLMOCR_MODEL", "synthetic-model-a")
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    linked = Path(pipeline.bronze_documents(17)[0]["relative_path"])
    assert linked.read_bytes() == b"synthetic source A"
    if request.param == "source-bytes":
        source.write_bytes(b"synthetic source B")
    else:
        monkeypatch.setenv("GLMOCR_MODEL", "synthetic-model-b")
    second = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    return first, second


def test_f2_regression_changed_identity_is_not_reused(changed_extraction_identity):
    first, second = changed_extraction_identity
    assert second != first


def test_f2_contract_changed_provenance_creates_new_extraction(
    changed_extraction_identity,
):
    first, second = changed_extraction_identity
    assert second != first
