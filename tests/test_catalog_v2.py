from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from validate_catalog_v2 import validate_catalog_v2


ROOT = Path(__file__).resolve().parents[1]
# Mirrors catalog_v2/meta/schema.yaml's evaluation_required_statuses: a
# freshly generated item carries no evaluation_ref until its status
# requires one.
EVALUATION_REQUIRED_STATUSES = {"testing", "approved", "limited", "rejected", "deprecated"}


def _fixture_tree(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "catalog_v2", tmp_path / "catalog_v2")
    shutil.copytree(ROOT / "catalog", tmp_path / "catalog")
    return tmp_path / "catalog_v2"


def _read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)


def _messages(errors: list[str]) -> str:
    return "\n".join(errors)


def _shard_paths(catalog: Path) -> list[Path]:
    return sorted((catalog / "items/style_pack").glob("*.yaml"))


def _items(catalog: Path) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for path in _shard_paths(catalog)
        for item in _read(path)["items"]
    }


def test_catalog_v2_migrates_all_style_packs_losslessly() -> None:
    catalog = ROOT / "catalog_v2"
    assert validate_catalog_v2(catalog) == []

    legacy_items = _read(ROOT / "catalog/art_styles.yaml")["items"]
    items = _items(catalog)
    legacy_v2_items = {
        item_id: item
        for item_id, item in items.items()
        if item["legacy_ref"].startswith("catalog/art_styles.yaml#items/")
    }
    shard_sizes = [
        _read(path)["shard"]["item_count"]
        for path in _shard_paths(catalog)
        if path.name.startswith("style_packs_")
    ]
    assert shard_sizes == [25, 25]
    assert set(legacy_v2_items) == {
        f"item:style_pack:{item_id}" for item_id in legacy_items
    }

    features = _read(catalog / "vocab/features.yaml")["entries"]
    lifecycles = _read(catalog / "lifecycle/records.yaml")["entries"]
    evaluations = _read(catalog / "lifecycle/evaluations.yaml")["entries"]
    route = _read(catalog / "runtime/routes.yaml")["entries"][
        "runtime_route:style_pack:complete_pack"
    ]

    for legacy_id, legacy in legacy_items.items():
        item = legacy_v2_items[f"item:style_pack:{legacy_id}"]
        assert item["legacy_ref"] == f"catalog/art_styles.yaml#items/{legacy_id}"
        assert "prompt" not in item
        assert "prompts" not in item
        assert item["source_refs"] == ["source:internal:taxonomy_v1"]

        projected_terms = [
            term
            for refs in item["feature_refs"].values()
            for feature_ref in refs
            for term in features[feature_ref].get("legacy_terms", [])
        ]
        assert sorted(projected_terms) == sorted(legacy["visual_axes"])

        status = legacy["validation"]["status"]
        lifecycle = lifecycles[item["lifecycle_ref"]]
        assert lifecycle["item_ref"] == item["id"]
        assert lifecycle["current_status"] == status

        if status in EVALUATION_REQUIRED_STATUSES:
            evaluation = evaluations[item["evaluation_ref"]]
            assert evaluation["item_ref"] == item["id"]
            assert evaluation["distinct_seed_count"] == legacy["validation"]["tested_seeds"]
        else:
            assert item.get("evaluation_ref") is None

        # sync_catalog_v2.py assigns runtime_route_ref unconditionally (unlike
        # evaluation_ref); runtime_route_required_statuses only governs
        # whether validate_catalog_v2.py's per-item check treats it as
        # mandatory, not whether sync actually sets it.
        assert item["runtime_route_ref"] == "runtime_route:style_pack:complete_pack"
        assert route["file"] == legacy["runtime"]["file"]
        assert [*route["path_prefix"], legacy_id] == legacy["runtime"]["path"]


def test_catalog_v2_declares_every_generated_catalog_kind() -> None:
    schema = _read(ROOT / "catalog_v2/meta/schema.yaml")
    item_kinds = schema["item_kinds"]
    expected = {
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
    assert expected <= set(item_kinds)
    for kind in expected - {"style_pack"}:
        spec = item_kinds[kind]
        assert 1 <= spec["minimum_total_features"] <= spec["maximum_total_features"] <= 12
        assert spec["additional_feature_axis"] == {"minimum": 1, "maximum": 8}


def test_catalog_v2_rejects_namespaced_and_dangling_refs(tmp_path: Path) -> None:
    catalog = _fixture_tree(tmp_path)
    shard_path = _shard_paths(catalog)[0]
    shard = _read(shard_path)
    item = shard["items"][0]
    item["feature_refs"]["linework"] = ["feature:linework:not_registered"]
    item["source_refs"] = ["feature:source:wrong_namespace"]
    item["evaluation_ref"] = "evaluation:style_pack:not_registered"
    _write(shard_path, shard)

    messages = _messages(validate_catalog_v2(catalog))
    assert "dangling feature reference 'feature:linework:not_registered'" in messages
    assert "expected 'source' namespace" in messages
    assert "dangling evaluation reference 'evaluation:style_pack:not_registered'" in messages


def test_catalog_v2_rejects_bad_shard_metadata_and_global_duplicates(tmp_path: Path) -> None:
    catalog = _fixture_tree(tmp_path)
    original_path = _shard_paths(catalog)[0]
    duplicate_path = catalog / "items/style_pack/style_packs_003.yaml"
    duplicate = _read(original_path)
    duplicate["shard"].update(
        {
            "id": "shard:style_pack:style_packs_003",
            "sequence": 3,
            "item_count": 26,
            "maximum_items": 26,
        }
    )
    _write(duplicate_path, duplicate)

    messages = _messages(validate_catalog_v2(catalog))
    assert "shard maximum_items must equal 25" in messages
    assert "shard item_count does not match items length" in messages
    assert "duplicate global ID 'item:style_pack:crystal_iris_pastel'" in messages


def test_catalog_v2_enforces_kind_cardinality_and_lifecycle_linkage(tmp_path: Path) -> None:
    catalog = _fixture_tree(tmp_path)
    shard_path = _shard_paths(catalog)[0]
    shard = _read(shard_path)
    del shard["items"][0]["feature_refs"]["linework"]
    _write(shard_path, shard)

    lifecycle_path = catalog / "lifecycle/records.yaml"
    lifecycle_data = _read(lifecycle_path)
    lifecycle = lifecycle_data["entries"]["lifecycle:style_pack:crystal_iris_pastel"]
    lifecycle["evaluation_ref"] = "evaluation:style_pack:missing_link"
    _write(lifecycle_path, lifecycle_data)

    messages = _messages(validate_catalog_v2(catalog))
    assert "feature projection does not preserve legacy visual_axes" in messages
    assert "lifecycle and item evaluation refs differ" in messages
    assert "dangling evaluation reference 'evaluation:style_pack:missing_link'" in messages


def test_catalog_v2_requires_an_available_route_and_preserves_public_path(tmp_path: Path) -> None:
    catalog = _fixture_tree(tmp_path)
    routes_path = catalog / "runtime/routes.yaml"
    routes = _read(routes_path)
    route = routes["entries"]["runtime_route:style_pack:complete_pack"]
    route["enabled"] = False
    route["path_prefix"] = ["krea2", "style", "renamed_pack"]
    _write(routes_path, routes)

    messages = _messages(validate_catalog_v2(catalog))
    assert "requires an enabled runtime route" in messages
    assert "runtime route does not preserve the legacy public path" in messages


def test_catalog_v2_coverage_gate_rejects_a_missing_legacy_item(tmp_path: Path) -> None:
    catalog = _fixture_tree(tmp_path)
    shard_path = catalog / "items/style_pack/style_packs_002.yaml"
    shard = _read(shard_path)
    removed = shard["items"].pop()
    shard["shard"]["item_count"] = len(shard["items"])
    _write(shard_path, shard)

    messages = _messages(validate_catalog_v2(catalog))
    assert f"missing migrated item {removed['id']!r}" in messages


def test_catalog_v2_coverage_gate_rejects_lossy_feature_projection(tmp_path: Path) -> None:
    catalog = _fixture_tree(tmp_path)
    shard_path = _shard_paths(catalog)[0]
    shard = _read(shard_path)
    shard["items"][0]["feature_refs"]["rendering"].pop()
    _write(shard_path, shard)

    messages = _messages(validate_catalog_v2(catalog))
    assert "feature projection does not preserve legacy visual_axes" in messages
