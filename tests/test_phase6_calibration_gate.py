from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import check_phase6_calibration as gate
from export_phase6_matrix import (
    CALIBRATION_SEEDS,
    PHASE6_PROFILE_FACTOR,
    PHASE6_PROFILE_SHA256,
)


def write_fixture(root: Path) -> Path:
    matrix = root / "tests/prompt_matrix/phase6_calibration_v1.jsonl"
    scored = root / "tests/reports/phase6_calibration_v1/scored.csv"
    report = root / "tests/reports/completion/phase6_calibration.json"
    matrix.parent.mkdir(parents=True)
    scored.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    rows = []
    for case in range(1, 24):
        for seed_index, seed in enumerate(CALIBRATION_SEEDS, start=1):
            rows.append(
                {
                    "schema_version": 1,
                    "test_id": f"PC{len(rows) + 1:06d}",
                    "style_id": f"calibration_case_{case:03d}",
                    "label": f"calibration_case_{case:03d}",
                    "mode": "single_axis",
                    "seed": seed,
                    "prompt": "Show exactly one adult subject in a controlled studio test.",
                    "factors": {
                        "case": f"case_{case:03d}",
                        "seed_slot": f"seed_{seed_index}",
                        "prompt_profile_sha256": PHASE6_PROFILE_FACTOR,
                    },
                }
            )
    matrix.write_text(
        "".join(
            json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    scored.write_text("verified\n", encoding="utf-8")
    document = {
        "schema_version": 1,
        "report_type": "phase6_prompt_profile_calibration",
        "status": "passed",
        "complete": True,
        "matrix_jobs": 69,
        "distinct_seeds": 3,
        "total_cases": 23,
        "critical_failures": 0,
        "prompt_profile_sha256": PHASE6_PROFILE_SHA256,
        "matrix_path": matrix.relative_to(root).as_posix(),
        "matrix_sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
        "scored_path": scored.relative_to(root).as_posix(),
        "scored_sha256": hashlib.sha256(scored.read_bytes()).hexdigest(),
    }
    report.write_text(json.dumps(document), encoding="utf-8")
    return report


def test_calibration_gate_binds_profile_matrix_and_scored_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path.resolve())
    report = write_fixture(tmp_path)

    document = gate.validate_report(report)

    assert document["prompt_profile_sha256"] == PHASE6_PROFILE_SHA256


def test_calibration_gate_rejects_stale_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path.resolve())
    report = write_fixture(tmp_path)
    document = json.loads(report.read_text(encoding="utf-8"))
    document["prompt_profile_sha256"] = "0" * 64
    report.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="prompt_profile_sha256"):
        gate.validate_report(report)
