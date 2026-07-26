#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def merge_rows(paths: list[Path]) -> tuple[list[str], list[dict[str, str]]]:
    fields: list[str] | None = None
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, int]] = set()
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"scorecard has no header: {path}")
            if fields is None:
                fields = reader.fieldnames
            elif reader.fieldnames != fields:
                raise ValueError(f"scorecard headers do not match: {path}")
            for line_number, row in enumerate(reader, start=2):
                style_id = (row.get("style_id") or "").strip()
                try:
                    seed = int((row.get("seed") or "").strip())
                except ValueError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid seed") from exc
                identity = (style_id, seed)
                if not style_id or identity in seen:
                    raise ValueError(f"{path}:{line_number}: missing or duplicate style and seed")
                seen.add(identity)
                rows.append(row)
    if fields is None or not rows:
        raise ValueError("no scorecard rows were loaded")
    rows.sort(key=lambda row: (row["style_id"], int(row["seed"])))
    return fields, rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge scored benchmark CSVs without duplicates")
    parser.add_argument("scorecards", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        fields, rows = merge_rows(args.scorecards)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Merged {len(rows)} unique scorecard row(s) into {args.output}.")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
