#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from common import iter_leaf_lists, load_yaml


WILDCARD_RE = re.compile(r"__[A-Za-z0-9][A-Za-z0-9_./-]*__")
NOVELAI_BRACE_RE = re.compile(r"[{}]")


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
    if not isinstance(items, list) or not items:
        raise ValueError("runtime manifest items must be a non-empty list")
    return document


def _logged_prompts(root: Path) -> int:
    count = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("run.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("resolved_prompt"), str):
            if value["resolved_prompt"].strip():
                count += 1
    return count


def audit(
    runtime_root: Path, manifest_path: Path, prompt_log_root: Path
) -> dict[str, Any]:
    manifest = _manifest(manifest_path)
    expected_files = set(manifest["files"])
    actual_files = {
        path.relative_to(runtime_root).as_posix()
        for path in runtime_root.rglob("*.yaml")
    }
    loaded: dict[str, dict[tuple[str, ...], list[Any]]] = {}
    yaml_syntax_errors = 0
    unresolved_wildcards = 0
    novelai_brace_conflicts = 0
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
                unresolved_wildcards += len(WILDCARD_RE.findall(value))
                novelai_brace_conflicts += len(NOVELAI_BRACE_RE.findall(value))

    expected_paths: set[tuple[str, tuple[str, ...]]] = set()
    resolved_paths = 0
    for index, item in enumerate(manifest["items"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest item {index} must be an object")
        relative = item.get("runtime_file")
        raw_path = item.get("runtime_path")
        prompt_count = item.get("prompt_count")
        if (
            not isinstance(relative, str)
            or not isinstance(raw_path, str)
            or not raw_path
            or isinstance(prompt_count, bool)
            or not isinstance(prompt_count, int)
            or prompt_count < 1
            or item.get("status") != "approved"
        ):
            raise ValueError(f"manifest item {index} has invalid runtime metadata")
        parts = tuple(raw_path.split("/"))
        identity = (relative, parts)
        if identity in expected_paths:
            raise ValueError("runtime manifest contains a duplicate wildcard path")
        expected_paths.add(identity)
        values = loaded.get(relative, {}).get(parts)
        if isinstance(values, list) and len(values) == prompt_count:
            resolved_paths += 1

    logged_prompts = _logged_prompts(prompt_log_root)
    complete = (
        actual_files == expected_files
        and len(loaded) == len(expected_files)
        and resolved_paths == len(expected_paths)
        and unresolved_wildcards == 0
        and yaml_syntax_errors == 0
        and novelai_brace_conflicts == 0
        and catalog_runtime_separated
        and logged_prompts > 0
    )
    return {
        "schema_version": 1,
        "report_type": "runtime_coverage",
        "status": "passed" if complete else "failed",
        "complete": complete,
        "runtime_files_expected": len(expected_files),
        "runtime_files_loaded": len(loaded),
        "wildcard_paths_expected": len(expected_paths),
        "wildcard_paths_resolved": resolved_paths,
        "unresolved_wildcards": unresolved_wildcards,
        "yaml_syntax_errors": yaml_syntax_errors,
        "novelai_brace_conflicts": novelai_brace_conflicts,
        "catalog_runtime_separated": catalog_runtime_separated,
        "final_prompt_logs_saved": logged_prompts > 0,
        "final_prompt_log_count": logged_prompts,
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
    parser.add_argument("--prompt-logs", type=Path, default=Path("tests/reports"))
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
        document = audit(args.runtime, args.manifest, args.prompt_logs)
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
