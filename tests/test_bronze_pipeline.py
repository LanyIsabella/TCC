from __future__ import annotations

from pathlib import Path

import requests
from data import bronze_postgres


def test_direct_ollama_pdf_text_preserves_page_order(
    monkeypatch, tmp_path: Path
) -> None:
    page_one = tmp_path / "page-0001.pdf"
    page_two = tmp_path / "page-0002.pdf"
    page_one.write_bytes(b"page one")
    page_two.write_bytes(b"page two")

    monkeypatch.setattr(
        "data.rag_pipeline.page_paths",
        lambda _path, _document_id: [page_one, page_two],
    )
    monkeypatch.setattr(
        "data.rag_pipeline.direct_ollama_glm_ocr",
        lambda page: (page.stem, page.stem, None),
    )

    result = bronze_postgres.direct_ollama_pdf_text(tmp_path / "document.pdf")

    assert result == "page-0001\n\npage-0002"


def test_direct_ollama_pdf_text_falls_back_to_native_text_on_ocr_error(
    monkeypatch, tmp_path: Path
) -> None:
    page = tmp_path / "page-0001.pdf"
    page.write_bytes(b"page one")

    monkeypatch.setattr(
        "data.rag_pipeline.page_paths", lambda _path, _document_id: [page]
    )
    monkeypatch.setattr(
        "data.rag_pipeline.direct_ollama_glm_ocr",
        lambda _page: (_ for _ in ()).throw(ValueError("truncado")),
    )
    monkeypatch.setattr("data.rag_pipeline.native_page_text", lambda _page: "nativo")

    result = bronze_postgres.direct_ollama_pdf_text(tmp_path / "document.pdf")

    assert result == "nativo"


def test_direct_ollama_pdf_text_falls_back_to_native_text_on_ollama_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    page = tmp_path / "page-0001.pdf"
    page.write_bytes(b"page one")

    monkeypatch.setattr(
        "data.rag_pipeline.page_paths", lambda _path, _document_id: [page]
    )
    monkeypatch.setattr(
        "data.rag_pipeline.direct_ollama_glm_ocr",
        lambda _page: (_ for _ in ()).throw(requests.exceptions.ReadTimeout("timeout")),
    )
    monkeypatch.setattr("data.rag_pipeline.native_page_text", lambda _page: "nativo")

    result = bronze_postgres.direct_ollama_pdf_text(tmp_path / "document.pdf")

    assert result == "nativo"


def test_direct_ollama_pdf_text_stops_retrying_after_ollama_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    page_one = tmp_path / "page-0001.pdf"
    page_two = tmp_path / "page-0002.pdf"
    page_one.write_bytes(b"page one")
    page_two.write_bytes(b"page two")
    calls = 0

    monkeypatch.setattr(
        "data.rag_pipeline.page_paths",
        lambda _path, _document_id: [page_one, page_two],
    )

    def fail_once(_page):
        nonlocal calls
        calls += 1
        raise requests.exceptions.ReadTimeout("timeout")

    monkeypatch.setattr("data.rag_pipeline.direct_ollama_glm_ocr", fail_once)
    monkeypatch.setattr(
        "data.rag_pipeline.native_page_text",
        lambda page: "nativo" if page == page_one else "",
    )

    result = bronze_postgres.direct_ollama_pdf_text(tmp_path / "document.pdf")

    assert result == "nativo\n\n"
    assert calls == 1


def test_bronze_direct_mode_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("RAG_GLM_OCR_MODE", raising=False)
    assert not bronze_postgres.use_direct_ollama_glm_ocr()

    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    assert bronze_postgres.use_direct_ollama_glm_ocr()


def test_primary_content_falls_back_from_short_corrupted_glm() -> None:
    docling = "texto confiável " * 100
    glmocr = "texto  corrompido"

    content, source = bronze_postgres.select_primary_content(docling, glmocr)

    assert content == docling
    assert source == "docling_quality_fallback"
