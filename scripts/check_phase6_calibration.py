#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from export_phase6_matrix import (
    CALIBRATION_SEEDS,
    PHASE6_PROFILE_FACTOR,
    PHASE6_PROFILE_SHA256,
)
from run_remote_prompt_matrix import load_jobs


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = Path("tests/reports/completion/phase6_calibration.json")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_file(raw: Any, *, field: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{field} must be a repository-relative file")
    value = Path(raw)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"{field} must be a repository-relative file")
    resolved = (ROOT / value).resolve()
    resolved.relative_to(ROOT.resolve())
    if not resolved.is_file():
        raise ValueError(f"{field} does not exist")
    return resolved


def validate_report(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("calibration report must be a JSON object")
    required = {
        "schema_version": 1,
        "report_type": "phase6_prompt_profile_calibration",
        "status": "passed",
        "complete": True,
        "matrix_jobs": 69,
        "distinct_seeds": 3,
        "total_cases": 23,
        "critical_failures": 0,
        "prompt_profile_sha256": PHASE6_PROFILE_SHA256,
    }
    for field, expected in required.items():
        if document.get(field) != expected:
            raise ValueError(f"calibration report field mismatch: {field}")
    matrix = repository_file(document.get("matrix_path"), field="matrix_path")
    scored = repository_file(document.get("scored_path"), field="scored_path")
    if file_sha256(matrix) != document.get("matrix_sha256"):
        raise ValueError("calibration matrix digest mismatch")
    if file_sha256(scored) != document.get("scored_sha256"):
        raise ValueError("calibration scored digest mismatch")
    jobs = load_jobs(matrix)
    if len(jobs) != 69:
        raise ValueError("calibration matrix must contain exactly 69 jobs")
    if {job["seed"] for job in jobs} != set(CALIBRATION_SEEDS):
        raise ValueError("calibration matrix must use the exact three screening seeds")
    if {job["factors"].get("prompt_profile_sha256") for job in jobs} != {
        PHASE6_PROFILE_FACTOR
    }:
        raise ValueError("calibration matrix prompt profile is stale")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require a fresh passing Phase 6 prompt-profile calibration"
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    try:
        report = args.report
        if not report.is_absolute():
            report = ROOT / report
        validate_report(report.resolve())
        print("OK: Phase 6 prompt-profile calibration gate passed.")
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
