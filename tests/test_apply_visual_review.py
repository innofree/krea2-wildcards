from __future__ import annotations

import pytest

from apply_visual_review import apply_review


def review(score: int = 4) -> dict[str, object]:
    return {
        "prompt_adherence": score,
        "style_fidelity": score,
        "stability": score,
        "character_quality": score,
        "composition_quality": score,
        "compatibility": score,
        "distinctiveness": score,
        "prompt_efficiency": score,
        "critical_failure": False,
        "notes": "Reviewed.",
    }


def test_apply_review_expands_style_scores_to_seed_rows() -> None:
    rows = [
        {"style_id": "one", "seed": "1"},
        {"style_id": "one", "seed": "2"},
    ]
    apply_review(rows, {"one": review()})
    assert [row["prompt_adherence"] for row in rows] == ["4", "4"]
    assert [row["critical_failure"] for row in rows] == ["false", "false"]


def test_apply_review_requires_exact_style_coverage() -> None:
    with pytest.raises(ValueError, match="coverage mismatch"):
        apply_review([{"style_id": "one"}], {"two": review()})


def test_apply_review_can_ignore_extra_reviewed_styles() -> None:
    rows = [{"style_id": "one", "seed": "1"}]
    apply_review(
        rows,
        {"one": review(), "two": review()},
        allow_extra_reviews=True,
    )
    assert rows[0]["prompt_adherence"] == "4"
