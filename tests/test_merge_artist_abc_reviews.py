from __future__ import annotations

from pathlib import Path

import pytest

from apply_artist_abc_review import MODES
from common import dump_yaml
from merge_artist_abc_reviews import merge_reviews
from summarize_results import METRICS


def write_review(path: Path, artist_id: str) -> None:
    dump_yaml(
        {
            "schema_version": 1,
            "artists": {
                artist_id: {
                    "modes": {
                        mode: {
                            "metrics": {metric: 4 for metric in METRICS},
                            "critical_failure": False,
                            "notes": f"{mode} was reviewed across all seeds.",
                        }
                        for mode in MODES
                    }
                }
            },
        },
        path,
    )


def test_merge_artist_abc_reviews_requires_exact_coverage(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_review(first, "artist_001")
    write_review(second, "artist_002")
    result = merge_reviews(
        [second, first], {"artist_001", "artist_002"}
    )
    assert list(result["artists"]) == ["artist_001", "artist_002"]
    assert set(result["artists"]["artist_001"]["modes"]) == set(MODES)


def test_merge_artist_abc_reviews_rejects_duplicate_artist(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_review(first, "artist_001")
    write_review(second, "artist_001")
    with pytest.raises(ValueError, match="duplicate reviewed artists"):
        merge_reviews([first, second])


def test_merge_artist_abc_reviews_rejects_missing_expected_artist(
    tmp_path: Path,
) -> None:
    review = tmp_path / "review.yaml"
    write_review(review, "artist_001")
    with pytest.raises(ValueError, match="coverage mismatch"):
        merge_reviews(
            [review], {"artist_001", "artist_002"}
        )
