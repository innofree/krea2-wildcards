from __future__ import annotations

import json
from pathlib import Path

import pytest

from common import canonical_prompt_sha256, load_yaml
from export_phase6_matrix import PHASE6_PROFILE_FACTOR, PHASE6_PROFILE_SHA256
from export_phase7_matrix import (
    COMPLETE_SCENE_AXES,
    COMPLETE_SCENE_SEEDS,
    DEFAULT_SEEDS,
    PHASE7_AXIS_ANCHORS,
    PHASE7_AXIS_CATALOGS,
    PHASE7_PROFILE_FACTOR,
    PROVEN_AXES,
    axis_profile_factor,
    axis_seeds,
    mass_axis_rows,
    prompt_binding,
    select_axis_items,
)


ROOT = Path(__file__).resolve().parents[1]
PROMPT_MATRIX = ROOT / "tests" / "prompt_matrix"
PHASE6_SINGLE_AXIS = PROMPT_MATRIX / "phase6_single_axis.jsonl"
PHASE6_PRESETS = PROMPT_MATRIX / "phase6_presets.jsonl"
EVALUATION = ROOT / "catalog" / "evaluation.yaml"
EXPECTED_ITEM_COUNTS = {
    "background": 400,
    "camera": 250,
    "character_design": 400,
    "effect": 200,
    "fashion": 500,
    "hair_design": 250,
    "lighting": 250,
    "linework_coloring": 300,
    "media_rendering": 150,
    "pose": 326,
    "preset": 200,
}


def phase6_prompts() -> dict[str, str]:
    prompts: dict[str, str] = {}
    for line in PHASE6_SINGLE_AXIS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prompts[row["factors"]["item_id"]] = row["prompt"]
    return prompts


def test_axis_coverage_matches_the_planned_counts() -> None:
    assert set(PHASE7_AXIS_CATALOGS) == set(EXPECTED_ITEM_COUNTS)
    for axis, expected in EXPECTED_ITEM_COUNTS.items():
        assert len(select_axis_items(axis, statuses={"generated"})) == expected, axis


def test_proven_axis_prompts_are_identical_to_phase6() -> None:
    """A promotion run must submit the prompt the coverage gate already passed."""
    expected = phase6_prompts()
    compared = 0
    for axis in PROVEN_AXES:
        rendered = {
            row["style_id"]: row["prompt"] for row in mass_axis_rows(axis)
        }
        for item_id, prompt in expected.items():
            if item_id not in rendered:
                continue
            compared += 1
            assert rendered[item_id] == prompt, (axis, item_id)
    assert compared == len(expected)


def test_preset_prompts_are_identical_to_the_phase6_conflict_audit() -> None:
    expected: dict[str, str] = {}
    for line in PHASE6_PRESETS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        expected[row["factors"]["preset"]] = row["prompt"]
    assert len(expected) == 100

    rendered = {row["style_id"]: row["prompt"] for row in mass_axis_rows("preset")}
    assert set(expected) <= set(rendered)
    for preset_id, prompt in expected.items():
        assert rendered[preset_id] == prompt, preset_id


def test_presets_stay_on_the_complete_scene_five_seed_bar() -> None:
    """A preset is a full scene contract, so it must not drop to the 3-seed bar."""
    policy = load_yaml(EVALUATION)["approval_policy"]
    assert "preset" in policy["complete_scene_families"]
    assert COMPLETE_SCENE_AXES == ("preset",)
    assert len(COMPLETE_SCENE_SEEDS) == policy["complete_scene_approval_seeds"] == 5
    assert axis_seeds("preset") == COMPLETE_SCENE_SEEDS

    rows = mass_axis_rows("preset")
    assert len({row["seed"] for row in rows}) == 5
    assert len(rows) == EXPECTED_ITEM_COUNTS["preset"] * 5


def test_atomic_axes_default_to_the_three_seed_bar() -> None:
    policy = load_yaml(EVALUATION)["approval_policy"]
    assert len(DEFAULT_SEEDS) == policy["minimum_approval_seeds"] == 3
    for axis in PHASE7_AXIS_CATALOGS:
        if axis in COMPLETE_SCENE_AXES:
            continue
        assert axis_seeds(axis) == DEFAULT_SEEDS, axis


def test_proven_axes_keep_the_phase6_profile_digest() -> None:
    for axis in PROVEN_AXES:
        assert axis_profile_factor(axis) == PHASE6_PROFILE_FACTOR


def test_new_axes_carry_a_separate_phase7_digest() -> None:
    assert PHASE7_PROFILE_FACTOR != PHASE6_PROFILE_FACTOR
    assert PHASE7_PROFILE_FACTOR[7:] != PHASE6_PROFILE_SHA256
    for axis in PHASE7_AXIS_ANCHORS:
        assert axis not in PROVEN_AXES
        assert axis_profile_factor(axis) == PHASE7_PROFILE_FACTOR


def test_rows_are_keyed_by_catalog_item_id() -> None:
    """apply_evaluation_summary resolves items[style_id], so they must match."""
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["effect"])["items"]
    rows = mass_axis_rows("effect")
    for row in rows:
        assert row["style_id"] in catalog, row["style_id"]
        assert row["label"] == row["style_id"]
        assert row["factors"]["item_id"] == row["style_id"]


def test_rows_bind_each_item_to_its_own_prompt_digest() -> None:
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["hair_design"])["items"]
    rows = mass_axis_rows("hair_design")
    for row in rows:
        expected = canonical_prompt_sha256(catalog[row["style_id"]]["prompt"])
        assert row["factors"]["evaluated_prompt_sha256"] == f"sha256_{expected}"

    binding = prompt_binding("hair_design", rows)
    assert len(binding) == EXPECTED_ITEM_COUNTS["hair_design"]
    assert binding == {
        item_id: canonical_prompt_sha256(catalog[item_id]["prompt"])
        for item_id in binding
    }


def test_every_item_gets_every_seed_and_test_ids_are_unique() -> None:
    seeds = (11, 22, 33)
    rows = mass_axis_rows("media_rendering", seeds)
    items = {row["style_id"] for row in rows}
    assert len(rows) == len(items) * len(seeds)
    assert len({row["test_id"] for row in rows}) == len(rows)
    by_item: dict[str, set[int]] = {}
    for row in rows:
        by_item.setdefault(row["style_id"], set()).add(row["seed"])
    assert all(found == set(seeds) for found in by_item.values())


def test_unstable_pose_items_stay_excluded() -> None:
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["pose"])["items"]
    selected = {item_id for item_id, _ in select_axis_items("pose")}
    excluded = set(catalog) - selected
    assert len(excluded) == 24
    assert all("kneeling" in item_id for item_id in excluded)


def test_limit_supports_small_anchor_calibration_runs() -> None:
    rows = mass_axis_rows("fashion", (1001,), limit=2)
    assert len({row["style_id"] for row in rows}) == 2
    assert len(rows) == 2


def test_unsupported_axis_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported axis"):
        mass_axis_rows("artist_signature")
    with pytest.raises(ValueError, match="unsupported axis"):
        axis_profile_factor("artist_signature")
