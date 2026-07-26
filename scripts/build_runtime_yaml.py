#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import (
    VALID_STATUSES,
    dump_yaml,
    item_prompts,
    item_status,
    iter_catalog_items,
    nested_set_list,
    normalized_phrase,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile catalog items into runtime YAML")
    parser.add_argument("--catalog", type=Path, default=Path("catalog"))
    parser.add_argument("--output", type=Path, default=Path("wildcards"))
    parser.add_argument(
        "--include-status",
        action="append",
        choices=sorted(VALID_STATUSES),
        default=None,
        help="status to include; repeat for multiple statuses (default: approved)",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="write no runtime files when no eligible entries exist",
    )
    return parser.parse_args()


def compile_catalog(
    catalog_root: Path,
    output_root: Path,
    statuses: set[str],
    allow_empty: bool = False,
) -> dict[str, Any]:
    outputs: dict[str, dict[str, Any]] = {}
    aggregates: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    included: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for source_path, item_id, item in iter_catalog_items(catalog_root):
        status = item_status(item)
        if status not in statuses:
            continue
        prompts = item_prompts(item)
        runtime = item.get("runtime")
        if not prompts or not isinstance(runtime, dict):
            raise ValueError(f"{source_path}: eligible item {item_id!r} lacks prompts/runtime")
        relative_file = runtime.get("file")
        path_parts = runtime.get("path")
        if not isinstance(relative_file, str) or not relative_file.endswith(".yaml"):
            raise ValueError(f"{source_path}: {item_id!r} has an invalid runtime.file")
        if (
            not isinstance(path_parts, list)
            or len(path_parts) < 2
            or not all(isinstance(part, str) and part for part in path_parts)
        ):
            raise ValueError(f"{source_path}: {item_id!r} has an invalid runtime.path")
        if path_parts[-1] != item_id:
            raise ValueError(f"{source_path}: runtime path must end in {item_id!r}")

        target = outputs.setdefault(relative_file, {})
        for prompt in prompts:
            key = normalized_phrase(prompt)
            if key in seen:
                raise ValueError(
                    f"duplicate prompt in {item_id!r}; first defined by {seen[key]!r}"
                )
            seen[key] = item_id
        nested_set_list(target, path_parts, prompts)

        parent_path = tuple(path_parts[:-1])
        aggregates[(relative_file, parent_path)].extend(prompts)
        included.append(
            {
                "id": item_id,
                "status": status,
                "source": str(source_path),
                "runtime_file": relative_file,
                "runtime_path": "/".join(path_parts),
                "prompt_count": len(prompts),
            }
        )

    if not included and not allow_empty:
        requested = ", ".join(sorted(statuses))
        raise ValueError(f"no catalog entries matched status: {requested}")

    for (relative_file, parent_path), prompts in aggregates.items():
        nested_set_list(outputs[relative_file], [*parent_path, "all"], prompts)

    manifest = {
        "schema_version": 1,
        "included_statuses": sorted(statuses),
        "item_count": len(included),
        "prompt_count": sum(item["prompt_count"] for item in included),
        "files": sorted(outputs),
        "items": included,
    }
    manifest_path = output_root.parent / f"{output_root.name}-manifest.json"
    output_root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.build.", dir=output_root.parent)
    )
    backup: Path | None = None
    try:
        for relative_file, data in outputs.items():
            dump_yaml(data, stage / relative_file)
        if output_root.exists():
            if not output_root.is_dir():
                raise ValueError(f"runtime output is not a directory: {output_root}")
            backup = output_root.parent / f".{output_root.name}.backup.{uuid.uuid4().hex}"
            os.replace(output_root, backup)
        try:
            os.replace(stage, output_root)
        except Exception:
            if backup is not None and backup.exists():
                os.replace(backup, output_root)
            raise
        if backup is not None:
            shutil.rmtree(backup)

        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{manifest_path.name}.", dir=manifest_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(manifest_text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, manifest_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest


def main() -> int:
    args = parse_args()
    statuses = set(args.include_status or ["approved"])
    try:
        manifest = compile_catalog(
            args.catalog, args.output, statuses, allow_empty=args.allow_empty
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(
        f"Built {manifest['prompt_count']} prompts from {manifest['item_count']} items "
        f"into {len(manifest['files'])} file(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
