#!/usr/bin/env python3
"""Evaluate the measurable plan.md completion criteria without changing release state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from common import item_prompts, load_yaml, normalized_phrase


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("tests/reports/completion_criteria.json")
REPORT_TYPES = {
    "runtime_coverage",
    "single_axis_coverage",
    "artist_abc_coverage",
    "pairwise_coverage",
    "preset_conflict_audit",
    "random_utility",
    "krea2_turbo_benchmark",
}
PAIRWISE_TYPES = {
    "style_pack_character_design",
    "style_pack_pose",
    "style_pack_lighting",
    "style_pack_background",
    "artist_signature_coloring",
    "artist_signature_camera_composition",
}
CONTENT_SCALE_TARGETS: dict[str, tuple[tuple[str, ...], int]] = {
    "style_pack_items": (("art_styles.yaml", "style_expansion.yaml"), 200),
    "artist_signature_items": (("artists.yaml",), 300),
    "media_rendering_items": (("media_rendering.yaml",), 150),
    "linework_coloring_items": (("linework_coloring.yaml",), 300),
    "character_design_items": (("character_designs.yaml",), 400),
    "hair_design_items": (("hair_designs.yaml",), 250),
    "fashion_items": (("fashion.yaml",), 500),
    "pose_items": (("poses.yaml",), 350),
    "camera_items": (("cameras.yaml",), 250),
    "lighting_items": (("lighting.yaml",), 250),
    "background_items": (("backgrounds.yaml",), 400),
    "effect_items": (("effects.yaml",), 200),
    "preset_items": (("presets.yaml",), 200),
}
TOTAL_LIBRARY_ITEMS = 3750
MINIMUM_SINGLE_AXIS_CASES = 4
MINIMUM_ARTIST_ABC_COUNT = 8
MINIMUM_PAIRWISE_CASES = 96
MINIMUM_PRESETS_TESTED = 100
MINIMUM_RANDOM_SAMPLES = 20
MINIMUM_BENCHMARK_SEEDS = 5
PRODUCTION_ARTIFACT = Path("build/impact-production/krea2_complete_pack.yaml")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _safe_repo_relative_file(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        return None
    unresolved = root / Path(*pure.parts)
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            return None
    candidate = unresolved.resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _digest_evidence_matches(
    root: Path, report: dict[str, Any], path_field: str, digest_field: str
) -> bool:
    path = _safe_repo_relative_file(root, report.get(path_field))
    digest = report.get(digest_field)
    return (
        path is not None
        and isinstance(digest, str)
        and len(digest) == 64
        and _sha256(path) == digest
    )


def _phase6_evidence_fresh(root: Path, report: dict[str, Any]) -> bool:
    return _digest_evidence_matches(
        root, report, "matrix_path", "matrix_sha256"
    ) and _digest_evidence_matches(root, report, "scored_path", "scored_sha256")


def _runtime_evidence_fresh(root: Path, report: dict[str, Any]) -> bool:
    artifact = _safe_repo_relative_file(root, report.get("production_artifact"))
    prompt_logs = report.get("prompt_logs")
    return (
        _digest_evidence_matches(root, report, "manifest", "manifest_sha256")
        and artifact is not None
        and _sha256(artifact) == report.get("production_artifact_sha256")
        and artifact.stat().st_size == report.get("production_artifact_bytes")
        and isinstance(prompt_logs, list)
        and bool(prompt_logs)
        and all(
            isinstance(item, dict)
            and _digest_evidence_matches(root, item, "path", "sha256")
            for item in prompt_logs
        )
    )


def _criterion(
    criterion_id: str,
    category: str,
    complete: bool,
    actual: Any,
    target: Any,
    evidence: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "category": category,
        "complete": bool(complete),
        "actual": actual,
        "target": target,
        "evidence": sorted(set(evidence)),
        "message": message,
    }


def _catalog_items(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    data = load_yaml(path)
    raw_items = data.get("items", {}) if isinstance(data, dict) else {}
    if not isinstance(raw_items, dict):
        return {}
    return {str(key): item for key, item in raw_items.items() if isinstance(item, dict)}


def _approved_and_valid(item: dict[str, Any]) -> bool:
    validation = item.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "approved":
        return False
    requirements = {
        "tested_seeds": (5, None),
        "prompt_adherence": (4, None),
        "style_fidelity": (3, None),
        "stability": (3, None),
        "compatibility": (3, None),
        "critical_failures": (None, 0),
    }
    for key, (minimum, maximum) in requirements.items():
        value = validation.get(key)
        if not _is_number(value):
            return False
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
    return True


def approved_runtime_catalog_inventory(root: Path) -> tuple[set[str], list[str]]:
    """Return approval-policy-valid runtime IDs and structural catalog problems."""

    approved_ids: set[str] = set()
    problems: list[str] = []
    for path in sorted((root / "catalog").glob("*.yaml")):
        for item_id, item in _catalog_items(path).items():
            if not _approved_and_valid(item):
                continue
            runtime = item.get("runtime")
            prompts = item_prompts(item)
            if not prompts or not isinstance(runtime, dict):
                problems.append("approval-policy-valid item lacks prompts/runtime")
                continue
            raw_file = runtime.get("file")
            raw_path = runtime.get("path")
            file_path = PurePosixPath(raw_file) if isinstance(raw_file, str) else None
            runtime_valid = (
                file_path is not None
                and not file_path.is_absolute()
                and ".." not in file_path.parts
                and file_path.suffix == ".yaml"
                and isinstance(raw_path, list)
                and len(raw_path) >= 2
                and all(isinstance(part, str) and part for part in raw_path)
                and raw_path[-1] == item_id
            )
            if not runtime_valid:
                problems.append("approval-policy-valid item has invalid runtime metadata")
                continue
            if item_id in approved_ids:
                problems.append("duplicate approval-policy-valid runtime item ID")
                continue
            approved_ids.add(item_id)
    return approved_ids, sorted(set(problems))


def _content_criteria(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    catalog = root / "catalog"
    style_paths = [catalog / "art_styles.yaml", catalog / "style_expansion.yaml"]
    artist_path = catalog / "artists.yaml"
    style_items = [
        (path, key, item)
        for path in style_paths
        for key, item in _catalog_items(path).items()
    ]
    artist_items = [
        (artist_path, key, item) for key, item in _catalog_items(artist_path).items()
    ]

    approved_styles = [
        row
        for row in style_items
        if row[2].get("family") == "style_pack" and _approved_and_valid(row[2])
    ]
    # Legacy style packs use named visual families; their runtime route is canonical.
    approved_styles += [
        row
        for row in style_items
        if row not in approved_styles
        and _approved_and_valid(row[2])
        and (row[2].get("runtime") or {}).get("file")
        == "krea2/style/complete_pack.yaml"
    ]
    approved_artists = [
        row
        for row in artist_items
        if _approved_and_valid(row[2])
        and (
            row[2].get("family") == "artist_signature"
            or (row[2].get("generation") or {}).get("kind") == "artist_signature"
        )
    ]
    criteria = [
        _criterion(
            "approved_style_packs",
            "content",
            len(approved_styles) >= 150,
            len(approved_styles),
            {"minimum": 150, "approval_policy_valid": True},
            [_relative(path, root) for path, _, _ in approved_styles]
            or [_relative(path, root) for path in style_paths if path.is_file()],
            "Count includes only approval-policy-valid complete style runtime entries.",
        ),
        _criterion(
            "approved_canonical_artist_signatures",
            "content",
            len(approved_artists) >= 200,
            len(approved_artists),
            {"minimum": 200, "approval_policy_valid": True},
            [_relative(artist_path, root)] if artist_path.is_file() else [],
            "Count includes only canonical artist-signature items that satisfy every approval gate.",
        ),
    ]
    all_approved: list[dict[str, Any]] = []
    for path in sorted(catalog.glob("*.yaml")):
        for item in _catalog_items(path).values():
            validation = item.get("validation")
            if isinstance(validation, dict) and validation.get("status") == "approved":
                all_approved.append(item)
    return criteria, all_approved


def _content_scale_criterion(root: Path) -> dict[str, Any]:
    catalog_root = root / "catalog"
    actual: dict[str, int] = {}
    evidence: list[str] = []
    for target_id, (catalog_names, _minimum) in CONTENT_SCALE_TARGETS.items():
        count = 0
        for catalog_name in catalog_names:
            path = catalog_root / catalog_name
            count += len(_catalog_items(path))
            if path.is_file():
                evidence.append(_relative(path, root))
        actual[target_id] = count

    total = 0
    for path in sorted(catalog_root.glob("*.yaml")):
        items = _catalog_items(path)
        total += len(items)
        if items:
            evidence.append(_relative(path, root))
    actual["total_library_items"] = total
    targets = {
        target_id: minimum
        for target_id, (_catalog_names, minimum) in CONTENT_SCALE_TARGETS.items()
    }
    targets["total_library_items"] = TOTAL_LIBRARY_ITEMS
    complete = all(
        actual[target_id] >= minimum for target_id, minimum in targets.items()
    )
    return _criterion(
        "content_scale_targets",
        "content",
        complete,
        actual,
        targets,
        evidence,
        "Every initial-scale category target and the 3,750-item total are counted directly from catalog items.",
    )


def _quality_metric_criterion(
    root: Path, approved_items: list[dict[str, Any]]
) -> dict[str, Any]:
    adherence: list[float] = []
    stability: list[float] = []
    missing = 0
    for item in approved_items:
        validation = item.get("validation", {})
        a_value = validation.get("prompt_adherence")
        s_value = validation.get("stability")
        if not _is_number(a_value) or not _is_number(s_value):
            missing += 1
            continue
        adherence.append(float(a_value))
        stability.append(float(s_value))
    averages = {
        "approved_items": len(approved_items),
        "evaluated_items": len(adherence),
        "missing_metrics": missing,
        "prompt_adherence": round(sum(adherence) / len(adherence), 3)
        if adherence
        else None,
        "stability": round(sum(stability) / len(stability), 3) if stability else None,
    }
    complete = (
        bool(adherence)
        and missing == 0
        and averages["prompt_adherence"] >= 4
        and averages["stability"] >= 3
    )
    return _criterion(
        "approved_quality_averages",
        "quality",
        complete,
        averages,
        {"prompt_adherence_minimum": 4, "stability_minimum": 3, "missing_metrics": 0},
        [
            "catalog/art_styles.yaml",
            "catalog/style_expansion.yaml",
            "catalog/artists.yaml",
        ],
        "Averages are computed directly from every catalog entry whose status is approved.",
    )


def _manifest_criterion(root: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    path = root / "wildcards-manifest.json"
    manifest = _json_object(path)
    problems: list[str] = []
    expected_ids, catalog_problems = approved_runtime_catalog_inventory(root)
    problems.extend(catalog_problems)
    manifest_ids: set[str] = set()
    catalog_ids_match = False
    if manifest is None:
        problems.append("missing or malformed manifest")
    else:
        items = manifest.get("items")
        files = manifest.get("files")
        if manifest.get("included_statuses") != ["approved"]:
            problems.append("manifest is not approved-only")
        if not isinstance(items, list) or not items:
            problems.append("manifest has no items")
        else:
            raw_ids = [
                item.get("id") if isinstance(item, dict) else None for item in items
            ]
            if manifest.get("item_count") != len(items) or any(
                not isinstance(item, dict)
                or item.get("status") != "approved"
                or not isinstance(item.get("id"), str)
                or not item.get("id")
                for item in items
            ):
                problems.append("manifest items are inconsistent")
            else:
                manifest_ids = set(raw_ids)
                if len(manifest_ids) != len(raw_ids):
                    problems.append("manifest contains duplicate item IDs")
                if manifest_ids != expected_ids:
                    problems.append(
                        "manifest item IDs do not match approval-policy-valid catalog runtime IDs"
                    )
                catalog_ids_match = not catalog_problems and manifest_ids == expected_ids
        if not isinstance(files, list) or not files:
            problems.append("manifest has no runtime files")
        else:
            for raw in files:
                if not isinstance(raw, str):
                    problems.append("invalid runtime file")
                    continue
                pure = PurePosixPath(raw)
                if (
                    pure.is_absolute()
                    or ".." in pure.parts
                    or not (root / "wildcards" / pure).is_file()
                ):
                    problems.append("missing or unsafe runtime file")
    actual = {
        "item_count": manifest.get("item_count") if manifest else None,
        "prompt_count": manifest.get("prompt_count") if manifest else None,
        "catalog_approved_runtime_item_count": len(expected_ids),
        "manifest_unique_item_id_count": len(manifest_ids),
        "catalog_item_ids_match": catalog_ids_match,
        "missing_catalog_item_ids": sorted(expected_ids - manifest_ids),
        "unexpected_manifest_item_ids": sorted(manifest_ids - expected_ids),
        "problems": sorted(set(problems)),
    }
    return (
        _criterion(
            "production_runtime_manifest",
            "functional",
            not problems,
            actual,
            {
                "approved_only": True,
                "consistent_counts": True,
                "all_files_exist": True,
                "catalog_item_ids_match_exactly": True,
                "approval_policy_valid": True,
            },
            [_relative(path, root)] if path.is_file() else [],
            "Production runtime must exactly contain every approval-policy-valid approved catalog runtime item.",
        ),
        manifest,
    )


def _release_criterion(
    root: Path,
    manifest: dict[str, Any] | None,
    *,
    manifest_catalog_ids_match: bool,
) -> dict[str, Any]:
    path = root / "tests/reports/releases/latest.json"
    report = _json_object(path)
    required = {
        "catalog_generation",
        "catalog_normalization",
        "catalog_duplicates",
        "catalog_conflicts",
        "catalog_v2_sync",
        "catalog_schema_v2",
        "sensitive_worktree",
        "sensitive_history",
        "preview_build",
        "preview_runtime_lint",
        "test_suite",
        "production_build",
        "production_runtime_lint",
        "production_impact_build",
        "plan_progress",
    }
    passed: set[str] = set()
    production_matches = False
    if report:
        outcomes = report.get("outcomes")
        if isinstance(outcomes, list):
            passed = {
                item.get("name")
                for item in outcomes
                if isinstance(item, dict)
                and item.get("status") == "passed"
                and item.get("returncode") == 0
            }
        production = report.get("production")
        production_matches = (
            isinstance(production, dict)
            and isinstance(manifest, dict)
            and production.get("item_count") == manifest.get("item_count")
            and production.get("prompt_count") == manifest.get("prompt_count")
        )
    missing = sorted(required - passed)
    complete = (
        bool(report)
        and report.get("status") == "passed"
        and not missing
        and production_matches
        and manifest_catalog_ids_match
    )
    return _criterion(
        "release_functional_gates",
        "functional",
        complete,
        {
            "passed_stages": sorted(passed & required),
            "missing_stages": missing,
            "production_matches_manifest": production_matches,
            "manifest_catalog_item_ids_match": manifest_catalog_ids_match,
        },
        {
            "required_stages": sorted(required),
            "release_status": "passed",
            "production_matches_manifest": True,
            "manifest_catalog_item_ids_match": True,
        },
        [_relative(path, root)] if path.is_file() else [],
        "Sensitive-data checks remain external; all deterministic build, lint, test, and schema gates are required.",
    )


def _discover_reports(root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    discovered = {name: [] for name in REPORT_TYPES}
    report_root = root / "tests/reports"
    if not report_root.is_dir():
        return discovered
    for path in sorted(report_root.rglob("*.json")):
        document = _json_object(path)
        if document and document.get("report_type") in discovered:
            discovered[document["report_type"]].append((path, document))
    return discovered


def _report_gate(
    root: Path,
    reports: dict[str, list[tuple[Path, dict[str, Any]]]],
    report_type: str,
    criterion_id: str,
    category: str,
    target: Any,
    validator: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    candidates = reports[report_type]
    passing: list[tuple[Path, dict[str, Any]]] = []
    for path, report in candidates:
        try:
            valid = validator(report)
        except (AttributeError, KeyError, TypeError, ValueError):
            valid = False
        if valid:
            passing.append((path, report))
    selected = passing[-1] if passing else (candidates[-1] if candidates else None)
    actual = (
        {
            "report_type": report_type,
            "schema_version": selected[1].get("schema_version"),
            "status": selected[1].get("status"),
            "complete": selected[1].get("complete"),
            "valid": bool(passing),
        }
        if selected
        else {"report_type": report_type, "status": "missing", "valid": False}
    )
    evidence = [_relative(selected[0], root)] if selected else []
    return _criterion(
        criterion_id,
        category,
        bool(passing),
        actual,
        target,
        evidence,
        f"Requires a schema_version 1 tests/reports JSON object with report_type={report_type!r}.",
    )


def _structured_report_criteria(
    root: Path, reports: dict[str, list[tuple[Path, dict[str, Any]]]]
) -> list[dict[str, Any]]:
    def base(report: dict[str, Any]) -> bool:
        return (
            report.get("schema_version") == 1
            and report.get("status") == "passed"
            and report.get("complete") is True
        )

    return [
        _report_gate(
            root,
            reports,
            "runtime_coverage",
            "runtime_resolution_coverage",
            "functional",
            {
                "unresolved_wildcards": 0,
                "syntax_errors": 0,
                "all_expected_loaded_and_resolved": True,
                "prompt_logs_saved": True,
            },
            lambda r: base(r)
            and _runtime_evidence_fresh(root, r)
            and _is_number(r.get("runtime_files_expected"))
            and r.get("runtime_files_expected") > 0
            and r.get("runtime_files_loaded") == r.get("runtime_files_expected")
            and _is_number(r.get("wildcard_paths_expected"))
            and r.get("wildcard_paths_expected") > 0
            and r.get("wildcard_paths_resolved") == r.get("wildcard_paths_expected")
            and r.get("unresolved_wildcards") == 0
            and r.get("yaml_syntax_errors") == 0
            and r.get("novelai_brace_conflicts") == 0
            and r.get("catalog_runtime_separated") is True
            and r.get("final_prompt_logs_saved") is True,
        ),
        _report_gate(
            root,
            reports,
            "single_axis_coverage",
            "single_axis_coverage",
            "coverage",
            {
                "tested_axes_include": ["linework", "coloring"],
                "total_cases_minimum": MINIMUM_SINGLE_AXIS_CASES,
                "critical_failures": 0,
            },
            lambda r: base(r)
            and _phase6_evidence_fresh(root, r)
            and isinstance(r.get("tested_axes"), list)
            and {"linework", "coloring"}.issubset(set(r["tested_axes"]))
            and _is_number(r.get("total_cases"))
            and r.get("total_cases") >= MINIMUM_SINGLE_AXIS_CASES
            and r.get("critical_failures") == 0,
        ),
        _report_gate(
            root,
            reports,
            "artist_abc_coverage",
            "artist_abc_coverage",
            "coverage",
            {
                "modes": ["native_name", "visual_signature", "hybrid"],
                "artist_count_minimum": MINIMUM_ARTIST_ABC_COUNT,
                "recommendations_complete": True,
            },
            lambda r: base(r)
            and _phase6_evidence_fresh(root, r)
            and isinstance(r.get("modes"), list)
            and {"native_name", "visual_signature", "hybrid"}.issubset(set(r["modes"]))
            and _is_number(r.get("artist_count"))
            and r.get("artist_count") >= MINIMUM_ARTIST_ABC_COUNT
            and r.get("recommended_modes_recorded") == r.get("artist_count")
            and r.get("critical_failures") == 0,
        ),
        _report_gate(
            root,
            reports,
            "pairwise_coverage",
            "pairwise_combination_coverage",
            "coverage",
            {
                "required_pair_types": sorted(PAIRWISE_TYPES),
                "total_cases_minimum": MINIMUM_PAIRWISE_CASES,
                "critical_failures": 0,
            },
            lambda r: base(r)
            and _phase6_evidence_fresh(root, r)
            and isinstance(r.get("covered_pair_types"), list)
            and PAIRWISE_TYPES.issubset(set(r["covered_pair_types"]))
            and _is_number(r.get("total_cases"))
            and r.get("total_cases") >= MINIMUM_PAIRWISE_CASES
            and r.get("critical_failures") == 0,
        ),
        _report_gate(
            root,
            reports,
            "preset_conflict_audit",
            "preset_critical_conflicts",
            "quality",
            {"presets_tested_minimum": MINIMUM_PRESETS_TESTED, "critical_conflicts": 0},
            lambda r: base(r)
            and _phase6_evidence_fresh(root, r)
            and _is_number(r.get("presets_tested"))
            and r.get("presets_tested") >= MINIMUM_PRESETS_TESTED
            and r.get("critical_conflicts") == 0,
        ),
        _report_gate(
            root,
            reports,
            "random_utility",
            "random_generation_utility_rate",
            "quality",
            {
                "sample_count_minimum": MINIMUM_RANDOM_SAMPLES,
                "measured_utility_rate": True,
            },
            lambda r: base(r)
            and _phase6_evidence_fresh(root, r)
            and isinstance(r.get("sample_count"), int)
            and not isinstance(r.get("sample_count"), bool)
            and r.get("sample_count") >= MINIMUM_RANDOM_SAMPLES
            and isinstance(r.get("usable_count"), int)
            and 0 <= r.get("usable_count") <= r.get("sample_count")
            and _is_number(r.get("utility_rate"))
            and 0 <= r.get("utility_rate") <= 1
            and abs(
                r.get("utility_rate") - r.get("usable_count") / r.get("sample_count")
            )
            <= 0.001,
        ),
        _report_gate(
            root,
            reports,
            "krea2_turbo_benchmark",
            "krea2_turbo_benchmark",
            "benchmark",
            {
                "model": "krea2_turbo",
                "distinct_seeds_minimum": MINIMUM_BENCHMARK_SEEDS,
                "sample_count_minimum": MINIMUM_BENCHMARK_SEEDS,
                "metrics_recorded": True,
            },
            lambda r: base(r)
            and _phase6_evidence_fresh(root, r)
            and "krea2" in str(r.get("model", "")).lower()
            and "turbo" in str(r.get("model", "")).lower()
            and isinstance(r.get("distinct_seeds"), int)
            and r.get("distinct_seeds") >= MINIMUM_BENCHMARK_SEEDS
            and isinstance(r.get("sample_count"), int)
            and r.get("sample_count") >= MINIMUM_BENCHMARK_SEEDS
            and isinstance(r.get("metrics"), dict)
            and bool(r.get("metrics")),
        ),
    ]


def _duplicate_criterion(root: Path) -> dict[str, Any]:
    path = root / "tests/reports/static_audit_v0_5.json"
    report = _json_object(path)
    rate: float | None = None
    duplicates_count: int | None = None
    total: int | None = None
    recorded_prompt_digest: str | None = None
    if report:
        duplicates = report.get("duplicates")
        catalog = report.get("catalog")
        if isinstance(duplicates, dict) and isinstance(catalog, dict):
            exact = duplicates.get("exact_duplicates")
            near = duplicates.get("near_duplicates")
            total = catalog.get("total_items")
            recorded_prompt_digest = catalog.get("prompt_digest_sha256")
            if (
                isinstance(exact, int)
                and isinstance(near, int)
                and isinstance(total, int)
                and total > 0
            ):
                duplicates_count = exact + near
                rate = duplicates_count / total
    current_total = sum(
        len(_catalog_items(path)) for path in sorted((root / "catalog").glob("*.yaml"))
    )
    prompt_rows = sorted(
        (
            path.name,
            item_id,
            normalized_phrase(prompt),
        )
        for path in sorted((root / "catalog").glob("*.yaml"))
        for item_id, item in _catalog_items(path).items()
        for prompt in item_prompts(item)
    )
    current_prompt_digest = hashlib.sha256(
        json.dumps(prompt_rows, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    total_matches = total == current_total
    digest_matches = recorded_prompt_digest == current_prompt_digest
    return _criterion(
        "semantic_duplicate_rate",
        "quality",
        rate is not None and rate <= 0.05 and total_matches and digest_matches,
        {
            "duplicate_items_or_pairs": duplicates_count,
            "catalog_items": total,
            "current_catalog_items": current_total,
            "catalog_count_matches": total_matches,
            "catalog_prompt_digest_matches": digest_matches,
            "rate": round(rate, 6) if rate is not None else None,
        },
        {
            "maximum_rate": 0.05,
            "catalog_count_matches": True,
            "catalog_prompt_digest_matches": True,
        },
        [_relative(path, root)] if path.is_file() else [],
        "Rate is derived from the committed static exact/near duplicate audit bound to the current prompt corpus.",
    )


def _deployment_criteria(
    root: Path, manifest: dict[str, Any] | None
) -> list[dict[str, Any]]:
    deployment_root = root / "tests/reports/deployments"
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if deployment_root.is_dir():
        for path in sorted(deployment_root.glob("*.json")):
            report = _json_object(path)
            if not report:
                continue
            identity = f"{path.name} {report.get('deployment_id', '')}"
            if report.get("deployment_type") == "production" or (
                "production" in identity.lower()
            ):
                candidates.append((path, report))
    expected_items = manifest.get("item_count") if isinstance(manifest, dict) else None
    artifact_path = root / PRODUCTION_ARTIFACT
    artifact_sha256 = _sha256(artifact_path)
    artifact_bytes = artifact_path.stat().st_size if artifact_path.is_file() else None

    def deployment_valid(report: dict[str, Any]) -> bool:
        verification = report.get("verification")
        artifact = report.get("artifact")
        approved_items = report.get("approved_items")
        return (
            type(expected_items) is int
            and expected_items > 0
            and type(approved_items) is int
            and approved_items == expected_items
            and report.get("deployment_type") == "production"
            and report.get("status") == "passed"
            and report.get("mode") == "apply"
            and report.get("applied") is True
            and isinstance(artifact, dict)
            and artifact.get("name") == artifact_path.name
            and artifact.get("sha256") == artifact_sha256
            and type(artifact.get("bytes")) is int
            and artifact.get("bytes") == artifact_bytes
            and isinstance(verification, dict)
            and verification.get("checksum_match") is True
            and verification.get("exact_krea2_namespace") is True
            and verification.get("impact_reload") is True
            and verification.get("queue_empty") is True
        )

    valid_deployments = [
        (path, report) for path, report in candidates if deployment_valid(report)
    ]
    selected = (
        valid_deployments[-1]
        if valid_deployments
        else (candidates[-1] if candidates else None)
    )
    evidence = [_relative(selected[0], root)] if selected else []
    actual = (
        {
            "deployment_id": selected[1].get("deployment_id"),
            "deployment_type": selected[1].get("deployment_type"),
            "status": selected[1].get("status"),
            "mode": selected[1].get("mode"),
            "applied": selected[1].get("applied"),
            "approved_items": selected[1].get("approved_items"),
            "artifact": selected[1].get("artifact"),
            "verification": {
                key: (selected[1].get("verification") or {}).get(key)
                for key in (
                    "checksum_match",
                    "exact_krea2_namespace",
                    "impact_reload",
                    "smoke_completed",
                    "queue_empty",
                )
                if isinstance(selected[1].get("verification"), dict)
            },
        }
        if selected
        else {"status": "missing"}
    )
    deploy = _criterion(
        "production_deployment",
        "deployment",
        bool(valid_deployments),
        actual,
        {
            "approved_items_match_manifest": True,
            "deployment_type": "production",
            "status": "passed",
            "mode": "apply",
            "applied": True,
            "artifact_matches_current_production": True,
            "checksum_match": True,
            "exact_namespace": True,
            "impact_reload": True,
            "queue_empty": True,
        },
        evidence,
        "Only a passed production apply matching the current manifest and production artifact may pass.",
    )
    smoke_valid = False
    smoke_seed_valid = False
    smoke_record_valid = False
    if valid_deployments:
        report = valid_deployments[-1][1]
        verification = report.get("verification", {})
        smoke = report.get("smoke")
        smoke_seed_valid = isinstance(smoke, dict) and type(smoke.get("seed")) is int
        smoke_record_valid = (
            isinstance(smoke, dict)
            and _safe_repo_relative_file(root, smoke.get("run_record")) is not None
        )
        smoke_valid = (
            verification.get("smoke_completed") is True
            and smoke_seed_valid
            and smoke_record_valid
        )
    smoke = _criterion(
        "production_smoke_test",
        "deployment",
        smoke_valid,
        {
            "deployment_valid": bool(valid_deployments),
            "smoke_completed": (
                (valid_deployments[-1][1].get("verification") or {}).get(
                    "smoke_completed"
                )
                is True
                if valid_deployments
                else False
            ),
            "seed_valid": smoke_seed_valid,
            "run_record_valid": smoke_record_valid,
        },
        {"smoke_completed": True, "seed_recorded": True, "run_record_exists": True},
        evidence,
        "Smoke evidence must belong to a valid current production deployment and reference a local run record.",
    )
    return [deploy, smoke]


def collect_completion(root: Path, stage: str = "final") -> dict[str, Any]:
    if stage not in {"predeploy", "final"}:
        raise ValueError(f"unsupported completion stage: {stage}")
    root = root.resolve()
    content, approved_items = _content_criteria(root)
    manifest_criterion, manifest = _manifest_criterion(root)
    reports = _discover_reports(root)
    criteria = [
        manifest_criterion,
        _release_criterion(
            root,
            manifest,
            manifest_catalog_ids_match=manifest_criterion["actual"][
                "catalog_item_ids_match"
            ],
        ),
        *_structured_report_criteria(root, reports),
        *content,
        _content_scale_criterion(root),
        _quality_metric_criterion(root, approved_items),
        _duplicate_criterion(root),
    ]
    if stage == "final":
        criteria.extend(_deployment_criteria(root, manifest))
    complete_count = sum(item["complete"] for item in criteria)
    return {
        "schema_version": 1,
        "stage": stage,
        "complete": complete_count == len(criteria),
        "summary": {
            "criteria": len(criteria),
            "complete": complete_count,
            "remaining": len(criteria) - complete_count,
        },
        "criteria": criteria,
    }


def _atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        temp.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a machine-readable plan.md completion report"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--stage",
        choices=("predeploy", "final"),
        default="final",
        help="evaluate pre-deployment gates or all final completion criteria",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return nonzero until every criterion passes",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        result = collect_completion(root, stage=args.stage)
        _atomic_write_json(output, result)
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(
        f"Completion criteria ({result['stage']}): "
        f"{result['summary']['complete']}/{result['summary']['criteria']} "
        f"passed; report={_relative(output, root)}"
    )
    if args.strict and not result["complete"]:
        print("ERROR: plan.md completion criteria remain incomplete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
