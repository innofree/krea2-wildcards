#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from common import load_yaml
from summarize_results import METRICS, parse_boolean, parse_metric


MODES = ("native_name", "visual_signature", "hybrid")


def load_review(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    document = load_yaml(path)
    artists = document.get("artists") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or not isinstance(artists, dict)
        or not artists
    ):
        raise ValueError("A/B/C review must contain schema_version 1 artists")
    reviews: dict[tuple[str, str], dict[str, Any]] = {}
    for artist_id, artist in artists.items():
        modes = artist.get("modes") if isinstance(artist, dict) else None
        if (
            not isinstance(artist_id, str)
            or not isinstance(modes, dict)
            or set(modes) != set(MODES)
        ):
            raise ValueError(
                f"{artist_id!r}: review must contain exactly three A/B/C modes"
            )
        for mode in MODES:
            review = modes[mode]
            metrics = review.get("metrics") if isinstance(review, dict) else None
            if not isinstance(metrics, dict) or set(metrics) != set(METRICS):
                raise ValueError(
                    f"{artist_id}.{mode}: metrics must contain exactly eight scores"
                )
            values: dict[str, Any] = {
                metric: parse_metric(
                    metrics[metric], field=f"{artist_id}.{mode}.{metric}"
                )
                for metric in METRICS
            }
            values["critical_failure"] = parse_boolean(
                review.get("critical_failure"),
                field=f"{artist_id}.{mode}.critical_failure",
            )
            notes = review.get("notes")
            if not isinstance(notes, str) or not notes.strip():
                raise ValueError(f"{artist_id}.{mode}: notes are required")
            values["notes"] = notes.strip()
            reviews[(artist_id, mode)] = values
    return reviews


def apply_review(
    rows: list[dict[str, str]], reviews: dict[tuple[str, str], dict[str, Any]]
) -> None:
    expected = {
        ((row.get("style_id") or "").strip(), (row.get("mode") or "").strip())
        for row in rows
    }
    if any(not artist_id or mode not in MODES for artist_id, mode in expected):
        raise ValueError("scorecard contains an invalid artist or A/B/C mode")
    if expected != set(reviews):
        raise ValueError(
            "A/B/C review coverage mismatch; "
            f"missing={len(expected - set(reviews))}, extra={len(set(reviews) - expected)}"
        )
    for row in rows:
        key = (row["style_id"].strip(), row["mode"].strip())
        review = reviews[key]
        for metric in METRICS:
            row[metric] = str(int(review[metric]))
        row["critical_failure"] = str(review["critical_failure"]).lower()
        row["notes"] = review["notes"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply visual scores to an artist A/B/C scorecard"
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        with args.scorecard.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fields = reader.fieldnames
        if not fields or not rows:
            raise ValueError("scorecard must contain a header and rows")
        required = {"style_id", "mode", *METRICS, "critical_failure", "notes"}
        if not required.issubset(fields):
            raise ValueError("scorecard is missing A/B/C review columns")
        apply_review(rows, load_review(args.review))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Applied A/B/C review to {len(rows)} scorecard row(s).")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
