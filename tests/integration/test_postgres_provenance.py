"""Contratos F2 sobre PostgreSQL real e dados exclusivamente sintéticos."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from data import extraction_provenance as provenance
from data import rag_pipeline as pipeline
from psycopg import sql


def test_original_change_creates_new_execution(isolated_pg):
    _, source = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    source.write_bytes(b"synthetic source B")
    second = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    assert second != first


def test_ocr_configuration_change_creates_new_execution(isolated_pg, monkeypatch):
    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    monkeypatch.setenv("GLMOCR_MODEL", "synthetic-model-a")
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    monkeypatch.setenv("GLMOCR_MODEL", "synthetic-model-b")
    second = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    assert second != first


def test_modified_text_cannot_keep_successful_evaluation(isolated_pg):
    connect, _ = isolated_pg
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "extracted_text='old', processing_status='success' WHERE"
                " extraction_id=%s"
            ),
            (execution,),
        )
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "evaluation_status='success', quality_score=97 WHERE "
                "extraction_id=%s"
            ),
            (execution,),
        )
        assert (
            connection.execute(
                (
                    "SELECT quality_score FROM "
                    "silver.silver_page_extractions WHERE extraction_id=%s"
                ),
                (execution,),
            ).fetchone()[0]
            == 97
        )
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "extracted_text='new' WHERE extraction_id=%s"
            ),
            (execution,),
        )
        result = connection.execute(
            (
                "SELECT evaluation_status,quality_score FROM "
                "silver.silver_page_extractions WHERE extraction_id=%s"
            ),
            (execution,),
        ).fetchone()
    assert result == ("pending", None)
    with connect() as connection:
        assert connection.execute(
            "SELECT content_hash FROM silver.silver_page_extractions"
        ).fetchone()[0] == pipeline.text_hash("new")


def test_forced_processing_preserves_previous_execution(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "extracted_text='old' WHERE extraction_id=%s"
            ),
            (first,),
        )
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "evaluation_status='success', quality_score=97 WHERE "
                "extraction_id=%s"
            ),
            (first,),
        )
    second = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    assert first != second
    with connect() as connection:
        assert connection.execute(
            (
                "SELECT extracted_text,quality_score FROM "
                "silver.silver_page_extractions WHERE extraction_id=%s"
            ),
            (first,),
        ).fetchone() == ("old", 97)
        assert connection.execute(
            (
                "SELECT evaluation_status,quality_score FROM "
                "silver.silver_page_extractions WHERE extraction_id=%s"
            ),
            (second,),
        ).fetchone() == ("pending", None)


def complete(connect, execution, text="synthetic text"):
    with connect() as connection:
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "extracted_text=%s,extracted_markdown=%s,content_hash=%s,processing_status='success',source_page_path='data/page_cache/synthetic.pdf'"
                " WHERE extraction_id=%s"
            ),
            (text, text, pipeline.text_hash(text), execution),
        )
    pipeline.rebuild_extraction(execution, "v1")


def configure_stubs(monkeypatch):
    calls = []
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    monkeypatch.setattr(
        pipeline, "native_page_text", lambda _: "synthetic native reference text"
    )

    def evaluate(*args):
        calls.append(args)
        return {"overall_score": 81, "requires_manual_review": False}, "page_image"

    monkeypatch.setattr(pipeline, "evaluate_page", evaluate)

    original_metrics = pipeline.deterministic_metrics

    def validated_metrics(reference, extracted):
        # Synthetic fixture: model an external attestation, not native text as truth.
        metrics = original_metrics(reference, extracted)
        metrics["deterministic_validation"] = {
            "status": "passed",
            "reference_type": "independent_reference",
            "reference_fingerprint": pipeline.text_hash(reference),
            "reference_status": "trusted",
        }
        return metrics

    monkeypatch.setattr(pipeline, "deterministic_metrics", validated_metrics)
    return calls


def test_equivalent_inputs_resume_but_force_is_another_execution(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    assert (
        pipeline.create_or_resume_extraction(17, "pdf_reader", 1, True, False) == first
    )
    forced = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    with connect() as connection:
        rows = connection.execute(
            "SELECT execution_id,input_fingerprint FROM "
            "silver.silver_document_extractions ORDER BY id"
        ).fetchall()
    assert first != forced and rows[0][0] != rows[1][0]
    assert rows[0][1] == rows[1][1]


@pytest.mark.parametrize(
    "setting,value",
    [
        ("GLMOCR_MODEL_DIGEST", "c" * 64),
        ("GLMOCR_DIRECT_CONTEXT", "8192"),
        ("GLMOCR_DIRECT_MAX_TOKENS", "1000"),
    ],
)
def test_ocr_digest_and_parameter_changes_are_new_inputs(
    isolated_pg, monkeypatch, setting, value
):
    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    monkeypatch.setenv(setting, value)
    assert pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False) != first


def test_extractor_version_changes_identity(isolated_pg, monkeypatch):
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    monkeypatch.setattr(pipeline, "extractor_versions", lambda: {"pdf_reader": "v2"})
    assert (
        pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False) != first
    )


def test_history_keeps_evaluation_and_is_append_only(isolated_pg):
    connect, _ = isolated_pg
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution, "old text")
    with connect() as connection:
        connection.execute(
            (
                "UPDATE silver.silver_page_extractions SET "
                "evaluation_status='success',quality_score=97 WHERE "
                "extraction_id=%s"
            ),
            (execution,),
        )
        old = connection.execute(
            "SELECT result_fingerprint,evaluation_id FROM "
            "silver.silver_page_extractions"
        ).fetchone()
        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='new text'"
        )
        new = connection.execute(
            "SELECT result_fingerprint,evaluation_id,quality_score "
            "FROM silver.silver_page_extractions"
        ).fetchone()
        assert new[0] != old[0] and new[1:] == (None, None)
        assert (
            connection.execute(
                (
                    "SELECT count(*) FROM silver.page_extraction_history "
                    "WHERE evaluation_id=%s AND "
                    "snapshot->>'quality_score'='97.00'"
                ),
                (old[1],),
            ).fetchone()[0]
            >= 1
        )
    with pytest.raises(psycopg.Error, match="append-only"), connect() as connection:
        connection.execute("DELETE FROM silver.page_extraction_history")


def test_changed_evaluator_configuration_reevaluates_only_latest_text(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    calls = configure_stubs(monkeypatch)
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, first, "old result")
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    second = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    complete(connect, second, "new result")
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    assert len(calls) == 2
    monkeypatch.setenv("RAG_EVALUATION_CONTEXT", "8192")
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    assert len(calls) == 3
    assert calls[-1][2] == "new result"
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT count(DISTINCT evaluation_id) FROM "
                "silver.page_extraction_history WHERE evaluation_id IS "
                "NOT NULL"
            ).fetchone()[0]
            >= 3
        )


def test_equivalent_evaluation_is_not_repeated_and_binds_result(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    calls = configure_stubs(monkeypatch)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    assert len(calls) == 1
    with connect() as connection:
        result, target, config = connection.execute(
            "SELECT "
            "result_fingerprint,evaluation_input_fingerprint,evaluation_config_fingerprint"
            " FROM silver.silver_page_extractions"
        ).fetchone()
    assert result == target and config is not None


def test_late_evaluation_is_historical_without_approving_current_text(isolated_pg):
    connect, _ = isolated_pg
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution, "old")
    with connect() as connection:
        page, target = connection.execute(
            "SELECT id,result_fingerprint FROM silver.silver_page_extractions"
        ).fetchone()
        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='new'"
        )
        accepted = provenance.save_evaluation(
            connection,
            page,
            target,
            {"model": "synthetic", "engine_version": "v1"},
            {
                "score": 99,
                "metrics": {},
                "status": "success",
                "method": "fixture",
                "error": None,
                "evaluated_at": datetime.now(UTC),
            },
        )
        assert not accepted
        assert connection.execute(
            "SELECT quality_score,evaluation_status FROM silver.silver_page_extractions"
        ).fetchone() == (None, "pending")
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.page_extraction_history "
                "WHERE event_kind='late_evaluation'"
            ).fetchone()[0]
            == 1
        )


def test_execution_creation_rollback_leaves_no_partial_pages(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        profile = connection.execute(
            (
                "SELECT input_provenance FROM "
                "silver.silver_document_extractions WHERE id=%s"
            ),
            (first,),
        ).fetchone()[0]
        connection.execute("INSERT INTO bronze.documents(record_id) VALUES(18)")
    with pytest.raises(RuntimeError), connect() as connection:
        provenance.start_execution(connection, 18, "pdf_reader", 3, profile, False)
        raise RuntimeError("synthetic interruption")
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.silver_document_extractions"
                " WHERE document_id=18"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.silver_page_extractions "
                "WHERE document_id=18"
            ).fetchone()[0]
            == 0
        )


def test_concurrent_equivalent_creation_is_idempotent(isolated_pg):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: pipeline.create_or_resume_extraction(
                    17, "pdf_reader", 1, False, False
                ),
                range(2),
            )
        )
    assert results[0] == results[1]


def test_concurrent_processing_claims_each_page_once(isolated_pg, monkeypatch):
    started, release = Event(), Event()
    calls = []
    monkeypatch.setattr(
        pipeline,
        "page_paths",
        lambda *_: [pipeline.ROOT / "data/page_cache/synthetic.pdf"],
    )

    def extract(*_):
        calls.append("called")
        if len(calls) == 1:
            started.set()
            assert release.wait(15)
        return "synthetic", "synthetic", None

    monkeypatch.setattr(pipeline, "extract_page", extract)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            pipeline.process_extractions, 17, ["pdf_reader"], False, False
        )
        try:
            assert started.wait(10)
            pool.submit(
                pipeline.process_extractions, 17, ["pdf_reader"], True, False
            ).result(timeout=10)
        finally:
            release.set()
        first.result(timeout=10)
    assert calls == ["called"]


def test_can_reactivate_previous_gold_without_deleting_versions(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, first, "first version")
    original = pipeline.activate_gold(17, "pdf_reader", True)
    second = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    complete(connect, second, "second version")
    newer = pipeline.activate_gold(17, "pdf_reader", True)
    assert original != newer
    restored = pipeline.activate_gold(17, "pdf_reader", True, extraction_id=first)
    assert restored == original
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT id FROM gold.gold_rag_documents WHERE is_active"
            ).fetchone()[0]
            == original
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM gold.gold_rag_documents"
            ).fetchone()[0]
            == 2
        )


def test_derivation_status_marks_old_gold_and_index_without_rewriting_them(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, first, "first text")
    gold = pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        connection.execute(
            (
                "UPDATE gold.gold_rag_page_index SET "
                "embedding=%s::vector,embedding_content_hash=content_hash,embedding_status='success',model_digest='synthetic'"
            ),
            ("[" + ",".join(["0.01"] * 768) + "]",),
        )
        old = connection.execute(
            "SELECT to_jsonb(p) FROM gold.gold_rag_page_index p"
        ).fetchone()[0]
        assert (
            connection.execute(
                (
                    "SELECT is_stale FROM gold.gold_rag_derivation_status "
                    "WHERE rag_document_id=%s"
                ),
                (gold,),
            ).fetchone()[0]
            is False
        )
    second = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    complete(connect, second, "second text")
    with connect() as connection:
        assert (
            connection.execute(
                (
                    "SELECT is_stale FROM gold.gold_rag_derivation_status "
                    "WHERE rag_document_id=%s"
                ),
                (gold,),
            ).fetchone()[0]
            is True
        )
        stale, identity = connection.execute(
            "SELECT source_is_stale,derivation_fingerprint FROM "
            "gold.gold_rag_page_derivation_status"
        ).fetchone()
        assert stale and len(identity) == 64
        assert (
            connection.execute(
                "SELECT to_jsonb(p) FROM gold.gold_rag_page_index p"
            ).fetchone()[0]
            == old
        )


def test_promotion_failure_rolls_back_active_variant(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, first, "old Gold")
    original = pipeline.activate_gold(17, "pdf_reader", True)
    second = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    complete(connect, second, "new Gold")
    with connect() as connection:
        connection.execute(
            "CREATE FUNCTION gold.fail_fixture() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic"
            " promotion interruption'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER fail_fixture BEFORE INSERT ON "
            "gold.gold_rag_page_index FOR EACH ROW EXECUTE FUNCTION "
            "gold.fail_fixture()"
        )
    with pytest.raises(psycopg.Error, match="synthetic promotion interruption"):
        pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT id FROM gold.gold_rag_documents WHERE is_active"
            ).fetchone()[0]
            == original
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM gold.gold_rag_documents"
            ).fetchone()[0]
            == 1
        )


def test_extraction_failure_does_not_overwrite_previous_success(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, first, "preserved text")
    monkeypatch.setattr(
        pipeline,
        "page_paths",
        lambda *_: [pipeline.ROOT / "data/page_cache/synthetic.pdf"],
    )

    def fail(*_):
        raise RuntimeError("synthetic extractor failure")

    monkeypatch.setattr(pipeline, "extract_page", fail)
    pipeline.process_extractions(17, ["pdf_reader"], False, True)
    with connect() as connection:
        rows = connection.execute(
            "SELECT id,processing_status FROM "
            "silver.silver_document_extractions ORDER BY id"
        ).fetchall()
        assert rows[0] == (first, "success") and rows[1][1] == "error"
        assert (
            connection.execute(
                (
                    "SELECT extracted_text FROM "
                    "silver.silver_page_extractions WHERE extraction_id=%s"
                ),
                (first,),
            ).fetchone()[0]
            == "preserved text"
        )


@pytest.mark.parametrize("isolated_pg", [False], indirect=True)
def test_legacy_migration_is_explicit_idempotent_and_reversible_before_new_work(
    isolated_pg,
):
    connect, _ = isolated_pg
    root = Path(__file__).resolve().parents[2]
    up = (root / "data/migrations/0001_extraction_provenance.up.sql").read_text(
        encoding="utf-8"
    )
    down = (root / "data/migrations/0001_extraction_provenance.down.sql").read_text(
        encoding="utf-8"
    )
    with connect() as connection:
        execution = connection.execute(
            "INSERT INTO "
            "silver.silver_document_extractions(document_id,extractor,extractor_version)"
            " VALUES(17,'pdf_reader','legacy') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            (
                "INSERT INTO "
                "silver.silver_page_extractions(extraction_id,document_id,extractor,extractor_version,page_number,extracted_text,quality_score,evaluation_status)"
                " VALUES(%s,17,'pdf_reader','legacy',1,'legacy "
                "text',97,'success')"
            ),
            (execution,),
        )
        before = connection.execute(
            "SELECT to_jsonb(p) FROM silver.silver_page_extractions p"
        ).fetchone()[0]
        connection.execute(up)
        connection.execute(up)
        profile = connection.execute(
            "SELECT input_provenance,input_fingerprint FROM "
            "silver.silver_document_extractions"
        ).fetchone()
        assert profile == ({"historical_configuration": "unknown"}, None)
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.page_extraction_history"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT quality_score FROM silver.silver_page_extractions"
            ).fetchone()[0]
            == 97
        )
        connection.execute(down)
        assert (
            connection.execute(
                "SELECT to_jsonb(p) FROM silver.silver_page_extractions p"
            ).fetchone()[0]
            == before
        )


def test_schema_downgrade_refuses_to_erase_used_history(isolated_pg):
    connect, _ = isolated_pg
    pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    root = Path(__file__).resolve().parents[2]
    with (
        pytest.raises(psycopg.Error, match="retain this archive"),
        connect() as connection,
    ):
        connection.execute(
            (root / "data/migrations/0001_extraction_provenance.down.sql").read_text(
                encoding="utf-8"
            )
        )
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.silver_document_extractions"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.page_extraction_history"
            ).fetchone()[0]
            == 1
        )


def test_unknown_ocr_digest_cannot_authorize_automatic_reuse(isolated_pg, monkeypatch):
    monkeypatch.setattr(provenance, "model_digest", lambda *_: None)
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    assert pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False) != first


def test_unknown_evaluator_digest_cannot_preserve_success_across_invocations(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    calls = configure_stubs(monkeypatch)
    monkeypatch.setattr(provenance, "model_digest", lambda *_: None)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    assert len(calls) == 2


def test_formatting_only_yaml_change_has_same_effective_identity(
    isolated_pg, monkeypatch, tmp_path
):
    config = tmp_path / "config/glmocr.yaml"
    config.parent.mkdir()
    config.write_text(
        ("pipeline: {ocr_api: {model: synthetic}, page_loader: {max_tokens: 2048}}"),
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    config.write_text(
        (
            "# formatting only\npipeline:\n  page_loader:\n    "
            "max_tokens: 2048\n  ocr_api:\n    model: synthetic\n"
        ),
        encoding="utf-8",
    )
    assert pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False) == first


def test_explicit_default_matches_effective_ocr_configuration(isolated_pg, monkeypatch):
    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    monkeypatch.delenv("GLMOCR_DIRECT_RETRY_MAX_TOKENS", raising=False)
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    monkeypatch.setenv("GLMOCR_DIRECT_RETRY_MAX_TOKENS", "32768")
    assert pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False) == first


@pytest.mark.parametrize("isolated_pg", [False], indirect=True)
def test_backup_restoration_reverts_schema_and_keeps_new_version_archive(
    isolated_pg, postgres_cluster, tmp_path
):
    connect, _ = isolated_pg
    settings, _marker = postgres_cluster
    root = Path(__file__).resolve().parents[2]
    binaries = Path(os.getenv("TCC_PG_BIN", "C:/Program Files/PostgreSQL/18/bin"))
    backup = tmp_path / "before.backup"
    with connect() as connection:
        source_database = connection.info.dbname
        assert source_database.startswith("tcc_f41_")
        old_id = connection.execute(
            "INSERT INTO "
            "silver.silver_document_extractions(document_id,extractor,extractor_version)"
            " VALUES(17,'pdf_reader','v1') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            (
                "INSERT INTO "
                "silver.silver_page_extractions(extraction_id,document_id,extractor,extractor_version,page_number,extracted_text,quality_score,evaluation_status)"
                " VALUES(%s,17,'pdf_reader','v1',1,'archived "
                "original',97,'success')"
            ),
            (old_id,),
        )
        original = connection.execute(
            "SELECT to_jsonb(p) FROM silver.silver_page_extractions p"
        ).fetchall()
    arguments = [
        "-h",
        settings["host"],
        "-p",
        str(settings["port"]),
        "-U",
        settings["user"],
    ]
    subprocess.run(
        [
            str(binaries / "pg_dump.exe"),
            *arguments,
            "-Fc",
            "-f",
            str(backup),
            "-d",
            source_database,
        ],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with connect() as connection:
        connection.execute(
            (root / "data/migrations/0001_extraction_provenance.up.sql").read_text(
                encoding="utf-8"
            )
        )
    current = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, current, "new version retained in archive")
    restored_database = "tcc_f41_restore_" + uuid4().hex
    with psycopg.connect(**settings, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_database))
        )
    try:
        subprocess.run(
            [
                str(binaries / "pg_restore.exe"),
                *arguments,
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "-d",
                restored_database,
                str(backup),
            ],
            check=True,
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with psycopg.connect(**{**settings, "dbname": restored_database}) as restored:
            assert (
                restored.execute(
                    "SELECT to_jsonb(p) FROM silver.silver_page_extractions p"
                ).fetchall()
                == original
            )
            assert (
                restored.execute(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "table_schema='silver' AND "
                    "column_name='input_fingerprint'"
                ).fetchone()[0]
                == 0
            )
        with connect() as archive:
            assert (
                archive.execute(
                    "SELECT count(*) FROM silver.silver_document_extractions"
                ).fetchone()[0]
                == 2
            )
            assert (
                archive.execute(
                    "SELECT count(*) FROM silver.page_extraction_history"
                ).fetchone()[0]
                >= 2
            )
    finally:
        with psycopg.connect(**settings, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(restored_database)
                )
            )


def test_promotion_compares_current_runs_and_rejects_outdated_evaluator(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    configure_stubs(monkeypatch)
    for extractor in ["pdf_reader", "docling", "glm_ocr"]:
        execution = pipeline.create_or_resume_extraction(17, extractor, 1, False, False)
        complete(connect, execution, "synthetic " + extractor)
    pipeline.evaluate_extractions(17, ["pdf_reader", "docling", "glm_ocr"], False)
    pipeline.activate_gold(17, "docling")
    new = pipeline.create_or_resume_extraction(17, "docling", 1, False, True)
    complete(connect, new, "new synthetic Docling")
    pipeline.evaluate_extractions(17, ["docling"], False)
    active = pipeline.activate_gold(17, "docling")
    with connect() as connection:
        assert (
            connection.execute(
                ("SELECT extraction_id FROM gold.gold_rag_documents WHERE id=%s"),
                (active,),
            ).fetchone()[0]
            == new
        )
    monkeypatch.setenv("RAG_EVALUATION_CONTEXT", "8192")
    with pytest.raises(ValueError, match="não validada"):
        pipeline.activate_gold(17, "docling")


def test_late_old_configuration_cannot_overwrite_newer_assessment(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    monkeypatch.setattr(
        pipeline, "native_page_text", lambda _: "synthetic reference text"
    )
    calls = []

    def evaluate(*_):
        calls.append("evaluation")
        if len(calls) == 1:
            monkeypatch.setenv("RAG_EVALUATION_CONTEXT", "8192")
            pipeline.evaluate_extractions(17, ["pdf_reader"], False)
            return {"overall_score": 11}, "page_image"
        return {"overall_score": 82}, "page_image"

    monkeypatch.setattr(pipeline, "evaluate_page", evaluate)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    with connect() as connection:
        score, context = connection.execute(
            "SELECT quality_score,evaluation_config->>'num_ctx' FROM"
            " silver.silver_page_extractions"
        ).fetchone()
        assert score == 82 and context == "8192"
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.page_extraction_history "
                "WHERE event_kind='late_evaluation'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("isolated_pg", [False], indirect=True)
def test_unmigrated_database_fails_closed_with_explicit_guidance(isolated_pg):
    connect, _ = isolated_pg
    with pytest.raises(RuntimeError, match="0001_extraction_provenance"):
        pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM silver.silver_document_extractions"
            ).fetchone()[0]
            == 0
        )


def test_current_page_change_marks_gold_stale_before_summary_rebuild(isolated_pg):
    connect, _ = isolated_pg
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution, "source before change")
    gold = pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        before = connection.execute(
            ("SELECT full_text FROM gold.gold_rag_documents WHERE id=%s"), (gold,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE silver.silver_page_extractions SET extracted_text='changed source'"
        )
        assert (
            connection.execute(
                (
                    "SELECT is_stale FROM gold.gold_rag_derivation_status "
                    "WHERE rag_document_id=%s"
                ),
                (gold,),
            ).fetchone()[0]
            is True
        )
        assert (
            connection.execute(
                ("SELECT full_text FROM gold.gold_rag_documents WHERE id=%s"), (gold,)
            ).fetchone()[0]
            == before
        )


def test_gold_keeps_links_to_each_assessment_used_at_publication(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    configure_stubs(monkeypatch)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    gold = pipeline.activate_gold(17, "pdf_reader", True)
    monkeypatch.setenv("RAG_EVALUATION_CONTEXT", "8192")
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    assert pipeline.activate_gold(17, "pdf_reader", True) == gold
    with connect() as connection:
        links = connection.execute(
            "SELECT evaluation_id,snapshot->'derived_gold'->>'id' "
            "FROM silver.page_extraction_history WHERE "
            "event_kind='gold_derivation'"
        ).fetchall()
        assert len(links) == 2 and links[0][0] != links[1][0]
        assert all(row[1] == str(gold) for row in links)


def test_interrupted_processing_can_resume_the_same_execution(isolated_pg, monkeypatch):
    connect, _ = isolated_pg
    calls = []
    monkeypatch.setattr(
        pipeline,
        "page_paths",
        lambda *_: [pipeline.ROOT / "data/page_cache/synthetic.pdf"],
    )

    def extract(*_):
        calls.append("attempt")
        if len(calls) == 1:
            raise KeyboardInterrupt("synthetic interrupted worker")
        return "resumed text", "resumed text", None

    monkeypatch.setattr(pipeline, "extract_page", extract)
    with pytest.raises(KeyboardInterrupt):
        pipeline.process_extractions(17, ["pdf_reader"], False, False)
    with connect() as connection:
        original = connection.execute(
            "SELECT id,processing_status FROM silver.silver_document_extractions"
        ).fetchone()
        assert original[1] == "pending"
        assert (
            connection.execute(
                "SELECT processing_status FROM silver.silver_page_extractions"
            ).fetchone()[0]
            == "processing"
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM gold.gold_rag_documents"
            ).fetchone()[0]
            == 0
        )
    pipeline.process_extractions(17, ["pdf_reader"], True, False)
    with connect() as connection:
        assert connection.execute(
            "SELECT id,processing_status FROM silver.silver_document_extractions"
        ).fetchall() == [(original[0], "success")]
        assert (
            connection.execute(
                "SELECT attempt_count FROM silver.silver_page_extractions"
            ).fetchone()[0]
            == 2
        )


def test_summary_failure_resumes_without_extracting_completed_pages_again(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    calls = []
    rebuild = pipeline.rebuild_extraction
    monkeypatch.setattr(
        pipeline,
        "page_paths",
        lambda *_: [pipeline.ROOT / "data/page_cache/synthetic.pdf"],
    )

    def extract(*_):
        calls.append("extract")
        return "stored text", "stored text", None

    def fail_once(*args):
        if len(calls) == 1:
            calls.append("summary interruption")
            raise RuntimeError("synthetic summary interruption")
        return rebuild(*args)

    monkeypatch.setattr(pipeline, "extract_page", extract)
    monkeypatch.setattr(pipeline, "rebuild_extraction", fail_once)
    with pytest.raises(RuntimeError, match="summary interruption"):
        pipeline.process_extractions(17, ["pdf_reader"], False, False)
    pipeline.process_extractions(17, ["pdf_reader"], False, False)
    assert calls.count("extract") == 1
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT processing_status FROM silver.silver_document_extractions"
            ).fetchone()[0]
            == "success"
        )


@pytest.mark.parametrize(
    "native,status",
    [
        ("tiny", "reference_unavailable"),
        ("x" * 19, "reference_unavailable"),
        ("x" * 20, "error"),
        ("synthetic reference with sufficient text", "error"),
    ],
)
def test_failed_assessment_never_marks_result_successful(
    isolated_pg, monkeypatch, native, status
):
    connect, _ = isolated_pg
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    monkeypatch.setattr(pipeline, "native_page_text", lambda _: native)

    def fail(*_):
        raise RuntimeError("synthetic evaluation failure")

    monkeypatch.setattr(pipeline, "evaluate_page", fail)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    with connect() as connection:
        assert connection.execute(
            "SELECT quality_score,evaluation_status FROM silver.silver_page_extractions"
        ).fetchone() == (None, status)


def test_job_selected_before_text_change_does_not_invoke_evaluator(
    isolated_pg, monkeypatch
):
    connect, _ = isolated_pg
    calls = configure_stubs(monkeypatch)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    with connect() as connection:
        job = connection.execute(
            "SELECT "
            "id,extraction_id,source_page_path,extracted_text,extracted_markdown,document_id,evaluation_status,result_fingerprint"
            " FROM silver.silver_page_extractions"
        ).fetchone()
        connection.execute(
            "UPDATE silver.silver_page_extractions SET "
            "extracted_text='superseded selection'"
        )
    pipeline._evaluate_page_result(job, pipeline.evaluation_configuration())
    assert calls == []


def test_unknown_evaluator_cannot_authorize_normal_promotion(isolated_pg, monkeypatch):
    connect, _ = isolated_pg
    configure_stubs(monkeypatch)
    monkeypatch.setattr(provenance, "model_digest", lambda *_: None)
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution)
    pipeline.evaluate_extractions(17, ["pdf_reader"], False)
    with pytest.raises(ValueError, match="não validada"):
        pipeline.activate_gold(17, "pdf_reader")


def test_changed_result_cannot_overwrite_already_published_gold(isolated_pg):
    connect, _ = isolated_pg
    execution = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, execution, "original immutable publication")
    original = pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        original_text = connection.execute(
            ("SELECT full_text FROM gold.gold_rag_documents WHERE id=%s"), (original,)
        ).fetchone()[0]
    complete(connect, execution, "different result in same execution")
    with pytest.raises(ValueError, match="outra execução"):
        pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        assert (
            connection.execute(
                ("SELECT full_text FROM gold.gold_rag_documents WHERE id=%s"),
                (original,),
            ).fetchone()[0]
            == original_text
        )


def test_processing_uses_identical_original_bytes_for_pages_and_identity(
    isolated_pg, monkeypatch
):
    connect, source = isolated_pg
    original_hash = provenance.file_digest(source)

    def pages(snapshot, _document_id):
        assert snapshot.read_bytes() == b"synthetic source A"
        source.write_bytes(b"synthetic source changed after page preparation")
        return [pipeline.ROOT / "data/page_cache/synthetic.pdf"]

    monkeypatch.setattr(pipeline, "page_paths", pages)
    monkeypatch.setattr(
        pipeline, "extract_page", lambda *_: ("from source A", "from source A", None)
    )
    pipeline.process_extractions(17, ["pdf_reader"], False, False)
    with connect() as connection:
        profile = connection.execute(
            "SELECT input_provenance FROM silver.silver_document_extractions"
        ).fetchone()[0]
    assert profile["source_sha256"] == original_hash
    assert (
        pipeline.PAGE_CACHE / "originals" / (original_hash + ".pdf")
    ).read_bytes() == b"synthetic source A"


def test_incomplete_new_execution_cannot_replace_previous_active_gold(isolated_pg):
    connect, _ = isolated_pg
    first = pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, False)
    complete(connect, first)
    active = pipeline.activate_gold(17, "pdf_reader", True)
    pipeline.create_or_resume_extraction(17, "pdf_reader", 1, False, True)
    with pytest.raises(ValueError, match="Nenhuma extração completa"):
        pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        assert (
            connection.execute(
                "SELECT id FROM gold.gold_rag_documents WHERE is_active"
            ).fetchone()[0]
            == active
        )
