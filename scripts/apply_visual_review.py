#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from common import load_yaml
from summarize_results import METRICS, parse_boolean, parse_metric


def load_review(path: Path) -> dict[str, dict[str, Any]]:
    document = load_yaml(path)
    styles = document.get("styles") if isinstance(document, dict) else None
    if not isinstance(styles, dict) or not styles:
        raise ValueError("visual review styles must be a non-empty mapping")
    validated: dict[str, dict[str, Any]] = {}
    for style_id, review in styles.items():
        if not isinstance(style_id, str) or not isinstance(review, dict):
            raise ValueError("visual review entries must use string style IDs")
        metrics = review.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"review {style_id!r} is missing metrics")
        values = {
            metric: parse_metric(metrics.get(metric), field=f"{style_id}.{metric}")
            for metric in METRICS
        }
        values["critical_failure"] = parse_boolean(
            review.get("critical_failure"), field=f"{style_id}.critical_failure"
        )
        notes = review.get("notes")
        if not isinstance(notes, str) or not notes.strip():
            raise ValueError(f"review {style_id!r} is missing notes")
        values["notes"] = notes.strip()
        validated[style_id] = values
    return validated


def apply_review(
    rows: list[dict[str, str]],
    reviews: dict[str, dict[str, Any]],
    *,
    allow_extra_reviews: bool = False,
) -> None:
    scorecard_styles = {(row.get("style_id") or "").strip() for row in rows}
    missing = sorted(scorecard_styles - set(reviews))
    extra = sorted(set(reviews) - scorecard_styles)
    if missing or (extra and not allow_extra_reviews):
        raise ValueError(f"visual review coverage mismatch; missing={missing}, extra={extra}")
    for row in rows:
        style_id = row["style_id"].strip()
        review = reviews[style_id]
        for metric in METRICS:
            row[metric] = str(int(review[metric]))
        row["critical_failure"] = str(review["critical_failure"]).lower()
        row["notes"] = review["notes"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply style-level visual review to a scorecard")
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-extra-reviews", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        with args.scorecard.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fields = reader.fieldnames
        if not fields:
            raise ValueError("scorecard has no header")
        required = {"style_id", *METRICS, "critical_failure", "notes"}
        if not required.issubset(fields):
            raise ValueError("scorecard is missing review columns")
        apply_review(
            rows,
            load_review(args.review),
            allow_extra_reviews=args.allow_extra_reviews,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Applied {len(rows)} reviewed score(s) to {args.output}.")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
