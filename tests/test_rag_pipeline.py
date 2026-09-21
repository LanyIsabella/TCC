from __future__ import annotations

import json
from base64 import b64decode
from pathlib import Path

import pytest
import requests
import yaml
from data.rag_pipeline import (
    OllamaEmbedder,
    comparison_is_ready,
    deterministic_metrics,
    direct_ollama_glm_ocr,
    estimated_token_count,
    evaluate_page,
    extract_page,
    extractor_status_query,
    is_gold_ready,
    is_likely_blank_page,
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


def test_evaluator_has_deterministic_fallback_on_invalid_model_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class InvalidModel:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def invoke(self, _messages: object) -> object:
            raise ValueError("JSON inválido")

    monkeypatch.setattr("langchain_ollama.ChatOllama", InvalidModel)
    image = tmp_path / "page.png"
    image.write_bytes(b"fake-image")

    evaluation, method = evaluate_page(
        image, "texto nativo confiável", "extração", "gemma"
    )

    assert method == "deterministic_fallback"
    assert evaluation["overall_score"] == 50.0
    assert evaluation["requires_manual_review"] is True
    assert evaluation["confidence"] == 0.0


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
    assert calls[1][0].endswith("/api/embed")
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


def test_embedding_splits_text_when_ollama_context_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            if "error" in self.body:
                raise requests.HTTPError("400 Bad Request", response=self)

        def json(self) -> dict[str, object]:
            return self.body

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        if url.endswith("/api/show"):
            return FakeResponse({"digest": "test-digest"})
        body = kwargs["json"]
        assert isinstance(body, dict)
        value = str(body["input"])
        calls.append(value)
        if len(value) > 180:
            return FakeResponse(
                {"error": "the input length exceeds the context length"}
            )
        vector = [1.0 if value.startswith("search_document: A") else 0.5] + [
            0.0
        ] * 767
        return FakeResponse({"embeddings": [vector]})

    monkeypatch.setattr("data.rag_pipeline.requests.post", fake_post)
    embedder = OllamaEmbedder()

    vector = embedder.embed("A" * 150 + " " + "B" * 149, "search_document: ")

    assert len(calls) == 3
    assert len(vector) == 768
    assert sum(value * value for value in vector) == pytest.approx(1.0)


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
        lambda question, pages_limit, documents_limit, **_kwargs: [
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


def test_rag_tool_validates_and_compacts_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.tools import rag_search

    monkeypatch.setattr(
        rag_search,
        "search_documents",
        lambda **_kwargs: [
            {
                "document_id": 19,
                "title": "ABNT NBR 6028",
                "version": "2021",
                "metadata": {"id": "abnt_nbr_6028", "issuer": "ABNT"},
                "pages": [4],
                "matched_pages": [{"page_number": 4, "direct_match": True}],
                "page_context": [
                    {"page_number": 4, "direct_match": True, "page_text": "evidence"}
                ],
                "full_text": "x" * 20_000,
                "embedding": [0.0] * 768,
            }
        ],
    )

    result = json.loads(
        rag_search.rag_document_search.invoke({"question": "resumo"})
    )

    assert result["status"] == "success"
    document = result["documents"][0]
    assert document["title"] == "ABNT NBR 6028"
    assert document["full_text"] is None
    assert document["page_context"][0]["page_text"] == "evidence"
    assert "embedding" not in document


def test_rag_tool_returns_structured_error_for_invalid_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.tools import rag_search

    monkeypatch.setattr(rag_search, "search_documents", lambda **_kwargs: {"bad": True})

    result = json.loads(
        rag_search.rag_document_search.invoke({"question": "resumo"})
    )

    assert result["status"] == "error"
    assert result["evidence_found"] is False


def test_gold_gate_requires_successful_evaluation() -> None:
    assert not is_gold_ready("success", 0, 0, [])
    assert is_gold_ready("success", 2, 2, ["success", "success"])
    assert not is_gold_ready("success", 2, 2, ["success", "pending"])
    assert is_gold_ready("success", 2, 2, ["pending", "error"], True)
    assert not is_gold_ready("error", 2, 1, ["success"], True)


def test_retry_recovers_pending_error_and_interrupted_pages() -> None:
    assert page_is_eligible("pending", False, False)
    assert not page_is_eligible("success", True, False)
    assert not page_is_eligible("error", False, False)
    assert page_is_eligible("error", True, False)
    assert page_is_eligible("processing", True, False)
    assert not page_is_eligible("processing", False, False)
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
    assert body["options"]["num_ctx"] == 16384

    class TruncatedResponse(FakeResponse):
        def json(self) -> dict:
            return {"response": "parcial", "done": True, "done_reason": "length"}

    def truncated_post(url: str, **kwargs: object) -> TruncatedResponse:
        calls.append((url, kwargs))
        return TruncatedResponse()

    monkeypatch.setattr("data.rag_pipeline.requests.post", truncated_post)
    with pytest.raises(ValueError, match="trunc"):
        direct_ollama_glm_ocr(image)
    assert calls[-2][1]["json"]["options"]["num_predict"] == 16384
    assert calls[-1][1]["json"]["options"]["num_predict"] == 32768

    class UnconfirmedResponse(FakeResponse):
        def json(self) -> dict:
            return {"response": "texto sem metadado final", "done": False}

    monkeypatch.setattr(
        "data.rag_pipeline.requests.post",
        lambda *_args, **_kwargs: UnconfirmedResponse(),
    )
    _, _, diagnostics = direct_ollama_glm_ocr(image)
    assert diagnostics == {"completion_unconfirmed": True}


def test_blank_page_is_detected(tmp_path: Path) -> None:
    page = tmp_path / "blank.png"
    page.write_bytes(
        b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAFklEQVR4nGP8//8/"
            "A27AhEeOYeRKAwCl4wMRx3ocVQAAAABJRU5ErkJggg=="
        )
    )

    assert is_likely_blank_page(page)
    assert direct_ollama_glm_ocr(page) == ("", "", None)


def test_extract_page_falls_back_to_docling_on_ollama_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = tmp_path / "page-0001.pdf"
    page.write_bytes(b"page one")

    class Document:
        def export_to_markdown(self) -> str:
            return "texto Docling"

    class Result:
        document = Document()

    class Converter:
        def convert(self, _page: Path) -> Result:
            return Result()

    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    monkeypatch.setattr(
        "data.rag_pipeline.direct_ollama_glm_ocr",
        lambda _page: (_ for _ in ()).throw(requests.exceptions.ReadTimeout("timeout")),
    )

    text, markdown, diagnostics = extract_page(
        "glm_ocr", page, Converter(), None
    )

    assert text == markdown == "texto Docling"
    assert diagnostics == {
        "fallback": "docling",
        "error": "timeout",
        "error_type": "ReadTimeout",
    }


def test_direct_glm_ocr_mode_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_GLM_OCR_MODE", raising=False)
    assert not use_direct_ollama_glm_ocr()

    monkeypatch.setenv("RAG_GLM_OCR_MODE", "direct_ollama")
    assert use_direct_ollama_glm_ocr()


def test_global_validation_query_does_not_use_untyped_null_parameter() -> None:
    query, params = extractor_status_query(None)

    assert "IS NULL" not in query
    assert "SUM(total_pages)::bigint" in query
    assert params == [["docling", "glm_ocr"]]

    filtered_query, filtered_params = extractor_status_query(8)
    assert "e.document_id = %s" in filtered_query
    assert filtered_params == [["docling", "glm_ocr"], 8]


def test_validation_status_query_ignores_pdf_reader_reference_pages() -> None:
    from data.rag_pipeline import page_status_query

    query, params = page_status_query(8)

    assert "p.extractor = ANY(%s)" in query
    assert params == [["docling", "glm_ocr"], 8]
