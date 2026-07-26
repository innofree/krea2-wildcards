from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common import item_status, iter_catalog_items


ROOT = Path(__file__).resolve().parents[1]


def test_prompt_matrix_and_summary_cli(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    export = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/export_prompt_matrix.py"),
            "--catalog",
            str(ROOT / "catalog"),
            "--output",
            str(matrix),
            "--seed",
            "42",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert export.returncode == 0, export.stderr or export.stdout
    active_count = sum(
        item_status(item) in {"generated", "testing", "approved"}
        for _, _, item in iter_catalog_items(ROOT / "catalog")
    )
    assert len(matrix.read_text(encoding="utf-8").splitlines()) == active_count

    summary = tmp_path / "summary.json"
    report = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/summarize_results.py"),
            str(ROOT / "tests/expected/scored_results.csv"),
            "--output",
            str(summary),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.returncode == 0, report.stderr or report.stdout
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["styles"][0]["tested_seeds"] == 5
    assert data["styles"][0]["recommended_status"] == "approved"
