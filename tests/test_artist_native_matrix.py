from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from export_artist_native_matrix import artist_rows, validate_seeds


ROOT = Path(__file__).resolve().parents[1]


def test_registry_exports_exact_native_name_pilot_matrix() -> None:
    rows = artist_rows(ROOT / "research/artist_registry.yaml")

    assert len(rows) == 900
    assert len({row["style_id"] for row in rows}) == 300
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    assert {row["mode"] for row in rows} == {"native_name"}
    assert len({row["test_id"] for row in rows}) == 900
    assert rows[0]["style_id"] == "artist_001"
    assert rows[-1]["style_id"] == "artist_300"
    assert all("__" not in row["prompt"] for row in rows)
    assert all(row["label"] in row["prompt"] for row in rows)
    assert all("one adult woman" in row["prompt"] for row in rows)
    assert all("eye-level full-length camera" in row["prompt"] for row in rows)


def test_export_cli_is_byte_deterministic(tmp_path: Path) -> None:
    outputs = [tmp_path / "one.jsonl", tmp_path / "two.jsonl"]
    for output in outputs:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/export_artist_native_matrix.py"),
                "--registry",
                str(ROOT / "research/artist_registry.yaml"),
                "--output",
                str(output),
                "--seed",
                "7",
                "--seed",
                "11",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout or result.stderr
        assert len(output.read_text(encoding="utf-8").splitlines()) == 600

    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs]
    assert hashes[0] == hashes[1]


def test_export_rejects_duplicate_seeds_and_incomplete_registry(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="distinct"):
        validate_seeds([1, 1])
    registry = tmp_path / "artists.yaml"
    registry.write_text(
        "artists:\n  artist_001:\n    display_name: example\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="exactly 300"):
        artist_rows(registry)


def test_exported_rows_are_valid_json_objects(tmp_path: Path) -> None:
    output = tmp_path / "matrix.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/export_artist_native_matrix.py"),
            "--output",
            str(output),
            "--seed",
            "42",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 300
    assert all(row["schema_version"] == 1 for row in rows)
