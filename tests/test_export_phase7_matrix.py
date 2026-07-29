from __future__ import annotations

import json
from pathlib import Path

import pytest

from common import canonical_prompt_sha256, load_yaml
from export_phase6_matrix import (
    CAMERA_SUBJECT_CONTRACT,
    PHASE6_PROFILE_FACTOR,
    PHASE6_PROFILE_SHA256,
    SUBJECT_CONTRACT,
    _prompt,
    _prompt_body,
    single_axis_prompt,
)
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
    binding_document,
    camera_prompt,
    mass_axis_rows,
    payload_sha256,
    prompt_binding,
    select_axis_items,
    verify_binding,
    wants_profile_contract,
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


def phase6_prompts(axis: str | None = None) -> dict[str, str]:
    prompts: dict[str, str] = {}
    for line in PHASE6_SINGLE_AXIS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if axis is not None and row["factors"]["axis"] != axis:
            continue
        prompts[row["factors"]["item_id"]] = row["prompt"]
    return prompts


def test_axis_coverage_matches_the_planned_counts() -> None:
    """Axis population is the stable invariant, not the generated subset.

    Promoting an axis empties its generated set, so counting only generated
    items would break every time an axis lands.
    """
    assert set(PHASE7_AXIS_CATALOGS) == set(EXPECTED_ITEM_COUNTS)
    for axis, expected in EXPECTED_ITEM_COUNTS.items():
        assert len(select_axis_items(axis)) == expected, axis


def test_promoted_axes_have_no_generated_items_left() -> None:
    """A promoted axis must be fully decided: nothing left in generated."""
    promoted = {"lighting", "background", "character_design", "pose"}
    for axis in promoted:
        with pytest.raises(ValueError, match="no matching items"):
            select_axis_items(axis, statuses={"generated"})
        decided = select_axis_items(axis, statuses={"approved", "rejected"})
        assert len(decided) == EXPECTED_ITEM_COUNTS[axis], axis

    for axis in set(PHASE7_AXIS_CATALOGS) - promoted:
        pending = select_axis_items(axis, statuses={"generated"})
        assert len(pending) == EXPECTED_ITEM_COUNTS[axis], axis


def test_proven_axis_prompts_are_identical_to_phase6() -> None:
    """A promotion run must submit the prompt the coverage gate already passed.

    camera is excluded: its profile contract was repaired, so it now carries the
    Phase 7 digest and is covered by the camera-specific tests below.
    """
    expected = {
        item_id: prompt
        for item_id, prompt in phase6_prompts().items()
        if not item_id.startswith("camera_")
    }
    assert len(expected) == 80

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


def test_camera_non_profile_prompts_still_match_phase6() -> None:
    """The repair must not disturb the 208 items Phase 6 rendered correctly."""
    expected = phase6_prompts("camera")
    assert len(expected) == 16
    rendered = {row["style_id"]: row["prompt"] for row in mass_axis_rows("camera")}
    matched = 0
    for item_id, prompt in expected.items():
        if "clean_profile" in item_id:
            assert rendered[item_id] != prompt, item_id
        else:
            assert rendered[item_id] == prompt, item_id
            matched += 1
    assert matched == 11


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


def test_camera_profile_items_get_the_profile_contract() -> None:
    """Phase 6 looked for a literal that no catalog body contains.

    The guard searched for "clean profile" while bodies read "clean side camera
    position ... preserves the facial profile", so all 42 profile items were told
    to keep both eyes readable and rendered frontal. See plan.md 7.5.
    """
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["camera"])["items"]
    profile_ids = {item_id for item_id in catalog if "clean_profile" in item_id}
    assert len(profile_ids) == 42

    # Detection must match the ids exactly: no misses and no over-triggering.
    detected = {
        item_id
        for item_id, item in select_axis_items("camera")
        if wants_profile_contract(_prompt_body(_prompt(item_id, item)))
    }
    assert detected == profile_ids

    rows = mass_axis_rows("camera")
    for row in rows:
        is_profile = row["style_id"] in profile_ids
        assert row["prompt"].startswith(
            CAMERA_SUBJECT_CONTRACT if is_profile else SUBJECT_CONTRACT
        ), row["style_id"]
        if is_profile:
            assert "both eyes clearly readable" not in row["prompt"]

    # The old literal never appears, which is why the Phase 6 guard was dead.
    assert not any(
        "clean profile" in _prompt(item_id, item).lower()
        for item_id, item in select_axis_items("camera")
    )


def test_camera_moved_off_the_phase6_profile_digest() -> None:
    assert "camera" not in PROVEN_AXES
    assert axis_profile_factor("camera") == PHASE7_PROFILE_FACTOR


def test_the_camera_repair_only_changes_profile_items() -> None:
    """Non-profile camera prompts must stay byte-identical to Phase 6."""
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["camera"])["items"]
    profile_ids = {item_id for item_id in catalog if "clean_profile" in item_id}
    changed = 0
    for item_id, item in select_axis_items("camera"):
        body = _prompt_body(_prompt(item_id, item))
        repaired = camera_prompt(body)
        phase6 = single_axis_prompt("camera", body)
        if item_id in profile_ids:
            assert repaired != phase6, item_id
            changed += 1
        else:
            assert repaired == phase6, item_id
    assert changed == 42


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


def test_binding_document_verifies_and_detects_tampering(tmp_path: Path) -> None:
    rows = mass_axis_rows("media_rendering")
    document = binding_document("media_rendering", rows)
    assert document["artifact_type"] == "phase7_axis_prompt_binding"
    assert document["style_count"] == EXPECTED_ITEM_COUNTS["media_rendering"]
    assert document["row_count"] == len(rows)
    assert document["seeds"] == sorted(DEFAULT_SEEDS)

    path = tmp_path / "binding.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert verify_binding(path) == document

    # A naive edit breaks the recorded payload digest.
    tampered = json.loads(json.dumps(document))
    tampered["styles"][sorted(tampered["styles"])[0]] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="payload digest is stale"):
        verify_binding(path)

    # Recomputing the digest still fails, because the binding is re-derived.
    tampered["binding_sha256"] = payload_sha256(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches"):
        verify_binding(path)


def test_binding_rejects_foreign_artifacts(tmp_path: Path) -> None:
    """The artist binding artifact must not be accepted as a Phase 7 binding."""
    path = tmp_path / "binding.json"
    document = {
        "schema_version": 1,
        "artifact_type": "artist_prompt_evidence_binding",
        "styles": {},
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid schema metadata"):
        verify_binding(path)


def test_unsupported_axis_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported axis"):
        mass_axis_rows("artist_signature")
    with pytest.raises(ValueError, match="unsupported axis"):
        axis_profile_factor("artist_signature")
