"""Execução ABNT: python -m rag_eval.baseline.run --stage retrieval."""

import argparse
import contextlib
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag_eval.baseline import runtime

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent


def load_cases(path: Path, split: str, *, allow_reserved: bool = False) -> list[dict]:
    if split == "reserved" and not allow_reserved:
        raise ValueError("reserved exige --allow-reserved; não usar para ajustes")
    return [
        case
        for case in json.loads(path.read_text(encoding="utf-8"))
        if case["split"] == split
    ]


def evaluate_cases(cases, stage, readiness, worker) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        row = {"case_id": case["id"], "stage": stage}
        if not readiness["ready"]:
            row.update(status="blocked", reason=readiness["reason"], metrics=None)
        else:
            try:
                row.update(worker(case, stage))
            except subprocess.TimeoutExpired:
                row.update(status="timeout", metrics=None)
            except (subprocess.CalledProcessError, ValueError):
                row.update(status="execution_error", metrics=None)
        rows.append(row)
    return rows


def worker(case: dict, stage: str, *, timeout: int) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "rag_eval.baseline.run",
            "--worker",
            "--stage",
            stage,
        ],
        input=json.dumps(case, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        timeout=timeout,
        check=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["retrieval", "agent"], required=True)
    parser.add_argument(
        "--split", choices=["development", "reserved"], default="development"
    )
    parser.add_argument("--allow-reserved", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        case = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            result = runtime.execute_production(case, args.stage, ROOT)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    cases = load_cases(
        BASELINE / "queries.json", args.split, allow_reserved=args.allow_reserved
    )
    readiness = runtime.preflight(ROOT)
    rows = evaluate_cases(
        cases,
        args.stage,
        readiness,
        lambda case, stage: worker(
            case,
            stage,
            timeout=args.timeout_seconds,
        ),
    )
    now = datetime.now(UTC).isoformat()
    output = args.output or BASELINE / "artifacts" / "runs" / (
        f"{now.replace(':', '-')}-{args.stage}-{args.split}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    from rag_eval.baseline.snapshot import source_hashes

    reference = BASELINE / "artifacts" / "initial_state.json"
    report = {
        "schema_version": 1,
        "created_at": now,
        "stage": args.stage,
        "split": args.split,
        "readiness": readiness,
        "dataset_sha256": hashlib.sha256(
            (BASELINE / "queries.json").read_bytes()
        ).hexdigest(),
        "initial_state_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "implementation_source_hashes": source_hashes(ROOT),
        "experimental_validation_complete": False,
        "cases": rows,
    }
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(output),
                "cases": len(rows),
                "statuses": {
                    s: sum(row["status"] == s for row in rows)
                    for s in sorted({row["status"] for row in rows})
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if all(row["status"] == "executed_unreviewed" for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
