from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest
import yaml

from export_artist_visual_signature_matrix import reinforced_axis_visibility_ledger
from export_phase6_matrix import (
    CALIBRATION_SEEDS,
    CAMERA_STORYBOARD_BASELINE,
    PAIRWISE_SPECS,
    PHASE6_PROFILE_FACTOR,
    PROVEN_VISIBILITY_FINISH,
    _crop_aware_scene_body,
    _framing_contract,
    _lighting_axis_focus,
    _lighting_neutral_style_direction,
    _lighting_reconciliation,
    _opening_framing_contract,
    _random_utility_reconciliation,
    _signature_ledger_at_camera_scale,
    _storyboard_camera_body,
    benchmark_rows,
    calibration_rows,
    pairwise_rows,
    preset_rows,
    random_utility_rows,
    single_axis_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def _item(item_id: str, family: str, *, status: str = "generated") -> dict[str, object]:
    item: dict[str, object] = {
        "family": family,
        "prompt": f"Observable visual direction for {item_id}.",
        "validation": {"status": status},
    }
    if family == "artist_signature":
        item["feature_axes"] = {
            "line_language": ["crisp_measured"],
            "face_design": ["compact_oval"],
            "eye_design": ["almond_deep"],
            "body_design": ["compact_grounded"],
            "palette_language": ["deep_jewel"],
            "light_modeling": ["soft_two_step"],
            "framing_language": ["spacious_asymmetric"],
            "ornament_language": ["textile_echo"],
        }
    if family == "style_pack":
        item["feature_axes"] = {
            "shape_language": ["faceted_rhythmic"],
            "color_strategy": ["warm_cool_split"],
            "surface_character": ["chalk_matte"],
            "atmosphere": ["ceremonial_energy"],
            "edge_language": ["crisp_cut"],
        }
    return item


def _write_catalog(
    root: Path, name: str, family: str, count: int, *, status: str = "generated"
) -> None:
    items = {
        f"{family}_{index:03d}": _item(f"{family}_{index:03d}", family, status=status)
        for index in range(1, count + 1)
    }
    path = root / "catalog" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "items": items}, sort_keys=False),
        encoding="utf-8",
    )


def _phase6_catalogs(root: Path) -> None:
    _write_catalog(root, "style_expansion", "style_pack", 16, status="approved")
    _write_catalog(root, "art_styles", "style_pack", 0, status="approved")
    _write_catalog(root, "artists", "artist_signature", 24, status="approved")
    _write_catalog(root, "character_designs", "character_design", 16)
    _write_catalog(root, "poses", "pose", 16)
    _write_catalog(root, "lighting", "lighting", 16)
    _write_catalog(root, "backgrounds", "background", 16)
    _write_catalog(root, "linework_coloring", "linework_coloring", 16)
    _write_catalog(root, "cameras", "camera", 16)
    _write_catalog(root, "presets", "preset", 100)


def test_single_axis_matrix_covers_pairwise_rhs_catalog_items_at_three_seeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    monkeypatch.chdir(tmp_path)
    rows = single_axis_rows()
    assert len(rows) == 6 * 16 * 3
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    assert len({row["style_id"] for row in rows}) == 6 * 16
    assert Counter(row["factors"]["axis"] for row in rows) == {
        "character_design": 16 * 3,
        "pose": 16 * 3,
        "lighting": 16 * 3,
        "background": 16 * 3,
        "linework_coloring": 16 * 3,
        "camera": 16 * 3,
    }
    assert len({row["factors"]["item_id"] for row in rows}) == 6 * 16
    by_case: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_case[row["style_id"]].add(row["prompt"])
    assert all(len(prompts) == 1 for prompts in by_case.values())
    assert all(
        row["factors"]["prompt_profile_sha256"] == PHASE6_PROFILE_FACTOR for row in rows
    )
    assert all("Preserve realistic skin texture" not in row["prompt"] for row in rows)


def test_pairwise_matrix_covers_six_types_with_sixteen_cases_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    monkeypatch.chdir(tmp_path)
    rows = pairwise_rows()
    assert len(rows) == 6 * 16 * 3
    assert len({row["style_id"] for row in rows}) == 96
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    counts = Counter(row["factors"]["pair_type"] for row in rows)
    assert counts == {spec[0]: 16 * 3 for spec in PAIRWISE_SPECS}
    assert all(
        row["factors"]["prompt_profile_sha256"] == PHASE6_PROFILE_FACTOR for row in rows
    )


def test_preset_random_and_benchmark_matrices_are_bounded_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    monkeypatch.chdir(tmp_path)

    presets = preset_rows()
    assert len(presets) == 100 * 3
    assert len({row["style_id"] for row in presets}) == 100

    random_a = random_utility_rows()
    random_b = random_utility_rows()
    assert random_a == random_b
    assert len(random_a) == 20 * 3
    assert len({row["style_id"] for row in random_a}) == 20

    benchmark = benchmark_rows()
    assert len(benchmark) == 5
    assert {row["seed"] for row in benchmark} == {1001, 2002, 3003, 4004, 5005}
    assert {row["mode"] for row in benchmark} == {"krea2_turbo_benchmark"}


def test_pairwise_refuses_unapproved_artist_signatures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    artists = tmp_path / "catalog/artists.yaml"
    document = yaml.safe_load(artists.read_text(encoding="utf-8"))
    for item in document["items"].values():
        item["validation"]["status"] = "testing"
    artists.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="need 16 artist_signature"):
        pairwise_rows()


def test_rows_are_json_serializable_without_connection_fields() -> None:
    encoded = json.dumps(single_axis_rows(cases_per_axis=1))
    assert "api_url" not in encoded
    assert "remote" not in encoded


def test_calibration_covers_every_phase6_prompt_path_with_69_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    monkeypatch.chdir(tmp_path)

    rows = calibration_rows()

    assert len(rows) == 69
    assert len({row["test_id"] for row in rows}) == 69
    assert len({(row["style_id"], row["mode"]) for row in rows}) == 23
    assert CALIBRATION_SEEDS == (91001, 92002, 93003)
    assert {row["seed"] for row in rows} == {91001, 92002, 93003}
    assert {row["mode"] for row in rows} == {
        "single_axis",
        "pairwise",
        "preset_audit",
        "random_utility",
        "krea2_turbo_benchmark",
    }
    assert {row["factors"]["prompt_profile_sha256"] for row in rows} == {
        PHASE6_PROFILE_FACTOR
    }
    assert all("exactly one" in row["prompt"] for row in rows)
    assert all("Preserve realistic skin texture" not in row["prompt"] for row in rows)

    by_style = {row["style_id"]: row["prompt"] for row in rows}
    assert PROVEN_VISIBILITY_FINISH in by_style["single_axis_lighting_001"]
    pose = by_style["pairwise_style_pack_pose_001"]
    assert PROVEN_VISIBILITY_FINISH in pose
    assert "both supporting legs, and both feet visible" in pose
    assert "Final camera lock—frame literally" in pose
    assert "mid-thigh inspection" not in pose
    assert PROVEN_VISIBILITY_FINISH in by_style["krea2_turbo_benchmark"]

    single_camera = by_style["single_axis_camera_001"]
    assert CAMERA_STORYBOARD_BASELINE in single_camera
    assert "final composition blueprint" in single_camera
    assert "Photograph an adult subject" not in single_camera
    assert "small neutral-grey rectangular storyboard block" not in single_camera

    camera = by_style["pairwise_artist_signature_camera_composition_001"]
    assert "these eight cues" in camera
    assert "framing language—" in camera
    assert "full-length figure" not in camera
    assert "complete figure" not in camera
    assert "Final camera lock—" in camera
    assert camera.rfind("Final camera lock—") > camera.rfind("framing language—")

    lighting = by_style["pairwise_style_pack_lighting_001"]
    assert "pigment fields printed across clothing and backdrop" in lighting
    assert "direction alone supplies every actual source" in lighting
    assert "final illumination blueprint" in lighting
    assert lighting.rfind("Final camera lock—") > lighting.rfind(
        "final illumination blueprint"
    )

    coloring = by_style["pairwise_artist_signature_coloring_001"]
    assert "these eight cues" in coloring
    assert "Final camera lock—frame literally" in coloring

    preset = by_style["preset_audit_001"]
    assert "Preserve only garment pieces visible" in preset
    assert preset.count("Opening camera contract—") == 1
    assert preset.count("Final camera lock—") == 1
    assert preset.rfind("Final camera lock—") > preset.rfind("natural-color")

    random_close = by_style["random_utility_001"]
    for conflict in (
        "full-length figure",
        "complete figure",
        "full-body stance",
        "full-body silhouette",
    ):
        assert conflict not in random_close
    assert "these eight cues" in random_close
    assert random_close.count("Opening camera contract—") == 1
    assert random_close.count("Final camera lock—") == 1
    assert random_close.rfind("Final camera lock—") > random_close.rfind(
        "outer-border ornament"
    )


def test_crop_aware_scene_body_removes_out_of_frame_lower_garments() -> None:
    chest = (
        "pausing mid-step with separated arms and stable weight in a library, "
        "wearing a structured overshirt, fluid column dress, and tapered trousers, with a "
        "quiet smile, framed in chest-up framing with gentle compression."
    )
    rendered = _crop_aware_scene_body(chest)
    assert "mid-step" not in rendered
    assert "tapered trousers" not in rendered
    assert "visible overshirt shoulders, collar, and chest panels" in rendered
    assert "visible dress bodice" in rendered
    assert "chest-up framing" in rendered

    thigh = (
        "turning in a coastal setting, wearing a collarless jacket, wide-leg trousers, "
        "and high-neck base, with a calm gaze, framed in eye-level thigh-up framing."
    )
    rendered = _crop_aware_scene_body(thigh)
    assert "wide-leg trousers" not in rendered
    assert "two broad upper-leg fabric panels intersected at mid-thigh" in rendered

    chest_hand = (
        "standing three-quarters, one hand at the waist and one lowered in a concourse, "
        "wearing a longline vest, fitted top, and straight trousers, with a calm gaze, "
        "framed in chest-up framing."
    )
    rendered = _crop_aware_scene_body(chest_hand)
    assert "one hand at the waist" not in rendered
    assert "upper arm bending toward a hand that continues below the frame" in rendered
    assert "longline vest" not in rendered
    assert "visible vest neckline, shoulders, and lapels" in rendered
    assert "straight trousers" not in rendered


def test_wide_camera_contract_fixes_scale_and_floor_margin() -> None:
    wide = "Use a wide view with the subject on a third and a clear depth path."
    opening = _opening_framing_contract(wide)
    closing = _framing_contract(wide)
    assert opening.startswith("Opening camera contract—pull the camera far back")
    assert closing.startswith("Final camera lock—pull the camera far back")
    for value in (opening, closing):
        assert "both shoes" in value
        assert "visible floor below both shoes" in value
        assert "at most two-thirds of the canvas height" in value
        assert "large enough for the face" not in value


def test_storyboard_camera_body_adds_a_counterweight_and_leaves_the_body_alone() -> None:
    """The medium rewrite is gone; only the counterweight clause is still derived.

    A camera body used to open "Photograph an adult subject", and that literal
    fought the storyboard baseline, so it was rewritten. The subject
    fragmentation dropped the opening, so there is nothing left to normalise and
    the body now passes through untouched.
    """
    original = (
        "captured in chest-up framing from a clean side camera position, using a classic wide "
        "field of view and one clear visual counterweight."
    )
    body, counterweight = _storyboard_camera_body(original)
    assert body == original
    assert "Photograph" not in body
    assert "small neutral-grey rectangular storyboard block" in counterweight
    assert "sole visual counterweight" in counterweight

    quiet_body, quiet_counterweight = _storyboard_camera_body(
        "captured in full-length framing from an eye-level frontal camera position."
    )
    assert quiet_counterweight == ""
    assert "counterweight" not in quiet_body


def test_lighting_style_synthesis_and_pose_ledger_remove_conflicts() -> None:
    item = _item("style_pack_001", "style_pack", status="approved")
    lighting_style = _lighting_neutral_style_direction(item)
    assert "amber-lit side" not in lighting_style
    assert "blue-shadowed side" not in lighting_style
    assert "amber and blue pigment fields" in lighting_style
    assert "second lighting direction alone supplies" in lighting_style

    plain_light = "Use one broad neutral daylight source with soft shadows."
    plain_authority = _lighting_axis_focus(plain_light) + _lighting_reconciliation(
        plain_light
    )
    assert "practical" not in plain_authority
    assert "reflected light" not in plain_authority

    complex_light = (
        "Use a cool key with readable reflected fill and one small warm practical lamp."
    )
    complex_authority = _lighting_axis_focus(complex_light) + _lighting_reconciliation(
        complex_light
    )
    assert "palm-sized warm amber lamp or glowing square" in complex_authority
    assert "reflected light or fill" in complex_authority

    artist = _item("artist_signature_001", "artist_signature", status="approved")
    ledger = reinforced_axis_visibility_ledger(artist["feature_axes"])
    aligned = _signature_ledger_at_camera_scale(
        ledger,
        "Use eye-level full-length framing.",
        scene_value="An adult holds a balanced contrapposto.",
    )
    assert "exaggerated fashion contrapposto" in aligned
    assert "compact grounded full-body stance" not in aligned
    pose_lock = _random_utility_reconciliation(
        artist["feature_axes"],
        "An adult holds a balanced contrapposto.",
    )
    assert "right heel lifted high off the ground" in pose_lock
    assert "Keep trousers slim enough" in pose_lock
    assert "only the toe touching" in pose_lock


def test_every_body_rewrite_literal_still_occurs_in_the_catalog() -> None:
    """A rewrite that no longer matches is a silent no-op, not an error.

    export_phase6_matrix reshapes catalog bodies by literal string replacement --
    exaggerating a contrapposto so the pose is measurable, dropping garments that
    fall outside a crop, widening a framing clause. When the catalog wording moves
    under those literals they simply stop firing, the prompt loses the correction,
    and nothing raises. The subject fragmentation did exactly that to five of them,
    and every existing test missed it because they all feed hand-written bodies
    rather than real catalog text.

    So this asserts the coupling directly: each literal the exporter searches for
    must still be findable somewhere in the catalog it is meant to rewrite.
    """
    corpus: list[str] = []
    for path in sorted((ROOT / "catalog").glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        items = document.get("items")
        if not isinstance(items, dict):
            continue
        for item in items.values():
            if isinstance(item, dict) and isinstance(item.get("prompt"), str):
                corpus.append(item["prompt"])
    assert corpus, "catalog corpus is empty"
    blob = "\n".join(corpus)

    source = (ROOT / "scripts" / "export_phase6_matrix.py").read_text(encoding="utf-8")
    searches = re.findall(r'''\.replace\(\s*["']([^"']{25,})["']''', source)
    assert len(searches) >= 8, "rewrite literals disappeared from the exporter"

    # These six are produced by reinforced_axis_visibility_ledger rather than read
    # from a catalog body, so their absence from the corpus is correct.
    intermediate = {
        "a compact grounded full-body stance",
        "a balanced narrow full-body silhouette",
        "within the full-length figure",
        "Keep the complete figure in front of every decorative framing element",
        "a centered figure inside an emblem-like border",
        "an off-center figure with broad open side space",
    }
    dead = [s for s in searches if s not in intermediate and s not in blob]
    assert not dead, f"rewrite literals no longer present in any catalog prompt: {dead}"
