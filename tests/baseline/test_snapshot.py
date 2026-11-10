"""Contracts for the observational baseline; these tests never connect to production."""

from unittest.mock import MagicMock, patch

import pytest
from rag_eval.baseline import snapshot


def test_connection_is_repeatable_read_readonly_and_keeps_tuple_rows(tmp_path):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("on",)
    with patch("psycopg.connect", return_value=connection) as connect:
        result = snapshot.connect_readonly(tmp_path)
    assert result is connection
    kwargs = connect.call_args.kwargs
    assert "default_transaction_read_only=on" in kwargs["options"]
    assert "statement_timeout=" in kwargs["options"]
    assert kwargs["connect_timeout"] == 5
    assert "row_factory" not in kwargs
    assert connection.execute.call_args_list[0].args == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
    )
    assert connection.execute.call_args_list[1].args == ("SHOW transaction_read_only",)


def test_connection_fails_closed_when_readonly_is_not_confirmed(tmp_path):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("off",)
    with patch("psycopg.connect", return_value=connection):
        with pytest.raises(RuntimeError, match="read.only"):
            snapshot.connect_readonly(tmp_path)
    connection.close.assert_called_once()


def test_capture_refuses_to_overwrite_preserved_baseline(tmp_path, monkeypatch):
    preserved = tmp_path / "initial_state.json"
    preserved.write_text("preserved evidence", encoding="utf-8")
    monkeypatch.setattr(snapshot, "_git", lambda *_args: "isolated-git-state")
    monkeypatch.setattr(
        snapshot,
        "connect_readonly",
        lambda _root: pytest.fail(
            "Existing baseline must be protected before any database access"
        ),
    )
    with pytest.raises(FileExistsError):
        snapshot.capture(tmp_path, tmp_path)
    assert preserved.read_text(encoding="utf-8") == "preserved evidence"


def test_hash_distinguishes_absent_empty_and_unicode():
    assert snapshot.text_sha256(None) is None
    assert (
        snapshot.text_sha256("")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert snapshot.text_sha256("norma ç") != snapshot.text_sha256("norma c")


def test_source_fingerprint_tracks_production_and_excludes_secrets_and_fixtures(
    tmp_path,
    monkeypatch,
):
    included = [
        "src/app/model.py",
        "data/pipeline.py",
        "data/rag_schema.sql",
        "config/glmocr.yaml",
        "data/corpus_manifest.yaml",
        "pyproject.toml",
        "uv.lock",
        "rag_eval/pyproject.toml",
    ]
    excluded = [
        ".env",
        "tests/test_x.py",
        "rag_eval/baseline/queries.json",
        "data/raw/example.pdf",
    ]
    for name in included + excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")
    tracked = included + excluded + ["src/missing.py", ""]
    monkeypatch.setattr(snapshot, "_git", lambda *_args: "\0".join(tracked))
    actual = snapshot.source_hashes(tmp_path)
    assert set(actual) == set(included)
    assert actual["src/app/model.py"] == snapshot.file_sha256(tmp_path / included[0])


def test_printed_number_is_only_an_unreviewed_candidate():
    result = snapshot.printed_page_candidate("ABNT NBR 6028\nTexto normativo\n12")
    assert result["candidate"] == "12"
    assert result["review_status"] == "pending_human_review"
    assert "silver" in result["provenance"]
    assert snapshot.printed_page_candidate("nenhum número seguro")["candidate"] is None


def test_human_selection_has_40_unique_pages_and_three_from_every_standard():
    documents = [{"document_id": i, "standard_id": f"norma_{i}"} for i in range(10)]
    pages = []
    for document in documents:
        for number in range(1, 7):
            pages.append(
                {
                    "document_id": document["document_id"],
                    "physical_page": number,
                    "extractions": [
                        {
                            "structured_output": {
                                "completion_unconfirmed": number == 2
                            },
                            "quality_metrics": {"requires_manual_review": number == 3},
                            "extracted_markdown": "| a | b |" if number == 4 else "",
                        }
                    ],
                }
            )
    selected = snapshot.select_human_reference(documents, pages)
    assert len(selected) == 40
    assert len({(p["document_id"], p["physical_page"]) for p in selected}) == 40
    for document in documents:
        assert sum(p["document_id"] == document["document_id"] for p in selected) >= 3
    assert all(
        p["transcription"] is None and p["review_status"] == "pending_human_review"
        for p in selected
    )
    assert sum(p["selection_group"] == "risk_or_structure" for p in selected) == 10
    assert all(p["transcription_origin"] is None for p in selected)


def test_reference_selection_does_not_silently_accept_insufficient_pages():
    with pytest.raises(ValueError, match="40"):
        snapshot.select_human_reference([{"document_id": 1, "standard_id": "a"}], [])


def test_sensitive_configuration_keys_and_personal_paths_are_redacted():
    value = {
        "model": "nomic",
        "password": "do-not-export",
        "nested": {"api_key": "secret"},
        "error": r"failed C:\Users\private\doc.pdf",
    }
    cleaned = snapshot.sanitize(value)
    assert cleaned["model"] == "nomic"
    assert "do-not-export" not in str(cleaned)
    assert "private" not in str(cleaned)
    assert "secret" not in str(cleaned)


def test_observed_source_text_is_preserved_exactly_even_if_it_contains_paths():
    text = r"Example C:\Users\Author\file.pdf"
    assert snapshot.sanitize({"extracted_text": text})["extracted_text"] == text


def test_capture_rolls_back_closes_and_exports_expected_contract(tmp_path):
    connection = MagicMock()
    documents = [
        {
            "document_id": 1,
            "file_name": "a.pdf",
            "page_count": 40,
            "standard_id": "a",
            "sha256": "abc",
        }
    ]
    rows = [documents, [], [], [], [], {"transaction_read_only": "on"}]

    def read(_connection, query):
        value = rows.pop(0)
        return value if isinstance(value, list) else [value]

    with (
        patch.object(snapshot, "connect_readonly", return_value=connection),
        patch.object(snapshot, "_read_rows", side_effect=read),
        patch.object(snapshot, "_git", return_value="fixture"),
        patch.object(snapshot, "file_sha256", return_value="abc"),
        patch.object(snapshot, "source_hashes", return_value={"src/a.py": "abc"}),
        patch.object(snapshot, "current_configuration", return_value={}),
    ):
        result = snapshot.capture(tmp_path, tmp_path / "output")
    assert (
        set(
            (
                "documents",
                "pages",
                "db_summary",
                "git",
                "configuration",
                "source_hashes",
            )
        )
        <= result.keys()
    )
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    assert (tmp_path / "output/initial_state.json").is_file()
    assert (tmp_path / "output/human_reference.json").is_file()


def test_capture_failure_still_rolls_back_and_closes(tmp_path):
    connection = MagicMock()
    with (
        patch.object(snapshot, "connect_readonly", return_value=connection),
        patch.object(snapshot, "_git", return_value="fixture"),
        patch.object(snapshot, "_read_rows", side_effect=RuntimeError("broken read")),
    ):
        with pytest.raises(RuntimeError, match="broken read"):
            snapshot.capture(tmp_path, tmp_path / "output")
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    assert not (tmp_path / "output").exists()


def test_summary_counts_only_active_gold_pages_and_preserves_flags():
    pages = [
        {
            "document_id": 1,
            "physical_page": 1,
            "extractions": [
                {
                    "extraction_id": 5,
                    "quality_metrics": {"requires_manual_review": True},
                    "structured_output": {"completion_unconfirmed": True},
                },
                {
                    "extraction_id": 6,
                    "quality_metrics": {"requires_manual_review": True},
                    "structured_output": {},
                },
            ],
        }
    ]
    variants = [{"document_id": 1, "extraction_id": 5, "is_active": True}]
    summary = snapshot.summarize([{"document_id": 1}], pages, variants, [])
    assert summary["active_gold_requires_manual_review"] == 1
    assert summary["active_gold_completion_unconfirmed"] == 1
    assert summary["silver_page_extractions"] == 2


def test_page_reference_carries_document_hash_without_inventing_page_hash():
    pages = snapshot._assemble_pages(
        [{"document_id": 1, "standard_id": "a", "sha256": "abc", "page_count": 1}],
        [],
        [],
        [],
    )
    assert pages[0]["document_sha256"] == "abc"
    assert pages[0]["physical_page"] == 1
    assert pages[0]["extractions"] == []


def test_static_source_observation_does_not_execute_modules(tmp_path):
    pipeline = tmp_path / "data/rag_pipeline.py"
    tool = tmp_path / "src/app/tools/rag_search.py"
    pipeline.parent.mkdir(parents=True)
    tool.parent.mkdir(parents=True)
    pipeline.write_text(
        "RRF_K = 60.0\n"
        "raise RuntimeError('must never execute')\n"
        "def search_documents(question, pages_limit=12, documents_limit=5):\n"
        "    pages_limit = max(1, min(int(pages_limit), 50))\n"
        "    return []\n",
        encoding="utf-8",
    )
    tool.write_text("MAX_PAGE_TEXT_CHARS = 1800\n", encoding="utf-8")
    observed = snapshot.source_configuration(tmp_path)
    values = observed["data/rag_pipeline.py"]["values"]
    assert values["RRF_K"] == 60.0
    assert values["search_documents_defaults"]["pages_limit"] == 12
    assert values["retrieval_limits_source"] == [
        "pages_limit = max(1, min(int(pages_limit), 50))"
    ]
    assert observed["src/app/tools/rag_search.py"]["sha256"] == snapshot.file_sha256(
        tool
    )
