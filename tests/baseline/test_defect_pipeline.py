"""F1/F2: actual persistence operations against an isolated SQLite database.

This is a DB-API compatibility fixture, not PostgreSQL integration coverage.
Only placeholder/ANY/time/JSON syntax is adapted; constraints and mutations
execute in SQLite. No production connection or corpus file is opened.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from data import rag_pipeline as pipeline


class SQLiteCursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, sql, params=()):
        values = iter(params)
        bound = []

        def placeholder(match):
            value = next(values)
            if match.group() == "= ANY(%s)":
                bound.extend(value)
                return "IN (" + ",".join("?" for _ in value) + ")"
            if isinstance(value, datetime):
                value = value.isoformat()
            bound.append(json.dumps(value.obj) if hasattr(value, "obj") else value)
            return "?"

        translated = re.sub(r"= ANY\(%s\)|%s", placeholder, sql)
        self.cursor.execute(translated.replace("now()", "CURRENT_TIMESTAMP"), bound)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def description(self):
        return [SimpleNamespace(name=column[0]) for column in self.cursor.description]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.cursor.close()


@pytest.fixture
def isolated_silver(monkeypatch):
    database = sqlite3.connect(":memory:")
    database.execute("ATTACH DATABASE ':memory:' AS silver")
    database.execute("ATTACH DATABASE ':memory:' AS bronze")
    database.executescript("""
        CREATE TABLE bronze.documents (
            record_id INTEGER PRIMARY KEY, relative_path TEXT,
            file_name TEXT, page_count INTEGER, manifest_metadata TEXT
        );
        CREATE TABLE silver.silver_document_extractions (
            id INTEGER PRIMARY KEY, document_id INTEGER, extractor TEXT,
            extractor_version TEXT, total_pages INTEGER, processing_status TEXT,
            started_at TEXT, updated_at TEXT,
            UNIQUE(document_id, extractor, extractor_version)
        );
        CREATE TABLE silver.silver_page_extractions (
            id INTEGER PRIMARY KEY, extraction_id INTEGER, document_id INTEGER,
            extractor TEXT, extractor_version TEXT, page_number INTEGER,
            processing_status TEXT, attempt_count INTEGER DEFAULT 0,
            last_attempt_at TEXT, updated_at TEXT, error_message TEXT,
            source_page_path TEXT, extracted_text TEXT, extracted_markdown TEXT,
            structured_output TEXT, character_count INTEGER, word_count INTEGER,
            content_hash TEXT, processing_time_ms INTEGER,
            evaluation_status TEXT DEFAULT 'pending', quality_score REAL,
            quality_metrics TEXT, evaluation_method TEXT, evaluation_model TEXT,
            evaluation_prompt_version TEXT, evaluation_error TEXT, evaluated_at TEXT,
            UNIQUE(extraction_id, page_number)
        );
    """)

    @contextmanager
    def connection():
        try:
            yield SimpleNamespace(
                cursor=lambda: SQLiteCursor(database), commit=database.commit
            )
        except Exception:
            database.rollback()
            raise

    monkeypatch.setattr(pipeline, "connect", connection)
    monkeypatch.setattr(pipeline, "extractor_versions", lambda: {"pdf_reader": "v1"})
    yield database
    database.close()


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
def test_f1_characterization_gate_accepts_legacy_success(legacy_evaluation):
    assert pipeline.is_gold_ready("success", 1, 1, [legacy_evaluation["status"]])


@pytest.mark.xfail(
    strict=True, reason="F1: Gold gate ignores review, score and evaluation method"
)
@pytest.mark.parametrize("legacy_evaluation", LEGACY_EVALUATIONS, indirect=True)
def test_f1_contract_legacy_untrusted_evaluation_blocks_gold(legacy_evaluation):
    assert not pipeline.is_gold_ready("success", 1, 1, [legacy_evaluation["status"]])


@pytest.fixture
def forced_reextraction(monkeypatch, isolated_silver):
    database = isolated_silver
    extraction_id = pipeline.create_or_resume_extraction(
        17, "pdf_reader", 1, False, False
    )
    database.execute(
        """UPDATE silver.silver_page_extractions
           SET processing_status='success', extracted_text='old text',
               content_hash=?, evaluation_status='success', quality_score=97,
               evaluation_method='page_image', quality_metrics='{}'""",
        (pipeline.text_hash("old text"),),
    )
    database.commit()
    monkeypatch.setattr(
        pipeline,
        "bronze_documents",
        lambda _: [{"record_id": 17, "relative_path": "synthetic.pdf"}],
    )
    monkeypatch.setattr(
        pipeline,
        "page_paths",
        lambda *_: [pipeline.ROOT / "data" / "page_cache" / "synthetic-baseline.pdf"],
    )
    monkeypatch.setattr(
        pipeline, "extract_page", lambda *_: ("new text", "new text", None)
    )
    monkeypatch.setattr(pipeline, "refresh_silver_document", lambda *_: None)
    monkeypatch.setattr(pipeline, "rebuild_extraction", lambda *_: None)
    pipeline.process_extractions(17, ["pdf_reader"], False, True)
    return database, extraction_id


def test_f2_characterization_force_reuses_evaluation(forced_reextraction):
    database, extraction_id = forced_reextraction
    row = database.execute(
        """SELECT extracted_text, content_hash, evaluation_status, quality_score,
                  attempt_count FROM silver.silver_page_extractions
           WHERE extraction_id=?""",
        (extraction_id,),
    ).fetchone()
    assert row == ("new text", pipeline.text_hash("new text"), "success", 97, 1)


@pytest.mark.xfail(
    strict=True,
    reason="F2: forced text replacement preserves stale successful evaluation",
)
def test_f2_contract_changed_content_invalidates_score(forced_reextraction):
    database, extraction_id = forced_reextraction
    row = database.execute(
        """SELECT evaluation_status, quality_score FROM silver.silver_page_extractions
           WHERE extraction_id=?""",
        (extraction_id,),
    ).fetchone()
    assert row == ("pending", None)


@pytest.fixture
def evaluation_after_force(monkeypatch, forced_reextraction):
    database, _ = forced_reextraction
    evaluated = []
    monkeypatch.setenv("RAG_EVALUATION_MODEL", "offline-stub")
    monkeypatch.setattr(pipeline, "native_page_text", lambda _: "new reference text")

    def evaluate(*args):
        evaluated.append(args)
        return {"overall_score": 81, "requires_manual_review": False}, "page_image"

    monkeypatch.setattr(pipeline, "evaluate_page", evaluate)
    monkeypatch.setattr(pipeline, "refresh_quality_aggregates", lambda: None)
    pipeline.evaluate_extractions(17, ["pdf_reader"], True)
    return database, evaluated


def test_f2_characterization_evaluator_skips_forced_success(evaluation_after_force):
    database, evaluated = evaluation_after_force
    assert evaluated == []
    assert database.execute(
        "SELECT quality_score FROM silver.silver_page_extractions"
    ).fetchone() == (97,)


@pytest.mark.xfail(
    strict=True,
    reason="F2: evaluator only selects pending/error and skips changed content",
)
def test_f2_contract_force_content_is_evaluated_again(evaluation_after_force):
    database, evaluated = evaluation_after_force
    assert len(evaluated) == 1
    assert database.execute(
        "SELECT quality_score FROM silver.silver_page_extractions"
    ).fetchone() == (81,)


@pytest.fixture(params=["source-bytes", "extractor-config"])
def changed_extraction_identity(request, monkeypatch, isolated_silver, tmp_path):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic source A")
    isolated_silver.execute(
        "INSERT INTO bronze.documents VALUES (?, ?, ?, ?, ?)",
        (17, str(source), source.name, 1, "{}"),
    )
    isolated_silver.commit()
    monkeypatch.setattr(pipeline, "extractor_versions", lambda: {"glm_ocr": "v1"})
    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    monkeypatch.setenv("GLMOCR_MODEL", "synthetic-model-a")
    first = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, False)
    linked_source = Path(pipeline.bronze_documents(17)[0]["relative_path"])
    assert linked_source.read_bytes() == b"synthetic source A"
    if request.param == "source-bytes":
        source.write_bytes(b"synthetic source B")
        assert linked_source.read_bytes() == b"synthetic source B"
    else:
        monkeypatch.setenv("GLMOCR_MODEL", "synthetic-model-b")
        assert pipeline.use_direct_ollama_glm_ocr()
    second = pipeline.create_or_resume_extraction(17, "glm_ocr", 1, False, True)
    return first, second


def test_f2_characterization_identity_uses_only_document_extractor_version(
    changed_extraction_identity,
):
    first, second = changed_extraction_identity
    assert second == first


@pytest.mark.xfail(
    strict=True,
    reason="F2: extraction identity lacks source hash and effective configuration",
)
def test_f2_contract_changed_provenance_creates_new_extraction(
    changed_extraction_identity,
):
    first, second = changed_extraction_identity
    assert second != first
