from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from check_completion_criteria import PAIRWISE_TYPES, collect_completion


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_completion_criteria.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def approved_item(item_id: str, *, family: str, runtime_file: str, kind: str) -> dict[str, object]:
    return {
        "family": family,
        "runtime": {"file": runtime_file, "path": ["krea2", "test", item_id]},
        "generation": {"kind": kind},
        "validation": {
            "status": "approved",
            "tested_seeds": 5,
            "prompt_adherence": 4,
            "style_fidelity": 3,
            "stability": 3,
            "compatibility": 3,
            "critical_failures": 0,
        },
    }


def complete_repository(root: Path) -> None:
    styles = {
        f"style_{index}": approved_item(
            f"style_{index}", family="style_pack", runtime_file="krea2/style/complete_pack.yaml", kind="style_pack"
        )
        for index in range(150)
    }
    artists = {
        f"artist_{index}": approved_item(
            f"artist_{index}", family="artist_signature", runtime_file="krea2/artist_signature/modern.yaml", kind="artist_signature"
        )
        for index in range(200)
    }
    write_yaml(root / "catalog/art_styles.yaml", {"items": styles})
    write_yaml(
        root / "catalog/style_expansion.yaml",
        {"items": {f"generated_style_{index}": {} for index in range(50)}},
    )
    artists.update({f"generated_artist_{index}": {} for index in range(100)})
    write_yaml(root / "catalog/artists.yaml", {"items": artists})
    scale_catalogs = {
        "media_rendering.yaml": 150,
        "linework_coloring.yaml": 300,
        "character_designs.yaml": 400,
        "hair_designs.yaml": 250,
        "fashion.yaml": 500,
        "poses.yaml": 350,
        "cameras.yaml": 250,
        "lighting.yaml": 250,
        "backgrounds.yaml": 400,
        "effects.yaml": 200,
        "presets.yaml": 200,
    }
    for catalog_name, count in scale_catalogs.items():
        prefix = catalog_name.removesuffix(".yaml")
        write_yaml(
            root / "catalog" / catalog_name,
            {"items": {f"{prefix}_{index}": {} for index in range(count)}},
        )
    runtime = root / "wildcards/krea2/style/complete_pack.yaml"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text("krea2:\n  style:\n    complete_pack:\n      all: [test]\n", encoding="utf-8")
    approved_artist_ids = [
        key for key, item in artists.items() if (item.get("validation") or {}).get("status") == "approved"
    ]
    items = [
        {"id": key, "status": "approved"}
        for key in [*styles, *approved_artist_ids]
    ]
    write_json(
        root / "wildcards-manifest.json",
        {"included_statuses": ["approved"], "item_count": 350, "prompt_count": 350, "files": ["krea2/style/complete_pack.yaml"], "items": items},
    )
    stages = [
        "catalog_generation", "catalog_normalization", "catalog_duplicates", "catalog_conflicts",
        "catalog_v2_sync", "catalog_schema_v2", "sensitive_worktree", "sensitive_history",
        "preview_build", "preview_runtime_lint",
        "test_suite", "production_build", "production_runtime_lint", "production_impact_build", "plan_progress",
    ]
    write_json(
        root / "tests/reports/releases/latest.json",
        {"status": "passed", "outcomes": [{"name": name, "status": "passed", "returncode": 0} for name in stages], "production": {"item_count": 350, "prompt_count": 350}},
    )
    write_json(
        root / "tests/reports/static_audit_v0_5.json",
        {"catalog": {"total_items": 3750}, "duplicates": {"exact_duplicates": 5, "near_duplicates": 5}},
    )
    common = {"schema_version": 1, "status": "passed", "complete": True}
    reports = {
        "runtime.json": {**common, "report_type": "runtime_coverage", "runtime_files_expected": 1, "runtime_files_loaded": 1, "wildcard_paths_expected": 350, "wildcard_paths_resolved": 350, "unresolved_wildcards": 0, "yaml_syntax_errors": 0, "novelai_brace_conflicts": 0, "catalog_runtime_separated": True, "final_prompt_logs_saved": True},
        "single.json": {**common, "report_type": "single_axis_coverage", "tested_axes": ["linework", "coloring"], "total_cases": 2, "critical_failures": 0},
        "abc.json": {**common, "report_type": "artist_abc_coverage", "modes": ["native_name", "visual_signature", "hybrid"], "artist_count": 2, "recommended_modes_recorded": 2, "critical_failures": 0},
        "pairwise.json": {**common, "report_type": "pairwise_coverage", "covered_pair_types": sorted(PAIRWISE_TYPES), "total_cases": 6, "critical_failures": 0},
        "presets.json": {**common, "report_type": "preset_conflict_audit", "presets_tested": 100, "critical_conflicts": 0},
        "random.json": {**common, "report_type": "random_utility", "sample_count": 20, "usable_count": 15, "utility_rate": 0.75},
        "benchmark.json": {**common, "report_type": "krea2_turbo_benchmark", "model": "krea2_turbo_mxfp8", "distinct_seeds": 5, "sample_count": 350, "metrics": {"prompt_adherence": 4.1}},
    }
    for name, report in reports.items():
        write_json(root / "tests/reports/completion" / name, report)
    smoke_path = root / "tests/reports/production_smoke/runs/test/run.json"
    write_json(smoke_path, {"seed": 6006})
    write_json(
        root / "tests/reports/deployments/production_v1.json",
        {"deployment_id": "production_v1", "status": "passed", "approved_items": 350, "verification": {"checksum_match": True, "exact_krea2_namespace": True, "impact_reload": True, "smoke_completed": True, "queue_empty": True}, "smoke": {"seed": 6006, "run_record": "tests/reports/production_smoke/runs/test/run.json"}},
    )


def by_id(result: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["id"]: item for item in result["criteria"]}  # type: ignore[index]


def test_collect_completion_accepts_only_complete_cross_checked_evidence(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    result = collect_completion(tmp_path)

    assert result["complete"] is True
    assert result["summary"]["remaining"] == 0
    assert by_id(result)["approved_style_packs"]["actual"] == 150
    assert by_id(result)["approved_canonical_artist_signatures"]["actual"] == 200


def test_missing_and_stale_evidence_cannot_pass(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    (tmp_path / "tests/reports/completion/pairwise.json").unlink()
    deployment = tmp_path / "tests/reports/deployments/production_v1.json"
    value = json.loads(deployment.read_text(encoding="utf-8"))
    value["approved_items"] = 349
    write_json(deployment, value)

    result = collect_completion(tmp_path)
    criteria = by_id(result)

    assert result["complete"] is False
    assert criteria["pairwise_combination_coverage"]["complete"] is False
    assert criteria["production_deployment"]["complete"] is False
    assert criteria["production_smoke_test"]["complete"] is False


def test_non_strict_writes_incomplete_report_and_only_strict_fails(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    normal = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    strict = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output), "--strict"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert normal.returncode == 0
    assert strict.returncode == 1
    assert json.loads(output.read_text(encoding="utf-8"))["complete"] is False


def test_unmeasured_or_inconsistent_utility_rate_cannot_pass(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    path = tmp_path / "tests/reports/completion/random.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["utility_rate"] = 0.9
    write_json(path, report)

    criterion = by_id(collect_completion(tmp_path))["random_generation_utility_rate"]
    assert criterion["complete"] is False


def test_approved_label_without_five_seed_policy_does_not_count(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    path = tmp_path / "catalog/art_styles.yaml"
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalog["items"]["style_149"]["validation"]["tested_seeds"] = 3
    write_yaml(path, catalog)

    criterion = by_id(collect_completion(tmp_path))["approved_style_packs"]
    assert criterion["actual"] == 149
    assert criterion["complete"] is False


def test_initial_scale_category_shortage_cannot_pass(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    path = tmp_path / "catalog/presets.yaml"
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalog["items"].pop(next(iter(catalog["items"])))
    write_yaml(path, catalog)

    criterion = by_id(collect_completion(tmp_path))["content_scale_targets"]
    assert criterion["actual"]["preset_items"] == 199
    assert criterion["complete"] is False


def test_malformed_recognized_report_is_incomplete_not_fatal(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    write_json(
        tmp_path / "tests/reports/completion/pairwise.json",
        {
            "schema_version": 1,
            "report_type": "pairwise_coverage",
            "status": "passed",
            "complete": True,
            "covered_pair_types": [{"invalid": "unhashable"}],
            "total_cases": 6,
            "critical_failures": 0,
        },
    )

    criterion = by_id(collect_completion(tmp_path))["pairwise_combination_coverage"]
    assert criterion["complete"] is False
