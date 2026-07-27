#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from bind_artist_prompt_evidence import (
    ARTIFACT_TYPE,
    ROOT,
    build_binding,
    file_sha256,
    payload_sha256,
)
from common import canonical_prompt_sha256, load_yaml
from export_artist_visual_signature_matrix import (
    LEGACY_BENCHMARK_PROFILE,
    REPAIR_BENCHMARK_PROFILE,
    REPAIR_SEEDS,
    REINFORCED_AXIS_REPAIR_PROFILE,
    REINFORCED_AXIS_REPAIR_SEEDS,
    RETEST_SEEDS,
)
from summarize_results import METRICS, parse_evaluated_prompt_sha256


LEGACY_SEEDS = (1001, 2002, 3003)
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


def load_binding_against_current_prompts(
    path: Path,
    catalog_path: Path,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("prompt binding must remain inside repository root") from exc
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"prompt binding must be valid JSON: {path}") from exc
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or document.get("artifact_type") != ARTIFACT_TYPE
        or document.get("binding_sha256") != payload_sha256(document)
    ):
        raise ValueError(f"prompt binding has invalid or stale metadata: {path}")
    source = document.get("source_matrix")
    catalog = document.get("catalog")
    if not isinstance(source, dict) or not isinstance(catalog, dict):
        raise ValueError("prompt binding is missing source metadata")
    matrix_name = source.get("path")
    catalog_name = catalog.get("path")
    if not isinstance(matrix_name, str) or not isinstance(catalog_name, str):
        raise ValueError("prompt binding source paths must be strings")
    for name in (matrix_name, catalog_name):
        pure = PurePosixPath(name)
        if pure.is_absolute() or not pure.parts or ".." in pure.parts:
            raise ValueError("prompt binding source paths must be safe relative paths")
    matrix_path = root / matrix_name
    if (root / catalog_name).resolve() != catalog_path.resolve():
        raise ValueError("prompt binding catalog path does not match current catalog")
    if source.get("sha256") != file_sha256(matrix_path):
        raise ValueError("prompt binding source matrix hash is stale")
    rebuilt = build_binding(matrix_path, catalog_path, root=root)
    for key in (
        "source_matrix",
        "style_count",
        "style_row_counts",
        "styles",
        "benchmark_profile",
        "benchmark_stage",
        "benchmark_stages",
        "benchmark_profiles",
        "repair_benchmark_stages",
    ):
        if key == "source_matrix":
            expected = dict(rebuilt[key])
            original = dict(source)
            if expected != original:
                raise ValueError("prompt binding source matrix metadata is stale")
        elif document.get(key) != rebuilt.get(key):
            raise ValueError(
                f"prompt binding no longer matches current catalog prompts: {key}"
            )
    return document


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"scorecard has no header: {path}")
        rows = list(reader)
        fields = reader.fieldnames
    if not rows:
        raise ValueError(f"scorecard has no rows: {path}")
    for field in ("style_id", "seed", "factors_json", *METRICS, "critical_failure"):
        if field not in fields:
            raise ValueError(f"scorecard is missing required field {field!r}: {path}")
    return fields, rows


def factors(row: dict[str, str], *, context: str) -> dict[str, Any]:
    value = row.get("factors_json")
    if not isinstance(value, str):
        raise ValueError(f"{context}: factors_json is required")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context}: factors_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{context}: factors_json must contain an object")
    return parsed


def validate_source(
    path: Path,
    *,
    bound_styles: dict[str, str],
    current_digests: dict[str, str],
    expected_seeds: tuple[int, ...],
    expected_profile: str,
    expected_stage: str | None,
    expected_matrix_rows: dict[tuple[str, int], dict[str, Any]],
) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    fields, rows = read_csv(path)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for row_number, row in enumerate(rows, start=2):
        style_id = (row.get("style_id") or "").strip()
        if style_id not in bound_styles:
            raise ValueError(f"{path}:{row_number}: style is absent from prompt binding")
        try:
            seed = int((row.get("seed") or "").strip())
        except ValueError as exc:
            raise ValueError(f"{path}:{row_number}: seed must be an integer") from exc
        identity = (style_id, seed)
        if identity in seen:
            raise ValueError(f"{path}:{row_number}: duplicate style and seed")
        seen.add(identity)
        row_factors = factors(row, context=f"{path}:{row_number}")
        expected_row = expected_matrix_rows.get(identity)
        if expected_row is None:
            raise ValueError(f"{path}:{row_number}: row is absent from bound matrix")
        if row.get("test_id") != expected_row.get("test_id"):
            raise ValueError(f"{path}:{row_number}: test_id does not match bound matrix")
        if row_factors != expected_row.get("factors"):
            raise ValueError(f"{path}:{row_number}: factors do not match bound matrix")
        profile = row_factors.get("benchmark_profile", LEGACY_BENCHMARK_PROFILE)
        if profile != expected_profile:
            raise ValueError(f"{path}:{row_number}: benchmark profile mismatch")
        if row_factors.get("benchmark_stage") != expected_stage:
            raise ValueError(f"{path}:{row_number}: benchmark stage mismatch")
        digest = parse_evaluated_prompt_sha256(row, row_number=row_number)
        current_digest = current_digests.get(style_id)
        if bound_styles[style_id] != current_digest:
            raise ValueError(f"{path}:{row_number}: bound catalog prompt digest is stale")
        if digest is not None and digest != current_digest:
            raise ValueError(f"{path}:{row_number}: scorecard prompt digest is stale")
        grouped[style_id].append(row)
    if set(grouped) != set(bound_styles):
        raise ValueError(f"{path}: scorecard style set does not match prompt binding")
    for style_id, style_rows in grouped.items():
        seeds = {int(row["seed"]) for row in style_rows}
        if seeds != set(expected_seeds) or len(style_rows) != len(expected_seeds):
            raise ValueError(
                f"{path}: style {style_id!r} does not contain exact seeds "
                f"{list(expected_seeds)}"
            )
    return fields, grouped


def bound_matrix_rows(
    binding: dict[str, Any],
    *,
    root: Path,
) -> dict[tuple[str, int], dict[str, Any]]:
    source = binding["source_matrix"]
    path = root / source["path"]
    expected: dict[tuple[str, int], dict[str, Any]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        identity = (row.get("style_id"), row.get("seed"))
        if (
            not isinstance(identity[0], str)
            or type(identity[1]) is not int
            or identity in expected
        ):
            raise ValueError(f"{path}:{line_number}: invalid or duplicate matrix row")
        expected[identity] = row
    return expected


def current_testing_digests(catalog_path: Path) -> dict[str, str]:
    catalog = load_yaml(catalog_path)
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, dict):
        raise ValueError("artist catalog must contain an items mapping")
    return {
        style_id: canonical_prompt_sha256(item.get("prompt"))
        for style_id, item in items.items()
        if isinstance(item, dict)
        and isinstance(item.get("validation"), dict)
        and item["validation"].get("status") == "testing"
    }


def atomic_write_csv(
    path: Path,
    fields: list[str],
    rows: list[dict[str, str]],
    *,
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise ValueError(f"output exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_pilot_rows(
    legacy_scored: Path,
    repair_scored: Path,
    legacy_binding_path: Path,
    repair_binding_path: Path,
    catalog_path: Path,
    *,
    root: Path = ROOT,
    minimum_testing_count: int = 200,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    current = current_testing_digests(catalog_path)
    if len(current) < minimum_testing_count:
        raise ValueError(
            f"current catalog must contain at least {minimum_testing_count} testing styles"
        )
    legacy_binding = load_binding_against_current_prompts(
        legacy_binding_path, catalog_path, root=root
    )
    repair_binding = load_binding_against_current_prompts(
        repair_binding_path, catalog_path, root=root
    )
    repair_profile = repair_binding.get("benchmark_profile")
    if repair_profile not in REPAIR_PROFILES:
        raise ValueError("repair prompt binding has the wrong benchmark profile")
    legacy_fields, legacy_rows = validate_source(
        legacy_scored,
        bound_styles=dict(legacy_binding["styles"]),
        current_digests={
            style_id: canonical_prompt_sha256(item.get("prompt"))
            for style_id, item in load_yaml(catalog_path)["items"].items()
        },
        expected_seeds=LEGACY_SEEDS,
        expected_profile=LEGACY_BENCHMARK_PROFILE,
        expected_stage=None,
        expected_matrix_rows=bound_matrix_rows(legacy_binding, root=root),
    )
    repair_fields, repair_rows = validate_source(
        repair_scored,
        bound_styles=dict(repair_binding["styles"]),
        current_digests={
            style_id: canonical_prompt_sha256(item.get("prompt"))
            for style_id, item in load_yaml(catalog_path)["items"].items()
        },
        expected_seeds=REPAIR_PROFILE_SEEDS[repair_profile],
        expected_profile=repair_profile,
        expected_stage="pilot",
        expected_matrix_rows=bound_matrix_rows(repair_binding, root=root),
    )
    if legacy_fields != repair_fields:
        raise ValueError("legacy and repair scored scorecard headers do not match")
    repair_style_ids = set(repair_rows)
    selected: list[dict[str, str]] = []
    for style_id in sorted(current):
        source = repair_rows if style_id in repair_style_ids else legacy_rows
        if style_id not in source:
            raise ValueError(
                f"current testing style {style_id!r} has no canonical pilot source"
            )
        selected.extend(source[style_id])
    selected.sort(key=lambda row: (row["style_id"], int(row["seed"])))
    selected_ids = {row["style_id"] for row in selected}
    if selected_ids != set(current) or len(selected) != len(current) * 3:
        raise ValueError("canonical pilot does not exactly match current testing set")
    return legacy_fields, selected, current


def validate_extension_rows(
    path: Path,
    fields: list[str],
    current: dict[str, str],
    pilot_rows: list[dict[str, str]],
    *,
    matrix_path: Path | None = None,
) -> list[dict[str, str]]:
    extension_fields, rows = read_csv(path)
    if extension_fields != fields:
        raise ValueError("extension and pilot scorecard headers do not match")
    pilot_profiles: dict[str, str] = {}
    for row in pilot_rows:
        style_id = row["style_id"]
        profile = factors(row, context=f"pilot:{style_id}").get(
            "benchmark_profile", LEGACY_BENCHMARK_PROFILE
        )
        previous = pilot_profiles.setdefault(style_id, profile)
        if previous != profile:
            raise ValueError(f"pilot style {style_id!r} mixes benchmark profiles")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    expected_matrix: dict[tuple[str, int], dict[str, Any]] | None = None
    if matrix_path is not None:
        expected_matrix = {}
        for line_number, line in enumerate(
            matrix_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            expected_row = json.loads(line)
            identity = (expected_row.get("style_id"), expected_row.get("seed"))
            if (
                not isinstance(identity[0], str)
                or type(identity[1]) is not int
                or identity in expected_matrix
            ):
                raise ValueError(
                    f"{matrix_path}:{line_number}: invalid or duplicate matrix row"
                )
            expected_matrix[identity] = expected_row
    for row_number, row in enumerate(rows, start=2):
        style_id = (row.get("style_id") or "").strip()
        if style_id not in current:
            raise ValueError(f"{path}:{row_number}: style is not currently testing")
        seed = int((row.get("seed") or "").strip())
        identity = (style_id, seed)
        if identity in seen:
            raise ValueError(f"{path}:{row_number}: duplicate style and seed")
        seen.add(identity)
        row_factors = factors(row, context=f"{path}:{row_number}")
        if expected_matrix is not None:
            expected_row = expected_matrix.get(identity)
            if expected_row is None:
                raise ValueError(
                    f"{path}:{row_number}: row is absent from extension matrix"
                )
            if (
                row.get("test_id") != expected_row.get("test_id")
                or row_factors != expected_row.get("factors")
            ):
                raise ValueError(
                    f"{path}:{row_number}: row does not match extension matrix"
                )
        profile = row_factors.get("benchmark_profile", LEGACY_BENCHMARK_PROFILE)
        if profile != pilot_profiles[style_id]:
            raise ValueError(f"{path}:{row_number}: pilot/extension profile mismatch")
        expected_stage = "extension" if profile in REPAIR_PROFILES else None
        if row_factors.get("benchmark_stage") != expected_stage:
            raise ValueError(f"{path}:{row_number}: extension stage mismatch")
        digest = parse_evaluated_prompt_sha256(row, row_number=row_number)
        if digest != current[style_id]:
            raise ValueError(f"{path}:{row_number}: extension prompt digest is stale")
        grouped[style_id].append(row)
    if set(grouped) != set(current):
        raise ValueError("extension scorecard does not exactly match current testing set")
    if expected_matrix is not None and set(expected_matrix) != seen:
        raise ValueError("extension scorecard does not exactly match extension matrix")
    for style_id, style_rows in grouped.items():
        seeds = {int(row["seed"]) for row in style_rows}
        if seeds != set(RETEST_SEEDS) or len(style_rows) != len(RETEST_SEEDS):
            raise ValueError(
                f"extension style {style_id!r} does not contain exact retest seeds"
            )
    combined = [*pilot_rows, *rows]
    identities = {(row["style_id"], int(row["seed"])) for row in combined}
    if len(identities) != len(combined):
        raise ValueError("combined scorecard contains duplicate style and seed rows")
    for style_id in current:
        if len([row for row in combined if row["style_id"] == style_id]) != 5:
            raise ValueError(f"combined style {style_id!r} does not have exactly 5 seeds")
    combined.sort(key=lambda row: (row["style_id"], int(row["seed"])))
    return combined


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Select the canonical three-seed artist pilot from v0.8.2 and the "
            "current repair profile's scored evidence for the exact testing set"
        )
    )
    parser.add_argument("legacy_scored", type=Path)
    parser.add_argument("repair_scored", type=Path)
    parser.add_argument("--legacy-binding", type=Path, required=True)
    parser.add_argument("--repair-binding", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/artists.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extension-scorecard", type=Path)
    parser.add_argument("--extension-matrix", type=Path)
    parser.add_argument("--combined-output", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        extension_values = (
            args.extension_scorecard,
            args.extension_matrix,
            args.combined_output,
        )
        if any(value is not None for value in extension_values) and any(
            value is None for value in extension_values
        ):
            raise ValueError(
                "--extension-scorecard, --extension-matrix, and --combined-output "
                "must be used together"
            )
        fields, pilot_rows, current = build_pilot_rows(
            args.legacy_scored,
            args.repair_scored,
            args.legacy_binding,
            args.repair_binding,
            args.catalog,
            root=args.root,
        )
        atomic_write_csv(args.output, fields, pilot_rows, overwrite=args.overwrite)
        if args.extension_scorecard is not None:
            combined = validate_extension_rows(
                args.extension_scorecard,
                fields,
                current,
                pilot_rows,
                matrix_path=args.extension_matrix,
            )
            atomic_write_csv(
                args.combined_output,
                fields,
                combined,
                overwrite=args.overwrite,
            )
            print(
                f"Selected {len(pilot_rows)} canonical pilot rows and validated "
                f"{len(combined)} exact five-seed rows."
            )
        else:
            print(
                f"Selected {len(pilot_rows)} canonical pilot rows for "
                f"{len(current)} current testing styles."
            )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
