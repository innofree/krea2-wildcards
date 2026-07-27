from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from apply_artist_abc_review import MODES, apply_review, load_review
from summarize_results import METRICS


def _mode_review(score: int = 4) -> dict[str, object]:
    return {
        "metrics": {metric: score for metric in METRICS},
        "critical_failure": False,
        "notes": "The three seeds preserve the reviewed visual direction.",
    }


def _document(artists: int = 2) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artists": {
            f"artist_{index:03d}": {"modes": {mode: _mode_review() for mode in MODES}}
            for index in range(1, artists + 1)
        },
    }


def _write(path: Path, document: object) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_review_loads_exact_artist_mode_scores(tmp_path: Path) -> None:
    path = tmp_path / "review.yaml"
    _write(path, _document())
    review = load_review(path)
    assert len(review) == 6
    assert review[("artist_001", "visual_signature")]["prompt_adherence"] == 4


def test_apply_review_scores_every_seed_for_each_mode(tmp_path: Path) -> None:
    path = tmp_path / "review.yaml"
    _write(path, _document(1))
    rows = [
        {
            "style_id": "artist_001",
            "mode": mode,
            "seed": str(seed),
            **{metric: "" for metric in METRICS},
            "critical_failure": "",
            "notes": "",
        }
        for mode in MODES
        for seed in (1001, 2002, 3003)
    ]
    apply_review(rows, load_review(path))
    assert all(row["prompt_adherence"] == "4" for row in rows)
    assert all(row["critical_failure"] == "false" for row in rows)
    assert all(row["notes"] for row in rows)


def test_review_rejects_missing_mode_metric_and_coverage(tmp_path: Path) -> None:
    path = tmp_path / "review.yaml"
    document = _document(1)
    del document["artists"]["artist_001"]["modes"]["hybrid"]  # type: ignore[index]
    _write(path, document)
    with pytest.raises(ValueError, match="exactly three"):
        load_review(path)

    document = _document(1)
    del document["artists"]["artist_001"]["modes"]["hybrid"]["metrics"][  # type: ignore[index]
        "stability"
    ]
    _write(path, document)
    with pytest.raises(ValueError, match="exactly eight"):
        load_review(path)

    _write(path, _document(1))
    reviews = load_review(path)
    rows = [{"style_id": "artist_001", "mode": "native_name"}]
    with pytest.raises(ValueError, match="coverage mismatch"):
        apply_review(rows, reviews)


def test_review_requires_boolean_critical_failure(tmp_path: Path) -> None:
    path = tmp_path / "review.yaml"
    document = _document(1)
    document["artists"]["artist_001"]["modes"]["native_name"][  # type: ignore[index]
        "critical_failure"
    ] = "no"
    _write(path, document)
    with pytest.raises(ValueError, match="boolean"):
        load_review(path)
