#!/usr/bin/env python3
"""Rank an axis run's items by saturation against their own feature-axis peers.

plan.md 7.18 held 35 catalog items after seeing three of them render greyscale,
then 7.35 found the collapse was the rig rather than the coloring value. Both
readings came from paging contact sheets, and neither could have been settled
that way: a sheet thumbnail is too small to judge saturation, and the eye has no
baseline to compare a palette against.

This gives the reviewer that baseline. It groups every item by one feature axis --
coloring, say -- and reports how far each item sits from its own group's median.
A palette that is meant to be muted has a low median and no outliers; a palette
that collapsed on some pairings has a normal median and a tail well below it.
Neither is visible from an absolute number, which is why Stage A records mean
saturation without judging it.

Nothing here is a verdict. The output is a shortlist worth opening at full size.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

from common import load_yaml

from audit_phase7_stage_a import mean_saturation


def load_rows(scorecard: Path) -> list[dict[str, str]]:
    with scorecard.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"scorecard has no rows: {scorecard}")
    required = {"style_id", "seed", "image_path"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"scorecard is missing columns: {sorted(missing)}")
    return rows


def feature_value(item: dict[str, Any], axis: str) -> str | None:
    values = (item.get("feature_axes") or {}).get(axis)
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def screen(
    scorecard: Path,
    catalog: Path,
    *,
    group_axis: str,
    root: Path,
    deviation: float,
) -> dict[str, Any]:
    items = load_yaml(catalog)["items"]
    rows = load_rows(scorecard)

    # One score per item: the mean across its seeds, so a single unlucky seed
    # does not put an otherwise sound item on the shortlist.
    per_item: dict[str, list[float]] = {}
    for row in rows:
        path = root / row["image_path"]
        if not path.is_file():
            raise ValueError(f"scorecard references a missing image: {path}")
        per_item.setdefault(row["style_id"], []).append(mean_saturation(path))

    groups: dict[str, list[tuple[str, float]]] = {}
    ungrouped: list[str] = []
    for item_id, samples in sorted(per_item.items()):
        item = items.get(item_id)
        value = feature_value(item, group_axis) if isinstance(item, dict) else None
        if value is None:
            ungrouped.append(item_id)
            continue
        groups.setdefault(value, []).append(
            (item_id, round(statistics.fmean(samples), 4))
        )

    report: dict[str, Any] = {
        "scorecard": scorecard.as_posix(),
        "catalog": catalog.as_posix(),
        "group_axis": group_axis,
        "deviation": deviation,
        "item_count": len(per_item),
        "ungrouped_item_ids": sorted(ungrouped),
        "groups": [],
    }
    for value, scored in sorted(groups.items()):
        readings = [score for _, score in scored]
        median = statistics.median(readings)
        floor = median * (1.0 - deviation)
        outliers = sorted(
            (
                {
                    "item_id": item_id,
                    "mean_saturation": score,
                    "fraction_of_median": round(score / median, 3) if median else None,
                }
                for item_id, score in scored
                if score < floor
            ),
            key=lambda entry: entry["mean_saturation"],
        )
        report["groups"].append(
            {
                "value": value,
                "item_count": len(scored),
                "median_saturation": round(median, 4),
                "min_saturation": round(min(readings), 4),
                "max_saturation": round(max(readings), 4),
                "outlier_count": len(outliers),
                "outliers": outliers,
            }
        )
    report["outlier_total"] = sum(g["outlier_count"] for g in report["groups"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shortlist axis items whose saturation is low for their own feature group"
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--group-axis",
        default="coloring",
        help="feature axis to group by before comparing (default: coloring)",
    )
    parser.add_argument(
        "--deviation",
        type=float,
        default=0.5,
        help="shortlist items below this fraction of their group median (default: 0.5)",
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = screen(
            args.scorecard,
            args.catalog,
            group_axis=args.group_axis,
            root=args.root,
            deviation=args.deviation,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    for group in report["groups"]:
        flag = f"  <-- {group['outlier_count']} outlier(s)" if group["outlier_count"] else ""
        print(
            f"{group['value']:26s} n={group['item_count']:3d} "
            f"median={group['median_saturation']:.4f} "
            f"range=[{group['min_saturation']:.4f}, {group['max_saturation']:.4f}]{flag}"
        )
    print(
        f"\n{report['outlier_total']} item(s) below {args.deviation:.0%} of their group median"
        f" across {report['item_count']} item(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
