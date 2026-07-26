#!/usr/bin/env python3
"""Compile deterministic expansion blueprints into schema-v1 catalog files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import string
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from common import FoldedStringDumper, KEY_RE, load_yaml, normalized_phrase
from lint_wildcards import repetition_issue


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLUEPRINTS = Path("catalog/blueprints")
DEFAULT_OUTPUT_ROOT = Path("catalog")
DEFAULT_SOURCES = Path("catalog/sources.yaml")
DEFAULT_MANIFEST = Path("build/catalog-generation-manifest.json")
GENERATOR_ID = "krea2_catalog_expansion_v1"
MAX_ITEM_ID_LENGTH = 180
RESERVED_OUTPUTS = {
    "aliases.yaml",
    "compatibility.yaml",
    "evaluation.yaml",
    "family_templates.yaml",
    "roadmap.yaml",
    "schema.yaml",
    "sources.yaml",
}
PROHIBITED_PROSE = (
    ("legacy subject tag", re.compile(r"\b(?:1girl|1boy)\b", re.IGNORECASE)),
    (
        "youth-coded subject",
        re.compile(r"\b(?:child|minor|underage|schoolgirl|schoolboy|young teen)\b", re.IGNORECASE),
    ),
    (
        "non-prose rendering token",
        re.compile(r"\b(?:anime|manga|illustration|cgi|digital[- ]art|2d|3d[- ]render)\b", re.IGNORECASE),
    ),
    ("quality score tag", re.compile(r"\b(?:score_\d+|absurdres)\b", re.IGNORECASE)),
    ("forbidden name", re.compile(r"\bvelyra\b", re.IGNORECASE)),
    ("legacy delimiter", re.compile(r"\bBREAK\s*,", re.IGNORECASE)),
    ("artist tag", re.compile(r"(?<!\w)@[a-z0-9_]", re.IGNORECASE)),
    ("NovelAI emphasis", re.compile(r"::|\[[^\]]+\]")),
)


@dataclass(frozen=True)
class ValueSpec:
    id: str
    text: str


@dataclass(frozen=True)
class DimensionSpec:
    id: str
    values: tuple[ValueSpec, ...]


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    text: str


@dataclass(frozen=True)
class RetrySpec:
    template: str
    dimensions: tuple[DimensionSpec, ...]


@dataclass(frozen=True)
class CollectionSpec:
    id: str
    kind: str
    output_file: str
    family: str
    runtime_file: str
    runtime_path_prefix: tuple[str, ...]
    source_refs: tuple[str, ...]
    target_count: int
    dimensions: tuple[DimensionSpec, ...]
    templates: tuple[TemplateSpec, ...]
    prompt_overrides: tuple[tuple[str, str], ...]
    retry: RetrySpec | None
    compatibility_avoid: tuple[str, ...]

    @property
    def product_size(self) -> int:
        return len(self.templates) * math.prod(len(dimension.values) for dimension in self.dimensions)


@dataclass(frozen=True)
class Compilation:
    documents: dict[str, dict[str, Any]]
    rendered: dict[str, str]
    manifest: dict[str, Any]
    preconditions: dict[str, str | None]


@dataclass
class _Edge:
    target: int
    reverse: int
    capacity: int
    initial: int


class _Flow:
    def __init__(self, size: int) -> None:
        self.graph: list[list[_Edge]] = [[] for _ in range(size)]

    def add(self, source: int, target: int, capacity: int) -> _Edge:
        forward = _Edge(target, len(self.graph[target]), capacity, capacity)
        backward = _Edge(source, len(self.graph[source]), 0, 0)
        self.graph[source].append(forward)
        self.graph[target].append(backward)
        return forward

    def maximum(self, source: int, sink: int) -> int:
        total = 0
        while True:
            level = [-1] * len(self.graph)
            level[source] = 0
            queue = [source]
            for node in queue:
                for edge in self.graph[node]:
                    if edge.capacity and level[edge.target] < 0:
                        level[edge.target] = level[node] + 1
                        queue.append(edge.target)
            if level[sink] < 0:
                return total
            cursor = [0] * len(self.graph)

            def send(node: int, available: int) -> int:
                if node == sink:
                    return available
                while cursor[node] < len(self.graph[node]):
                    edge = self.graph[node][cursor[node]]
                    if edge.capacity and level[edge.target] == level[node] + 1:
                        amount = send(edge.target, min(available, edge.capacity))
                        if amount:
                            edge.capacity -= amount
                            self.graph[edge.target][edge.reverse].capacity += amount
                            return amount
                    cursor[node] += 1
                return 0

            while True:
                amount = send(source, 1 << 60)
                if not amount:
                    break
                total += amount


def stable_digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def _strict_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise ValueError(f"{context} missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{context} has unknown field(s): {', '.join(sorted(unknown))}")


def _strict_keys_with_optional(
    value: dict[str, Any], required: set[str], optional: set[str], context: str
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise ValueError(f"{context} missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{context} has unknown field(s): {', '.join(sorted(unknown))}")


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        raise ValueError(f"{context} must be a lowercase snake_case identifier")
    return value


def _identifiers(value: Any, context: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        suffix = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{context} must be {suffix} of identifiers")
    result = tuple(_identifier(item, f"{context} entry") for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{context} contains duplicate identifiers")
    return result


def _safe_output_file(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a YAML filename")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or ".." in path.parts
        or path.suffix != ".yaml"
        or not KEY_RE.fullmatch(path.stem)
        or path.name in RESERVED_OUTPUTS
    ):
        raise ValueError(f"{context} is not a safe schema-v1 catalog filename")
    return path.name


def _safe_runtime_file(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a relative YAML path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 3
        or path.parts[0] != "krea2"
        or path.suffix != ".yaml"
        or any(not KEY_RE.fullmatch(part) for part in (*path.parts[:-1], path.stem))
    ):
        raise ValueError(f"{context} must be a safe krea2 runtime YAML path")
    return path.as_posix()


def _validate_fragment(text: Any, context: str) -> str:
    if not isinstance(text, str) or not text.strip() or text != text.strip():
        raise ValueError(f"{context} must be trimmed, non-empty natural-language text")
    compact = re.sub(r"\s+", " ", text)
    if "_" in compact or any(token in compact for token in ("{", "}", "|")):
        raise ValueError(f"{context} contains wildcard or tag syntax")
    if len(re.findall(r"[A-Za-z]+", compact)) < 3:
        raise ValueError(f"{context} is too short to be natural-language prose")
    for label, pattern in PROHIBITED_PROSE:
        if pattern.search(compact):
            raise ValueError(f"{context} contains {label}")
    return compact


def _template_fields(text: str, context: str) -> tuple[str, ...]:
    try:
        parsed = tuple(string.Formatter().parse(text))
    except ValueError as exc:
        raise ValueError(f"{context} has invalid placeholder syntax") from exc
    fields = []
    for _, field, format_spec, conversion in parsed:
        if field is None:
            continue
        if not KEY_RE.fullmatch(field) or format_spec or conversion:
            raise ValueError(f"{context} contains an unsafe placeholder")
        fields.append(field)
    return tuple(fields)


def _validate_prompt(text: str, context: str, *, check_repetition: bool = True) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    if not compact or len(compact) > 600:
        raise ValueError(f"{context} must contain 1 to 600 characters")
    if compact.endswith(","):
        raise ValueError(f"{context} has a trailing comma")
    if "_" in compact or any(token in compact for token in ("{", "}", "|")):
        raise ValueError(f"{context} contains unresolved wildcard or tag syntax")
    for label, pattern in PROHIBITED_PROSE:
        if pattern.search(compact):
            raise ValueError(f"{context} contains {label}")
    if check_repetition:
        repetition = repetition_issue(compact)
        if repetition:
            raise ValueError(f"{context} {repetition}")
    return compact


def _parse_dimension(raw: Any, context: str) -> DimensionSpec:
    value = _mapping(raw, context)
    _strict_keys(value, {"id", "values"}, context)
    dimension_id = _identifier(value["id"], f"{context}.id")
    raw_values = value["values"]
    if not isinstance(raw_values, list) or not raw_values:
        raise ValueError(f"{context}.values must be a non-empty list")
    values: list[ValueSpec] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    for index, raw_value in enumerate(raw_values):
        value_context = f"{context}.values[{index}]"
        item = _mapping(raw_value, value_context)
        _strict_keys(item, {"id", "text"}, value_context)
        value_id = _identifier(item["id"], f"{value_context}.id")
        text = _validate_fragment(item["text"], f"{value_context}.text")
        normalized = normalized_phrase(text)
        if value_id in seen_ids:
            raise ValueError(f"{context} contains duplicate value ID {value_id!r}")
        if normalized in seen_text:
            raise ValueError(f"{context} contains duplicate normalized value text")
        seen_ids.add(value_id)
        seen_text.add(normalized)
        values.append(ValueSpec(value_id, text))
    return DimensionSpec(dimension_id, tuple(values))


def _parse_template(raw: Any, dimension_ids: tuple[str, ...], context: str) -> TemplateSpec:
    value = _mapping(raw, context)
    _strict_keys(value, {"id", "text"}, context)
    template_id = _identifier(value["id"], f"{context}.id")
    text = value["text"]
    if not isinstance(text, str) or not text.strip() or text != text.strip():
        raise ValueError(f"{context}.text must be trimmed, non-empty prose")
    fields = _template_fields(text, f"{context}.text")
    unknown = set(fields) - set(dimension_ids)
    missing = set(dimension_ids) - set(fields)
    repeated = sorted(field for field, count in Counter(fields).items() if count != 1)
    if unknown:
        raise ValueError(f"{context}.text has unknown placeholder(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"{context}.text is missing placeholder(s): {', '.join(sorted(missing))}")
    if repeated:
        raise ValueError(f"{context}.text must use each placeholder exactly once")
    probe = text.format_map({dimension_id: "natural visual detail" for dimension_id in dimension_ids})
    _validate_prompt(probe, f"{context}.text", check_repetition=False)
    return TemplateSpec(template_id, text)


def _parse_retry(
    raw: Any,
    dimensions: tuple[DimensionSpec, ...],
    context: str,
) -> RetrySpec:
    value = _mapping(raw, context)
    _strict_keys(value, {"template", "dimensions"}, context)
    dimension_ids = tuple(dimension.id for dimension in dimensions)
    template = value["template"]
    if not isinstance(template, str) or not template.strip() or template != template.strip():
        raise ValueError(f"{context}.template must be trimmed, non-empty prose")
    fields = _template_fields(template, f"{context}.template")
    unknown = set(fields) - set(dimension_ids)
    missing = set(dimension_ids) - set(fields)
    repeated = sorted(field for field, count in Counter(fields).items() if count != 1)
    if unknown:
        raise ValueError(
            f"{context}.template has unknown placeholder(s): {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ValueError(
            f"{context}.template is missing placeholder(s): {', '.join(sorted(missing))}"
        )
    if repeated:
        raise ValueError(f"{context}.template must use each placeholder exactly once")

    raw_dimensions = _mapping(value["dimensions"], f"{context}.dimensions")
    if set(raw_dimensions) != set(dimension_ids):
        raise ValueError(f"{context}.dimensions must exactly match collection dimensions")
    retry_dimensions: list[DimensionSpec] = []
    for dimension in dimensions:
        raw_values = _mapping(
            raw_dimensions[dimension.id], f"{context}.dimensions.{dimension.id}"
        )
        expected_ids = {item.id for item in dimension.values}
        if set(raw_values) != expected_ids:
            raise ValueError(
                f"{context}.dimensions.{dimension.id} must exactly match collection values"
            )
        retry_dimensions.append(
            DimensionSpec(
                dimension.id,
                tuple(
                    ValueSpec(
                        item.id,
                        _validate_fragment(
                            raw_values[item.id],
                            f"{context}.dimensions.{dimension.id}.{item.id}",
                        ),
                    )
                    for item in dimension.values
                ),
            )
        )
    probe = template.format_map(
        {dimension_id: "observable physical detail" for dimension_id in dimension_ids}
    )
    _validate_prompt(probe, f"{context}.template", check_repetition=False)
    return RetrySpec(template, tuple(retry_dimensions))


def parse_collection(raw: Any, context: str, source_ids: set[str]) -> CollectionSpec:
    value = _mapping(raw, context)
    _strict_keys_with_optional(
        value,
        {
            "id",
            "kind",
            "output_file",
            "family",
            "runtime",
            "source_refs",
            "target_count",
            "dimensions",
            "templates",
            "compatibility",
        },
        {"prompt_overrides", "retry"},
        context,
    )
    collection_id = _identifier(value["id"], f"{context}.id")
    kind = _identifier(value["kind"], f"{context}.kind")
    output_file = _safe_output_file(value["output_file"], f"{context}.output_file")
    family = _identifier(value["family"], f"{context}.family")

    runtime = _mapping(value["runtime"], f"{context}.runtime")
    _strict_keys(runtime, {"file", "path_prefix"}, f"{context}.runtime")
    runtime_file = _safe_runtime_file(runtime["file"], f"{context}.runtime.file")
    runtime_path = _identifiers(runtime["path_prefix"], f"{context}.runtime.path_prefix")
    if len(runtime_path) < 3 or runtime_path[0] != "krea2":
        raise ValueError(f"{context}.runtime.path_prefix must start with a three-part krea2 path")
    expected_path = PurePosixPath(runtime_file).with_suffix("").parts
    if runtime_path != expected_path:
        raise ValueError(f"{context}.runtime file and path_prefix must describe the same path")

    source_refs = _identifiers(value["source_refs"], f"{context}.source_refs")
    missing_sources = set(source_refs) - source_ids
    if missing_sources:
        raise ValueError(f"{context} has unknown source_refs: {', '.join(sorted(missing_sources))}")
    target_count = value["target_count"]
    if isinstance(target_count, bool) or not isinstance(target_count, int) or target_count < 1:
        raise ValueError(f"{context}.target_count must be a positive integer")

    raw_dimensions = value["dimensions"]
    if not isinstance(raw_dimensions, list) or not raw_dimensions:
        raise ValueError(f"{context}.dimensions must be a non-empty list")
    dimensions = tuple(
        _parse_dimension(item, f"{context}.dimensions[{index}]")
        for index, item in enumerate(raw_dimensions)
    )
    dimension_ids = tuple(dimension.id for dimension in dimensions)
    if len(set(dimension_ids)) != len(dimension_ids):
        raise ValueError(f"{context} contains duplicate dimension IDs")

    raw_templates = value["templates"]
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ValueError(f"{context}.templates must be a non-empty list")
    templates = tuple(
        _parse_template(item, dimension_ids, f"{context}.templates[{index}]")
        for index, item in enumerate(raw_templates)
    )
    template_ids = [template.id for template in templates]
    if len(set(template_ids)) != len(template_ids):
        raise ValueError(f"{context} contains duplicate template IDs")

    raw_overrides = value.get("prompt_overrides", {})
    if not isinstance(raw_overrides, dict):
        raise ValueError(f"{context}.prompt_overrides must be a mapping")
    prompt_overrides: list[tuple[str, str]] = []
    for raw_item_id, raw_text in raw_overrides.items():
        item_id = _identifier(raw_item_id, f"{context}.prompt_overrides key")
        if len(item_id) > MAX_ITEM_ID_LENGTH:
            raise ValueError(f"{context}.prompt_overrides key is overlong: {item_id!r}")
        text = _validate_fragment(raw_text, f"{context}.prompt_overrides.{item_id}")
        prompt_overrides.append((item_id, text))

    retry = (
        _parse_retry(value["retry"], dimensions, f"{context}.retry")
        if "retry" in value
        else None
    )

    compatibility = _mapping(value["compatibility"], f"{context}.compatibility")
    _strict_keys(compatibility, {"avoid"}, f"{context}.compatibility")
    avoids = _identifiers(
        compatibility["avoid"], f"{context}.compatibility.avoid", allow_empty=True
    )

    collection = CollectionSpec(
        id=collection_id,
        kind=kind,
        output_file=output_file,
        family=family,
        runtime_file=runtime_file,
        runtime_path_prefix=runtime_path,
        source_refs=source_refs,
        target_count=target_count,
        dimensions=dimensions,
        templates=templates,
        prompt_overrides=tuple(sorted(prompt_overrides)),
        retry=retry,
        compatibility_avoid=avoids,
    )
    if collection.product_size < target_count:
        raise ValueError(
            f"{context} Cartesian product is too small: "
            f"{collection.product_size} < {target_count}"
        )
    return collection


def load_collections(blueprint_root: Path, sources_path: Path) -> tuple[list[CollectionSpec], list[dict[str, str]]]:
    sources_document = _mapping(load_yaml(sources_path), str(sources_path))
    sources = sources_document.get("sources")
    if not isinstance(sources, dict):
        raise ValueError(f"{sources_path}: sources must be a mapping")
    source_ids = set(sources)

    root = blueprint_root.resolve()
    if not root.is_dir():
        raise ValueError(f"blueprint directory not found: {blueprint_root}")
    paths = sorted(blueprint_root.rglob("*.yaml"))
    if not paths:
        raise ValueError(f"no YAML blueprints found under {blueprint_root}")

    collections: list[CollectionSpec] = []
    blueprints: list[dict[str, str]] = []
    seen_collection_ids: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"blueprint path escapes its root: {path}")
        relative = resolved.relative_to(root).as_posix()
        document = _mapping(load_yaml(path), str(path))
        _strict_keys(document, {"schema_version", "collections"}, str(path))
        if document["schema_version"] != 1:
            raise ValueError(f"{path}: schema_version must be 1")
        raw_collections = document["collections"]
        if not isinstance(raw_collections, list) or not raw_collections:
            raise ValueError(f"{path}: collections must be a non-empty list")
        for index, raw_collection in enumerate(raw_collections):
            context = f"{relative}: collections[{index}]"
            collection = parse_collection(raw_collection, context, source_ids)
            if collection.id in seen_collection_ids:
                raise ValueError(f"duplicate collection ID: {collection.id}")
            seen_collection_ids.add(collection.id)
            collections.append(collection)
        blueprints.append({"path": relative, "sha256": file_sha256(path)})
    return collections, blueprints


def balanced_quotas(collection_id: str, axis_id: str, value_ids: tuple[str, ...], total: int) -> dict[str, int]:
    quotient, remainder = divmod(total, len(value_ids))
    ranked = sorted(value_ids, key=lambda value_id: stable_digest(collection_id, axis_id, value_id))
    promoted = set(ranked[:remainder])
    return {value_id: quotient + (value_id in promoted) for value_id in value_ids}


def _initial_pairs(
    collection_id: str,
    left_axis: str,
    left_values: tuple[str, ...],
    right_axis: str,
    right_values: tuple[str, ...],
    left_quotas: dict[str, int],
    right_quotas: dict[str, int],
    total: int,
    remaining_capacity: int,
) -> list[tuple[str, str]]:
    source = 0
    left_offset = 1
    right_offset = left_offset + len(left_values)
    sink = right_offset + len(right_values)
    flow = _Flow(sink + 1)
    for index, value_id in enumerate(left_values):
        flow.add(source, left_offset + index, left_quotas[value_id])
    for index, value_id in enumerate(right_values):
        flow.add(right_offset + index, sink, right_quotas[value_id])

    pair_edges: list[tuple[str, str, _Edge]] = []
    right_index = {value_id: index for index, value_id in enumerate(right_values)}
    for left_index, left_id in enumerate(left_values):
        ranked_right = sorted(
            right_values,
            key=lambda right_id: stable_digest(
                collection_id, left_axis, left_id, right_axis, right_id
            ),
        )
        for right_id in ranked_right:
            edge = flow.add(
                left_offset + left_index,
                right_offset + right_index[right_id],
                remaining_capacity,
            )
            pair_edges.append((left_id, right_id, edge))
    if flow.maximum(source, sink) != total:
        raise ValueError(f"{collection_id}: balanced Cartesian selection is infeasible")
    pairs = [
        (left, right)
        for left, right, edge in pair_edges
        for _ in range(edge.initial - edge.capacity)
    ]
    return sorted(pairs, key=lambda pair: stable_digest(collection_id, *pair))


def _extend_rows(
    collection_id: str,
    rows: list[tuple[str, ...]],
    axis_id: str,
    value_ids: tuple[str, ...],
    quotas: dict[str, int],
    remaining_capacity: int,
) -> list[tuple[str, ...]]:
    grouped_rows = sorted(
        Counter(rows).items(), key=lambda item: stable_digest(collection_id, *item[0])
    )
    source = 0
    row_offset = 1
    value_offset = row_offset + len(grouped_rows)
    sink = value_offset + len(value_ids)
    flow = _Flow(sink + 1)
    for index, (_, count) in enumerate(grouped_rows):
        flow.add(source, row_offset + index, count)
    for index, value_id in enumerate(value_ids):
        flow.add(value_offset + index, sink, quotas[value_id])

    value_index = {value_id: index for index, value_id in enumerate(value_ids)}
    edges: list[tuple[tuple[str, ...], str, _Edge]] = []
    for row_index, (row, _) in enumerate(grouped_rows):
        ranked_values = sorted(
            value_ids,
            key=lambda value_id: stable_digest(collection_id, *row, axis_id, value_id),
        )
        for value_id in ranked_values:
            edge = flow.add(
                row_offset + row_index,
                value_offset + value_index[value_id],
                remaining_capacity,
            )
            edges.append((row, value_id, edge))
    if flow.maximum(source, sink) != len(rows):
        raise ValueError(f"{collection_id}: balanced Cartesian extension is infeasible")
    extended = [
        (*row, value_id)
        for row, value_id, edge in edges
        for _ in range(edge.initial - edge.capacity)
    ]
    if len(extended) != len(rows):
        raise ValueError(f"{collection_id}: incomplete balanced assignment")
    if remaining_capacity == 1 and len(set(extended)) != len(extended):
        raise ValueError(f"{collection_id}: balanced selection produced duplicate combinations")
    return sorted(extended, key=lambda row: stable_digest(collection_id, *row))


def select_combinations(collection: CollectionSpec) -> list[tuple[str, ...]]:
    axes = [
        (dimension.id, tuple(value.id for value in dimension.values))
        for dimension in collection.dimensions
    ]
    axes.append(("template", tuple(template.id for template in collection.templates)))
    quotas = {
        axis_id: balanced_quotas(collection.id, axis_id, values, collection.target_count)
        for axis_id, values in axes
    }
    left_axis, left_values = axes[0]
    right_axis, right_values = axes[1]
    rows: list[tuple[str, ...]] = _initial_pairs(
        collection.id,
        left_axis,
        left_values,
        right_axis,
        right_values,
        quotas[left_axis],
        quotas[right_axis],
        collection.target_count,
        math.prod(len(values) for _, values in axes[2:]),
    )
    for axis_index, (axis_id, values) in enumerate(axes[2:], start=2):
        rows = _extend_rows(
            collection.id,
            rows,
            axis_id,
            values,
            quotas[axis_id],
            math.prod(len(later_values) for _, later_values in axes[axis_index + 1 :]),
        )
    if len(rows) != collection.target_count or len(set(rows)) != len(rows):
        raise ValueError(f"{collection.id}: selection did not produce the exact unique target")
    for axis_index, (axis_id, values) in enumerate(axes):
        counts = Counter(row[axis_index] for row in rows)
        if set(counts) - set(values) or max(counts.get(value, 0) for value in values) - min(
            counts.get(value, 0) for value in values
        ) > 1:
            raise ValueError(f"{collection.id}: {axis_id} selection is not balanced")
    return rows


def compile_collection(collection: CollectionSpec) -> dict[str, dict[str, Any]]:
    dimension_values = {
        dimension.id: {value.id: value for value in dimension.values}
        for dimension in collection.dimensions
    }
    templates = {template.id: template for template in collection.templates}
    retry_dimension_values = (
        {
            dimension.id: {value.id: value for value in dimension.values}
            for dimension in collection.retry.dimensions
        }
        if collection.retry is not None
        else None
    )
    prompt_overrides = dict(collection.prompt_overrides)
    items: dict[str, dict[str, Any]] = {}
    prompt_origins: dict[str, str] = {}
    for row in select_combinations(collection):
        dimension_ids = row[:-1]
        template_id = row[-1]
        item_id = "_".join((collection.id, *dimension_ids, template_id))
        if not KEY_RE.fullmatch(item_id) or len(item_id) > MAX_ITEM_ID_LENGTH:
            raise ValueError(
                f"collection {collection.id} produced an invalid or overlong item ID: {item_id!r}"
            )
        selected = {
            dimension.id: dimension_values[dimension.id][value_id]
            for dimension, value_id in zip(collection.dimensions, dimension_ids, strict=True)
        }
        base_prompt = templates[template_id].text.format_map(
            {dimension_id: value.text for dimension_id, value in selected.items()}
        )
        override = prompt_overrides.get(item_id)
        prompt = _validate_prompt(
            f"{base_prompt} {override}" if override else base_prompt,
            f"collection {collection.id}, item {item_id}, template {template_id}",
        )
        retry_prompt = None
        if collection.retry is not None and retry_dimension_values is not None:
            retry_prompt = _validate_prompt(
                collection.retry.template.format_map(
                    {
                        dimension.id: retry_dimension_values[dimension.id][value_id].text
                        for dimension, value_id in zip(
                            collection.dimensions, dimension_ids, strict=True
                        )
                    }
                ),
                f"collection {collection.id}, item {item_id}, retry",
            )
        if item_id in items:
            raise ValueError(f"collection {collection.id} produced duplicate item ID {item_id!r}")
        normalized = normalized_phrase(prompt)
        if normalized in prompt_origins:
            raise ValueError(
                f"collection {collection.id} produced duplicate normalized prompts: "
                f"{prompt_origins[normalized]} and {item_id}"
            )
        prompt_origins[normalized] = item_id
        feature_axes = {
            dimension.id: [value_id]
            for dimension, value_id in zip(collection.dimensions, dimension_ids, strict=True)
        }
        items[item_id] = {
            "family": collection.family,
            "visual_axes": [
                f"{dimension.id}_{value_id}"
                for dimension, value_id in zip(collection.dimensions, dimension_ids, strict=True)
            ],
            "feature_axes": feature_axes,
            "prompt": prompt,
            "compatibility": {"avoid": list(collection.compatibility_avoid)},
            "source_refs": list(collection.source_refs),
            "runtime": {
                "file": collection.runtime_file,
                "path": [*collection.runtime_path_prefix, item_id],
            },
            "validation": {
                "model": "krea2_turbo",
                "tested_seeds": 0,
                "status": "generated",
            },
            "generation": {
                "collection_id": collection.id,
                "kind": collection.kind,
                "template_id": template_id,
            },
            **({"_retry_prompt": retry_prompt} if retry_prompt is not None else {}),
        }
    unknown_overrides = set(prompt_overrides) - set(items)
    if unknown_overrides:
        raise ValueError(
            f"collection {collection.id} has prompt override(s) for unselected item(s): "
            + ", ".join(sorted(unknown_overrides)[:5])
        )
    return dict(sorted(items.items()))


def render_yaml(document: dict[str, Any]) -> str:
    return yaml.dump(
        document,
        Dumper=FoldedStringDumper,
        allow_unicode=True,
        sort_keys=False,
        width=100,
        default_flow_style=False,
    )


def _load_previous_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing generation manifest is unreadable: {path}") from exc
    if not isinstance(document, dict) or document.get("generator") != GENERATOR_ID:
        raise ValueError(f"refusing to replace unrelated manifest: {path}")
    outputs = document.get("outputs")
    if not isinstance(outputs, list):
        raise ValueError(f"existing generation manifest has invalid outputs: {path}")
    return document


def _previous_outputs(manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if manifest is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw in manifest["outputs"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("output_file"), str):
            raise ValueError("existing generation manifest has an invalid output record")
        output_file = raw["output_file"]
        if output_file in result:
            raise ValueError("existing generation manifest has duplicate output records")
        result[output_file] = raw
    return result


def _verify_previous_outputs(
    output_root: Path, previous: dict[str, dict[str, Any]], current_outputs: set[str]
) -> None:
    orphaned = set(previous) - current_outputs
    if orphaned:
        raise ValueError(
            "blueprints omit previously managed output(s): " + ", ".join(sorted(orphaned))
        )
    for output_file, record in previous.items():
        path = output_root / output_file
        expected = record.get("sha256")
        if not path.is_file() or not isinstance(expected, str) or file_sha256(path) != expected:
            raise ValueError(f"managed output changed outside the generator: {output_file}")


def _base_catalog(
    path: Path,
    output_file: str,
    previous_record: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if path.is_file():
        document = _mapping(load_yaml(path), str(path))
        if document.get("schema_version") != 1 or document.get("catalog") != Path(output_file).stem:
            raise ValueError(f"refusing to replace unrelated catalog file: {output_file}")
        raw_items = document.get("items")
        if not isinstance(raw_items, dict):
            raise ValueError(f"{output_file}: items must be a mapping")
        items = dict(raw_items)
    else:
        document = {"schema_version": 1, "catalog": Path(output_file).stem, "items": {}}
        items = {}

    owned_items: dict[str, dict[str, Any]] = {}
    if previous_record is not None:
        generated_ids = previous_record.get("generated_item_ids")
        if not isinstance(generated_ids, list) or not all(isinstance(item, str) for item in generated_ids):
            raise ValueError(f"previous manifest lacks generated item ownership for {output_file}")
        owned = set(generated_ids)
        if not owned <= set(items):
            raise ValueError(f"managed items are missing from {output_file}")
        for item_id in owned:
            item = items[item_id]
            if not isinstance(item, dict):
                raise ValueError(f"managed item is not a mapping in {output_file}: {item_id}")
            owned_items[item_id] = item
            del items[item_id]
    output = dict(document)
    output["items"] = items
    return output, owned_items


def _body_without_validation(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "validation"}


def _preserve_evaluated_validation(
    output_file: str,
    generated_items: dict[str, dict[str, Any]],
    previous_items: dict[str, dict[str, Any]],
) -> None:
    for item_id, item in generated_items.items():
        previous = previous_items.get(item_id)
        retry_prompt = item.pop("_retry_prompt", None)
        if previous is None:
            continue
        previous_validation = previous.get("validation")
        if not isinstance(previous_validation, dict):
            raise ValueError(f"managed item lacks validation in {output_file}: {item_id}")
        if previous_validation.get("status") == "rejected" and isinstance(retry_prompt, str):
            item["prompt"] = retry_prompt
        if _body_without_validation(item) == _body_without_validation(previous):
            item["validation"] = dict(previous_validation)
            continue
        status = previous_validation.get("status")
        if status not in {"generated", "rejected"}:
            raise ValueError(
                f"refusing to rewrite managed {status!r} item in {output_file}: {item_id}"
            )


def _display_path(path: Path, fallback: str) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return PurePosixPath(fallback).as_posix()


def compile_expansion(
    blueprint_root: Path,
    output_root: Path,
    sources_path: Path,
    manifest_path: Path,
) -> Compilation:
    collections, blueprint_records = load_collections(blueprint_root, sources_path)
    grouped: dict[str, list[CollectionSpec]] = {}
    for collection in collections:
        grouped.setdefault(collection.output_file, []).append(collection)

    previous_manifest = _load_previous_manifest(manifest_path)
    previous = _previous_outputs(previous_manifest)
    _verify_previous_outputs(output_root, previous, set(grouped))

    documents: dict[str, dict[str, Any]] = {}
    rendered: dict[str, str] = {}
    generated_by_output: dict[str, list[str]] = {}
    all_new_prompts: dict[str, str] = {}
    preconditions: dict[str, str | None] = {}

    for output_file in sorted(grouped):
        output_path = output_root / output_file
        preconditions[output_file] = file_sha256(output_path) if output_path.is_file() else None
        document, previous_items = _base_catalog(
            output_path, output_file, previous.get(output_file)
        )
        items = document["items"]
        generated_ids: list[str] = []
        for collection in sorted(grouped[output_file], key=lambda item: item.id):
            generated_items = compile_collection(collection)
            _preserve_evaluated_validation(output_file, generated_items, previous_items)
            collisions = set(items) & set(generated_items)
            if collisions:
                raise ValueError(
                    f"{output_file}: generated item ID collides with existing item: "
                    + ", ".join(sorted(collisions)[:5])
                )
            for item_id, item in generated_items.items():
                prompt = item["prompt"]
                normalized = normalized_phrase(prompt)
                if normalized in all_new_prompts:
                    raise ValueError(
                        f"duplicate normalized generated prompt: {all_new_prompts[normalized]} and {item_id}"
                    )
                all_new_prompts[normalized] = item_id
            items.update(generated_items)
            generated_ids.extend(generated_items)
        document["items"] = dict(sorted(items.items()))
        documents[output_file] = document
        rendered[output_file] = render_yaml(document)
        generated_by_output[output_file] = sorted(generated_ids)

    # Reject prompt collisions with unrelated catalog items, including other existing files.
    generated_id_sets = {name: set(ids) for name, ids in generated_by_output.items()}
    existing_prompts: dict[str, str] = {}
    for path in sorted(output_root.glob("*.yaml")):
        try:
            document = load_yaml(path)
        except (OSError, yaml.YAMLError, ValueError):
            continue
        items = document.get("items") if isinstance(document, dict) else None
        if not isinstance(items, dict):
            continue
        owned = set(previous.get(path.name, {}).get("generated_item_ids", []))
        for item_id, item in items.items():
            if item_id in owned or item_id in generated_id_sets.get(path.name, set()):
                continue
            if not isinstance(item, dict):
                continue
            prompts = item.get("prompts") if isinstance(item.get("prompts"), list) else [item.get("prompt")]
            for prompt in prompts:
                if isinstance(prompt, str) and prompt.strip():
                    existing_prompts.setdefault(normalized_phrase(prompt), f"{path.name}:{item_id}")
    for normalized, item_id in all_new_prompts.items():
        if normalized in existing_prompts:
            raise ValueError(
                f"generated prompt {item_id} duplicates existing {existing_prompts[normalized]}"
            )

    blueprint_digest_payload = json.dumps(
        blueprint_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    blueprint_digest = hashlib.sha256(blueprint_digest_payload.encode("utf-8")).hexdigest()
    output_records = []
    collection_records = []
    for output_file in sorted(documents):
        digest = text_sha256(rendered[output_file])
        output_collections = sorted(grouped[output_file], key=lambda item: item.id)
        output_records.append(
            {
                "path": _display_path(output_root / output_file, output_file),
                "output_file": output_file,
                "sha256": digest,
                "item_count": len(documents[output_file]["items"]),
                "generated_item_count": len(generated_by_output[output_file]),
                "generated_item_ids": generated_by_output[output_file],
                "collection_ids": [collection.id for collection in output_collections],
            }
        )
        for collection in output_collections:
            collection_records.append(
                {
                    "id": collection.id,
                    "kind": collection.kind,
                    "output_file": output_file,
                    "item_count": collection.target_count,
                    "product_size": collection.product_size,
                    "output_sha256": digest,
                }
            )
    manifest = {
        "schema_version": 1,
        "generator": GENERATOR_ID,
        "blueprints": blueprint_records,
        "blueprint_digest": blueprint_digest,
        "total_item_count": sum(collection.target_count for collection in collections),
        "outputs": output_records,
        "collections": sorted(collection_records, key=lambda item: item["id"]),
    }
    return Compilation(documents, rendered, manifest, preconditions)


def _stage_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def apply_compilation(
    compilation: Compilation,
    output_root: Path,
    manifest_path: Path,
) -> None:
    for output_file, expected in compilation.preconditions.items():
        path = output_root / output_file
        actual = file_sha256(path) if path.is_file() else None
        if actual != expected:
            raise ValueError(f"catalog output changed during compilation: {output_file}")

    staged: list[tuple[Path, Path]] = []
    try:
        for output_file in sorted(compilation.rendered):
            destination = output_root / output_file
            staged.append((destination, _stage_text(destination, compilation.rendered[output_file])))
        manifest_text = json.dumps(
            compilation.manifest, ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        staged_manifest = _stage_text(manifest_path, manifest_text)
        for destination, temporary in staged:
            os.replace(temporary, destination)
        os.replace(staged_manifest, manifest_path)
    finally:
        for _, temporary in staged:
            if temporary.exists():
                temporary.unlink()
        if "staged_manifest" in locals() and staged_manifest.exists():
            staged_manifest.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile deterministic catalog expansion blueprints; dry-run by default"
    )
    parser.add_argument("blueprints", nargs="?", type=Path, default=DEFAULT_BLUEPRINTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply", action="store_true", help="atomically write catalog outputs and manifest")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete planned manifest during a dry-run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        compilation = compile_expansion(
            args.blueprints,
            args.output,
            args.sources,
            args.manifest,
        )
        if args.apply:
            apply_compilation(compilation, args.output, args.manifest)
            print(
                f"Applied {compilation.manifest['total_item_count']} generated item(s) "
                f"across {len(compilation.manifest['outputs'])} catalog file(s)."
            )
        else:
            if args.json:
                print(json.dumps(compilation.manifest, ensure_ascii=False, indent=2, sort_keys=True))
            print(
                f"DRY RUN: {compilation.manifest['total_item_count']} generated item(s), "
                f"{len(compilation.manifest['outputs'])} catalog file(s)."
            )
            print("Re-run with --apply to write catalog files.")
        return 0
    except (OSError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
