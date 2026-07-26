from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import run_release
from run_release import CommandOutcome, Stage


def test_release_sequence_contains_every_required_gate_and_approved_build() -> None:
    stages = run_release.release_stages()
    names = [stage.name for stage in stages]

    assert names[:8] == [
        "catalog_generation",
        "catalog_normalization",
        "catalog_duplicates",
        "catalog_conflicts",
        "catalog_v2_sync",
        "catalog_schema_v2",
        "sensitive_worktree",
        "sensitive_history",
    ]
    assert "preview_runtime_lint" in names
    assert "test_suite" in names
    assert "production_runtime_lint" in names
    assert "plan_progress" in names
    impact = stages[names.index("production_impact_build")]
    assert ("--source", "wildcards") == impact.argv[2:4]
    production = stages[names.index("production_build")]
    assert production.argv == (
        "python3",
        "scripts/build_runtime_yaml.py",
        "--output",
        "wildcards",
    )
    assert "--include-status" not in production.argv
    assert not any(name.startswith("deployment_") for name in names)


def test_deployment_is_dry_run_by_default_and_apply_is_explicit() -> None:
    dry_run = run_release.release_stages("dry-run")[-1]
    apply = run_release.release_stages("apply")[-1]

    assert dry_run.name == "deployment_dry-run"
    assert dry_run.argv == ("python3", "scripts/deploy_remote_wildcards.py")
    assert apply.name == "deployment_apply"
    assert apply.argv[-1] == "--apply"


def test_run_stage_uses_argv_without_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "safe", "")

    monkeypatch.setattr(run_release.subprocess, "run", fake_run)
    outcome = run_release.run_stage(Stage("gate", ("python3", "script.py")), tmp_path)

    assert outcome.status == "passed"
    assert observed["argv"] == ["python3", "script.py"]
    assert observed["shell"] is False
    assert observed["cwd"] == tmp_path


def test_failure_is_fail_fast_and_does_not_persist_subprocess_output(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    secret = "operator@example.invalid:/private/location"

    def failing_runner(stage: Stage, root: Path) -> CommandOutcome:
        calls.append(stage.name)
        # The orchestrator deliberately has no field for stdout/stderr.
        _ = secret, root
        return CommandOutcome(stage.name, stage.argv, 9, "failed")

    evidence = Path("reports/release.json")
    result = run_release.orchestrate(
        root=tmp_path,
        evidence_path=evidence,
        runner=failing_runner,
    )

    assert result == 1
    assert calls == ["catalog_generation"]
    raw = (tmp_path / evidence).read_text(encoding="utf-8")
    assert secret not in raw
    document = json.loads(raw)
    assert document["failed_stage"] == "catalog_generation"
    assert document["outcomes"][0]["returncode"] == 9
    assert document["artifacts"] == []


def test_production_manifest_must_be_approved_only(tmp_path: Path) -> None:
    manifest = {
        "included_statuses": ["approved", "testing"],
        "item_count": 1,
        "prompt_count": 1,
        "items": [{"status": "approved"}],
        "files": ["krea2/style/complete_pack.yaml"],
    }
    (tmp_path / "wildcards-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="approved-only"):
        run_release.verify_approved_production(tmp_path)


def test_release_evidence_path_must_remain_relative(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relative"):
        run_release.orchestrate(root=tmp_path, evidence_path=tmp_path / "release.json")


def test_atomic_evidence_has_relative_artifact_paths(tmp_path: Path) -> None:
    manifest = {
        "included_statuses": ["approved"],
        "item_count": 1,
        "prompt_count": 1,
        "files": ["krea2/style/complete_pack.yaml"],
        "items": [{"status": "approved"}],
    }
    (tmp_path / "wildcards/krea2/style").mkdir(parents=True)
    (tmp_path / "build/impact-production").mkdir(parents=True)
    (tmp_path / "wildcards-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "wildcards/krea2/style/complete_pack.yaml").write_text("krea2: {}\n")
    (tmp_path / "build/impact-production/krea2_complete_pack.yaml").write_text(
        "krea2: {}\n"
    )
    progress = {"complete": False, "targets": []}
    (tmp_path / "tests/reports").mkdir(parents=True)
    (tmp_path / "tests/reports/plan_progress.json").write_text(json.dumps(progress))

    def passing_runner(stage: Stage, root: Path) -> CommandOutcome:
        return CommandOutcome(stage.name, stage.argv, 0, "passed")

    evidence = Path("reports/release.json")
    assert (
        run_release.orchestrate(
            root=tmp_path,
            evidence_path=evidence,
            runner=passing_runner,
        )
        == 0
    )
    document = json.loads((tmp_path / evidence).read_text(encoding="utf-8"))

    assert document["production"]["included_statuses"] == ["approved"]
    assert document["plan_progress"] == {"complete": False, "targets": []}
    assert all(not Path(item["path"]).is_absolute() for item in document["artifacts"])
    assert all(len(item["sha256"]) == 64 for item in document["artifacts"])
    assert not list((tmp_path / "reports").glob(".release.json.*"))
