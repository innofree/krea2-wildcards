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

from bind_artist_prompt_evidence import load_validated_binding
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
SHA256_TOKEN = re.compile(r"^[0-9a-f]{64}$")
FACTOR_SHA256_TOKEN = re.compile(r"^sha256_([0-9a-f]{64})$")


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


def parse_evaluated_prompt_sha256(row: dict[str, Any], *, row_number: int) -> str | None:
    direct = row.get("evaluated_prompt_sha256")
    factors_value = row.get("factors_json")
    factors_digest: Any = None
    if factors_value not in (None, ""):
        if not isinstance(factors_value, str):
            raise ValueError(f"row {row_number}: factors_json must be JSON text")
        try:
            factors = json.loads(factors_value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"row {row_number}: factors_json must be valid JSON"
            ) from exc
        if not isinstance(factors, dict):
            raise ValueError(f"row {row_number}: factors_json must contain an object")
        factors_digest = factors.get("evaluated_prompt_sha256")

    normalized: list[str] = []
    if direct not in (None, ""):
        if not isinstance(direct, str) or not SHA256_TOKEN.fullmatch(direct):
            raise ValueError(
                f"row {row_number}: evaluated_prompt_sha256 must be "
                "64 lowercase hex characters"
            )
        normalized.append(direct)
    if factors_digest not in (None, ""):
        factor_match = (
            FACTOR_SHA256_TOKEN.fullmatch(factors_digest)
            if isinstance(factors_digest, str)
            else None
        )
        if factor_match is None:
            raise ValueError(
                f"row {row_number}: factors evaluated_prompt_sha256 must use "
                "sha256_<64 lowercase hex> format"
            )
        normalized.append(factor_match.group(1))
    if not normalized:
        return None
    if len(set(normalized)) != 1:
        raise ValueError(
            f"row {row_number}: evaluated_prompt_sha256 sources do not match"
        )
    return normalized[0]


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


def validate_rows(
    rows: list[dict[str, Any]],
    *,
    prompt_bindings: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
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
        evaluated_prompt_sha256 = parse_evaluated_prompt_sha256(
            row, row_number=row_number
        )
        if prompt_bindings is not None:
            bound_digest = prompt_bindings.get(style_id)
            if bound_digest is None:
                raise ValueError(
                    f"row {row_number}: style_id is absent from prompt binding"
                )
            if (
                evaluated_prompt_sha256 is not None
                and evaluated_prompt_sha256 != bound_digest
            ):
                raise ValueError(
                    f"row {row_number}: scorecard prompt digest does not match binding"
                )
            evaluated_prompt_sha256 = bound_digest
        if evaluated_prompt_sha256 is not None:
            scorecard["evaluated_prompt_sha256"] = evaluated_prompt_sha256
        validated.append(scorecard)
    return validated


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize scored Krea2 benchmark results")
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tests/reports/summary.json"))
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--prompt-binding",
        type=Path,
        help="validated immutable-matrix to catalog prompt digest binding",
    )
    args = parser.parse_args()

    try:
        prompt_bindings = (
            load_validated_binding(args.prompt_binding)
            if args.prompt_binding is not None
            else None
        )
        rows = validate_rows(read_rows(args.results), prompt_bindings=prompt_bindings)
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
            prompt_digests = {
                row.get("evaluated_prompt_sha256") for row in style_rows
            }
            if None in prompt_digests and len(prompt_digests) > 1:
                raise ValueError(
                    f"style {style_id!r} has incomplete evaluated_prompt_sha256 coverage"
                )
            if len(prompt_digests) > 1:
                raise ValueError(
                    f"style {style_id!r} has inconsistent evaluated_prompt_sha256 values"
                )
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
            result = {
                    "style_id": style_id,
                    "sample_count": len(style_rows),
                    "tested_seeds": len(tested_seeds),
                    "averages": averages,
                    "critical_failures": critical_failures,
                    "recommended_status": recommended_status,
                }
            evaluated_prompt_sha256 = next(iter(prompt_digests))
            if evaluated_prompt_sha256 is not None:
                result["evaluated_prompt_sha256"] = evaluated_prompt_sha256
            summaries.append(result)
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
