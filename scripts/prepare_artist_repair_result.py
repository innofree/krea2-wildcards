#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from apply_evaluation_summary import (
    validate_summary_prompt_binding,
    validate_transition_gate,
)
from bind_artist_prompt_evidence import (
    ROOT,
    atomic_write_json,
    file_sha256,
    load_validated_binding_document,
    relative_file,
)
from common import load_yaml


ARTIFACT_TYPE = "artist_repair_accumulation_summary"


def catalog_status_counts(catalog: dict[str, Any]) -> Counter[str]:
    items = catalog.get("items")
    if not isinstance(items, dict):
        raise ValueError("artist catalog must contain an items mapping")
    counts: Counter[str] = Counter()
    for style_id, item in items.items():
        validation = item.get("validation") if isinstance(item, dict) else None
        status = validation.get("status") if isinstance(validation, dict) else None
        if not isinstance(status, str):
            raise ValueError(f"catalog style {style_id!r} is missing validation status")
        counts[status] += 1
    return counts


def build_accumulation_summary(
    summary_path: Path,
    binding_path: Path,
    catalog_path: Path,
    *,
    root: Path = ROOT,
    expected_existing_testing: int = 185,
    expected_repair_candidates: int = 115,
    minimum_cumulative_testing: int = 200,
    require_retest_ready: bool = False,
) -> dict[str, Any]:
    summary_name, summary_file = relative_file(summary_path, root)
    binding_name, binding_file = relative_file(binding_path, root)
    binding = load_validated_binding_document(
        binding_file,
        root=root,
        expected_catalog=catalog_path,
    )
    summary = load_yaml(summary_file)
    catalog = load_yaml(catalog_path)
    if not isinstance(summary, dict) or not isinstance(catalog, dict):
        raise ValueError("repair summary and catalog must be mappings")
    status_counts = catalog_status_counts(catalog)
    expected_status_counts = {
        "testing": expected_existing_testing,
        "generated": expected_repair_candidates,
    }
    if dict(status_counts) != expected_status_counts:
        raise ValueError(
            "catalog is not at the exact v0.8.3 repair source lifecycle: "
            f"expected {expected_status_counts}, got {dict(status_counts)}"
        )
    if binding.get("benchmark_profile") != "artist_visual_signature_repair_v0_8_3":
        raise ValueError("repair result requires a v0.8.3 repair prompt binding")
    prompt_bindings = dict(binding["styles"])
    validate_summary_prompt_binding(summary, prompt_bindings)
    recommendation_counts = validate_transition_gate(
        catalog,
        summary,
        {"generated"},
        require_exact_source_set=True,
        required_tested_seeds=3,
        allowed_recommendations={"testing", "rejected"},
    )
    styles = summary.get("styles")
    if not isinstance(styles, list) or len(styles) != expected_repair_candidates:
        raise ValueError(
            f"repair summary must contain exactly {expected_repair_candidates} styles"
        )
    cumulative_testing = (
        expected_existing_testing + recommendation_counts.get("testing", 0)
    )
    retest_ready = cumulative_testing >= minimum_cumulative_testing
    if require_retest_ready and not retest_ready:
        raise ValueError(
            f"repair would yield {cumulative_testing} cumulative testing styles; "
            f"minimum is {minimum_cumulative_testing}"
        )
    transformed: list[dict[str, Any]] = []
    for result in sorted(styles, key=lambda value: value["style_id"]):
        updated = dict(result)
        if updated["recommended_status"] == "rejected":
            updated["recommended_status"] = "generated"
        transformed.append(updated)
    transformed_counts = Counter(
        result["recommended_status"] for result in transformed
    )
    return {
        "schema_version": 1,
        "style_count": len(transformed),
        "repair_accumulation": {
            "artifact_type": ARTIFACT_TYPE,
            "policy": "repair_pass_to_testing_and_failure_remains_generated",
            "source_summary": {
                "path": summary_name,
                "sha256": file_sha256(summary_file),
            },
            "source_binding": {
                "path": binding_name,
                "sha256": file_sha256(binding_file),
                "binding_sha256": binding["binding_sha256"],
            },
            "catalog_status_counts_before_apply": dict(sorted(status_counts.items())),
            "original_recommendation_counts": dict(
                sorted(recommendation_counts.items())
            ),
            "transformed_recommendation_counts": dict(
                sorted(transformed_counts.items())
            ),
            "cumulative_testing_after_apply": cumulative_testing,
            "minimum_cumulative_testing": minimum_cumulative_testing,
            "retest_gate_satisfied": retest_ready,
        },
        "styles": transformed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and transform v0.8.3 repair results into an accumulating "
            "testing/generated lifecycle summary"
        )
    )
    parser.add_argument("summary", type=Path)
    parser.add_argument("--prompt-binding", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/artists.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expected-existing-testing", type=int, default=185)
    parser.add_argument("--expected-repair-candidates", type=int, default=115)
    parser.add_argument("--minimum-cumulative-testing", type=int, default=200)
    parser.add_argument(
        "--require-retest-ready",
        action="store_true",
        help="refuse preparation unless the cumulative testing set reaches the retest gate",
    )
    args = parser.parse_args()
    try:
        document = build_accumulation_summary(
            args.summary,
            args.prompt_binding,
            args.catalog,
            root=args.root,
            expected_existing_testing=args.expected_existing_testing,
            expected_repair_candidates=args.expected_repair_candidates,
            minimum_cumulative_testing=args.minimum_cumulative_testing,
            require_retest_ready=args.require_retest_ready,
        )
        atomic_write_json(args.output, document)
        evidence = document["repair_accumulation"]
        print(
            "Prepared repair accumulation summary: "
            f"cumulative testing={evidence['cumulative_testing_after_apply']}."
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
