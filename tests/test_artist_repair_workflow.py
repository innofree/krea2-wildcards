from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from bind_artist_prompt_evidence import atomic_write_json, build_binding
from common import canonical_prompt_sha256
from export_artist_testing_retest_matrix import retest_rows
from export_artist_visual_signature_matrix import (
    AXIS_CALIBRATION_PROFILE,
    AXIS_CALIBRATION_SEEDS,
    EDITORIAL_CALIBRATION_PROFILE,
    EDITORIAL_CALIBRATION_SEEDS,
    FRAMING_CALIBRATION_PROFILE,
    FRAMING_CALIBRATION_SEEDS,
    LEGACY_BENCHMARK_PROFILE,
    REPAIR_BENCHMARK_PROFILE,
    REPAIR_SEEDS,
    REINFORCED_AXIS_CALIBRATION_PROFILE,
    REINFORCED_AXIS_CALIBRATION_SEEDS,
    REINFORCED_AXIS_REPAIR_PROFILE,
    REINFORCED_AXIS_REPAIR_SEEDS,
    SINGLE_VIEW_CALIBRATION_PROFILE,
    SINGLE_VIEW_CALIBRATION_SEEDS,
    signature_rows,
    write_immutable_jsonl,
)
from prepare_artist_repair_result import build_accumulation_summary
from prepare_artist_screen_repair_lifecycle import build_lifecycle_summary
from select_artist_testing_pilot import (
    build_pilot_rows,
    validate_extension_rows,
)
from summarize_results import METRICS


def artist_item(status: str, index: int) -> dict[str, object]:
    axes = {
        "line_language": [f"line_{index}"],
        "face_design": [f"face_{index}"],
        "eye_design": [f"eye_{index}"],
        "body_design": [f"body_{index}"],
        "palette_language": [f"palette_{index}"],
        "light_modeling": [f"light_{index}"],
        "framing_language": [f"framing_{index}"],
        "ornament_language": [f"ornament_{index}"],
    }
    return {
        "family": "artist_signature",
        "visual_axes": list(axes),
        "feature_axes": axes,
        "prompt": (
            f"An adult portrait uses exact contour family {index}, clear face geometry, "
            "layered eye construction, coherent anatomy, separated colors, graphic shadow "
            "edges, balanced placement, and repeating garment motifs."
        ),
        "validation": {"status": status, "tested_seeds": 0},
        "generation": {"kind": "artist_signature"},
    }


def write_catalog(
    root: Path, statuses: dict[str, str]
) -> tuple[Path, dict[str, dict[str, object]]]:
    items = {
        style_id: artist_item(status, index)
        for index, (style_id, status) in enumerate(sorted(statuses.items()), start=1)
    }
    path = root / "catalog/artists.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"items": items}, sort_keys=False),
        encoding="utf-8",
    )
    return path, items


def summary_style(
    style_id: str,
    item: dict[str, object],
    recommendation: str,
) -> dict[str, object]:
    return {
        "style_id": style_id,
        "sample_count": 3,
        "tested_seeds": 3,
        "averages": {
            "prompt_adherence": 4,
            "style_fidelity": 4,
            "stability": 4,
            "character_quality": 4,
            "composition_quality": 4,
            "compatibility": 4,
            "distinctiveness": 4,
            "prompt_efficiency": 4,
        },
        "critical_failures": 0,
        "recommended_status": recommendation,
        "evaluated_prompt_sha256": canonical_prompt_sha256(item["prompt"]),
    }


def write_summary(path: Path, styles: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": 1, "style_count": len(styles), "styles": styles},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def create_binding(
    root: Path,
    catalog: Path,
    matrix_name: str,
    *,
    profile: str = LEGACY_BENCHMARK_PROFILE,
    statuses: tuple[str, ...] = ("generated",),
    count: int,
) -> tuple[Path, list[dict[str, object]]]:
    seeds = {
        REPAIR_BENCHMARK_PROFILE: REPAIR_SEEDS,
        REINFORCED_AXIS_REPAIR_PROFILE: REINFORCED_AXIS_REPAIR_SEEDS,
    }.get(profile, (1001, 2002, 3003))
    rows = signature_rows(
        catalog,
        seeds=seeds,
        statuses=statuses,
        include_prompt_digest=profile
        in {REPAIR_BENCHMARK_PROFILE, REINFORCED_AXIS_REPAIR_PROFILE},
        benchmark_profile=profile,
        require_signature_count=count,
    )
    matrix = root / f"tests/prompt_matrix/{matrix_name}.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = root / f"tests/reports/{matrix_name}/prompt_binding.json"
    atomic_write_json(binding, build_binding(matrix, catalog, root=root))
    return binding, rows


def test_screen_lifecycle_defers_only_rejected_and_records_source_hashes(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {"artist_one": "generated", "artist_two": "generated", "artist_three": "generated"},
    )
    binding, _ = create_binding(
        tmp_path, catalog, "legacy", count=3
    )
    source = tmp_path / "tests/reports/legacy/summary.json"
    write_summary(
        source,
        [
            summary_style("artist_one", items["artist_one"], "testing"),
            summary_style("artist_two", items["artist_two"], "testing"),
            summary_style("artist_three", items["artist_three"], "rejected"),
        ],
    )

    first = build_lifecycle_summary(
        source,
        binding,
        catalog,
        root=tmp_path,
        expected_testing=2,
        expected_rejected=1,
    )
    second = build_lifecycle_summary(
        source,
        binding,
        catalog,
        root=tmp_path,
        expected_testing=2,
        expected_rejected=1,
    )

    assert first == second
    assert first["repair_lifecycle"]["original_recommendation_counts"] == {
        "rejected": 1,
        "testing": 2,
    }
    assert first["repair_lifecycle"]["transformed_recommendation_counts"] == {
        "generated": 1,
        "testing": 2,
    }
    assert {
        item["style_id"]: item["recommended_status"] for item in first["styles"]
    } == {
        "artist_one": "testing",
        "artist_three": "generated",
        "artist_two": "testing",
    }
    assert len(first["repair_lifecycle"]["source_summary"]["sha256"]) == 64
    assert len(first["repair_lifecycle"]["source_binding"]["sha256"]) == 64


def test_screen_lifecycle_rejects_wrong_counts_and_catalog_prompt_drift(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path, {"artist_one": "generated", "artist_two": "generated"}
    )
    binding, _ = create_binding(tmp_path, catalog, "legacy", count=2)
    source = tmp_path / "tests/reports/legacy/summary.json"
    write_summary(
        source,
        [
            summary_style("artist_one", items["artist_one"], "testing"),
            summary_style("artist_two", items["artist_two"], "rejected"),
        ],
    )

    with pytest.raises(ValueError, match="minimum is 2"):
        build_lifecycle_summary(
            source,
            binding,
            catalog,
            root=tmp_path,
            expected_testing=2,
            expected_rejected=0,
        )

    changed = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    changed["items"]["artist_two"]["prompt"] += " Drifted."
    catalog.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="resolved prompt does not exactly bind"):
        build_lifecycle_summary(
            source,
            binding,
            catalog,
            root=tmp_path,
            expected_testing=1,
            expected_rejected=1,
        )


def test_repair_profile_uses_exact_three_seeds_digest_and_axis_ledger(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(tmp_path, {"artist_repair": "generated"})
    rows = signature_rows(
        catalog,
        seeds=REPAIR_SEEDS,
        benchmark_profile=REPAIR_BENCHMARK_PROFILE,
        require_signature_count=1,
    )

    assert len(rows) == 3
    assert {row["seed"] for row in rows} == set(REPAIR_SEEDS)
    for row in rows:
        factors = row["factors"]
        assert factors["benchmark_profile"] == REPAIR_BENCHMARK_PROFILE
        assert factors["benchmark_stage"] == "pilot"
        assert factors["evaluated_prompt_sha256"] == (
            "sha256_" + canonical_prompt_sha256(items["artist_repair"]["prompt"])
        )
        prompt = row["prompt"]
        assert prompt.count(items["artist_repair"]["prompt"]) == 1
        assert "outer contour and garment seams" in prompt
        assert "jaw, cheeks, and nose" in prompt
        assert "hair and accessories away from fully exposed eyes" in prompt
        assert "shoulder and torso silhouette" in prompt
        assert "broad garment and background regions" in prompt
        assert "shadow edges and highlights on the face" in prompt
        assert "head, face, and both hands uncropped" in prompt
        assert "repeating broad garment motif" in prompt
        assert "outer-border motif" in prompt
        assert "leaving the head, face, eyes" in prompt
        assert "line 1" in prompt
        assert "ornament 1" in prompt

    matrix = tmp_path / "tests/prompt_matrix/repair.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == REPAIR_BENCHMARK_PROFILE
    assert binding["benchmark_stage"] == "pilot"

    tampered = [dict(row) for row in rows]
    tampered[0] = {**tampered[0], "factors": dict(tampered[0]["factors"])}
    tampered[0]["factors"]["benchmark_profile"] = "unknown_profile"
    bad = tmp_path / "tests/prompt_matrix/bad.jsonl"
    write_immutable_jsonl(bad, tampered)
    with pytest.raises(ValueError, match="unsupported benchmark_profile"):
        build_binding(bad, catalog, root=tmp_path)


def test_framing_calibration_profile_is_short_framing_first_and_exact(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {f"artist_calibration_{index}": "generated" for index in range(1, 7)},
    )
    rows = signature_rows(
        catalog,
        seeds=FRAMING_CALIBRATION_SEEDS,
        benchmark_profile=FRAMING_CALIBRATION_PROFILE,
        limit_signatures=5,
        require_candidate_count=6,
        require_signature_count=5,
    )
    selected = {row["style_id"] for row in rows}

    assert len(rows) == 15
    assert len(selected) == 5
    assert {row["seed"] for row in rows} == set(FRAMING_CALIBRATION_SEEDS)
    for row in rows:
        body = items[row["style_id"]]["prompt"]
        factors = row["factors"]
        prompt = row["prompt"]
        assert factors["benchmark_profile"] == FRAMING_CALIBRATION_PROFILE
        assert factors["benchmark_stage"] == "calibration"
        assert factors["evaluated_prompt_sha256"] == (
            "sha256_" + canonical_prompt_sha256(body)
        )
        assert prompt.startswith("Full-body character sheet, camera far back.")
        assert prompt.count(body) == 1
        assert len(prompt) <= 1400
        assert len(prompt.split()) <= 200
        assert "complete hair-to-shoes silhouette" in prompt
        assert "Never zoom, crop" in prompt
        assert "framing=framing" in prompt
        assert "outer border" in prompt
        assert "full silhouette, face, eyes, hands visible" in prompt

    matrix = tmp_path / "tests/prompt_matrix/framing_calibration.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == FRAMING_CALIBRATION_PROFILE
    assert binding["benchmark_stage"] == "calibration"

    with pytest.raises(ValueError, match="requires seeds"):
        signature_rows(
            catalog,
            seeds=(7101, 7202, 9999),
            benchmark_profile=FRAMING_CALIBRATION_PROFILE,
            limit_signatures=5,
            require_candidate_count=6,
        )
    with pytest.raises(ValueError, match="exactly 5 limited"):
        signature_rows(
            catalog,
            seeds=FRAMING_CALIBRATION_SEEDS,
            benchmark_profile=FRAMING_CALIBRATION_PROFILE,
            limit_signatures=4,
            require_candidate_count=6,
        )
    with pytest.raises(ValueError, match="required exactly 5 before limiting"):
        signature_rows(
            catalog,
            seeds=FRAMING_CALIBRATION_SEEDS,
            benchmark_profile=FRAMING_CALIBRATION_PROFILE,
            limit_signatures=5,
            require_candidate_count=5,
        )


def test_single_view_calibration_forbids_turnarounds_and_strengthens_axes(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {f"artist_single_view_{index}": "generated" for index in range(1, 7)},
    )
    rows = signature_rows(
        catalog,
        seeds=SINGLE_VIEW_CALIBRATION_SEEDS,
        benchmark_profile=SINGLE_VIEW_CALIBRATION_PROFILE,
        limit_signatures=5,
        require_candidate_count=6,
        require_signature_count=5,
    )

    assert len(rows) == 15
    assert len({row["style_id"] for row in rows}) == 5
    assert {row["seed"] for row in rows} == set(SINGLE_VIEW_CALIBRATION_SEEDS)
    for row in rows:
        body = items[row["style_id"]]["prompt"]
        prompt = row["prompt"]
        assert row["factors"]["benchmark_profile"] == SINGLE_VIEW_CALIBRATION_PROFILE
        assert row["factors"]["benchmark_stage"] == "calibration"
        assert prompt.startswith("Full-body single-view, camera far back.")
        assert prompt.count(body) == 1
        assert len(prompt) <= 1500
        assert len(prompt.split()) <= 210
        assert "exactly one adult woman once" in prompt
        assert "no duplicate, lineup, alternate view" in prompt
        assert "turnaround" in prompt
        assert "Make each cue bold and independent" in prompt
        assert "repeated garment motif and flat outer border" in prompt
        assert "one full silhouette, face, eyes, hands" in prompt

    matrix = tmp_path / "tests/prompt_matrix/single_view_calibration.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == SINGLE_VIEW_CALIBRATION_PROFILE
    assert binding["benchmark_stage"] == "calibration"

    with pytest.raises(ValueError, match="single-view calibration profile requires seeds"):
        signature_rows(
            catalog,
            seeds=(8101, 8202, 9999),
            benchmark_profile=SINGLE_VIEW_CALIBRATION_PROFILE,
            limit_signatures=5,
            require_candidate_count=6,
        )


def test_editorial_calibration_uses_proven_positive_head_to_toe_anchors(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {f"artist_editorial_{index}": "generated" for index in range(1, 7)},
    )
    rows = signature_rows(
        catalog,
        seeds=EDITORIAL_CALIBRATION_SEEDS,
        benchmark_profile=EDITORIAL_CALIBRATION_PROFILE,
        limit_signatures=5,
        require_candidate_count=6,
        require_signature_count=5,
    )

    assert len(rows) == 15
    assert {row["seed"] for row in rows} == set(EDITORIAL_CALIBRATION_SEEDS)
    for row in rows:
        body = items[row["style_id"]]["prompt"]
        prompt = row["prompt"]
        assert row["factors"]["benchmark_profile"] == EDITORIAL_CALIBRATION_PROFILE
        assert row["factors"]["benchmark_stage"] == "calibration"
        assert prompt.startswith("Create a clean hand-drawn 2D editorial illustration.")
        assert prompt.count(body) == 1
        assert "balanced full-length contrapposto pose" in prompt
        assert "eye-level head-to-toe framing" in prompt
        assert "generous negative space around the complete silhouette" in prompt
        assert "both hands and both feet clearly visible" in prompt
        assert "Render distinct visible cues" in prompt
        assert "flat decorative outer border behind the figure" in prompt
        assert "exactly one complete adult figure" in prompt

    matrix = tmp_path / "tests/prompt_matrix/editorial_calibration.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == EDITORIAL_CALIBRATION_PROFILE
    assert binding["benchmark_stage"] == "calibration"

    with pytest.raises(ValueError, match="editorial calibration profile requires seeds"):
        signature_rows(
            catalog,
            seeds=(9101, 9202, 9999),
            benchmark_profile=EDITORIAL_CALIBRATION_PROFILE,
            limit_signatures=5,
            require_candidate_count=6,
        )


def test_axis_calibration_translates_feature_tokens_into_visible_directions(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {f"artist_axis_{index}": "generated" for index in range(1, 7)},
    )
    supported_axes = {
        "line_language": ["dry_broken"],
        "face_design": ["angular_planar"],
        "eye_design": ["layered_large"],
        "body_design": ["broad_athletic"],
        "palette_language": ["sunlit_earth"],
        "light_modeling": ["luminous_glaze"],
        "framing_language": ["spacious_asymmetric"],
        "ornament_language": ["geometric_inset"],
    }
    for item in items.values():
        item["feature_axes"] = supported_axes
        item["visual_axes"] = list(supported_axes)
    catalog.write_text(
        yaml.safe_dump({"items": items}, sort_keys=False),
        encoding="utf-8",
    )
    rows = signature_rows(
        catalog,
        seeds=AXIS_CALIBRATION_SEEDS,
        benchmark_profile=AXIS_CALIBRATION_PROFILE,
        limit_signatures=5,
        require_candidate_count=6,
        require_signature_count=5,
    )

    assert len(rows) == 15
    assert {row["seed"] for row in rows} == set(AXIS_CALIBRATION_SEEDS)
    for row in rows:
        prompt = row["prompt"]
        assert row["factors"]["benchmark_profile"] == AXIS_CALIBRATION_PROFILE
        assert row["factors"]["benchmark_stage"] == "calibration"
        assert "clearly broken dry-brush contour segments" in prompt
        assert "a firm jaw and planar cheeks" in prompt
        assert "large layered irises and paired catchlights" in prompt
        assert "broad shoulders and athletic stable limbs" in prompt
        assert "clay, sand, olive, cream, and warm brown fields" in prompt
        assert "translucent highlights and open reflected shadows" in prompt
        assert "an off-center figure with broad open side space" in prompt
        assert "bold repeated geometric panels" in prompt
        assert "Put the ornament on both the garment and outer border" in prompt
        assert "eye-level head-to-toe framing" in prompt

    matrix = tmp_path / "tests/prompt_matrix/axis_calibration.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == AXIS_CALIBRATION_PROFILE
    assert binding["benchmark_stage"] == "calibration"

    with pytest.raises(ValueError, match="unsupported feature axis line_language"):
        items["artist_axis_1"]["feature_axes"]["line_language"] = ["unknown_line"]
        catalog.write_text(
            yaml.safe_dump({"items": items}, sort_keys=False),
            encoding="utf-8",
        )
        signature_rows(
            catalog,
            seeds=AXIS_CALIBRATION_SEEDS,
            benchmark_profile=AXIS_CALIBRATION_PROFILE,
            limit_signatures=5,
            require_candidate_count=6,
        )


def test_reinforced_axis_calibration_changes_only_failed_visual_cues(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {f"artist_reinforced_{index}": "generated" for index in range(1, 7)},
    )
    supported_axes = {
        "line_language": ["dry_broken"],
        "face_design": ["angular_planar"],
        "eye_design": ["layered_large"],
        "body_design": ["broad_athletic"],
        "palette_language": ["sunlit_earth"],
        "light_modeling": ["luminous_glaze"],
        "framing_language": ["layered_intimate"],
        "ornament_language": ["geometric_inset"],
    }
    for item in items.values():
        item["feature_axes"] = supported_axes
        item["visual_axes"] = list(supported_axes)
    catalog.write_text(
        yaml.safe_dump({"items": items}, sort_keys=False),
        encoding="utf-8",
    )
    rows = signature_rows(
        catalog,
        seeds=REINFORCED_AXIS_CALIBRATION_SEEDS,
        benchmark_profile=REINFORCED_AXIS_CALIBRATION_PROFILE,
        limit_signatures=5,
        require_candidate_count=6,
        require_signature_count=5,
    )

    assert len(rows) == 15
    assert {row["seed"] for row in rows} == set(
        REINFORCED_AXIS_CALIBRATION_SEEDS
    )
    for row in rows:
        prompt = row["prompt"]
        assert (
            row["factors"]["benchmark_profile"]
            == REINFORCED_AXIS_CALIBRATION_PROFILE
        )
        assert "bold broken dry-brush contours with visible gaps" in prompt
        assert "strong translucent colored glaze, reflected color" in prompt
        assert "many large overlapping paper panels clearly visible" in prompt
        assert "a firm jaw and planar cheeks" in prompt
        assert "large layered irises and paired catchlights" in prompt
        assert "bold repeated geometric panels" in prompt
        assert "balanced full-length contrapposto pose" in prompt

    matrix = tmp_path / "tests/prompt_matrix/reinforced_axis_calibration.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == REINFORCED_AXIS_CALIBRATION_PROFILE
    assert binding["benchmark_stage"] == "calibration"


def test_reinforced_axis_full_repair_is_exact_and_uses_distinct_pilot_seeds(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {f"artist_full_repair_{index}": "generated" for index in range(1, 3)},
    )
    supported_axes = {
        "line_language": ["dry_broken"],
        "face_design": ["angular_planar"],
        "eye_design": ["layered_large"],
        "body_design": ["broad_athletic"],
        "palette_language": ["sunlit_earth"],
        "light_modeling": ["luminous_glaze"],
        "framing_language": ["layered_intimate"],
        "ornament_language": ["geometric_inset"],
    }
    for item in items.values():
        item["feature_axes"] = supported_axes
        item["visual_axes"] = list(supported_axes)
    catalog.write_text(
        yaml.safe_dump({"items": items}, sort_keys=False),
        encoding="utf-8",
    )
    rows = signature_rows(
        catalog,
        seeds=REINFORCED_AXIS_REPAIR_SEEDS,
        benchmark_profile=REINFORCED_AXIS_REPAIR_PROFILE,
        require_signature_count=2,
    )

    assert len(rows) == 6
    assert {row["seed"] for row in rows} == set(REINFORCED_AXIS_REPAIR_SEEDS)
    for row in rows:
        assert row["factors"]["benchmark_profile"] == REINFORCED_AXIS_REPAIR_PROFILE
        assert row["factors"]["benchmark_stage"] == "pilot"
        assert "balanced full-length contrapposto pose" in row["prompt"]
        assert "bold broken dry-brush contours with visible gaps" in row["prompt"]

    matrix = tmp_path / "tests/prompt_matrix/full_repair.jsonl"
    write_immutable_jsonl(matrix, rows)
    binding = build_binding(matrix, catalog, root=tmp_path)
    assert binding["benchmark_profile"] == REINFORCED_AXIS_REPAIR_PROFILE
    assert binding["benchmark_stage"] == "pilot"

    with pytest.raises(ValueError, match="reinforced axis repair profile requires seeds"):
        signature_rows(
            catalog,
            seeds=REINFORCED_AXIS_CALIBRATION_SEEDS,
            benchmark_profile=REINFORCED_AXIS_REPAIR_PROFILE,
            require_signature_count=2,
        )


def test_repair_accumulation_preserves_failures_and_enforces_total_gate(
    tmp_path: Path,
) -> None:
    catalog, items = write_catalog(
        tmp_path,
        {
            "artist_existing_one": "testing",
            "artist_existing_two": "testing",
            "artist_repair_one": "generated",
            "artist_repair_two": "generated",
        },
    )
    binding, _ = create_binding(
        tmp_path,
        catalog,
        "repair",
        profile=REPAIR_BENCHMARK_PROFILE,
        count=2,
    )
    source = tmp_path / "tests/reports/repair/raw_summary.json"
    write_summary(
        source,
        [
            summary_style("artist_repair_one", items["artist_repair_one"], "testing"),
            summary_style("artist_repair_two", items["artist_repair_two"], "rejected"),
        ],
    )

    document = build_accumulation_summary(
        source,
        binding,
        catalog,
        root=tmp_path,
        expected_existing_testing=2,
        expected_repair_candidates=2,
        minimum_cumulative_testing=3,
    )
    assert document["repair_accumulation"]["cumulative_testing_after_apply"] == 3
    assert document["repair_accumulation"]["retest_gate_satisfied"] is True
    assert {
        item["style_id"]: item["recommended_status"] for item in document["styles"]
    } == {
        "artist_repair_one": "testing",
        "artist_repair_two": "generated",
    }

    write_summary(
        source,
        [
            summary_style("artist_repair_one", items["artist_repair_one"], "rejected"),
            summary_style("artist_repair_two", items["artist_repair_two"], "rejected"),
        ],
    )
    deferred = build_accumulation_summary(
        source,
        binding,
        catalog,
        root=tmp_path,
        expected_existing_testing=2,
        expected_repair_candidates=2,
        minimum_cumulative_testing=3,
    )
    assert deferred["repair_accumulation"]["cumulative_testing_after_apply"] == 2
    assert deferred["repair_accumulation"]["retest_gate_satisfied"] is False
    assert {
        item["style_id"]: item["recommended_status"]
        for item in deferred["styles"]
    } == {
        "artist_repair_one": "generated",
        "artist_repair_two": "generated",
    }

    with pytest.raises(ValueError, match="cumulative testing styles"):
        build_accumulation_summary(
            source,
            binding,
            catalog,
            root=tmp_path,
            expected_existing_testing=2,
            expected_repair_candidates=2,
            minimum_cumulative_testing=3,
            require_retest_ready=True,
        )


SCORE_FIELDS = [
    "test_id",
    "style_id",
    "seed",
    "factors_json",
    "image_path",
    *METRICS,
    "critical_failure",
]


def score_rows(matrix_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "test_id": str(row["test_id"]),
            "style_id": str(row["style_id"]),
            "seed": str(row["seed"]),
            "factors_json": json.dumps(row["factors"], sort_keys=True),
            "image_path": f"runs/{row['test_id']}/output.png",
            **{metric: "4" for metric in METRICS},
            "critical_failure": "false",
        }
        for row in matrix_rows
    ]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pilot_fixture(
    tmp_path: Path,
    *,
    repair_profile: str = REPAIR_BENCHMARK_PROFILE,
) -> tuple[Path, Path, Path, Path, Path]:
    catalog, items = write_catalog(
        tmp_path, {"artist_legacy": "generated", "artist_repair": "generated"}
    )
    if repair_profile == REINFORCED_AXIS_REPAIR_PROFILE:
        supported_axes = {
            "line_language": ["dry_broken"],
            "face_design": ["angular_planar"],
            "eye_design": ["layered_large"],
            "body_design": ["broad_athletic"],
            "palette_language": ["sunlit_earth"],
            "light_modeling": ["luminous_glaze"],
            "framing_language": ["layered_intimate"],
            "ornament_language": ["geometric_inset"],
        }
        items["artist_repair"]["feature_axes"] = supported_axes
        items["artist_repair"]["visual_axes"] = list(supported_axes)
        catalog.write_text(
            yaml.safe_dump({"items": items}, sort_keys=False),
            encoding="utf-8",
        )
    legacy_binding, legacy_matrix = create_binding(
        tmp_path, catalog, "legacy", count=2
    )
    lifecycle = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    lifecycle["items"]["artist_legacy"]["validation"]["status"] = "testing"
    catalog.write_text(yaml.safe_dump(lifecycle, sort_keys=False), encoding="utf-8")
    repair_binding, repair_matrix = create_binding(
        tmp_path,
        catalog,
        "repair",
        profile=repair_profile,
        count=1,
    )
    lifecycle["items"]["artist_repair"]["validation"]["status"] = "testing"
    catalog.write_text(yaml.safe_dump(lifecycle, sort_keys=False), encoding="utf-8")
    legacy_scored = tmp_path / "tests/reports/legacy/scored.csv"
    repair_scored = tmp_path / "tests/reports/repair/scored.csv"
    write_csv(legacy_scored, score_rows(legacy_matrix))
    write_csv(repair_scored, score_rows(repair_matrix))
    return catalog, legacy_binding, repair_binding, legacy_scored, repair_scored


def test_testing_pilot_prefers_repair_scores_and_validates_exact_five_seeds(
    tmp_path: Path,
) -> None:
    catalog, legacy_binding, repair_binding, legacy_scored, repair_scored = (
        pilot_fixture(tmp_path)
    )
    fields, pilot, current = build_pilot_rows(
        legacy_scored,
        repair_scored,
        legacy_binding,
        repair_binding,
        catalog,
        root=tmp_path,
        minimum_testing_count=2,
    )
    by_style = {
        style_id: {int(row["seed"]) for row in pilot if row["style_id"] == style_id}
        for style_id in current
    }
    assert by_style == {
        "artist_legacy": {1001, 2002, 3003},
        "artist_repair": set(REPAIR_SEEDS),
    }

    pilot_path = tmp_path / "tests/reports/combined/pilot_scorecard.csv"
    write_csv(pilot_path, pilot)
    extension_matrix_rows = retest_rows(pilot_path, catalog)
    extension_matrix = tmp_path / "tests/prompt_matrix/retest.jsonl"
    write_immutable_jsonl(extension_matrix, extension_matrix_rows)
    extension = score_rows(extension_matrix_rows)
    extension_path = tmp_path / "tests/reports/retest/scorecard.csv"
    write_csv(extension_path, extension)
    combined = validate_extension_rows(
        extension_path,
        fields,
        current,
        pilot,
        matrix_path=extension_matrix,
    )
    assert len(combined) == 10
    assert all(
        len({int(row["seed"]) for row in combined if row["style_id"] == style_id})
        == 5
        for style_id in current
    )


def test_testing_pilot_supports_reinforced_axis_repair_profile(
    tmp_path: Path,
) -> None:
    catalog, legacy_binding, repair_binding, legacy_scored, repair_scored = (
        pilot_fixture(
            tmp_path,
            repair_profile=REINFORCED_AXIS_REPAIR_PROFILE,
        )
    )
    fields, pilot, current = build_pilot_rows(
        legacy_scored,
        repair_scored,
        legacy_binding,
        repair_binding,
        catalog,
        root=tmp_path,
        minimum_testing_count=2,
    )
    repair_pilot = [
        row for row in pilot if row["style_id"] == "artist_repair"
    ]
    assert {int(row["seed"]) for row in repair_pilot} == set(
        REINFORCED_AXIS_REPAIR_SEEDS
    )
    assert {
        json.loads(row["factors_json"])["benchmark_profile"]
        for row in repair_pilot
    } == {REINFORCED_AXIS_REPAIR_PROFILE}

    pilot_path = tmp_path / "tests/reports/combined/pilot_scorecard.csv"
    write_csv(pilot_path, pilot)
    extension_matrix_rows = retest_rows(pilot_path, catalog)
    repair_extension = [
        row
        for row in extension_matrix_rows
        if row["style_id"] == "artist_repair"
    ]
    assert {row["seed"] for row in repair_extension} == {4004, 5005}
    assert {
        (
            row["factors"]["benchmark_profile"],
            row["factors"]["benchmark_stage"],
        )
        for row in repair_extension
    } == {(REINFORCED_AXIS_REPAIR_PROFILE, "extension")}

    extension_matrix = tmp_path / "tests/prompt_matrix/retest.jsonl"
    write_immutable_jsonl(extension_matrix, extension_matrix_rows)
    extension_path = tmp_path / "tests/reports/retest/scorecard.csv"
    write_csv(extension_path, score_rows(extension_matrix_rows))
    combined = validate_extension_rows(
        extension_path,
        fields,
        current,
        pilot,
        matrix_path=extension_matrix,
    )
    assert len(combined) == 10


def test_testing_pilot_and_extension_fail_closed_on_drift_or_profile_mismatch(
    tmp_path: Path,
) -> None:
    catalog, legacy_binding, repair_binding, legacy_scored, repair_scored = (
        pilot_fixture(tmp_path)
    )
    repair_rows = list(csv.DictReader(repair_scored.open(encoding="utf-8")))
    repair_rows[0]["factors_json"] = json.dumps(
        {
            **json.loads(repair_rows[0]["factors_json"]),
            "evaluated_prompt_sha256": "sha256_" + "0" * 64,
        }
    )
    write_csv(repair_scored, repair_rows)
    with pytest.raises(ValueError, match="factors do not match bound matrix"):
        build_pilot_rows(
            legacy_scored,
            repair_scored,
            legacy_binding,
            repair_binding,
            catalog,
            root=tmp_path,
            minimum_testing_count=2,
        )

    _, _, _, legacy_scored, repair_scored = pilot_fixture(tmp_path / "fresh")
    fresh = tmp_path / "fresh"
    fresh_catalog = fresh / "catalog/artists.yaml"
    fields, pilot, current = build_pilot_rows(
        legacy_scored,
        repair_scored,
        fresh / "tests/reports/legacy/prompt_binding.json",
        fresh / "tests/reports/repair/prompt_binding.json",
        fresh_catalog,
        root=fresh,
        minimum_testing_count=2,
    )
    pilot_path = fresh / "tests/reports/combined/pilot_scorecard.csv"
    write_csv(pilot_path, pilot)
    extension = score_rows(retest_rows(pilot_path, fresh_catalog))
    repair_extension = next(
        row for row in extension if row["style_id"] == "artist_repair"
    )
    payload = json.loads(repair_extension["factors_json"])
    del payload["benchmark_profile"]
    repair_extension["factors_json"] = json.dumps(payload)
    extension_path = fresh / "tests/reports/retest/scorecard.csv"
    write_csv(extension_path, extension)
    with pytest.raises(ValueError, match="pilot/extension profile mismatch"):
        validate_extension_rows(extension_path, fields, current, pilot)


def test_testing_pilot_rejects_missing_rows_and_current_status_set_drift(
    tmp_path: Path,
) -> None:
    catalog, legacy_binding, repair_binding, legacy_scored, repair_scored = (
        pilot_fixture(tmp_path)
    )
    repair_rows = list(csv.DictReader(repair_scored.open(encoding="utf-8")))
    write_csv(repair_scored, repair_rows[:-1])
    with pytest.raises(ValueError, match="does not contain exact seeds"):
        build_pilot_rows(
            legacy_scored,
            repair_scored,
            legacy_binding,
            repair_binding,
            catalog,
            root=tmp_path,
            minimum_testing_count=2,
        )

    catalog_document = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    catalog_document["items"]["artist_repair"]["validation"]["status"] = "generated"
    catalog.write_text(
        yaml.safe_dump(catalog_document, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="at least 2 testing styles"):
        build_pilot_rows(
            legacy_scored,
            repair_scored,
            legacy_binding,
            repair_binding,
            catalog,
            root=tmp_path,
            minimum_testing_count=2,
        )


def test_five_seed_combiner_rejects_duplicate_or_missing_extension_seed(
    tmp_path: Path,
) -> None:
    catalog, legacy_binding, repair_binding, legacy_scored, repair_scored = (
        pilot_fixture(tmp_path)
    )
    fields, pilot, current = build_pilot_rows(
        legacy_scored,
        repair_scored,
        legacy_binding,
        repair_binding,
        catalog,
        root=tmp_path,
        minimum_testing_count=2,
    )
    pilot_path = tmp_path / "tests/reports/combined/pilot_scorecard.csv"
    write_csv(pilot_path, pilot)
    extension = score_rows(retest_rows(pilot_path, catalog))
    extension[-1]["seed"] = extension[-2]["seed"]
    extension_path = tmp_path / "tests/reports/retest/scorecard.csv"
    write_csv(extension_path, extension)

    with pytest.raises(ValueError, match="duplicate style and seed"):
        validate_extension_rows(extension_path, fields, current, pilot)


@pytest.mark.parametrize(
    ("style_id", "mutation", "message"),
    (
        ("artist_legacy", "seed", "exact profile seeds"),
        ("artist_repair", "seed", "exact profile seeds"),
        ("artist_repair", "stage", "invalid benchmark stage"),
        ("artist_repair", "digest", "stale prompt digest"),
        ("artist_repair", "missing_digest", "missing its prompt digest"),
    ),
)
def test_retest_exporter_revalidates_canonical_pilot_evidence(
    tmp_path: Path,
    style_id: str,
    mutation: str,
    message: str,
) -> None:
    catalog, legacy_binding, repair_binding, legacy_scored, repair_scored = (
        pilot_fixture(tmp_path)
    )
    _, pilot, _ = build_pilot_rows(
        legacy_scored,
        repair_scored,
        legacy_binding,
        repair_binding,
        catalog,
        root=tmp_path,
        minimum_testing_count=2,
    )
    target = next(row for row in pilot if row["style_id"] == style_id)
    if mutation == "seed":
        target["seed"] = "7777"
    else:
        payload = json.loads(target["factors_json"])
        if mutation == "stage":
            payload["benchmark_stage"] = "extension"
        elif mutation == "digest":
            payload["evaluated_prompt_sha256"] = "sha256_" + "0" * 64
        else:
            del payload["evaluated_prompt_sha256"]
        target["factors_json"] = json.dumps(payload, sort_keys=True)
    pilot_path = tmp_path / "tests/reports/combined/pilot_scorecard.csv"
    write_csv(pilot_path, pilot)

    with pytest.raises(ValueError, match=message):
        retest_rows(pilot_path, catalog)
