from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from common import load_yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "catalog_v2"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load(path: Path, errors: list[str]) -> Any | None:
    try:
        return load_yaml(path)
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        errors.append(f"{path}: cannot load YAML: {exc}")
        return None


def _legacy_value(
    repo_root: Path,
    ref: Any,
    context: str,
    errors: list[str],
    document_cache: dict[Path, Any] | None = None,
) -> Any | None:
    if not isinstance(ref, str) or "#" not in ref:
        errors.append(f"{context}: legacy_ref must be a relative-file#mapping/path reference")
        return None
    file_name, fragment = ref.split("#", 1)
    relative = PurePosixPath(file_name)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{context}: legacy_ref must remain inside the repository: {ref!r}")
        return None
    path = repo_root.joinpath(*relative.parts)
    if document_cache is not None and path in document_cache:
        data = document_cache[path]
    else:
        data = _load(path, errors)
        if document_cache is not None and data is not None:
            document_cache[path] = data
    if data is None:
        return None
    value = data
    for segment in (part for part in fragment.split("/") if part):
        if not isinstance(value, Mapping) or segment not in value:
            errors.append(f"{context}: dangling legacy_ref {ref!r}")
            return None
        value = value[segment]
    return value


def _check_namespaced_id(
    value: Any,
    namespace: str,
    pattern: re.Pattern[str],
    context: str,
    errors: list[str],
) -> bool:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        errors.append(f"{context}: invalid namespaced ID {value!r}")
        return False
    if value.split(":", 1)[0] != namespace:
        errors.append(f"{context}: expected {namespace!r} namespace, got {value!r}")
        return False
    return True


def _check_ref(
    value: Any,
    namespace: str,
    entries: Mapping[str, Any],
    pattern: re.Pattern[str],
    context: str,
    errors: list[str],
) -> bool:
    valid = _check_namespaced_id(value, namespace, pattern, context, errors)
    if valid and value not in entries:
        errors.append(f"{context}: dangling {namespace} reference {value!r}")
        return False
    return valid


def validate_catalog_v2(catalog_root: Path = DEFAULT_CATALOG) -> list[str]:
    """Return every schema-v2 validation error without mutating either catalog tree."""

    catalog_root = catalog_root.resolve()
    repo_root = catalog_root.parent
    errors: list[str] = []
    legacy_document_cache: dict[Path, Any] = {}
    schema_path = catalog_root / "meta" / "schema.yaml"
    schema_data = _load(schema_path, errors)
    schema = _mapping(schema_data)
    if not schema:
        return errors or [f"{schema_path}: expected a mapping"]
    if schema.get("schema_version") != 2 or schema.get("catalog") != "meta_schema":
        errors.append(f"{schema_path}: expected schema_version 2 meta_schema")

    try:
        id_pattern = re.compile(str(schema["id_pattern"]))
    except (KeyError, re.error) as exc:
        errors.append(f"{schema_path}: invalid id_pattern: {exc}")
        return errors

    global_origins: dict[str, str] = {}

    def register(identifier: str, origin: str) -> None:
        previous = global_origins.get(identifier)
        if previous is not None:
            errors.append(f"{origin}: duplicate global ID {identifier!r}; first declared at {previous}")
        else:
            global_origins[identifier] = origin

    registries: dict[str, Mapping[str, Any]] = {}
    registry_specs = _mapping(schema.get("registries"))
    for registry_name, raw_spec in registry_specs.items():
        spec = _mapping(raw_spec)
        relative_file = spec.get("file")
        namespace = spec.get("namespace")
        expected_catalog = spec.get("catalog")
        if not all(isinstance(value, str) for value in (relative_file, namespace, expected_catalog)):
            errors.append(f"{schema_path}: registry {registry_name!r} has incomplete metadata")
            registries[registry_name] = {}
            continue
        registry_path = catalog_root / relative_file
        data = _mapping(_load(registry_path, errors))
        if data.get("schema_version") != 2 or data.get("catalog") != expected_catalog:
            errors.append(
                f"{registry_path}: expected schema_version 2 catalog {expected_catalog!r}"
            )
        if data.get("namespace") != namespace:
            errors.append(f"{registry_path}: expected namespace {namespace!r}")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, Mapping):
            errors.append(f"{registry_path}: entries must be a mapping")
            entries: Mapping[str, Any] = {}
        else:
            entries = raw_entries
        registries[registry_name] = entries
        for identifier, entry in entries.items():
            context = f"{registry_path}: entry"
            if _check_namespaced_id(identifier, namespace, id_pattern, context, errors):
                register(identifier, str(registry_path))
            if not isinstance(entry, Mapping):
                errors.append(f"{registry_path}: entry {identifier!r} must be a mapping")

    features = registries.get("features", {})
    sources = registries.get("sources", {})
    evaluations = registries.get("evaluations", {})
    lifecycles = registries.get("lifecycles", {})
    runtime_routes = registries.get("runtime_routes", {})

    for feature_id, raw_feature in features.items():
        feature = _mapping(raw_feature)
        axis = feature.get("axis")
        if not isinstance(axis, str) or feature_id.split(":")[1:2] != [axis]:
            errors.append(f"feature {feature_id!r}: axis must match the second ID segment")
        if not isinstance(feature.get("label"), str) or not feature["label"].strip():
            errors.append(f"feature {feature_id!r}: label must be a non-empty string")
        legacy_terms = feature.get("legacy_terms")
        if legacy_terms is not None and (
            not isinstance(legacy_terms, list)
            or not legacy_terms
            or any(not isinstance(term, str) or not term for term in legacy_terms)
        ):
            errors.append(f"feature {feature_id!r}: legacy_terms must be non-empty strings")

    for source_id, raw_source in sources.items():
        source = _mapping(raw_source)
        if "legacy_ref" in source:
            _legacy_value(
                repo_root,
                source["legacy_ref"],
                f"source {source_id!r}",
                errors,
                legacy_document_cache,
            )

    for route_id, raw_route in runtime_routes.items():
        route = _mapping(raw_route)
        if not isinstance(route.get("enabled"), bool):
            errors.append(f"runtime route {route_id!r}: enabled must be boolean")
        runtime_file = route.get("file")
        if (
            not isinstance(runtime_file, str)
            or PurePosixPath(runtime_file).is_absolute()
            or ".." in PurePosixPath(runtime_file).parts
            or not runtime_file.endswith(".yaml")
        ):
            errors.append(f"runtime route {route_id!r}: file must be a relative YAML path")
        path_prefix = route.get("path_prefix")
        if (
            not isinstance(path_prefix, list)
            or not path_prefix
            or path_prefix[0] != "krea2"
            or any(not isinstance(part, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", part) for part in path_prefix)
        ):
            errors.append(f"runtime route {route_id!r}: path_prefix must be a krea2 key path")

    shard_spec = _mapping(schema.get("shards"))
    shard_glob = shard_spec.get("glob", "items/**/*.yaml")
    shard_namespace = shard_spec.get("namespace", "shard")
    item_namespace = shard_spec.get("item_namespace", "item")
    maximum_items = shard_spec.get("maximum_items", 25)
    item_kinds = _mapping(schema.get("item_kinds"))
    items: dict[str, Mapping[str, Any]] = {}
    item_origins: dict[str, Path] = {}
    legacy_items: dict[str, Mapping[str, Any]] = {}
    legacy_ref_origins: dict[str, str] = {}
    shard_sequence_origins: dict[tuple[str, int], Path] = {}

    shard_paths = sorted(catalog_root.glob(str(shard_glob)))
    if not shard_paths:
        errors.append(f"{catalog_root}: no item shards matched {shard_glob!r}")
    for shard_path in shard_paths:
        data = _mapping(_load(shard_path, errors))
        if data.get("schema_version") != 2 or data.get("catalog") != "item_shard":
            errors.append(f"{shard_path}: expected schema_version 2 item_shard")
        shard = _mapping(data.get("shard"))
        shard_id = shard.get("id")
        kind = shard.get("kind")
        if _check_namespaced_id(shard_id, str(shard_namespace), id_pattern, str(shard_path), errors):
            register(shard_id, str(shard_path))
        if not isinstance(kind, str) or kind not in item_kinds:
            errors.append(f"{shard_path}: unknown shard kind {kind!r}")
        elif len(shard_path.relative_to(catalog_root / "items").parts) < 2 or shard_path.parent.name != kind:
            errors.append(f"{shard_path}: shard kind must match its items/<kind>/ directory")
        sequence = shard.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            errors.append(f"{shard_path}: shard sequence must be a positive integer")
        elif isinstance(kind, str):
            sequence_key = (kind, sequence)
            previous_path = shard_sequence_origins.get(sequence_key)
            if previous_path is not None:
                errors.append(
                    f"{shard_path}: duplicate shard sequence {sequence} for kind {kind!r}; "
                    f"first declared at {previous_path}"
                )
            else:
                shard_sequence_origins[sequence_key] = shard_path
        if shard.get("maximum_items") != maximum_items:
            errors.append(f"{shard_path}: shard maximum_items must equal {maximum_items}")
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            errors.append(f"{shard_path}: items must be a list")
            raw_items = []
        if shard.get("item_count") != len(raw_items):
            errors.append(f"{shard_path}: shard item_count does not match items length")
        if len(raw_items) > maximum_items:
            errors.append(f"{shard_path}: shard exceeds maximum of {maximum_items} items")
        for index, raw_item in enumerate(raw_items):
            context = f"{shard_path}: item {index}"
            item = _mapping(raw_item)
            if not item:
                errors.append(f"{context}: item must be a mapping")
                continue
            item_id = item.get("id")
            if not _check_namespaced_id(item_id, str(item_namespace), id_pattern, context, errors):
                continue
            parts = item_id.split(":")
            if isinstance(kind, str) and (len(parts) < 3 or parts[1] != kind):
                errors.append(f"{context}: item ID kind must match shard kind {kind!r}")
            register(item_id, context)
            if item_id in items:
                errors.append(f"{context}: duplicate item ID {item_id!r}")
            else:
                items[item_id] = item
                item_origins[item_id] = shard_path
            legacy_ref = item.get("legacy_ref")
            if isinstance(legacy_ref, str):
                previous = legacy_ref_origins.get(legacy_ref)
                if previous is not None:
                    errors.append(
                        f"{context}: duplicate legacy_ref {legacy_ref!r}; first declared at {previous}"
                    )
                else:
                    legacy_ref_origins[legacy_ref] = context
            legacy = _legacy_value(
                repo_root, legacy_ref, context, errors, legacy_document_cache
            )
            if isinstance(legacy, Mapping):
                legacy_items[item_id] = legacy
            for prompt_field in ("prompt", "prompts"):
                if prompt_field in item:
                    errors.append(
                        f"{context}: {prompt_field} text must remain behind legacy_ref during migration"
                    )

    lifecycle_rules = _mapping(schema.get("lifecycle"))
    statuses = set(_list(lifecycle_rules.get("statuses")))
    evaluation_required = set(_list(lifecycle_rules.get("evaluation_required_statuses")))
    route_required = set(_list(lifecycle_rules.get("runtime_route_required_statuses")))

    for item_id, item in items.items():
        context = f"{item_origins[item_id]}: {item_id}"
        kind = item_id.split(":")[1]
        kind_spec = _mapping(item_kinds.get(kind))
        axis_specs = _mapping(kind_spec.get("feature_axes"))
        feature_refs = item.get("feature_refs")
        if not isinstance(feature_refs, Mapping):
            errors.append(f"{context}: feature_refs must be an axis mapping")
            feature_refs = {}
        extra_axes = set(feature_refs) - set(axis_specs)
        allow_additional_axes = kind_spec.get("additional_feature_axes") is True
        if not allow_additional_axes:
            if extra_axes:
                errors.append(f"{context}: unsupported feature axes {sorted(extra_axes)}")
        axes_to_check = set(axis_specs)
        if allow_additional_axes:
            axes_to_check.update(extra_axes)
        additional_limits = _mapping(kind_spec.get("additional_feature_axis"))
        for axis in sorted(axes_to_check):
            limits = _mapping(axis_specs.get(axis, additional_limits))
            refs = feature_refs.get(axis)
            if not isinstance(refs, list):
                refs = []
            minimum = limits.get("minimum", 0)
            maximum = limits.get("maximum", 0)
            if not isinstance(minimum, int) or not isinstance(maximum, int) or not minimum <= len(refs) <= maximum:
                errors.append(
                    f"{context}: feature axis {axis!r} requires {minimum}..{maximum} references, got {len(refs)}"
                )
            for ref in refs:
                if _check_ref(ref, "feature", features, id_pattern, context, errors):
                    feature = _mapping(features[ref])
                    if feature.get("axis") != axis:
                        errors.append(f"{context}: feature {ref!r} belongs to axis {feature.get('axis')!r}")
        total_features = sum(
            len(refs) for refs in feature_refs.values() if isinstance(refs, list)
        )
        minimum_total = kind_spec.get("minimum_total_features")
        maximum_total = kind_spec.get("maximum_total_features")
        if isinstance(minimum_total, int) and total_features < minimum_total:
            errors.append(
                f"{context}: item kind {kind!r} requires at least {minimum_total} total feature references"
            )
        if isinstance(maximum_total, int) and total_features > maximum_total:
            errors.append(
                f"{context}: item kind {kind!r} allows at most {maximum_total} total feature references"
            )

        source_refs = item.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            errors.append(f"{context}: source_refs must be a non-empty list")
        else:
            for ref in source_refs:
                _check_ref(ref, "source", sources, id_pattern, context, errors)

        lifecycle_ref = item.get("lifecycle_ref")
        lifecycle_ok = _check_ref(
            lifecycle_ref, "lifecycle", lifecycles, id_pattern, context, errors
        )
        lifecycle = _mapping(lifecycles.get(lifecycle_ref)) if lifecycle_ok else {}
        status = lifecycle.get("current_status")
        if lifecycle and lifecycle.get("item_ref") != item_id:
            errors.append(f"{context}: lifecycle item_ref does not link back to the item")
        if status not in statuses:
            errors.append(f"{context}: unknown lifecycle status {status!r}")

        evaluation_ref = item.get("evaluation_ref")
        if status not in evaluation_required and evaluation_ref is not None:
            errors.append(
                f"{context}: status {status!r} must not declare a current evaluation_ref"
            )
        if status in evaluation_required:
            evaluation_ok = _check_ref(
                evaluation_ref, "evaluation", evaluations, id_pattern, context, errors
            )
            evaluation = _mapping(evaluations.get(evaluation_ref)) if evaluation_ok else {}
            if evaluation and evaluation.get("item_ref") != item_id:
                errors.append(f"{context}: evaluation item_ref does not link back to the item")
            if lifecycle and lifecycle.get("evaluation_ref") != evaluation_ref:
                errors.append(f"{context}: lifecycle and item evaluation refs differ")

        route_ref = item.get("runtime_route_ref")
        route_ok = False
        if status in route_required or route_ref is not None:
            route_ok = _check_ref(
                route_ref, "runtime_route", runtime_routes, id_pattern, context, errors
            )
            route = _mapping(runtime_routes.get(route_ref)) if route_ok else {}
            if status in route_required and route.get("enabled") is not True:
                errors.append(f"{context}: status {status!r} requires an enabled runtime route")
        else:
            route = {}

        legacy = legacy_items.get(item_id)
        if route_ok and legacy:
            legacy_runtime = _mapping(legacy.get("runtime"))
            expected_path = [*_list(route.get("path_prefix")), item_id.split(":")[-1]]
            if legacy_runtime.get("file") != route.get("file") or legacy_runtime.get("path") != expected_path:
                errors.append(f"{context}: runtime route does not preserve the legacy public path")

    coverage_specs = _mapping(schema.get("legacy_coverage"))
    for coverage_name, raw_coverage in coverage_specs.items():
        coverage = _mapping(raw_coverage)
        kind = coverage.get("kind")
        mapping_ref = coverage.get("mapping_ref")
        context = f"{schema_path}: legacy coverage {coverage_name!r}"
        if not isinstance(kind, str) or kind not in item_kinds:
            errors.append(f"{context}: kind must name a declared item kind")
            continue
        legacy_mapping = _legacy_value(
            repo_root, mapping_ref, context, errors, legacy_document_cache
        )
        if not isinstance(legacy_mapping, Mapping):
            errors.append(f"{context}: mapping_ref must resolve to a mapping")
            continue
        if not isinstance(mapping_ref, str):
            continue
        for legacy_id, raw_legacy in legacy_mapping.items():
            expected_item_id = f"item:{kind}:{legacy_id}"
            expected_ref = f"{mapping_ref}/{legacy_id}"
            item = items.get(expected_item_id)
            if item is None:
                errors.append(f"{context}: missing migrated item {expected_item_id!r}")
                continue
            if item.get("legacy_ref") != expected_ref:
                errors.append(
                    f"{context}: {expected_item_id!r} must use legacy_ref {expected_ref!r}"
                )

            legacy = _mapping(raw_legacy)
            expected_terms = sorted(term for term in _list(legacy.get("visual_axes")) if isinstance(term, str))
            projected_terms: list[str] = []
            for refs in _mapping(item.get("feature_refs")).values():
                for feature_ref in _list(refs):
                    feature = _mapping(features.get(feature_ref))
                    projected_terms.extend(
                        term
                        for term in _list(feature.get("legacy_terms"))
                        if isinstance(term, str)
                    )
            if sorted(projected_terms) != expected_terms:
                errors.append(
                    f"{context}: {expected_item_id!r} feature projection does not preserve legacy visual_axes"
                )

            lifecycle = _mapping(lifecycles.get(item.get("lifecycle_ref")))
            validation = _mapping(legacy.get("validation"))
            if lifecycle.get("current_status") != validation.get("status"):
                errors.append(
                    f"{context}: {expected_item_id!r} lifecycle status does not match legacy validation"
                )
            evaluation = _mapping(evaluations.get(item.get("evaluation_ref")))
            if evaluation.get("distinct_seed_count") != validation.get("tested_seeds"):
                errors.append(
                    f"{context}: {expected_item_id!r} seed count does not match legacy validation"
                )

    for evaluation_id, raw_evaluation in evaluations.items():
        evaluation = _mapping(raw_evaluation)
        item_ref = evaluation.get("item_ref")
        _check_ref(item_ref, "item", items, id_pattern, f"evaluation {evaluation_id!r}", errors)
        if "legacy_ref" in evaluation:
            _legacy_value(
                repo_root,
                evaluation["legacy_ref"],
                f"evaluation {evaluation_id!r}",
                errors,
                legacy_document_cache,
            )
        if not isinstance(evaluation.get("distinct_seed_count"), int) or evaluation["distinct_seed_count"] < 0:
            errors.append(f"evaluation {evaluation_id!r}: distinct_seed_count must be non-negative")

    for lifecycle_id, raw_lifecycle in lifecycles.items():
        lifecycle = _mapping(raw_lifecycle)
        item_ref = lifecycle.get("item_ref")
        _check_ref(item_ref, "item", items, id_pattern, f"lifecycle {lifecycle_id!r}", errors)
        current_status = lifecycle.get("current_status")
        if current_status not in statuses:
            errors.append(f"lifecycle {lifecycle_id!r}: unknown current_status {current_status!r}")
        evaluation_ref = lifecycle.get("evaluation_ref")
        if current_status not in evaluation_required and evaluation_ref is not None:
            errors.append(
                f"lifecycle {lifecycle_id!r}: status {current_status!r} must not declare a current evaluation_ref"
            )
        if current_status in evaluation_required:
            _check_ref(
                evaluation_ref,
                "evaluation",
                evaluations,
                id_pattern,
                f"lifecycle {lifecycle_id!r}",
                errors,
            )
        history = lifecycle.get("history")
        if not isinstance(history, list) or not history:
            errors.append(f"lifecycle {lifecycle_id!r}: history must be a non-empty list")
        else:
            previous_to_status: Any | None = None
            for expected_sequence, transition in enumerate(history, start=1):
                record = _mapping(transition)
                if record.get("sequence") != expected_sequence:
                    errors.append(f"lifecycle {lifecycle_id!r}: history sequence must be contiguous")
                if record.get("to_status") not in statuses or record.get("from_status") not in statuses:
                    errors.append(f"lifecycle {lifecycle_id!r}: transition uses an unknown status")
                if expected_sequence > 1 and record.get("from_status") != previous_to_status:
                    errors.append(
                        f"lifecycle {lifecycle_id!r}: transition status chain must be contiguous"
                    )
                if record.get("evaluation_ref") is not None:
                    _check_ref(
                        record["evaluation_ref"],
                        "evaluation",
                        evaluations,
                        id_pattern,
                        f"lifecycle {lifecycle_id!r}",
                        errors,
                    )
                previous_to_status = record.get("to_status")
            if _mapping(history[-1]).get("to_status") != current_status:
                errors.append(f"lifecycle {lifecycle_id!r}: final transition must match current_status")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the isolated catalog schema-v2 tree.")
    parser.add_argument("catalog", nargs="?", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    errors = validate_catalog_v2(args.catalog)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "OK: catalog v2 reference closure, legacy coverage, lifecycle, "
        "cardinality, and runtime routes are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
