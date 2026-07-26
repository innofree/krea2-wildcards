from __future__ import annotations

import csv
from pathlib import Path

import pytest

from select_scorecard_styles import select_rows


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["style_id", "seed"])
        writer.writeheader()
        writer.writerows(rows)


def test_select_rows_keeps_all_seeds_for_selected_styles(tmp_path: Path) -> None:
    source = tmp_path / "scores.csv"
    write_rows(
        source,
        [
            {"style_id": "one", "seed": "1"},
            {"style_id": "one", "seed": "2"},
            {"style_id": "two", "seed": "1"},
        ],
    )
    _, rows = select_rows(source, {"one"})
    assert [row["seed"] for row in rows] == ["1", "2"]


def test_select_rows_rejects_missing_selected_style(tmp_path: Path) -> None:
    source = tmp_path / "scores.csv"
    write_rows(source, [{"style_id": "one", "seed": "1"}])
    with pytest.raises(ValueError, match="missing selected styles"):
        select_rows(source, {"two"})
