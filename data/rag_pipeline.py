"""Persistência Silver/Gold, avaliação e recuperação hierárquica do RAG.

O módulo usa somente psycopg, SQL direto e os clientes já utilizados pelo
projeto. Cada página é persistida em sua própria transação e pode ser retomada
sem reprocessar páginas concluídas.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PAGE_CACHE = ROOT / "data" / "page_cache"
SCHEMA_SQL = ROOT / "data" / "rag_schema.sql"
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIMENSION = 768
EMBEDDING_URL = "http://localhost:11434/api/embed"
EVALUATION_PROMPT_VERSION = "rag-page-evaluation-v1"
VALID_STATUSES = {"pending", "processing", "success", "error"}
EVALUATION_SCORE_KEYS = {
    "textual_fidelity",
    "content_completeness",
    "reading_order",
    "structural_preservation",
    "lists_preservation",
    "tables_preservation",
    "numbers_and_references",
    "duplication_control",
    "noise_control",
    "hallucination_control",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def package_version(package: str, fallback: str = "unknown") -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return fallback


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def estimated_token_count(value: str) -> int:
    """Estima tokens sem truncar o texto quando não há tokenizer do LLM local."""
    return len(re.findall(r"\w+|[^\w\s]", value, flags=re.UNICODE))


def context_token_limit() -> int:
    return int(os.getenv("RAG_CONTEXT_TOKEN_LIMIT", "8192"))


def configure_utf8_output() -> None:
    """Evita que o console Windows corrompa ou rejeite texto Unicode."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")


def reconstruct_page_content(pages: list[dict[str, Any]]) -> str:
    """Reconstrói páginas ordenadas, preservando marcadores e falhas."""
    blocks: list[str] = []
    for page in sorted(pages, key=lambda item: int(item["page_number"])):
        number = page["page_number"]
        if page.get("status") == "success":
            blocks.append(f"<<<PÁGINA {number}>>>\n\n{page.get('text') or ''}")
            continue
        status = (
            "ERRO DE EXTRAÇÃO"
            if page.get("status") == "error"
            else "PENDENTE"
        )
        blocks.append(f"<<<PÁGINA {number} — {status}>>>")
    return "\n\n".join(blocks)


def connect():
    import psycopg

    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value) if value else None


def initialise_database() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with connect() as connection:
        connection.execute(sql)
        connection.commit()
    print("Estruturas Silver, Gold, índices e view criados/verificados.")


def bronze_documents(document_id: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT record_id, relative_path, file_name, page_count,
               manifest_metadata
        FROM bronze.documents
    """
    params: tuple[Any, ...] = ()
    if document_id is not None:
        query += " WHERE record_id = %s"
        params = (document_id,)
    query += " ORDER BY record_id"
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [item.name for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def page_paths(pdf_path: Path, document_id: int) -> list[Path]:
    import fitz
    import pypdf

    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    target_dir = PAGE_CACHE / str(document_id) / digest
    target_dir.mkdir(parents=True, exist_ok=True)
    reader = pypdf.PdfReader(str(pdf_path), strict=False)
    pdf_document = fitz.open(str(pdf_path))
    paths: list[Path] = []
    try:
        for index, page in enumerate(reader.pages, start=1):
            target = target_dir / f"page-{index:04d}.pdf"
            image_target = target_dir / f"page-{index:04d}.png"
            if not target.exists():
                writer = pypdf.PdfWriter()
                writer.add_page(page)
                with target.open("wb") as output:
                    writer.write(output)
            if not image_target.exists():
                pixmap = pdf_document[index - 1].get_pixmap(
                    matrix=fitz.Matrix(2, 2), alpha=False
                )
                pixmap.save(str(image_target))
            paths.append(target)
    finally:
        pdf_document.close()
    return paths


def native_page_text(page_pdf: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(page_pdf), strict=False)
    return (reader.pages[0].extract_text() or "").strip()


def use_direct_ollama_glm_ocr() -> bool:
    """Seleciona o modo direto somente quando explicitamente configurado."""
    return os.getenv("RAG_GLM_OCR_MODE", "package").lower() == "direct_ollama"


def direct_ollama_glm_ocr(
    page_path: Path,
) -> tuple[str, str, dict[str, Any] | None]:
    """Extrai uma página com o endpoint nativo do GLM-OCR no Ollama.

    Este modo é útil em máquinas sem GPU: evita o detector de layout local do
    pacote ``glmocr`` e envia uma imagem de cada vez ao modelo GLM-OCR. Uma
    resposta encerrada por limite de tokens é tratada como erro, nunca como
    conteúdo válido parcial.
    """
    import yaml

    config = yaml.safe_load(
        (ROOT / "config" / "glmocr.yaml").read_text(encoding="utf-8")
    )
    pipeline = config.get("pipeline", {})
    api = pipeline.get("ocr_api", {})
    page_loader = pipeline.get("page_loader", {})
    image_path = render_page_image(page_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Imagem da página não encontrada: {image_path}")
    payload = {
        "model": os.getenv("GLMOCR_MODEL", api.get("model", "glm-ocr:latest")),
        "prompt": page_loader.get("task_prompt_mapping", {}).get(
            "text", "Text Recognition:"
        ),
        "images": [base64.b64encode(image_path.read_bytes()).decode("ascii")],
        "stream": False,
        "keep_alive": os.getenv("GLMOCR_KEEP_ALIVE", "5m"),
        "options": {
            "temperature": 0,
            "num_predict": int(
                os.getenv(
                    "GLMOCR_DIRECT_MAX_TOKENS",
                    str(page_loader.get("max_tokens", 2048)),
                )
            ),
        },
    }
    host = api.get("api_host", "localhost")
    port = api.get("api_port", 11434)
    path = api.get("api_path", "/api/generate")
    url = f"http://{host}:{port}/{str(path).lstrip('/')}"
    response = requests.post(
        url,
        json=payload,
        timeout=int(
            os.getenv(
                "GLMOCR_DIRECT_TIMEOUT",
                str(api.get("request_timeout", 300)),
            )
        ),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Resposta inválida do GLM-OCR: objeto JSON esperado.")
    if data.get("done_reason") == "length":
        raise ValueError("Resposta do GLM-OCR truncada por limite de tokens.")
    text = str(data.get("response") or "").strip()
    if not text:
        raise ValueError("GLM-OCR não retornou texto para a página.")
    return text, text, None


def extractor_versions() -> dict[str, str]:
    return {
        "pdf_reader": f"pypdf-{package_version('pypdf')}",
        "docling": f"docling-{package_version('docling')}",
        "glm_ocr": f"glmocr-{package_version('glmocr')}",
    }


def create_or_resume_extraction(
    document_id: int,
    extractor: str,
    total_pages: int,
    retry_errors: bool,
    force: bool,
) -> int:
    extractor_version = extractor_versions()[extractor]
    now = utc_now()
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO silver.silver_document_extractions
                (document_id, extractor, extractor_version, total_pages,
                 processing_status, started_at, updated_at)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s)
            ON CONFLICT (document_id, extractor, extractor_version) DO NOTHING
            RETURNING id
            """,
            (document_id, extractor, extractor_version, total_pages, now, now),
        )
        row = cursor.fetchone()
        if row:
            extraction_id = row[0]
        else:
            cursor.execute(
                """
                SELECT id FROM silver.silver_document_extractions
                WHERE document_id = %s AND extractor = %s
                  AND extractor_version = %s
                """,
                (document_id, extractor, extractor_version),
            )
            extraction_id = cursor.fetchone()[0]
        cursor.execute(
            """
            UPDATE silver.silver_document_extractions
            SET total_pages = %s, updated_at = now()
            WHERE id = %s
            """,
            (total_pages, extraction_id),
        )
        for page_number in range(1, total_pages + 1):
            cursor.execute(
                """
                INSERT INTO silver.silver_page_extractions
                    (extraction_id, document_id, extractor, extractor_version,
                     page_number, processing_status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (extraction_id, page_number) DO NOTHING
                """,
                (
                    extraction_id,
                    document_id,
                    extractor,
                    extractor_version,
                    page_number,
                ),
            )
        connection.commit()
    return extraction_id


def page_is_eligible(status: str, retry_errors: bool, force: bool) -> bool:
    if force:
        return True
    if status == "pending":
        return True
    return retry_errors and status == "error"


def extract_page(
    extractor: str,
    page_pdf: Path,
    docling_converter: Any,
    glmocr_parser: Any,
) -> tuple[str, str, dict[str, Any] | None]:
    if extractor == "pdf_reader":
        text = native_page_text(page_pdf)
        return text, text, None
    if extractor == "docling":
        result = docling_converter.convert(page_pdf)
        markdown = result.document.export_to_markdown()
        return markdown, markdown, None
    if use_direct_ollama_glm_ocr():
        return direct_ollama_glm_ocr(page_pdf)
    result = glmocr_parser.parse(page_pdf, save_layout_visualization=False)
    return result.markdown_result or "", result.markdown_result or "", None


def process_extractions(
    document_id: int | None,
    extractor_names: list[str],
    retry_errors: bool,
    force: bool,
) -> None:
    from docling.document_converter import DocumentConverter
    from glmocr import GlmOcr
    from psycopg.types.json import Jsonb

    versions = extractor_versions()
    documents = bronze_documents(document_id)
    if not documents:
        raise ValueError("Nenhum documento Bronze encontrado.")
    docling_converter = DocumentConverter() if "docling" in extractor_names else None
    glmocr_parser = (
        GlmOcr(config_path=str(ROOT / "config" / "glmocr.yaml"))
        if "glm_ocr" in extractor_names and not use_direct_ollama_glm_ocr()
        else None
    )
    for document in documents:
        pdf_path = RAW_DIR / document["relative_path"]
        paths = page_paths(pdf_path, document["record_id"])
        for extractor in extractor_names:
            extraction_id = create_or_resume_extraction(
                document["record_id"],
                extractor,
                len(paths),
                retry_errors,
                force,
            )
            with connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, page_number, processing_status
                    FROM silver.silver_page_extractions
                    WHERE extraction_id = %s ORDER BY page_number
                    """,
                    (extraction_id,),
                )
                pages = cursor.fetchall()
            for page_id, page_number, status in pages:
                if not page_is_eligible(status, retry_errors, force):
                    continue
                started = time.perf_counter()
                attempt_time = utc_now()
                with connect() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE silver.silver_page_extractions
                        SET processing_status = 'processing',
                            attempt_count = attempt_count + 1,
                            last_attempt_at = %s, updated_at = now(),
                            error_message = NULL
                        WHERE id = %s
                        """,
                        (attempt_time, page_id),
                    )
                    connection.commit()
                try:
                    extracted_text, extracted_markdown, structured = extract_page(
                        extractor,
                        paths[page_number - 1],
                        docling_converter,
                        glmocr_parser,
                    )
                    elapsed = int((time.perf_counter() - started) * 1000)
                    content = extracted_text or extracted_markdown
                    with connect() as connection, connection.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE silver.silver_page_extractions
                            SET source_page_path = %s, extracted_text = %s,
                                extracted_markdown = %s, structured_output = %s,
                                character_count = %s, word_count = %s,
                                content_hash = %s, processing_status = 'success',
                                processing_time_ms = %s, updated_at = now()
                            WHERE id = %s
                            """,
                            (
                                str(paths[page_number - 1].relative_to(ROOT)),
                                extracted_text,
                                extracted_markdown,
                                Jsonb(structured) if structured else None,
                                len(content),
                                len(content.split()),
                                text_hash(content),
                                elapsed,
                                page_id,
                            ),
                        )
                        connection.commit()
                    refresh_silver_document(document["record_id"], extractor)
                except Exception as error:
                    elapsed = int((time.perf_counter() - started) * 1000)
                    with connect() as connection, connection.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE silver.silver_page_extractions
                            SET processing_status = 'error', error_message = %s,
                                processing_time_ms = %s, updated_at = now()
                            WHERE id = %s
                            """,
                            (str(error)[:4000], elapsed, page_id),
                        )
                        connection.commit()
                    refresh_silver_document(document["record_id"], extractor)
            rebuild_extraction(extraction_id, versions[extractor])
            refresh_silver_document(document["record_id"], extractor)


def rebuild_extraction(extraction_id: int, extractor_version: str) -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT page_number, extracted_text, extracted_markdown,
                   processing_status, processing_time_ms, source_page_path,
                   character_count, word_count, content_hash, attempt_count,
                   error_message, last_attempt_at, quality_score,
                   quality_metrics, evaluation_status, evaluation_method,
                   evaluation_model, evaluation_prompt_version,
                   evaluation_error, evaluated_at
            FROM silver.silver_page_extractions
            WHERE extraction_id = %s ORDER BY page_number
            """,
            (extraction_id,),
        )
        rows = cursor.fetchall()
        total = len(rows)
        success = [row for row in rows if row[3] == "success"]
        failed = sum(row[3] == "error" for row in rows)
        processed = sum(row[3] in {"success", "error"} for row in rows)
        complete = len(success) == total and total > 0
        full_text = reconstruct_page_content(
            [
                {"page_number": row[0], "status": row[3], "text": row[1]}
                for row in rows
            ]
        )
        full_markdown = reconstruct_page_content(
            [
                {"page_number": row[0], "status": row[3], "text": row[2]}
                for row in rows
            ]
        )
        status = "success" if complete else ("error" if failed else "pending")
        cursor.execute(
            """
            UPDATE silver.silver_document_extractions
            SET extractor_version = %s, processing_status = %s,
                processed_pages = %s, successful_pages = %s, failed_pages = %s,
                full_text = %s,
                full_markdown = %s,
                character_count = %s,
                word_count = %s,
                processing_time_ms = %s,
                content_hash = CASE WHEN %s THEN %s ELSE NULL END,
                finished_at = CASE WHEN %s THEN now() ELSE NULL END,
                updated_at = now()
            WHERE id = %s
            """,
            (
                extractor_version,
                status,
                processed,
                len(success),
                failed,
                full_text,
                full_markdown,
                len(full_text),
                len(full_text.split()),
                sum(row[4] or 0 for row in rows),
                complete,
                text_hash(full_text) if complete else None,
                complete,
                extraction_id,
            ),
        )
        connection.commit()


def refresh_silver_document(document_id: int, extractor: str) -> None:
    """Atualiza a linha-resumo da Silver a partir do estado por página."""
    if extractor not in {"docling", "glm_ocr"}:
        return
    from psycopg.types.json import Jsonb

    prefix = "docling" if extractor == "docling" else "glm_ocr"
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT page_count FROM bronze.documents WHERE record_id = %s
            """,
            (document_id,),
        )
        total_pages = (cursor.fetchone() or (0,))[0] or 0
        cursor.execute(
            """
            SELECT id, extractor_version, processing_status, processed_pages,
                   failed_pages, full_text, full_markdown, character_count,
                   word_count, processing_time_ms, content_hash,
                   average_quality_score, weighted_quality_score,
                   evaluation_summary, finished_at
            FROM silver.silver_document_extractions
            WHERE document_id = %s AND extractor = %s
            ORDER BY id DESC LIMIT 1
            """,
            (document_id, extractor),
        )
        execution = cursor.fetchone()
        if not execution:
            return
        (
            extraction_id,
            extractor_version,
            processing_status,
            processed_pages,
            failed_pages,
            full_text,
            full_markdown,
            character_count,
            word_count,
            processing_time_ms,
            content_hash,
            average_score,
            weighted_score,
            evaluation_summary,
            processed_at,
        ) = execution
        cursor.execute(
            """
            SELECT page_number, processing_status, extracted_text,
                   extracted_markdown, character_count, word_count,
                   attempt_count, processing_time_ms, content_hash,
                   error_message, last_attempt_at, quality_score,
                   quality_metrics, evaluation_status, evaluation_method,
                   evaluation_model, evaluation_prompt_version,
                   evaluation_error, evaluated_at
            FROM silver.silver_page_extractions
            WHERE extraction_id = %s ORDER BY page_number
            """,
            (extraction_id,),
        )
        pages = []
        for row in cursor.fetchall():
            pages.append(
                {
                    "page_number": row[0],
                    "status": row[1],
                    "text": row[2],
                    "markdown": row[3],
                    "character_count": row[4],
                    "word_count": row[5],
                    "attempt_count": row[6],
                    "processing_time_ms": row[7],
                    "content_hash": row[8],
                    "error": row[9],
                    "processed_at": row[10].isoformat() if row[10] else None,
                    "quality_score": float(row[11]) if row[11] is not None else None,
                    "quality_metrics": row[12],
                    "evaluation_status": row[13],
                    "evaluation_method": row[14],
                    "evaluation_model": row[15],
                    "evaluation_prompt_version": row[16],
                    "evaluation_error": row[17],
                    "evaluated_at": row[18].isoformat() if row[18] else None,
                }
            )
        page_json = Jsonb({"pages": pages})
        cursor.execute(
            """
            INSERT INTO silver.silver_documents (document_id, total_pages)
            VALUES (%s, %s)
            ON CONFLICT (document_id) DO NOTHING
            """,
            (document_id, total_pages),
        )
        cursor.execute(
            f"""
            UPDATE silver.silver_documents
            SET total_pages = %s,
                {prefix}_text = %s, {prefix}_markdown = %s,
                {prefix}_pages = %s, {prefix}_processing_status = %s,
                {prefix}_processed_pages = %s, {prefix}_failed_pages = %s,
                {prefix}_character_count = %s, {prefix}_word_count = %s,
                {prefix}_processing_time_ms = %s, {prefix}_content_hash = %s,
                {prefix}_average_score = %s, {prefix}_weighted_score = %s,
                {prefix}_evaluation = %s, {prefix}_extractor_version = %s,
                {prefix}_processed_at = %s, updated_at = now()
            WHERE document_id = %s
            """,
            (
                total_pages,
                full_text,
                full_markdown,
                page_json,
                processing_status,
                processed_pages,
                failed_pages,
                character_count,
                word_count,
                processing_time_ms,
                content_hash,
                average_score,
                weighted_score,
                Jsonb(evaluation_summary or {}),
                extractor_version,
                processed_at,
                document_id,
            ),
        )
        connection.commit()


def render_page_image(page_path: Path) -> Path:
    return page_path.with_suffix(".png")


def image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def response_text(response: Any) -> str:
    content = response.content if hasattr(response, "content") else response
    if isinstance(content, list):
        return "".join(str(item.get("text", item)) for item in content)
    return str(content)


def parse_json_response(value: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        raise ValueError("A resposta do avaliador não contém JSON.")
    result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("A resposta do avaliador não é um objeto JSON.")
    required = {"overall_score", "confidence", "justification"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"Campos ausentes na avaliação: {sorted(missing)}")
    scores = result.get("scores")
    if scores is None:
        top_level_scores = {
            key: result[key] for key in EVALUATION_SCORE_KEYS if key in result
        }
        if top_level_scores:
            scores = top_level_scores
            result["scores"] = scores
    if not isinstance(scores, dict):
        raise ValueError("A avaliação precisa conter o objeto scores.")
    missing_scores = EVALUATION_SCORE_KEYS - scores.keys()
    if missing_scores:
        raise ValueError(f"Critérios ausentes na avaliação: {sorted(missing_scores)}")
    for criterion, score in scores.items():
        if criterion not in EVALUATION_SCORE_KEYS:
            continue
        if score is not None and not 0 <= float(score) <= 100:
            raise ValueError(f"Nota inválida para {criterion}: {score}")
    result["overall_score"] = max(0.0, min(100.0, float(result["overall_score"])))
    result["confidence"] = max(0.0, min(100.0, float(result["confidence"])))
    return result


def levenshtein(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, left_value in enumerate(left, start=1):
        current = [i]
        for j, right_value in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (left_value != right_value),
                )
            )
        previous = current
    return previous[-1]


def deterministic_metrics(reference: str, extracted: str) -> dict[str, Any]:
    ref_chars = list(reference)
    ext_chars = list(extracted)
    ref_words = reference.split()
    ext_words = extracted.split()
    return {
        "cer": levenshtein(ref_chars, ext_chars) / max(len(ref_chars), 1),
        "wer": levenshtein(ref_words, ext_words) / max(len(ref_words), 1),
        "normalized_similarity": 1
        - levenshtein(ref_chars, ext_chars) / max(len(ref_chars), len(ext_chars), 1),
        "reference_character_count": len(ref_chars),
        "extracted_character_count": len(ext_chars),
        "reference_word_count": len(ref_words),
        "extracted_word_count": len(ext_words),
    }


def evaluate_page(
    page_path: Path, native_text: str, extracted: str, model_name: str
) -> tuple[dict[str, Any], str]:
    from langchain_core.messages import HumanMessage
    from langchain_ollama import ChatOllama

    rubric = """
Avalie somente a página original e a extração fornecidas. Não use conhecimento
externo, web search ou RAG. Responda exclusivamente com JSON válido.
Notas de 0 a 100 para: textual_fidelity, content_completeness, reading_order,
structural_preservation, lists_preservation, tables_preservation,
numbers_and_references, duplication_control, noise_control e
hallucination_control. Use null quando um critério não for aplicável.
Inclua overall_score, confidence, missing_elements, incorrect_elements,
duplicated_elements, hallucinated_elements, requires_manual_review e
justification.
"""
    prompt = (
        rubric
        + "\nTEXTO EXTRAÍDO:\n"
        + extracted
        + "\n\nTEXTO NATIVO AUXILIAR, se houver:\n"
        + native_text
    )
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data_url(page_path)}},
    ]
    model = ChatOllama(
        model=model_name,
        temperature=0,
        base_url=os.getenv("OLLAMA_HOST"),
        reasoning=False,
        format="json",
        num_predict=int(os.getenv("RAG_EVALUATION_MAX_TOKENS", "1200")),
    )
    try:
        result = model.invoke([HumanMessage(content=content)])
        return parse_json_response(response_text(result)), "page_image"
    except Exception:
        if len(native_text.strip()) < 20:
            raise
        text_only = rubric + "\nTEXTO NATIVO:\n" + native_text
        result = model.invoke([HumanMessage(content=text_only)])
        return parse_json_response(response_text(result)), "pdf_reader_text"


def evaluate_extractions(
    document_id: int | None, extractor_names: list[str], retry_errors: bool
) -> None:
    model_name = os.getenv("RAG_EVALUATION_MODEL", os.getenv("OLLAMA_MODEL"))
    from psycopg.types.json import Jsonb
    if not model_name:
        raise ValueError("Defina OLLAMA_MODEL ou RAG_EVALUATION_MODEL no .env.")
    query = """
        SELECT p.id, p.extraction_id, p.source_page_path, p.extracted_text,
               p.extracted_markdown, d.document_id, p.evaluation_status
        FROM silver.silver_page_extractions p
        JOIN silver.silver_document_extractions d ON d.id = p.extraction_id
        WHERE p.processing_status = 'success' AND p.extractor = ANY(%s)
          AND (
              p.evaluation_status = 'pending'
              OR (p.evaluation_status = 'error' AND %s)
          )
    """
    params: list[Any] = [extractor_names, retry_errors]
    if document_id is not None:
        query += " AND d.document_id = %s"
        params.append(document_id)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    for page_id, _extraction_id, source_path, text, markdown, _doc_id, _status in rows:
        page_path = ROOT / source_path
        native = native_page_text(page_path)
        extracted = text or markdown or ""
        started = utc_now()
        try:
            evaluation, method = evaluate_page(
                page_path.with_suffix(".png"), native, extracted, model_name
            )
            metrics = deterministic_metrics(native, extracted)
            metrics["requires_manual_review"] = bool(
                evaluation.get("requires_manual_review", False)
            )
            evaluation_status = "success"
            error = None
        except Exception as exc:
            evaluation = {}
            metrics = None
            if len(native) < 20:
                method = "reference_unavailable"
                evaluation_status = "reference_unavailable"
            else:
                method = "page_image"
                evaluation_status = "error"
            error = str(exc)[:4000]
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE silver.silver_page_extractions
                SET quality_score = %s, quality_metrics = %s,
                    evaluation_status = %s, evaluation_method = %s,
                    evaluation_model = %s, evaluation_prompt_version = %s,
                    evaluation_error = %s, evaluated_at = %s, updated_at = now()
                WHERE id = %s
                """,
                (
                    evaluation.get("overall_score"),
                    Jsonb({**(metrics or {}), "evaluation": evaluation}),
                    evaluation_status,
                    method,
                    model_name,
                    EVALUATION_PROMPT_VERSION,
                    error,
                    started,
                    page_id,
                ),
            )
            connection.commit()
    refresh_quality_aggregates()
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT d.document_id, d.extractor
            FROM silver.silver_document_extractions d
            WHERE d.extractor = ANY(%s)
            """,
            (extractor_names,),
        )
        refreshed = cursor.fetchall()
    for refreshed_document_id, refreshed_extractor in refreshed:
        refresh_silver_document(refreshed_document_id, refreshed_extractor)


def refresh_quality_aggregates() -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE silver.silver_document_extractions d
            SET average_quality_score = q.simple_average,
                weighted_quality_score = q.weighted_average,
                evaluation_summary = q.summary,
                updated_at = now()
            FROM (
                SELECT extraction_id,
                       AVG(quality_score) FILTER (
                           WHERE evaluation_status = 'success'
                       ) AS simple_average,
                       SUM(quality_score * NULLIF(word_count, 0)) /
                       NULLIF(SUM(word_count) FILTER (
                           WHERE evaluation_status = 'success'
                       ), 0) AS weighted_average,
                       jsonb_build_object(
                           'evaluated_pages', COUNT(*) FILTER (
                               WHERE evaluation_status = 'success'
                           ),
                           'failed_pages', COUNT(*) FILTER (
                               WHERE evaluation_status = 'error'
                           )
                       ) AS summary
                FROM silver.silver_page_extractions
                GROUP BY extraction_id
            ) q
            WHERE d.id = q.extraction_id
            """
        )
        connection.commit()


def is_gold_ready(
    processing_status: str,
    total_pages: int,
    successful_pages: int,
    evaluation_statuses: list[str],
    allow_unvalidated: bool = False,
) -> bool:
    """Define o gate de promoção para uma variante completa e validada."""
    if (
        processing_status != "success"
        or total_pages <= 0
        or successful_pages != total_pages
    ):
        return False
    return allow_unvalidated or (
        len(evaluation_statuses) == total_pages
        and all(status == "success" for status in evaluation_statuses)
    )


def comparison_is_ready(rows: list[tuple[Any, ...]]) -> bool:
    """Confirma que Docling e GLM-OCR estão completos e avaliados."""
    return (
        {row[0] for row in rows} == {"docling", "glm_ocr"}
        and len(rows) == 2
        and all(
            row[1] == "success"
            and row[3] == row[2]
            and row[4] == row[2]
            and row[5] == row[2]
            for row in rows
        )
    )


def activate_gold(
    document_id: int,
    extractor: str | None = None,
    allow_unvalidated: bool = False,
) -> int:
    from psycopg.types.json import Jsonb

    with connect() as connection, connection.cursor() as cursor:
        query = """
            SELECT d.id, d.document_id, d.extractor, d.full_text,
                   d.full_markdown, d.total_pages, d.average_quality_score,
                   b.manifest_metadata
            FROM silver.silver_document_extractions d
            JOIN bronze.documents b ON b.record_id = d.document_id
            WHERE d.document_id = %s AND d.processing_status = 'success'
        """
        params: list[Any] = [document_id]
        if extractor:
            query += " AND d.extractor = %s"
            params.append(extractor)
        query += " ORDER BY d.average_quality_score DESC NULLS LAST, d.id DESC LIMIT 1"
        cursor.execute(query, params)
        row = cursor.fetchone()
        if not row:
            raise ValueError("Nenhuma extração completa disponível para ativação.")
        (
            extraction_id,
            doc_id,
            source_extractor,
            full_text,
            full_markdown,
            total_pages,
            quality,
            metadata,
        ) = row
        metadata = metadata or {}
        cursor.execute(
            """
            SELECT COUNT(*) AS total_pages,
                   COUNT(*) FILTER (WHERE processing_status = 'success')
                       AS successful_pages,
                   array_agg(evaluation_status ORDER BY page_number)
                       AS evaluation_statuses
            FROM silver.silver_page_extractions
            WHERE extraction_id = %s
            """,
            (extraction_id,),
        )
        evaluated_total, successful_pages, evaluation_statuses = cursor.fetchone()
        evaluation_statuses = evaluation_statuses or []
        if not is_gold_ready(
            "success",
            evaluated_total,
            successful_pages,
            evaluation_statuses,
            allow_unvalidated,
        ):
            raise ValueError(
                "Extração não validada: avalie todas as páginas antes de promover "
                "para a Gold ou use --allow-unvalidated explicitamente."
            )
        cursor.execute(
            """
            SELECT e.extractor, e.processing_status, e.total_pages,
                   COUNT(p.id) AS page_rows,
                   COUNT(p.id) FILTER (WHERE p.processing_status = 'success')
                       AS successful_pages,
                   COUNT(p.id) FILTER (WHERE p.evaluation_status = 'success')
                       AS evaluated_pages
            FROM silver.silver_document_extractions e
            LEFT JOIN silver.silver_page_extractions p
                ON p.extraction_id = e.id
            WHERE e.document_id = %s AND e.extractor = ANY(%s)
            GROUP BY e.extractor, e.processing_status, e.total_pages
            """,
            (doc_id, ["docling", "glm_ocr"]),
        )
        comparison_rows = cursor.fetchall()
        comparison_ready = comparison_is_ready(comparison_rows)
        if not comparison_ready and not allow_unvalidated:
            raise ValueError(
                "Docling e GLM-OCR precisam estar completos e avaliados antes "
                "da promoção normal para a Gold."
            )
        content_hash = text_hash(full_text)
        token_count = estimated_token_count(full_text)
        token_limit = context_token_limit()
        context_exceeded = token_count > token_limit
        context_warning = (
            f"Documento integral estimado em {token_count} tokens; "
            f"limite configurado: {token_limit}. O texto não foi truncado."
            if context_exceeded
            else None
        )
        cursor.execute(
            """
            INSERT INTO silver.silver_documents (document_id, total_pages)
            VALUES (%s, %s)
            ON CONFLICT (document_id) DO NOTHING
            """,
            (doc_id, total_pages),
        )
        cursor.execute(
            "SELECT id FROM silver.silver_documents WHERE document_id = %s",
            (doc_id,),
        )
        silver_document_id = cursor.fetchone()[0]
        cursor.execute(
            """
            UPDATE silver.silver_documents
            SET selected_extractor = %s, selected_at = now(),
                selection_reason = %s, ready_for_gold = true, updated_at = now()
            WHERE id = %s
            """,
            (
                source_extractor,
                (
                    "Maior média de qualidade disponível; seleção explícita "
                    "para a Gold."
                    if not allow_unvalidated
                    else "Promoção explicitamente autorizada sem avaliação completa."
                ),
                silver_document_id,
            ),
        )
        cursor.execute(
            "UPDATE gold.gold_rag_documents SET is_active = false "
            "WHERE document_id = %s",
            (doc_id,),
        )
        cursor.execute(
            """
            INSERT INTO gold.gold_rag_documents
                (document_id, extraction_id, silver_document_id, title,
                 document_type, issuer, version, document_status, source_extractor,
                full_text, full_markdown,
                 total_pages, token_count, context_token_limit,
                 context_window_exceeded, context_warning, quality_score,
                 content_hash, is_active, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, true, %s)
            ON CONFLICT (document_id, extraction_id) DO UPDATE SET
                full_text = EXCLUDED.full_text,
                full_markdown = EXCLUDED.full_markdown,
                total_pages = EXCLUDED.total_pages,
                token_count = EXCLUDED.token_count,
                context_token_limit = EXCLUDED.context_token_limit,
                context_window_exceeded = EXCLUDED.context_window_exceeded,
                context_warning = EXCLUDED.context_warning,
                quality_score = EXCLUDED.quality_score,
                content_hash = EXCLUDED.content_hash,
                source_extractor = EXCLUDED.source_extractor,
                silver_document_id = EXCLUDED.silver_document_id,
                is_active = true,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
            """,
            (
                doc_id,
                extraction_id,
                silver_document_id,
                metadata.get("title"),
                metadata.get("document_type"),
                metadata.get("issuer"),
                metadata.get("version"),
                metadata.get("status"),
                source_extractor,
                full_text,
                full_markdown,
                total_pages,
                token_count,
                token_limit,
                context_exceeded,
                context_warning,
                quality,
                content_hash,
                Jsonb(metadata),
            ),
        )
        rag_document_id = cursor.fetchone()[0]
        cursor.execute(
            """
            UPDATE gold.gold_rag_documents
            SET search_vector =
                setweight(to_tsvector('portuguese', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('portuguese', coalesce(version, '')), 'B') ||
                setweight(to_tsvector('portuguese', coalesce(full_text, '')), 'C') ||
                setweight(to_tsvector('portuguese', coalesce(metadata::text, '')), 'D'),
                updated_at = now()
            WHERE id = %s
            """,
            (rag_document_id,),
        )
        cursor.execute(
            """
            INSERT INTO gold.gold_rag_page_index
                (rag_document_id, document_id, page_number, page_text,
                 source_extractor, page_content_hash, embedding_model,
                 embedding_dimension, content_hash, search_vector)
            SELECT %s, %s, page_number, extracted_text, %s, content_hash,
                   %s, %s, content_hash,
                   to_tsvector('portuguese', coalesce(extracted_text, ''))
            FROM silver.silver_page_extractions
            WHERE extraction_id = %s AND processing_status = 'success'
            ON CONFLICT (rag_document_id, page_number) DO UPDATE SET
                page_text = EXCLUDED.page_text,
                document_id = EXCLUDED.document_id,
                source_extractor = EXCLUDED.source_extractor,
                page_content_hash = EXCLUDED.page_content_hash,
                search_vector = EXCLUDED.search_vector,
                content_hash = EXCLUDED.content_hash,
                embedding = CASE
                    WHEN gold.gold_rag_page_index.content_hash = EXCLUDED.content_hash
                    THEN gold.gold_rag_page_index.embedding
                    ELSE NULL
                END,
                embedding_content_hash = CASE
                    WHEN gold.gold_rag_page_index.content_hash = EXCLUDED.content_hash
                    THEN gold.gold_rag_page_index.embedding_content_hash
                    ELSE NULL
                END,
                embedding_status = CASE
                    WHEN gold.gold_rag_page_index.content_hash = EXCLUDED.content_hash
                    THEN gold.gold_rag_page_index.embedding_status
                    ELSE 'pending'
                END,
                updated_at = now()
            """,
            (
                rag_document_id,
                doc_id,
                source_extractor,
                EMBEDDING_MODEL,
                EMBEDDING_DIMENSION,
                extraction_id,
            ),
        )
        connection.commit()
    return rag_document_id


class OllamaEmbedder:
    def __init__(self) -> None:
        self.model = EMBEDDING_MODEL
        self.url = os.getenv("OLLAMA_EMBED_URL", EMBEDDING_URL)
        self.digest = self._get_digest()

    def _get_digest(self) -> str:
        base_url = self.url.rsplit("/api/", 1)[0]
        try:
            response = requests.post(
                f"{base_url}/api/show", json={"model": self.model}, timeout=30
            )
            response.raise_for_status()
            data = response.json()
            official_digest = data.get("digest") or data.get("details", {}).get(
                "digest"
            )
            if official_digest:
                return str(official_digest)
            modified_at = data.get("modified_at") or data.get("modifiedAt")
            if modified_at:
                return f"ollama-modified-at:{modified_at}"
            canonical = json.dumps(data, ensure_ascii=False, sort_keys=True)
            return f"ollama-show-sha256:{text_hash(canonical)}"
        except Exception:
            return os.getenv("EMBEDDING_MODEL_DIGEST", "unknown")

    def embed(self, text: str, prefix: str) -> list[float]:
        response = requests.post(
            self.url,
            json={"model": self.model, "input": prefix + text, "truncate": False},
            timeout=int(os.getenv("OLLAMA_EMBED_TIMEOUT", "120")),
        )
        response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise ValueError("/api/embed não retornou exatamente um embedding.")
        vector = embeddings[0]
        if len(vector) != EMBEDDING_DIMENSION:
            raise ValueError(
                f"Dimensão inválida: esperado {EMBEDDING_DIMENSION}, "
                f"recebido {len(vector)}."
            )
        return [float(value) for value in vector]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.10g}" for value in vector) + "]"


def generate_embeddings(document_id: int | None, retry_errors: bool) -> None:
    embedder = OllamaEmbedder()
    query = """
        SELECT p.id, p.page_text, p.content_hash, p.embedding_status,
               p.embedding_content_hash, p.embedding_model,
               p.embedding_dimension, p.model_digest
        FROM gold.gold_rag_page_index p
        JOIN gold.gold_rag_documents d ON d.id = p.rag_document_id
        WHERE d.is_active
    """
    params: list[Any] = []
    if document_id is not None:
        query += " AND d.document_id = %s"
        params.append(document_id)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    for (
        page_id,
        page_text,
        content_hash,
        status,
        embedding_content_hash,
        model,
        dimension,
        digest,
    ) in rows:
        if (
            status == "success"
            and embedding_content_hash == content_hash
            and model == embedder.model
            and dimension == EMBEDDING_DIMENSION
            and digest == embedder.digest
            and not retry_errors
        ):
            continue
        if status == "error" and not retry_errors and model == embedder.model:
            continue
        try:
            vector = embedder.embed(page_text, "search_document: ")
            with connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE gold.gold_rag_page_index
                    SET embedding = %s::vector, embedding_model = %s,
                        embedding_dimension = %s, model_digest = %s,
                        embedding_content_hash = %s,
                        generated_at = now(), embedding_status = 'success',
                        embedding_error = NULL, last_attempt_at = now(),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        vector_literal(vector),
                        embedder.model,
                        EMBEDDING_DIMENSION,
                        embedder.digest,
                        content_hash,
                        page_id,
                    ),
                )
                connection.commit()
        except Exception as error:
            with connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE gold.gold_rag_page_index
                    SET embedding_status = 'error', embedding_error = %s,
                        last_attempt_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (str(error)[:4000], page_id),
                )
                connection.commit()


def search_documents(
    question: str, pages_limit: int, documents_limit: int
) -> list[dict[str, Any]]:
    embedder = OllamaEmbedder()
    vector = vector_literal(embedder.embed(question, "search_query: "))
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            WITH query_params AS (
                SELECT %s::vector AS embedding,
                       websearch_to_tsquery('portuguese', %s) AS tsquery
            ), semantic_pages AS (
                SELECT p.rag_document_id, p.page_number,
                       p.embedding <=> q.embedding AS semantic_distance,
                       NULL::real AS textual_rank
                FROM gold.gold_rag_page_index p
                JOIN gold.gold_rag_documents d ON d.id = p.rag_document_id
                CROSS JOIN query_params q
                WHERE d.is_active AND p.embedding_status = 'success'
                  AND p.embedding IS NOT NULL
                ORDER BY p.embedding <=> q.embedding
                LIMIT %s
            ), textual_pages AS (
                SELECT p.rag_document_id, p.page_number,
                       NULL::double precision AS semantic_distance,
                       ts_rank_cd(p.search_vector, q.tsquery) AS textual_rank
                FROM gold.gold_rag_page_index p
                JOIN gold.gold_rag_documents d ON d.id = p.rag_document_id
                CROSS JOIN query_params q
                WHERE d.is_active AND p.search_vector @@ q.tsquery
                ORDER BY ts_rank_cd(p.search_vector, q.tsquery) DESC
                LIMIT %s
            ), textual_documents AS (
                SELECT d.id AS rag_document_id, NULL::integer AS page_number,
                       NULL::double precision AS semantic_distance,
                       ts_rank_cd(d.search_vector, q.tsquery) AS textual_rank
                FROM gold.gold_rag_documents d
                CROSS JOIN query_params q
                WHERE d.is_active AND d.search_vector @@ q.tsquery
                ORDER BY ts_rank_cd(d.search_vector, q.tsquery) DESC
                LIMIT %s
            ), candidates AS (
                SELECT * FROM semantic_pages
                UNION ALL SELECT * FROM textual_pages
                UNION ALL SELECT * FROM textual_documents
            ), grouped AS (
                SELECT rag_document_id,
                       MIN(semantic_distance) AS best_distance,
                       MAX(textual_rank) AS best_textual_rank,
                       array_agg(DISTINCT page_number ORDER BY page_number)
                           FILTER (WHERE page_number IS NOT NULL) AS pages
                FROM candidates
                GROUP BY rag_document_id
                ORDER BY MIN(semantic_distance) NULLS LAST,
                         MAX(textual_rank) DESC NULLS LAST
                LIMIT %s
            )
            SELECT d.id, d.document_id, d.title, d.version,
                   d.source_extractor, d.quality_score, g.pages,
                   g.best_distance, g.best_textual_rank,
                   d.full_text, d.metadata,
                   d.token_count, d.context_token_limit,
                   d.context_window_exceeded, d.context_warning
            FROM grouped g
            JOIN gold.gold_rag_documents d ON d.id = g.rag_document_id
            ORDER BY g.best_distance NULLS LAST,
                     g.best_textual_rank DESC NULLS LAST
            """,
            (vector, question, pages_limit, pages_limit, pages_limit, documents_limit),
        )
        columns = [item.name for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def extractor_status_query(
    document_id: int | None,
) -> tuple[str, list[Any]]:
    """Monta o filtro de extratores sem parâmetro ``NULL`` sem tipo."""
    query = """
        SELECT e.extractor, e.processing_status, e.total_pages,
               COUNT(p.id) AS page_rows,
               COUNT(p.id) FILTER (WHERE p.processing_status = 'success')
                   AS successful_pages,
               COUNT(p.id) FILTER (WHERE p.evaluation_status = 'success')
                   AS evaluated_pages
        FROM silver.silver_document_extractions e
        LEFT JOIN silver.silver_page_extractions p
            ON p.extraction_id = e.id
        WHERE e.extractor = ANY(%s)
    """
    params: list[Any] = [["docling", "glm_ocr"]]
    if document_id is not None:
        query += " AND e.document_id = %s"
        params.append(document_id)
    query += " GROUP BY e.extractor, e.processing_status, e.total_pages"
    return query, params


def page_status_query(document_id: int | None) -> tuple[str, list[Any]]:
    """Consulta status somente das variantes comparadas na Silver."""
    query = """
        SELECT
            COUNT(*) FILTER (WHERE p.processing_status = 'success') AS success,
            COUNT(*) FILTER (WHERE p.processing_status = 'error') AS errors,
            COUNT(*) FILTER (WHERE p.processing_status = 'pending') AS pending,
            COUNT(*) FILTER (WHERE p.evaluation_status = 'success') AS evaluated,
            COUNT(*) FILTER (WHERE p.evaluation_status = 'error')
                AS evaluation_errors,
            COUNT(*) FILTER (
                WHERE p.evaluation_status IN ('pending', 'reference_unavailable')
            ) AS evaluation_pending
        FROM silver.silver_page_extractions p
        LEFT JOIN silver.silver_document_extractions e
            ON e.id = p.extraction_id
        WHERE p.extractor = ANY(%s)
    """
    params: list[Any] = [["docling", "glm_ocr"]]
    if document_id is not None:
        query += " AND e.document_id = %s"
        params.append(document_id)
    return query, params


def validate_pipeline(document_id: int | None = None) -> dict[str, Any]:
    """Audita invariantes do pipeline sem modificar dados existentes."""
    required_tables = {
        "silver.silver_documents",
        "silver.silver_document_extractions",
        "silver.silver_page_extractions",
        "gold.gold_rag_documents",
        "gold.gold_rag_page_index",
    }
    required_indexes = {
        "idx_gold_rag_page_embedding_hnsw",
        "idx_gold_rag_page_search_vector",
        "idx_gold_rag_documents_search_vector",
    }
    document_filter = ""
    params: list[Any] = []
    if document_id is not None:
        document_filter = " AND d.document_id = %s"
        params.append(document_id)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_schema || '.' || table_name
            FROM information_schema.tables
            WHERE table_schema IN ('silver', 'gold')
            """
        )
        existing_tables = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname IN ('silver', 'gold')
            """
        )
        existing_indexes = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS documents,
                COUNT(*) FILTER (WHERE d.is_active) AS active_documents,
                    COUNT(*) FILTER (
                        WHERE d.is_active AND d.full_text IS NOT NULL
                      AND d.full_text LIKE '%%<<<PÁGINA%%'
                ) AS active_documents_with_markers,
                COUNT(*) FILTER (
                    WHERE d.is_active AND d.search_vector IS NOT NULL
                ) AS active_documents_with_text_search
            FROM gold.gold_rag_documents d
            WHERE true {document_filter}
            """,
            params,
        )
        documents, active_documents, marked_documents, text_documents = (
            cursor.fetchone()
        )
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS pages,
                COUNT(*) FILTER (WHERE p.embedding_status = 'success') AS embedded,
                COUNT(*) FILTER (WHERE p.embedding IS NULL) AS missing_embedding,
                COUNT(*) FILTER (
                    WHERE p.embedding IS NOT NULL AND vector_dims(p.embedding) <> 768
                ) AS invalid_dimensions,
                COUNT(*) FILTER (WHERE p.search_vector IS NOT NULL) AS text_indexed,
                COUNT(*) FILTER (
                    WHERE p.content_hash IS DISTINCT FROM p.embedding_content_hash
                )
                    AS stale_hashes
            FROM gold.gold_rag_page_index p
            JOIN gold.gold_rag_documents d ON d.id = p.rag_document_id
            WHERE d.is_active {document_filter}
            """,
            params,
        )
        page_metrics = cursor.fetchone()
        status_query, status_params = page_status_query(document_id)
        cursor.execute(status_query, status_params)
        page_status = cursor.fetchone()
        extractor_query, extractor_params = extractor_status_query(document_id)
        cursor.execute(extractor_query, extractor_params)
        extractor_rows = cursor.fetchall()

    (
        pages,
        embedded,
        missing_embedding,
        invalid_dimensions,
        text_indexed,
        stale_hashes,
    ) = page_metrics
    (
        extraction_success,
        extraction_errors,
        extraction_pending,
        evaluated,
        evaluation_errors,
        evaluation_pending,
    ) = page_status
    structural_checks = {
        "required_tables": required_tables <= existing_tables,
        "required_indexes": required_indexes <= existing_indexes,
        "active_documents_exist": active_documents > 0,
        "active_documents_have_full_text_markers": (
            active_documents == marked_documents
        ),
        "active_documents_have_text_search": active_documents == text_documents,
        "active_pages_have_embeddings": missing_embedding == 0,
        "embeddings_have_dimension_768": invalid_dimensions == 0,
        "active_pages_have_text_search": pages == text_indexed,
        "embeddings_match_page_hash": stale_hashes == 0,
    }
    quality_checks = {
        "both_extractors_present": {row[0] for row in extractor_rows}
        == {"docling", "glm_ocr"},
        "both_extractors_complete": all(
            row[1] == "success" and row[4] == row[2] and row[3] == row[2]
            for row in extractor_rows
        )
        and len(extractor_rows) == 2,
        "both_extractors_evaluated": all(
            row[5] == row[2] for row in extractor_rows
        )
        and len(extractor_rows) == 2,
        "no_extraction_errors": extraction_errors == 0,
        "no_extraction_pending": extraction_pending == 0,
        "evaluations_complete": evaluation_pending == 0,
        "no_evaluation_errors": evaluation_errors == 0,
    }
    return {
        "document_id": document_id,
        "structural_checks": structural_checks,
        "quality_checks": quality_checks,
        "structural_passed": all(structural_checks.values()),
        "quality_passed": all(quality_checks.values()),
        "validation_passed": all(structural_checks.values())
        and all(quality_checks.values()),
        "documents": {
            "total": documents,
            "active": active_documents,
            "with_markers": marked_documents,
            "with_text_search": text_documents,
        },
        "active_page_embeddings": {
            "pages": pages,
            "embedded": embedded,
            "missing": missing_embedding,
            "invalid_dimensions": invalid_dimensions,
            "text_indexed": text_indexed,
            "stale_hashes": stale_hashes,
        },
        "page_status": {
            "extraction_success": extraction_success,
            "extraction_errors": extraction_errors,
            "extraction_pending": extraction_pending,
            "evaluated": evaluated,
            "evaluation_errors": evaluation_errors,
            "evaluation_pending": evaluation_pending,
        },
        "extractors": [
            {
                "extractor": row[0],
                "processing_status": row[1],
                "total_pages": row[2],
                "page_rows": row[3],
                "successful_pages": row[4],
                "evaluated_pages": row[5],
            }
            for row in extractor_rows
        ],
    }


def parse_ids(value: str | None) -> int | None:
    return int(value) if value else None


def main() -> int:
    configure_utf8_output()
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    extract = subparsers.add_parser("extract")
    extract.add_argument("--document-id")
    extract.add_argument(
        "--extractor",
        choices=["pdf_reader", "docling", "glm_ocr", "all"],
        default="all",
    )
    extract.add_argument("--retry-errors", action="store_true")
    extract.add_argument("--force", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--document-id")
    evaluate.add_argument(
        "--extractor", choices=["docling", "glm_ocr", "all"], default="all"
    )
    evaluate.add_argument("--retry-errors", action="store_true")
    activate = subparsers.add_parser("activate")
    activate.add_argument("document_id")
    activate.add_argument("--extractor", choices=["pdf_reader", "docling", "glm_ocr"])
    activate.add_argument("--allow-unvalidated", action="store_true")
    embed = subparsers.add_parser("embed")
    embed.add_argument("--document-id")
    embed.add_argument("--retry-errors", action="store_true")
    search = subparsers.add_parser("search")
    search.add_argument("question")
    search.add_argument("--pages", type=int, default=12)
    search.add_argument("--documents", type=int, default=5)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--document-id")
    args = parser.parse_args()
    try:
        if args.command == "init-db":
            initialise_database()
        elif args.command == "extract":
            names = (
                list(extractor_versions())
                if args.extractor == "all"
                else [args.extractor]
            )
            process_extractions(
                parse_ids(args.document_id), names, args.retry_errors, args.force
            )
        elif args.command == "evaluate":
            names = (
                ["docling", "glm_ocr"] if args.extractor == "all" else [args.extractor]
            )
            evaluate_extractions(parse_ids(args.document_id), names, args.retry_errors)
        elif args.command == "activate":
            rag_document_id = activate_gold(
                int(args.document_id), args.extractor, args.allow_unvalidated
            )
            print(
                f"Gold ativo: {rag_document_id}"
            )
        elif args.command == "embed":
            generate_embeddings(parse_ids(args.document_id), args.retry_errors)
        elif args.command == "search":
            print(
                json.dumps(
                    search_documents(args.question, args.pages, args.documents),
                    ensure_ascii=False,
                    default=str,
                    indent=2,
                )
            )
        elif args.command == "validate":
            report = validate_pipeline(parse_ids(args.document_id))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if not report["validation_passed"]:
                return 1
    except Exception as error:
        print(f"Erro: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
