#!/usr/bin/env python3
"""Emit the expected sub-attributes for each contact sheet, in sheet order.

A sheet reviewer reads a grid of thumbnails and has to decide whether each item
renders the attribute it was built for. Reading that attribute off the item name
in the montage label does not work: the label carries only the alias and seed,
so the attribute has to come from the catalog. Guessing it from the item's
position on the sheet is worse still, and it has already produced two wrong
verdicts in this phase -- a pose case judged as `low_kneeling` was actually
`measured_walking_pause` and rendered correctly.

This crib pairs each alias with its catalog feature axes so the verdict is made
against the ground truth rather than against a recollection of it. Sheet
membership is taken from the review manifest's per-sheet `case_aliases`, which
is authoritative: under --spread-cases a sheet holds a strided selection that
the alias numbering alone cannot reconstruct.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

MANIFEST_KIND = "resolved_prompt_matrix_contact_sheet_review"


def load_manifest(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != MANIFEST_KIND:
        raise ValueError(f"{path} is not a prompt-matrix contact sheet review manifest")
    for key in ("sheets", "cases"):
        if not isinstance(document.get(key), list):
            raise ValueError(f"{path} is missing its {key} list")
    for sheet in document["sheets"]:
        if not isinstance(sheet.get("case_aliases"), list):
            raise ValueError(
                f"{path} predates per-sheet case_aliases; rebuild the sheets so the "
                "crib cannot be paired with the wrong cases"
            )
    return document


def load_catalog_items(path: Path) -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, dict):
        raise ValueError(f"{path} does not contain an item mapping")
    return items


def attribute_columns(items: dict[str, dict[str, Any]], style_ids: list[str]) -> list[str]:
    """Column order is the catalog's own feature-axis order, deduplicated."""
    columns: list[str] = []
    for style_id in style_ids:
        feature_axes = items[style_id].get("feature_axes")
        if not isinstance(feature_axes, dict):
            raise ValueError(f"{style_id} has no feature_axes mapping")
        for axis in feature_axes:
            if axis not in columns:
                columns.append(axis)
    return columns


def attribute_values(item: dict[str, Any], columns: list[str]) -> list[str]:
    feature_axes = item.get("feature_axes") or {}
    values: list[str] = []
    for axis in columns:
        raw = feature_axes.get(axis)
        if raw is None:
            values.append("-")
        elif isinstance(raw, (list, tuple)):
            values.append("+".join(str(value) for value in raw) or "-")
        else:
            values.append(str(raw))
    return values


def render_crib(
    manifest: dict[str, Any],
    items: dict[str, dict[str, Any]],
    *,
    excluded: tuple[str, ...] = (),
    sheets: tuple[int, ...] | None = None,
) -> str:
    style_by_alias = {case["alias"]: case["style_id"] for case in manifest["cases"]}
    missing = sorted(set(style_by_alias.values()) - set(items))
    if missing:
        raise ValueError(
            f"{len(missing)} manifest case(s) are absent from the catalog, "
            f"starting with {missing[0]}"
        )
    columns = attribute_columns(items, list(style_by_alias.values()))
    unknown = [axis for axis in excluded if axis not in columns]
    if unknown:
        raise ValueError(f"excluded axes are not catalog feature axes: {unknown}")

    headers = [
        axis + (" [EXCLUDED]" if axis in excluded else "") for axis in columns
    ]
    widths = [len(header) for header in headers]
    for style_id in style_by_alias.values():
        for position, value in enumerate(attribute_values(items[style_id], columns)):
            widths[position] = max(widths[position], len(value))
    alias_width = max((len(alias) for alias in style_by_alias), default=5)

    lines: list[str] = []
    if excluded:
        lines.append(
            "Excluded from the sheet verdict (not readable at this density): "
            + ", ".join(excluded)
        )
        lines.append("")

    for sheet in manifest["sheets"]:
        index = sheet["sheet_index"]
        if sheets is not None and index not in sheets:
            continue
        lines.append(
            f"## sheet {index:03d}  ({sheet['case_count']} cases)  {sheet['path']}"
        )
        lines.append(
            f"{'alias':<{alias_width}}  "
            + "  ".join(
                f"{header:<{width}}" for header, width in zip(headers, widths)
            )
        )
        for alias in sheet["case_aliases"]:
            values = attribute_values(items[style_by_alias[alias]], columns)
            lines.append(
                f"{alias:<{alias_width}}  "
                + "  ".join(
                    f"{value:<{width}}" for value, width in zip(values, widths)
                )
            )
        lines.append("")
    return "\n".join(lines)


def parse_sheets(raw: str | None) -> tuple[int, ...] | None:
    if not raw:
        return None
    selected: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, _, end_raw = part.partition("-")
            start, end = int(start_raw), int(end_raw)
            if start > end:
                raise ValueError(f"sheet range is inverted: {part}")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))
    if not selected:
        raise ValueError("no sheets selected")
    return tuple(sorted(selected))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="review/manifest.json")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--exclude-axis",
        action="append",
        default=[],
        help="feature axis that is not readable at this sheet density; it is "
        "marked EXCLUDED rather than dropped, so the omission stays visible",
    )
    parser.add_argument(
        "--sheets", help="sheet selection, e.g. 1-10 or 3,7,11 (default: all)"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        manifest = load_manifest(args.manifest)
        items = load_catalog_items(args.catalog)
        text = render_crib(
            manifest,
            items,
            excluded=tuple(args.exclude_axis),
            sheets=parse_sheets(args.sheets),
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}")
        return 1

    if args.output is None:
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
