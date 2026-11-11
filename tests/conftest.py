"""PostgreSQL real em cluster descartável, sem credenciais ou banco produtivo."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
ROOT = REPO_ROOT


def _pg_command(binary, *arguments):
    # pg_ctl children can inherit pipes on Windows; a file does not wait for EOF.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [str(binary), *map(str, arguments)],
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(text)
    return text


@pytest.fixture(scope="session")
def postgres_cluster():
    binaries = Path(os.getenv("TCC_PG_BIN", "C:/Program Files/PostgreSQL/18/bin"))
    if not (binaries / "initdb.exe").is_file():
        if os.getenv("TCC_REQUIRE_PG") == "1":
            pytest.fail("TCC_PG_BIN deve apontar para os binários PostgreSQL locais")
        pytest.skip("PostgreSQL local ausente; integração não executada")
    workspace = Path(tempfile.mkdtemp(prefix="tcc-f41-pg-"))
    data = workspace / "cluster"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _pg_command(
        binaries / "initdb.exe",
        "-D",
        data,
        "-U",
        "tcc_f41",
        "-A",
        "trust",
        "--encoding=UTF8",
        "--locale=C",
    )
    settings = {
        "host": "127.0.0.1",
        "port": port,
        "user": "tcc_f41",
        "dbname": "postgres",
        "connect_timeout": 5,
    }
    receipt = None
    receipt_path = None
    try:
        _pg_command(
            binaries / "pg_ctl.exe",
            "-D",
            data,
            "-l",
            workspace / "server.log",
            "-o",
            f"-h 127.0.0.1 -p {port} -F",
            "-w",
            "-t",
            "25",
            "start",
        )
        with psycopg.connect(**settings) as connection:
            cluster_id = connection.execute(
                "SELECT system_identifier::text FROM pg_control_system()"
            ).fetchone()[0]
            directory = connection.execute("SHOW data_directory").fetchone()[0]
            assert Path(directory).resolve() == data.resolve()
        production = ROOT / "docs/fase4_1/artifacts/production_before.json"
        if production.exists():
            assert (
                cluster_id
                != json.loads(production.read_text(encoding="utf-8"))[
                    "cluster_identifier"
                ]
            )
        marker = {
            "cluster_identifier": cluster_id,
            "data_directory": str(data),
            "settings": settings,
        }
        (workspace / "isolation.json").write_text(
            json.dumps(marker, indent=2), encoding="utf-8"
        )
        if os.getenv("TCC_PG_REPORT_DIR"):
            destination = Path(os.environ["TCC_PG_REPORT_DIR"])
            destination.mkdir(parents=True, exist_ok=True)
            receipt_path = destination / f"cluster_{cluster_id}.json"
            receipt = {
                "cluster_identifier": cluster_id,
                "temporary_directory": workspace.name,
                "host": settings["host"],
                "port": port,
                "role": settings["user"],
                "data_directory_verified": True,
                "original_cluster_different": production.exists(),
                "uses_production_credentials": False,
                "stopped": False,
            }
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        yield settings, marker
    finally:
        if (data / "postmaster.pid").exists():
            _pg_command(binaries / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop")
        if receipt is not None:
            receipt["stopped"] = not (data / "postmaster.pid").exists()
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


@pytest.fixture
def isolated_pg(postgres_cluster, monkeypatch, tmp_path, request):
    from data import rag_pipeline as pipeline

    def forbid_model_construction(*args, **kwargs):
        raise AssertionError("Integrações sintéticas não constroem motores OCR reais")

    def offline_http(*args, **kwargs):
        import requests

        raise requests.ConnectionError("Rede desabilitada nas fixtures sintéticas")

    monkeypatch.setattr(pipeline, "create_docling_converter", forbid_model_construction)
    monkeypatch.setitem(
        sys.modules, "glmocr", SimpleNamespace(GlmOcr=forbid_model_construction)
    )
    monkeypatch.setattr(pipeline.requests.sessions.Session, "send", offline_http)
    settings, marker = postgres_cluster
    name = "tcc_f41_" + uuid4().hex
    with psycopg.connect(**settings, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    target = {**settings, "dbname": name}

    def connect():
        connection = psycopg.connect(**target)
        assert connection.info.dbname == name
        actual = connection.execute("SHOW data_directory").fetchone()[0]
        assert Path(actual).resolve() == Path(marker["data_directory"]).resolve()
        return connection

    monkeypatch.setattr(pipeline, "connect", connect)
    with connect() as connection:
        connection.execute("CREATE SCHEMA bronze")
        connection.execute(
            "CREATE TABLE bronze.documents (record_id BIGINT PRIMARY"
            " KEY, relative_path TEXT, file_name TEXT, page_count "
            "INTEGER, manifest_metadata JSONB DEFAULT '{}'::jsonb, "
            "sha256 CHAR(64))"
        )
        connection.execute((ROOT / "data/rag_schema.sql").read_text(encoding="utf-8"))
        if getattr(request, "param", True):
            for migration in sorted(
                (ROOT / "data/migrations").glob("*.up.sql")
            ):
                connection.execute(migration.read_text(encoding="utf-8"))
    source = tmp_path / "synthetic.pdf"
    monkeypatch.setattr(pipeline, "PAGE_CACHE", tmp_path / "page_cache")
    source.write_bytes(b"synthetic source A")
    with connect() as connection:
        connection.execute(
            (
                "INSERT INTO "
                "bronze.documents(record_id,relative_path,file_name,page_count)"
                " VALUES (17,%s,'synthetic.pdf',1)"
            ),
            (str(source),),
        )
    monkeypatch.setattr(
        pipeline,
        "extractor_versions",
        lambda: {"pdf_reader": "v1", "glm_ocr": "v1", "docling": "v1"},
    )
    monkeypatch.setenv("GLMOCR_MODEL_DIGEST", "a" * 64)
    monkeypatch.setenv("RAG_EVALUATION_MODEL_DIGEST", "b" * 64)
    try:
        yield connect, source
    finally:
        with psycopg.connect(**settings, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
