from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from bind_artist_prompt_evidence import (
    PROMPT_PREFIX,
    PROMPT_SUFFIX,
    atomic_write_json,
    build_binding,
    file_sha256,
    load_validated_binding,
)
from summarize_results import METRICS


ROOT = Path(__file__).resolve().parents[1]


def write_fixture(root: Path) -> tuple[Path, Path]:
    catalog = root / "catalog/artists.yaml"
    matrix = root / "tests/prompt_matrix/artist_v0_8_2.jsonl"
    catalog.parent.mkdir(parents=True)
    matrix.parent.mkdir(parents=True)
    items = {
        "artist_signature_one": {
            "prompt": "An adult portrait uses exact narrow lines and a blue palette.",
            "validation": {"status": "generated"},
        },
        "artist_signature_two": {
            "prompt": "An adult portrait uses broad ink lines and an amber palette.",
            "validation": {"status": "generated"},
        },
    }
    catalog.write_text(
        yaml.safe_dump({"items": items}, sort_keys=False),
        encoding="utf-8",
    )
    rows = []
    for style_id, item in items.items():
        for seed in (1001, 2002, 3003):
            rows.append(
                {
                    "schema_version": 1,
                    "test_id": f"VS{len(rows) + 1:06d}",
                    "style_id": style_id,
                    "mode": "visual_signature",
                    "seed": seed,
                    "prompt": f"{PROMPT_PREFIX}{item['prompt']}{PROMPT_SUFFIX}",
                    "factors": {},
                }
            )
    matrix.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return matrix, catalog


def test_binding_preserves_immutable_matrix_and_current_catalog_hashes(
    tmp_path: Path,
) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/screen/prompt_binding.json"

    document = build_binding(matrix, catalog, root=tmp_path)
    atomic_write_json(binding_path, document)
    styles = load_validated_binding(binding_path)

    assert document["source_matrix"]["sha256"] == file_sha256(matrix)
    assert document["catalog"]["sha256"] == file_sha256(catalog)
    assert document["source_matrix"]["row_count"] == 6
    assert document["style_count"] == 2
    assert styles == document["styles"]
    assert matrix.read_text(encoding="utf-8").count("\n") == 6


def test_binding_rejects_catalog_or_matrix_drift(tmp_path: Path) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/screen/prompt_binding.json"
    atomic_write_json(binding_path, build_binding(matrix, catalog, root=tmp_path))

    catalog_document = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    catalog_document["items"]["artist_signature_one"]["prompt"] += " Changed."
    catalog.write_text(yaml.safe_dump(catalog_document), encoding="utf-8")

    with pytest.raises(ValueError, match="resolved prompt does not exactly bind"):
        load_validated_binding(binding_path)


def test_binding_rejects_catalog_metadata_sha_drift_before_apply(
    tmp_path: Path,
) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/screen/prompt_binding.json"
    atomic_write_json(binding_path, build_binding(matrix, catalog, root=tmp_path))

    catalog_document = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    catalog_document["items"]["artist_signature_one"]["validation"][
        "tested_seeds"
    ] = 1
    catalog.write_text(
        yaml.safe_dump(catalog_document, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no longer matches its matrix or catalog"):
        load_validated_binding(binding_path)


def test_binding_rejects_tampered_payload_digest(tmp_path: Path) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/screen/prompt_binding.json"
    document = build_binding(matrix, catalog, root=tmp_path)
    document["styles"]["artist_signature_one"] = "0" * 64
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="payload digest is stale"):
        load_validated_binding(binding_path)


def test_summary_migrates_digestless_scorecard_through_binding(
    tmp_path: Path,
) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/screen/prompt_binding.json"
    atomic_write_json(binding_path, build_binding(matrix, catalog, root=tmp_path))
    scorecard = tmp_path / "tests/reports/screen/scored.csv"
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "style_id",
        "seed",
        "factors_json",
        *METRICS,
        "critical_failure",
    ]
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for seed in (1001, 2002, 3003):
            writer.writerow(
                {
                    "style_id": "artist_signature_one",
                    "seed": seed,
                    "factors_json": "{}",
                    **{metric: 4 for metric in METRICS},
                    "critical_failure": "false",
                }
            )
    policy = tmp_path / "catalog/evaluation.yaml"
    policy.write_text(
        yaml.safe_dump(
            {
                "approval_policy": {
                    "minimum_pilot_seeds": 3,
                    "minimum_approval_seeds": 5,
                    "minimum_prompt_adherence": 4,
                    "minimum_style_fidelity": 3,
                    "minimum_stability": 3,
                    "minimum_compatibility": 3,
                    "maximum_critical_failures": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tests/reports/screen/summary.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/summarize_results.py"),
            str(scorecard),
            "--policy",
            str(policy),
            "--prompt-binding",
            str(binding_path),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    summary = json.loads(output.read_text(encoding="utf-8"))["styles"][0]
    assert summary["evaluated_prompt_sha256"] == build_binding(
        matrix, catalog, root=tmp_path
    )["styles"]["artist_signature_one"]


def test_apply_revalidates_binding_before_persisting_digest(tmp_path: Path) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/screen/prompt_binding.json"
    document = build_binding(matrix, catalog, root=tmp_path)
    atomic_write_json(binding_path, document)
    digest = document["styles"]["artist_signature_one"]
    summary = tmp_path / "tests/reports/screen/summary.json"
    summary.write_text(
        json.dumps(
            {
                "styles": [
                    {
                        "style_id": "artist_signature_one",
                        "evaluated_prompt_sha256": digest,
                        "tested_seeds": 3,
                        "averages": {
                            "prompt_adherence": 4,
                            "style_fidelity": 3,
                            "stability": 4,
                            "compatibility": 4,
                        },
                        "critical_failures": 0,
                        "recommended_status": "testing",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/apply_evaluation_summary.py"),
            str(summary),
            "--catalog",
            str(catalog),
            "--prompt-binding",
            str(binding_path),
            "--evaluation-id",
            "screen_v0_8_2",
            "--apply",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    updated = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    validation = updated["items"]["artist_signature_one"]["validation"]
    assert validation["status"] == "testing"
    assert validation["evaluated_prompt_sha256"] == digest


def test_combined_five_seed_summary_binds_digestless_pilot_and_retest_rows(
    tmp_path: Path,
) -> None:
    matrix, catalog = write_fixture(tmp_path)
    binding_path = tmp_path / "tests/reports/combined/prompt_binding.json"
    document = build_binding(matrix, catalog, root=tmp_path)
    atomic_write_json(binding_path, document)
    digest = document["styles"]["artist_signature_one"]
    scorecard = tmp_path / "tests/reports/combined/scored.csv"
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "style_id",
        "seed",
        "factors_json",
        *METRICS,
        "critical_failure",
    ]
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for seed in (1001, 2002, 3003, 4004, 5005):
            writer.writerow(
                {
                    "style_id": "artist_signature_one",
                    "seed": seed,
                    "factors_json": (
                        "{}"
                        if seed < 4004
                        else json.dumps(
                            {
                                "evaluated_prompt_sha256": (
                                    f"sha256_{digest}"
                                )
                            }
                        )
                    ),
                    **{metric: 4 for metric in METRICS},
                    "critical_failure": "false",
                }
            )
    policy = tmp_path / "catalog/evaluation.yaml"
    policy.write_text(
        yaml.safe_dump(
            {
                "approval_policy": {
                    "minimum_pilot_seeds": 3,
                    "minimum_approval_seeds": 5,
                    "minimum_prompt_adherence": 4,
                    "minimum_style_fidelity": 3,
                    "minimum_stability": 3,
                    "minimum_compatibility": 3,
                    "maximum_critical_failures": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "tests/reports/combined/summary.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/summarize_results.py"),
            str(scorecard),
            "--policy",
            str(policy),
            "--prompt-binding",
            str(binding_path),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    summary = json.loads(output.read_text(encoding="utf-8"))["styles"][0]
    assert summary["tested_seeds"] == 5
    assert summary["recommended_status"] == "approved"
    assert summary["evaluated_prompt_sha256"] == digest
