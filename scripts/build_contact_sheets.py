#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import load_yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = Path("catalog/art_styles.yaml")


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("review artifacts must remain inside the repository") from exc


def load_catalog_families(path: Path) -> dict[str, str]:
    document = load_yaml(path)
    if not isinstance(document, dict) or not isinstance(document.get("items"), dict):
        raise ValueError("catalog items must be a mapping")
    families: dict[str, str] = {}
    for style_id, item in document["items"].items():
        if not isinstance(style_id, str) or not isinstance(item, dict):
            raise ValueError("catalog styles must be mappings with string IDs")
        family = item.get("family")
        if not isinstance(family, str) or not family:
            raise ValueError(f"catalog style {style_id!r} is missing family")
        families[style_id] = family
    return families


def load_scorecard(path: Path, families: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, raw in enumerate(csv.DictReader(handle), start=2):
            style_id = (raw.get("style_id") or "").strip()
            if style_id not in families:
                raise ValueError(f"line {line_number}: unknown style_id")
            try:
                seed = int((raw.get("seed") or "").strip())
            except ValueError as exc:
                raise ValueError(f"line {line_number}: seed must be an integer") from exc
            identity = (style_id, seed)
            if identity in seen:
                raise ValueError(f"line {line_number}: duplicate style_id and seed")
            seen.add(identity)
            raw_image = (raw.get("image_path") or "").strip()
            if not raw_image:
                raise ValueError(f"line {line_number}: image_path is required")
            image = Path(raw_image)
            if not image.is_absolute():
                image = ROOT / image
            relative_image = repo_relative(image)
            if not image.is_file():
                raise ValueError(f"line {line_number}: image is missing")
            rows.append(
                {
                    "style_id": style_id,
                    "seed": seed,
                    "family": families[style_id],
                    "image": image.resolve(),
                    "image_path": relative_image,
                }
            )
    if not rows:
        raise ValueError("scorecard contains no rows")
    return rows


def validate_seed_matrix(rows: list[dict[str, Any]], expected_seeds: int) -> None:
    by_style: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        by_style[row["style_id"]].add(row["seed"])
    incomplete = sorted(
        style_id for style_id, seeds in by_style.items() if len(seeds) != expected_seeds
    )
    if incomplete:
        raise ValueError(
            f"expected exactly {expected_seeds} seeds for every style; incomplete styles: "
            + ", ".join(incomplete)
        )


def render_sheet(
    family: str,
    rows: list[dict[str, Any]],
    output: Path,
    expected_seeds: int,
) -> None:
    montage = shutil.which("montage")
    if montage is None:
        raise RuntimeError("ImageMagick montage is required")
    with tempfile.TemporaryDirectory(prefix="krea2-review-") as temp_name:
        temp = Path(temp_name)
        inputs: list[str] = []
        for row in sorted(rows, key=lambda item: (item["style_id"], item["seed"])):
            link = temp / f"{row['style_id']}__{row['seed']}.png"
            link.symlink_to(row["image"])
            inputs.append(str(link))
        result = subprocess.run(
            [
                montage,
                "-label",
                "%t",
                *inputs,
                "-thumbnail",
                "256x256",
                "-tile",
                f"{expected_seeds}x",
                "-geometry",
                "+8+26",
                "-background",
                "#1f1f1f",
                "-fill",
                "white",
                "-title",
                family,
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"contact sheet rendering failed for family {family}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build family contact sheets for visual review")
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-seeds", type=int, default=3)
    parser.add_argument(
        "--styles-per-sheet",
        type=int,
        default=0,
        help="split large families into bounded sheets; 0 keeps one sheet per family",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        if args.expected_seeds < 1:
            raise ValueError("--expected-seeds must be at least 1")
        if args.styles_per_sheet < 0:
            raise ValueError("--styles-per-sheet cannot be negative")
        families = load_catalog_families(args.catalog)
        rows = load_scorecard(args.scorecard, families)
        validate_seed_matrix(rows, args.expected_seeds)
        output = args.output or args.scorecard.parent / "review"
        repo_relative(output)
        if output.exists() and any(output.iterdir()) and not args.overwrite:
            raise ValueError("review output already exists; pass --overwrite to replace sheets")
        output.mkdir(parents=True, exist_ok=True)

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["family"]].append(row)
        sheet_paths: dict[str, str | list[str]] = {}
        for family, family_rows in sorted(grouped.items()):
            style_ids = sorted({row["style_id"] for row in family_rows})
            chunk_size = args.styles_per_sheet or len(style_ids)
            family_sheets: list[str] = []
            for chunk_index, start in enumerate(range(0, len(style_ids), chunk_size), start=1):
                selected = set(style_ids[start : start + chunk_size])
                chunk_rows = [row for row in family_rows if row["style_id"] in selected]
                suffix = f"_{chunk_index:03d}" if len(style_ids) > chunk_size else ""
                sheet = output / f"{family}{suffix}.png"
                render_sheet(
                    f"{family} {chunk_index}/{(len(style_ids) + chunk_size - 1) // chunk_size}",
                    chunk_rows,
                    sheet,
                    args.expected_seeds,
                )
                family_sheets.append(repo_relative(sheet))
            sheet_paths[family] = family_sheets if args.styles_per_sheet else family_sheets[0]

        manifest = {
            "schema_version": 1,
            "scorecard": repo_relative(args.scorecard),
            "expected_seeds_per_style": args.expected_seeds,
            "style_count": len({row["style_id"] for row in rows}),
            "image_count": len(rows),
            "sheets": sheet_paths,
            "items": [
                {
                    "style_id": row["style_id"],
                    "family": row["family"],
                    "seed": row["seed"],
                    "image_path": row["image_path"],
                }
                for row in sorted(rows, key=lambda item: (item["family"], item["style_id"], item["seed"]))
            ],
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Built {len(sheet_paths)} contact sheet(s) for {manifest['style_count']} styles.")
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
