#!/usr/bin/env python3
"""Export Phase 7 mass promotion matrices, one axis per run.

Phase 6 measured each axis with 16 sampled cases and synthetic ``style_id``
values. Promotion needs the opposite shape: every ``generated`` item of one
axis, keyed by its catalog id, so ``apply_evaluation_summary.py`` can resolve
``items[style_id]`` and bind each row to the item's own prompt digest.

Axes that Phase 6 already validated reuse ``single_axis_prompt`` verbatim and
carry the Phase 6 profile digest. The four axes Phase 6 never covered get their
own anchors and a separate Phase 7 digest, so adding them cannot disturb the
frozen Phase 6 completion evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from common import canonical_prompt_sha256, load_yaml
from export_artist_native_matrix import validate_seeds, write_jsonl
from export_phase6_matrix import (
    FINISH,
    PHASE6_PROFILE_FACTOR,
    PHASE6_PROFILE_SHA256,
    SINGLE_AXIS_EXCLUDED_ITEM_PREFIXES,
    SUBJECT_CONTRACT,
    _catalog_items,
    _framing_contract,
    _prompt,
    _prompt_body,
    _status,
    single_axis_prompt,
)
from run_remote_prompt_matrix import validate_job


DEFAULT_SEEDS = (1001, 2002, 3003)
CALIBRATION_SEEDS = (71001, 72002, 73003)

PROVEN_AXES = (
    "background",
    "camera",
    "character_design",
    "lighting",
    "linework_coloring",
    "pose",
)
PHASE7_AXIS_ANCHORS = {
    "fashion": (
        "Show exactly one adult woman in a balanced standing pose with a simple "
        "shoulder-length neutral-brown hairstyle. Use an eye-level full-length camera, "
        "broad neutral diffused lighting, and an uncluttered warm-grey studio cyclorama, "
        "with her head, both hands, and both feet visible."
    ),
    "hair_design": (
        "Show exactly one adult woman in a plain long-sleeve top, facing the camera in a "
        "balanced upright pose. Use broad neutral diffused lighting and an uncluttered "
        "warm-grey studio cyclorama, keeping her complete crown, hairline, face, and both "
        "eyes readable."
    ),
    "effect": (
        "Show exactly one adult woman in a balanced standing pose, wearing a plain "
        "long-sleeve top and straight trousers, on an uncluttered warm-grey studio ground "
        "under broad neutral diffused lighting. Keep her the dominant subject: the named "
        "elements never cover her face, both hands, or silhouette."
    ),
    "media_rendering": (
        "Render the adult as a clearly drawn editorial character illustration whose named "
        "medium covers the face, hair, clothing, and silhouette. Use an eye-level mid-thigh "
        "frame, broad neutral diffused lighting, and an uncluttered warm-grey studio ground, "
        "with her face, eyes, and both hands readable."
    ),
}
PHASE7_AXIS_FOCUS = {
    "fashion": (
        "The outfit is the measured axis: make every named garment layer, fabric structure, "
        "construction detail, and palette family front-readable on the clothing."
    ),
    "hair_design": (
        "The hair design is the measured axis: make the named cut shape, strand texture, "
        "parting arrangement, and color transition plainly visible from crown to ends."
    ),
    "effect": (
        "The effect is the measured axis: make the named element, frame placement, density "
        "gradient, and motion direction distinct while the subject stays fully readable."
    ),
    "media_rendering": (
        "The medium is the measured axis: make the named mark making, ground surface, depth "
        "treatment, and light response plainly visible across the figure."
    ),
}
PHASE7_AXIS_FRAMING = {
    "fashion": "Use an eye-level full-length camera.",
    "hair_design": "Use an eye-level waist-up camera.",
    "effect": "Use an eye-level full-length camera.",
    "media_rendering": "Use an eye-level mid-thigh camera.",
}
PHASE7_AXIS_CATALOGS = {
    "background": "catalog/backgrounds.yaml",
    "camera": "catalog/cameras.yaml",
    "character_design": "catalog/character_designs.yaml",
    "effect": "catalog/effects.yaml",
    "fashion": "catalog/fashion.yaml",
    "hair_design": "catalog/hair_designs.yaml",
    "lighting": "catalog/lighting.yaml",
    "linework_coloring": "catalog/linework_coloring.yaml",
    "media_rendering": "catalog/media_rendering.yaml",
    "pose": "catalog/poses.yaml",
}
PHASE7_PROFILE_ALGORITHM = (
    "phase7-mass-axis-v1|phase6-single-axis-prompt-reuse|"
    "item-id-keyed-rows-v1|per-item-prompt-digest-binding-v1"
)
PHASE7_PROFILE_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "phase6_profile_sha256": PHASE6_PROFILE_SHA256,
            "phase7_axis_anchors": PHASE7_AXIS_ANCHORS,
            "phase7_axis_focus": PHASE7_AXIS_FOCUS,
            "phase7_axis_framing": PHASE7_AXIS_FRAMING,
            "profile_algorithm": PHASE7_PROFILE_ALGORITHM,
            "version": "phase7_mass_axis_v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
PHASE7_PROFILE_FACTOR = f"sha256_{PHASE7_PROFILE_SHA256}"


def axis_profile_factor(axis: str) -> str:
    """Profile digest a row carries.

    Proven axes submit the exact prompt string Phase 6 passed, so they stay bound
    to the Phase 6 digest rather than claiming a new profile.
    """
    if axis in PROVEN_AXES:
        return PHASE6_PROFILE_FACTOR
    if axis in PHASE7_AXIS_ANCHORS:
        return PHASE7_PROFILE_FACTOR
    raise ValueError(f"unsupported axis: {axis}")


def phase7_axis_prompt(axis: str, prompt: str) -> str:
    """Render an axis Phase 6 never covered, in the same profiled shape."""
    if axis not in PHASE7_AXIS_ANCHORS:
        raise ValueError(f"axis has no Phase 7 anchor: {axis}")
    value = (
        f"Apply exactly this {axis} direction as the sole changing axis: "
        f"{prompt}. {PHASE7_AXIS_ANCHORS[axis]}"
    )
    framing = _framing_contract(PHASE7_AXIS_FRAMING[axis])
    return (
        f"{SUBJECT_CONTRACT} {PHASE7_AXIS_FOCUS[axis]} "
        f"{value.strip().rstrip('.,;:')}. {FINISH} {framing}"
    )


def axis_prompt(axis: str, prompt: str) -> str:
    if axis in PROVEN_AXES:
        return single_axis_prompt(axis, prompt)
    return phase7_axis_prompt(axis, prompt)


def select_axis_items(
    axis: str, *, statuses: set[str] | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Every catalog item on one axis, id-sorted, with Phase 6 exclusions kept."""
    if axis not in PHASE7_AXIS_CATALOGS:
        raise ValueError(f"unsupported axis: {axis}")
    exclude = SINGLE_AXIS_EXCLUDED_ITEM_PREFIXES if axis == "pose" else ()
    selected: list[tuple[str, dict[str, Any]]] = []
    for item_id, item in _catalog_items(Path(PHASE7_AXIS_CATALOGS[axis])).items():
        if item.get("family") != axis:
            continue
        if statuses is not None and _status(item) not in statuses:
            continue
        if any(item_id.startswith(prefix) for prefix in exclude):
            continue
        selected.append((item_id, item))
    if not selected:
        raise ValueError(f"axis {axis!r} has no matching items")
    return sorted(selected, key=lambda entry: entry[0])


def mass_axis_rows(
    axis: str,
    seeds: Iterable[int] = DEFAULT_SEEDS,
    *,
    statuses: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """One row per (item, seed) for a single axis, keyed by catalog item id."""
    seed_values = validate_seeds(seeds)
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    items = select_axis_items(axis, statuses=statuses)
    if limit is not None:
        items = items[:limit]
    profile_factor = axis_profile_factor(axis)
    rows: list[dict[str, Any]] = []
    for item_id, item in items:
        rendered = axis_prompt(axis, _prompt_body(_prompt(item_id, item)))
        digest = canonical_prompt_sha256(item.get("prompt"))
        for seed in seed_values:
            row = {
                "schema_version": 1,
                "test_id": f"P7{len(rows) + 1:06d}",
                "style_id": item_id,
                "label": item_id,
                "mode": f"mass_axis_{axis}",
                "seed": seed,
                "prompt": rendered,
                "factors": {
                    "axis": axis,
                    "item_id": item_id,
                    "prompt_profile_sha256": profile_factor,
                    "evaluated_prompt_sha256": f"sha256_{digest}",
                },
            }
            validate_job(row, len(rows) + 1)
            rows.append(row)
    return rows


def prompt_binding(axis: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    """style_id to prompt digest map, as apply_evaluation_summary expects."""
    binding: dict[str, str] = {}
    for row in rows:
        digest = row["factors"]["evaluated_prompt_sha256"][7:]
        existing = binding.setdefault(row["style_id"], digest)
        if existing != digest:
            raise ValueError(
                f"axis {axis!r} style {row['style_id']!r} has inconsistent digests"
            )
    return binding


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a Phase 7 mass promotion matrix for one axis"
    )
    parser.add_argument("axis", choices=sorted(PHASE7_AXIS_CATALOGS))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binding-output", type=Path)
    parser.add_argument("--seed", action="append", type=int, default=None)
    parser.add_argument(
        "--status",
        action="append",
        default=None,
        help="catalog status to include (default: generated)",
    )
    parser.add_argument(
        "--limit", type=int, help="cap item count, for anchor calibration runs"
    )
    parser.add_argument(
        "--calibration",
        action="store_true",
        help="use the Phase 7 calibration seeds instead of the promotion seeds",
    )
    args = parser.parse_args()
    try:
        seeds = args.seed or (CALIBRATION_SEEDS if args.calibration else DEFAULT_SEEDS)
        statuses = set(args.status) if args.status else {"generated"}
        rows = mass_axis_rows(
            args.axis, seeds, statuses=statuses, limit=args.limit
        )
        write_jsonl(args.output, rows)
        if args.binding_output is not None:
            binding = prompt_binding(args.axis, rows)
            document = {
                "schema_version": 1,
                "kind": "phase7_axis_prompt_binding",
                "axis": args.axis,
                "catalog": PHASE7_AXIS_CATALOGS[args.axis],
                "prompt_profile_sha256": axis_profile_factor(args.axis)[7:],
                "style_count": len(binding),
                "styles": dict(sorted(binding.items())),
            }
            args.binding_output.parent.mkdir(parents=True, exist_ok=True)
            args.binding_output.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        items = len({row["style_id"] for row in rows})
        print(
            f"Wrote {len(rows)} resolved {args.axis} prompt(s): "
            f"{items} item(s), {len({row['seed'] for row in rows})} seed(s)."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
