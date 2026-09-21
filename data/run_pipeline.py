"""Orquestra o fluxo completo Bronze -> Silver -> Gold -> RAG.

Uso:
    uv run python data/run_pipeline.py --skip-bronze
"""

# Especificadores de execução:
#
# Fluxo completo:
#   uv run python data/run_pipeline.py
#
# Fluxo para um documento já existente na Bronze e GLM-OCR direto via Ollama:
#   uv run python data/run_pipeline.py --document-id 8 --skip-bronze \
#       --direct-glm-ocr
#
# Ordem das etapas:
#   Bronze -> init-db -> extract -> evaluate -> activate -> embed -> validate
#
# Retomada somente de páginas/embeddings com erro:
#   uv run python data/run_pipeline.py --retry-errors
#
# Conferência sem executar comandos ou acessar o banco:
#   uv run python data/run_pipeline.py --dry-run
#
# Controle por etapa:
#   --skip-bronze       pula a carga/atualização da Bronze
#   --skip-init-db      pula a criação/verificação do schema
#   --skip-extract      pula a extração por página
#   --skip-evaluate     pula a avaliação das extrações
#   --skip-activate     pula a promoção para Gold
#   --skip-embed        pula a geração dos embeddings
#   --skip-validate     pula a validação final
#
# Outros especificadores:
#   --document-id N     limita a execução ao documento N
#   --extractor all|docling|glm_ocr
#   --force             reprocessa páginas já concluídas
#   --allow-unvalidated permite promoção experimental sem validação completa

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BRONZE_SCRIPT = ROOT / "data" / "bronze_postgres.py"
RAG_SCRIPT = ROOT / "data" / "rag_pipeline.py"


@dataclass(frozen=True)
class PipelineOptions:
    document_id: int | None = None
    extractor: str = "all"
    retry_errors: bool = False
    force: bool = False
    allow_unvalidated: bool = False
    direct_glm_ocr: bool = False
    dry_run: bool = False
    skip_bronze: bool = False
    skip_init_db: bool = False
    skip_extract: bool = False
    skip_evaluate: bool = False
    skip_activate: bool = False
    skip_embed: bool = False
    skip_validate: bool = False


@dataclass(frozen=True)
class PipelineStep:
    name: str
    command: tuple[str, ...]


def script_command(script: Path, *arguments: str) -> tuple[str, ...]:
    return (sys.executable, str(script), *arguments)


def document_argument(document_id: int | None) -> tuple[str, ...]:
    return ("--document-id", str(document_id)) if document_id is not None else ()


def build_pipeline_steps(options: PipelineOptions) -> tuple[PipelineStep, ...]:
    """Constrói a ordem determinística sem executar comandos externos."""
    steps: list[PipelineStep] = []
    if not options.skip_bronze:
        steps.append(PipelineStep("bronze", script_command(BRONZE_SCRIPT)))
    if not options.skip_init_db:
        steps.append(
            PipelineStep("init-db", script_command(RAG_SCRIPT, "init-db"))
        )
    if not options.skip_extract:
        extract_args = (
            "extract",
            *document_argument(options.document_id),
            "--extractor",
            options.extractor,
        )
        if options.retry_errors:
            extract_args += ("--retry-errors",)
        if options.force:
            extract_args += ("--force",)
        steps.append(PipelineStep("extract", script_command(RAG_SCRIPT, *extract_args)))
    if not options.skip_evaluate:
        evaluate_args = (
            "evaluate",
            *document_argument(options. document_id),
            "--extractor",
            options.extractor,
        )
        if options.retry_errors:
            evaluate_args += ("--retry-errors",)
        steps.append(
            PipelineStep("evaluate", script_command(RAG_SCRIPT, *evaluate_args))
        )
    if not options.skip_activate:
        if options.document_id is None:
            activate_command: tuple[str, ...] = ()
        else:
            activate_args = ("activate", str(options.document_id))
            if options.allow_unvalidated:
                activate_args += ("--allow-unvalidated",)
            activate_command = script_command(RAG_SCRIPT, *activate_args)
        steps.append(
            PipelineStep("activate", activate_command)
        )
    if not options.skip_embed:
        embed_args = ("embed", *document_argument(options.document_id))
        if options.retry_errors:
            embed_args += ("--retry-errors",)
        steps.append(PipelineStep("embed", script_command(RAG_SCRIPT, *embed_args)))
    if not options.skip_validate:
        validate_args = ("validate", *document_argument(options.document_id))
        steps.append(
            PipelineStep("validate", script_command(RAG_SCRIPT, *validate_args))
        )
    return tuple(steps)


def pipeline_environment(options: PipelineOptions) -> dict[str, str]:
    environment = os.environ.copy()
    if options.direct_glm_ocr:
        environment["RAG_GLM_OCR_MODE"] = "direct_ollama"
    return environment


def discover_document_ids(document_id: int | None) -> list[int]:
    if document_id is not None:
        return [document_id]
    from data.rag_pipeline import bronze_documents

    ids = [int(row["record_id"]) for row in bronze_documents()]
    if not ids:
        raise RuntimeError("Nenhum documento encontrado na Bronze.")
    return ids


def run_step(
    step: PipelineStep,
    environment: dict[str, str],
    dry_run: bool,
) -> None:
    command_text = " ".join(step.command) if step.command else "(aguarda IDs da Bronze)"
    print(f"[pipeline] {step.name}: {command_text}", flush=True)
    if not dry_run:
        subprocess.run(step.command, cwd=ROOT, env=environment, check=True)


def run_pipeline(options: PipelineOptions) -> None:
    environment = pipeline_environment(options)
    for step in build_pipeline_steps(options):
        if step.name != "activate" or options.document_id is not None:
            run_step(step, environment, options.dry_run)
            continue
        if options.dry_run:
            run_step(step, environment, True)
            continue
        document_ids = discover_document_ids(options.document_id)
        for document_id in document_ids:
            activation = PipelineStep(
                "activate",
                script_command(RAG_SCRIPT, "activate", str(document_id))
                + (("--allow-unvalidated",) if options.allow_unvalidated else ()),
            )
            run_step(activation, environment, options.dry_run)


def parse_args() -> PipelineOptions:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=int)
    parser.add_argument(
        "--extractor", choices=["all", "docling", "glm_ocr"], default="all"
    )
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-unvalidated", action="store_true")
    parser.add_argument(
        "--direct-glm-ocr",
        action="store_true",
        help="usa o modo direto /api/generate do GLM-OCR",
    )
    parser.add_argument("--dry-run", action="store_true")
    for name, help_text in (
        ("bronze", "não executa a carga Bronze"),
        ("init-db", "não inicializa Silver/Gold"),
        ("extract", "não executa extração"),
        ("evaluate", "não executa avaliação"),
        ("activate", "não promove para Gold"),
        ("embed", "não gera embeddings"),
        ("validate", "não valida o resultado"),
    ):
        parser.add_argument(f"--skip-{name}", action="store_true", help=help_text)
    args = parser.parse_args()
    return PipelineOptions(
        document_id=args.document_id,
        extractor=args.extractor,
        retry_errors=args.retry_errors,
        force=args.force,
        allow_unvalidated=args.allow_unvalidated,
        direct_glm_ocr=args.direct_glm_ocr,
        dry_run=args.dry_run,
        skip_bronze=args.skip_bronze,
        skip_init_db=args.skip_init_db,
        skip_extract=args.skip_extract,
        skip_evaluate=args.skip_evaluate,
        skip_activate=args.skip_activate,
        skip_embed=args.skip_embed,
        skip_validate=args.skip_validate,
    )


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from data.rag_pipeline import configure_utf8_output

    configure_utf8_output()
    load_dotenv(ROOT / ".env")
    options = parse_args()
    try:
        run_pipeline(options)
    except subprocess.CalledProcessError as error:
        print(
            f"[pipeline] etapa interrompida com código {error.returncode}.",
            file=sys.stderr,
        )
        return error.returncode or 1
    except Exception as error:
        print(f"[pipeline] erro: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
