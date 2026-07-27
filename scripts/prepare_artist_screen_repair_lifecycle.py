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


ARTIFACT_TYPE = "artist_screen_repair_lifecycle_summary"


def build_lifecycle_summary(
    summary_path: Path,
    binding_path: Path,
    catalog_path: Path,
    *,
    root: Path = ROOT,
    expected_testing: int = 185,
    expected_rejected: int = 115,
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
        raise ValueError("source summary and catalog must be mappings")
    prompt_bindings = dict(binding["styles"])
    validate_summary_prompt_binding(summary, prompt_bindings)
    recommendation_counts = validate_transition_gate(
        catalog,
        summary,
        {"generated"},
        require_exact_source_set=True,
        required_tested_seeds=3,
        allowed_recommendations={"testing", "rejected"},
        minimum_recommendations={"testing": expected_testing},
    )
    expected_counts = {"testing": expected_testing, "rejected": expected_rejected}
    if recommendation_counts != expected_counts:
        raise ValueError(
            "source summary recommendation counts do not match the immutable "
            f"v0.8.2 result: expected {expected_counts}, got {recommendation_counts}"
        )
    styles = summary.get("styles")
    if not isinstance(styles, list):
        raise ValueError("source summary styles must be a list")
    transformed: list[dict[str, Any]] = []
    for result in sorted(styles, key=lambda value: value["style_id"]):
        updated = dict(result)
        if updated["recommended_status"] == "rejected":
            updated["recommended_status"] = "generated"
        transformed.append(updated)
    transformed_counts = Counter(
        result["recommended_status"] for result in transformed
    )
    document: dict[str, Any] = {
        "schema_version": 1,
        "style_count": len(transformed),
        "repair_lifecycle": {
            "artifact_type": ARTIFACT_TYPE,
            "policy": "defer_rejected_to_generated_for_v0_8_3_repair",
            "source_summary": {
                "path": summary_name,
                "sha256": file_sha256(summary_file),
            },
            "source_binding": {
                "path": binding_name,
                "sha256": file_sha256(binding_file),
                "binding_sha256": binding["binding_sha256"],
            },
            "original_recommendation_counts": dict(
                sorted(recommendation_counts.items())
            ),
            "transformed_recommendation_counts": dict(
                sorted(transformed_counts.items())
            ),
        },
        "styles": transformed,
    }
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert immutable v0.8.2 rejected recommendations to deferred generated "
            "repair candidates"
        )
    )
    parser.add_argument("summary", type=Path)
    parser.add_argument("--prompt-binding", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/artists.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expected-testing", type=int, default=185)
    parser.add_argument("--expected-rejected", type=int, default=115)
    args = parser.parse_args()
    try:
        document = build_lifecycle_summary(
            args.summary,
            args.prompt_binding,
            args.catalog,
            root=args.root,
            expected_testing=args.expected_testing,
            expected_rejected=args.expected_rejected,
        )
        atomic_write_json(args.output, document)
        counts = document["repair_lifecycle"]["transformed_recommendation_counts"]
        print(
            "Prepared deterministic repair lifecycle summary: "
            f"testing={counts.get('testing', 0)}, generated={counts.get('generated', 0)}."
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
