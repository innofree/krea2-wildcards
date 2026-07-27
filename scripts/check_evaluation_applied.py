#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from apply_evaluation_summary import (
    ALLOWED_RECOMMENDATIONS,
    PERSISTED_METRICS,
    validated_prompt_digest,
)
from common import load_yaml


def validate_applied_evaluation(
    summary: dict[str, Any],
    catalog: dict[str, Any],
    evaluation_id: str,
) -> int:
    items = catalog.get("items")
    styles = summary.get("styles")
    if not isinstance(items, dict) or not isinstance(styles, list) or not styles:
        raise ValueError("catalog items and summary styles are required")
    if summary.get("style_count") not in (None, len(styles)):
        raise ValueError("summary style_count does not match summary styles")

    summary_ids: set[str] = set()
    for result in styles:
        if not isinstance(result, dict) or not isinstance(result.get("style_id"), str):
            raise ValueError("summary style entries must be mappings with style_id")
        style_id = result["style_id"]
        if style_id in summary_ids:
            raise ValueError(f"duplicate summary style: {style_id}")
        summary_ids.add(style_id)
        item = items.get(style_id)
        if not isinstance(item, dict) or not isinstance(item.get("validation"), dict):
            raise ValueError(f"summary style is missing from catalog: {style_id}")
        validation = item["validation"]
        digest = validated_prompt_digest(item, result, style_id=style_id)
        recommendation = result.get("recommended_status")
        tested_seeds = result.get("tested_seeds")
        critical_failures = result.get("critical_failures")
        averages = result.get("averages")
        if recommendation not in ALLOWED_RECOMMENDATIONS:
            raise ValueError(f"summary style {style_id!r} has invalid recommendation")
        if (
            not isinstance(tested_seeds, int)
            or tested_seeds < 1
            or not isinstance(critical_failures, int)
            or critical_failures < 0
            or not isinstance(averages, dict)
        ):
            raise ValueError(
                f"summary style {style_id!r} has invalid evaluation values"
            )
        expected = {
            "tested_seeds": tested_seeds,
            "status": recommendation,
            "last_evaluation": evaluation_id,
            "evaluated_prompt_sha256": digest,
            **{metric: averages[metric] for metric in PERSISTED_METRICS},
            "critical_failures": critical_failures,
        }
        for key, value in expected.items():
            if validation.get(key) != value:
                raise ValueError(
                    f"catalog style {style_id!r} does not contain the exact applied "
                    f"evaluation value for {key!r}"
                )

    evaluation_ids = {
        style_id
        for style_id, item in items.items()
        if isinstance(item, dict)
        and isinstance(item.get("validation"), dict)
        and item["validation"].get("last_evaluation") == evaluation_id
    }
    if evaluation_ids != summary_ids:
        raise ValueError(
            "catalog evaluation-id set does not exactly match summary styles "
            f"(missing={len(summary_ids - evaluation_ids)}, "
            f"unexpected={len(evaluation_ids - summary_ids)})"
        )
    return len(summary_ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether an evaluation summary is already applied exactly to a catalog"
        )
    )
    parser.add_argument("summary", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--evaluation-id", required=True)
    args = parser.parse_args()
    try:
        summary = load_yaml(args.summary)
        catalog = load_yaml(args.catalog)
        if not isinstance(summary, dict) or not isinstance(catalog, dict):
            raise ValueError("summary and catalog must be mappings")
        count = validate_applied_evaluation(
            summary,
            catalog,
            args.evaluation_id,
        )
        print(
            f"Evaluation {args.evaluation_id} is already applied exactly "
            f"to {count} catalog style(s)."
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"NOT APPLIED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
