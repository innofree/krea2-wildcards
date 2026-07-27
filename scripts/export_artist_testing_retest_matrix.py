#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import canonical_prompt_sha256, load_yaml
from export_artist_visual_signature_matrix import (
    LEGACY_BENCHMARK_PROFILE,
    REPAIR_BENCHMARK_PROFILE,
    REPAIR_SEEDS,
    REINFORCED_AXIS_REPAIR_PROFILE,
    REINFORCED_AXIS_REPAIR_SEEDS,
    RETEST_SEEDS,
    prompt_for_profile,
    validate_signature_item,
    write_immutable_jsonl,
)
from run_remote_prompt_matrix import validate_job
from select_artist_testing_pilot import (
    current_testing_digests,
    factors,
    read_csv,
)
from summarize_results import parse_evaluated_prompt_sha256


LEGACY_PILOT_SEEDS = (1001, 2002, 3003)
REPAIR_PROFILES = frozenset(
    {
        REPAIR_BENCHMARK_PROFILE,
        REINFORCED_AXIS_REPAIR_PROFILE,
    }
)
REPAIR_PROFILE_SEEDS = {
    REPAIR_BENCHMARK_PROFILE: REPAIR_SEEDS,
    REINFORCED_AXIS_REPAIR_PROFILE: REINFORCED_AXIS_REPAIR_SEEDS,
}


def retest_rows(
    pilot_scorecard: Path,
    catalog_path: Path,
) -> list[dict[str, Any]]:
    _, pilot_rows = read_csv(pilot_scorecard)
    current = current_testing_digests(catalog_path)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pilot_rows:
        style_id = (row.get("style_id") or "").strip()
        if style_id not in current:
            raise ValueError(f"pilot style {style_id!r} is not currently testing")
        grouped[style_id].append(row)
    if set(grouped) != set(current):
        raise ValueError("pilot scorecard does not exactly match current testing styles")

    catalog = load_yaml(catalog_path)
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, dict):
        raise ValueError("artist catalog must contain an items mapping")
    rows: list[dict[str, Any]] = []
    for style_id in sorted(current):
        source_rows = grouped[style_id]
        try:
            source_seeds = {int(row["seed"]) for row in source_rows}
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"pilot style {style_id!r} contains a non-integer seed"
            ) from exc
        if len(source_rows) != 3 or len(source_seeds) != 3:
            raise ValueError(f"pilot style {style_id!r} must have exactly three seeds")
        profiles = {
            factors(row, context=f"pilot:{style_id}").get(
                "benchmark_profile", LEGACY_BENCHMARK_PROFILE
            )
            for row in source_rows
        }
        if len(profiles) != 1:
            raise ValueError(f"pilot style {style_id!r} mixes benchmark profiles")
        profile = next(iter(profiles))
        if profile not in {
            LEGACY_BENCHMARK_PROFILE,
            REPAIR_BENCHMARK_PROFILE,
            REINFORCED_AXIS_REPAIR_PROFILE,
        }:
            raise ValueError(f"pilot style {style_id!r} has an unsupported profile")
        expected_pilot_seeds = (
            REPAIR_PROFILE_SEEDS[profile]
            if profile in REPAIR_PROFILES
            else LEGACY_PILOT_SEEDS
        )
        if source_seeds != set(expected_pilot_seeds):
            raise ValueError(
                f"pilot style {style_id!r} does not contain its exact profile seeds"
            )
        expected_digest = current[style_id]
        for row_number, source_row in enumerate(source_rows, start=1):
            source_factors = factors(
                source_row,
                context=f"pilot:{style_id}:{row_number}",
            )
            expected_stage = (
                "pilot" if profile in REPAIR_PROFILES else None
            )
            if source_factors.get("benchmark_stage") != expected_stage:
                raise ValueError(
                    f"pilot style {style_id!r} has an invalid benchmark stage"
                )
            digest = parse_evaluated_prompt_sha256(
                source_row,
                row_number=row_number,
            )
            if profile in REPAIR_PROFILES and digest is None:
                raise ValueError(
                    f"repair pilot style {style_id!r} is missing its prompt digest"
                )
            if digest is not None and digest != expected_digest:
                raise ValueError(
                    f"pilot style {style_id!r} has a stale prompt digest"
                )
        _, body = validate_signature_item(style_id, items[style_id])
        row_factors = {
            axis: values[0]
            for axis, values in sorted(items[style_id]["feature_axes"].items())
        }
        row_factors["evaluated_prompt_sha256"] = (
            "sha256_" + canonical_prompt_sha256(body)
        )
        if profile in REPAIR_PROFILES:
            row_factors["benchmark_profile"] = profile
            row_factors["benchmark_stage"] = "extension"
        prompt = prompt_for_profile(
            body,
            profile,
            feature_axes=items[style_id]["feature_axes"],
        )
        for seed in RETEST_SEEDS:
            row = {
                "schema_version": 1,
                "test_id": f"VSRT{len(rows) + 1:06d}",
                "style_id": style_id,
                "label": style_id,
                "mode": "visual_signature",
                "seed": seed,
                "prompt": prompt,
                "factors": row_factors,
            }
            validate_job(row, len(rows) + 1)
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export two extension seeds using each current testing style's canonical "
            "legacy or current repair pilot profile"
        )
    )
    parser.add_argument("pilot_scorecard", type=Path)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/artists.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = retest_rows(args.pilot_scorecard, args.catalog)
        write_immutable_jsonl(args.output, rows)
        print(
            f"Wrote {len(rows)} extension prompt(s) for "
            f"{len({row['style_id'] for row in rows})} testing style(s)."
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
