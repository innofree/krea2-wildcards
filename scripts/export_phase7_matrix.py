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
    CAMERA_SUBJECT_CONTRACT,
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
    preset_prompt,
    single_axis_prompt,
)
from run_remote_prompt_matrix import validate_job


DEFAULT_SEEDS = (1001, 2002, 3003)
CALIBRATION_SEEDS = (71001, 72002, 73003)
# A preset is a full scene contract, so it stays on the complete-scene 5-seed
# bar declared in catalog/evaluation.yaml.
COMPLETE_SCENE_SEEDS = (1001, 2002, 3003, 4004, 5005)
COMPLETE_SCENE_AXES = ("preset",)

PROVEN_AXES = (
    "background",
    "character_design",
    "lighting",
    "linework_coloring",
    "pose",
    "preset",
)
# camera is deliberately absent from PROVEN_AXES. Phase 6 selects
# CAMERA_SUBJECT_CONTRACT by searching the body for the literal "clean profile",
# which no catalog body contains -- every body reads "clean side camera position
# ... preserves the facial profile". All 42 profile items were therefore told to
# keep both eyes readable, which a profile view cannot satisfy, and generation
# resolved the conflict frontally. See plan.md 7.5.
CAMERA_PROFILE_MARKERS = ("clean side camera position", "facial profile")
# `_framing_contract` in export_phase6_matrix.py has no branch for these three
# crops, so all 94 camera items using one of them fall through to the generic
# mid-thigh default, which demands "both eyes" regardless of the actual crop.
# 8 of those 94 also want a profile view (close_face + clean_profile), so the
# fallback directly contradicts CAMERA_SUBJECT_CONTRACT's single visible eye.
# See plan.md 7.5.
CAMERA_CROP_FRAMING_MARKERS = (
    "close facial framing",
    "head-and-shoulders framing",
    "vertical full-scene framing",
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
# Calibration (plan.md 7.29) showed the catalog body's own medium description
# was not enough: every mark_making value rendered as the same generic
# photographic portrait. Appended after the closing camera lock -- the true
# end of the prompt, the position that reliably held the camera axis's
# profile-view fix -- this reasserts the medium where recency gives it the
# most weight.
PHASE7_AXIS_SUFFIX = {
    "media_rendering": (
        "This must not read as a photograph anywhere on the figure: apply the "
        "described medium's marks uniformly across skin, hair, and fabric, with "
        "no photographic skin texture visible."
    ),
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
    "preset": "catalog/presets.yaml",
}
BINDING_ARTIFACT_TYPE = "phase7_axis_prompt_binding"
PHASE7_PROFILE_ALGORITHM = (
    "phase7-mass-axis-v5|phase6-single-axis-prompt-reuse|"
    "item-id-keyed-rows-v1|per-item-prompt-digest-binding-v1|"
    "camera-profile-contract-repair-v1|camera-crop-framing-repair-v1|"
    "camera-profile-framing-suffix-repair-v1|axis-suffix-v1"
)
CAMERA_PROFILE_FRAMING_SUFFIX = (
    "This is a strict side-profile view: only the near eye is visible, and "
    "the far eye is fully hidden by the turn of the head."
)
PHASE7_PROFILE_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "camera_crop_framing_markers": list(CAMERA_CROP_FRAMING_MARKERS),
            "camera_profile_framing_suffix": CAMERA_PROFILE_FRAMING_SUFFIX,
            "camera_profile_markers": list(CAMERA_PROFILE_MARKERS),
            "phase6_profile_sha256": PHASE6_PROFILE_SHA256,
            "phase7_axis_anchors": PHASE7_AXIS_ANCHORS,
            "phase7_axis_focus": PHASE7_AXIS_FOCUS,
            "phase7_axis_framing": PHASE7_AXIS_FRAMING,
            "phase7_axis_suffix": PHASE7_AXIS_SUFFIX,
            "profile_algorithm": PHASE7_PROFILE_ALGORITHM,
            "version": "phase7_mass_axis_v5",
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
    if axis in PHASE7_AXIS_ANCHORS or axis == "camera":
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
    suffix = PHASE7_AXIS_SUFFIX.get(axis, "")
    tail = f"{framing} {suffix}".strip() if suffix else framing
    return (
        f"{SUBJECT_CONTRACT} {PHASE7_AXIS_FOCUS[axis]} "
        f"{value.strip().rstrip('.,;:')}. {FINISH} {tail}"
    )


def wants_profile_contract(body: str) -> bool:
    """Whether a camera body asks for a profile view, by its real phrasing."""
    lowered = body.lower()
    return any(marker in lowered for marker in CAMERA_PROFILE_MARKERS)


def camera_crop_framing_override(prompt: str, *, profile: bool) -> str | None:
    """Closing camera lock for the three crops the Phase 6 contract can't map."""
    lowered = prompt.lower()
    eyes_clause = "the visible profile eye" if profile else "both eyes"
    if "close facial framing" in lowered:
        return (
            "Final camera lock—make a tight close-face portrait cutting from just above "
            f"the hairline to just below the chin. Keep the complete crown and {eyes_clause} "
            "inside. Do not show the neck, shoulders, or anything below the jaw."
        )
    if "head-and-shoulders framing" in lowered:
        return (
            "Final camera lock—frame the head and shoulders, with a narrow strip of "
            "background above the complete crown and a lower edge crossing just below both "
            f"shoulders. Keep the face and {eyes_clause} inside. Do not show the chest, arms, "
            "or hands."
        )
    if "vertical full-scene framing" in lowered:
        return (
            "Final camera lock—pull back to a vertical full-scene view keeping the complete "
            f"crown, {eyes_clause}, both shoes, and visible floor below both shoes inside the "
            "canvas."
        )
    return None


def camera_prompt(prompt: str) -> str:
    """Phase 6 camera construction with the profile contract actually applied.

    A 12-shot recalibration (plan.md 7.26) showed the crop fix and an earlier
    reconciliation sentence were enough for close-face and thigh-up profile
    items (6/6 held the view) but not chest-up (5/6 still rendered frontal):
    its closing lock has a correct crop-boundary branch but never reasserts
    view direction, so the profile request decays by the end of the prompt.
    ``framing_suffix`` reinforces it at the true end of the prompt for every
    profile item, whatever its crop.
    """
    profile = wants_profile_contract(prompt)
    return single_axis_prompt(
        "camera",
        prompt,
        subject_contract=CAMERA_SUBJECT_CONTRACT if profile else SUBJECT_CONTRACT,
        framing_override=camera_crop_framing_override(prompt, profile=profile),
        framing_suffix=CAMERA_PROFILE_FRAMING_SUFFIX if profile else "",
        reconciliation_suffix=(
            " For a profile camera position, only the near eye must stay visible and "
            "readable; do not force the far eye into frame."
            if profile
            else ""
        ),
    )


def axis_prompt(axis: str, prompt: str) -> str:
    if axis == "preset":
        return preset_prompt(prompt)
    if axis == "camera":
        return camera_prompt(prompt)
    if axis in PROVEN_AXES:
        return single_axis_prompt(axis, prompt)
    return phase7_axis_prompt(axis, prompt)


def axis_seeds(axis: str) -> tuple[int, ...]:
    """Seed set an axis needs, following the catalog approval policy tiers."""
    if axis in COMPLETE_SCENE_AXES:
        return COMPLETE_SCENE_SEEDS
    return DEFAULT_SEEDS


def select_axis_items(
    axis: str,
    *,
    statuses: set[str] | None = None,
    include_ids: set[str] | None = None,
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
        if include_ids is not None and item_id not in include_ids:
            continue
        if any(item_id.startswith(prefix) for prefix in exclude):
            continue
        selected.append((item_id, item))
    if not selected:
        raise ValueError(f"axis {axis!r} has no matching items")
    if include_ids is not None:
        missing = sorted(include_ids - {item_id for item_id, _ in selected})
        if missing:
            raise ValueError(f"axis {axis!r} has no such item(s): {missing}")
    return sorted(selected, key=lambda entry: entry[0])


def mass_axis_rows(
    axis: str,
    seeds: Iterable[int] | None = None,
    *,
    statuses: set[str] | None = None,
    limit: int | None = None,
    include_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """One row per (item, seed) for a single axis, keyed by catalog item id."""
    if axis not in PHASE7_AXIS_CATALOGS:
        raise ValueError(f"unsupported axis: {axis}")
    seed_values = validate_seeds(axis_seeds(axis) if seeds is None else seeds)
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    items = select_axis_items(axis, statuses=statuses, include_ids=include_ids)
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
    """style_id to catalog prompt digest map for one axis."""
    binding: dict[str, str] = {}
    for row in rows:
        digest = row["factors"]["evaluated_prompt_sha256"][7:]
        existing = binding.setdefault(row["style_id"], digest)
        if existing != digest:
            raise ValueError(
                f"axis {axis!r} style {row['style_id']!r} has inconsistent digests"
            )
    return binding


def payload_sha256(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "binding_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def binding_document(axis: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 7's own prompt-binding record.

    This is deliberately not the artist_prompt_evidence_binding artifact:
    bind_artist_prompt_evidence.py reconstructs expected prompts with the artist
    signature renderer, so it cannot validate axis rows. Phase 7 records its own
    digests and verifies them by re-deriving from the exporter and catalog, and
    apply_evaluation_summary.py still enforces the per-item digest independently.
    """
    binding = prompt_binding(axis, rows)
    document: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": BINDING_ARTIFACT_TYPE,
        "axis": axis,
        "catalog": PHASE7_AXIS_CATALOGS[axis],
        "prompt_profile_sha256": axis_profile_factor(axis)[7:],
        "seeds": sorted({row["seed"] for row in rows}),
        "row_count": len(rows),
        "style_count": len(binding),
        "styles": dict(sorted(binding.items())),
    }
    document["binding_sha256"] = payload_sha256(document)
    return document


def verify_binding(path: Path) -> dict[str, Any]:
    """Re-derive a binding from the exporter and catalog, and compare."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("prompt binding must be a JSON object")
    if (
        document.get("schema_version") != 1
        or document.get("artifact_type") != BINDING_ARTIFACT_TYPE
    ):
        raise ValueError("prompt binding has invalid schema metadata")
    if document.get("binding_sha256") != payload_sha256(document):
        raise ValueError("prompt binding payload digest is stale")
    axis = document.get("axis")
    if axis not in PHASE7_AXIS_CATALOGS:
        raise ValueError(f"prompt binding has an unsupported axis: {axis!r}")
    seeds = document.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("prompt binding must record its seeds")
    expected = binding_document(axis, mass_axis_rows(axis, seeds))
    if document != expected:
        raise ValueError(
            f"prompt binding no longer matches the {axis} catalog or exporter"
        )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a Phase 7 mass promotion matrix for one axis"
    )
    parser.add_argument("axis", choices=sorted(PHASE7_AXIS_CATALOGS))
    parser.add_argument("--output", type=Path)
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
        "--include-id",
        action="append",
        default=None,
        help="restrict to these catalog item ids, for targeted calibration",
    )
    parser.add_argument(
        "--calibration",
        action="store_true",
        help="use the Phase 7 calibration seeds instead of the promotion seeds",
    )
    parser.add_argument(
        "--verify-binding",
        type=Path,
        help="verify an existing binding against the exporter and catalog, then exit",
    )
    args = parser.parse_args()
    try:
        if args.verify_binding is not None:
            document = verify_binding(args.verify_binding)
            print(
                f"Binding verified ({document['axis']}): "
                f"{document['style_count']} item(s), "
                f"{document['row_count']} row(s), "
                f"seeds={document['seeds']}."
            )
            return 0
        if args.output is None:
            raise ValueError("--output is required unless --verify-binding is used")
        if args.seed:
            seeds = args.seed
        elif args.calibration:
            seeds = CALIBRATION_SEEDS
        else:
            seeds = axis_seeds(args.axis)
        statuses = set(args.status) if args.status else {"generated"}
        rows = mass_axis_rows(
            args.axis,
            seeds,
            statuses=statuses,
            limit=args.limit,
            include_ids=set(args.include_id) if args.include_id else None,
        )
        write_jsonl(args.output, rows)
        if args.binding_output is not None:
            document = binding_document(args.axis, rows)
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
