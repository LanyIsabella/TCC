"""Contratos determinísticos de fingerprints e observação de digests."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from data import extraction_provenance as provenance


def _snapshot_worker(source, directory):
    snapshot, digest = provenance.original_snapshot(Path(source), Path(directory))
    return str(snapshot), digest


@pytest.fixture(autouse=True)
def offline_metadata_tests(monkeypatch):
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("Synthetic tests do not access the network")

    monkeypatch.setattr(requests.sessions.Session, "send", unavailable)


def test_fingerprint_is_canonical_but_preserves_content_and_sequence():
    # Published protocol vector: changes require a new fingerprint scheme.
    assert provenance.fingerprint("v1", "ação\n") == (
        "7c6385edfa2cf7f947506207b5baff27bc1eac5e9a36f7b6dd2646ca81dfff1b"
    )
    assert provenance.fingerprint("v1", {"a": 1, "b": 2}) == provenance.fingerprint(
        "v1", {"b": 2, "a": 1}
    )
    assert provenance.fingerprint("v1", "citação\n") != provenance.fingerprint(
        "v1", "citação"
    )
    assert provenance.fingerprint("v1", [1, 2]) != provenance.fingerprint("v1", [2, 1])
    assert provenance.fingerprint("v1", "x") != provenance.fingerprint("v2", "x")


def test_non_finite_configuration_is_not_fingerprinted():
    with pytest.raises(ValueError):
        provenance.fingerprint("v1", {"temperature": float("nan")})


@pytest.mark.parametrize(
    "provided,expected",
    [("unknown", None), ("sha256:" + "a" * 64, "a" * 64), ("A" * 64, "a" * 64)],
)
def test_configured_digest_requires_actual_sha256(monkeypatch, provided, expected):
    monkeypatch.setenv("TCC_SYNTHETIC_DIGEST", provided)
    assert (
        provenance.model_digest("synthetic", "http://unused", "TCC_SYNTHETIC_DIGEST")
        == expected
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"models": [None]},
        {"models": [{"name": "synthetic:latest", "digest": "unknown"}]},
        {"models": None},
        [],
    ],
)
def test_malformed_model_registry_is_unknown(monkeypatch, payload):
    monkeypatch.delenv("TCC_SYNTHETIC_DIGEST", raising=False)
    monkeypatch.setattr(
        provenance.requests,
        "get",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: payload
        ),
    )
    assert (
        provenance.model_digest("synthetic", "http://unused", "TCC_SYNTHETIC_DIGEST")
        is None
    )


def test_model_registry_alias_is_observed_without_inference(monkeypatch):
    monkeypatch.delenv("TCC_SYNTHETIC_DIGEST", raising=False)
    monkeypatch.setattr(
        provenance.requests,
        "get",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"models": [{"name": "synthetic:latest", "digest": "b" * 64}]},
        ),
    )
    assert (
        provenance.model_digest("synthetic", "http://unused", "TCC_SYNTHETIC_DIGEST")
        == "b" * 64
    )


def test_model_registry_timeout_does_not_invent_a_digest(monkeypatch):
    monkeypatch.delenv("TCC_SYNTHETIC_DIGEST", raising=False)

    def unavailable(*a, **kw):
        raise requests.ReadTimeout("synthetic offline registry")

    monkeypatch.setattr(provenance.requests, "get", unavailable)
    assert (
        provenance.model_digest("synthetic", "http://unused", "TCC_SYNTHETIC_DIGEST")
        is None
    )


def test_evaluation_requires_an_explicitly_configured_model(monkeypatch):
    from data import rag_pipeline

    monkeypatch.delenv("RAG_EVALUATION_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(ValueError, match="Defina"):
        rag_pipeline.evaluation_configuration()


def test_original_snapshots_preserve_versions_and_deduplicate_equal_bytes(tmp_path):
    original = tmp_path / "original.pdf"
    cache = tmp_path / "snapshots"
    original.write_bytes(b"source A")
    first, first_hash = provenance.original_snapshot(original, cache)
    original.write_bytes(b"source B")
    second, second_hash = provenance.original_snapshot(original, cache)
    assert first_hash != second_hash and first.read_bytes() == b"source A"
    assert second.read_bytes() == b"source B"
    assert provenance.original_snapshot(original, cache) == (second, second_hash)
    assert len(list(cache.iterdir())) == 2
    second.write_bytes(b"synthetic cache corruption")
    with pytest.raises(ValueError, match="corrompido"):
        provenance.original_snapshot(original, cache)
    assert second.read_bytes() == b"synthetic cache corruption"
    assert not list(cache.glob("*.tmp"))


def test_missing_original_leaves_no_partial_snapshot(tmp_path):
    cache = tmp_path / "snapshots"
    with pytest.raises(FileNotFoundError):
        provenance.original_snapshot(tmp_path / "missing.pdf", cache)
    assert not list(cache.iterdir())


def test_snapshot_copy_failure_removes_its_temporary_file(tmp_path, monkeypatch):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"source A")

    def fail_copy(*_args, **_kwargs):
        raise OSError("synthetic copy failure")

    monkeypatch.setattr(provenance.shutil, "copyfileobj", fail_copy)
    with pytest.raises(OSError, match="synthetic copy failure"):
        provenance.original_snapshot(original, tmp_path / "snapshots")
    assert not list((tmp_path / "snapshots").glob("*.tmp"))


def test_snapshot_keeps_copied_bytes_when_raw_changes_after_copy(tmp_path, monkeypatch):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"source A")

    def copy_then_change(source, target):
        target.write(source.read())
        original.write_bytes(b"source B")

    monkeypatch.setattr(provenance.shutil, "copyfileobj", copy_then_change)
    snapshot, digest = provenance.original_snapshot(original, tmp_path / "snapshots")
    assert original.read_bytes() == b"source B"
    assert snapshot.read_bytes() == b"source A"
    assert digest == provenance.file_digest(snapshot)


def test_snapshot_does_not_reopen_target_after_its_own_atomic_publish(
    tmp_path, monkeypatch
):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"source A")
    real_digest = provenance.file_digest
    digest_calls = []

    def digest(path):
        digest_calls.append(Path(path))
        if Path(path).suffix == ".pdf":
            raise AssertionError("the publishing process already owns these bytes")
        return real_digest(path)

    monkeypatch.setattr(provenance, "file_digest", digest)
    snapshot, expected = provenance.original_snapshot(
        original, tmp_path / "snapshots"
    )

    assert snapshot.name == f"{expected}.pdf"
    assert digest_calls and all(path.suffix == ".tmp" for path in digest_calls)


def test_independent_processes_publish_one_valid_snapshot(tmp_path):
    original = tmp_path / "original.pdf"
    cache = tmp_path / "snapshots"
    original.write_bytes(b"source A")
    context = get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as workers:
        results = list(
            workers.map(
                _snapshot_worker,
                [str(original)] * 4,
                [str(cache)] * 4,
            )
        )
    assert len({path for path, _digest in results}) == 1
    assert len({digest for _path, digest in results}) == 1
    published = Path(results[0][0])
    assert published.read_bytes() == b"source A"
    assert len(list(cache.glob("*.pdf"))) == 1
    assert not list(cache.glob("*.tmp"))


def test_invalidate_evaluations_defaults_to_non_forced_invalidation():
    calls = []

    class Connection:
        def execute(self, query, parameters):
            calls.append((query, parameters))

    provenance.invalidate_evaluations(
        Connection(), "config-fingerprint", ["pdf_reader"], None
    )

    assert len(calls) == 1
    assert calls[0][1][-1] is False


def test_equivalent_snapshot_publish_race_keeps_one_valid_copy(tmp_path, monkeypatch):
    from pathlib import Path

    original = tmp_path / "original.pdf"
    original.write_bytes(b"source A")

    def competing_writer(temporary, destination):
        destination.write_bytes(temporary.read_bytes())
        raise FileExistsError("synthetic equivalent concurrent writer")

    monkeypatch.setattr(Path, "rename", competing_writer)
    snapshot, digest = provenance.original_snapshot(original, tmp_path / "snapshots")
    assert snapshot.read_bytes() == original.read_bytes()
    assert digest == provenance.file_digest(original)
    assert len(list(snapshot.parent.iterdir())) == 1


@pytest.mark.parametrize("context,prediction", [(None, None), ("8192", "1024")])
def test_evaluation_metadata_matches_parameters_actually_sent(
    monkeypatch, tmp_path, context, prediction
):
    import json

    import langchain_ollama
    from data import rag_pipeline

    monkeypatch.setenv("RAG_EVALUATION_MODEL", "synthetic-evaluator")
    for key, value in [
        ("RAG_EVALUATION_CONTEXT", context),
        ("RAG_EVALUATION_MAX_TOKENS", prediction),
    ]:
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(provenance, "model_digest", lambda *_: "a" * 64)
    monkeypatch.setattr(
        rag_pipeline, "image_data_url", lambda _: "data:image/png;base64,fixture"
    )
    sent = {}

    def model(**kwargs):
        sent.update(kwargs)
        payload = {
            "overall_score": 81,
            "confidence": 90,
            "scores": dict.fromkeys(rag_pipeline.EVALUATION_SCORE_KEYS, 81),
            "justification": "synthetic fixture",
        }
        return SimpleNamespace(
            invoke=lambda _: SimpleNamespace(content=json.dumps(payload))
        )

    monkeypatch.setattr(langchain_ollama, "ChatOllama", model)
    profile = rag_pipeline.evaluation_configuration()
    rag_pipeline.evaluate_page(
        tmp_path / "synthetic.png", "native", "text", profile["model"]
    )
    for key in [
        "model",
        "temperature",
        "reasoning",
        "format",
        "num_ctx",
        "num_predict",
    ]:
        assert profile[key] == sent[key]
