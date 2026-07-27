from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/summarize_results.py"
METRICS = (
    "prompt_adherence",
    "style_fidelity",
    "stability",
    "character_quality",
    "composition_quality",
    "compatibility",
    "distinctiveness",
    "prompt_efficiency",
)


def scorecard(seed: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "style_id": "example_style",
        "seed": seed,
        **{metric: 4 for metric in METRICS},
        "critical_failure": False,
    }
    row.update(overrides)
    return row


def policy(*, pilot: int = 3, approval: int = 5) -> dict[str, Any]:
    return {
        "approval_policy": {
            "minimum_pilot_seeds": pilot,
            "minimum_approval_seeds": approval,
            "minimum_prompt_adherence": 4,
            "minimum_style_fidelity": 3,
            "minimum_stability": 3,
            "minimum_compatibility": 3,
            "maximum_critical_failures": 0,
        }
    }


def run_summary(
    tmp_path: Path,
    rows: list[Any],
    *,
    policy_document: dict[str, Any] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    results = tmp_path / "results.jsonl"
    results.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(json.dumps(policy_document or policy()), encoding="utf-8")
    output = tmp_path / "summary.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(results),
            "--output",
            str(output),
            "--policy",
            str(policy_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output


@pytest.mark.parametrize(
    ("seed_count", "expected_status"),
    [(2, "generated"), (3, "testing"), (5, "approved")],
)
def test_seed_gates_use_policy_boundaries(
    tmp_path: Path, seed_count: int, expected_status: str
) -> None:
    result, output = run_summary(
        tmp_path,
        [scorecard(seed) for seed in range(1, seed_count + 1)],
    )

    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(output.read_text(encoding="utf-8"))["styles"][0]
    assert summary["tested_seeds"] == seed_count
    assert summary["recommended_status"] == expected_status


def test_complete_pilot_below_quality_gate_is_rejected(tmp_path: Path) -> None:
    rows = [scorecard(seed, prompt_adherence=2) for seed in range(1, 4)]
    result, output = run_summary(tmp_path, rows)
    assert result.returncode == 0
    summary = json.loads(output.read_text(encoding="utf-8"))["styles"][0]
    assert summary["recommended_status"] == "rejected"


def test_seed_gates_are_configurable_from_policy(tmp_path: Path) -> None:
    result, output = run_summary(
        tmp_path,
        [scorecard(seed) for seed in range(1, 5)],
        policy_document=policy(pilot=2, approval=4),
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["styles"][0][
        "recommended_status"
    ] == "approved"


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_error"),
    [
        ("prompt_adherence", None, "prompt_adherence"),
        ("style_fidelity", "not-a-score", "style_fidelity"),
        ("stability", 0, "stability"),
        ("character_quality", 5.1, "character_quality"),
        ("composition_quality", float("nan"), "composition_quality"),
    ],
)
def test_every_metric_is_required_numeric_and_in_range(
    tmp_path: Path, field: str, invalid_value: Any, expected_error: str
) -> None:
    row = scorecard(1)
    if invalid_value is None:
        row.pop(field)
    else:
        row[field] = invalid_value

    result, output = run_summary(tmp_path, [row])

    assert result.returncode == 1
    assert expected_error in result.stdout
    assert not output.exists()


@pytest.mark.parametrize("invalid_value", [None, "", "yes", "1", 1, 0])
def test_critical_failure_requires_a_strict_boolean_token(
    tmp_path: Path, invalid_value: Any
) -> None:
    row = scorecard(1)
    if invalid_value is None:
        row.pop("critical_failure")
    else:
        row["critical_failure"] = invalid_value

    result, output = run_summary(tmp_path, [row])

    assert result.returncode == 1
    assert "critical_failure" in result.stdout
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("style_id", None), ("style_id", "   "), ("seed", None), ("seed", "1.5")],
)
def test_style_id_and_seed_are_required(
    tmp_path: Path, field: str, invalid_value: Any
) -> None:
    row = scorecard(1)
    if invalid_value is None:
        row.pop(field)
    else:
        row[field] = invalid_value

    result, output = run_summary(tmp_path, [row])

    assert result.returncode == 1
    assert field in result.stdout
    assert not output.exists()


def test_duplicate_style_and_seed_is_rejected(tmp_path: Path) -> None:
    result, output = run_summary(tmp_path, [scorecard(7), scorecard(7)])

    assert result.returncode == 1
    assert "duplicate scorecard" in result.stdout
    assert not output.exists()


def test_incomplete_row_prevents_all_averaging(tmp_path: Path) -> None:
    complete = scorecard(1)
    incomplete = scorecard(2)
    incomplete.pop("prompt_efficiency")

    result, output = run_summary(tmp_path, [complete, incomplete])

    assert result.returncode == 1
    assert "prompt_efficiency" in result.stdout
    assert not output.exists()


def test_evaluated_prompt_digest_is_preserved_per_style(tmp_path: Path) -> None:
    digest = "a" * 64
    rows = [
        scorecard(
            seed,
            factors_json=json.dumps(
                {"evaluated_prompt_sha256": f"sha256_{digest}"}
            ),
        )
        for seed in range(1, 4)
    ]

    result, output = run_summary(tmp_path, rows)

    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(output.read_text(encoding="utf-8"))["styles"][0]
    assert summary["evaluated_prompt_sha256"] == digest


def test_evaluated_prompt_digest_must_cover_every_seed_consistently(
    tmp_path: Path,
) -> None:
    rows = [
        scorecard(
            1,
            factors_json=json.dumps(
                {"evaluated_prompt_sha256": f"sha256_{'a' * 64}"}
            ),
        ),
        scorecard(2),
        scorecard(
            3,
            factors_json=json.dumps(
                {"evaluated_prompt_sha256": f"sha256_{'b' * 64}"}
            ),
        ),
    ]

    result, output = run_summary(tmp_path, rows)

    assert result.returncode == 1
    assert (
        "incomplete evaluated_prompt_sha256 coverage" in result.stdout
        or "inconsistent evaluated_prompt_sha256 values" in result.stdout
    )
    assert not output.exists()
