#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any, Iterable

from common import load_yaml
from export_artist_native_matrix import validate_seeds, write_jsonl
from run_remote_prompt_matrix import validate_job


DEFAULT_SEEDS = (1001, 2002, 3003)
BENCHMARK_SEEDS = (1001, 2002, 3003, 4004, 5005)
FINISH = (
    "Preserve realistic skin texture, coherent hands, believable fabric, natural proportions, "
    "cinematic depth, and no text, logos, or watermarks."
)
FIXED_SCENE = (
    "Depict exactly one adult woman standing naturally on an uncluttered warm-grey studio "
    "cyclorama. Use an eye-level full-length camera, broad neutral diffused lighting, a plain "
    "long-sleeve top and straight trousers, with her head, both hands, and both feet visible."
)

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
            row = {
                "schema_version": 1,
                "test_id": f"{prefix}{len(rows) + 1:06d}",
                "style_id": case["style_id"],
                "label": case["style_id"],
                "mode": mode,
                "seed": seed,
                "prompt": case["prompt"],
                "factors": case.get("factors", {}),
            }
            validate_job(row, len(rows) + 1)
            rows.append(row)
    return rows


def single_axis_rows(seeds: Iterable[int] = DEFAULT_SEEDS) -> list[dict[str, Any]]:
    common = f"{FIXED_SCENE} Render it as a polished flat illustration with restrained soft shading."
    cases = [
        {
            "style_id": "single_axis_linework_fine_tapered",
            "prompt": (
                f"{common} Use fine tapered contour lines with light interior construction marks. "
                f"Keep a neutral mid-value palette. {FINISH}"
            ),
            "factors": {"axis": "linework", "variant": "fine_tapered"},
        },
        {
            "style_id": "single_axis_linework_bold_angular",
            "prompt": (
                f"{common} Use bold angular contour lines with firm geometric interior marks. "
                f"Keep a neutral mid-value palette. {FINISH}"
            ),
            "factors": {"axis": "linework", "variant": "bold_angular"},
        },
        {
            "style_id": "single_axis_coloring_muted_pastel",
            "prompt": (
                f"{common} Use medium-width clean contour lines. Apply a muted pastel palette with "
                f"low-contrast color separation. {FINISH}"
            ),
            "factors": {"axis": "coloring", "variant": "muted_pastel"},
        },
        {
            "style_id": "single_axis_coloring_deep_jewel",
            "prompt": (
                f"{common} Use medium-width clean contour lines. Apply a deep jewel palette with "
                f"high-contrast color separation. {FINISH}"
            ),
            "factors": {"axis": "coloring", "variant": "deep_jewel"},
        },
    ]
    return _rows(cases, seeds, prefix="SA", mode="single_axis")


def pairwise_rows(
    seeds: Iterable[int] = DEFAULT_SEEDS, *, cases_per_type: int = 16
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
            cases.append(
                {
                    "style_id": f"pairwise_{pair_type}_{index:03d}",
                    "prompt": (
                        f"{left_prompt}. Combine it coherently with this second visual direction: "
                        f"{right_prompt}. Resolve both directions on exactly one adult subject. {FINISH}"
                    ),
                    "factors": {
                        "pair_type": pair_type,
                        "left_item": left_id,
                        "right_item": right_id,
                    },
                }
            )
    return _rows(cases, seeds, prefix="PW", mode="pairwise")


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
            "prompt": f"{prompt} {FINISH}",
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
                "prompt": (
                    f"Apply this name-free visual treatment: {signature}. Use it to render this "
                    f"validated scene preset: {preset}. Keep the combined direction coherent. {FINISH}"
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
            "prompt": f"{prompt}. {FIXED_SCENE} {FINISH}",
            "factors": {"style_pack": style_id},
        }
    ]
    return _rows(cases, seeds, prefix="KB", mode="krea2_turbo_benchmark")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export resolved Phase 6 validation matrices"
    )
    parser.add_argument(
        "kind",
        choices=("single-axis", "pairwise", "presets", "random-utility", "benchmark"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", action="append", type=int, default=None)
    parser.add_argument("--cases-per-pair-type", type=int, default=16)
    parser.add_argument("--preset-count", type=int, default=100)
    parser.add_argument("--sample-count", type=int, default=20)
    args = parser.parse_args()
    try:
        seeds = args.seed or (
            BENCHMARK_SEEDS if args.kind == "benchmark" else DEFAULT_SEEDS
        )
        if args.kind == "single-axis":
            rows = single_axis_rows(seeds)
        elif args.kind == "pairwise":
            rows = pairwise_rows(seeds, cases_per_type=args.cases_per_pair_type)
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
