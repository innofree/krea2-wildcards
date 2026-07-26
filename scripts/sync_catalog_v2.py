from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from common import load_yaml
from validate_catalog_v2 import validate_catalog_v2


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_REQUIRED = {"testing", "approved", "limited", "rejected", "deprecated"}
SUPPORTED_KINDS = {
    "style_pack",
    "artist_signature",
    "style_atomic",
    "media_rendering",
    "linework_coloring",
    "character_design",
    "hair_design",
    "fashion",
    "pose",
    "camera",
    "lighting",
    "background",
    "effect",
    "preset",
}
PRIMARY_AXES = {
    "artist_signature": "signature",
    "style_atomic": "style",
    "media_rendering": "rendering",
    "linework_coloring": "linework_coloring",
    "character_design": "character",
    "hair_design": "hair",
    "fashion": "fashion",
    "pose": "pose",
    "camera": "camera",
    "lighting": "lighting",
    "background": "background",
    "effect": "effect",
    "preset": "preset",
}
ORDINARY_CATALOGS = {
    "catalog/art_styles.yaml": "style_pack",
    "catalog/artists.yaml": "artist_signature",
    "catalog/style_atomics.yaml": "style_atomic",
    "catalog/media_rendering.yaml": "media_rendering",
    "catalog/linework_coloring.yaml": "linework_coloring",
    "catalog/character_designs.yaml": "character_design",
    "catalog/hair_designs.yaml": "hair_design",
    "catalog/fashions.yaml": "fashion",
    "catalog/poses.yaml": "pose",
    "catalog/cameras.yaml": "camera",
    "catalog/lighting.yaml": "lighting",
    "catalog/backgrounds.yaml": "background",
    "catalog/effects.yaml": "effect",
    "catalog/presets.yaml": "preset",
}
AUTO_BLUEPRINTS = (
    "catalog/generation_blueprint.yaml",
    "catalog/blueprint.yaml",
    "catalog/blueprints.yaml",
)
AUTO_MANIFESTS = (
    "build/catalog-generation-manifest.json",
    "build/generated-catalog-manifest.json",
)
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SyncError(ValueError):
    pass


@dataclass(frozen=True)
class CollectionSpec:
    identifier: str
    kind: str
    output_file: str
    family: str
    runtime_file: str
    path_prefix: tuple[str, ...]
    source_refs: tuple[str, ...]
    target_count: int
    product_size: int
    dimensions: Mapping[str, Mapping[str, str]]


@dataclass
class SyncReport:
    dry_run: bool
    catalog_files: int = 0
    scanned_items: int = 0
    added_items: int = 0
    updated_items: int = 0
    added_features: int = 0
    added_sources: int = 0
    added_routes: int = 0
    added_evaluations: int = 0
    lifecycle_transitions: int = 0
    manifest_outputs_verified: int = 0

    @property
    def changed(self) -> bool:
        return any(
            (
                self.added_items,
                self.updated_items,
                self.added_features,
                self.added_sources,
                self.added_routes,
                self.added_evaluations,
                self.lifecycle_transitions,
            )
        )


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SyncError(f"{context}: expected a mapping")
    return dict(value)


def _sequence(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise SyncError(f"{context}: expected a list")
    return value


def _load_document(path: Path) -> dict[str, Any]:
    try:
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as handle:
                return _mapping(json.load(handle), str(path))
        return _mapping(load_yaml(path), str(path))
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise SyncError(f"{path}: cannot load document: {exc}") from exc


def _repo_relative(repo_root: Path, raw_path: Any, context: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path:
        raise SyncError(f"{context}: path must be a non-empty repo-relative string")
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise SyncError(f"{context}: path must remain inside the repository")
    normalized = pure.as_posix()
    candidate = repo_root.joinpath(*pure.parts)
    if not candidate.resolve(strict=False).is_relative_to(repo_root.resolve()):
        raise SyncError(f"{context}: path resolves outside the repository")
    return normalized, candidate


def _slug(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncError(f"{context}: expected a non-empty string")
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not slug or not KEY_PATTERN.fullmatch(slug):
        raise SyncError(f"{context}: cannot normalize {value!r} to a schema key")
    return slug


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _blueprint_paths(repo_root: Path, explicit: Sequence[Path]) -> list[Path]:
    if explicit:
        discovered = [path if path.is_absolute() else repo_root / path for path in explicit]
    else:
        discovered = [repo_root / raw for raw in AUTO_BLUEPRINTS if (repo_root / raw).is_file()]
        discovered.extend(sorted((repo_root / "catalog/blueprints").glob("*.yaml")))
    resolved = sorted({path.resolve() for path in discovered})
    if any(not path.is_relative_to(repo_root.resolve()) for path in resolved):
        raise SyncError("blueprint paths must remain inside the repository")
    return resolved


def _manifest_paths(repo_root: Path, explicit: Sequence[Path]) -> list[Path]:
    if explicit:
        discovered = [path if path.is_absolute() else repo_root / path for path in explicit]
    else:
        discovered = [repo_root / raw for raw in AUTO_MANIFESTS if (repo_root / raw).is_file()]
        discovered.extend(sorted((repo_root / "build").glob("catalog-generation-manifest*.json")))
        discovered.extend(sorted((repo_root / "build").glob("generated-catalog-manifest*.json")))
    resolved = sorted({path.resolve() for path in discovered})
    if any(not path.is_relative_to(repo_root.resolve()) for path in resolved):
        raise SyncError("manifest paths must remain inside the repository")
    return resolved


def _catalog_output_path(repo_root: Path, raw_path: Any, context: str) -> tuple[str, Path]:
    if isinstance(raw_path, str) and len(PurePosixPath(raw_path).parts) == 1:
        raw_path = f"catalog/{raw_path}"
    return _repo_relative(repo_root, raw_path, context)


def _load_blueprints(
    repo_root: Path, paths: Sequence[Path]
) -> tuple[list[CollectionSpec], dict[Path, str]]:
    collections: list[CollectionSpec] = []
    digests: dict[Path, str] = {}
    identifiers: set[str] = set()
    for path in paths:
        data = _load_document(path)
        if data.get("schema_version") != 1:
            raise SyncError(f"{path}: blueprint schema_version must be 1")
        digests[path.resolve()] = _sha256(path)
        for index, raw_collection in enumerate(
            _sequence(data.get("collections"), f"{path}: collections")
        ):
            context = f"{path}: collection {index}"
            collection = _mapping(raw_collection, context)
            identifier = _slug(collection.get("id"), f"{context}.id")
            if identifier in identifiers:
                raise SyncError(f"{context}: duplicate collection ID {identifier!r}")
            identifiers.add(identifier)
            kind = _slug(collection.get("kind"), f"{context}.kind")
            if kind not in SUPPORTED_KINDS:
                raise SyncError(f"{context}: unsupported kind {kind!r}")
            output_file, _ = _catalog_output_path(
                repo_root, collection.get("output_file"), f"{context}.output_file"
            )
            family = _slug(collection.get("family"), f"{context}.family")
            runtime = _mapping(collection.get("runtime"), f"{context}.runtime")
            runtime_file, _ = _repo_relative(
                repo_root, runtime.get("file"), f"{context}.runtime.file"
            )
            if not runtime_file.endswith(".yaml"):
                raise SyncError(f"{context}.runtime.file: expected a YAML path")
            path_prefix = tuple(
                _slug(part, f"{context}.runtime.path_prefix")
                for part in _sequence(
                    runtime.get("path_prefix"), f"{context}.runtime.path_prefix"
                )
            )
            if not path_prefix or path_prefix[0] != "krea2":
                raise SyncError(f"{context}.runtime.path_prefix: must start with 'krea2'")
            source_refs = tuple(
                _slug(source, f"{context}.source_refs")
                for source in _sequence(
                    collection.get("source_refs"), f"{context}.source_refs"
                )
            )
            if not source_refs:
                raise SyncError(f"{context}.source_refs: at least one source is required")
            target_count = collection.get("target_count")
            if not isinstance(target_count, int) or target_count < 1:
                raise SyncError(f"{context}.target_count: expected a positive integer")

            dimensions: dict[str, dict[str, str]] = {}
            for dimension_index, raw_dimension in enumerate(
                _sequence(collection.get("dimensions"), f"{context}.dimensions")
            ):
                dimension_context = f"{context}.dimensions[{dimension_index}]"
                dimension = _mapping(raw_dimension, dimension_context)
                dimension_id = _slug(dimension.get("id"), f"{dimension_context}.id")
                if dimension_id in dimensions:
                    raise SyncError(
                        f"{dimension_context}: duplicate dimension ID {dimension_id!r}"
                    )
                values: dict[str, str] = {}
                for value_index, raw_value in enumerate(
                    _sequence(dimension.get("values"), f"{dimension_context}.values")
                ):
                    value_context = f"{dimension_context}.values[{value_index}]"
                    value = _mapping(raw_value, value_context)
                    value_id = _slug(value.get("id"), f"{value_context}.id")
                    text = value.get("text")
                    if not isinstance(text, str) or not text.strip():
                        raise SyncError(f"{value_context}.text: expected a non-empty string")
                    if value_id in values:
                        raise SyncError(f"{value_context}: duplicate value ID {value_id!r}")
                    values[value_id] = text.strip()
                if not values:
                    raise SyncError(f"{dimension_context}.values: at least one value is required")
                dimensions[dimension_id] = values
            if not dimensions:
                raise SyncError(f"{context}.dimensions: at least one dimension is required")
            product_size = 1
            for values in dimensions.values():
                product_size *= len(values)

            template_ids: set[str] = set()
            for template_index, raw_template in enumerate(
                _sequence(collection.get("templates"), f"{context}.templates")
            ):
                template_context = f"{context}.templates[{template_index}]"
                template = _mapping(raw_template, template_context)
                template_id = _slug(template.get("id"), f"{template_context}.id")
                template_text = template.get("text")
                if template_id in template_ids:
                    raise SyncError(f"{template_context}: duplicate template ID {template_id!r}")
                if not isinstance(template_text, str) or not template_text.strip():
                    raise SyncError(f"{template_context}.text: expected a non-empty string")
                template_ids.add(template_id)
            if not template_ids:
                raise SyncError(f"{context}.templates: at least one template is required")
            product_size *= len(template_ids)
            if target_count > product_size:
                raise SyncError(
                    f"{context}.target_count: cannot exceed template × dimension product size "
                    f"{product_size}"
                )
            compatibility = _mapping(
                collection.get("compatibility"), f"{context}.compatibility"
            )
            for avoided in _sequence(
                compatibility.get("avoid"), f"{context}.compatibility.avoid"
            ):
                _slug(avoided, f"{context}.compatibility.avoid")

            collections.append(
                CollectionSpec(
                    identifier=identifier,
                    kind=kind,
                    output_file=output_file,
                    family=family,
                    runtime_file=runtime_file,
                    path_prefix=path_prefix,
                    source_refs=source_refs,
                    target_count=target_count,
                    product_size=product_size,
                    dimensions=dimensions,
                )
            )
    return collections, digests


def _catalog_items(path: Path) -> dict[str, dict[str, Any]]:
    data = _load_document(path)
    if data.get("schema_version") != 1:
        raise SyncError(f"{path}: catalog schema_version must be 1")
    raw_items = _mapping(data.get("items"), f"{path}: items")
    items: dict[str, dict[str, Any]] = {}
    for raw_item_id, raw_item in raw_items.items():
        item_id = _slug(raw_item_id, f"{path}: item ID")
        if item_id != raw_item_id:
            raise SyncError(f"{path}: item ID {raw_item_id!r} is not canonical snake_case")
        items[item_id] = _mapping(raw_item, f"{path}: item {item_id!r}")
    return items


def _verify_manifests(
    repo_root: Path,
    paths: Sequence[Path],
    collections: Sequence[CollectionSpec],
    blueprint_digests: Mapping[Path, str],
) -> int:
    known_collections = {collection.identifier: collection for collection in collections}
    blueprint_root = (repo_root / "catalog/blueprints").resolve()
    expected_blueprints = []
    for blueprint_path, digest in blueprint_digests.items():
        resolved = blueprint_path.resolve()
        if resolved.is_relative_to(blueprint_root):
            relative = resolved.relative_to(blueprint_root).as_posix()
        else:
            relative = resolved.relative_to(repo_root).as_posix()
        expected_blueprints.append({"path": relative, "sha256": digest})
    expected_blueprints.sort(key=lambda entry: entry["path"])
    combined_blueprint_digest = hashlib.sha256(
        json.dumps(
            expected_blueprints,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    verified_outputs = 0
    covered_collections: set[str] = set()
    covered_outputs: set[str] = set()
    for path in paths:
        data = _load_document(path)
        if data.get("schema_version") != 1:
            raise SyncError(f"{path}: manifest schema_version must be 1")
        if not isinstance(data.get("generator"), str) or not data["generator"].strip():
            raise SyncError(f"{path}: generator must be a non-empty string")
        manifest_blueprints = _sequence(data.get("blueprints"), f"{path}: blueprints")
        if manifest_blueprints != expected_blueprints:
            raise SyncError(f"{path}: blueprints do not match the selected blueprint files")
        if data.get("blueprint_digest") != combined_blueprint_digest:
            raise SyncError(f"{path}: blueprint_digest does not match selected blueprints")
        outputs = _sequence(data.get("outputs"), f"{path}: outputs")
        manifest_output_collections: set[str] = set()
        for index, raw_output in enumerate(outputs):
            context = f"{path}: outputs[{index}]"
            output = _mapping(raw_output, context)
            output_name, output_path = _repo_relative(
                repo_root, output.get("path"), f"{context}.path"
            )
            if output_name in covered_outputs:
                raise SyncError(f"{context}: duplicate output across manifests: {output_name}")
            if not output_path.is_file():
                raise SyncError(f"{context}: output does not exist: {output_name}")
            expected_hash = output.get("sha256")
            actual_hash = _sha256(output_path)
            if expected_hash != actual_hash:
                raise SyncError(f"{context}: sha256 does not match {output_name}")
            items = _catalog_items(output_path)
            item_count = output.get("item_count")
            if item_count != len(items):
                raise SyncError(f"{context}: item_count does not match {output_name}")
            declared_output, _ = _catalog_output_path(
                repo_root, output.get("output_file"), f"{context}.output_file"
            )
            if declared_output != output_name:
                raise SyncError(f"{context}: output_file does not match path")
            collection_ids = _sequence(
                output.get("collection_ids"), f"{context}.collection_ids"
            )
            for identifier in collection_ids:
                if identifier not in known_collections:
                    raise SyncError(f"{context}: unknown collection ID {identifier!r}")
            expected_collection_ids = {
                collection.identifier
                for collection in collections
                if collection.output_file == output_name
            }
            if set(collection_ids) != expected_collection_ids:
                raise SyncError(f"{context}: collection_ids do not match blueprint output ownership")
            generated_ids = _sequence(
                output.get("generated_item_ids"), f"{context}.generated_item_ids"
            )
            if generated_ids != sorted(set(generated_ids)):
                raise SyncError(f"{context}: generated_item_ids must be sorted and unique")
            if any(item_id not in items for item_id in generated_ids):
                raise SyncError(f"{context}: generated_item_ids include missing catalog items")
            expected_generated_count = sum(
                known_collections[identifier].target_count for identifier in collection_ids
            )
            if (
                output.get("generated_item_count") != len(generated_ids)
                or len(generated_ids) != expected_generated_count
            ):
                raise SyncError(f"{context}: generated item ownership count is inconsistent")
            covered_outputs.add(output_name)
            manifest_output_collections.update(collection_ids)
            verified_outputs += 1
        manifest_collection_ids: set[str] = set()
        manifest_generated_count = 0
        for index, raw_collection in enumerate(
            _sequence(data.get("collections"), f"{path}: collections")
        ):
            context = f"{path}: collections[{index}]"
            entry = _mapping(raw_collection, context)
            identifier = entry.get("id")
            collection = known_collections.get(identifier)
            if collection is None:
                raise SyncError(f"{context}: unknown collection ID {identifier!r}")
            if identifier in manifest_collection_ids:
                raise SyncError(f"{context}: duplicate collection entry {identifier!r}")
            manifest_collection_ids.add(identifier)
            if entry.get("kind") != collection.kind:
                raise SyncError(f"{context}: kind does not match blueprint")
            manifest_output_file, _ = _catalog_output_path(
                repo_root, entry.get("output_file"), f"{context}.output_file"
            )
            if manifest_output_file != collection.output_file:
                raise SyncError(f"{context}: output_file does not match blueprint")
            output_path = repo_root.joinpath(*PurePosixPath(collection.output_file).parts)
            if entry.get("output_sha256") != _sha256(output_path):
                raise SyncError(f"{context}: output_sha256 does not match output")
            items = _catalog_items(output_path)
            family_count = sum(item.get("family") == collection.family for item in items.values())
            if entry.get("item_count") != family_count:
                raise SyncError(f"{context}: item_count does not match collection family")
            manifest_generated_count += entry["item_count"]
            if entry.get("product_size") != collection.product_size:
                raise SyncError(f"{context}: product_size does not match blueprint dimensions")
        if data.get("total_item_count") != manifest_generated_count:
            raise SyncError(f"{path}: total_item_count does not match collections")
        if manifest_collection_ids != manifest_output_collections:
            raise SyncError(f"{path}: collection entries do not match output collection_ids")
        covered_collections.update(manifest_collection_ids)
    if paths and covered_collections != set(known_collections):
        missing = sorted(set(known_collections) - covered_collections)
        raise SyncError(f"generated manifests do not cover blueprint collections: {missing}")
    return verified_outputs


def _style_pack_projection(visual_axes: list[str]) -> dict[str, list[str]]:
    result = {axis: [] for axis in ("linework", "face", "eye", "rendering", "composition")}
    composition_markers = (
        "composition",
        "frame",
        "crop",
        "angle",
        "perspective",
        "depth",
        "layout",
        "arch",
        "spiral",
        "symmetry",
        "space",
        "studio",
        "architecture",
        "silhouette",
        "scale",
        "border",
        "vignette",
    )
    for index, term in enumerate(visual_axes):
        if index == 0:
            axis = "linework"
        elif any(marker in term for marker in ("eye", "eyes", "iris", "irises", "gaze")):
            axis = "eye"
        elif term == "angular_forms" or any(
            marker in term
            for marker in ("_line", "lines", "_ink", "contour", "edge", "brush", "pencil")
        ):
            axis = "linework"
        elif any(
            marker in term
            for marker in ("face", "skin", "profile", "features", "expression")
        ):
            axis = "face"
        elif "figure" in term or (
            index == len(visual_axes) - 1
            and any(marker in term for marker in composition_markers)
        ):
            axis = "composition"
        else:
            axis = "rendering"
        result[axis].append(term)
    return result


class V2State:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.features_doc = _load_document(root / "vocab/features.yaml")
        self.sources_doc = _load_document(root / "vocab/sources.yaml")
        self.routes_doc = _load_document(root / "runtime/routes.yaml")
        self.evaluations_doc = _load_document(root / "lifecycle/evaluations.yaml")
        self.lifecycles_doc = _load_document(root / "lifecycle/records.yaml")
        self.features = _mapping(self.features_doc.get("entries"), "feature registry")
        self.sources = _mapping(self.sources_doc.get("entries"), "source registry")
        self.routes = _mapping(self.routes_doc.get("entries"), "runtime route registry")
        self.evaluations = _mapping(
            self.evaluations_doc.get("entries"), "evaluation registry"
        )
        self.lifecycles = _mapping(
            self.lifecycles_doc.get("entries"), "lifecycle registry"
        )
        self.features_doc["entries"] = self.features
        self.sources_doc["entries"] = self.sources
        self.routes_doc["entries"] = self.routes
        self.evaluations_doc["entries"] = self.evaluations
        self.lifecycles_doc["entries"] = self.lifecycles
        self.shards: dict[Path, dict[str, Any]] = {}
        self.item_locations: dict[str, tuple[Path, int]] = {}
        for path in sorted(root.glob("items/**/*.yaml")):
            document = _load_document(path)
            self.shards[path.relative_to(root)] = document
            for index, item in enumerate(
                _sequence(document.get("items"), f"{path}: items")
            ):
                item_mapping = _mapping(item, f"{path}: item {index}")
                item_id = item_mapping.get("id")
                if isinstance(item_id, str):
                    self.item_locations[item_id] = (path.relative_to(root), index)

    def item(self, item_id: str) -> dict[str, Any] | None:
        location = self.item_locations.get(item_id)
        if location is None:
            return None
        path, index = location
        return _mapping(self.shards[path]["items"][index], item_id)

    def put_item(self, kind: str, item: dict[str, Any]) -> bool:
        item_id = item["id"]
        location = self.item_locations.get(item_id)
        if location is not None:
            path, index = location
            changed = self.shards[path]["items"][index] != item
            self.shards[path]["items"][index] = item
            return changed

        kind_shards = sorted(
            (
                (path, document)
                for path, document in self.shards.items()
                if _mapping(document.get("shard"), str(path)).get("kind") == kind
            ),
            key=lambda pair: _mapping(pair[1].get("shard"), str(pair[0])).get("sequence", 0),
        )
        destination: tuple[Path, dict[str, Any]] | None = next(
            (
                pair
                for pair in kind_shards
                if len(_sequence(pair[1].get("items"), str(pair[0]))) < 25
            ),
            None,
        )
        if destination is None:
            sequence = max(
                (
                    _mapping(document.get("shard"), str(path)).get("sequence", 0)
                    for path, document in kind_shards
                ),
                default=0,
            ) + 1
            relative = Path("items") / kind / f"synced_{sequence:03d}.yaml"
            document = {
                "schema_version": 2,
                "catalog": "item_shard",
                "shard": {
                    "id": f"shard:{kind}:synced_{sequence:03d}",
                    "kind": kind,
                    "sequence": sequence,
                    "item_count": 0,
                    "maximum_items": 25,
                },
                "items": [],
            }
            self.shards[relative] = document
            destination = (relative, document)
        path, document = destination
        rows = _sequence(document.get("items"), str(path))
        rows.append(item)
        rows.sort(key=lambda row: row["id"])
        index = next(index for index, row in enumerate(rows) if row["id"] == item_id)
        self.item_locations[item_id] = (path, index)
        for row_index, row in enumerate(rows):
            self.item_locations[row["id"]] = (path, row_index)
        return True

    def write(self, destination: Path) -> None:
        documents = {
            Path("vocab/features.yaml"): self.features_doc,
            Path("vocab/sources.yaml"): self.sources_doc,
            Path("runtime/routes.yaml"): self.routes_doc,
            Path("lifecycle/evaluations.yaml"): self.evaluations_doc,
            Path("lifecycle/records.yaml"): self.lifecycles_doc,
        }
        for path, document in self.shards.items():
            document["shard"]["item_count"] = len(document["items"])
            documents[path] = document
        for relative, document in documents.items():
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                yaml.safe_dump(document, handle, allow_unicode=True, sort_keys=False, width=120)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)


def _feature_ref(
    state: V2State,
    axis: str,
    value: str,
    legacy_term: str,
    label: str,
    report: SyncReport,
) -> str:
    for feature_id, raw_feature in state.features.items():
        feature = _mapping(raw_feature, feature_id)
        if (
            feature.get("axis") == axis
            and feature.get("label") == label
            and legacy_term in feature.get("legacy_terms", [])
        ):
            return feature_id
    base = f"feature:{axis}:{_slug(value, 'feature value')}"
    candidate = base
    expected = {"axis": axis, "label": label, "legacy_terms": [legacy_term]}
    if candidate in state.features and state.features[candidate] != expected:
        suffix = hashlib.sha256(f"{legacy_term}|{label}".encode("utf-8")).hexdigest()[:8]
        candidate = f"{base}_{suffix}"
    if candidate in state.features and state.features[candidate] != expected:
        raise SyncError(f"feature ID collision for {candidate!r}")
    if candidate not in state.features:
        state.features[candidate] = expected
        report.added_features += 1
    return candidate


def _source_ref(
    repo_root: Path, state: V2State, source_name: str, report: SyncReport
) -> str:
    legacy_ref = f"catalog/sources.yaml#sources/{source_name}"
    for source_id, raw_source in state.sources.items():
        if _mapping(raw_source, source_id).get("legacy_ref") == legacy_ref:
            return source_id
    sources_path = repo_root / "catalog/sources.yaml"
    sources = _mapping(_load_document(sources_path).get("sources"), str(sources_path))
    if source_name not in sources:
        raise SyncError(f"source {source_name!r} is not declared in catalog/sources.yaml")
    source_id = f"source:v1:{source_name}"
    if source_id in state.sources:
        raise SyncError(f"source ID collision for {source_name!r}")
    state.sources[source_id] = {"legacy_ref": legacy_ref}
    report.added_sources += 1
    return source_id


def _route_ref(
    state: V2State,
    kind: str,
    runtime_file: str,
    path_prefix: tuple[str, ...],
    report: SyncReport,
) -> str:
    for route_id, raw_route in state.routes.items():
        route = _mapping(raw_route, route_id)
        if route.get("file") == runtime_file and route.get("path_prefix") == list(path_prefix):
            return route_id
    slug = "_".join(path_prefix[1:]) or "root"
    base = f"runtime_route:{kind}:{slug}"
    route_id = base
    expected = {"enabled": True, "file": runtime_file, "path_prefix": list(path_prefix)}
    if route_id in state.routes and state.routes[route_id] != expected:
        suffix = hashlib.sha256(
            f"{runtime_file}|{'/'.join(path_prefix)}".encode("utf-8")
        ).hexdigest()[:8]
        route_id = f"{base}_{suffix}"
    if route_id not in state.routes:
        state.routes[route_id] = expected
        report.added_routes += 1
    return route_id


def _evaluation_ref(
    state: V2State,
    kind: str,
    item_id: str,
    item_ref: str,
    catalog_file: str,
    validation: Mapping[str, Any],
    report: SyncReport,
) -> str:
    tested_seeds = validation.get("tested_seeds")
    if not isinstance(tested_seeds, int) or tested_seeds < 0:
        raise SyncError(f"{catalog_file}#{item_id}: evaluated status requires tested_seeds")
    evaluation_name = _slug(
        validation.get("last_evaluation", "legacy"),
        f"{catalog_file}#{item_id}.validation.last_evaluation",
    )
    evaluation_id = f"evaluation:{kind}:{item_id}_{evaluation_name}_s{tested_seeds}"
    expected = {
        "item_ref": item_ref,
        "legacy_ref": f"{catalog_file}#items/{item_id}/validation",
        "distinct_seed_count": tested_seeds,
        "decision": validation.get("status"),
    }
    existing = state.evaluations.get(evaluation_id)
    if existing is not None and existing != expected:
        raise SyncError(f"evaluation ID collision for {evaluation_id!r}")
    if existing is None:
        state.evaluations[evaluation_id] = expected
        report.added_evaluations += 1
    return evaluation_id


def _reconcile_lifecycle(
    state: V2State,
    kind: str,
    item_id: str,
    status: str,
    evaluation_ref: str | None,
    report: SyncReport,
) -> str:
    item_ref = f"item:{kind}:{item_id}"
    lifecycle_ref = f"lifecycle:{kind}:{item_id}"
    current = state.lifecycles.get(lifecycle_ref)
    if current is None:
        from_status = "testing" if status == "approved" else "research"
        state.lifecycles[lifecycle_ref] = {
            "item_ref": item_ref,
            "current_status": status,
            **({"evaluation_ref": evaluation_ref} if evaluation_ref is not None else {}),
            "history": [
                {
                    "sequence": 1,
                    "from_status": from_status,
                    "to_status": status,
                    **({"evaluation_ref": evaluation_ref} if evaluation_ref is not None else {}),
                }
            ],
        }
        report.lifecycle_transitions += 1
        return lifecycle_ref

    lifecycle = _mapping(current, lifecycle_ref)
    if lifecycle.get("item_ref") != item_ref:
        raise SyncError(f"{lifecycle_ref}: item_ref collision")
    old_status = lifecycle.get("current_status")
    old_evaluation = lifecycle.get("evaluation_ref")
    if old_status != status or old_evaluation != evaluation_ref:
        history = _sequence(lifecycle.get("history"), f"{lifecycle_ref}.history")
        history.append(
            {
                "sequence": len(history) + 1,
                "from_status": old_status,
                "to_status": status,
                **({"evaluation_ref": evaluation_ref} if evaluation_ref is not None else {}),
            }
        )
        lifecycle["current_status"] = status
        if evaluation_ref is None:
            lifecycle.pop("evaluation_ref", None)
        else:
            lifecycle["evaluation_ref"] = evaluation_ref
        state.lifecycles[lifecycle_ref] = lifecycle
        report.lifecycle_transitions += 1
    return lifecycle_ref


def _collection_for_item(
    collections: Sequence[CollectionSpec], item: Mapping[str, Any], context: str
) -> CollectionSpec | None:
    if not collections:
        return None
    family = item.get("family")
    matches = [collection for collection in collections if collection.family == family]
    if len(matches) == 1:
        return matches[0]
    if len(collections) == 1:
        return collections[0]
    raise SyncError(f"{context}: family {family!r} does not identify one blueprint collection")


def _item_feature_axes(
    item: Mapping[str, Any],
    kind: str,
    collection: CollectionSpec | None,
    context: str,
) -> tuple[dict[str, list[tuple[str, str, str]]], list[str]]:
    raw_visual_axes = item.get("visual_axes", [])
    visual_axes = [
        _slug(value, f"{context}.visual_axes")
        for value in _sequence(raw_visual_axes, f"{context}.visual_axes")
    ]
    raw_axes = item.get("feature_axes", item.get("normalized_features"))
    if isinstance(raw_axes, Mapping):
        result: dict[str, list[tuple[str, str, str]]] = {}
        for raw_axis, raw_values in raw_axes.items():
            axis = _slug(raw_axis, f"{context}.feature_axes")
            if collection is not None and axis not in collection.dimensions:
                raise SyncError(
                    f"{context}.feature_axes: axis {axis!r} is not declared by the blueprint"
                )
            values = [
                _slug(value, f"{context}.feature_axes.{axis}")
                for value in _sequence(raw_values, f"{context}.feature_axes.{axis}")
            ]
            projected: list[tuple[str, str, str]] = []
            for value in values:
                if collection is not None and value not in collection.dimensions[axis]:
                    raise SyncError(
                        f"{context}.feature_axes.{axis}: value {value!r} is not declared by the blueprint"
                    )
                combined = f"{axis}_{value}"
                legacy_term = combined if combined in visual_axes else value
                projected.append(
                    (value, legacy_term, value.replace("_", " ").capitalize())
                )
            result[axis] = projected
        if collection is not None:
            if set(result) != set(collection.dimensions):
                raise SyncError(
                    f"{context}.feature_axes: axes must exactly match blueprint dimensions"
                )
            if any(len(values) != 1 for values in result.values()):
                raise SyncError(
                    f"{context}.feature_axes: each blueprint dimension must select exactly one value"
                )
            expected_visual_axes = sorted(
                f"{axis}_{values[0][0]}" for axis, values in result.items()
            )
            if sorted(visual_axes) != expected_visual_axes:
                raise SyncError(
                    f"{context}.visual_axes: must exactly project blueprint feature_axes"
                )
        return result, visual_axes

    if kind == "style_pack":
        projection = _style_pack_projection(visual_axes)
        return {
            axis: [(term, term, term.replace("_", " ").capitalize()) for term in terms]
            for axis, terms in projection.items()
        }, visual_axes

    primary_axis = PRIMARY_AXES[kind]
    return {
        primary_axis: [
            (term, term, term.replace("_", " ").capitalize()) for term in visual_axes
        ]
    }, visual_axes


def _catalog_specs(
    repo_root: Path, collections: Sequence[CollectionSpec]
) -> dict[str, tuple[str, list[CollectionSpec]]]:
    specs: dict[str, tuple[str, list[CollectionSpec]]] = {}
    for relative, kind in ORDINARY_CATALOGS.items():
        if (repo_root / relative).is_file():
            specs[relative] = (kind, [])
    grouped: dict[str, list[CollectionSpec]] = defaultdict(list)
    for collection in collections:
        grouped[collection.output_file].append(collection)
    for output_file, output_collections in grouped.items():
        kinds = {collection.kind for collection in output_collections}
        if len(kinds) != 1:
            raise SyncError(f"{output_file}: one v1 catalog cannot contain multiple item kinds")
        specs[output_file] = (next(iter(kinds)), output_collections)
    return dict(sorted(specs.items()))


def _sync_to_stage(
    repo_root: Path,
    catalog_v2: Path,
    blueprint_paths: Sequence[Path],
    manifest_paths: Sequence[Path],
    report: SyncReport,
) -> Path:
    collections, blueprint_digests = _load_blueprints(repo_root, blueprint_paths)
    if collections and not manifest_paths:
        raise SyncError("blueprint-driven catalogs require a generated manifest")
    if manifest_paths and not collections:
        raise SyncError("generated manifests require at least one blueprint")
    report.manifest_outputs_verified = _verify_manifests(
        repo_root, manifest_paths, collections, blueprint_digests
    )
    specs = _catalog_specs(repo_root, collections)
    state = V2State(catalog_v2)
    pending_items: list[tuple[str, dict[str, Any], bool]] = []

    for catalog_file, (kind, file_collections) in specs.items():
        _, catalog_path = _repo_relative(repo_root, catalog_file, "catalog file")
        if not catalog_path.is_file():
            raise SyncError(f"catalog file does not exist: {catalog_file}")
        items = _catalog_items(catalog_path)
        report.catalog_files += 1
        family_counts: dict[str, int] = defaultdict(int)
        for item in items.values():
            family = item.get("family")
            if isinstance(family, str):
                family_counts[family] += 1
        for collection in file_collections:
            if family_counts.get(collection.family, 0) != collection.target_count:
                raise SyncError(
                    f"{catalog_file}: family {collection.family!r} count does not match "
                    f"blueprint target_count {collection.target_count}"
                )

        for item_id, legacy_item in sorted(items.items()):
            report.scanned_items += 1
            context = f"{catalog_file}#items/{item_id}"
            item_ref = f"item:{kind}:{item_id}"
            existing = state.item(item_ref)
            collection = _collection_for_item(file_collections, legacy_item, context)
            if existing is not None and existing.get("legacy_ref") != context:
                raise SyncError(f"{item_ref}: legacy_ref collision")

            preserve_foundation_projection = (
                existing is not None
                and existing.get("legacy_ref", "").startswith(
                    "catalog/art_styles.yaml#items/"
                )
            )
            if not preserve_foundation_projection:
                projected_axes, _ = _item_feature_axes(
                    legacy_item, kind, collection, context
                )
                feature_refs = {
                    axis: [
                        _feature_ref(state, axis, value, legacy_term, label, report)
                        for value, legacy_term, label in projected
                    ]
                    for axis, projected in sorted(projected_axes.items())
                }
                raw_source_refs = legacy_item.get("source_refs")
                if raw_source_refs is None and collection is not None:
                    raw_source_refs = list(collection.source_refs)
                source_refs = [
                    _source_ref(
                        repo_root,
                        state,
                        _slug(source, f"{context}.source_refs"),
                        report,
                    )
                    for source in _sequence(raw_source_refs, f"{context}.source_refs")
                ]
                if not source_refs:
                    raise SyncError(f"{context}: source_refs must not be empty")
            else:
                feature_refs = _mapping(existing.get("feature_refs"), f"{item_ref}.feature_refs")
                source_refs = _sequence(existing.get("source_refs"), f"{item_ref}.source_refs")

            raw_runtime = legacy_item.get("runtime")
            if raw_runtime is None and collection is not None:
                runtime_file = collection.runtime_file
                path_prefix = collection.path_prefix
                runtime_path = [*path_prefix, item_id]
            else:
                runtime = _mapping(raw_runtime, f"{context}.runtime")
                runtime_file, _ = _repo_relative(
                    repo_root, runtime.get("file"), f"{context}.runtime.file"
                )
                runtime_path = [
                    _slug(part, f"{context}.runtime.path")
                    for part in _sequence(runtime.get("path"), f"{context}.runtime.path")
                ]
                if not runtime_path or runtime_path[-1] != item_id:
                    raise SyncError(f"{context}.runtime.path: final key must equal item ID")
                path_prefix = tuple(runtime_path[:-1])
            route_ref = _route_ref(
                state, kind, runtime_file, tuple(path_prefix), report
            )

            validation = _mapping(legacy_item.get("validation"), f"{context}.validation")
            status = validation.get("status")
            if not isinstance(status, str):
                raise SyncError(f"{context}.validation.status: expected a string")
            evaluation_ref: str | None = None
            if status in EVALUATION_REQUIRED:
                existing_evaluation_ref = existing.get("evaluation_ref") if existing else None
                existing_evaluation = state.evaluations.get(existing_evaluation_ref)
                existing_lifecycle = (
                    state.lifecycles.get(existing.get("lifecycle_ref")) if existing else None
                )
                if (
                    isinstance(existing_evaluation_ref, str)
                    and isinstance(existing_evaluation, Mapping)
                    and isinstance(existing_lifecycle, Mapping)
                    and existing_lifecycle.get("current_status") == status
                    and existing_evaluation.get("distinct_seed_count")
                    == validation.get("tested_seeds")
                ):
                    evaluation_ref = existing_evaluation_ref
                else:
                    evaluation_ref = _evaluation_ref(
                        state,
                        kind,
                        item_id,
                        item_ref,
                        catalog_file,
                        validation,
                        report,
                    )
            lifecycle_ref = _reconcile_lifecycle(
                state, kind, item_id, status, evaluation_ref, report
            )
            new_item = {
                "id": item_ref,
                "legacy_ref": context,
                "feature_refs": feature_refs,
                "source_refs": source_refs,
                **({"evaluation_ref": evaluation_ref} if evaluation_ref is not None else {}),
                "lifecycle_ref": lifecycle_ref,
                "runtime_route_ref": route_ref,
            }
            pending_items.append((kind, new_item, existing is None))

    for kind, item, is_new in sorted(pending_items, key=lambda row: row[1]["id"]):
        changed = state.put_item(kind, item)
        if is_new:
            report.added_items += 1
        elif changed:
            report.updated_items += 1

    stage = Path(
        tempfile.mkdtemp(prefix=".catalog_v2.sync.", dir=catalog_v2.parent)
    )
    try:
        shutil.copytree(catalog_v2, stage, dirs_exist_ok=True)
        state.write(stage)
        errors = validate_catalog_v2(stage)
        if errors:
            raise SyncError("staged catalog-v2 validation failed:\n" + "\n".join(errors))
        return stage
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def sync_catalog_v2(
    repo_root: Path = ROOT,
    catalog_v2: Path | None = None,
    blueprint_paths: Sequence[Path] = (),
    manifest_paths: Sequence[Path] = (),
    *,
    apply: bool = False,
) -> SyncReport:
    repo_root = repo_root.resolve()
    catalog_v2 = (catalog_v2 or repo_root / "catalog_v2").resolve()
    if catalog_v2.parent != repo_root:
        raise SyncError("catalog_v2 must be a direct child of repo_root for transactional replacement")
    if not catalog_v2.is_dir():
        raise SyncError(f"catalog-v2 root does not exist: {catalog_v2}")
    blueprints = _blueprint_paths(repo_root, blueprint_paths)
    manifests = _manifest_paths(repo_root, manifest_paths)
    before_digest = _tree_digest(catalog_v2)
    report = SyncReport(dry_run=not apply)
    stage = _sync_to_stage(repo_root, catalog_v2, blueprints, manifests, report)
    if not apply:
        shutil.rmtree(stage, ignore_errors=True)
        if _tree_digest(catalog_v2) != before_digest:
            raise SyncError("dry-run invariant failed: catalog_v2 changed")
        return report

    backup = catalog_v2.parent / f".{catalog_v2.name}.backup.{uuid.uuid4().hex}"
    os.replace(catalog_v2, backup)
    try:
        os.replace(stage, catalog_v2)
    except Exception:
        os.replace(backup, catalog_v2)
        shutil.rmtree(stage, ignore_errors=True)
        raise
    shutil.rmtree(backup)
    report.dry_run = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project v1 catalogs and generated blueprint metadata into schema-v2."
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--catalog-v2", type=Path)
    parser.add_argument("--blueprint", action="append", type=Path, default=[])
    parser.add_argument("--manifest", action="append", type=Path, default=[])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="transactionally replace catalog_v2 after staged validation (default is dry-run)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="stage and validate without changing catalog_v2 (the default mode)",
    )
    args = parser.parse_args()
    try:
        report = sync_catalog_v2(
            repo_root=args.repo_root,
            catalog_v2=args.catalog_v2,
            blueprint_paths=args.blueprint,
            manifest_paths=args.manifest,
            apply=args.apply,
        )
    except SyncError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(asdict(report) | {"changed": report.changed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
