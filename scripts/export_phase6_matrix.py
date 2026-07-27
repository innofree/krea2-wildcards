#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable

from common import load_yaml
from export_artist_native_matrix import validate_seeds, write_jsonl
from run_remote_prompt_matrix import validate_job


DEFAULT_SEEDS = (1001, 2002, 3003)
CALIBRATION_SEEDS = (21001, 22002, 23003)
BENCHMARK_SEEDS = (1001, 2002, 3003, 4004, 5005)
SUBJECT_CONTRACT = (
    "Compose one continuous single-view vertical image centered on exactly one clearly adult "
    "woman as the only figure. Every visible face, body, and hand belongs to this same woman. "
    "Keep a clean margin above her complete crown and keep both eyes clearly readable."
)
FINISH = (
    "Give every named visual cue an obvious, concrete location on the face, clothing, silhouette, "
    "lighting, or environment. Preserve the selected medium and keep the face, eyes, visible hands, "
    "joints, garment construction, and spatial relationships coherent. Finish the single scene "
    "cleanly with text-free, logo-free, watermark-free imagery."
)
FIXED_SCENE = (
    "Depict exactly one adult woman standing naturally on an uncluttered warm-grey studio "
    "cyclorama. Use an eye-level full-length camera, broad neutral diffused lighting, a plain "
    "long-sleeve top and straight trousers, with her head, both hands, and both feet visible."
)
SINGLE_AXIS_ANCHORS = {
    "character_design": (
        "Show the described adult design in a balanced standing pose. Dress her in a complete "
        "front-readable outfit that visibly carries every named layer, seam, closure, silhouette, "
        "and proportion cue. Use an eye-level full-length camera, broad neutral diffused lighting, "
        "and an uncluttered warm-grey studio cyclorama."
    ),
    "pose": (
        "Show exactly one adult woman in a plain long-sleeve top and straight trousers. Use an "
        "eye-level full-length camera, broad neutral diffused lighting, and an uncluttered "
        "warm-grey studio cyclorama, with her head, both hands, and both feet visible."
    ),
    "lighting": (
        "Show exactly one adult woman in a balanced standing pose, wearing a plain long-sleeve "
        "top and straight trousers. Use an eye-level full-length camera on an uncluttered neutral "
        "studio cyclorama, with her head, both hands, and both feet visible."
    ),
    "background": (
        "Show exactly one adult woman in a balanced standing pose, wearing a plain long-sleeve "
        "top and straight trousers. Use an eye-level full-length camera and broad neutral "
        "diffused lighting, with her head, both hands, and both feet visible."
    ),
    "linework_coloring": (
        "Render the adult as a clearly drawn editorial character illustration whose named line "
        "quality and color treatment cover the face, hair, clothing, and silhouette. Use an "
        "eye-level mid-thigh frame, broad neutral diffused lighting, and an uncluttered warm-grey "
        "studio ground, with her face, eyes, and both hands readable."
    ),
    "camera": (
        "Show the adult woman in a balanced pose, wearing a plain long-sleeve top under broad "
        "neutral diffused lighting on an uncluttered warm-grey studio cyclorama. Treat the named "
        "camera boundary, view position, field of view, placement, and negative space as literal."
    ),
}
PHASE6_PROFILE_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "finish": FINISH,
            "fixed_scene": FIXED_SCENE,
            "subject_contract": SUBJECT_CONTRACT,
            "single_axis_anchors": SINGLE_AXIS_ANCHORS,
            "version": "phase6_positive_profile_v3",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
PHASE6_PROFILE_FACTOR = f"sha256_{PHASE6_PROFILE_SHA256}"

PAIRWISE_SPECS = (
    (
        "style_pack_character_design",
        ("catalog/style_expansion.yaml", "catalog/art_styles.yaml"),
        "style_pack",
        "catalog/character_designs.yaml",
        "character_design",
    ),
    (
        "style_pack_pose",
        ("catalog/style_expansion.yaml", "catalog/art_styles.yaml"),
        "style_pack",
        "catalog/poses.yaml",
        "pose",
    ),
    (
        "style_pack_lighting",
        ("catalog/style_expansion.yaml", "catalog/art_styles.yaml"),
        "style_pack",
        "catalog/lighting.yaml",
        "lighting",
    ),
    (
        "style_pack_background",
        ("catalog/style_expansion.yaml", "catalog/art_styles.yaml"),
        "style_pack",
        "catalog/backgrounds.yaml",
        "background",
    ),
    (
        "artist_signature_coloring",
        ("catalog/artists.yaml",),
        "artist_signature",
        "catalog/linework_coloring.yaml",
        "linework_coloring",
    ),
    (
        "artist_signature_camera_composition",
        ("catalog/artists.yaml",),
        "artist_signature",
        "catalog/cameras.yaml",
        "camera",
    ),
)


def _catalog_items(path: Path) -> dict[str, dict[str, Any]]:
    document = load_yaml(path)
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, dict):
        raise ValueError(f"catalog has no items mapping: {path}")
    if any(
        not isinstance(key, str) or not isinstance(value, dict)
        for key, value in items.items()
    ):
        raise ValueError(f"catalog items are invalid: {path}")
    return items


def _status(item: dict[str, Any]) -> str | None:
    validation = item.get("validation")
    return validation.get("status") if isinstance(validation, dict) else None


def _prompt(item_id: str, item: dict[str, Any]) -> str:
    value = item.get("prompt")
    if not isinstance(value, str) or not value.strip():
        prompts = item.get("prompts")
        value = prompts[0] if isinstance(prompts, list) and prompts else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"catalog item has no prompt: {item_id}")
    return " ".join(value.split())


def _prompt_body(value: str) -> str:
    markers = (
        "Preserve realistic skin texture",
        "Preserve natural proportions",
        "Keep the result free of text",
    )
    indexes = [value.find(marker) for marker in markers if marker in value]
    if indexes:
        value = value[: min(indexes)]
    return value.strip().rstrip(".,;:")


def _framing_contract(value: str) -> str:
    lowered = value.lower()
    if "chest-up" in lowered:
        return (
            "Frame literally from the complete crown through the upper torso, with the chin, "
            "both shoulders, and the described upper-arm gesture inside the image."
        )
    if "waist-up" in lowered:
        return (
            "Frame literally from the complete crown through just below the waist, keeping both "
            "described hand gestures inside the image."
        )
    if "mid-thigh" in lowered or "thigh-up" in lowered:
        return (
            "Frame literally from the complete crown through mid-thigh, keeping the face and "
            "both described hand gestures inside the image."
        )
    if "full-length" in lowered:
        return (
            "Frame literally from the complete crown through both feet, with generous visible "
            "margin above the head and below the shoes."
        )
    if "wide view" in lowered:
        return (
            "Use the requested wide environmental view with the complete crown and complete "
            "figure inside the canvas while the subject remains large enough for the face and "
            "hands to be readable."
        )
    return (
        "Keep the complete crown, both eyes, and every body landmark named by the requested "
        "camera direction inside the image."
    )


def _profiled_prompt(value: str, focus: str) -> str:
    return (
        f"{SUBJECT_CONTRACT} {_framing_contract(value)} {focus} "
        f"{value.strip().rstrip('.,;:')}. {FINISH}"
    )


def _select(
    paths: Iterable[Path],
    *,
    count: int,
    family: str,
    statuses: set[str] | None,
) -> list[tuple[str, str]]:
    selected: dict[str, str] = {}
    for path in paths:
        for item_id, item in _catalog_items(path).items():
            if item.get("family") != family:
                continue
            if statuses is not None and _status(item) not in statuses:
                continue
            selected[item_id] = _prompt_body(_prompt(item_id, item))
    ordered = sorted(selected.items())
    if len(ordered) < count:
        expected = ",".join(sorted(statuses)) if statuses else "any"
        raise ValueError(
            f"need {count} {family} item(s) with status={expected}; found {len(ordered)}"
        )
    if count == 1:
        return [ordered[0]]
    indexes = [(index * (len(ordered) - 1)) // (count - 1) for index in range(count)]
    return [ordered[index] for index in indexes]


def _rows(
    cases: list[dict[str, Any]],
    seeds: Iterable[int],
    *,
    prefix: str,
    mode: str,
) -> list[dict[str, Any]]:
    seed_values = validate_seeds(seeds)
    rows: list[dict[str, Any]] = []
    for case in cases:
        for seed in seed_values:
            factors = dict(case.get("factors", {}))
            factors["prompt_profile_sha256"] = PHASE6_PROFILE_FACTOR
            row = {
                "schema_version": 1,
                "test_id": f"{prefix}{len(rows) + 1:06d}",
                "style_id": case["style_id"],
                "label": case["style_id"],
                "mode": mode,
                "seed": seed,
                "prompt": case["prompt"],
                "factors": factors,
            }
            validate_job(row, len(rows) + 1)
            rows.append(row)
    return rows


def single_axis_rows(
    seeds: Iterable[int] = DEFAULT_SEEDS, *, cases_per_axis: int = 16
) -> list[dict[str, Any]]:
    if cases_per_axis < 1:
        raise ValueError("cases_per_axis must be at least 1")
    cases: list[dict[str, Any]] = []
    seen_axes: set[str] = set()
    for _, _, _, right_path, right_family in PAIRWISE_SPECS:
        if right_family in seen_axes:
            continue
        seen_axes.add(right_family)
        selected = _select(
            (Path(right_path),),
            count=cases_per_axis,
            family=right_family,
            statuses=None,
        )
        anchor = SINGLE_AXIS_ANCHORS[right_family]
        for index, (item_id, prompt) in enumerate(selected, start=1):
            focus = {
                "character_design": (
                    "The character design is the measured axis: make its named face geometry, "
                    "body proportions, garment silhouette, seams, and closures visibly explicit."
                ),
                "pose": (
                    "The pose is the measured axis: make the named hand placement, shoulder line, "
                    "gaze, leg support, and weight distribution visibly explicit."
                ),
                "lighting": (
                    "The lighting is the measured axis: keep both eyes readable and make every "
                    "named source direction, shadow edge, reflected fill, and accent distinguishable."
                ),
                "background": (
                    "The background is the measured axis: keep the subject large and readable "
                    "while every named foreground, middle-distance, horizon, and atmosphere layer "
                    "remains distinct."
                ),
                "linework_coloring": (
                    "Linework and coloring are the measured axis: make the named contour geometry, "
                    "palette families, value planes, and edge accent plainly visible across the figure."
                ),
                "camera": (
                    "The camera is the measured axis: obey its crop boundary, camera position, field "
                    "of view, subject placement, and negative-space relationship exactly."
                ),
            }[right_family]
            cases.append(
                {
                    "style_id": f"single_axis_{right_family}_{index:03d}",
                    "prompt": _profiled_prompt(
                        f"Apply exactly this {right_family} direction as the sole changing axis: "
                        f"{prompt}. {anchor}",
                        focus,
                    ),
                    "factors": {"axis": right_family, "item_id": item_id},
                }
            )
    return _rows(cases, seeds, prefix="SA", mode="single_axis")


def pairwise_rows(
    seeds: Iterable[int] = DEFAULT_SEEDS,
    *,
    cases_per_type: int = 16,
    passed_single_axis_items: set[str] | None = None,
) -> list[dict[str, Any]]:
    if cases_per_type < 1:
        raise ValueError("cases_per_type must be at least 1")
    cases: list[dict[str, Any]] = []
    for pair_type, left_paths, left_family, right_path, right_family in PAIRWISE_SPECS:
        left = _select(
            (Path(path) for path in left_paths),
            count=cases_per_type,
            family=left_family,
            statuses={"approved"},
        )
        right = _select(
            (Path(right_path),),
            count=cases_per_type,
            family=right_family,
            statuses=None,
        )
        for index, ((left_id, left_prompt), (right_id, right_prompt)) in enumerate(
            zip(left, right, strict=True), start=1
        ):
            focus = {
                "character_design": (
                    "The second character-design direction is the measured axis. Put its named "
                    "face geometry, proportions, layers, seams, and closures on the visible subject."
                ),
                "pose": (
                    "The second pose direction is the measured axis. Make its named hand placement, "
                    "gaze, shoulder line, leg support, and weight distribution unambiguous."
                ),
                "lighting": (
                    "The second lighting direction is the measured axis. Keep both eyes readable "
                    "and give its named key source, shadow structure, reflected fill, and practical "
                    "accent separate visible roles."
                ),
                "background": (
                    "The second background direction is the measured axis. Keep the complete subject "
                    "large enough to read while its foreground, middle-distance, horizon, and "
                    "atmosphere remain visibly separated."
                ),
                "linework_coloring": (
                    "The second line-and-color direction is the measured axis. Render its named "
                    "contours, jewel palette, value planes, and rim accent across one continuous figure."
                ),
                "camera": (
                    "The second camera direction is the measured axis. Obey its literal crop, side "
                    "view, field of view, asymmetric placement, and negative-space counterweight."
                ),
            }[right_family]
            cases.append(
                {
                    "style_id": f"pairwise_{pair_type}_{index:03d}",
                    "prompt": _profiled_prompt(
                        f"{left_prompt}. Combine it coherently with this second visual direction: "
                        f"{right_prompt}. Resolve both directions on the same adult subject",
                        focus,
                    ),
                    "factors": {
                        "pair_type": pair_type,
                        "left_item": left_id,
                        "right_item": right_id,
                    },
                }
            )
    rows = _rows(cases, seeds, prefix="PW", mode="pairwise")
    selected_right_items = {row["factors"]["right_item"] for row in rows}
    if (
        passed_single_axis_items is not None
        and not selected_right_items <= passed_single_axis_items
    ):
        missing = sorted(selected_right_items - passed_single_axis_items)
        raise ValueError(
            "pairwise matrix includes item(s) without passing single-axis evidence: "
            + ", ".join(missing[:5])
        )
    return rows


def preset_rows(
    seeds: Iterable[int] = DEFAULT_SEEDS, *, preset_count: int = 100
) -> list[dict[str, Any]]:
    presets = _select(
        (Path("catalog/presets.yaml"),),
        count=preset_count,
        family="preset",
        statuses=None,
    )
    cases = [
        {
            "style_id": f"preset_audit_{index:03d}",
            "prompt": _profiled_prompt(
                prompt,
                "Treat the validated preset as an exact scene contract: visibly preserve its named "
                "pose, hand placement, location, garment pieces, expression, camera boundary, "
                "perspective, and lighting.",
            ),
            "factors": {"preset": preset_id},
        }
        for index, (preset_id, prompt) in enumerate(presets, start=1)
    ]
    return _rows(cases, seeds, prefix="PA", mode="preset_audit")


def random_utility_rows(
    seeds: Iterable[int] = DEFAULT_SEEDS,
    *,
    sample_count: int = 20,
    selection_seed: int = 20260727,
) -> list[dict[str, Any]]:
    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")
    presets = sorted(
        (
            item_id,
            _prompt_body(_prompt(item_id, item)),
        )
        for item_id, item in _catalog_items(Path("catalog/presets.yaml")).items()
        if item.get("family") == "preset"
    )
    signatures = sorted(
        (
            item_id,
            _prompt_body(_prompt(item_id, item)),
        )
        for item_id, item in _catalog_items(Path("catalog/artists.yaml")).items()
        if item.get("family") == "artist_signature" and _status(item) == "approved"
    )
    if len(presets) < sample_count or len(signatures) < sample_count:
        raise ValueError(
            "random utility requires enough presets and approved artist signatures"
        )
    chooser = random.Random(selection_seed)
    chosen_presets = chooser.sample(presets, sample_count)
    chosen_signatures = chooser.sample(signatures, sample_count)
    cases = []
    for index, ((preset_id, preset), (signature_id, signature)) in enumerate(
        zip(chosen_presets, chosen_signatures, strict=True), start=1
    ):
        cases.append(
            {
                "style_id": f"random_utility_{index:03d}",
                "prompt": _profiled_prompt(
                    f"Apply this name-free visual treatment: {signature}. Use it to render this "
                    f"validated scene preset: {preset}. Keep the combined direction coherent",
                    "Make the name-free visual treatment the unmistakable rendering language across "
                    "the face, eyes, hair, clothing, silhouette, palette, shading, composition, and "
                    "motif placement while keeping the validated scene readable.",
                ),
                "factors": {"preset": preset_id, "artist_signature": signature_id},
            }
        )
    return _rows(cases, seeds, prefix="RU", mode="random_utility")


def benchmark_rows(seeds: Iterable[int] = BENCHMARK_SEEDS) -> list[dict[str, Any]]:
    styles = _select(
        (Path("catalog/art_styles.yaml"), Path("catalog/style_expansion.yaml")),
        count=1,
        family="style_pack",
        statuses={"approved"},
    )
    style_id, prompt = styles[0]
    cases = [
        {
            "style_id": "krea2_turbo_benchmark",
            "prompt": _profiled_prompt(
                f"{prompt}. {FIXED_SCENE}",
                "Make the selected style pack visible across the subject and backdrop while keeping "
                "the fixed studio scene and the complete adult figure easy to inspect.",
            ),
            "factors": {"style_pack": style_id},
        }
    ]
    return _rows(cases, seeds, prefix="KB", mode="krea2_turbo_benchmark")


def calibration_rows(
    seeds: Iterable[int] = CALIBRATION_SEEDS,
) -> list[dict[str, Any]]:
    seed_values = validate_seeds(seeds)
    rows = [
        *single_axis_rows(seed_values, cases_per_axis=1),
        *pairwise_rows(seed_values, cases_per_type=1),
        *preset_rows(seed_values, preset_count=5),
        *random_utility_rows(seed_values, sample_count=5),
        *benchmark_rows(seed_values),
    ]
    if len(rows) != 69 or len({row["test_id"] for row in rows}) != len(rows):
        raise ValueError("Phase 6 calibration must contain exactly 69 unique jobs")
    return rows


def load_passed_single_axis_items(path: Path) -> set[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or document.get("report_type") != "single_axis_coverage"
        or document.get("status") != "passed"
        or document.get("complete") is not True
        or document.get("prompt_profile_sha256") != PHASE6_PROFILE_SHA256
    ):
        raise ValueError("single-axis report is not a passing current-profile report")
    values = document.get("passed_item_ids")
    if (
        not isinstance(values, list)
        or not values
        or len(values) != len(set(values))
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise ValueError("single-axis report has invalid passed_item_ids")
    return set(values)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export resolved Phase 6 validation matrices"
    )
    parser.add_argument(
        "kind",
        choices=(
            "calibration",
            "single-axis",
            "pairwise",
            "presets",
            "random-utility",
            "benchmark",
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", action="append", type=int, default=None)
    parser.add_argument("--cases-per-pair-type", type=int, default=16)
    parser.add_argument("--cases-per-axis", type=int, default=16)
    parser.add_argument("--preset-count", type=int, default=100)
    parser.add_argument("--sample-count", type=int, default=20)
    parser.add_argument("--single-axis-report", type=Path)
    args = parser.parse_args()
    try:
        if args.seed:
            seeds = args.seed
        elif args.kind == "benchmark":
            seeds = BENCHMARK_SEEDS
        elif args.kind == "calibration":
            seeds = CALIBRATION_SEEDS
        else:
            seeds = DEFAULT_SEEDS
        if args.kind == "calibration":
            rows = calibration_rows(seeds)
        elif args.kind == "single-axis":
            rows = single_axis_rows(seeds, cases_per_axis=args.cases_per_axis)
        elif args.kind == "pairwise":
            if args.single_axis_report is None:
                raise ValueError("pairwise export requires --single-axis-report")
            rows = pairwise_rows(
                seeds,
                cases_per_type=args.cases_per_pair_type,
                passed_single_axis_items=load_passed_single_axis_items(
                    args.single_axis_report
                ),
            )
        elif args.kind == "presets":
            rows = preset_rows(seeds, preset_count=args.preset_count)
        elif args.kind == "random-utility":
            rows = random_utility_rows(seeds, sample_count=args.sample_count)
        else:
            rows = benchmark_rows(seeds)
        write_jsonl(args.output, rows)
        print(
            f"Wrote {len(rows)} resolved {args.kind} prompt(s): "
            f"{len({row['style_id'] for row in rows})} case(s), "
            f"{len({row['seed'] for row in rows})} seed(s)."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
