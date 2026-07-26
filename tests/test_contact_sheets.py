from __future__ import annotations

import csv
from pathlib import Path

import pytest

import build_contact_sheets
from build_contact_sheets import load_scorecard, validate_seed_matrix


def write_scorecard(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["style_id", "seed", "image_path"])
        writer.writeheader()
        writer.writerows(rows)


def test_seed_matrix_requires_exact_seed_count() -> None:
    rows = [
        {"style_id": "one", "seed": 1},
        {"style_id": "one", "seed": 2},
        {"style_id": "two", "seed": 1},
    ]
    with pytest.raises(ValueError, match="incomplete styles: two"):
        validate_seed_matrix(rows, 2)


def test_scorecard_rejects_duplicate_style_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_contact_sheets, "ROOT", tmp_path)
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    scorecard = tmp_path / "scorecard.csv"
    relative = image.name
    write_scorecard(
        scorecard,
        [
            {"style_id": "one", "seed": "1", "image_path": relative},
            {"style_id": "one", "seed": "1", "image_path": relative},
        ],
    )
    with pytest.raises(ValueError, match="duplicate style_id and seed"):
        load_scorecard(scorecard, {"one": "family"})


def test_scorecard_rejects_unknown_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_contact_sheets, "ROOT", tmp_path)
    scorecard = tmp_path / "scorecard.csv"
    write_scorecard(
        scorecard,
        [{"style_id": "unknown", "seed": "1", "image_path": "missing.png"}],
    )
    with pytest.raises(ValueError, match="unknown style_id"):
        load_scorecard(scorecard, {"one": "family"})


def test_seed_matrix_accepts_complete_three_seed_styles() -> None:
    rows = [
        {"style_id": style_id, "seed": seed}
        for style_id in ("one", "two")
        for seed in (1001, 2002, 3003)
    ]
    validate_seed_matrix(rows, 3)
