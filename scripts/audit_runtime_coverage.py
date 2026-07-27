#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

import yaml

from build_impact_yaml import impact_compatible_document
from common import KEY_RE, iter_leaf_lists, load_yaml


NOVELAI_BRACE_RE = re.compile(r"[{}]")
NOVELAI_BRACKET_RE = re.compile(r"\[[^\]\r\n]*\]")
PRODUCTION_ARTIFACT = Path("build/impact-production/krea2_complete_pack.yaml")
DEFAULT_PROMPT_LOG = Path(
    "tests/reports/production_smoke_v1/runs/crystal_iris_pastel_seed_6006/run.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unresolved_wildcard_count(value: str) -> int:
    """Count both valid and malformed ``__wildcard__``-style markers."""

    markers = value.count("__")
    return (markers + 1) // 2


def _repo_file(root: Path, raw: Path, *, label: str) -> tuple[Path, str]:
    pure = PurePosixPath(raw.as_posix())
    if raw.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"{label} must be a safe repository-relative path")
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse symbolic links")
    candidate = current.resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the repository") from exc
    if not candidate.is_file():
        raise ValueError(f"{label} must reference an existing file")
    return candidate, pure.as_posix()


def _image_reference_valid(root: Path, run_path: Path, raw: Any) -> bool:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return False
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        return False
    relative = Path(*pure.parts)
    for candidate in (root / relative, run_path.parent / relative):
        current = candidate.anchor and Path(candidate.anchor) or Path()
        symlinked = False
        for part in candidate.parts[len(current.parts) :]:
            current /= part
            if current.is_symlink():
                symlinked = True
                break
        if symlinked:
            continue
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if resolved.is_file():
            return True
    return False


def _manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("runtime manifest is invalid JSON") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("runtime manifest must be a schema_version 1 object")
    if document.get("included_statuses") != ["approved"]:
        raise ValueError("runtime manifest must be approved-only")
    files = document.get("files")
    items = document.get("items")
    if (
        not isinstance(files, list)
        or not files
        or not all(isinstance(v, str) for v in files)
    ):
        raise ValueError("runtime manifest files must be a non-empty text list")
    normalized_files: list[str] = []
    for value in files:
        if "\\" in value:
            raise ValueError("runtime manifest contains an unsafe runtime file")
        pure = PurePosixPath(value)
        if (
            pure.is_absolute()
            or len(pure.parts) < 2
            or pure.parts[0] != "krea2"
            or any(
                part in {"", ".", ".."} or not KEY_RE.fullmatch(part)
                for part in pure.parts[:-1]
            )
            or pure.suffix != ".yaml"
            or not KEY_RE.fullmatch(pure.stem)
        ):
            raise ValueError("runtime manifest contains an unsafe runtime file")
        if value != pure.as_posix():
            raise ValueError("runtime manifest contains a non-canonical runtime file")
        normalized_files.append(pure.as_posix())
    if len(set(normalized_files)) != len(normalized_files):
        raise ValueError("runtime manifest contains duplicate runtime files")
    if not isinstance(items, list) or not items:
        raise ValueError("runtime manifest items must be a non-empty list")
    if type(document.get("item_count")) is not int or document.get("item_count") != len(
        items
    ):
        raise ValueError("runtime manifest item count is inconsistent")
    return document


def _prompt_log_evidence(
    root: Path, prompt_logs: Sequence[Path]
) -> tuple[list[dict[str, str]], int, int, int]:
    if not prompt_logs:
        raise ValueError("at least one --prompt-log run.json is required")
    evidence: list[dict[str, str]] = []
    seen: set[str] = set()
    unresolved_wildcards = 0
    brace_conflicts = 0
    bracket_conflicts = 0
    for index, raw_path in enumerate(prompt_logs, start=1):
        path, relative = _repo_file(root, raw_path, label=f"prompt log {index}")
        if path.name != "run.json":
            raise ValueError(f"prompt log {index} must be a run.json file")
        if relative in seen:
            raise ValueError("prompt logs must be unique")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"prompt log {index} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"prompt log {index} must be a JSON object")
        resolved_prompt = value.get("resolved_prompt")
        if not isinstance(resolved_prompt, str) or not resolved_prompt.strip():
            raise ValueError(f"prompt log {index} lacks a resolved prompt")
        unresolved_wildcards += _unresolved_wildcard_count(resolved_prompt)
        brace_conflicts += len(NOVELAI_BRACE_RE.findall(resolved_prompt))
        bracket_conflicts += len(NOVELAI_BRACKET_RE.findall(resolved_prompt))
        if value.get("remote") != "private_comfyui":
            raise ValueError(f"prompt log {index} has invalid remote metadata")
        if type(value.get("seed")) is not int:
            raise ValueError(f"prompt log {index} has invalid seed metadata")
        images = value.get("images")
        if (
            not isinstance(images, list)
            or not images
            or not all(_image_reference_valid(root, path, image) for image in images)
        ):
            raise ValueError(f"prompt log {index} has invalid image references")
        evidence.append({"path": relative, "sha256": _sha256(path)})
        seen.add(relative)
    return evidence, unresolved_wildcards, brace_conflicts, bracket_conflicts


def audit(
    runtime_root: Path,
    manifest_path: Path,
    prompt_logs: Sequence[Path],
) -> dict[str, Any]:
    root = manifest_path.resolve().parent
    manifest = _manifest(manifest_path)
    manifest_sha256 = _sha256(manifest_path)
    artifact_path, artifact_relative = _repo_file(
        root, PRODUCTION_ARTIFACT, label="production artifact"
    )
    (
        prompt_log_evidence,
        final_prompt_unresolved_wildcards,
        final_prompt_brace_conflicts,
        final_prompt_bracket_conflicts,
    ) = _prompt_log_evidence(root, prompt_logs)
    expected_files = set(manifest["files"])
    actual_files = {
        path.relative_to(runtime_root).as_posix()
        for path in runtime_root.rglob("*.yaml")
    }
    loaded: dict[str, dict[tuple[str, ...], list[Any]]] = {}
    yaml_syntax_errors = 0
    unresolved_wildcards = 0
    novelai_brace_conflicts = 0
    novelai_bracket_conflicts = 0
    metadata_keys = {
        "validation",
        "generation",
        "runtime",
        "source_refs",
        "feature_axes",
        "visual_axes",
        "compatibility",
    }
    catalog_runtime_separated = True

    for relative in sorted(expected_files & actual_files):
        path = runtime_root / relative
        try:
            document = load_yaml(path)
            if not isinstance(document, dict) or list(document) != ["krea2"]:
                raise ValueError("runtime root must contain only krea2")
            leaves = {
                tuple(parts): values for parts, values in iter_leaf_lists(document)
            }
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            yaml_syntax_errors += 1
            continue
        loaded[relative] = leaves
        for parts, values in leaves.items():
            if any(part in metadata_keys for part in parts):
                catalog_runtime_separated = False
            for value in values:
                if not isinstance(value, str):
                    yaml_syntax_errors += 1
                    continue
                unresolved_wildcards += _unresolved_wildcard_count(value)
                novelai_brace_conflicts += len(NOVELAI_BRACE_RE.findall(value))
                novelai_bracket_conflicts += len(
                    NOVELAI_BRACKET_RE.findall(value)
                )

    expected_paths: set[tuple[str, tuple[str, ...]]] = set()
    expected_public_paths: set[tuple[str, ...]] = set()
    expected_aggregate_paths: set[tuple[str, tuple[str, ...]]] = set()
    expected_aggregate_values: dict[
        tuple[str, tuple[str, ...]], list[str]
    ] = {}
    invalid_aggregate_paths: set[tuple[str, tuple[str, ...]]] = set()
    expected_ids: set[str] = set()
    resolved_item_paths = 0
    expected_prompt_count = 0
    for index, item in enumerate(manifest["items"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest item {index} must be an object")
        item_id = item.get("id")
        relative = item.get("runtime_file")
        raw_path = item.get("runtime_path")
        prompt_count = item.get("prompt_count")
        if (
            not isinstance(item_id, str)
            or not item_id
            or not isinstance(relative, str)
            or relative not in expected_files
            or not isinstance(raw_path, str)
            or not raw_path
            or isinstance(prompt_count, bool)
            or not isinstance(prompt_count, int)
            or prompt_count < 1
            or item.get("status") != "approved"
        ):
            raise ValueError(f"manifest item {index} has invalid runtime metadata")
        parts = tuple(raw_path.split("/"))
        if (
            not parts
            or parts[0] != "krea2"
            or any(not KEY_RE.fullmatch(part) for part in parts)
            or parts[-1] != item_id
            or parts[-1] == "all"
        ):
            raise ValueError(f"manifest item {index} has invalid id or runtime path")
        identity = (relative, parts)
        if parts in expected_public_paths:
            raise ValueError("runtime manifest contains a duplicate wildcard path")
        if item_id in expected_ids:
            raise ValueError("runtime manifest contains a duplicate item id")
        expected_ids.add(item_id)
        expected_paths.add(identity)
        expected_public_paths.add(parts)
        expected_prompt_count += prompt_count
        values = loaded.get(relative, {}).get(parts)
        aggregate_identity = (relative, (*parts[:-1], "all"))
        expected_aggregate_paths.add(aggregate_identity)
        expected_aggregate_values.setdefault(aggregate_identity, [])
        if (
            isinstance(values, list)
            and len(values) == prompt_count
            and all(isinstance(value, str) and value.strip() for value in values)
        ):
            resolved_item_paths += 1
            expected_aggregate_values[aggregate_identity].extend(values)
        else:
            invalid_aggregate_paths.add(aggregate_identity)
    if (
        type(manifest.get("prompt_count")) is not int
        or manifest.get("prompt_count") != expected_prompt_count
    ):
        raise ValueError("runtime manifest prompt count is inconsistent")

    resolved_aggregate_paths = sum(
        identity not in invalid_aggregate_paths
        and loaded.get(identity[0], {}).get(identity[1]) == values
        for identity, values in expected_aggregate_values.items()
    )
    all_expected_paths = expected_paths | expected_aggregate_paths
    actual_paths = {
        (relative, parts)
        for relative, leaves in loaded.items()
        for parts in leaves
    }
    unexpected_paths = actual_paths - all_expected_paths
    missing_paths = all_expected_paths - actual_paths
    resolved_paths = resolved_item_paths + resolved_aggregate_paths

    impact_adapter_exact = False
    impact_paths_expected = {
        "/".join(parts[1:]) for _, parts in all_expected_paths
    }
    impact_paths_resolved = 0
    try:
        expected_impact = impact_compatible_document(runtime_root)
        artifact_document = load_yaml(artifact_path)
        artifact_paths = (
            set(artifact_document["krea2"])
            if isinstance(artifact_document, dict)
            and list(artifact_document) == ["krea2"]
            and isinstance(artifact_document.get("krea2"), dict)
            else set()
        )
        impact_adapter_exact = (
            artifact_document == expected_impact
            and artifact_paths == impact_paths_expected
        )
        if impact_adapter_exact:
            impact_paths_resolved = len(impact_paths_expected)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        impact_adapter_exact = False

    complete = (
        actual_files == expected_files
        and len(loaded) == len(expected_files)
        and not unexpected_paths
        and not missing_paths
        and resolved_paths == len(all_expected_paths)
        and impact_adapter_exact
        and impact_paths_resolved == len(impact_paths_expected)
        and unresolved_wildcards == 0
        and final_prompt_unresolved_wildcards == 0
        and yaml_syntax_errors == 0
        and novelai_brace_conflicts == 0
        and novelai_bracket_conflicts == 0
        and final_prompt_brace_conflicts == 0
        and final_prompt_bracket_conflicts == 0
        and catalog_runtime_separated
        and bool(prompt_log_evidence)
    )
    return {
        "schema_version": 1,
        "report_type": "runtime_coverage",
        "status": "passed" if complete else "failed",
        "complete": complete,
        "manifest": manifest_path.name,
        "manifest_sha256": manifest_sha256,
        "production_artifact": artifact_relative,
        "production_artifact_sha256": _sha256(artifact_path),
        "production_artifact_bytes": artifact_path.stat().st_size,
        "runtime_files_expected": len(expected_files),
        "runtime_files_loaded": len(loaded),
        "wildcard_paths_expected": len(all_expected_paths),
        "wildcard_paths_resolved": resolved_paths,
        "approved_item_paths_expected": len(expected_paths),
        "approved_item_paths_resolved": resolved_item_paths,
        "aggregate_paths_expected": len(expected_aggregate_paths),
        "aggregate_paths_resolved": resolved_aggregate_paths,
        "unexpected_runtime_leaf_paths": len(unexpected_paths),
        "missing_runtime_leaf_paths": len(missing_paths),
        "impact_paths_expected": len(impact_paths_expected),
        "impact_paths_resolved": impact_paths_resolved,
        "impact_adapter_exact": impact_adapter_exact,
        "all_runtime_leaves_resolved": (
            resolved_paths == len(all_expected_paths)
            and not unexpected_paths
            and not missing_paths
            and impact_adapter_exact
        ),
        "unresolved_wildcards": unresolved_wildcards,
        "final_prompt_unresolved_wildcards": final_prompt_unresolved_wildcards,
        "yaml_syntax_errors": yaml_syntax_errors,
        "novelai_brace_conflicts": novelai_brace_conflicts,
        "novelai_bracket_conflicts": novelai_bracket_conflicts,
        "final_prompt_brace_conflicts": final_prompt_brace_conflicts,
        "final_prompt_bracket_conflicts": final_prompt_bracket_conflicts,
        "catalog_runtime_separated": catalog_runtime_separated,
        "final_prompt_logs_saved": bool(prompt_log_evidence),
        "final_prompt_log_count": len(prompt_log_evidence),
        "prompt_logs": prompt_log_evidence,
    }


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit approved runtime wildcard resolution"
    )
    parser.add_argument("--runtime", type=Path, default=Path("wildcards"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("wildcards-manifest.json")
    )
    parser.add_argument(
        "--prompt-log",
        type=Path,
        action="append",
        help=(
            "safe repository-relative run.json; repeat for multiple explicit logs "
            f"(default: {DEFAULT_PROMPT_LOG.as_posix()})"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/reports/completion/runtime_coverage.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        prompt_logs = args.prompt_log or [DEFAULT_PROMPT_LOG]
        document = audit(args.runtime, args.manifest, prompt_logs)
        _atomic_write(args.output, document)
        print(
            f"Runtime coverage: {document['wildcard_paths_resolved']}/"
            f"{document['wildcard_paths_expected']} paths, status={document['status']}."
        )
        return 0 if document["complete"] else 1
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
