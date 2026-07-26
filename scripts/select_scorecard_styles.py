#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def style_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        selected = {(row.get("style_id") or "").strip() for row in reader}
    selected.discard("")
    if not selected:
        raise ValueError("reference scorecard contains no style IDs")
    return selected


def select_rows(source: Path, selected: set[str]) -> tuple[list[str], list[dict[str, str]]]:
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("source scorecard has no header")
        rows = [row for row in reader if (row.get("style_id") or "").strip() in selected]
        fields = reader.fieldnames
    found = {(row.get("style_id") or "").strip() for row in rows}
    if found != selected:
        raise ValueError(f"source scorecard is missing selected styles: {sorted(selected - found)}")
    return fields, rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Select scorecard rows by a reference scorecard")
    parser.add_argument("source", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        fields, rows = select_rows(args.source, style_ids(args.reference))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Selected {len(rows)} scorecard row(s) into {args.output}.")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
