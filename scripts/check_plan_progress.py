#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import item_status, load_yaml


DEFAULT_ROADMAP = Path("catalog/roadmap.yaml")
DEFAULT_CATALOG = Path("catalog")


def catalog_items(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    data = load_yaml(path)
    items = data.get("items", {}) if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        raise ValueError(f"{path}: items must be a mapping")
    return {key: value for key, value in items.items() if isinstance(value, dict)}


def target_items(catalog_root: Path, catalog_names: list[str]) -> dict[str, dict[str, Any]]:
    paths = (
        sorted(catalog_root.glob("*.yaml"))
        if catalog_names == ["*"]
        else [catalog_root / name for name in catalog_names]
    )
    combined: dict[str, dict[str, Any]] = {}
    for path in paths:
        for item_id, item in catalog_items(path).items():
            unique_id = f"{path.name}:{item_id}"
            combined[unique_id] = item
    return combined


def collect_progress(roadmap_path: Path, catalog_root: Path) -> dict[str, Any]:
    roadmap = load_yaml(roadmap_path)
    targets = roadmap.get("content_targets", {}) if isinstance(roadmap, dict) else {}
    if not isinstance(targets, dict):
        raise ValueError("roadmap content_targets must be a mapping")

    results = []
    for target_id, config in targets.items():
        if not isinstance(config, dict):
            raise ValueError(f"roadmap target {target_id!r} must be a mapping")
        catalog_names = config.get("catalogs")
        target = config.get("target")
        metric = config.get("metric")
        if (
            not isinstance(catalog_names, list)
            or not all(isinstance(name, str) for name in catalog_names)
            or not isinstance(target, int)
            or target <= 0
            or metric not in {"items", "status"}
        ):
            raise ValueError(f"roadmap target {target_id!r} has invalid configuration")
        items = target_items(catalog_root, catalog_names)
        if metric == "status":
            expected_status = config.get("status")
            current = sum(item_status(item) == expected_status for item in items.values())
        else:
            current = len(items)
        results.append(
            {
                "id": target_id,
                "label": config.get("label", target_id),
                "current": current,
                "target": target,
                "remaining": max(target - current, 0),
                "percent": round(min(current / target * 100, 100), 1),
                "complete": current >= target,
            }
        )
    return {
        "schema_version": 1,
        "complete": all(result["complete"] for result in results),
        "targets": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Report plan.md catalog completion progress")
    parser.add_argument("--roadmap", type=Path, default=DEFAULT_ROADMAP)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="fail while any target is incomplete")
    args = parser.parse_args()

    try:
        progress = collect_progress(args.roadmap, args.catalog)
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    for result in progress["targets"]:
        print(
            f"{result['id']}: {result['current']}/{result['target']} "
            f"({result['percent']:.1f}%, remaining {result['remaining']})"
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.strict and not progress["complete"]:
        print("ERROR: one or more plan content targets remain incomplete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
