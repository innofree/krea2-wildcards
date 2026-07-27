#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from apply_artist_abc_review import MODES, load_review
from common import dump_yaml
from summarize_results import METRICS


def scorecard_artist_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        values = {(row.get("style_id") or "").strip() for row in csv.DictReader(handle)}
    values.discard("")
    if not values:
        raise ValueError("expected scorecard contains no artist IDs")
    return values


def merge_reviews(
    paths: list[Path], expected: set[str] | None = None
) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one A/B/C review is required")

    artists: dict[str, dict[str, Any]] = {}
    for path in paths:
        reviews = load_review(path)
        part_artists = {artist_id for artist_id, _ in reviews}
        duplicate = sorted(set(artists) & part_artists)
        if duplicate:
            raise ValueError(f"duplicate reviewed artists: {duplicate}")

        for artist_id in sorted(part_artists):
            modes: dict[str, Any] = {}
            for mode in MODES:
                values = reviews[(artist_id, mode)]
                modes[mode] = {
                    "metrics": {
                        metric: int(values[metric]) for metric in METRICS
                    },
                    "critical_failure": bool(values["critical_failure"]),
                    "notes": values["notes"],
                }
            artists[artist_id] = {"modes": modes}

    if expected is not None and set(artists) != expected:
        missing = sorted(expected - set(artists))
        extra = sorted(set(artists) - expected)
        raise ValueError(
            f"A/B/C review coverage mismatch; missing={missing}, extra={extra}"
        )

    return {
        "schema_version": 1,
        "review_method": "partitioned_artist_abc_contact_sheet_review",
        "reviewer_parts": [path.as_posix() for path in paths],
        "artists": {
            artist_id: artists[artist_id] for artist_id in sorted(artists)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge partitioned artist A/B/C reviews exactly once"
    )
    parser.add_argument("reviews", nargs="+", type=Path)
    parser.add_argument("--expected-scorecard", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        expected = (
            scorecard_artist_ids(args.expected_scorecard)
            if args.expected_scorecard
            else None
        )
        document = merge_reviews(args.reviews, expected)
        dump_yaml(document, args.output)
        print(
            f"Merged {len(document['artists'])} unique artist A/B/C "
            f"review(s) into {args.output}."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
