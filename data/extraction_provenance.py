"""Identidades de processamento e persistência versionada, sem executar extratores."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from psycopg.types.json import Jsonb


def fingerprint(scheme: str, value: Any) -> str:
    payload = json.dumps(
        {"scheme": scheme, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def original_snapshot(source: Path, directory: Path) -> tuple[Path, str]:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=directory, suffix=".tmp", delete=False
    ) as output:
        temporary = Path(output.name)
    try:
        with source.open("rb") as original, temporary.open("wb") as snapshot:
            shutil.copyfileobj(original, snapshot)
        digest = file_digest(temporary)
        target = directory / (digest + ".pdf")
        assert target.parent.resolve() == directory
        try:
            if not target.exists():
                temporary.rename(target)
        except FileExistsError:
            pass
        if file_digest(target) != digest:
            raise ValueError(
                "Snapshot original corrompido; a versão existente foi preservada."
            )
        return target, digest
    finally:
        temporary.unlink(missing_ok=True)


def _known_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.removeprefix("sha256:").lower()
    return value if re.fullmatch(r"[a-f0-9]{64}", value) else None


def model_digest(model: str, endpoint: str, setting: str) -> str | None:
    provided = os.getenv(setting)
    if provided:
        return _known_digest(provided)
    try:
        response = requests.get(endpoint.rstrip("/") + "/api/tags", timeout=2)
        response.raise_for_status()
        aliases = {model, model if ":" in model else model + ":latest"}
        return _known_digest(
            next(
                (
                    item.get("digest")
                    for item in response.json()["models"]
                    if isinstance(item, dict) and item.get("name") in aliases
                ),
                None,
            )
        )
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def processing_profile(root: Path, extractor: str, versions: dict, recipe: str) -> dict:
    profile: dict[str, Any] = {
        "extractor": extractor,
        "version": versions[extractor],
        "implementation_sha256": recipe,
    }
    if extractor == "glm_ocr":
        import yaml

        config = yaml.safe_load(
            (root / "config/glmocr.yaml").read_text(encoding="utf-8")
        )
        pipeline = config["pipeline"]
        api = pipeline.get("ocr_api", {})
        loader = pipeline.get("page_loader", {})
        mode = os.getenv("RAG_GLM_OCR_MODE", "package").lower()
        configured_model = api.get("model", "glm-ocr:latest")
        model = (
            os.getenv("GLMOCR_MODEL", configured_model)
            if mode == "direct_ollama"
            else configured_model
        )
        profile.update(
            {
                "configuration_file_sha256": file_digest(root / "config/glmocr.yaml"),
                "configuration": pipeline,
                "mode": mode,
                "model": model,
                "model_digest_observed": model_digest(
                    model,
                    f"http://{api.get('api_host', 'localhost')}:"
                    f"{api.get('api_port', 11434)}",
                    "GLMOCR_MODEL_DIGEST",
                ),
                "fallback_versions": versions,
            }
        )
        if mode == "direct_ollama":
            initial = int(
                os.getenv(
                    "GLMOCR_DIRECT_MAX_TOKENS", str(loader.get("max_tokens", 2048))
                )
            )
            profile.update(
                {
                    "max_tokens": initial,
                    "retry_max_tokens": int(
                        os.getenv(
                            "GLMOCR_DIRECT_RETRY_MAX_TOKENS", str(max(initial, 32768))
                        )
                    ),
                    "context": int(os.getenv("GLMOCR_DIRECT_CONTEXT", "16384")),
                    "timeout": int(
                        os.getenv(
                            "GLMOCR_DIRECT_TIMEOUT",
                            str(api.get("request_timeout", 300)),
                        )
                    ),
                    "keep_alive": os.getenv("GLMOCR_KEEP_ALIVE", "5m"),
                }
            )
    return profile


def input_fingerprint(profile: dict) -> str:
    effective = {
        key: value
        for key, value in profile["processing"].items()
        if key != "configuration_file_sha256"
    }
    return fingerprint("extraction-input-v1", {**profile, "processing": effective})


def require_schema(connection) -> None:
    if (
        connection.execute(
            "SELECT to_regclass('silver.page_extraction_history')"
        ).fetchone()[0]
        is None
    ):
        raise RuntimeError(
            "Aplique 0001_extraction_provenance explicitamente; o "
            "schema legado não será modificado automaticamente."
        )


def record_gold_derivation(connection, rag_document_id: int) -> None:
    origin = connection.execute(
        """
        SELECT jsonb_build_object('execution',e.execution_id,
            'input',e.input_fingerprint,
            'content',g.content_hash,'pages',(
                SELECT jsonb_object_agg(p.page_number::text,p.result_fingerprint)
                FROM silver.silver_page_extractions p WHERE p.extraction_id=e.id
            ))
        FROM gold.gold_rag_documents g JOIN silver.silver_document_extractions e
          ON e.id=g.extraction_id WHERE g.id=%s
        """,
        (rag_document_id,),
    ).fetchone()[0]
    previous = connection.execute(
        ("SELECT origin FROM gold.document_derivations WHERE rag_document_id=%s"),
        (rag_document_id,),
    ).fetchone()
    if previous is not None and previous[0] != origin:
        raise ValueError(
            "Derivado já versionado: crie outra execução para "
            "publicar o resultado alterado."
        )
    connection.execute(
        """
        INSERT INTO gold.document_derivations(rag_document_id,origin,fingerprint)
        VALUES (%s,%s,%s) ON CONFLICT(rag_document_id) DO NOTHING
        """,
        (rag_document_id, Jsonb(origin), fingerprint("gold-derivation-v1", origin)),
    )
    connection.execute(
        """
        INSERT INTO silver.page_extraction_history
            (page_extraction_id,result_fingerprint,evaluation_id,event_kind,snapshot)
        SELECT p.id,p.result_fingerprint,p.evaluation_id,'gold_derivation',
            to_jsonb(p) || jsonb_build_object('derived_gold',jsonb_build_object(
                'id',g.id,'fingerprint',lineage.fingerprint,'quality_score',g.quality_score))
        FROM gold.gold_rag_documents g
        JOIN gold.document_derivations lineage ON lineage.rag_document_id=g.id
        JOIN silver.silver_page_extractions p ON p.extraction_id=g.extraction_id
        WHERE g.id=%s AND NOT EXISTS (
            SELECT 1 FROM silver.page_extraction_history h
            WHERE h.page_extraction_id=p.id AND h.event_kind='gold_derivation'
              AND h.evaluation_id IS NOT DISTINCT FROM p.evaluation_id
              AND h.snapshot->'derived_gold'->>'fingerprint'=lineage.fingerprint
        )
        """,
        (rag_document_id,),
    )


def start_execution(
    connection,
    document_id: int,
    extractor: str,
    total_pages: int,
    profile: dict,
    force: bool,
) -> int:
    require_schema(connection)
    identity = input_fingerprint(profile)
    verified_model = (
        extractor != "glm_ocr"
        or profile["processing"]["model_digest_observed"] is not None
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"extraction:{document_id}:{extractor}",),
        )
        if not force and verified_model:
            cursor.execute(
                (
                    "SELECT id FROM silver.silver_document_extractions WHERE"
                    " document_id=%s AND extractor=%s AND "
                    "input_fingerprint=%s ORDER BY id DESC LIMIT 1"
                ),
                (document_id, extractor, identity),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
        cursor.execute(
            """
            INSERT INTO silver.silver_document_extractions
                (document_id,extractor,extractor_version,total_pages,
                 input_fingerprint,input_provenance,started_at)
            VALUES (%s,%s,%s,%s,%s,%s,now()) RETURNING id
            """,
            (
                document_id,
                extractor,
                profile["processing"]["version"],
                total_pages,
                identity,
                Jsonb(profile),
            ),
        )
        execution = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO silver.silver_page_extractions
                (extraction_id,document_id,extractor,extractor_version,page_number)
            SELECT %s,%s,%s,%s,number FROM generate_series(1,%s) number
            """,
            (
                execution,
                document_id,
                extractor,
                profile["processing"]["version"],
                total_pages,
            ),
        )
    return execution


def invalidate_evaluations(
    connection,
    config_fingerprint: str,
    extractors: list[str],
    document_id: int | None,
    force: bool = False,
) -> None:
    connection.execute(
        """
        UPDATE silver.silver_page_extractions p SET
            quality_score=NULL,quality_metrics=NULL,evaluation_status='pending',
            evaluation_method=NULL,evaluation_model=NULL,evaluation_prompt_version=NULL,
            evaluation_error=NULL,evaluated_at=NULL,evaluation_id=NULL,
            evaluation_request_id=NULL,
            evaluation_input_fingerprint=NULL,evaluation_config_fingerprint=NULL,
            evaluation_config=NULL
        WHERE p.extractor=ANY(%s) AND (%s::bigint IS NULL OR p.document_id=%s)
          AND (p.evaluation_config_fingerprint IS DISTINCT FROM %s OR %s)
          AND p.evaluation_status<>'pending'
          AND p.extraction_id IN (
              SELECT DISTINCT ON (document_id,extractor) id
              FROM silver.silver_document_extractions
              ORDER BY document_id,extractor,id DESC
          )
        """,
        (extractors, document_id, document_id, config_fingerprint, force),
    )


def reserve_evaluation(
    connection, page_id: int, result: str, status: str, configuration: dict
) -> str | None:
    request = str(uuid4())
    identity = fingerprint("evaluation-config-v1", configuration)
    row = connection.execute(
        """
        UPDATE silver.silver_page_extractions SET
            evaluation_request_id=%s,evaluation_config_fingerprint=%s,
            evaluation_config=%s,evaluation_status='pending',
            evaluation_id=NULL,quality_score=NULL,quality_metrics=NULL,
            evaluation_method=NULL,evaluation_model=NULL,evaluation_prompt_version=NULL,
            evaluation_error=NULL,evaluated_at=NULL,evaluation_input_fingerprint=NULL
        WHERE id=%s AND result_fingerprint=%s AND evaluation_status=%s RETURNING id
        """,
        (request, identity, Jsonb(configuration), page_id, result, status),
    ).fetchone()
    return request if row else None


def save_evaluation(
    connection,
    page_id: int,
    result_fingerprint: str,
    configuration: dict,
    values: dict,
    request_id: str | None = None,
) -> bool:
    config_fingerprint = fingerprint("evaluation-config-v1", configuration)
    evaluation_id = request_id or str(uuid4())
    row = connection.execute(
        """
        UPDATE silver.silver_page_extractions SET
            quality_score=%s,quality_metrics=%s,evaluation_status=%s,
            evaluation_method=%s,evaluation_model=%s,evaluation_prompt_version=%s,
            evaluation_error=%s,evaluated_at=%s,evaluation_id=%s,
            evaluation_input_fingerprint=%s,evaluation_config_fingerprint=%s,
            evaluation_config=%s,updated_at=now()
        WHERE id=%s AND result_fingerprint=%s
          AND evaluation_request_id IS NOT DISTINCT FROM %s::uuid RETURNING id
        """,
        (
            values["score"],
            Jsonb(values["metrics"]),
            values["status"],
            values["method"],
            configuration["model"],
            configuration["engine_version"],
            values["error"],
            values["evaluated_at"],
            evaluation_id,
            result_fingerprint,
            config_fingerprint,
            Jsonb(configuration),
            page_id,
            result_fingerprint,
            request_id,
        ),
    ).fetchone()
    if row:
        return True
    snapshot = {
        **values,
        "evaluation_config": configuration,
        "evaluation_config_fingerprint": config_fingerprint,
        "result_fingerprint": result_fingerprint,
        "evaluation_id": evaluation_id,
    }
    snapshot["evaluated_at"] = str(snapshot["evaluated_at"])
    connection.execute(
        """
        INSERT INTO silver.page_extraction_history
            (page_extraction_id,result_fingerprint,evaluation_id,event_kind,snapshot)
        VALUES (%s,%s,%s,'late_evaluation',%s)
        """,
        (page_id, result_fingerprint, evaluation_id, Jsonb(snapshot)),
    )
    return False
