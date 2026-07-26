#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from common import VALID_STATUSES, load_yaml
from generate_catalog_expansion import (
    GENERATOR_ID,
    compile_collection,
    file_sha256,
    load_collections,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLUEPRINTS = Path("catalog/blueprints")
DEFAULT_SOURCES = Path("catalog/sources.yaml")
DEFAULT_MANIFEST = Path("build/catalog-generation-manifest.json")
EVALUATED_STATUSES = {"testing", "approved", "limited", "rejected", "deprecated"}


def validate_validation(style_id: str, validation: Any) -> None:
    if not isinstance(validation, dict):
        raise ValueError(f"{style_id}: validation must be a mapping")
    status = validation.get("status")
    seeds = validation.get("tested_seeds")
    if status not in VALID_STATUSES:
        raise ValueError(f"{style_id}: validation status is invalid")
    if not isinstance(seeds, int) or isinstance(seeds, bool) or seeds < 0:
        raise ValueError(f"{style_id}: tested_seeds must be a non-negative integer")
    if status in EVALUATED_STATUSES:
        evaluation = validation.get("last_evaluation")
        if not isinstance(evaluation, str) or not evaluation.strip() or seeds < 1:
            raise ValueError(f"{style_id}: evaluated status requires evaluation evidence")


def validate_catalog_against_generation(
    current_items: dict[str, Any],
    expected_items: dict[str, Any],
    owned_ids: list[str],
) -> None:
    if len(owned_ids) != len(set(owned_ids)):
        raise ValueError("generation manifest contains duplicate owned item IDs")
    owned = set(owned_ids)
    if owned != set(expected_items):
        raise ValueError("generation manifest ownership does not match blueprint output")
    if owned != set(current_items):
        raise ValueError("catalog item IDs do not match managed blueprint output")
    for style_id in sorted(owned):
        current = current_items[style_id]
        expected = expected_items[style_id]
        if not isinstance(current, dict) or not isinstance(expected, dict):
            raise ValueError(f"{style_id}: catalog items must be mappings")
        current_body = dict(current)
        expected_body = dict(expected)
        validation = current_body.pop("validation", None)
        expected_body.pop("validation", None)
        if current_body != expected_body:
            raise ValueError(f"{style_id}: managed content changed outside the generator")
        validate_validation(style_id, validation)


def refreshed_manifest(
    manifest: dict[str, Any], output_file: str, output_path: Path
) -> dict[str, Any]:
    updated = json.loads(json.dumps(manifest))
    outputs = updated.get("outputs")
    collections = updated.get("collections")
    if not isinstance(outputs, list) or not isinstance(collections, list):
        raise ValueError("generation manifest outputs and collections are required")
    matches = [record for record in outputs if record.get("output_file") == output_file]
    if len(matches) != 1:
        raise ValueError(f"generation manifest must own {output_file} exactly once")
    digest = file_sha256(output_path)
    matches[0]["sha256"] = digest
    collection_ids = matches[0].get("collection_ids")
    if not isinstance(collection_ids, list) or not collection_ids:
        raise ValueError("generation manifest output has no collection ownership")
    seen: set[str] = set()
    for record in collections:
        if record.get("output_file") == output_file:
            identifier = record.get("id")
            if not isinstance(identifier, str):
                raise ValueError("generation manifest collection ID is invalid")
            record["output_sha256"] = digest
            seen.add(identifier)
    if seen != set(collection_ids):
        raise ValueError("generation manifest collection ownership is inconsistent")
    return updated


def atomic_write_json(document: dict[str, Any], path: Path) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adopt validation-only changes into a generated catalog manifest"
    )
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--blueprints", type=Path, default=DEFAULT_BLUEPRINTS)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("generator") != GENERATOR_ID:
            raise ValueError("manifest was not produced by the catalog expansion generator")
        collections, blueprint_records = load_collections(args.blueprints, args.sources)
        if manifest.get("blueprints") != blueprint_records:
            raise ValueError("blueprint records no longer match the generation manifest")
        payload = json.dumps(
            blueprint_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if manifest.get("blueprint_digest") != hashlib.sha256(payload.encode()).hexdigest():
            raise ValueError("blueprint digest no longer matches the generation manifest")
        try:
            output_file = args.catalog.resolve().relative_to(args.catalog.parent.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("catalog path is invalid") from exc
        output_file = args.catalog.name
        output_records = manifest.get("outputs")
        if not isinstance(output_records, list):
            raise ValueError("generation manifest outputs are required")
        matches = [record for record in output_records if record.get("output_file") == output_file]
        if len(matches) != 1:
            raise ValueError(f"generation manifest must own {output_file} exactly once")
        record = matches[0]
        expected_items: dict[str, Any] = {}
        for collection in collections:
            if collection.output_file == output_file:
                expected_items.update(compile_collection(collection))
        document = load_yaml(args.catalog)
        current_items = document.get("items") if isinstance(document, dict) else None
        if not isinstance(current_items, dict):
            raise ValueError("catalog items must be a mapping")
        owned_ids = record.get("generated_item_ids")
        if not isinstance(owned_ids, list) or not all(isinstance(item, str) for item in owned_ids):
            raise ValueError("generation manifest owned item IDs are invalid")
        validate_catalog_against_generation(current_items, expected_items, owned_ids)
        updated = refreshed_manifest(manifest, output_file, args.catalog)
        if args.apply:
            atomic_write_json(updated, args.manifest)
            print(f"Adopted validation-only changes for {output_file} into the generation manifest.")
        else:
            print(f"DRY RUN: validation-only changes for {output_file} are safe to adopt.")
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
