# ruff: noqa: E501

"""Coleta arquivos de data/raw e faz upsert direto no PostgreSQL.

Execução padrão:
    uv run python data/bronze_postgres.py

O modo opcional ``--review-only`` gera um JSONL sem acessar o banco.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RAW_DIR = Path("data/raw")
DEFAULT_MANIFEST = Path("data/corpus_manifest.yaml")
DEFAULT_GLMOCR_CONFIG = Path("config/glmocr.yaml")
DEFAULT_REVIEW_DIR = Path("data/tmp")
COLLECTOR_VERSION = "1.0"
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result: dict[str, dict[str, Any]] = {}
    for item in raw.get("documents", []):
        if not isinstance(item, dict) or not item.get("file"):
            continue
        # Aceita tanto o caminho relativo ao projeto quanto somente o nome do PDF.
        key = Path(str(item["file"])).name.lower()
        result[key] = item
    return result


def pdf_details(
    path: Path,
    docling_converter: Any,
    glmocr_parser: Any,
) -> tuple[dict[str, Any], str, str, int | None, bool | None]:
    if path.suffix.lower() != ".pdf":
        return {}, "", "", None, None
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    metadata = {
        str(key).lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
        if value is not None
    }
    docling_result = docling_converter.convert(path)
    docling_text = docling_result.document.export_to_markdown()
    if use_direct_ollama_glm_ocr():
        try:
            glmocr_text = direct_ollama_pdf_text(path)
        except RuntimeError as error:
            # O conteúdo Docling já foi extraído acima. Uma falha transitória
            # do Ollama não deve impedir a carga do PDF inteiro na Bronze.
            print(
                f"Aviso: GLM-OCR indisponível em {path.name}; "
                f"usando Docling como conteúdo principal: {error}",
                file=sys.stderr,
                flush=True,
            )
            glmocr_text = ""
    else:
        glmocr_result = glmocr_parser.parse(path, save_layout_visualization=False)
        glmocr_text = glmocr_result.markdown_result
    return (
        metadata,
        docling_text,
        glmocr_text,
        len(reader.pages),
        reader.is_encrypted,
    )


def use_direct_ollama_glm_ocr() -> bool:
    """Usa o endpoint local do Ollama sem o detector de layout em CPU."""
    return os.getenv("RAG_GLM_OCR_MODE", "package").lower() == "direct_ollama"


def direct_ollama_pdf_text(path: Path) -> str:
    """Extrai todas as páginas diretamente pelo GLM-OCR no Ollama."""
    import requests

    try:
        from data.rag_pipeline import (
            direct_ollama_glm_ocr,
            native_page_text,
            page_paths,
        )
    except ModuleNotFoundError as error:
        # Execução como ``python data/bronze_postgres.py`` coloca somente
        # ``data/`` no sys.path; nesse caso, o módulo é importado pelo nome
        # do arquivo, mantendo o suporte à execução pelo orquestrador.
        if error.name != "data":
            raise
        from rag_pipeline import direct_ollama_glm_ocr, native_page_text, page_paths

    page_texts: list[str] = []
    network_error: requests.exceptions.RequestException | None = None
    paths = page_paths(path, 0)
    for page_number, page_path in enumerate(paths, start=1):
        if network_error is not None:
            native = native_page_text(page_path)
            if native:
                text = native
            else:
                print(
                    f"Aviso: sem fallback nativo em {path.name}, "
                    f"página {page_number}; Ollama já havia excedido o timeout.",
                    file=sys.stderr,
                    flush=True,
                )
                text = ""
            page_texts.append(text)
            continue
        try:
            text, _, _ = direct_ollama_glm_ocr(page_path)
        except ValueError as error:
            native = native_page_text(page_path)
            if native:
                print(
                    f"Aviso: usando texto nativo em {path.name}, "
                    f"página {page_number}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
                text = native
            else:
                raise RuntimeError(
                    f"GLM-OCR falhou em {path.name}, página {page_number}: {error}"
                ) from error
        except requests.exceptions.RequestException as error:
            network_error = error
            native = native_page_text(page_path)
            if native:
                print(
                    f"Aviso: usando texto nativo em {path.name}, "
                    f"página {page_number}, após falha de rede do Ollama: {error}",
                    file=sys.stderr,
                    flush=True,
                )
                text = native
            else:
                raise RuntimeError(
                    f"GLM-OCR falhou em {path.name}, página {page_number}: {error}"
                ) from error
        except Exception as error:
            raise RuntimeError(
                f"GLM-OCR falhou em {path.name}, página {page_number}: {error}"
            ) from error
        page_texts.append(text)
    return "\n\n".join(page_texts)


def select_primary_content(docling_text: str, glmocr_text: str) -> tuple[str, str]:
    """Escolhe uma fonte utilizável e informa quando o GLM foi rejeitado."""
    if not glmocr_text.strip():
        return docling_text, "glmocr_empty"
    if not docling_text.strip():
        return glmocr_text, "glmocr_only"

    private_use = sum(
        "\ue000" <= character <= "\uf8ff" for character in glmocr_text
    )
    private_ratio = private_use / max(len(glmocr_text), 1)
    too_short = len(docling_text) >= 1000 and len(glmocr_text) < len(docling_text) * 0.05
    if private_ratio > 0.005 or too_short:
        return docling_text, "docling_quality_fallback"
    return glmocr_text, "glmocr"


def collect_file(
    path: Path,
    manifest: dict[str, dict[str, Any]],
    docling_converter: Any,
    glmocr_parser: Any,
) -> dict[str, Any]:
    stat = path.stat()
    relative_path = path.relative_to(RAW_DIR).as_posix()
    (
        pdf_metadata,
        docling_text,
        glmocr_text,
        page_count,
        encrypted,
    ) = pdf_details(path, docling_converter, glmocr_parser)
    content, content_source = select_primary_content(docling_text, glmocr_text)
    manifest_data = manifest.get(path.name.lower(), {})
    return {
        "relative_path": relative_path,
        "file_name": path.name,
        "extension": path.suffix.lower(),
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "size_bytes": stat.st_size,
        "sha256": sha256(path),
        "created_at": iso_timestamp(stat.st_ctime),
        "modified_at": iso_timestamp(stat.st_mtime),
        "accessed_at": iso_timestamp(stat.st_atime),
        "page_count": page_count,
        "is_pdf_encrypted": encrypted,
        "character_count": len(content),
        "word_count": len(content.split()),
        "content_text": content,
        "content_text_docling": docling_text,
        "content_text_glmocr": glmocr_text,
        "pdf_metadata": pdf_metadata,
        "manifest_metadata": manifest_data,
        "raw_metadata": {
            "filesystem": {
                "mode": stat.st_mode,
                "inode": stat.st_ino,
                "device": stat.st_dev,
                "hard_links": stat.st_nlink,
                "uid": getattr(stat, "st_uid", None),
                "gid": getattr(stat, "st_gid", None),
            },
            "pdf": pdf_metadata,
            "manifest": manifest_data,
            "content_source": content_source,
        },
        "collector_version": COLLECTOR_VERSION,
        "inventory_generated_at": utc_now(),
    }


def iter_inventory(
    raw_dir: Path, manifest_path: Path, glmocr_config: Path
):
    """Produz registros um a um para permitir retomada por arquivo."""
    global RAW_DIR
    RAW_DIR = raw_dir.resolve()
    files = sorted(path for path in RAW_DIR.rglob("*") if path.is_file())
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo encontrado em {RAW_DIR}")
    try:
        from data.rag_pipeline import create_docling_converter
    except ModuleNotFoundError as error:
        if error.name != "data":
            raise
        from rag_pipeline import create_docling_converter

    manifest = load_manifest(manifest_path)
    docling_converter = create_docling_converter()
    if use_direct_ollama_glm_ocr():
        glmocr_parser = None
    else:
        from glmocr import GlmOcr

        glmocr_parser = GlmOcr(config_path=str(glmocr_config))
    for path in files:
        yield collect_file(
            path,
            manifest,
            docling_converter,
            glmocr_parser,
        )


def collect_inventory(
    raw_dir: Path, manifest_path: Path, glmocr_config: Path
) -> list[dict[str, Any]]:
    return list(iter_inventory(raw_dir, manifest_path, glmocr_config))


def write_inventory(records: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_inventory(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(f"Inventário vazio: {path}")
    return records


def validate_inventory(records: list[dict[str, Any]], raw_dir: Path) -> None:
    for record in records:
        path = (raw_dir / record["relative_path"]).resolve()
        if raw_dir.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(
                f"Arquivo ausente ou fora de data/raw: {record['relative_path']}"
            )
        current_hash = sha256(path)
        if current_hash != record["sha256"]:
            raise RuntimeError(
                f"Arquivo alterado depois da revisão: {record['relative_path']}. "
                "Gere um novo inventário antes de aplicar."
            )


def identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} inválido: {value!r}")
    return value


def load_database(records: list[dict[str, Any]], args: argparse.Namespace) -> int:
    import psycopg
    from psycopg.types.json import Jsonb

    schema = identifier(args.schema, "schema")
    table = identifier(args.table, "tabela")
    qualified = f'"{schema}"."{table}"'
    columns = [
        "relative_path",
        "file_name",
        "extension",
        "mime_type",
        "size_bytes",
        "sha256",
        "created_at",
        "modified_at",
        "accessed_at",
        "page_count",
        "is_pdf_encrypted",
        "character_count",
        "word_count",
        "content_text",
        "content_text_docling",
        "content_text_glmocr",
        "pdf_metadata",
        "manifest_metadata",
        "raw_metadata",
        "collector_version",
        "inventory_generated_at",
    ]
    connect_args = {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "dbname": os.getenv("DB_NAME", "postgres"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }
    values = [
        tuple(
            Jsonb(record[key]) if key.endswith("metadata") else record[key]
            for key in columns
        )
        for record in records
    ]
    connection = psycopg.connect(**connect_args)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {qualified} (
                    record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    relative_path TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL, extension TEXT NOT NULL, mime_type TEXT NOT NULL,
                    size_bytes BIGINT NOT NULL, sha256 CHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ, modified_at TIMESTAMPTZ, accessed_at TIMESTAMPTZ,
                    page_count INTEGER, is_pdf_encrypted BOOLEAN,
                    character_count BIGINT NOT NULL, word_count BIGINT NOT NULL,
                    content_text TEXT NOT NULL, pdf_metadata JSONB NOT NULL DEFAULT '{{}}',
                    content_text_docling TEXT NOT NULL DEFAULT '',
                    content_text_glmocr TEXT NOT NULL DEFAULT '',
                    manifest_metadata JSONB NOT NULL DEFAULT '{{}}', raw_metadata JSONB NOT NULL DEFAULT '{{}}',
                    collector_version TEXT NOT NULL, inventory_generated_at TIMESTAMPTZ NOT NULL,
                    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cursor.execute(
                f"ALTER TABLE {qualified} "
                "ADD COLUMN IF NOT EXISTS content_text_docling TEXT NOT NULL DEFAULT '', "
                "ADD COLUMN IF NOT EXISTS content_text_glmocr TEXT NOT NULL DEFAULT ''"
            )
            assignments = ", ".join(
                f'"{column}" = EXCLUDED."{column}"'
                for column in columns
                if column != "relative_path"
            )
            placeholders = ", ".join(["%s"] * len(columns))
            cursor.executemany(
                f"INSERT INTO {qualified} ({', '.join(f'"{c}"' for c in columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT (relative_path) DO UPDATE SET {assignments}, loaded_at = now()",
                values,
            )
        connection.commit()
    return len(records)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--glmocr-config",
        type=Path,
        default=Path(os.getenv("GLMOCR_CONFIG", DEFAULT_GLMOCR_CONFIG)),
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        help="arquivo JSONL existente; usado somente junto com --apply",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="compatibilidade: aplica um inventário JSONL existente",
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="gera um inventário temporário sem carregar no banco",
    )
    parser.add_argument("--schema", default=os.getenv("BRONZE_SCHEMA", "bronze"))
    parser.add_argument("--table", default=os.getenv("BRONZE_TABLE", "documents"))
    args = parser.parse_args()
    try:
        if args.apply:
            if not args.inventory:
                parser.error("--apply exige --inventory com o arquivo revisado")
            records = read_inventory(args.inventory)
            validate_inventory(records, args.raw_dir)
            print(
                f"Carregados {load_database(records, args)} registros em {args.schema}.{args.table}."
            )
        elif args.review_only:
            output = (
                args.inventory
                or DEFAULT_REVIEW_DIR
                / f"bronze_inventory_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
            )
            records = collect_inventory(
                args.raw_dir.resolve(), args.manifest, args.glmocr_config
            )
            write_inventory(records, output)
            print(f"Inventário gerado: {output} ({len(records)} arquivos).")
        else:
            loaded = 0
            for record in iter_inventory(
                args.raw_dir.resolve(), args.manifest, args.glmocr_config
            ):
                loaded += load_database([record], args)
                print(
                    f"Bronze: {record['file_name']} carregado "
                    f"({loaded} arquivo(s)).",
                    flush=True,
                )
            print(f"Carregados {loaded} registros em {args.schema}.{args.table}.")
    except Exception as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
