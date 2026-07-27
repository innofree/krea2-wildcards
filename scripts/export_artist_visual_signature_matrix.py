#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

from common import canonical_prompt_sha256, load_yaml
from export_artist_native_matrix import validate_seeds
from run_remote_prompt_matrix import STYLE_ID_RE, validate_job


DEFAULT_CATALOG = Path("catalog/artists.yaml")
DEFAULT_OUTPUT = Path("tests/prompt_matrix/artist_visual_signature.jsonl")
DEFAULT_SEEDS = (1001, 2002, 3003)
REPAIR_SEEDS = (6101, 6202, 6303)
FRAMING_CALIBRATION_SEEDS = (7101, 7202, 7303)
SINGLE_VIEW_CALIBRATION_SEEDS = (8101, 8202, 8303)
EDITORIAL_CALIBRATION_SEEDS = (9101, 9202, 9303)
DEFAULT_STATUSES = ("generated",)
ALLOWED_STATUSES = frozenset({"generated", "testing", "approved"})
EXPECTED_VISUAL_AXES = 8
LEGACY_BENCHMARK_PROFILE = "artist_visual_signature_v0_8_2"
REPAIR_BENCHMARK_PROFILE = "artist_visual_signature_repair_v0_8_3"
FRAMING_CALIBRATION_PROFILE = (
    "artist_visual_signature_repair_framing_calibration_v0_8_4"
)
SINGLE_VIEW_CALIBRATION_PROFILE = (
    "artist_visual_signature_repair_single_view_calibration_v0_8_5"
)
EDITORIAL_CALIBRATION_PROFILE = (
    "artist_visual_signature_repair_editorial_calibration_v0_8_6"
)
BENCHMARK_PROFILES = frozenset(
    {
        LEGACY_BENCHMARK_PROFILE,
        REPAIR_BENCHMARK_PROFILE,
        FRAMING_CALIBRATION_PROFILE,
        SINGLE_VIEW_CALIBRATION_PROFILE,
        EDITORIAL_CALIBRATION_PROFILE,
    }
)
REPAIR_SIGNATURE_COUNT = 115
FRAMING_CALIBRATION_SIGNATURE_COUNT = 5
RETEST_SEEDS = (4004, 5005)
CATALOG_QUALITY_SUFFIX = (
    "Preserve realistic skin texture, coherent hands, believable fabric, natural proportions, "
    "cinematic depth, and no text, logos, or watermarks."
)
ILLUSTRATED_BENCHMARK_FINISH = (
    "Make the requested contour character, face geometry, eye construction, body silhouette, "
    "local-color palette, shadow-edge treatment, composition, and recurring motifs each "
    "unmistakably legible at contact-sheet scale. Finish this as a clearly hand-drawn "
    "two-dimensional character-design illustration with coherent illustrated anatomy, readable hands, "
    "clean garment shapes, and no text, logos, or watermarks."
)
REPAIR_ILLUSTRATED_BENCHMARK_FINISH = (
    "Make all eight requested axes independently legible without allowing one axis to substitute "
    "for another: contour and line language, face geometry, accessory-free eye construction, "
    "body silhouette and anatomy, local-color palette, light and shadow-edge treatment across "
    "the face, sleeves, garment folds, and ground, framing with negative space, and recurring "
    "ornament motifs in both garment and outer-border regions. Finish this as an unmistakably "
    "hand-drawn two-dimensional character-design illustration with clean garment surfaces, "
    "coherent illustrated anatomy, readable fingers, and no text, logos, or watermarks."
)
FIXED_SCENE = (
    "Create exactly one adult woman as a standing character-design portrait framed from "
    "mid-thigh upward at eye level. Keep her face and both eyes large enough to inspect, and show "
    "both complete hands clearly near the torso. Give her a simple long-sleeve garment with broad "
    "readable surfaces for the requested palette and ornament, against a quiet uncluttered studio "
    "ground. These neutral content anchors keep the subject, "
    "garment, camera distance, and background content comparable across seeds while the primary "
    "visual signature controls silhouette, placement, negative space, light and shadow, and "
    "ornament."
)
REPAIR_FIXED_SCENE = (
    "Create exactly one adult woman as a standing character-design portrait framed from "
    "mid-thigh upward at eye level, with the lower image edge crossing both thighs at mid-thigh "
    "and breathing room around the top of the head, elbows, and both complete hands. Present an "
    "accessory-free, completely exposed face and eye area, with hair and ornament arranged "
    "outside it, so the full iris, pupil, lids, lashes, and face geometry remain large and clear. "
    "Keep clear space around both hands so every finger remains readable. Give her a simple "
    "long-sleeve garment with broad readable "
    "surfaces for palette and garment-level motifs against a quiet uncluttered studio ground. "
    "If the requested framing language suggests a layered or intimate crop, express it through "
    "placement, negative space, and non-occluding foreground layers while leaving the head, face, "
    "eyes, forearms, and hands fully inside the frame. "
    "These neutral anchors keep subject, garment, camera distance, and background content "
    "comparable while the requested signature controls the eight visual axes."
)
FRAMING_CALIBRATION_OPEN = (
    "Full-body character sheet, camera far back. Exactly one adult woman stands centered. Keep "
    "her complete hair-to-shoes silhouette inside the square canvas with clear margins. Face "
    "and eyes forward; show both whole hands. Nothing touches an edge. Never zoom, crop, "
    "occlude, or cut her body."
)
FRAMING_CALIBRATION_CLOSE = (
    "Independently render line={line}; face={face}; eyes={eyes}; body={body}; "
    "palette={palette}; light={light}; framing={framing}; ornament={ornament}. Place these on "
    "contours and seams, face, irises and lids, silhouette, broad fields, shadows, negative "
    "space, and garment plus flat outer border, respectively. Treat close, intimate, layered, "
    "or foreground only as layout behind her, never crop or occlusion. Clean hand-drawn 2D, "
    "simple long sleeves, quiet studio, coherent anatomy and fingers; full silhouette, face, "
    "eyes, hands visible; no text, logos, or watermarks."
)
SINGLE_VIEW_CALIBRATION_OPEN = (
    "Full-body single-view, camera far back. Show exactly one adult woman once in one scene; no "
    "duplicate, lineup, alternate view, front-back pair, turnaround, inset, or panel. Keep her "
    "hair-to-shoes silhouette inside the square canvas with margins. Face and eyes forward, both "
    "hands whole. Nothing touches an edge. Never zoom, crop, or occlude."
)
SINGLE_VIEW_CALIBRATION_CLOSE = (
    "Make each cue bold and independent: line={line}; face={face}; eyes={eyes}; "
    "body={body}; palette={palette}; light={light}; framing={framing}; ornament={ornament}. "
    "Place them respectively on contours and seams; face; irises and lids; silhouette; broad "
    "fields; clear shadows; placement and negative space; repeated garment motif and flat outer "
    "border behind her. Close, intimate, layered, or foreground means background layout only, "
    "never crop. Clean hand-drawn 2D, simple sleeves, quiet studio, coherent anatomy and fingers; "
    "one full silhouette, face, eyes, hands; no text, logos, or watermarks."
)
EDITORIAL_CALIBRATION_SCENE = (
    "An adult fashion model holds a balanced full-length contrapposto pose on a spacious "
    "warm-grey cyclorama, wearing a plain long-sleeve top and straight full-length trousers, "
    "with both hands and both feet clearly visible. Her composed direct gaze, unobstructed eyes, "
    "eye-level head-to-toe framing, fixed camera position, and generous negative space around "
    "the complete silhouette remain unchanged. Keep exactly one complete adult figure with "
    "coherent illustrated anatomy and fingers, and no text, logos, or watermarks."
)
EDITORIAL_CALIBRATION_LEDGER = (
    "Render distinct visible cues: line={line} on contours and seams; face={face} on jaw and "
    "cheeks; eyes={eyes} in irises and lids; body={body} in the silhouette; palette={palette} "
    "in broad color fields; light={light} in face and garment shadows; framing={framing} through "
    "placement and negative space; ornament={ornament} as repeated garment trim and a flat "
    "decorative outer border behind the figure."
)
ARTIST_REFERENCE_RE = re.compile(
    r"\bartist(?:'s)?\b|\bin\s+the\s+style\s+of\b|\binfluenced\s+by\b|\bstyle\s+by\b",
    re.IGNORECASE,
)
WILDCARD_RE = re.compile(r"__[A-Za-z0-9][A-Za-z0-9_./-]*__")


def repair_axis_ledger(feature_axes: Any) -> str:
    if not isinstance(feature_axes, dict):
        raise ValueError("repair benchmark profile requires feature axes")

    def cue(axis: str) -> str:
        values = feature_axes.get(axis)
        if (
            not isinstance(values, list)
            or not values
            or not isinstance(values[0], str)
            or not values[0]
        ):
            raise ValueError(f"repair benchmark profile is missing feature axis {axis}")
        return values[0].replace("_", " ")

    return (
        "Use this eight-axis visibility ledger: "
        f"line—show {cue('line_language')} through the outer contour and garment seams; "
        f"face—show {cue('face_design')} through the jaw, cheeks, and nose; "
        f"eyes—keep hair and accessories away from fully exposed eyes and show {cue('eye_design')} "
        "in the iris, pupil, lids, and lashes; "
        f"body—show {cue('body_design')} through the shoulder and torso silhouette; "
        f"palette—separate broad garment and background regions using {cue('palette_language')}; "
        f"light—show {cue('light_modeling')} through shadow edges and highlights on the face, "
        "sleeves, garment folds, and ground; "
        f"framing—show {cue('framing_language')} through placement, negative space, and foreground "
        "layering while keeping the head, face, and both hands uncropped; "
        f"ornament—show {cue('ornament_language')} in two clear locations, as a repeating broad "
        "garment motif and as an outer-border motif."
    )


def framing_calibration_axis_ledger(feature_axes: Any) -> str:
    if not isinstance(feature_axes, dict):
        raise ValueError("framing calibration profile requires feature axes")

    def cue(axis: str) -> str:
        values = feature_axes.get(axis)
        if (
            not isinstance(values, list)
            or not values
            or not isinstance(values[0], str)
            or not values[0]
        ):
            raise ValueError(f"framing calibration profile is missing feature axis {axis}")
        return values[0].replace("_", " ")

    return FRAMING_CALIBRATION_CLOSE.format(
        line=cue("line_language"),
        face=cue("face_design"),
        eyes=cue("eye_design"),
        body=cue("body_design"),
        palette=cue("palette_language"),
        light=cue("light_modeling"),
        framing=cue("framing_language"),
        ornament=cue("ornament_language"),
    )


def single_view_calibration_axis_ledger(feature_axes: Any) -> str:
    if not isinstance(feature_axes, dict):
        raise ValueError("single-view calibration profile requires feature axes")

    def cue(axis: str) -> str:
        values = feature_axes.get(axis)
        if (
            not isinstance(values, list)
            or not values
            or not isinstance(values[0], str)
            or not values[0]
        ):
            raise ValueError(
                f"single-view calibration profile is missing feature axis {axis}"
            )
        return values[0].replace("_", " ")

    return SINGLE_VIEW_CALIBRATION_CLOSE.format(
        line=cue("line_language"),
        face=cue("face_design"),
        eyes=cue("eye_design"),
        body=cue("body_design"),
        palette=cue("palette_language"),
        light=cue("light_modeling"),
        framing=cue("framing_language"),
        ornament=cue("ornament_language"),
    )


def editorial_calibration_axis_ledger(feature_axes: Any) -> str:
    if not isinstance(feature_axes, dict):
        raise ValueError("editorial calibration profile requires feature axes")

    def cue(axis: str) -> str:
        values = feature_axes.get(axis)
        if (
            not isinstance(values, list)
            or not values
            or not isinstance(values[0], str)
            or not values[0]
        ):
            raise ValueError(
                f"editorial calibration profile is missing feature axis {axis}"
            )
        return values[0].replace("_", " ")

    return EDITORIAL_CALIBRATION_LEDGER.format(
        line=cue("line_language"),
        face=cue("face_design"),
        eyes=cue("eye_design"),
        body=cue("body_design"),
        palette=cue("palette_language"),
        light=cue("light_modeling"),
        framing=cue("framing_language"),
        ornament=cue("ornament_language"),
    )


def prompt_for_profile(
    body: str,
    benchmark_profile: str,
    *,
    feature_axes: Any = None,
) -> str:
    if benchmark_profile == EDITORIAL_CALIBRATION_PROFILE:
        return (
            "Create a clean hand-drawn 2D editorial illustration. "
            f"This exact visual signature controls the rendering: {body} "
            f"{editorial_calibration_axis_ledger(feature_axes)} "
            f"{EDITORIAL_CALIBRATION_SCENE}"
        )
    if benchmark_profile == SINGLE_VIEW_CALIBRATION_PROFILE:
        return (
            f"{SINGLE_VIEW_CALIBRATION_OPEN} "
            f"Controlling visual signature: {body} "
            f"{single_view_calibration_axis_ledger(feature_axes)}"
        )
    if benchmark_profile == FRAMING_CALIBRATION_PROFILE:
        return (
            f"{FRAMING_CALIBRATION_OPEN} "
            f"Controlling visual signature: {body} "
            f"{framing_calibration_axis_ledger(feature_axes)}"
        )
    if benchmark_profile == REPAIR_BENCHMARK_PROFILE:
        return (
            "Treat this visual signature as the controlling design brief. Every listed "
            "property must be visibly and independently expressed without merging one visual "
            f"axis into another: {body} {repair_axis_ledger(feature_axes)} "
            f"{REPAIR_FIXED_SCENE} "
            f"{REPAIR_ILLUSTRATED_BENCHMARK_FINISH}"
        )
    if benchmark_profile == LEGACY_BENCHMARK_PROFILE:
        return (
            "Treat this visual signature as the controlling design brief. Every listed "
            f"property must be visibly expressed: {body} {FIXED_SCENE} "
            f"{ILLUSTRATED_BENCHMARK_FINISH}"
        )
    raise ValueError(f"unsupported benchmark profile: {benchmark_profile}")


def write_immutable_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(
                f"refusing to overwrite a different versioned prompt matrix: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_statuses(statuses: Iterable[str]) -> tuple[str, ...]:
    values = tuple(statuses)
    if not values:
        raise ValueError("at least one status is required")
    if len(values) != len(set(values)):
        raise ValueError("statuses must be distinct")
    invalid = sorted(set(values) - ALLOWED_STATUSES)
    if invalid:
        raise ValueError(f"unsupported artist signature status: {', '.join(invalid)}")
    return values


def signature_body(value: Any, *, style_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"artist signature {style_id!r} must have a non-empty prompt")
    prompt = value.strip()
    if "\x00" in prompt:
        raise ValueError(f"artist signature {style_id!r} contains a null byte")
    if "@" in prompt or ARTIST_REFERENCE_RE.search(prompt):
        raise ValueError(
            f"artist signature {style_id!r} contains an artist-name reference"
        )
    if WILDCARD_RE.search(prompt):
        raise ValueError(
            f"artist signature {style_id!r} contains an unresolved wildcard"
        )
    if any(token in prompt for token in ("{", "}", "[", "]", "::")):
        raise ValueError(
            f"artist signature {style_id!r} contains NovelAI emphasis syntax"
        )
    if CATALOG_QUALITY_SUFFIX in prompt:
        raise ValueError(
            f"artist signature {style_id!r} contains the unvalidated realistic quality suffix"
        )
    return prompt


def signature_status(style_id: str, item: Any) -> str:
    if not isinstance(item, dict):
        raise ValueError(f"artist signature {style_id!r} must be a mapping")
    validation = item.get("validation")
    status = validation.get("status") if isinstance(validation, dict) else None
    if not isinstance(status, str) or not status:
        raise ValueError(f"artist signature {style_id!r} is missing validation status")
    return status


def validate_signature_item(style_id: str, item: Any) -> tuple[str, str]:
    if not isinstance(style_id, str) or not STYLE_ID_RE.fullmatch(style_id):
        raise ValueError(f"invalid artist signature id: {style_id!r}")
    if not isinstance(item, dict):
        raise ValueError(f"artist signature {style_id!r} must be a mapping")
    if item.get("family") != "artist_signature":
        raise ValueError(f"artist signature {style_id!r} has the wrong family")
    generation = item.get("generation")
    if not isinstance(generation, dict) or generation.get("kind") != "artist_signature":
        raise ValueError(f"artist signature {style_id!r} has the wrong generation kind")
    visual_axes = item.get("visual_axes")
    feature_axes = item.get("feature_axes")
    if not isinstance(visual_axes, list) or len(visual_axes) != EXPECTED_VISUAL_AXES:
        raise ValueError(
            f"artist signature {style_id!r} must define exactly {EXPECTED_VISUAL_AXES} visual axes"
        )
    if not isinstance(feature_axes, dict) or len(feature_axes) != EXPECTED_VISUAL_AXES:
        raise ValueError(
            f"artist signature {style_id!r} must define exactly {EXPECTED_VISUAL_AXES} feature axes"
        )
    status = signature_status(style_id, item)
    return status, signature_body(item.get("prompt"), style_id=style_id)


def signature_feature_vector(item: dict[str, Any]) -> frozenset[str]:
    feature_axes = item["feature_axes"]
    tokens: set[str] = set()
    for axis, values in sorted(feature_axes.items()):
        if not isinstance(axis, str) or not axis:
            raise ValueError("artist signature feature axis must have a non-empty name")
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError(
                f"artist signature feature axis {axis!r} must contain non-empty strings"
            )
        tokens.update(f"{axis}:{value}" for value in values)
    return frozenset(tokens)


def select_diverse_signatures(
    candidates: list[tuple[str, str, frozenset[str]]],
    limit: int,
) -> list[tuple[str, str, frozenset[str]]]:
    if limit == 1:
        return [candidates[0]]
    selected = [candidates[0]]
    remaining = candidates[1:]
    while len(selected) < limit:
        covered = frozenset().union(*(candidate[2] for candidate in selected))

        def rank(
            candidate: tuple[str, str, frozenset[str]],
        ) -> tuple[int, int, int, str]:
            vector = candidate[2]
            distances = [len(vector.symmetric_difference(item[2])) for item in selected]
            return (
                -min(distances),
                -len(vector - covered),
                -sum(distances),
                candidate[0],
            )

        chosen = min(remaining, key=rank)
        selected.append(chosen)
        remaining.remove(chosen)

    def score(
        selection: list[tuple[str, str, frozenset[str]]],
    ) -> tuple[int, int, int]:
        coverage = frozenset().union(*(candidate[2] for candidate in selection))
        distances = [
            len(left[2].symmetric_difference(right[2]))
            for index, left in enumerate(selection)
            for right in selection[index + 1 :]
        ]
        return len(coverage), min(distances, default=0), sum(distances)

    while True:
        current_score = score(selected)
        selected_ids = {candidate[0] for candidate in selected}
        best_score = current_score
        best_selection: list[tuple[str, str, frozenset[str]]] | None = None
        best_ids: tuple[str, ...] | None = None
        for index in range(len(selected)):
            for candidate in candidates:
                if candidate[0] in selected_ids:
                    continue
                trial = selected.copy()
                trial[index] = candidate
                trial_score = score(trial)
                trial_ids = tuple(sorted(item[0] for item in trial))
                if trial_score > best_score or (
                    trial_score == best_score
                    and best_selection is not None
                    and best_ids is not None
                    and trial_ids < best_ids
                ):
                    best_score = trial_score
                    best_selection = trial
                    best_ids = trial_ids
        if best_selection is None or best_score <= current_score:
            break
        selected = best_selection
    return sorted(selected, key=lambda candidate: candidate[0])


def signature_rows(
    catalog_path: Path,
    seeds: Iterable[int] = DEFAULT_SEEDS,
    *,
    statuses: Iterable[str] = DEFAULT_STATUSES,
    limit_signatures: int | None = None,
    include_prompt_digest: bool = True,
    benchmark_profile: str = LEGACY_BENCHMARK_PROFILE,
    require_candidate_count: int | None = None,
    require_signature_count: int | None = None,
) -> list[dict[str, Any]]:
    seed_values = validate_seeds(seeds)
    status_values = validate_statuses(statuses)
    if benchmark_profile not in BENCHMARK_PROFILES:
        raise ValueError(f"unsupported benchmark profile: {benchmark_profile}")
    if benchmark_profile == REPAIR_BENCHMARK_PROFILE:
        if seed_values != REPAIR_SEEDS:
            raise ValueError(
                "repair benchmark profile requires seeds "
                + ", ".join(str(seed) for seed in REPAIR_SEEDS)
            )
        if status_values != ("generated",):
            raise ValueError(
                "repair benchmark profile requires exactly status generated"
            )
        if limit_signatures is not None:
            raise ValueError("repair benchmark profile cannot limit signatures")
        if require_signature_count is None:
            require_signature_count = REPAIR_SIGNATURE_COUNT
    elif benchmark_profile == FRAMING_CALIBRATION_PROFILE:
        if seed_values != FRAMING_CALIBRATION_SEEDS:
            raise ValueError(
                "framing calibration profile requires seeds "
                + ", ".join(str(seed) for seed in FRAMING_CALIBRATION_SEEDS)
            )
        if status_values != ("generated",):
            raise ValueError(
                "framing calibration profile requires exactly status generated"
            )
        if limit_signatures != FRAMING_CALIBRATION_SIGNATURE_COUNT:
            raise ValueError(
                "framing calibration profile requires exactly "
                f"{FRAMING_CALIBRATION_SIGNATURE_COUNT} limited signatures"
            )
        if require_candidate_count is None:
            raise ValueError(
                "framing calibration profile requires an exact pre-limit candidate count"
            )
        if require_signature_count is None:
            require_signature_count = FRAMING_CALIBRATION_SIGNATURE_COUNT
    elif benchmark_profile == SINGLE_VIEW_CALIBRATION_PROFILE:
        if seed_values != SINGLE_VIEW_CALIBRATION_SEEDS:
            raise ValueError(
                "single-view calibration profile requires seeds "
                + ", ".join(str(seed) for seed in SINGLE_VIEW_CALIBRATION_SEEDS)
            )
        if status_values != ("generated",):
            raise ValueError(
                "single-view calibration profile requires exactly status generated"
            )
        if limit_signatures != FRAMING_CALIBRATION_SIGNATURE_COUNT:
            raise ValueError(
                "single-view calibration profile requires exactly "
                f"{FRAMING_CALIBRATION_SIGNATURE_COUNT} limited signatures"
            )
        if require_candidate_count is None:
            raise ValueError(
                "single-view calibration profile requires an exact pre-limit "
                "candidate count"
            )
        if require_signature_count is None:
            require_signature_count = FRAMING_CALIBRATION_SIGNATURE_COUNT
    elif benchmark_profile == EDITORIAL_CALIBRATION_PROFILE:
        if seed_values != EDITORIAL_CALIBRATION_SEEDS:
            raise ValueError(
                "editorial calibration profile requires seeds "
                + ", ".join(str(seed) for seed in EDITORIAL_CALIBRATION_SEEDS)
            )
        if status_values != ("generated",):
            raise ValueError(
                "editorial calibration profile requires exactly status generated"
            )
        if limit_signatures != FRAMING_CALIBRATION_SIGNATURE_COUNT:
            raise ValueError(
                "editorial calibration profile requires exactly "
                f"{FRAMING_CALIBRATION_SIGNATURE_COUNT} limited signatures"
            )
        if require_candidate_count is None:
            raise ValueError(
                "editorial calibration profile requires an exact pre-limit candidate count"
            )
        if require_signature_count is None:
            require_signature_count = FRAMING_CALIBRATION_SIGNATURE_COUNT
    document = load_yaml(catalog_path)
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, dict):
        raise ValueError("artist signature catalog must contain an items mapping")

    selected: list[tuple[str, str, frozenset[str]]] = []
    for style_id in sorted(items):
        if signature_status(style_id, items[style_id]) not in status_values:
            continue
        _, body = validate_signature_item(style_id, items[style_id])
        selected.append((style_id, body, signature_feature_vector(items[style_id])))
    if not selected:
        raise ValueError("no artist signatures matched the requested statuses")
    if require_candidate_count is not None:
        if type(require_candidate_count) is not int or require_candidate_count < 1:
            raise ValueError("require_candidate_count must be a positive integer")
        if len(selected) != require_candidate_count:
            raise ValueError(
                f"selected {len(selected)} artist signature candidate(s); "
                f"required exactly {require_candidate_count} before limiting"
            )
    if limit_signatures is not None:
        if type(limit_signatures) is not int or limit_signatures < 1:
            raise ValueError("limit_signatures must be a positive integer")
        if limit_signatures > len(selected):
            raise ValueError("limit_signatures exceeds the selected signature count")
        selected = select_diverse_signatures(selected, limit_signatures)
    if require_signature_count is not None:
        if type(require_signature_count) is not int or require_signature_count < 1:
            raise ValueError("require_signature_count must be a positive integer")
        if len(selected) != require_signature_count:
            raise ValueError(
                f"selected {len(selected)} artist signature(s); "
                f"required exactly {require_signature_count}"
            )

    rows: list[dict[str, Any]] = []
    for style_id, body, _ in selected:
        factors = {
            axis: values[0]
            for axis, values in sorted(items[style_id]["feature_axes"].items())
        }
        if include_prompt_digest:
            factors["evaluated_prompt_sha256"] = (
                "sha256_" + canonical_prompt_sha256(items[style_id]["prompt"])
            )
        if benchmark_profile in {
            REPAIR_BENCHMARK_PROFILE,
            FRAMING_CALIBRATION_PROFILE,
            SINGLE_VIEW_CALIBRATION_PROFILE,
            EDITORIAL_CALIBRATION_PROFILE,
        }:
            factors["benchmark_profile"] = benchmark_profile
            factors["benchmark_stage"] = (
                "pilot"
                if benchmark_profile == REPAIR_BENCHMARK_PROFILE
                else "calibration"
            )
        prompt = prompt_for_profile(
            body,
            benchmark_profile,
            feature_axes=items[style_id]["feature_axes"],
        )
        for seed in seed_values:
            row = {
                "schema_version": 1,
                "test_id": f"VS{len(rows) + 1:06d}",
                "style_id": style_id,
                "label": style_id,
                "mode": "visual_signature",
                "seed": seed,
                "prompt": prompt,
                "factors": factors,
            }
            validate_job(row, len(rows) + 1)
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a resolved name-free artist visual-signature benchmark matrix"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--status",
        action="append",
        choices=sorted(ALLOWED_STATUSES),
        default=None,
        help="include a lifecycle status; repeat for multiple statuses (default: generated)",
    )
    parser.add_argument(
        "--seed",
        action="append",
        type=int,
        default=None,
        help="include a distinct seed; repeat for extension seeds",
    )
    parser.add_argument(
        "--limit-signatures",
        type=int,
        help="select an evenly spaced deterministic subset for calibration",
    )
    parser.add_argument(
        "--omit-prompt-digest",
        action="store_true",
        help="reproduce a legacy immutable matrix that predates prompt digest binding",
    )
    parser.add_argument(
        "--benchmark-profile",
        choices=sorted(BENCHMARK_PROFILES),
        default=LEGACY_BENCHMARK_PROFILE,
        help="versioned prompt wrapper profile (default preserves v0.8.2 matrices)",
    )
    parser.add_argument(
        "--require-candidates",
        type=int,
        help="require the status-filtered pool to contain exactly this many signatures",
    )
    parser.add_argument(
        "--require-signatures",
        type=int,
        help="require the selected catalog status set to contain exactly this many signatures",
    )
    args = parser.parse_args()

    try:
        default_seeds = (
            REPAIR_SEEDS
            if args.benchmark_profile == REPAIR_BENCHMARK_PROFILE
            else (
                FRAMING_CALIBRATION_SEEDS
                if args.benchmark_profile == FRAMING_CALIBRATION_PROFILE
                else (
                    SINGLE_VIEW_CALIBRATION_SEEDS
                    if args.benchmark_profile == SINGLE_VIEW_CALIBRATION_PROFILE
                    else (
                        EDITORIAL_CALIBRATION_SEEDS
                        if args.benchmark_profile == EDITORIAL_CALIBRATION_PROFILE
                        else DEFAULT_SEEDS
                    )
                )
            )
        )
        seeds = validate_seeds(args.seed or default_seeds)
        statuses = validate_statuses(args.status or DEFAULT_STATUSES)
        rows = signature_rows(
            args.catalog,
            seeds,
            statuses=statuses,
            limit_signatures=args.limit_signatures,
            include_prompt_digest=not args.omit_prompt_digest,
            benchmark_profile=args.benchmark_profile,
            require_candidate_count=args.require_candidates,
            require_signature_count=args.require_signatures,
        )
        write_immutable_jsonl(args.output, rows)
        print(
            f"Wrote {len(rows)} resolved prompt(s): "
            f"{len({row['style_id'] for row in rows})} visual signature(s) x "
            f"{len(seeds)} seed(s), statuses={','.join(statuses)}."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
