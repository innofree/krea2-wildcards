#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import re
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
    "artifact",
    "verification",
    "smoke",
}
ARTIFACT_FIELDS = {"name", "sha256", "bytes", "wildcard_path_count"}
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


def _require_current_path(path: Path, expected: Path, *, label: str) -> None:
    if PurePosixPath(path.as_posix()) != PurePosixPath(expected.as_posix()):
        raise ValueError(f"{label} must reference the current production file")


def _validate_evidence_shape(document: dict[str, Any], evidence_path: Path) -> None:
    if set(document) != EVIDENCE_FIELDS or document.get("schema_version") != 1:
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
    verification = document.get("verification")
    if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS:
        raise ValueError("deployment artifact evidence is invalid")
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


def _validate_smoke_run(document: dict[str, Any]) -> tuple[int, list[str]]:
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
    return seed, outputs


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
    seed, _ = _validate_smoke_run(smoke_run)
    existing_smoke = evidence.get("smoke")
    if evidence["verification"]["smoke_completed"] is True and existing_smoke != {
        "seed": seed,
        "run_record": smoke_relative,
    }:
        raise ValueError("completed smoke evidence does not match the current run")

    updated = copy.deepcopy(evidence)
    updated["verification"]["smoke_completed"] = True
    updated["smoke"] = {"seed": seed, "run_record": smoke_relative}
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
    parser.add_argument("--smoke-run", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        finalize(
            root=args.root,
            evidence_path=args.evidence,
            manifest_path=args.manifest,
            artifact_path=args.artifact,
            smoke_run_path=args.smoke_run,
        )
        print("Production deployment evidence finalized.")
        return 0
    except (OSError, TypeError, ValueError):
        print("ERROR: production deployment finalization failed validation.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
