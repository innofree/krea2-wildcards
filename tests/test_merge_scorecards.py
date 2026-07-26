from __future__ import annotations

import csv
from pathlib import Path

import pytest

from merge_scorecards import merge_rows


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["style_id", "seed", "score"])
        writer.writeheader()
        writer.writerows(rows)


def test_merge_rows_sorts_unique_style_seed_pairs(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    write_rows(first, [{"style_id": "one", "seed": "2", "score": "4"}])
    write_rows(second, [{"style_id": "one", "seed": "1", "score": "5"}])
    fields, rows = merge_rows([first, second])
    assert fields == ["style_id", "seed", "score"]
    assert [row["seed"] for row in rows] == ["1", "2"]


def test_merge_rows_rejects_duplicate_style_seed(tmp_path: Path) -> None:
    scorecard = tmp_path / "scores.csv"
    write_rows(
        scorecard,
        [
            {"style_id": "one", "seed": "1", "score": "4"},
            {"style_id": "one", "seed": "1", "score": "5"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        merge_rows([scorecard])
