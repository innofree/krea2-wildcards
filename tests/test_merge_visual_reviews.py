from __future__ import annotations

from pathlib import Path

import pytest

from common import dump_yaml
from merge_visual_reviews import merge_reviews


def write_review(path: Path, style_id: str) -> None:
    dump_yaml(
        {
            "styles": {
                style_id: {
                    "metrics": {
                        "prompt_adherence": 4,
                        "style_fidelity": 4,
                        "stability": 4,
                        "character_quality": 4,
                        "composition_quality": 4,
                        "compatibility": 4,
                        "distinctiveness": 4,
                        "prompt_efficiency": 4,
                    },
                    "critical_failure": False,
                    "recommendation": "testing",
                    "notes": "Reviewed across all seeds.",
                }
            }
        },
        path,
    )


def test_merge_reviews_requires_exact_coverage(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_review(first, "one")
    write_review(second, "two")
    result = merge_reviews([second, first], {"one", "two"})
    assert list(result["styles"]) == ["one", "two"]


def test_merge_reviews_rejects_duplicate_styles(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_review(first, "one")
    write_review(second, "one")
    with pytest.raises(ValueError, match="duplicate reviewed styles"):
        merge_reviews([first, second])


def test_merge_reviews_rejects_missing_expected_style(tmp_path: Path) -> None:
    review = tmp_path / "review.yaml"
    write_review(review, "one")
    with pytest.raises(ValueError, match="coverage mismatch"):
        merge_reviews([review], {"one", "two"})
