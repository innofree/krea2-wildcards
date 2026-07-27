#!/usr/bin/env python3
"""Run the local release pipeline without skipping production gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from check_completion_criteria import approved_runtime_catalog_inventory


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = Path("tests/reports/releases/latest.json")
PRODUCTION_MANIFEST = Path("wildcards-manifest.json")
PRODUCTION_RUNTIME_ROOT = Path("wildcards")
PRODUCTION_IMPACT = Path("build/impact-production/krea2_complete_pack.yaml")
PROGRESS_REPORT = Path("tests/reports/plan_progress.json")
PRODUCTION_DRY_RUN_EVIDENCE = Path(
    "tests/reports/deployments/production_v1-dry-run.json"
)


@dataclass(frozen=True)
class Stage:
    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class CommandOutcome:
    name: str
    argv: tuple[str, ...]
    returncode: int | None
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "command",
            "argv": list(self.argv),
            "returncode": self.returncode,
            "status": self.status,
        }


Runner = Callable[[Stage, Path], CommandOutcome]


def release_stages(deployment: str = "none") -> tuple[Stage, ...]:
    """Return the fixed, fail-fast release sequence."""

    if deployment == "apply":
        raise ValueError(
            "release runner is build-only; apply deployment must use the final deployment workflow"
        )
    if deployment not in {"none", "dry-run"}:
        raise ValueError(f"unsupported deployment mode: {deployment}")

    stages = [
        Stage(
            "catalog_generation",
            ("python3", "scripts/generate_catalog_expansion.py", "catalog/blueprints"),
        ),
        Stage("catalog_normalization", ("python3", "scripts/normalize_catalog.py", "catalog")),
        Stage("catalog_duplicates", ("python3", "scripts/check_duplicates.py", "catalog")),
        Stage(
            "catalog_conflicts",
            (
                "python3",
                "scripts/check_conflicts.py",
                "--catalog",
                "catalog/compatibility.yaml",
            ),
        ),
        Stage("catalog_v2_sync", ("python3", "scripts/sync_catalog_v2.py")),
        Stage("catalog_schema_v2", ("python3", "scripts/validate_catalog_v2.py")),
        Stage("sensitive_worktree", ("python3", "scripts/check_sensitive_data.py")),
        Stage("sensitive_history", ("python3", "scripts/check_sensitive_history.py")),
        Stage(
            "preview_build",
            (
                "python3",
                "scripts/build_runtime_yaml.py",
                "--include-status",
                "generated",
                "--include-status",
                "testing",
                "--include-status",
                "approved",
                "--output",
                "build/preview-wildcards",
            ),
        ),
        Stage(
            "preview_runtime_lint",
            ("python3", "scripts/lint_wildcards.py", "build/preview-wildcards"),
        ),
        Stage("test_suite", ("python3", "-m", "pytest")),
        # No --include-status is intentional: the compiler default is approved only.
        Stage(
            "production_build",
            ("python3", "scripts/build_runtime_yaml.py", "--output", "wildcards"),
        ),
        Stage("production_runtime_lint", ("python3", "scripts/lint_wildcards.py", "wildcards")),
        Stage(
            "production_impact_build",
            (
                "python3",
                "scripts/build_impact_yaml.py",
                "--source",
                str(PRODUCTION_RUNTIME_ROOT),
                "--output",
                str(PRODUCTION_IMPACT),
            ),
        ),
        Stage(
            "plan_progress",
            (
                "python3",
                "scripts/check_plan_progress.py",
                "--output",
                str(PROGRESS_REPORT),
            ),
        ),
    ]
    if deployment != "none":
        evidence = PRODUCTION_DRY_RUN_EVIDENCE
        argv = [
            "python3",
            "scripts/deploy_remote_wildcards.py",
            "--evidence",
            str(evidence),
        ]
        stages.append(Stage(f"deployment_{deployment}", tuple(argv)))
    return tuple(stages)


def run_stage(stage: Stage, root: Path) -> CommandOutcome:
    """Run a stage as argv without a shell and with output withheld from evidence."""

    try:
        result = subprocess.run(
            list(stage.argv),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
    except OSError:
        return CommandOutcome(stage.name, stage.argv, None, "failed")
    return CommandOutcome(
        stage.name,
        stage.argv,
        result.returncode,
        "passed" if result.returncode == 0 else "failed",
    )


def _relative_path(path: Path) -> str:
    pure = PurePosixPath(path.as_posix())
    if path.is_absolute() or ".." in pure.parts:
        raise ValueError("release paths must be relative and remain inside the repository")
    return pure.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def verify_approved_production(root: Path) -> dict[str, Any]:
    """Prove that the production manifest contains approved entries only."""

    manifest_path = root / PRODUCTION_MANIFEST
    manifest = _load_json(manifest_path)
    if manifest.get("included_statuses") != ["approved"]:
        raise ValueError("production manifest is not approved-only")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("production manifest contains no approved items")
    if any(not isinstance(item, dict) or item.get("status") != "approved" for item in items):
        raise ValueError("production manifest contains a non-approved item")
    raw_ids = [item.get("id") if isinstance(item, dict) else None for item in items]
    if any(not isinstance(item_id, str) or not item_id for item_id in raw_ids):
        raise ValueError("production manifest contains an invalid item ID")
    manifest_ids = set(raw_ids)
    if len(manifest_ids) != len(raw_ids):
        raise ValueError("production manifest contains duplicate item IDs")
    expected_ids, catalog_problems = approved_runtime_catalog_inventory(root)
    if catalog_problems:
        raise ValueError("approved runtime catalog inventory is invalid")
    if manifest_ids != expected_ids:
        raise ValueError(
            "production manifest item IDs do not match approval-policy-valid catalog runtime IDs"
        )
    item_count = manifest.get("item_count")
    prompt_count = manifest.get("prompt_count")
    if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count != len(items):
        raise ValueError("production manifest item count is inconsistent")
    if not isinstance(prompt_count, int) or isinstance(prompt_count, bool) or prompt_count < item_count:
        raise ValueError("production manifest prompt count is inconsistent")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("production manifest declares no canonical runtime files")
    runtime_files: list[str] = []
    for raw_file in files:
        if not isinstance(raw_file, str):
            raise ValueError("production manifest contains an invalid runtime file")
        pure = PurePosixPath(raw_file)
        if pure.is_absolute() or ".." in pure.parts or pure.suffix != ".yaml":
            raise ValueError("production manifest contains an unsafe runtime file")
        runtime_path = root / PRODUCTION_RUNTIME_ROOT.joinpath(*pure.parts)
        if not runtime_path.is_file():
            raise ValueError("production manifest references a missing runtime file")
        runtime_files.append(pure.as_posix())
    if len(set(runtime_files)) != len(runtime_files):
        raise ValueError("production manifest declares duplicate runtime files")
    return {
        "included_statuses": ["approved"],
        "item_count": item_count,
        "prompt_count": prompt_count,
        "runtime_files": sorted(runtime_files),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_records(root: Path, *, include_impact: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    paths = [PRODUCTION_MANIFEST]
    manifest = _load_json(root / PRODUCTION_MANIFEST)
    files = manifest.get("files", [])
    if not isinstance(files, list):
        raise ValueError("production manifest files must be a list")
    for raw_file in files:
        if not isinstance(raw_file, str):
            raise ValueError("production manifest contains an invalid runtime file")
        pure = PurePosixPath(raw_file)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("production manifest contains an unsafe runtime file")
        paths.append(PRODUCTION_RUNTIME_ROOT.joinpath(*pure.parts))
    if include_impact:
        paths.append(PRODUCTION_IMPACT)
    for relative in paths:
        path = root / relative
        if path.is_file():
            records.append(
                {
                    "path": _relative_path(relative),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    return records


def progress_record(root: Path) -> dict[str, Any] | None:
    path = root / PROGRESS_REPORT
    if not path.is_file():
        return None
    report = _load_json(path)
    targets = report.get("targets")
    if not isinstance(targets, list):
        raise ValueError("progress report targets must be a list")
    safe_targets = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("progress report target must be an object")
        safe_targets.append(
            {
                key: target.get(key)
                for key in ("id", "current", "target", "remaining", "complete")
            }
        )
    return {"complete": report.get("complete") is True, "targets": safe_targets}


def _release_id(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def orchestrate(
    *,
    root: Path = ROOT,
    evidence_path: Path = DEFAULT_EVIDENCE,
    deployment: str = "none",
    runner: Runner = run_stage,
) -> int:
    evidence_relative = Path(_relative_path(evidence_path))
    outcomes: list[CommandOutcome] = []
    production: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    failure: str | None = None

    for stage in release_stages(deployment):
        print(f"[{stage.name}] running")
        outcome = runner(stage, root)
        outcomes.append(outcome)
        if outcome.status != "passed":
            failure = stage.name
            print(
                f"ERROR: {stage.name} failed; subprocess details were redacted.",
                file=sys.stderr,
            )
            break
        print(f"[{stage.name}] passed")

        if stage.name == "production_build":
            try:
                production = verify_approved_production(root)
            except (OSError, ValueError, json.JSONDecodeError):
                failure = "approved_only_invariant"
                print(
                    "ERROR: approved-only production invariant failed; details were redacted.",
                    file=sys.stderr,
                )
                break
        elif stage.name == "plan_progress":
            try:
                progress = progress_record(root)
            except (OSError, ValueError, json.JSONDecodeError):
                failure = "plan_progress_evidence"
                print(
                    "ERROR: plan progress evidence validation failed; details were redacted.",
                    file=sys.stderr,
                )
                break

    passed = failure is None
    passed_stages = {outcome.name for outcome in outcomes if outcome.status == "passed"}
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "failed_stage": failure,
        "deployment": {
            "requested": deployment != "none",
            "mode": deployment,
            "applied": passed and deployment == "apply",
        },
        "outcomes": [outcome.as_dict() for outcome in outcomes],
        "production": production,
        "artifacts": (
            artifact_records(
                root,
                include_impact="production_impact_build" in passed_stages,
            )
            if production is not None
            else []
        ),
        "plan_progress": progress,
    }
    evidence["release_id"] = _release_id(evidence)
    atomic_write_json(root / evidence_relative, evidence)
    print(f"Release evidence: {evidence_relative.as_posix()}")
    return 0 if passed else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic local release gates; deployment is omitted by default"
    )
    deployment = parser.add_mutually_exclusive_group()
    deployment.add_argument(
        "--deploy",
        action="store_true",
        help="run the production deployment command in its default dry-run mode",
    )
    deployment.add_argument(
        "--apply",
        action="store_true",
        help="refused: use the separate final deployment workflow after predeploy gates",
    )
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.apply:
        print(
            "ERROR: release runner is build-only; run the separate final deployment workflow after predeploy gates",
            file=sys.stderr,
        )
        return 2
    mode = "dry-run" if args.deploy else "none"
    try:
        return orchestrate(evidence_path=args.evidence, deployment=mode)
    except (OSError, ValueError) as exc:
        print(f"ERROR: release setup failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
