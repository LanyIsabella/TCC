"""Contratos da infraestrutura; fakes aqui não são resultados experimentais."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from rag_eval.baseline import run, runtime


def test_unavailable_dependency_does_not_execute_or_fabricate_metrics() -> None:
    calls = []
    rows = run.evaluate_cases(
        [{"id": "q1"}],
        "agent",
        {"ready": False, "reason": "ollama_unavailable"},
        lambda *_args: calls.append(True),
    )
    assert calls == []
    assert rows == [
        {
            "case_id": "q1",
            "stage": "agent",
            "status": "blocked",
            "reason": "ollama_unavailable",
            "metrics": None,
        }
    ]


def test_failed_execution_is_not_counted_as_an_answer() -> None:
    def failing_worker(*_args):
        raise subprocess.TimeoutExpired("isolated evaluation worker", 1)

    rows = run.evaluate_cases(
        [{"id": "q1"}],
        "retrieval",
        {"ready": True},
        failing_worker,
    )
    assert rows[0]["status"] == "timeout"
    assert rows[0]["metrics"] is None
    assert "answer" not in rows[0]


def test_reserved_cases_require_explicit_evaluation_selection(tmp_path: Path) -> None:
    dataset = tmp_path / "queries.json"
    dataset.write_text(
        json.dumps(
            [
                {"id": "dev", "split": "development"},
                {"id": "test", "split": "reserved"},
            ]
        ),
        encoding="utf-8",
    )
    assert [q["id"] for q in run.load_cases(dataset, "development")] == ["dev"]
    with pytest.raises(ValueError, match="reserved"):
        run.load_cases(dataset, "reserved")
    assert run.load_cases(dataset, "reserved", allow_reserved=True)[0]["id"] == "test"


def test_readiness_does_not_expose_url_credentials_or_connection_error(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "environment",
        lambda _root: {
            "OLLAMA_HOST": "http://user:secret@example.invalid/private?token=secret",
            "OLLAMA_MODEL": "gemma4:e2b",
        },
    )
    monkeypatch.setattr(
        runtime.requests,
        "get",
        lambda *_a, **_k: (_ for _ in ()).throw(
            runtime.requests.ConnectionError("secret")
        ),
    )
    status = runtime.preflight(Path("."))
    assert not status["ready"]
    assert "secret" not in json.dumps(status)


def test_empty_or_malformed_ollama_response_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "environment",
        lambda _root: {
            "OLLAMA_HOST": "http://localhost:11434",
            "OLLAMA_MODEL": "gemma4:e2b",
        },
    )
    response = type(
        "Response",
        (),
        {
            "raise_for_status": lambda _self: None,
            "json": lambda _self: {"models": []},
        },
    )()
    monkeypatch.setattr(runtime.requests, "get", lambda *_a, **_k: response)
    assert runtime.preflight(Path("."))["reason"] == "required_models_missing"


def test_runtime_observes_production_tool_and_preserves_its_limits(monkeypatch):
    from data import rag_pipeline
    from rag_eval.baseline import snapshot
    from src.app.tools import rag_search

    readonly = object()
    monkeypatch.setattr(snapshot, "connect_readonly", lambda _root: readonly)

    def search(**parameters):
        assert rag_pipeline.connect() is readonly
        assert parameters["pages_limit"] == 6
        assert parameters["documents_limit"] == 1
        assert parameters["full_documents_limit"] == 0
        return [
            {
                "id": 3,
                "document_id": 1,
                "metadata": {"id": "abnt_nbr_6028"},
                "pages": [4],
                "page_context": [
                    {
                        "page_number": 4,
                        "direct_match": True,
                        "page_text": "Resumo.",
                    }
                ],
            }
        ]

    monkeypatch.setattr(rag_search, "search_documents", search)
    output = runtime.execute_production(
        {"question": "Como elaborar resumo?", "references": []},
        "retrieval",
        Path("."),
    )
    assert output["status"] == "executed_unreviewed"
    assert output["result"]["tool_payload"]["status"] == "success"
    assert (
        output["retrieval_traces"][0]["documents"][0]["standard_id"] == "abnt_nbr_6028"
    )
    assert output["metrics"]["factual_correctness"] is None


def test_agent_stage_uses_real_structured_response_adapter(monkeypatch):
    from src.app import agente
    from src.app.evidence import AgentAnswer

    class Executor:
        def invoke(self, payload):
            assert payload["messages"][-1]["content"] == "Pergunta"
            return {
                "messages": payload["messages"],
                "structured_response": AgentAnswer(
                    answer="Resposta sintética de teste.",
                    evidence_ids=[],
                ),
            }

    monkeypatch.setattr(agente, "build_agent", lambda: Executor())
    result = runtime.execute_stage({"question": "Pergunta"}, "agent")
    assert result["answer"] == "Resposta sintética de teste."
    assert result["evidences"] == []


def test_cli_writes_blocked_report_with_provenance_and_nonzero_exit(
    tmp_path, monkeypatch
):
    from rag_eval.baseline import snapshot

    baseline = tmp_path / "baseline"
    (baseline / "artifacts").mkdir(parents=True)
    (baseline / "queries.json").write_text(
        json.dumps(
            [
                {"id": "q1", "split": "development"},
            ]
        ),
        encoding="utf-8",
    )
    (baseline / "artifacts/initial_state.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr(run, "BASELINE", baseline)
    monkeypatch.setattr(snapshot, "source_hashes", lambda _root: {"src/x.py": "hash"})
    monkeypatch.setattr(
        runtime,
        "preflight",
        lambda _root: {
            "ready": False,
            "reason": "ollama_unavailable",
        },
    )
    monkeypatch.setattr(
        sys, "argv", ["baseline", "--stage", "agent", "--output", str(output)]
    )
    assert run.main() == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["implementation_source_hashes"] == {"src/x.py": "hash"}
    assert report["experimental_validation_complete"] is False
    assert report["cases"][0]["metrics"] is None
    assert len(report["dataset_sha256"]) == len(report["initial_state_sha256"]) == 64
