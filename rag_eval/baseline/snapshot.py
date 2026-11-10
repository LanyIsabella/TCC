"""Read-only, source-preserving inventory; never imports the ingestion pipeline."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SAFE_SETTINGS = (
    "OLLAMA_MODEL",
    "OLLAMA_TEMPERATURE",
    "RAG_CONTEXT_TOKEN_LIMIT",
    "RAG_GLM_OCR_MODE",
    "GLMOCR_DIRECT_CONTEXT",
    "GLMOCR_DIRECT_MAX_TOKENS",
    "GLMOCR_DIRECT_RETRY_MAX_TOKENS",
    "GLMOCR_DIRECT_TIMEOUT",
    "GLMOCR_MODEL",
    "GLMOCR_KEEP_ALIVE",
    "RAG_EVALUATION_CONTEXT",
    "RAG_EVALUATION_MAX_TOKENS",
    "RAG_EVALUATION_MODEL",
    "EMBEDDING_MODEL_DIGEST",
    "OLLAMA_EMBED_TIMEOUT",
    "RAG_EVIDENCE_PAGES_PER_DOCUMENT",
)
PACKAGES = (
    "psycopg",
    "pypdf",
    "PyMuPDF",
    "docling",
    "glmocr",
    "PyYAML",
    "langchain",
    "langchain-ollama",
    "requests",
    "pytest",
    "python-dotenv",
)


def connect_readonly(root: Path):
    """Start a tuple-row, consistent read transaction, failing closed."""
    import psycopg

    settings = {**dotenv_values(root / ".env"), **os.environ}
    connection = psycopg.connect(
        host=settings.get("DB_HOST"),
        port=settings.get("DB_PORT"),
        dbname=settings.get("DB_NAME", "postgres"),
        user=settings.get("DB_USER"),
        password=settings.get("DB_PASSWORD"),
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    )
    try:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if connection.execute("SHOW transaction_read_only").fetchone()[0] != "on":
            raise RuntimeError("Database read-only transaction was not confirmed")
    except BaseException:
        connection.close()
        raise
    return connection


def text_sha256(value: str | None) -> str | None:
    return None if value is None else hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def sanitize(value: Any) -> Any:
    """Keep captured evidence, excluding credentials and personal machine paths."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.search(
                r"password|secret|api[_-]?key|credential|authorization", key, re.I
            )
            else item
            if key
            in {
                "extracted_text",
                "extracted_markdown",
                "full_text",
                "full_markdown",
                "page_text",
            }
            else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\s\"']+", "[PERSONAL_PATH]", value)
    return value


def printed_page_candidate(text: str | None) -> dict[str, Any]:
    lines = (text or "").strip().splitlines()
    candidates = [
        line.strip()
        for line in lines[-4:]
        if re.fullmatch(r"\d{1,3}|[ivxlcdm]{1,8}", line.strip(), re.I)
    ]
    return {
        "candidate": candidates[-1] if candidates else None,
        "provenance": "automatic_footer_candidate_from_silver_pdf_reader_text",
        "review_status": "pending_human_review",
    }


def _read_rows(connection, query: str) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        return cursor.fetchall()


def _page_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    record.pop("source_page_path", None)
    record["text_sha256"] = text_sha256(row.get("extracted_text"))
    record["markdown_sha256"] = text_sha256(row.get("extracted_markdown"))
    record["historical_configuration"] = None
    record["historical_configuration_provenance"] = "not_persisted_in_extraction_schema"
    return record


def _assemble_pages(documents, extractions, variants, indexes):
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in extractions:
        grouped.setdefault((row["document_id"], row["page_number"]), []).append(
            _page_record(row)
        )
    active = {row["document_id"]: row for row in variants if row["is_active"]}
    pages = []
    for document in documents:
        document_id = document["document_id"]
        for number in range(1, document["page_count"] + 1):
            extracted = grouped.get((document_id, number), [])
            native = next(
                (row for row in extracted if row["extractor"] == "pdf_reader"), {}
            )
            active_variant = active.get(document_id, {})
            pages.append(
                {
                    "document_id": document_id,
                    "standard_id": document["standard_id"],
                    "document_sha256": document.get("sha256"),
                    "physical_page": number,
                    "printed_page": printed_page_candidate(
                        native.get("extracted_text")
                    ),
                    "extractions": extracted,
                    "active_gold_variant_id": active_variant.get("id"),
                    "active_gold_extraction_id": active_variant.get("extraction_id"),
                    "gold_index_ids": [
                        row["id"]
                        for row in indexes
                        if row["document_id"] == document_id
                        and row["page_number"] == number
                    ],
                }
            )
    return pages


def summarize(documents, pages, variants, indexes) -> dict[str, Any]:
    active = {
        row["document_id"]: row["extraction_id"] for row in variants if row["is_active"]
    }
    extracted = [row for page in pages for row in page["extractions"]]
    active_pages = [
        row
        for page in pages
        for row in page["extractions"]
        if row["extraction_id"] == active.get(page["document_id"])
    ]
    return {
        "documents": len(documents),
        "physical_pages": len(pages),
        "silver_page_extractions": len(extracted),
        "extractions_by_extractor": dict(
            Counter(row.get("extractor") for row in extracted)
        ),
        "active_gold_documents": len(active),
        "gold_index_rows": len(indexes),
        "active_gold_requires_manual_review": sum(
            (row.get("quality_metrics") or {}).get("requires_manual_review") is True
            for row in active_pages
        ),
        "active_gold_completion_unconfirmed": sum(
            (row.get("structured_output") or {}).get("completion_unconfirmed") is True
            for row in active_pages
        ),
        "interpretation": (
            "Flags describe recorded review/completion uncertainty; "
            "they do not prove text loss."
        ),
    }


def _risk_reasons(page: dict[str, Any]) -> list[str]:
    reasons = []
    for row in page["extractions"]:
        if (row.get("structured_output") or {}).get("completion_unconfirmed"):
            reasons.append("recorded_completion_unconfirmed")
        if (row.get("quality_metrics") or {}).get("requires_manual_review"):
            reasons.append("recorded_requires_manual_review")
        if "|" in (row.get("extracted_markdown") or ""):
            reasons.append("automatic_markdown_table_candidate")
    return sorted(set(reasons))


def _coverage_pages(document_id: int, pages) -> list[dict[str, Any]]:
    pool = [page for page in pages if page["document_id"] == document_id]
    if len(pool) < 3:
        raise ValueError(
            "Cannot select 40 representative pages: a standard has fewer than three"
        )
    return [pool[index] for index in (0, len(pool) // 2, len(pool) - 1)]


def select_human_reference(documents, pages) -> list[dict[str, Any]]:
    """Choose three spread pages per norm plus ten risk/structure candidates."""
    selected: dict[tuple[int, int], dict[str, Any]] = {}

    def add(page, group, reasons):
        selected[(page["document_id"], page["physical_page"])] = {
            "document_id": page["document_id"],
            "standard_id": page.get("standard_id"),
            "physical_page": page["physical_page"],
            "document_sha256": page.get("document_sha256"),
            "selection_group": group,
            "selection_reason": reasons,
            "transcription": None,
            "transcription_origin": None,
            "review_status": "pending_human_review",
            "reviewer": None,
            "reviewed_at": None,
            "printed_page_confirmed": None,
        }

    for document in documents:
        for page in _coverage_pages(document["document_id"], pages):
            add(page, "standard_coverage", ["physical_start_middle_end_coverage"])
    candidates = sorted(
        pages,
        key=lambda page: (
            -len(_risk_reasons(page)),
            page["document_id"],
            page["physical_page"],
        ),
    )
    for page in candidates:
        if len(selected) >= 40:
            break
        if (page["document_id"], page["physical_page"]) not in selected:
            reasons = _risk_reasons(page) or ["additional_physical_structure_coverage"]
            add(page, "risk_or_structure", reasons)
    if len(selected) != 40:
        raise ValueError("Cannot select exactly 40 unique representative pages")
    return sorted(
        selected.values(), key=lambda page: (page["document_id"], page["physical_page"])
    )


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.rstrip()


def source_hashes(root: Path) -> dict[str, str]:
    tracked = _git(root, "ls-files", "-z").split("\0")
    selected = [
        name
        for name in tracked
        if name
        and (
            name.startswith("src/")
            or (name.startswith("data/") and name.endswith(".py"))
            or name
            in (
                "data/rag_schema.sql",
                "config/glmocr.yaml",
                "data/corpus_manifest.yaml",
                "pyproject.toml",
                "uv.lock",
                "rag_eval/pyproject.toml",
            )
        )
    ]
    return {
        name: file_sha256(root / name)
        for name in sorted(selected)
        if (root / name).is_file()
    }


def current_configuration(root: Path) -> dict[str, Any]:
    import yaml

    settings = {**dotenv_values(root / ".env"), **os.environ}
    config_path = root / "config/glmocr.yaml"
    return {
        "provenance": "observed_at_capture_not_historical_extraction_parameters",
        "environment_allowlist": {key: settings.get(key) for key in SAFE_SETTINGS},
        "glmocr_yaml": yaml.safe_load(config_path.read_text(encoding="utf-8")),
        "source_observations": source_configuration(root),
        "historical_configuration": None,
        "historical_configuration_status": "unknown_not_persisted",
    }


def _literal_constants(tree: ast.Module) -> dict[str, Any]:
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    values[target.id] = node.value.value
    return values


def _retrieval_limit(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Assign):
        return False
    names = {
        "pages_limit",
        "documents_limit",
        "full_documents_limit",
        "neighbor_radius",
        "candidates_limit",
        "evidence_pages_limit",
    }
    return any(
        isinstance(target, ast.Name) and target.id in names
        for target in statement.targets
    )


def _search_configuration(tree: ast.Module, source: str) -> dict[str, Any]:
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "search_documents"
        ),
        None,
    )
    if function is None:
        return {}
    return {
        "search_documents_defaults": {
            argument.arg: ast.literal_eval(default)
            for argument, default in zip(
                function.args.args[-len(function.args.defaults) :],
                function.args.defaults,
                strict=True,
            )
        },
        "retrieval_limits_source": [
            ast.get_source_segment(source, statement)
            for statement in function.body
            if _retrieval_limit(statement)
        ],
    }


def source_configuration(root: Path) -> dict[str, Any]:
    """Read constant expressions as data without executing production modules."""
    observations = {}
    for relative in ("data/rag_pipeline.py", "src/app/tools/rag_search.py"):
        source = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        values = {**_literal_constants(tree), **_search_configuration(tree, source)}
        if relative == "data/rag_pipeline.py":
            weights = {}
            for name in (
                "semantic",
                "textual_page",
                "textual_document",
                "exact_standard",
            ):
                match = re.search(
                    rf"'{name}'(?:::text AS source)?, source_rank,\s*"
                    r"(\d+(?:\.\d+)?)::double precision",
                    source,
                )
                weights[name] = float(match.group(1)) if match else None
            values["rrf_source_weights"] = weights
        observations[relative] = {
            "sha256": file_sha256(root / relative),
            "values": values,
            "provenance": "static_source_observation_not_historical_execution_config",
        }
    return observations


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def capture(
    root: Path, output_dir: Path, *, initial_git_state: dict | None = None
) -> dict[str, Any]:
    """Capture one database snapshot and write observational artifacts only."""
    if (output_dir / "initial_state.json").exists():
        raise FileExistsError(
            "Preserve the initial baseline; choose a new output directory"
        )
    observed_git = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "branch": _git(root, "branch", "--show-current"),
        "status_at_capture": _git(root, "status", "--short"),
    }
    connection = connect_readonly(root)
    try:
        documents = _read_rows(
            connection,
            """
            SELECT record_id AS document_id, file_name, page_count, sha256,
                   size_bytes, collector_version, inventory_generated_at,
                   manifest_metadata->>'id' AS standard_id,
                   manifest_metadata->>'version' AS standard_version
            FROM bronze.documents ORDER BY record_id
        """,
        )
        runs = _read_rows(
            connection, "SELECT * FROM silver.silver_document_extractions ORDER BY id"
        )
        extractions = _read_rows(
            connection,
            "SELECT * FROM silver.silver_page_extractions "
            "ORDER BY document_id, page_number, extractor, id",
        )
        variants = _read_rows(
            connection,
            "SELECT to_jsonb(g) - 'search_vector' AS record "
            "FROM gold.gold_rag_documents g ORDER BY id",
        )
        indexes = _read_rows(
            connection,
            "SELECT to_jsonb(g) - 'embedding' - 'search_vector' AS record "
            "FROM gold.gold_rag_page_index g ORDER BY id",
        )
        db_info = _read_rows(
            connection,
            "SELECT current_setting('transaction_read_only') AS transaction_read_only, "
            "current_setting('transaction_isolation') AS isolation, "
            "transaction_timestamp() AS snapshot_timestamp, "
            "version() AS server_version, "
            "(SELECT extversion FROM pg_extension WHERE extname='vector') "
            "AS pgvector_version",
        )[0]
    finally:
        connection.rollback()
        connection.close()
    for document in documents:
        document["local_pdf_sha256"] = file_sha256(
            root / "data/raw" / document["file_name"]
        )
        document["pdf_hash_matches_database"] = (
            document["sha256"].strip() == document["local_pdf_sha256"]
        )
    variants = [row["record"] for row in variants]
    indexes = [row["record"] for row in indexes]
    pages = _assemble_pages(documents, extractions, variants, indexes)
    if sum(len(page["extractions"]) for page in pages) != len(extractions):
        raise ValueError("Unmapped extraction rows: refusing an incomplete snapshot")
    dependencies = {"python": platform.python_version()}
    for package in PACKAGES:
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    snapshot = {
        "schema_version": "tcc-initial-state-v1",
        "captured_at": datetime.now(UTC),
        "documents": documents,
        "pages": pages,
        "extraction_runs": runs,
        "gold_variants": variants,
        "gold_page_index": indexes,
        "db_summary": {**summarize(documents, pages, variants, indexes), **db_info},
        "git": {**observed_git, "initial_observation": initial_git_state},
        "configuration": current_configuration(root),
        "source_hashes": source_hashes(root),
        "dependencies": dependencies,
        "limits": [
            "No OCR, generation, migration, inference, mutation, or embedding "
            "requests were performed.",
            "Historical execution IDs identify mutable persisted extraction records, "
            "not immutable execution logs.",
            "Printed page numbers are automatic candidates pending human verification.",
            "No human transcriptions have been produced by this capture.",
        ],
    }
    snapshot = sanitize(snapshot)
    write_json(output_dir / "initial_state.json", snapshot)
    write_json(
        output_dir / "human_reference.json",
        {
            "schema_version": "tcc-human-reference-v1",
            "source_snapshot_sha256": file_sha256(output_dir / "initial_state.json"),
            "status": "pending_human_review",
            "pages": select_human_reference(documents, pages),
        },
    )
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "rag_eval/baseline/artifacts"
    )
    args = parser.parse_args()
    snapshot = capture(ROOT, args.output_dir)
    print(json.dumps(snapshot["db_summary"], ensure_ascii=False, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
