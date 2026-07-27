#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from bind_artist_prompt_evidence import (
    file_sha256,
    load_validated_binding_document,
)
from common import canonical_prompt_sha256, dump_yaml, load_yaml


PERSISTED_METRICS = (
    "prompt_adherence",
    "style_fidelity",
    "stability",
    "compatibility",
)
ALLOWED_RECOMMENDATIONS = {"generated", "testing", "approved", "rejected"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validated_prompt_digest(
    item: dict[str, Any], result: dict[str, Any], *, style_id: str
) -> str:
    digest = result.get("evaluated_prompt_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError(
            f"summary style {style_id!r} is missing a valid evaluated_prompt_sha256"
        )
    try:
        current_digest = canonical_prompt_sha256(item.get("prompt"))
    except ValueError as exc:
        raise ValueError(
            f"catalog style {style_id!r} is missing a canonical prompt body"
        ) from exc
    if digest != current_digest:
        raise ValueError(
            f"summary style {style_id!r} evaluated_prompt_sha256 is stale"
        )
    return digest


def validate_summary_prompt_binding(
    summary: dict[str, Any], prompt_bindings: dict[str, str]
) -> None:
    styles = summary.get("styles")
    if not isinstance(styles, list) or not styles:
        raise ValueError("summary styles are required for prompt binding")
    for result in styles:
        if not isinstance(result, dict) or not isinstance(result.get("style_id"), str):
            raise ValueError("summary style entries must be mappings with style_id")
        style_id = result["style_id"]
        bound_digest = prompt_bindings.get(style_id)
        if bound_digest is None:
            raise ValueError(f"summary style {style_id!r} is absent from prompt binding")
        if result.get("evaluated_prompt_sha256") != bound_digest:
            raise ValueError(
                f"summary style {style_id!r} does not match prompt binding"
            )


def validate_transition_gate(
    catalog: dict[str, Any],
    summary: dict[str, Any],
    allowed_from: set[str],
    *,
    require_exact_source_set: bool = False,
    required_tested_seeds: int | None = None,
    allowed_recommendations: set[str] | None = None,
    minimum_recommendations: dict[str, int] | None = None,
) -> dict[str, int]:
    items = catalog.get("items")
    styles = summary.get("styles")
    if not isinstance(items, dict) or not isinstance(styles, list) or not styles:
        raise ValueError("catalog items and summary styles are required")
    if summary.get("style_count") not in (None, len(styles)):
        raise ValueError("summary style_count does not match summary styles")

    summary_ids: set[str] = set()
    recommendation_counts: dict[str, int] = {}
    for result in styles:
        if not isinstance(result, dict) or not isinstance(result.get("style_id"), str):
            raise ValueError("summary style entries must be mappings with style_id")
        style_id = result["style_id"]
        if style_id in summary_ids:
            raise ValueError(f"duplicate summary style: {style_id}")
        summary_ids.add(style_id)
        item = items.get(style_id)
        if not isinstance(item, dict):
            raise ValueError(f"summary style is missing from catalog: {style_id}")
        validated_prompt_digest(item, result, style_id=style_id)
        if (
            required_tested_seeds is not None
            and result.get("tested_seeds") != required_tested_seeds
        ):
            raise ValueError(
                f"summary style {style_id!r} must have exactly "
                f"{required_tested_seeds} tested seeds"
            )
        recommendation = result.get("recommended_status")
        if recommendation not in ALLOWED_RECOMMENDATIONS:
            raise ValueError(f"summary style {style_id!r} has invalid recommendation")
        if (
            allowed_recommendations is not None
            and recommendation not in allowed_recommendations
        ):
            raise ValueError(
                f"summary style {style_id!r} has disallowed recommendation "
                f"{recommendation!r}"
            )
        recommendation_counts[recommendation] = (
            recommendation_counts.get(recommendation, 0) + 1
        )

    if require_exact_source_set:
        source_ids = {
            style_id
            for style_id, item in items.items()
            if isinstance(item, dict)
            and isinstance(item.get("validation"), dict)
            and item["validation"].get("status") in allowed_from
        }
        if summary_ids != source_ids:
            missing = len(source_ids - summary_ids)
            unexpected = len(summary_ids - source_ids)
            raise ValueError(
                "summary styles do not exactly match catalog source statuses "
                f"(missing={missing}, unexpected={unexpected})"
            )

    for recommendation, minimum in (minimum_recommendations or {}).items():
        if recommendation not in ALLOWED_RECOMMENDATIONS:
            raise ValueError(f"invalid minimum recommendation status: {recommendation}")
        if not isinstance(minimum, int) or minimum < 0:
            raise ValueError("minimum recommendation count must be non-negative")
        actual = recommendation_counts.get(recommendation, 0)
        if actual < minimum:
            raise ValueError(
                f"summary recommends {actual} {recommendation} style(s); "
                f"minimum is {minimum}"
            )
    return recommendation_counts


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
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
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
        evaluated_prompt_sha256 = validated_prompt_digest(
            item, result, style_id=style_id
        )
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
            raise ValueError(
                f"summary style {style_id!r} has invalid evaluation values"
            )
        values = {
            "tested_seeds": tested_seeds,
            "status": recommended,
            "last_evaluation": evaluation_id,
            "evaluated_prompt_sha256": evaluated_prompt_sha256,
            **{metric: averages[metric] for metric in PERSISTED_METRICS},
            "critical_failures": critical_failures,
        }
        pending.append((validation, values))
    for validation, values in pending:
        validation.update(values)
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
    parser = argparse.ArgumentParser(
        description="Apply validated evaluation status to a catalog"
    )
    parser.add_argument("summary", type=Path)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/art_styles.yaml"))
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--from-status", action="append", default=None)
    parser.add_argument("--require-exact-source-set", action="store_true")
    parser.add_argument("--require-tested-seeds", type=int)
    parser.add_argument(
        "--allow-recommendation",
        action="append",
        choices=sorted(ALLOWED_RECOMMENDATIONS),
        default=None,
    )
    parser.add_argument(
        "--minimum-recommendation",
        action="append",
        default=None,
        metavar="STATUS=COUNT",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--prompt-binding",
        type=Path,
        help="validated immutable-matrix to catalog prompt digest binding",
    )
    args = parser.parse_args()
    try:
        summary = load_yaml(args.summary)
        if not isinstance(summary, dict):
            raise ValueError("summary must be a mapping")
        bound_catalog_sha256: str | None = None
        if args.prompt_binding is not None:
            binding = load_validated_binding_document(
                args.prompt_binding,
                expected_catalog=args.catalog,
            )
            prompt_bindings = dict(binding["styles"])
            bound_catalog_sha256 = binding["catalog"]["sha256"]
            validate_summary_prompt_binding(summary, prompt_bindings)
        catalog = load_yaml(args.catalog)
        if not isinstance(catalog, dict):
            raise ValueError("catalog must be a mapping")
        if (
            bound_catalog_sha256 is not None
            and file_sha256(args.catalog) != bound_catalog_sha256
        ):
            raise ValueError("prompt binding catalog changed before evaluation apply")
        allowed_from = set(args.from_status or ["generated"])
        minimum_recommendations: dict[str, int] = {}
        for value in args.minimum_recommendation or []:
            status, separator, count = value.partition("=")
            if (
                not separator
                or status not in ALLOWED_RECOMMENDATIONS
                or not count.isdigit()
            ):
                raise ValueError("minimum recommendation must use STATUS=COUNT")
            if status in minimum_recommendations:
                raise ValueError(f"duplicate minimum recommendation: {status}")
            minimum_recommendations[status] = int(count)
        validate_transition_gate(
            catalog,
            summary,
            allowed_from,
            require_exact_source_set=args.require_exact_source_set,
            required_tested_seeds=args.require_tested_seeds,
            allowed_recommendations=(
                set(args.allow_recommendation)
                if args.allow_recommendation is not None
                else None
            ),
            minimum_recommendations=minimum_recommendations,
        )
        count = update_catalog(
            catalog,
            summary,
            args.evaluation_id,
            allowed_from,
        )
        if args.apply:
            if (
                bound_catalog_sha256 is not None
                and file_sha256(args.catalog) != bound_catalog_sha256
            ):
                raise ValueError("prompt binding catalog changed before atomic write")
            atomic_dump_yaml(catalog, args.catalog)
            print(
                f"Applied evaluation {args.evaluation_id} to {count} catalog style(s)."
            )
        else:
            print(
                f"DRY RUN: evaluation {args.evaluation_id} would update {count} catalog style(s)."
            )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
