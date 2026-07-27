#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Iterable

from common import load_yaml
from export_artist_native_matrix import validate_seeds, write_jsonl
from run_remote_prompt_matrix import STYLE_ID_RE, validate_job


DEFAULT_CATALOG = Path("catalog/artists.yaml")
DEFAULT_OUTPUT = Path("tests/prompt_matrix/artist_visual_signature.jsonl")
DEFAULT_SEEDS = (1001, 2002, 3003)
DEFAULT_STATUSES = ("generated",)
ALLOWED_STATUSES = frozenset({"generated", "testing", "approved"})
EXPECTED_VISUAL_AXES = 8
CATALOG_QUALITY_SUFFIX = (
    "Preserve realistic skin texture, coherent hands, believable fabric, natural proportions, "
    "cinematic depth, and no text, logos, or watermarks."
)
FIXED_SCENE = (
    "Depict exactly one adult woman in a balanced standing pose, wearing a plain fitted "
    "long-sleeve top and straight trousers on an uncluttered warm-grey studio cyclorama. "
    "Use an eye-level full-length camera and broad neutral diffused lighting, with her head, "
    "both hands, and both feet fully visible."
)
ARTIST_REFERENCE_RE = re.compile(
    r"\bartist(?:'s)?\b|\bin\s+the\s+style\s+of\b|\binfluenced\s+by\b|\bstyle\s+by\b",
    re.IGNORECASE,
)
WILDCARD_RE = re.compile(r"__[A-Za-z0-9][A-Za-z0-9_./-]*__")


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
        raise ValueError(f"artist signature {style_id!r} contains an artist-name reference")
    if WILDCARD_RE.search(prompt):
        raise ValueError(f"artist signature {style_id!r} contains an unresolved wildcard")
    if any(token in prompt for token in ("{", "}", "[", "]", "::")):
        raise ValueError(f"artist signature {style_id!r} contains NovelAI emphasis syntax")
    if prompt.endswith(CATALOG_QUALITY_SUFFIX):
        prompt = prompt[: -len(CATALOG_QUALITY_SUFFIX)].rstrip()
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


def signature_rows(
    catalog_path: Path,
    seeds: Iterable[int] = DEFAULT_SEEDS,
    *,
    statuses: Iterable[str] = DEFAULT_STATUSES,
) -> list[dict[str, Any]]:
    seed_values = validate_seeds(seeds)
    status_values = validate_statuses(statuses)
    document = load_yaml(catalog_path)
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, dict):
        raise ValueError("artist signature catalog must contain an items mapping")

    selected: list[tuple[str, str]] = []
    for style_id in sorted(items):
        if signature_status(style_id, items[style_id]) not in status_values:
            continue
        _, body = validate_signature_item(style_id, items[style_id])
        selected.append((style_id, body))
    if not selected:
        raise ValueError("no artist signatures matched the requested statuses")

    rows: list[dict[str, Any]] = []
    for style_id, body in selected:
        prompt = f"{FIXED_SCENE} Apply these observable visual properties: {body} {CATALOG_QUALITY_SUFFIX}"
        for seed in seed_values:
            row = {
                "schema_version": 1,
                "test_id": f"VS{len(rows) + 1:06d}",
                "style_id": style_id,
                "label": style_id,
                "mode": "visual_signature",
                "seed": seed,
                "prompt": prompt,
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
    args = parser.parse_args()

    try:
        seeds = validate_seeds(args.seed or DEFAULT_SEEDS)
        statuses = validate_statuses(args.status or DEFAULT_STATUSES)
        rows = signature_rows(args.catalog, seeds, statuses=statuses)
        write_jsonl(args.output, rows)
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
