from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from data.rag_pipeline import (
    OllamaEmbedder,
    comparison_is_ready,
    deterministic_metrics,
    direct_ollama_glm_ocr,
    estimated_token_count,
    evaluate_page,
    extractor_status_query,
    is_gold_ready,
    page_is_eligible,
    parse_json_response,
    reconstruct_page_content,
    use_direct_ollama_glm_ocr,
    vector_literal,
)


def test_vector_literal_preserves_dimension() -> None:
    vector = [float(index) for index in range(768)]

    literal = vector_literal(vector)

    assert literal.startswith("[")
    assert literal.endswith("]")
    assert len(literal[1:-1].split(",")) == 768


def test_deterministic_metrics_are_separate_from_agent_score() -> None:
    metrics = deterministic_metrics("texto de referência", "texto de referência")

    assert metrics["cer"] == 0
    assert metrics["wer"] == 0
    assert metrics["normalized_similarity"] == 1
    assert "overall_score" not in metrics


def test_evaluation_json_is_validated() -> None:
    payload = {
        "overall_score": 91.5,
        "confidence": 88,
        "scores": {
            "textual_fidelity": 94,
            "content_completeness": 92,
            "reading_order": 90,
            "structural_preservation": 87,
            "lists_preservation": 90,
            "tables_preservation": None,
            "numbers_and_references": 96,
            "duplication_control": 100,
            "noise_control": 89,
            "hallucination_control": 100,
        },
        "justification": "ok",
    }

    assert parse_json_response(json.dumps(payload))["overall_score"] == 91.5


def test_evaluation_rejects_incomplete_criteria() -> None:
    payload = {
        "overall_score": 91.5,
        "confidence": 88,
        "scores": {"textual_fidelity": 94},
        "justification": "ok",
    }

    with pytest.raises(ValueError, match="Critérios ausentes"):
        parse_json_response(json.dumps(payload))


def test_evaluation_normalizes_top_level_criteria() -> None:
    payload = {
        "overall_score": 90,
        "confidence": 90,
        "textual_fidelity": 90,
        "content_completeness": 90,
        "reading_order": 90,
        "structural_preservation": 90,
        "lists_preservation": None,
        "tables_preservation": None,
        "numbers_and_references": 90,
        "duplication_control": 90,
        "noise_control": 90,
        "hallucination_control": 90,
        "justification": "ok",
    }

    assert parse_json_response(json.dumps(payload))["scores"]["noise_control"] == 90


def test_page_reconstruction_preserves_order_and_error_markers() -> None:
    pages = [
        {"page_number": 2, "status": "error", "text": None},
        {"page_number": 1, "status": "success", "text": "primeira"},
    ]

    result = reconstruct_page_content(pages)

    assert result.index("<<<PÁGINA 1>>>") < result.index("<<<PÁGINA 2")
    assert "primeira" in result
    assert "ERRO DE EXTRAÇÃO" in result


def test_token_estimate_counts_words_and_punctuation() -> None:
    assert estimated_token_count("ABNT: 6023.") == 4


def test_glmocr_config_maps_layout_labels_to_tasks() -> None:
    config = yaml.safe_load(Path("config/glmocr.yaml").read_text(encoding="utf-8"))
    mapping = config["pipeline"]["layout"]["label_task_mapping"]

    assert "paragraph_title" in mapping["text"]
    assert mapping["table"] == ["table"]
    assert "display_formula" in mapping["formula"]
    assert config["pipeline"]["max_workers"] == 1
    assert config["pipeline"]["ocr_api"]["retry_max_attempts"] == 0
    assert config["pipeline"]["page_loader"]["pdf_dpi"] == 120
    assert config["pipeline"]["page_loader"]["max_pixels"] == 4000000


def test_evaluator_uses_deterministic_json_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs: object) -> None:
            calls.update(kwargs)

        def invoke(self, _messages: object) -> object:
            scores = {
                "textual_fidelity": 90,
                "content_completeness": 90,
                "reading_order": 90,
                "structural_preservation": 90,
                "lists_preservation": 90,
                "tables_preservation": None,
                "numbers_and_references": 90,
                "duplication_control": 90,
                "noise_control": 90,
                "hallucination_control": 90,
            }
            return type("Response", (), {"content": json.dumps({
                "overall_score": 90,
                "confidence": 90,
                "scores": scores,
                "justification": "ok",
            })})()

    monkeypatch.setattr("langchain_ollama.ChatOllama", FakeModel)
    image = tmp_path / "page.png"
    image.write_bytes(b"fake-image")

    evaluation, method = evaluate_page(
        image, "texto nativo confiável", "extração", "gemma"
    )

    assert method == "page_image"
    assert evaluation["overall_score"] == 90
    assert calls["temperature"] == 0
    assert calls["reasoning"] is False
    assert calls["format"] == "json"


def test_embedding_request_uses_required_prefix_and_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"embeddings": [[0.0] * 768]}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("data.rag_pipeline.requests.post", fake_post)
    embedder = OllamaEmbedder()
    embedder.embed("conteúdo", "search_document: ")

    assert calls[0][0].endswith("/api/show")
    assert calls[1][0] == "http://localhost:11434/api/embed"
    body = calls[1][1]["json"]
    assert body["input"] == "search_document: conteúdo"
    assert body["truncate"] is False


def test_embedding_rejects_wrong_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"embeddings": [[0.0] * 767]}

    def fake_post(_url: str, **_kwargs: object) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("data.rag_pipeline.requests.post", fake_post)
    embedder = OllamaEmbedder()

    with pytest.raises(ValueError, match="Dimensão inválida"):
        embedder.embed("conteúdo", "search_document: ")


def test_schema_declares_hybrid_retrieval_contract() -> None:
    schema = Path("data/rag_schema.sql").read_text(encoding="utf-8")
    pipeline = Path("data/rag_pipeline.py").read_text(encoding="utf-8")

    assert "silver.silver_documents" in schema
    assert "gold.gold_rag_documents" in schema
    assert "USING hnsw (embedding vector_cosine_ops)" in schema
    assert "USING gin (search_vector)" in schema
    assert "websearch_to_tsquery('portuguese'" in pipeline
    assert "search_document: " in pipeline
    assert "search_query: " in pipeline


def test_rag_tool_returns_complete_document(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.tools import rag_search

    monkeypatch.setattr(
        rag_search,
        "search_documents",
        lambda question, pages_limit, documents_limit: [
            {
                "document_id": 8,
                "pages": [5],
                "full_text": "<<<PÁGINA 1>>>\nconteúdo integral",
            }
        ],
    )

    result = rag_search.rag_document_search.invoke(
        {"question": "pergunta", "pages_limit": 1, "documents_limit": 1}
    )

    assert "conteúdo integral" in result
    assert '"pages": [5]' in result


def test_gold_gate_requires_successful_evaluation() -> None:
    assert not is_gold_ready("success", 0, 0, [])
    assert is_gold_ready("success", 2, 2, ["success", "success"])
    assert not is_gold_ready("success", 2, 2, ["success", "pending"])
    assert is_gold_ready("success", 2, 2, ["pending", "error"], True)
    assert not is_gold_ready("error", 2, 1, ["success"], True)


def test_retry_only_selects_pending_or_explicit_error_pages() -> None:
    assert page_is_eligible("pending", False, False)
    assert not page_is_eligible("success", True, False)
    assert not page_is_eligible("error", False, False)
    assert page_is_eligible("error", True, False)
    assert page_is_eligible("success", False, True)


def test_comparison_gate_requires_both_complete_and_evaluated_extractors() -> None:
    complete = [
        ("docling", "success", 2, 2, 2, 2),
        ("glm_ocr", "success", 2, 2, 2, 2),
    ]
    missing_glm = complete[:1]
    incomplete_glm = [
        complete[0],
        ("glm_ocr", "error", 2, 2, 1, 0),
    ]

    assert comparison_is_ready(complete)
    assert not comparison_is_ready(missing_glm)
    assert not comparison_is_ready(incomplete_glm)


def test_direct_glm_ocr_uses_ollama_generate_and_rejects_truncation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "texto GLM", "done": True, "done_reason": "stop"}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse()

    image = tmp_path / "page.png"
    image.write_bytes(b"fake-image")
    monkeypatch.setattr("data.rag_pipeline.requests.post", fake_post)

    text, markdown, structured = direct_ollama_glm_ocr(image)

    assert (text, markdown, structured) == ("texto GLM", "texto GLM", None)
    assert calls[0][0] == "http://localhost:11434/api/generate"
    body = calls[0][1]["json"]
    assert body["model"] == "glm-ocr:latest"
    assert body["stream"] is False
    assert body["images"]

    class TruncatedResponse(FakeResponse):
        def json(self) -> dict:
            return {"response": "parcial", "done": True, "done_reason": "length"}

    monkeypatch.setattr(
        "data.rag_pipeline.requests.post", lambda *_args, **_kwargs: TruncatedResponse()
    )
    with pytest.raises(ValueError, match="trunc"):
        direct_ollama_glm_ocr(image)


def test_direct_glm_ocr_mode_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_GLM_OCR_MODE", raising=False)
    assert not use_direct_ollama_glm_ocr()

    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    assert use_direct_ollama_glm_ocr()


def test_global_validation_query_does_not_use_untyped_null_parameter() -> None:
    query, params = extractor_status_query(None)

    assert "IS NULL" not in query
    assert params == [["docling", "glm_ocr"]]

    filtered_query, filtered_params = extractor_status_query(8)
    assert "e.document_id = %s" in filtered_query
    assert filtered_params == [["docling", "glm_ocr"], 8]


def test_validation_status_query_ignores_pdf_reader_reference_pages() -> None:
    from data.rag_pipeline import page_status_query

    query, params = page_status_query(8)

    assert "p.extractor = ANY(%s)" in query
    assert params == [["docling", "glm_ocr"], 8]
