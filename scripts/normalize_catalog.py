#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import canonical_id, dump_yaml, iter_catalog_files, load_yaml


def normalize_document(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    changes: list[str] = []
    items = data.get("items", {})
    normalized_items: dict[str, Any] = {}
    for original_id, item in items.items():
        normalized_id = canonical_id(str(original_id))
        if not normalized_id:
            raise ValueError(f"cannot normalize empty item id: {original_id!r}")
        if normalized_id in normalized_items:
            raise ValueError(f"item id collision after normalization: {normalized_id}")
        if normalized_id != original_id:
            changes.append(f"id {original_id!r} -> {normalized_id!r}")

        if isinstance(item, dict):
            aliases = item.get("aliases")
            if isinstance(aliases, list):
                cleaned = sorted(
                    {str(alias).strip().lower() for alias in aliases if str(alias).strip()}
                )
                if cleaned != aliases:
                    item = dict(item)
                    item["aliases"] = cleaned
                    changes.append(f"normalized aliases for {normalized_id}")
            runtime = item.get("runtime")
            if isinstance(runtime, dict) and isinstance(runtime.get("path"), list):
                path = list(runtime["path"])
                if path and path[-1] != normalized_id:
                    item = dict(item)
                    runtime = dict(runtime)
                    runtime["path"] = [*path[:-1], normalized_id]
                    item["runtime"] = runtime
                    changes.append(f"normalized runtime path for {normalized_id}")
        normalized_items[normalized_id] = item

    output = dict(data)
    output["items"] = dict(sorted(normalized_items.items()))
    return output, changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize catalog IDs and aliases")
    parser.add_argument("catalog", nargs="?", type=Path, default=Path("catalog"))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    all_changes: list[str] = []
    try:
        for path in iter_catalog_files(args.catalog):
            data = load_yaml(path)
            normalized, changes = normalize_document(data)
            all_changes.extend(f"{path}: {change}" for change in changes)
            if changes and args.write:
                dump_yaml(normalized, path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    for change in all_changes:
        print(change)
    if all_changes and not args.write:
        print(f"ERROR: {len(all_changes)} normalization change(s) required")
        return 1
    print(f"Catalog normalization OK ({len(all_changes)} change(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
