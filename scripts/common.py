from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml


VALID_STATUSES = {
    "research",
    "normalized",
    "generated",
    "testing",
    "approved",
    "limited",
    "rejected",
    "deprecated",
}
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


class FoldedStringDumper(yaml.SafeDumper):
    """Emit long prompt strings as readable folded scalars."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def _represent_string(dumper: FoldedStringDumper, value: str) -> yaml.ScalarNode:
    style = ">" if len(value) > 100 and " " in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


FoldedStringDumper.add_representer(str, _represent_string)


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.load(handle, Loader=UniqueKeyLoader)


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.dump(
            data,
            handle,
            Dumper=FoldedStringDumper,
            allow_unicode=True,
            sort_keys=False,
            width=100,
            default_flow_style=False,
        )


def canonical_id(value: str) -> str:
    value = value.strip().lower().replace("@", "")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if value and value[0].isdigit():
        value = f"item_{value}"
    return value


def normalized_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower().rstrip(".,;:"))


def canonical_prompt_sha256(value: Any) -> str:
    """Hash the exact parsed catalog prompt body without normalization."""

    if not isinstance(value, str) or not value:
        raise ValueError("canonical prompt must be a non-empty string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def iter_catalog_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.glob("*.yaml")):
        data = load_yaml(path)
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            yield path


def iter_catalog_items(root: Path) -> Iterator[tuple[Path, str, dict[str, Any]]]:
    for path in iter_catalog_files(root):
        data = load_yaml(path)
        for item_id, item in data["items"].items():
            if not isinstance(item, dict):
                raise ValueError(f"{path}: item {item_id!r} must be a mapping")
            yield path, item_id, item


def item_prompts(item: dict[str, Any]) -> list[str]:
    prompts = item.get("prompts")
    if prompts is None and isinstance(item.get("prompt"), str):
        prompts = [item["prompt"]]
    if not isinstance(prompts, list) or not prompts:
        return []
    return [value for value in prompts if isinstance(value, str) and value.strip()]


def item_status(item: dict[str, Any]) -> str | None:
    validation = item.get("validation", {})
    if isinstance(validation, dict):
        return validation.get("status")
    return None


def nested_set_list(root: dict[str, Any], keys: list[str], values: list[str]) -> None:
    cursor = root
    for key in keys[:-1]:
        existing = cursor.setdefault(key, {})
        if not isinstance(existing, dict):
            raise ValueError(f"runtime path collides at {'/'.join(keys)}")
        cursor = existing
    leaf = cursor.setdefault(keys[-1], [])
    if not isinstance(leaf, list):
        raise ValueError(f"runtime path collides at {'/'.join(keys)}")
    leaf.extend(values)


def iter_leaf_lists(
    value: Any, prefix: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], list[Any]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_leaf_lists(child, (*prefix, str(key)))
    elif isinstance(value, list):
        yield prefix, value
    else:
        raise ValueError(f"{'/'.join(prefix) or '<root>'}: expected mapping or list")
