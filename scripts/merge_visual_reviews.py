#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from apply_visual_review import load_review
from common import dump_yaml, load_yaml
from summarize_results import METRICS


def scorecard_style_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        values = {(row.get("style_id") or "").strip() for row in csv.DictReader(handle)}
    values.discard("")
    if not values:
        raise ValueError("expected scorecard contains no style IDs")
    return values


def merge_reviews(paths: list[Path], expected: set[str] | None = None) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one visual review is required")
    merged: dict[str, Any] = {}
    for path in paths:
        document = load_yaml(path)
        raw_styles = document.get("styles") if isinstance(document, dict) else None
        if not isinstance(raw_styles, dict) or not raw_styles:
            raise ValueError(f"visual review has no styles: {path}")
        validated = load_review(path)
        duplicate = sorted(set(merged) & set(validated))
        if duplicate:
            raise ValueError(f"duplicate reviewed styles: {duplicate}")
        for style_id, values in validated.items():
            raw = raw_styles[style_id]
            review = {
                "metrics": {metric: int(values[metric]) for metric in METRICS},
                "critical_failure": bool(values["critical_failure"]),
                "notes": values["notes"],
            }
            recommendation = raw.get("recommendation")
            if isinstance(recommendation, str) and recommendation.strip():
                review["recommendation"] = recommendation.strip()
            merged[style_id] = review
    if expected is not None and set(merged) != expected:
        missing = sorted(expected - set(merged))
        extra = sorted(set(merged) - expected)
        raise ValueError(f"visual review coverage mismatch; missing={missing}, extra={extra}")
    return {
        "schema_version": 1,
        "review_method": "partitioned_contact_sheet_visual_review",
        "reviewer_parts": [path.as_posix() for path in paths],
        "styles": {style_id: merged[style_id] for style_id in sorted(merged)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge partitioned visual reviews exactly once")
    parser.add_argument("reviews", nargs="+", type=Path)
    parser.add_argument("--expected-scorecard", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        expected = (
            scorecard_style_ids(args.expected_scorecard) if args.expected_scorecard else None
        )
        document = merge_reviews(args.reviews, expected)
        dump_yaml(document, args.output)
        print(f"Merged {len(document['styles'])} unique visual review(s) into {args.output}.")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
