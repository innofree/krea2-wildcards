#!/usr/bin/env python3
"""Render sibling-value pairs at contact-sheet scale to test discriminability.

Calibration answers a different question than sheet review does. Calibration
picks maximally separated combinations and asks "does the axis respond at all";
sheet review asks "can I tell this value from its siblings". Every Phase 7 axis
so far was calibrated the first way and reviewed the second way, so sibling
discriminability was never measured.

This probe closes that gap. Given a pair of values on the same feature axis, it
finds catalog items that differ in *only* that axis -- every other feature value
held identical -- and renders them adjacently at the same cell size the reviewer
will actually see. If two siblings are indistinguishable at that size, the sheet
verdict for that axis is not trustworthy and has to be narrowed or escalated,
whatever the calibration suggested.

Cell size is the point of the exercise, so it is an explicit argument rather
than a consequence of sheet height: pass the size the review display produces.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_catalog_items(path: Path) -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, dict):
        raise ValueError(f"{path} does not contain an item mapping")
    return items


def feature_signature(item: dict[str, Any], *, without: str) -> tuple[tuple[str, str], ...]:
    """The item's feature values with one axis removed, as a comparable key."""
    feature_axes = item.get("feature_axes")
    if not isinstance(feature_axes, dict):
        raise ValueError("item has no feature_axes mapping")
    signature: list[tuple[str, str]] = []
    for axis, raw in sorted(feature_axes.items()):
        if axis == without:
            continue
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        signature.append((axis, "+".join(str(value) for value in values)))
    return tuple(signature)


def axis_value(item: dict[str, Any], axis: str) -> str | None:
    feature_axes = item.get("feature_axes") or {}
    raw = feature_axes.get(axis)
    if raw is None:
        return None
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    joined = "+".join(str(value) for value in values)
    return joined or None


def find_matched_pairs(
    items: dict[str, dict[str, Any]], axis: str, left: str, right: str
) -> list[tuple[str, str]]:
    """Item pairs differing only in `axis`, one holding `left` and one `right`."""
    by_signature: dict[tuple[tuple[str, str], ...], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item_id, item in items.items():
        value = axis_value(item, axis)
        if value not in (left, right):
            continue
        by_signature[feature_signature(item, without=axis)][value].append(item_id)

    pairs: list[tuple[str, str]] = []
    for buckets in by_signature.values():
        for left_id, right_id in zip(sorted(buckets.get(left, [])), sorted(buckets.get(right, []))):
            pairs.append((left_id, right_id))
    return sorted(pairs)


def load_scorecard_images(path: Path) -> dict[str, list[tuple[int, Path]]]:
    frames: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"style_id", "seed", "image_path"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f"{path} is missing {sorted(required)}")
        for line_number, raw in enumerate(reader, start=2):
            image = ROOT / (raw["image_path"] or "").strip()
            if not image.is_file():
                raise ValueError(f"line {line_number}: missing image {raw['image_path']}")
            frames[(raw["style_id"] or "").strip()].append((int(raw["seed"]), image))
    return {style_id: sorted(seeds) for style_id, seeds in frames.items()}


def render_probe(
    pairs: list[tuple[str, str]],
    frames: dict[str, list[tuple[int, Path]]],
    output: Path,
    *,
    axis: str,
    left: str,
    right: str,
    cell: int,
    seed_index: int,
) -> int:
    montage = shutil.which("montage")
    if montage is None:
        raise RuntimeError("ImageMagick montage is required")

    usable = [
        (left_id, right_id)
        for left_id, right_id in pairs
        if len(frames.get(left_id, ())) > seed_index
        and len(frames.get(right_id, ())) > seed_index
    ]
    if not usable:
        raise ValueError(
            f"no {left}/{right} pair has a rendered frame at seed index {seed_index}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sibling-probe-", dir=output.parent) as name:
        temp = Path(name)
        inputs: list[str] = []
        # Left and right alternate along each row, so the eye compares the pair
        # directly instead of comparing two blocks from memory.
        for index, (left_id, right_id) in enumerate(usable, start=1):
            for side, item_id in ((left, left_id), (right, right_id)):
                link = temp / f"{index:02d}_{side}.png"
                link.symlink_to(frames[item_id][seed_index][1])
                inputs.append(str(link))
        result = subprocess.run(
            [
                montage,
                "-label",
                "%t",
                *inputs,
                "-thumbnail",
                f"{cell}x{cell}",
                "-tile",
                "2x",
                "-geometry",
                "+6+20",
                "-background",
                "#1f1f1f",
                "-fill",
                "white",
                "-title",
                f"{axis}: {left} (left) vs {right} (right)  cell={cell}px",
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"probe rendering failed for {axis} {left}/{right}")
    return len(usable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--scorecard", type=Path, required=True)
    parser.add_argument("--axis", required=True, help="feature axis holding the pair")
    parser.add_argument("--pair", required=True, help="two sibling values, comma separated")
    parser.add_argument(
        "--cell",
        type=int,
        required=True,
        help="cell size in pixels; pass the size the review display actually produces",
    )
    parser.add_argument("--seed-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=6, help="pairs to render")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    left, _, right = (part.strip() for part in args.pair.partition(","))
    if not left or not right or left == right:
        print("ERROR: --pair needs two distinct comma-separated values")
        return 1
    if args.cell < 1 or args.limit < 1 or args.seed_index < 0:
        print("ERROR: --cell and --limit must be positive and --seed-index non-negative")
        return 1

    try:
        items = load_catalog_items(args.catalog)
        pairs = find_matched_pairs(items, args.axis, left, right)
        if not pairs:
            print(
                f"ERROR: no item pair differs only in {args.axis} between "
                f"{left} and {right}"
            )
            return 1
        frames = load_scorecard_images(args.scorecard)
        rendered = render_probe(
            pairs[: args.limit],
            frames,
            args.output,
            axis=args.axis,
            left=left,
            right=right,
            cell=args.cell,
            seed_index=args.seed_index,
        )
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}")
        return 1

    print(
        f"wrote {args.output}: {rendered} matched pair(s) of {len(pairs)} available, "
        f"{args.axis} {left} vs {right} at {args.cell}px"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
