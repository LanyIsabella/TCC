from pathlib import Path

import pytest
from data import extraction_provenance as provenance
from data import rag_pipeline as pipeline
from psycopg.types.json import Jsonb


def test_policy_migration_is_idempotent_and_empty_rollback_safe(isolated_pg):
    connect, _ = isolated_pg
    root = Path(pipeline.ROOT)
    up = (root / "data/migrations/0002_gold_promotion_policy.up.sql").read_text(
        encoding="utf-8"
    )
    down = (root / "data/migrations/0002_gold_promotion_policy.down.sql").read_text(
        encoding="utf-8"
    )
    with connect() as connection:
        connection.execute(up)
        connection.execute(up)
        assert connection.execute(
            "SELECT to_regclass('silver.gold_promotion_reviews')"
        ).fetchone()[0] == "silver.gold_promotion_reviews"
        connection.execute(down)
        assert connection.execute(
            "SELECT to_regclass('silver.gold_promotion_reviews')"
        ).fetchone()[0] is None
        connection.execute(up)


def _configure_evaluator(monkeypatch):
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    monkeypatch.setattr(
        pipeline, "native_page_text", lambda _: "synthetic native reference text"
    )
    monkeypatch.setattr(
        pipeline,
        "evaluate_page",
        lambda *_: (
            {"overall_score": 81, "requires_manual_review": False},
            "page_image",
        ),
    )


def test_human_review_is_append_only_and_result_bound(isolated_pg, monkeypatch):
    connect, _ = isolated_pg
    _configure_evaluator(monkeypatch)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='reviewed',"
            "extracted_markdown='reviewed',content_hash=%s,processing_status='success',"
            "source_page_path='data/page_cache/synthetic.pdf'"
            " WHERE extraction_id=%s",
            (pipeline.text_hash("reviewed"), execution),
        )
    pipeline.rebuild_extraction(execution, "v1")
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    with connect() as connection:
        page_id, result, evaluation_id, config_fp = connection.execute(
            "SELECT id,result_fingerprint,evaluation_id,evaluation_config_fingerprint "
            "FROM silver.silver_page_extractions WHERE extraction_id=%s",
            (execution,),
        ).fetchone()
        review_id = provenance.record_human_review(
            connection,
            page_id,
            result,
            str(evaluation_id),
            config_fp,
            "reviewer-1",
            "approved",
            {"fidelity": "checked"},
            {"source": "human_review_package", "snapshot": "ba555e"},
        )
        reviews = provenance.current_human_reviews(connection, [page_id])
        assert reviews[page_id][0]["review_id"] == review_id
        connection.commit()
        with connect() as blocked:
            with pytest.raises(Exception, match="append-only"):
                blocked.execute(
                    "DELETE FROM silver.gold_promotion_reviews WHERE review_id=%s",
                    (review_id,),
                )

        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='changed' "
            "WHERE id=%s",
            (page_id,),
        )
        changed = connection.execute(
            "SELECT result_fingerprint FROM silver.silver_page_extractions WHERE id=%s",
            (page_id,),
        ).fetchone()[0]
        assert changed != result
        with pytest.raises(ValueError, match="não corresponde"):
            provenance.record_human_review(
                connection,
                page_id,
                result,
                str(evaluation_id),
                config_fp,
                "reviewer-1",
                "approved",
                {"fidelity": "checked"},
                {"source": "human_review_package"},
            )


def test_normal_promotion_rejects_legacy_success_without_identity(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='legacy',"
            "extracted_markdown='legacy',content_hash=%s,processing_status='success',"
            "source_page_path='data/page_cache/synthetic.pdf',evaluation_status='success',"
            "quality_score=90,evaluation_method='page_image',quality_metrics=%s "
            "WHERE extraction_id=%s",
            (
                pipeline.text_hash("legacy"),
                Jsonb({"evaluation": {"requires_manual_review": True}}),
                execution,
            ),
        )
    pipeline.rebuild_extraction(execution, "v1")
    with pytest.raises(ValueError, match="não validada"):
        pipeline.activate_gold(17, "pdf_reader")


def test_uncertainty_quarantines_without_alternative_and_keeps_active_gold(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    monkeypatch.setattr(
        pipeline, "native_page_text", lambda _: "synthetic native reference text"
    )
    monkeypatch.setattr(
        pipeline,
        "evaluate_page",
        lambda *_: (
            {"overall_score": 81, "requires_manual_review": True},
            "page_image",
        ),
    )
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='uncertain',"
            "extracted_markdown='uncertain',content_hash=%s,processing_status='success',"
            "source_page_path='data/page_cache/synthetic.pdf' WHERE extraction_id=%s",
            (pipeline.text_hash("uncertain"), execution),
        )
    pipeline.rebuild_extraction(execution, "v1")
    active = pipeline.activate_gold(17, "pdf_reader", True)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    with pytest.raises(ValueError, match="não validada"):
        pipeline.activate_gold(17, "pdf_reader")
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT id FROM gold.gold_rag_documents WHERE is_active"
            ).fetchone()[0]
            == active
        )
