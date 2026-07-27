from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from check_completion_criteria import PAIRWISE_TYPES, collect_completion
from common import item_prompts, load_yaml, normalized_phrase
from export_phase6_matrix import PHASE6_PROFILE_SHA256


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_completion_criteria.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def approved_item(
    item_id: str, *, family: str, runtime_file: str, kind: str
) -> dict[str, object]:
    prompt = f"A complete visual prompt for {item_id}."
    return {
        "prompt": prompt,
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
            "evaluated_prompt_sha256": hashlib.sha256(
                prompt.encode("utf-8")
            ).hexdigest(),
        },
    }


def complete_repository(root: Path) -> None:
    styles = {
        f"style_{index}": approved_item(
            f"style_{index}",
            family="style_pack",
            runtime_file="krea2/style/complete_pack.yaml",
            kind="style_pack",
        )
        for index in range(150)
    }
    artists = {
        f"artist_{index}": approved_item(
            f"artist_{index}",
            family="artist_signature",
            runtime_file="krea2/artist_signature/modern.yaml",
            kind="artist_signature",
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
    runtime.write_text(
        "krea2:\n  style:\n    complete_pack:\n      all: [test]\n", encoding="utf-8"
    )
    approved_artist_ids = [
        key
        for key, item in artists.items()
        if (item.get("validation") or {}).get("status") == "approved"
    ]
    items = [
        {"id": key, "status": "approved"} for key in [*styles, *approved_artist_ids]
    ]
    manifest_path = root / "wildcards-manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": 1,
            "included_statuses": ["approved"],
            "item_count": 350,
            "prompt_count": 350,
            "files": ["krea2/style/complete_pack.yaml"],
            "items": items,
        },
    )
    production_artifact = root / "build/impact-production/krea2_complete_pack.yaml"
    production_artifact.parent.mkdir(parents=True, exist_ok=True)
    production_artifact.write_text(
        "krea2:\n  complete_pack:\n    all: [test]\n", encoding="utf-8"
    )
    production_bytes = production_artifact.read_bytes()
    stages = [
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
    ]
    write_json(
        root / "tests/reports/releases/latest.json",
        {
            "status": "passed",
            "outcomes": [
                {"name": name, "status": "passed", "returncode": 0} for name in stages
            ],
            "production": {"item_count": 350, "prompt_count": 350},
        },
    )
    write_json(
        root / "tests/reports/static_audit_v0_5.json",
        {
            "catalog": {
                "total_items": 3750,
                "prompt_digest_sha256": hashlib.sha256(
                    json.dumps(
                        sorted(
                            (
                                path.name,
                                item_id,
                                normalized_phrase(prompt),
                            )
                            for path in sorted((root / "catalog").glob("*.yaml"))
                            for item_id, item in (
                                load_yaml(path).get("items", {}) or {}
                            ).items()
                            for prompt in item_prompts(item)
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            },
            "duplicates": {"exact_duplicates": 5, "near_duplicates": 5},
        },
    )
    common = {"schema_version": 1, "status": "passed", "complete": True}
    phase6_common = {
        **common,
        "prompt_profile_sha256": PHASE6_PROFILE_SHA256,
    }
    single_axis_items = [f"single_axis_item_{index:03d}" for index in range(96)]
    prompt_log = root / "tests/reports/runtime_prompt/run.json"
    write_json(prompt_log, {"seed": 6006})
    reports = {
        "runtime.json": {
            **common,
            "report_type": "runtime_coverage",
            "manifest": "wildcards-manifest.json",
            "manifest_sha256": hashlib.sha256(
                (root / "wildcards-manifest.json").read_bytes()
            ).hexdigest(),
            "production_artifact": (
                "build/impact-production/krea2_complete_pack.yaml"
            ),
            "production_artifact_sha256": hashlib.sha256(
                production_bytes
            ).hexdigest(),
            "production_artifact_bytes": len(production_bytes),
            "prompt_logs": [
                {
                    "path": "tests/reports/runtime_prompt/run.json",
                    "sha256": hashlib.sha256(prompt_log.read_bytes()).hexdigest(),
                }
            ],
            "runtime_files_expected": 1,
            "runtime_files_loaded": 1,
            "wildcard_paths_expected": 350,
            "wildcard_paths_resolved": 350,
            "all_runtime_leaves_resolved": True,
            "unexpected_runtime_leaf_paths": 0,
            "missing_runtime_leaf_paths": 0,
            "impact_paths_expected": 350,
            "impact_paths_resolved": 350,
            "impact_adapter_exact": True,
            "unresolved_wildcards": 0,
            "final_prompt_unresolved_wildcards": 0,
            "yaml_syntax_errors": 0,
            "novelai_brace_conflicts": 0,
            "novelai_bracket_conflicts": 0,
            "final_prompt_brace_conflicts": 0,
            "final_prompt_bracket_conflicts": 0,
            "catalog_runtime_separated": True,
            "final_prompt_logs_saved": True,
        },
        "single.json": {
            **phase6_common,
            "report_type": "single_axis_coverage",
            "tested_axes": [
                "background",
                "camera",
                "character_design",
                "lighting",
                "linework_coloring",
                "pose",
            ],
            "total_cases": 96,
            "passed_item_ids": single_axis_items,
            "critical_failures": 0,
        },
        "calibration.json": {
            **phase6_common,
            "report_type": "phase6_prompt_profile_calibration",
            "matrix_jobs": 69,
            "distinct_seeds": 3,
            "total_cases": 23,
            "critical_failures": 0,
        },
        "abc.json": {
            **common,
            "report_type": "artist_abc_coverage",
            "modes": ["native_name", "visual_signature", "hybrid"],
            "artist_count": 8,
            "recommended_modes_recorded": 8,
            "critical_failures": 0,
        },
        "pairwise.json": {
            **phase6_common,
            "report_type": "pairwise_coverage",
            "covered_pair_types": sorted(PAIRWISE_TYPES),
            "total_cases": 96,
            "right_item_ids": single_axis_items,
            "critical_failures": 0,
        },
        "presets.json": {
            **phase6_common,
            "report_type": "preset_conflict_audit",
            "presets_tested": 100,
            "critical_conflicts": 0,
        },
        "random.json": {
            **phase6_common,
            "report_type": "random_utility",
            "sample_count": 20,
            "usable_count": 15,
            "utility_rate": 0.75,
        },
        "benchmark.json": {
            **phase6_common,
            "report_type": "krea2_turbo_benchmark",
            "model": "krea2_turbo_mxfp8",
            "distinct_seeds": 5,
            "sample_count": 350,
            "metrics": {"prompt_adherence": 4.1},
        },
    }
    for name, report in reports.items():
        if report["report_type"] != "runtime_coverage":
            stem = Path(name).stem
            matrix = root / f"tests/prompt_matrix/{stem}.jsonl"
            scored = root / f"tests/reports/completion_inputs/{stem}.csv"
            matrix.parent.mkdir(parents=True, exist_ok=True)
            scored.parent.mkdir(parents=True, exist_ok=True)
            matrix.write_text(f"matrix evidence for {stem}\n", encoding="utf-8")
            scored.write_text(f"scored evidence for {stem}\n", encoding="utf-8")
            report.update(
                {
                    "matrix_path": f"tests/prompt_matrix/{stem}.jsonl",
                    "matrix_sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
                    "scored_path": f"tests/reports/completion_inputs/{stem}.csv",
                    "scored_sha256": hashlib.sha256(scored.read_bytes()).hexdigest(),
                }
            )
        write_json(root / "tests/reports/completion" / name, report)
    smoke_path = root / "tests/reports/production_smoke/runs/test/run.json"
    deployment_nonce = "d" * 32
    deployed_at = "2026-07-27T12:00:00Z"
    started_at = "2026-07-27T12:00:01Z"
    completed_at = "2026-07-27T12:00:02Z"
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    artifact_digest = hashlib.sha256(production_bytes).hexdigest()
    deployment_binding = {
        "deployment_id": "production_v1",
        "deployment_nonce": deployment_nonce,
        "artifact_sha256": artifact_digest,
        "manifest_sha256": manifest_digest,
        "deployed_at_utc": deployed_at,
    }
    write_json(
        smoke_path,
        {
            "schema_version": 2,
            "seed": 6006,
            "remote": "private_comfyui",
            "resolved_prompt": "A resolved adult portrait with clean illustrated detail.",
            "images": ["tests/reports/production_smoke/runs/test/image_01.png"],
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "deployment": deployment_binding,
        },
    )
    write_json(
        root / "tests/reports/deployments/production_v1.json",
        {
            "schema_version": 2,
            "deployment_id": "production_v1",
            "deployment_type": "production",
            "status": "passed",
            "mode": "apply",
            "applied": True,
            "approved_items": 350,
            "manifest": {
                "name": "wildcards-manifest.json",
                "sha256": manifest_digest,
                "bytes": manifest_path.stat().st_size,
            },
            "artifact": {
                "name": "krea2_complete_pack.yaml",
                "sha256": artifact_digest,
                "bytes": len(production_bytes),
                "wildcard_path_count": 351,
            },
            "deployment": {
                "nonce": deployment_nonce,
                "completed_at_utc": deployed_at,
            },
            "verification": {
                "checksum_match": True,
                "exact_krea2_namespace": True,
                "impact_reload": True,
                "smoke_completed": True,
                "queue_empty": True,
            },
            "smoke": {
                "seed": 6006,
                "run_record": "tests/reports/production_smoke/runs/test/run.json",
                "run_record_sha256": hashlib.sha256(smoke_path.read_bytes()).hexdigest(),
                "deployment_id": "production_v1",
                "deployment_nonce": deployment_nonce,
                "artifact_sha256": artifact_digest,
                "manifest_sha256": manifest_digest,
                "started_at_utc": started_at,
                "completed_at_utc": completed_at,
            },
        },
    )


def by_id(result: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["id"]: item for item in result["criteria"]}  # type: ignore[index]


def test_collect_completion_accepts_only_complete_cross_checked_evidence(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    result = collect_completion(tmp_path)

    assert result["complete"] is True
    assert result["stage"] == "final"
    assert result["summary"]["remaining"] == 0
    assert by_id(result)["approved_style_packs"]["actual"] == 150
    assert by_id(result)["approved_canonical_artist_signatures"]["actual"] == 200


def test_manifest_requires_exact_approval_policy_valid_catalog_item_ids(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    manifest_path = tmp_path / "wildcards-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["items"][-1]["id"] = "unexpected_item"
    write_json(manifest_path, manifest)

    criteria = by_id(collect_completion(tmp_path))

    assert criteria["production_runtime_manifest"]["complete"] is False
    assert criteria["release_functional_gates"]["complete"] is False
    actual = criteria["production_runtime_manifest"]["actual"]
    assert actual["missing_catalog_item_ids"] == ["artist_199"]
    assert actual["unexpected_manifest_item_ids"] == ["unexpected_item"]


def test_artist_prompt_mutation_invalidates_approval_completion(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    artists_path = tmp_path / "catalog/artists.yaml"
    artists = yaml.safe_load(artists_path.read_text(encoding="utf-8"))
    artists["items"]["artist_0"]["prompt"] += " Mutated after evaluation."
    write_yaml(artists_path, artists)

    criterion = by_id(collect_completion(tmp_path))[
        "approved_canonical_artist_signatures"
    ]

    assert criterion["complete"] is False
    assert criterion["actual"] == 199


def test_two_hundred_matching_artist_prompt_digests_pass_artist_gate(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)

    criterion = by_id(collect_completion(tmp_path))[
        "approved_canonical_artist_signatures"
    ]

    assert criterion["complete"] is True
    assert criterion["actual"] == 200


def test_predeploy_excludes_only_deployment_and_smoke(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    (tmp_path / "tests/reports/deployments/production_v1.json").unlink()

    predeploy = collect_completion(tmp_path, stage="predeploy")
    final = collect_completion(tmp_path, stage="final")

    assert predeploy["stage"] == "predeploy"
    assert predeploy["complete"] is True
    assert predeploy["summary"]["criteria"] == 14
    assert {item["id"] for item in predeploy["criteria"]}.isdisjoint(
        {"production_deployment", "production_smoke_test"}
    )
    assert final["stage"] == "final"
    assert final["complete"] is False
    assert final["summary"]["criteria"] == 16


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


def test_runtime_and_phase6_digest_drift_cannot_pass(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    (tmp_path / "wildcards-manifest.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "tests/prompt_matrix/single.jsonl").write_text(
        "changed matrix\n", encoding="utf-8"
    )

    criteria = by_id(collect_completion(tmp_path))

    assert criteria["runtime_resolution_coverage"]["complete"] is False
    assert criteria["single_axis_coverage"]["complete"] is False


@pytest.mark.parametrize("variant", ["preview", "dry-run"])
def test_preview_or_dry_run_deployment_cannot_pass(
    tmp_path: Path, variant: str
) -> None:
    complete_repository(tmp_path)
    path = tmp_path / "tests/reports/deployments/production_v1.json"
    deployment = json.loads(path.read_text(encoding="utf-8"))
    if variant == "preview":
        deployment["deployment_type"] = "preview"
    else:
        deployment["status"] = "dry-run"
        deployment["mode"] = "dry-run"
        deployment["applied"] = False
    write_json(path, deployment)

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is False
    assert criteria["production_smoke_test"]["complete"] is False


def test_production_artifact_change_invalidates_deployment_and_smoke(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    artifact = tmp_path / "build/impact-production/krea2_complete_pack.yaml"
    artifact.write_text(artifact.read_text(encoding="utf-8") + "changed: true\n")

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is False
    assert criteria["production_smoke_test"]["complete"] is False


def test_production_manifest_change_invalidates_deployment_and_smoke(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    manifest = tmp_path / "wildcards-manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is False
    assert criteria["production_smoke_test"]["complete"] is False


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("smoke", "artifact_sha256", "e" * 64),
        ("smoke", "deployment_id", "another_deployment"),
        ("run_binding", "deployment_nonce", "e" * 32),
        ("run", "started_at_utc", "2026-07-27T11:59:59Z"),
    ],
)
def test_smoke_binding_digest_and_chronology_are_fail_closed(
    tmp_path: Path, target: str, field: str, value: str
) -> None:
    complete_repository(tmp_path)
    evidence_path = tmp_path / "tests/reports/deployments/production_v1.json"
    run_path = tmp_path / "tests/reports/production_smoke/runs/test/run.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if target == "smoke":
        evidence["smoke"][field] = value
    elif target == "run_binding":
        run["deployment"][field] = value
        write_json(run_path, run)
        evidence["smoke"]["run_record_sha256"] = hashlib.sha256(
            run_path.read_bytes()
        ).hexdigest()
    else:
        run[field] = value
        write_json(run_path, run)
        evidence["smoke"]["run_record_sha256"] = hashlib.sha256(
            run_path.read_bytes()
        ).hexdigest()
        evidence["smoke"][field] = value
    write_json(evidence_path, evidence)

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is True
    assert criteria["production_smoke_test"]["complete"] is False


def test_smoke_run_record_mutation_invalidates_record_digest(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    run_path = tmp_path / "tests/reports/production_smoke/runs/test/run.json"
    run_path.write_text(run_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    criterion = by_id(collect_completion(tmp_path))["production_smoke_test"]
    assert criterion["complete"] is False
    assert criterion["actual"]["run_record_sha256_valid"] is False


def test_smoke_path_traversal_cannot_pass_even_when_target_exists(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    write_json(tmp_path / "tests/outside-run.json", {"seed": 6006})
    path = tmp_path / "tests/reports/deployments/production_v1.json"
    deployment = json.loads(path.read_text(encoding="utf-8"))
    deployment["smoke"]["run_record"] = "tests/reports/../outside-run.json"
    write_json(path, deployment)

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is True
    assert criteria["production_smoke_test"]["complete"] is False
    assert criteria["production_smoke_test"]["actual"]["run_record_valid"] is False


def test_smoke_symlink_cannot_pass(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    real_run = tmp_path / "tests/reports/production_smoke/runs/test/run.json"
    linked_run = real_run.with_name("linked-run.json")
    linked_run.symlink_to(real_run.name)
    path = tmp_path / "tests/reports/deployments/production_v1.json"
    deployment = json.loads(path.read_text(encoding="utf-8"))
    deployment["smoke"]["run_record"] = (
        "tests/reports/production_smoke/runs/test/linked-run.json"
    )
    write_json(path, deployment)

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is True
    assert criteria["production_smoke_test"]["complete"] is False


def test_boolean_smoke_seed_is_not_an_integer_seed(tmp_path: Path) -> None:
    complete_repository(tmp_path)
    path = tmp_path / "tests/reports/deployments/production_v1.json"
    deployment = json.loads(path.read_text(encoding="utf-8"))
    deployment["smoke"]["seed"] = True
    write_json(path, deployment)

    criteria = by_id(collect_completion(tmp_path))
    assert criteria["production_deployment"]["complete"] is True
    assert criteria["production_smoke_test"]["complete"] is False
    assert criteria["production_smoke_test"]["actual"]["seed_valid"] is False


def test_non_strict_writes_incomplete_report_and_only_strict_fails(
    tmp_path: Path,
) -> None:
    output = tmp_path / "result.json"
    normal = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    strict = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--strict",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert normal.returncode == 0
    assert strict.returncode == 1
    assert json.loads(output.read_text(encoding="utf-8"))["complete"] is False


def test_predeploy_cli_strict_writes_stage_and_ignores_only_deployment(
    tmp_path: Path,
) -> None:
    complete_repository(tmp_path)
    (tmp_path / "tests/reports/deployments/production_v1.json").unlink()
    output = tmp_path / "predeploy.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--stage",
            "predeploy",
            "--strict",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert report["stage"] == "predeploy"
    assert report["complete"] is True


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


@pytest.mark.parametrize(
    ("filename", "field", "value", "criterion_id"),
    [
        ("single.json", "total_cases", 3, "single_axis_coverage"),
        ("abc.json", "artist_count", 7, "artist_abc_coverage"),
        ("pairwise.json", "total_cases", 95, "pairwise_combination_coverage"),
        ("presets.json", "presets_tested", 99, "preset_critical_conflicts"),
        ("random.json", "sample_count", 19, "random_generation_utility_rate"),
        ("benchmark.json", "distinct_seeds", 4, "krea2_turbo_benchmark"),
    ],
)
def test_representative_phase6_minimums_are_enforced(
    tmp_path: Path,
    filename: str,
    field: str,
    value: int,
    criterion_id: str,
) -> None:
    complete_repository(tmp_path)
    path = tmp_path / "tests/reports/completion" / filename
    report = json.loads(path.read_text(encoding="utf-8"))
    report[field] = value
    if filename == "random.json":
        report["usable_count"] = min(report["usable_count"], value)
        report["utility_rate"] = report["usable_count"] / value
    if filename == "abc.json":
        report["recommended_modes_recorded"] = value
    write_json(path, report)
    assert by_id(collect_completion(tmp_path))[criterion_id]["complete"] is False
