"""Adaptação observacional dos componentes reais, com banco somente leitura."""

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests
from dotenv import dotenv_values, load_dotenv


def environment(root: Path) -> dict[str, str]:
    return {**dotenv_values(root / ".env"), **os.environ}


def preflight(root: Path) -> dict[str, Any]:
    config = environment(root)
    host, model = config.get("OLLAMA_HOST"), config.get("OLLAMA_MODEL")
    if not host or not model:
        return {"ready": False, "reason": "ollama_not_configured"}
    try:
        response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json()["models"]
        names = {row["name"] for row in models}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {"ready": False, "reason": "ollama_unavailable"}
    from data.rag_pipeline import EMBEDDING_MODEL

    required = {
        name if ":" in name else f"{name}:latest" for name in (model, EMBEDDING_MODEL)
    }
    if not required <= names:
        return {
            "ready": False,
            "reason": "required_models_missing",
            "missing_models": sorted(required - names),
        }
    return {
        "ready": True,
        "models": [
            {"name": row["name"], "digest": row.get("digest")}
            for row in models
            if row["name"] in required
        ],
    }


def observed_document(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata") or {}
    return {
        **{
            key: document.get(key)
            for key in (
                "document_id",
                "pages",
                "rrf_score",
                "source_ranks",
                "semantic_search_available",
                "page_context",
            )
        },
        "standard_id": metadata.get("id"),
        "version": document.get("version") or metadata.get("version"),
    }


def execute_production(case: dict[str, Any], stage: str, root: Path) -> dict[str, Any]:
    from data import rag_pipeline
    from src.app.tools import rag_search

    from rag_eval.baseline.metrics import locator_metrics
    from rag_eval.baseline.snapshot import connect_readonly

    load_dotenv(root / ".env")
    original_search = rag_search.search_documents
    traces: list[dict[str, Any]] = []

    def observe(**kwargs):
        started = time.perf_counter()
        documents = original_search(**kwargs)
        traces.append(
            {
                "query": kwargs["question"],
                "parameters": kwargs,
                "seconds": time.perf_counter() - started,
                "documents": [observed_document(d) for d in documents],
            }
        )
        return documents

    with (
        patch.object(rag_pipeline, "connect", lambda: connect_readonly(root)),
        patch.object(rag_search, "search_documents", observe),
    ):
        started = time.perf_counter()
        result = execute_stage(case, stage)
    payload = result.get("tool_payload") or {
        "documents": [doc for trace in traces for doc in trace["documents"]]
    }
    return {
        "status": "executed_unreviewed",
        "seconds": time.perf_counter() - started,
        "result": result,
        "retrieval_traces": traces,
        "metrics": locator_metrics(case, traces, payload),
    }


def execute_stage(case: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage == "retrieval":
        import json

        from src.app.query_planner import contextualize_query
        from src.app.tools.rag_search import rag_document_search

        query = contextualize_query(case["question"], case.get("history", []))
        return {
            "tool_payload": json.loads(rag_document_search.invoke({"question": query}))
        }
    from src.app.agente import build_agent
    from src.app.evidence import _tool_payloads, extract_agent_result

    result = build_agent().invoke(
        {
            "messages": [
                *case.get("history", []),
                {"role": "user", "content": case["question"]},
            ]
        }
    )
    extracted = extract_agent_result(result)
    return {
        "answer": extracted.answer,
        "evidences": extracted.evidences,
        "tool_payload": {
            "documents": [
                doc
                for payload in _tool_payloads(result)
                for doc in payload.get("documents", [])
            ]
        },
        "messages": [
            message.model_dump() if hasattr(message, "model_dump") else message
            for message in result.get("messages", [])
        ],
    }
