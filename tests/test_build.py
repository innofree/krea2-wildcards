from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from build_runtime_yaml import compile_catalog
from common import item_status, iter_catalog_items, iter_leaf_lists, load_yaml
from lint_wildcards import lint_file


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"


def test_preview_build_contains_active_leaf_prompts_and_aggregate(tmp_path: Path) -> None:
    active_statuses = {"generated", "testing", "approved"}
    expected_count = sum(
        item_status(item) in active_statuses for _, _, item in iter_catalog_items(CATALOG)
    )
    output = tmp_path / "wildcards"
    manifest = compile_catalog(CATALOG, output, active_statuses)
    runtime_paths = sorted(output.rglob("*.yaml"))
    leaves = {
        f"{runtime_path.relative_to(output)}:{'/'.join(path)}": values
        for runtime_path in runtime_paths
        for path, values in iter_leaf_lists(load_yaml(runtime_path))
    }

    assert manifest["item_count"] == expected_count
    assert manifest["prompt_count"] == expected_count
    item_leaves = [path for path in leaves if not path.endswith("/all")]
    assert len(item_leaves) == expected_count
    assert all(len(leaves[path]) == 1 for path in item_leaves)
    assert all(lint_file(path, max_length=600) == [] for path in runtime_paths)


def test_production_build_contains_only_approved_prompts(tmp_path: Path) -> None:
    approved_count = sum(
        item_status(item) == "approved" for _, _, item in iter_catalog_items(CATALOG)
    )
    output = tmp_path / "wildcards"
    manifest = compile_catalog(CATALOG, output, {"approved"})
    leaves = {
        f"{runtime_path.relative_to(output)}:{'/'.join(path)}": values
        for runtime_path in output.rglob("*.yaml")
        for path, values in iter_leaf_lists(load_yaml(runtime_path))
    }

    assert manifest["item_count"] == approved_count
    assert manifest["prompt_count"] == approved_count
    assert len([path for path in leaves if not path.endswith("/all")]) == approved_count


def test_preview_runtime_uses_folded_scalars(tmp_path: Path) -> None:
    output = tmp_path / "wildcards"
    compile_catalog(CATALOG, output, {"generated", "testing", "approved"})
    raw = (output / "krea2/style/complete_pack.yaml").read_text(encoding="utf-8")
    assert ">-" in raw


def test_runtime_rebuild_removes_stale_generated_files(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    item = {
        "family": "test_family",
        "visual_axes": ["test_axis"],
        "prompt": "a precise visual treatment with controlled clean detail",
        "compatibility": {"avoid": []},
        "source_refs": ["test_source"],
        "runtime": {
            "file": "krea2/style/old.yaml",
            "path": ["krea2", "style", "old", "test_item"],
        },
        "validation": {"status": "approved"},
    }
    path = catalog / "items.yaml"
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "catalog": "items", "items": {"test_item": item}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "runtime"
    compile_catalog(catalog, output, {"approved"})
    assert (output / "krea2/style/old.yaml").is_file()

    item["runtime"] = {
        "file": "krea2/style/new.yaml",
        "path": ["krea2", "style", "new", "test_item"],
    }
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "catalog": "items", "items": {"test_item": item}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    compile_catalog(catalog, output, {"approved"})
    assert not (output / "krea2/style/old.yaml").exists()
    assert (output / "krea2/style/new.yaml").is_file()


@pytest.mark.parametrize(
    ("runtime_file", "runtime_path"),
    [
        ("../escaped.yaml", ["krea2", "style", "test_item"]),
        ("krea2/style/valid.yaml", ["krea2", "style/escaped", "test_item"]),
        ("krea2/style/valid.yaml", ["krea2", "style", "all"]),
        ("krea2/style/valid.yaml", ["other", "style", "test_item"]),
    ],
)
def test_runtime_build_rejects_unsafe_or_ambiguous_public_paths(
    tmp_path: Path, runtime_file: str, runtime_path: list[str]
) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    item_id = runtime_path[-1]
    path = catalog / "items.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "catalog": "items",
                "items": {
                    item_id: {
                        "prompt": "A complete safe prompt.",
                        "runtime": {"file": runtime_file, "path": runtime_path},
                        "validation": {"status": "approved"},
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid runtime"):
        compile_catalog(catalog, tmp_path / "runtime", {"approved"})


def test_runtime_build_rejects_one_aggregate_path_split_across_files(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    path = catalog / "items.yaml"
    items = {
        item_id: {
            "prompt": f"A complete safe prompt for {item_id}.",
            "runtime": {
                "file": runtime_file,
                "path": ["krea2", "style", "shared", item_id],
            },
            "validation": {"status": "approved"},
        }
        for item_id, runtime_file in (
            ("first_item", "krea2/style/first.yaml"),
            ("second_item", "krea2/style/second.yaml"),
        )
    }
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "catalog": "items", "items": items},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="split across multiple files"):
        compile_catalog(catalog, tmp_path / "runtime", {"approved"})
