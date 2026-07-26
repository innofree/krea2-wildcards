#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import load_yaml


METRICS = (
    "prompt_adherence",
    "style_fidelity",
    "stability",
    "character_quality",
    "composition_quality",
    "compatibility",
    "distinctiveness",
    "prompt_efficiency",
)
DEFAULT_POLICY = Path("catalog/evaluation.yaml")
INTEGER_TOKEN = re.compile(r"^[+-]?\d+$")


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and INTEGER_TOKEN.fullmatch(value.strip()):
        return int(value.strip())
    raise ValueError(f"{field} must be an integer")


def parse_metric(value: Any, *, field: str) -> float:
    if value is None or value == "" or isinstance(value, bool):
        raise ValueError(f"{field} is required and must be numeric from 1 to 5")
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric from 1 to 5") from exc
    if not math.isfinite(score) or not 1 <= score <= 5:
        raise ValueError(f"{field} must be numeric from 1 to 5")
    return score


def parse_boolean(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "true":
            return True
        if token == "false":
            return False
    raise ValueError(f"{field} must be the boolean token true or false")


def validate_policy(policy: Any) -> dict[str, int | float]:
    if not isinstance(policy, dict):
        raise ValueError("approval_policy must be a mapping")

    minimum_pilot_seeds = parse_integer(
        policy.get("minimum_pilot_seeds"), field="minimum_pilot_seeds"
    )
    minimum_approval_seeds = parse_integer(
        policy.get("minimum_approval_seeds"), field="minimum_approval_seeds"
    )
    if minimum_pilot_seeds < 1:
        raise ValueError("minimum_pilot_seeds must be at least 1")
    if minimum_approval_seeds < minimum_pilot_seeds:
        raise ValueError("minimum_approval_seeds must be at least minimum_pilot_seeds")

    validated: dict[str, int | float] = {
        "minimum_pilot_seeds": minimum_pilot_seeds,
        "minimum_approval_seeds": minimum_approval_seeds,
    }
    for key in (
        "minimum_prompt_adherence",
        "minimum_style_fidelity",
        "minimum_stability",
        "minimum_compatibility",
    ):
        validated[key] = parse_metric(policy.get(key), field=key)

    maximum_critical_failures = parse_integer(
        policy.get("maximum_critical_failures"), field="maximum_critical_failures"
    )
    if maximum_critical_failures < 0:
        raise ValueError("maximum_critical_failures must be at least 0")
    validated["maximum_critical_failures"] = maximum_critical_failures
    return validated


def validate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"row {row_number}: scorecard row must be a mapping")

        raw_style_id = row.get("style_id")
        if not isinstance(raw_style_id, str) or not raw_style_id.strip():
            raise ValueError(f"row {row_number}: style_id is required")
        style_id = raw_style_id.strip()

        try:
            seed = parse_integer(row.get("seed"), field="seed")
        except ValueError as exc:
            raise ValueError(f"row {row_number}: {exc}") from exc

        identity = (style_id, seed)
        if identity in seen:
            raise ValueError(
                f"row {row_number}: duplicate scorecard for style_id={style_id!r}, seed={seed}"
            )
        seen.add(identity)

        scorecard: dict[str, Any] = {"style_id": style_id, "seed": seed}
        for metric in METRICS:
            try:
                scorecard[metric] = parse_metric(row.get(metric), field=metric)
            except ValueError as exc:
                raise ValueError(f"row {row_number}: {exc}") from exc
        try:
            scorecard["critical_failure"] = parse_boolean(
                row.get("critical_failure"), field="critical_failure"
            )
        except ValueError as exc:
            raise ValueError(f"row {row_number}: {exc}") from exc
        validated.append(scorecard)
    return validated


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize scored Krea2 benchmark results")
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tests/reports/summary.json"))
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    try:
        rows = validate_rows(read_rows(args.results))
        policy_document = load_yaml(args.policy)
        if not isinstance(policy_document, dict):
            raise ValueError("policy document must be a mapping")
        policy = validate_policy(policy_document.get("approval_policy"))
        minimum_pilot_seeds = int(policy["minimum_pilot_seeds"])
        minimum_approval_seeds = int(policy["minimum_approval_seeds"])
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["style_id"]].append(row)
        summaries = []
        for style_id, style_rows in sorted(grouped.items()):
            tested_seeds = {row["seed"] for row in style_rows}
            averages = {}
            for metric in METRICS:
                values = [row[metric] for row in style_rows]
                averages[metric] = round(sum(values) / len(values), 3)
            critical_failures = sum(row["critical_failure"] for row in style_rows)
            quality_passed = (
                averages["prompt_adherence"] >= policy["minimum_prompt_adherence"]
                and averages["style_fidelity"] >= policy["minimum_style_fidelity"]
                and averages["stability"] >= policy["minimum_stability"]
                and averages["compatibility"] >= policy["minimum_compatibility"]
                and critical_failures <= policy["maximum_critical_failures"]
            )
            approved = len(tested_seeds) >= minimum_approval_seeds and quality_passed
            if len(tested_seeds) < minimum_pilot_seeds:
                recommended_status = "generated"
            elif approved:
                recommended_status = "approved"
            elif quality_passed:
                recommended_status = "testing"
            else:
                recommended_status = "rejected"
            summaries.append(
                {
                    "style_id": style_id,
                    "sample_count": len(style_rows),
                    "tested_seeds": len(tested_seeds),
                    "averages": averages,
                    "critical_failures": critical_failures,
                    "recommended_status": recommended_status,
                }
            )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1

    output = {"schema_version": 1, "style_count": len(summaries), "styles": summaries}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(summaries)} style summaries to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
