from __future__ import annotations

from typing import Any

import pytest

from export_phase6_matrix import PAIRWISE_SPECS
from summarize_phase6_results import summarize
from summarize_results import METRICS


def _job(
    index: int,
    style_id: str,
    mode: str,
    seed: int,
    factors: dict[str, str],
) -> dict[str, Any]:
    return {
        "test_id": f"T{index:06d}",
        "style_id": style_id,
        "mode": mode,
        "seed": seed,
        "factors": factors,
    }


def _scored(
    job: dict[str, Any], *, critical: bool = False, score: int = 4
) -> dict[str, Any]:
    return {
        **job,
        **{metric: score for metric in METRICS},
        "critical_failure": critical,
    }


def _matrix(
    cases: list[tuple[str, str, dict[str, str]]],
    seeds: tuple[int, ...] = (1001, 2002, 3003),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    jobs: list[dict[str, Any]] = []
    for style_id, mode, factors in cases:
        for seed in seeds:
            jobs.append(_job(len(jobs) + 1, style_id, mode, seed, factors))
    return jobs, [_scored(job) for job in jobs]


def test_single_axis_summary_requires_both_axes() -> None:
    cases = [
        ("line_a", "single_axis", {"axis": "linework"}),
        ("line_b", "single_axis", {"axis": "linework"}),
        ("color_a", "single_axis", {"axis": "coloring"}),
        ("color_b", "single_axis", {"axis": "coloring"}),
    ]
    jobs, rows = _matrix(cases)
    report = summarize("single-axis", jobs, rows)
    assert report["complete"] is True
    assert report["tested_axes"] == ["coloring", "linework"]
    assert report["total_cases"] == 4


def test_pairwise_summary_requires_ninety_six_cases_and_six_types() -> None:
    cases = []
    for pair_type, *_ in PAIRWISE_SPECS:
        cases.extend(
            (f"{pair_type}_{index:03d}", "pairwise", {"pair_type": pair_type})
            for index in range(1, 17)
        )
    jobs, rows = _matrix(cases)
    report = summarize("pairwise", jobs, rows)
    assert report["complete"] is True
    assert report["total_cases"] == 96
    assert set(report["cases_per_pair_type"].values()) == {16}


def test_preset_and_random_reports_derive_measured_counts() -> None:
    preset_jobs, preset_rows = _matrix(
        [(f"preset_{index:03d}", "preset_audit", {}) for index in range(1, 101)]
    )
    preset = summarize("presets", preset_jobs, preset_rows)
    assert preset["presets_tested"] == 100
    assert preset["critical_conflicts"] == 0
    assert preset["complete"] is True

    random_jobs, random_rows = _matrix(
        [(f"random_{index:03d}", "random_utility", {}) for index in range(1, 21)]
    )
    random_rows[0]["prompt_adherence"] = 2
    utility = summarize("random-utility", random_jobs, random_rows)
    assert utility["sample_count"] == 20
    assert utility["usable_count"] == 19
    assert utility["utility_rate"] == 0.95


def test_benchmark_requires_and_records_five_seeds() -> None:
    jobs, rows = _matrix(
        [("krea2_turbo_benchmark", "krea2_turbo_benchmark", {})],
        seeds=(1001, 2002, 3003, 4004, 5005),
    )
    report = summarize("benchmark", jobs, rows)
    assert report["complete"] is True
    assert report["distinct_seeds"] == 5
    assert report["sample_count"] == 5
    assert report["model"] == "krea2_turbo_mxfp8"


def test_artist_abc_records_one_recommendation_per_artist() -> None:
    cases = [
        (f"artist_{artist:03d}", mode, {})
        for artist in range(1, 9)
        for mode in ("native_name", "visual_signature", "hybrid")
    ]
    jobs, rows = _matrix(cases)
    for row in rows:
        if row["mode"] == "visual_signature":
            row["style_fidelity"] = 5
    report = summarize("artist-abc", jobs, rows)
    assert report["complete"] is True
    assert report["artist_count"] == 8
    assert report["recommended_modes_recorded"] == 8
    assert set(report["recommended_modes"].values()) == {"visual_signature"}


def test_summary_rejects_metadata_drift_and_missing_seeds() -> None:
    jobs, rows = _matrix([("case_a", "single_axis", {"axis": "linework"})])
    rows[0]["seed"] = 9999
    with pytest.raises(ValueError, match="metadata differs"):
        summarize("single-axis", jobs, rows)

    jobs, rows = _matrix(
        [("case_a", "single_axis", {"axis": "linework"})], seeds=(1001, 2002)
    )
    with pytest.raises(ValueError, match="at least 3 distinct seeds"):
        summarize("single-axis", jobs, rows)
