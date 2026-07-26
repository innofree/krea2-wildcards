#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import load_yaml


def conflict_pairs(data: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    conflicts = data.get("conflicts", {})
    if not isinstance(conflicts, dict):
        raise ValueError("conflicts must be a mapping")
    for left, right_values in conflicts.items():
        if not isinstance(right_values, list):
            raise ValueError(f"conflicts.{left} must be a list")
        for right in right_values:
            if not isinstance(right, str):
                raise ValueError(f"conflicts.{left} contains a non-string value")
            pairs.add(tuple(sorted((str(left), right))))
    return pairs


def find_conflicts(ids: set[str], pairs: set[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(pair for pair in pairs if set(pair) <= ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a set of wildcard IDs for conflicts")
    parser.add_argument(
        "--catalog", type=Path, default=Path("catalog/compatibility.yaml")
    )
    parser.add_argument("--ids", nargs="*", default=[])
    args = parser.parse_args()

    try:
        data = load_yaml(args.catalog)
        if not isinstance(data, dict):
            raise ValueError("compatibility catalog must be a mapping")
        pairs = conflict_pairs(data)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    if not args.ids:
        print(f"OK: loaded {len(pairs)} normalized conflict pair(s).")
        return 0
    found = find_conflicts(set(args.ids), pairs)
    for left, right in found:
        print(f"CONFLICT: {left} + {right}")
    if found:
        return 1
    print(f"OK: no conflicts among {len(set(args.ids))} ID(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
