import pytest
from data import rag_pipeline as pipeline
from psycopg.types.json import Jsonb


def _complete_pages(connect, extraction_id, texts):
    with connect() as connection:
        for page_number, text in enumerate(texts, start=1):
            connection.execute(
                """
                UPDATE silver.silver_page_extractions
                SET extracted_text=%s, extracted_markdown=%s,
                    processing_status='success', content_hash=%s,
                    result_fingerprint=%s
                WHERE extraction_id=%s AND page_number=%s
                """,
                (
                    text,
                    text,
                    pipeline.text_hash(text),
                    pipeline.text_hash(f"result:{text}"),
                    extraction_id,
                    page_number,
                ),
            )


def test_selection_is_per_page_and_history_is_append_only(isolated_pg):
    connect, _ = isolated_pg
    extraction = pipeline.create_or_resume_extraction(
        17, "docling", 2, False, False
    )
    _complete_pages(connect, extraction, ["texto limpo", "## Título\n- item"])
    other = pipeline.create_or_resume_extraction(17, "glm_ocr", 2, False, False)
    _complete_pages(connect, other, ["\ue000", "texto alternativo"])

    first = pipeline.select_extractions_for_document(17)
    second = pipeline.select_extractions_for_document(17)
    assert first != second
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT selection_run_id,status,selected_page_extraction_id
            FROM silver.page_extraction_selections
            WHERE document_id=17 ORDER BY created_at,id
            """
        ).fetchall()
        decision = connection.execute(
            """
            SELECT decision->'candidates'->0->>'execution_id'
            FROM silver.page_extraction_selections
            WHERE document_id=17 ORDER BY created_at,id LIMIT 1
            """
        ).fetchone()[0]
    assert len(rows) == 4
    assert {row[1] for row in rows} == {"selected"}
    assert rows[0][0] != rows[2][0]
    assert rows[0][2] != rows[1][2]
    assert decision


def test_selection_quarantines_peer_agreement_without_reference(isolated_pg):
    connect, _ = isolated_pg
    for extractor in ("docling", "glm_ocr"):
        extraction = pipeline.create_or_resume_extraction(
            17, extractor, 1, False, False
        )
        _complete_pages(connect, extraction, ["mesmo erro"])
    pipeline.select_extractions_for_document(17)
    with connect() as connection:
        status, reason = connection.execute(
            """
            SELECT status,decision->>'reason'
            FROM silver.page_extraction_selections
            WHERE document_id=17 ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    assert status == "quarantined"
    assert reason == "peer_agreement_without_reference"


def test_quarantined_selection_cannot_replace_active_gold(isolated_pg):
    connect, _ = isolated_pg
    extraction = pipeline.create_or_resume_extraction(
        17, "pdf_reader", 1, False, False
    )
    _complete_pages(connect, extraction, ["conteúdo publicado"])
    pipeline.rebuild_extraction(extraction, "v1")
    active = pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO silver.page_extraction_selections
                (document_id,page_number,status,decision)
            VALUES (17,1,'quarantined',%s)
            """,
            (Jsonb({"reason": "no_eligible_candidate"}),),
        )

    with pytest.raises(ValueError, match="quarentena"):
        pipeline.activate_gold(17, "pdf_reader", True)
    with connect() as connection:
        assert connection.execute(
            "SELECT id FROM gold.gold_rag_documents WHERE is_active"
        ).fetchone()[0] == active
