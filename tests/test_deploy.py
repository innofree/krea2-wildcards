from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from build_impact_yaml import impact_compatible_document
from common import iter_leaf_lists, item_status, iter_catalog_items, load_yaml
from deploy_remote_wildcards import krea2_namespace, rsync_command


ROOT = Path(__file__).resolve().parents[1]


def test_preview_has_expected_remote_paths(tmp_path: Path) -> None:
    from build_runtime_yaml import compile_catalog

    output = tmp_path / "wildcards"
    compile_catalog(ROOT / "catalog", output, {"generated", "testing", "approved"})
    document = impact_compatible_document(output)
    paths = {f"__krea2/{path}__" for path in document["krea2"]}
    active = sum(
        item_status(item) in {"generated", "testing", "approved"}
        for _, _, item in iter_catalog_items(ROOT / "catalog")
    )
    aggregate_count = sum(
        1
        for path in output.rglob("*.yaml")
        for parts, _ in iter_leaf_lists(load_yaml(path))
        if parts[-1] == "all"
    )
    assert len(paths) == active + aggregate_count
    assert "__krea2/style/complete_pack/all__" in paths
    assert "__krea2/style/complete_pack/crystal_iris_pastel__" in paths


def test_impact_adapter_flattens_to_two_yaml_levels(tmp_path: Path) -> None:
    from build_runtime_yaml import compile_catalog

    output = tmp_path / "wildcards"
    compile_catalog(ROOT / "catalog", output, {"generated", "testing", "approved"})
    document = impact_compatible_document(output)
    active = sum(
        item_status(item) in {"generated", "testing", "approved"}
        for _, _, item in iter_catalog_items(ROOT / "catalog")
    )

    assert list(document) == ["krea2"]
    aggregate_count = sum(
        1
        for path in output.rglob("*.yaml")
        for parts, _ in iter_leaf_lists(load_yaml(path))
        if parts[-1] == "all"
    )
    assert len(document["krea2"]) == active + aggregate_count
    assert "style/complete_pack/all" in document["krea2"]
    assert "style" not in document["krea2"]


def test_impact_adapter_bundles_runtime_tree_and_rejects_path_collisions(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "nested/second.yaml"
    second.parent.mkdir()
    first.write_text("krea2:\n  style:\n    medium:\n      ink: [fluid ink detail]\n", encoding="utf-8")
    second.write_text(
        "krea2:\n  camera:\n    framing:\n      portrait: [balanced portrait framing]\n",
        encoding="utf-8",
    )
    document = impact_compatible_document(tmp_path)
    assert set(document["krea2"]) == {"style/medium/ink", "camera/framing/portrait"}

    second.write_text(
        "krea2:\n  style:\n    medium:\n      ink: [a second ink detail]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate Impact runtime path"):
        impact_compatible_document(tmp_path)


def test_production_impact_contains_only_approved_paths(tmp_path: Path) -> None:
    from build_runtime_yaml import compile_catalog

    output = tmp_path / "wildcards"
    compile_catalog(ROOT / "catalog", output, {"approved"})
    document = impact_compatible_document(output)
    approved_count = sum(
        item_status(item) == "approved"
        for _, _, item in iter_catalog_items(ROOT / "catalog")
    )

    aggregate_count = sum(
        1
        for path in output.rglob("*.yaml")
        for parts, _ in iter_leaf_lists(load_yaml(path))
        if parts[-1] == "all"
    )
    assert len(document["krea2"]) == approved_count + aggregate_count
    assert "style/complete_pack/all" in document["krea2"]
    assert "style/complete_pack/crystal_iris_pastel" in document["krea2"]
    assert "style/complete_pack/petal_airlight" not in document["krea2"]


def test_rsync_is_dry_run_by_default_and_never_deletes() -> None:
    command = rsync_command(
        Path("preview.yaml"),
        "operator@example.invalid",
        PurePosixPath("/srv/wildcards/krea2.yaml"),
        apply=False,
    )
    assert "--dry-run" in command
    assert "--delete" not in command
    assert "--backup" not in command


def test_apply_rsync_keeps_recoverable_backup() -> None:
    command = rsync_command(
        Path("preview.yaml"),
        "operator@example.invalid",
        PurePosixPath("/srv/wildcards/krea2.yaml"),
        apply=True,
        backup_suffix=".bak.20260726T000000Z",
    )
    assert "--dry-run" not in command
    assert "--delete" not in command
    assert "--backup" in command
    assert "--suffix=.bak.20260726T000000Z" in command


def test_namespace_filter_excludes_unrelated_wildcards() -> None:
    available = {
        "__krea2/style/complete_pack/all__",
        "__krea2/style/complete_pack/sumi_mist__",
        "__other/collection/item__",
    }
    assert krea2_namespace(available) == {
        "__krea2/style/complete_pack/all__",
        "__krea2/style/complete_pack/sumi_mist__",
    }
