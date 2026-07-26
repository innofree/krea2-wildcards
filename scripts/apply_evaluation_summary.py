#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import Any

from common import dump_yaml, load_yaml


PERSISTED_METRICS = (
    "prompt_adherence",
    "style_fidelity",
    "stability",
    "compatibility",
)
ALLOWED_RECOMMENDATIONS = {"generated", "testing", "approved", "rejected"}


def update_catalog(
    catalog: dict[str, Any],
    summary: dict[str, Any],
    evaluation_id: str,
    allowed_from: set[str],
) -> int:
    items = catalog.get("items")
    styles = summary.get("styles")
    if not isinstance(items, dict) or not isinstance(styles, list) or not styles:
        raise ValueError("catalog items and summary styles are required")
    seen: set[str] = set()
    for result in styles:
        if not isinstance(result, dict) or not isinstance(result.get("style_id"), str):
            raise ValueError("summary style entries must be mappings with style_id")
        style_id = result["style_id"]
        if style_id in seen:
            raise ValueError(f"duplicate summary style: {style_id}")
        seen.add(style_id)
        item = items.get(style_id)
        if not isinstance(item, dict) or not isinstance(item.get("validation"), dict):
            raise ValueError(f"summary style is missing from catalog: {style_id}")
        validation = item["validation"]
        current_status = validation.get("status")
        if current_status not in allowed_from:
            raise ValueError(
                f"catalog style {style_id!r} has disallowed source status {current_status!r}"
            )
        recommended = result.get("recommended_status")
        if recommended not in ALLOWED_RECOMMENDATIONS:
            raise ValueError(f"summary style {style_id!r} has invalid recommendation")
        tested_seeds = result.get("tested_seeds")
        critical_failures = result.get("critical_failures")
        averages = result.get("averages")
        if (
            not isinstance(tested_seeds, int)
            or tested_seeds < 1
            or not isinstance(critical_failures, int)
            or critical_failures < 0
            or not isinstance(averages, dict)
        ):
            raise ValueError(f"summary style {style_id!r} has invalid evaluation values")
        validation.update(
            {
                "tested_seeds": tested_seeds,
                "status": recommended,
                "last_evaluation": evaluation_id,
                **{metric: averages[metric] for metric in PERSISTED_METRICS},
                "critical_failures": critical_failures,
            }
        )
    return len(seen)


def atomic_dump_yaml(document: dict[str, Any], path: Path) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        dump_yaml(document, temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply validated evaluation status to a catalog")
    parser.add_argument("summary", type=Path)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/art_styles.yaml"))
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--from-status", action="append", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        catalog = load_yaml(args.catalog)
        summary = load_yaml(args.summary)
        if not isinstance(catalog, dict) or not isinstance(summary, dict):
            raise ValueError("catalog and summary must be mappings")
        count = update_catalog(
            catalog,
            summary,
            args.evaluation_id,
            set(args.from_status or ["generated"]),
        )
        if args.apply:
            atomic_dump_yaml(catalog, args.catalog)
            print(f"Applied evaluation {args.evaluation_id} to {count} catalog style(s).")
        else:
            print(f"DRY RUN: evaluation {args.evaluation_id} would update {count} catalog style(s).")
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
