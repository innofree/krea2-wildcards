#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from deploy_remote_wildcards import (
    DEFAULT_MANIFEST,
    DEFAULT_SOURCE,
    approved_manifest_item_count,
    atomic_write_evidence,
    deployment_id_from_evidence,
    load_json_object,
    sha256,
)


EVIDENCE_FIELDS = {
    "schema_version",
    "deployment_id",
    "deployment_type",
    "status",
    "remote",
    "mode",
    "applied",
    "approved_items",
    "manifest",
    "artifact",
    "deployment",
    "verification",
    "smoke",
}
MANIFEST_FIELDS = {"name", "sha256", "bytes"}
ARTIFACT_FIELDS = {"name", "sha256", "bytes", "wildcard_path_count"}
DEPLOYMENT_FIELDS = {"nonce", "completed_at_utc"}
VERIFICATION_FIELDS = {
    "checksum_match",
    "exact_krea2_namespace",
    "impact_reload",
    "smoke_completed",
    "queue_empty",
}
WILDCARD_RE = re.compile(r"__[A-Za-z0-9][A-Za-z0-9_./-]*__")
URL_RE = re.compile(r"(?:https?|ssh)://", re.IGNORECASE)
HOME_RE = re.compile(r"(?:/home/|/Users/)[A-Za-z0-9_.-]+")
ACCOUNT_RE = re.compile(
    r"(?<![<\w])[a-z_][a-z0-9_.-]*@[a-z0-9][a-z0-9.-]+", re.IGNORECASE
)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
NONCE_RE = re.compile(r"[0-9a-f]{32}")
UTC_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z"
)


def _safe_repo_file(root: Path, relative: Path, *, label: str) -> tuple[Path, str]:
    pure = PurePosixPath(relative.as_posix())
    if relative.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"{label} must be a repository-relative path")
    base = root.resolve()
    candidate = (base / relative).resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the repository") from exc
    if not candidate.is_file():
        raise ValueError(f"{label} must reference an existing file")
    return candidate, pure.as_posix()


def _safe_repo_directory(root: Path, relative: Path, *, label: str) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if relative.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"{label} must be a repository-relative path")
    base = root.resolve()
    current = base
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symbolic link")
    candidate = current.resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the repository") from exc
    if not candidate.is_dir():
        raise ValueError(f"{label} must reference an existing directory")
    return candidate


def _require_current_path(path: Path, expected: Path, *, label: str) -> None:
    if PurePosixPath(path.as_posix()) != PurePosixPath(expected.as_posix()):
        raise ValueError(f"{label} must reference the current production file")


def _validate_evidence_shape(document: dict[str, Any], evidence_path: Path) -> None:
    if set(document) != EVIDENCE_FIELDS or document.get("schema_version") != 2:
        raise ValueError("deployment evidence schema is invalid")
    if document.get("deployment_id") != deployment_id_from_evidence(evidence_path):
        raise ValueError("deployment evidence id does not match its filename")
    if (
        document.get("deployment_type") != "production"
        or document.get("status") != "passed"
        or document.get("mode") != "apply"
        or document.get("applied") is not True
        or document.get("remote") != "private_comfyui"
    ):
        raise ValueError("deployment evidence is not a passed production apply")
    approved_items = document.get("approved_items")
    if type(approved_items) is not int or approved_items < 1:
        raise ValueError("deployment approved item evidence is invalid")
    artifact = document.get("artifact")
    manifest = document.get("manifest")
    deployment = document.get("deployment")
    verification = document.get("verification")
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("deployment manifest evidence is invalid")
    if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS:
        raise ValueError("deployment artifact evidence is invalid")
    if not isinstance(deployment, dict) or set(deployment) != DEPLOYMENT_FIELDS:
        raise ValueError("deployment identity evidence is invalid")
    if (
        not isinstance(deployment.get("nonce"), str)
        or not NONCE_RE.fullmatch(deployment["nonce"])
        or not isinstance(deployment.get("completed_at_utc"), str)
        or not UTC_TIMESTAMP_RE.fullmatch(deployment["completed_at_utc"])
    ):
        raise ValueError("deployment identity evidence is invalid")
    if not isinstance(verification, dict) or set(verification) != VERIFICATION_FIELDS:
        raise ValueError("deployment verification evidence is invalid")
    if not all(
        verification.get(key) is True
        for key in (
            "checksum_match",
            "exact_krea2_namespace",
            "impact_reload",
            "queue_empty",
        )
    ):
        raise ValueError("deployment verification gates have not passed")
    smoke_completed = verification.get("smoke_completed")
    smoke = document.get("smoke")
    if smoke_completed is False and smoke is not None:
        raise ValueError("incomplete deployment evidence must not contain smoke metadata")
    if smoke_completed is True and not isinstance(smoke, dict):
        raise ValueError("completed deployment evidence must contain smoke metadata")
    if type(smoke_completed) is not bool:
        raise ValueError("deployment smoke verification must be boolean")


def _parse_utc_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{label} must be a UTC timestamp")
    return parsed


def _validate_smoke_run(
    document: dict[str, Any],
) -> tuple[int, list[str], dict[str, str], datetime, datetime]:
    seed = document.get("seed")
    if type(seed) is not int:
        raise ValueError("smoke run seed must be an integer")
    if document.get("remote") != "private_comfyui":
        raise ValueError("smoke run remote marker is invalid")
    resolved_prompt = document.get("resolved_prompt")
    if (
        not isinstance(resolved_prompt, str)
        or not resolved_prompt.strip()
        or WILDCARD_RE.search(resolved_prompt)
        or "{" in resolved_prompt
        or "}" in resolved_prompt
    ):
        raise ValueError("smoke run resolved_prompt is incomplete")
    outputs = document.get("images", document.get("outputs"))
    if (
        not isinstance(outputs, list)
        or not outputs
        or not all(isinstance(value, str) and value.strip() for value in outputs)
    ):
        raise ValueError("smoke run must record non-empty outputs")
    for output in outputs:
        pure = PurePosixPath(output)
        if pure.is_absolute() or ".." in pure.parts or URL_RE.search(output):
            raise ValueError("smoke run output references must remain relative")
    deployment = document.get("deployment")
    if not isinstance(deployment, dict) or set(deployment) != {
        "deployment_id",
        "deployment_nonce",
        "artifact_sha256",
        "manifest_sha256",
        "deployed_at_utc",
    }:
        raise ValueError("smoke run deployment binding is invalid")
    required_text = {
        "deployment_id": deployment.get("deployment_id"),
        "deployment_nonce": deployment.get("deployment_nonce"),
        "artifact_sha256": deployment.get("artifact_sha256"),
        "manifest_sha256": deployment.get("manifest_sha256"),
        "deployed_at_utc": deployment.get("deployed_at_utc"),
    }
    if (
        not isinstance(required_text["deployment_id"], str)
        or not required_text["deployment_id"]
        or not isinstance(required_text["deployment_nonce"], str)
        or not NONCE_RE.fullmatch(required_text["deployment_nonce"])
        or not isinstance(required_text["artifact_sha256"], str)
        or not SHA256_RE.fullmatch(required_text["artifact_sha256"])
        or not isinstance(required_text["manifest_sha256"], str)
        or not SHA256_RE.fullmatch(required_text["manifest_sha256"])
    ):
        raise ValueError("smoke run deployment binding is invalid")
    deployed_at = _parse_utc_timestamp(
        required_text["deployed_at_utc"], label="smoke deployed_at_utc"
    )
    started_at = _parse_utc_timestamp(
        document.get("started_at_utc"), label="smoke started_at_utc"
    )
    completed_at = _parse_utc_timestamp(
        document.get("completed_at_utc"), label="smoke completed_at_utc"
    )
    if not deployed_at <= started_at <= completed_at:
        raise ValueError("smoke run chronology is invalid")
    return seed, outputs, required_text, started_at, completed_at


def discover_smoke_run(
    *,
    root: Path,
    evidence_path: Path,
    smoke_root: Path,
) -> Path:
    evidence_file, _ = _safe_repo_file(root, evidence_path, label="evidence")
    evidence = load_json_object(evidence_file, label="deployment evidence")
    _validate_evidence_shape(evidence, evidence_path)
    deployment = evidence["deployment"]
    expected_binding = {
        "deployment_id": evidence["deployment_id"],
        "deployment_nonce": deployment["nonce"],
        "artifact_sha256": evidence["artifact"]["sha256"],
        "manifest_sha256": evidence["manifest"]["sha256"],
        "deployed_at_utc": deployment["completed_at_utc"],
    }
    directory = _safe_repo_directory(root, smoke_root, label="smoke root")
    matches: list[Path] = []
    for candidate in sorted(directory.rglob("run.json")):
        try:
            relative = candidate.relative_to(root.resolve())
            safe_file, _ = _safe_repo_file(root, relative, label="smoke run")
            smoke_run = load_json_object(safe_file, label="smoke run")
            _, _, binding, _, _ = _validate_smoke_run(smoke_run)
        except (OSError, TypeError, ValueError):
            continue
        if binding == expected_binding:
            matches.append(relative)
    if len(matches) != 1:
        raise ValueError("smoke root must contain exactly one current deployment run")
    return matches[0]


def finalize(
    *,
    root: Path,
    evidence_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    artifact_path: Path = DEFAULT_SOURCE,
    smoke_run_path: Path,
) -> dict[str, Any]:
    _require_current_path(manifest_path, DEFAULT_MANIFEST, label="manifest")
    _require_current_path(artifact_path, DEFAULT_SOURCE, label="artifact")
    evidence_file, _ = _safe_repo_file(root, evidence_path, label="evidence")
    manifest_file, _ = _safe_repo_file(root, manifest_path, label="manifest")
    artifact_file, _ = _safe_repo_file(root, artifact_path, label="artifact")
    smoke_file, smoke_relative = _safe_repo_file(
        root, smoke_run_path, label="smoke run"
    )
    if smoke_file.name != "run.json":
        raise ValueError("smoke run must reference a run.json file")

    evidence = load_json_object(evidence_file, label="deployment evidence")
    _validate_evidence_shape(evidence, evidence_path)
    if any(
        pattern.search(str(evidence))
        for pattern in (URL_RE, HOME_RE, ACCOUNT_RE, IPV4_RE)
    ):
        raise ValueError("deployment evidence contains private connection data")

    approved_items = approved_manifest_item_count(manifest_file)
    if evidence.get("approved_items") != approved_items:
        raise ValueError("deployment evidence approved item count is stale")
    manifest = evidence["manifest"]
    manifest_digest = sha256(manifest_file)
    if (
        manifest.get("name") != manifest_file.name
        or manifest.get("sha256") != manifest_digest
        or manifest.get("bytes") != manifest_file.stat().st_size
    ):
        raise ValueError("deployment manifest evidence is stale or mismatched")
    artifact = evidence["artifact"]
    digest = sha256(artifact_file)
    if (
        artifact.get("name") != artifact_file.name
        or artifact.get("sha256") != digest
        or artifact.get("bytes") != artifact_file.stat().st_size
        or isinstance(artifact.get("wildcard_path_count"), bool)
        or not isinstance(artifact.get("wildcard_path_count"), int)
        or artifact["wildcard_path_count"] < 1
    ):
        raise ValueError("deployment artifact evidence is stale or mismatched")

    smoke_run = load_json_object(smoke_file, label="smoke run")
    seed, _, smoke_binding, started_at, completed_at = _validate_smoke_run(smoke_run)
    deployment = evidence["deployment"]
    expected_binding = {
        "deployment_id": evidence["deployment_id"],
        "deployment_nonce": deployment["nonce"],
        "artifact_sha256": artifact["sha256"],
        "manifest_sha256": manifest["sha256"],
        "deployed_at_utc": deployment["completed_at_utc"],
    }
    if smoke_binding != expected_binding:
        raise ValueError("smoke run does not belong to the current deployment")
    deployed_at = _parse_utc_timestamp(
        deployment["completed_at_utc"], label="deployment completed_at_utc"
    )
    if not deployed_at <= started_at <= completed_at:
        raise ValueError("smoke run did not execute after deployment")
    run_digest = sha256(smoke_file)
    smoke_evidence = {
        "seed": seed,
        "run_record": smoke_relative,
        "run_record_sha256": run_digest,
        "deployment_id": evidence["deployment_id"],
        "deployment_nonce": deployment["nonce"],
        "artifact_sha256": artifact["sha256"],
        "manifest_sha256": manifest["sha256"],
        "started_at_utc": smoke_run["started_at_utc"],
        "completed_at_utc": smoke_run["completed_at_utc"],
    }
    existing_smoke = evidence.get("smoke")
    if evidence["verification"]["smoke_completed"] is True:
        if existing_smoke != smoke_evidence:
            raise ValueError("completed smoke evidence does not match the current run")
        return evidence

    updated = copy.deepcopy(evidence)
    updated["verification"]["smoke_completed"] = True
    updated["smoke"] = smoke_evidence
    atomic_write_evidence(evidence_path, updated, root=root)
    return updated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Finalize redacted production deployment evidence with a smoke run"
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_SOURCE)
    smoke_source = parser.add_mutually_exclusive_group(required=True)
    smoke_source.add_argument("--smoke-run", type=Path)
    smoke_source.add_argument("--smoke-root", type=Path)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress status output when probing for reusable completed evidence",
    )
    args = parser.parse_args(argv)
    try:
        smoke_run = args.smoke_run
        if smoke_run is None:
            smoke_run = discover_smoke_run(
                root=args.root,
                evidence_path=args.evidence,
                smoke_root=args.smoke_root,
            )
        finalize(
            root=args.root,
            evidence_path=args.evidence,
            manifest_path=args.manifest,
            artifact_path=args.artifact,
            smoke_run_path=smoke_run,
        )
        if not args.quiet:
            print("Production deployment evidence finalized.")
        return 0
    except (OSError, TypeError, ValueError):
        if not args.quiet:
            print("ERROR: production deployment finalization failed validation.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
