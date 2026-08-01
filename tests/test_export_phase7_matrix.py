from __future__ import annotations

import json
from collections import Counter
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
    CAMERA_CROP_FRAMING_MARKERS,
    CAMERA_PROFILE_FRAMING_SUFFIX,
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
    camera_crop_framing_override,
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


def _axis_items(axis: str, statuses: set[str]) -> list[tuple[str, dict]]:
    """select_axis_items, but an empty selection is [] instead of a raise."""
    try:
        return select_axis_items(axis, statuses=statuses)
    except ValueError:
        return []


def test_promoted_axes_have_no_generated_items_left() -> None:
    """A promoted axis must be fully decided: nothing left in generated.

    Which axes count as promoted is read from the catalog rather than hardcoded,
    so a promotion and the subject fragmentation that sent all eleven axes back
    to generated both move the expectation instead of breaking the test.
    """
    for axis in sorted(PHASE7_AXIS_CATALOGS):
        counted = sum(
            len(_axis_items(axis, {status}))
            for status in ("generated", "testing", "approved", "rejected")
        )
        assert counted == EXPECTED_ITEM_COUNTS[axis], axis
        if _axis_items(axis, {"approved"}):
            assert not _axis_items(axis, {"generated"}), axis


def _phase6_preset_prompts() -> dict[str, str]:
    prompts: dict[str, str] = {}
    for line in PHASE6_PRESETS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prompts[row["factors"]["preset"]] = row["prompt"]
    return prompts


def test_phase6_prompt_corpus_survives_as_a_superseded_baseline() -> None:
    """The phase6 jsonl files record what Phase 6 actually submitted, so they stay.

    These files used to back an identity guard: a promotion run had to submit the
    exact prompt the coverage gate already passed. The subject fragmentation
    retired that guard rather than broke it. Every catalog prompt dropped its
    "An adult subject ..." opening, so no current rendering can match a recorded
    one, and re-exporting the baselines to make them match would destroy the
    record of what was tested.

    What keeps the retirement honest is the second half of this test: the guard
    only ever protected promotion runs, and nothing is promoted right now, so
    there is no run that could be submitting a stale prompt. Restoring the guard
    means recording a fresh baseline once a new coverage gate passes.
    """
    single_axis = phase6_prompts()
    non_camera = {k: v for k, v in single_axis.items() if not k.startswith("camera_")}
    assert len(non_camera) == 80
    assert len(phase6_prompts("camera")) == 16
    assert len(_phase6_preset_prompts()) == 100

    for axis in PROVEN_AXES:
        rendered = {row["style_id"]: row["prompt"] for row in mass_axis_rows(axis)}
        for item_id, prompt in non_camera.items():
            if item_id in rendered:
                assert rendered[item_id] != prompt, (axis, item_id)

    # The guard protected promotion runs, and a promotion has now happened
    # (linework_coloring v2), so "nothing is promoted" is no longer what makes the
    # retirement safe. This is the stronger invariant it gives way to: every
    # decided item's recorded evaluated_prompt_sha256 must still be the digest of
    # the prompt the catalog carries. That is the same property the phase6 corpus
    # was standing in for -- a verdict describing a prompt that no longer exists --
    # asserted directly against the catalog instead of against a frozen baseline,
    # so it holds for every future revalidation without needing a new corpus.
    for axis, catalog_path in sorted(PHASE7_AXIS_CATALOGS.items()):
        items = load_yaml(Path(catalog_path))["items"]
        for item_id, item in items.items():
            validation = item.get("validation") or {}
            if validation.get("status") not in {"approved", "rejected"}:
                continue
            recorded = validation.get("evaluated_prompt_sha256")
            assert recorded, (axis, item_id, "decided without a prompt digest")
            assert recorded == canonical_prompt_sha256(item["prompt"]), (
                axis,
                item_id,
                "verdict describes a prompt the catalog no longer carries",
            )


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


def test_the_camera_repair_only_changes_prompts_it_must() -> None:
    """Everything else must stay byte-identical to Phase 6.

    That's profile items (wrong subject contract) plus close_face /
    head_shoulders / vertical_full_scene items (no closing-lock branch, so
    they got the generic mid-thigh lock regardless of crop or profile status).
    94 items use one of those three crops and 42 want a profile view, with an
    8-item overlap (close_face + clean_profile), so 128 items must change.
    See plan.md 7.5.
    """
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["camera"])["items"]
    profile_ids = {item_id for item_id in catalog if "clean_profile" in item_id}
    broken_crop_ids = {
        item_id
        for item_id, item in catalog.items()
        if item["feature_axes"]["framing"][0]
        in {"close_face", "head_shoulders", "vertical_full_scene"}
    }
    assert len(broken_crop_ids) == 94
    expected_changed = profile_ids | broken_crop_ids
    assert len(expected_changed) == 128

    changed = 0
    for item_id, item in select_axis_items("camera"):
        body = _prompt_body(_prompt(item_id, item))
        repaired = camera_prompt(body)
        phase6 = single_axis_prompt("camera", body)
        if item_id in expected_changed:
            assert repaired != phase6, item_id
            changed += 1
        else:
            assert repaired == phase6, item_id
    assert changed == len(expected_changed)


def test_camera_unmapped_crops_get_their_own_closing_lock() -> None:
    """The three crops with no `_framing_contract` branch must no longer fall
    back to the generic mid-thigh lock, whatever their camera position."""
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["camera"])["items"]
    counted = Counter()
    for item_id, item in catalog.items():
        crop = item["feature_axes"]["framing"][0]
        if crop not in {"close_face", "head_shoulders", "vertical_full_scene"}:
            continue
        counted[crop] += 1
        body = _prompt_body(_prompt(item_id, item))
        rendered = camera_prompt(body)
        assert "eye-level mid-thigh inspection frame" not in rendered, item_id
        assert any(marker in rendered.lower() for marker in CAMERA_CROP_FRAMING_MARKERS)
    assert counted == Counter(
        {"close_face": 32, "head_shoulders": 31, "vertical_full_scene": 31}
    )


def test_camera_profile_closing_lock_no_longer_demands_two_eyes() -> None:
    """The 8 items combining a profile view with an unmapped crop used to get
    a closing lock demanding "both eyes", directly contradicting the profile
    subject contract's single visible eye. See plan.md 7.5.
    """
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["camera"])["items"]
    conflicted = [
        item_id
        for item_id, item in catalog.items()
        if item["feature_axes"]["framing"][0] == "close_face"
        and item["feature_axes"]["camera_position"][0] == "clean_profile"
    ]
    assert len(conflicted) == 8
    for item_id in conflicted:
        body = _prompt_body(_prompt(item_id, catalog[item_id]))
        rendered = camera_prompt(body)
        assert "both eyes" not in rendered, item_id


def test_camera_profile_items_end_with_the_view_reinforcement_suffix() -> None:
    """A 12-shot recalibration (plan.md 7.26) showed the crop fix plus an
    earlier reconciliation sentence held the profile view for close-face and
    thigh-up (6/6) but not chest-up (5/6 still rendered frontal): its closing
    lock never reasserts view direction, so the request decays by the end of
    the prompt. Every profile item must end with the reinforcement, whatever
    its crop -- a second 6-shot recalibration on the two failing chest-up
    items confirmed 6/6 held the profile after this landed.
    """
    catalog = load_yaml(ROOT / PHASE7_AXIS_CATALOGS["camera"])["items"]
    profile_ids = {item_id for item_id in catalog if "clean_profile" in item_id}
    for item_id, item in catalog.items():
        body = _prompt_body(_prompt(item_id, item))
        rendered = camera_prompt(body)
        if item_id in profile_ids:
            assert rendered.rstrip().endswith(CAMERA_PROFILE_FRAMING_SUFFIX), item_id
        else:
            assert CAMERA_PROFILE_FRAMING_SUFFIX not in rendered, item_id


def test_camera_crop_framing_override_is_none_for_mapped_crops() -> None:
    """The escape hatch must stay inert for the five crops Phase 6 already
    mapped correctly, whatever the profile flag."""
    for profile in (True, False):
        assert (
            camera_crop_framing_override(
                "Photograph an adult subject using chest-up framing.", profile=profile
            )
            is None
        )


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
