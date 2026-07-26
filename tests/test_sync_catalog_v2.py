from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from sync_catalog_v2 import SyncError, sync_catalog_v2
from validate_catalog_v2 import validate_catalog_v2


ROOT = Path(__file__).resolve().parents[1]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=120)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _v2_items(repo: Path, kind: str) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for path in sorted((repo / f"catalog_v2/items/{kind}").glob("*.yaml"))
        for item in _read_yaml(path)["items"]
    }


def _refresh_manifest(repo: Path, blueprint: Path, manifest: Path, count: int) -> None:
    output = repo / "catalog/style_atomics.yaml"
    generated_ids = [f"atomic_{index:03d}" for index in range(1, count + 1)]
    blueprints = [{"path": blueprint.name, "sha256": _sha256(blueprint)}]
    blueprint_digest = hashlib.sha256(
        json.dumps(
            blueprints,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "generator": "test-fixture",
            "blueprints": blueprints,
            "blueprint_digest": blueprint_digest,
            "total_item_count": count,
            "outputs": [
                {
                    "path": "catalog/style_atomics.yaml",
                    "output_file": "style_atomics.yaml",
                    "sha256": _sha256(output),
                    "item_count": count,
                    "generated_item_count": count,
                    "generated_item_ids": generated_ids,
                    "collection_ids": ["atomic_set"],
                }
            ],
            "collections": [
                {
                    "id": "atomic_set",
                    "kind": "style_atomic",
                    "output_file": "style_atomics.yaml",
                    "item_count": count,
                    "product_size": count * 2,
                    "output_sha256": _sha256(output),
                }
            ],
        },
    )


def _fixture_repo(tmp_path: Path, count: int) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / "catalog").mkdir(parents=True)
    shutil.copytree(ROOT / "catalog_v2/meta", repo / "catalog_v2/meta")
    _write_yaml(
        repo / "catalog/sources.yaml",
        {
            "schema_version": 1,
            "catalog": "sources",
            "sources": {
                "internal_taxonomy_v1": {"title": "Minimal synchronization fixture"}
            },
        },
    )
    _write_yaml(
        repo / "catalog/art_styles.yaml",
        {"schema_version": 1, "catalog": "art_styles", "items": {}},
    )
    for relative, catalog_name, namespace in (
        ("vocab/features.yaml", "feature_registry", "feature"),
        ("vocab/sources.yaml", "source_registry", "source"),
        ("runtime/routes.yaml", "runtime_route_registry", "runtime_route"),
        ("lifecycle/evaluations.yaml", "evaluation_registry", "evaluation"),
        ("lifecycle/records.yaml", "lifecycle_registry", "lifecycle"),
    ):
        _write_yaml(
            repo / "catalog_v2" / relative,
            {
                "schema_version": 2,
                "catalog": catalog_name,
                "namespace": namespace,
                "entries": {},
            },
        )
    _write_yaml(
        repo / "catalog_v2/items/style_pack/fixture_001.yaml",
        {
            "schema_version": 2,
            "catalog": "item_shard",
            "shard": {
                "id": "shard:style_pack:fixture_001",
                "kind": "style_pack",
                "sequence": 1,
                "item_count": 0,
                "maximum_items": 25,
            },
            "items": [],
        },
    )

    items = {}
    form_values = []
    for index in range(1, count + 1):
        item_id = f"atomic_{index:03d}"
        form_id = f"form_{index:03d}"
        form_values.append({"id": form_id, "text": f"balanced visual form number {index}"})
        items[item_id] = {
            "family": "atomic_set",
            "visual_axes": [f"form_{form_id}", "energy_calm"],
            "feature_axes": {"form": [form_id], "energy": ["calm"]},
            "prompt": f"PROMPT BODY SHOULD NOT APPEAR IN V2 {index}",
            "compatibility": {"recommended": [], "avoid": []},
            "source_refs": ["internal_taxonomy_v1"],
            "runtime": {
                "file": "krea2/style/atomic.yaml",
                "path": ["krea2", "style", "atomic", item_id],
            },
            "validation": {
                "model": "krea2_turbo_mxfp8",
                "tested_seeds": 0,
                "status": "generated",
            },
        }
    _write_yaml(
        repo / "catalog/style_atomics.yaml",
        {"schema_version": 1, "catalog": "style_atomics", "items": items},
    )

    blueprint = repo / "catalog/blueprints/test_atomics.yaml"
    _write_yaml(
        blueprint,
        {
            "schema_version": 1,
            "collections": [
                {
                    "id": "atomic_set",
                    "kind": "style_atomic",
                    "output_file": "style_atomics.yaml",
                    "family": "atomic_set",
                    "runtime": {
                        "file": "krea2/style/atomic.yaml",
                        "path_prefix": ["krea2", "style", "atomic"],
                    },
                    "source_refs": ["internal_taxonomy_v1"],
                    "target_count": count,
                    "dimensions": [
                        {"id": "form", "values": form_values},
                        {"id": "energy", "values": [{"id": "calm", "text": "calm energy"}]},
                    ],
                    "templates": [
                        {"id": "atomic", "text": "{form} with {energy}"},
                        {"id": "atomic_alt", "text": "Alternative {form} with {energy}"},
                    ],
                    "compatibility": {"avoid": []},
                }
            ],
        },
    )
    manifest = repo / "build/catalog-generation-manifest.json"
    _refresh_manifest(repo, blueprint, manifest, count)
    return repo, blueprint, manifest


def test_sync_dry_run_then_atomic_apply_preserves_styles_and_shards_at_25(
    tmp_path: Path,
) -> None:
    repo, blueprint, manifest = _fixture_repo(tmp_path, 26)
    before_digest = _tree_digest(repo / "catalog_v2")
    original_lifecycles = _read_yaml(repo / "catalog_v2/lifecycle/records.yaml")["entries"]
    original_evaluations = _read_yaml(repo / "catalog_v2/lifecycle/evaluations.yaml")["entries"]

    report = sync_catalog_v2(
        repo,
        blueprint_paths=[blueprint],
        manifest_paths=[manifest],
    )
    assert report.dry_run is True
    assert report.added_items == 26
    assert report.manifest_outputs_verified == 1
    assert _tree_digest(repo / "catalog_v2") == before_digest
    assert not (repo / "catalog_v2/items/style_atomic").exists()

    applied = sync_catalog_v2(
        repo,
        blueprint_paths=[blueprint],
        manifest_paths=[manifest],
        apply=True,
    )
    assert applied.dry_run is False
    assert applied.added_items == 26
    assert validate_catalog_v2(repo / "catalog_v2") == []

    shards = [
        _read_yaml(path)
        for path in sorted((repo / "catalog_v2/items/style_atomic").glob("*.yaml"))
    ]
    assert [shard["shard"]["item_count"] for shard in shards] == [25, 1]
    items = _v2_items(repo, "style_atomic")
    assert len(items) == 26
    first = items["item:style_atomic:atomic_001"]
    assert set(first["feature_refs"]) == {"energy", "form"}
    assert "evaluation_ref" not in first
    assert "prompt" not in first and "prompts" not in first
    assert first["legacy_ref"] == "catalog/style_atomics.yaml#items/atomic_001"
    v2_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repo / "catalog_v2").rglob("*.yaml")
    )
    assert "PROMPT BODY SHOULD NOT APPEAR" not in v2_text
    assert "balanced visual form number 1" not in v2_text

    lifecycles = _read_yaml(repo / "catalog_v2/lifecycle/records.yaml")["entries"]
    evaluations = _read_yaml(repo / "catalog_v2/lifecycle/evaluations.yaml")["entries"]
    assert {key: lifecycles[key] for key in original_lifecycles} == original_lifecycles
    assert {key: evaluations[key] for key in original_evaluations} == original_evaluations
    assert not any(key.startswith("evaluation:style_atomic:") for key in evaluations)


def test_sync_adds_evaluation_only_on_required_status_and_preserves_history(
    tmp_path: Path,
) -> None:
    repo, blueprint, manifest = _fixture_repo(tmp_path, 1)
    sync_catalog_v2(
        repo,
        blueprint_paths=[blueprint],
        manifest_paths=[manifest],
        apply=True,
    )

    catalog_path = repo / "catalog/style_atomics.yaml"
    catalog = _read_yaml(catalog_path)
    validation = catalog["items"]["atomic_001"]["validation"]
    validation.update(
        {"status": "testing", "tested_seeds": 3, "last_evaluation": "atomic_pilot_v0_1"}
    )
    _write_yaml(catalog_path, catalog)
    _refresh_manifest(repo, blueprint, manifest, 1)

    report = sync_catalog_v2(
        repo,
        blueprint_paths=[blueprint],
        manifest_paths=[manifest],
        apply=True,
    )
    assert report.added_evaluations == 1
    assert report.lifecycle_transitions == 1
    item = _v2_items(repo, "style_atomic")["item:style_atomic:atomic_001"]
    assert item["evaluation_ref"].endswith("atomic_pilot_v0_1_s3")
    lifecycle = _read_yaml(repo / "catalog_v2/lifecycle/records.yaml")["entries"][
        item["lifecycle_ref"]
    ]
    assert [record["to_status"] for record in lifecycle["history"]] == [
        "generated",
        "testing",
    ]
    assert lifecycle["evaluation_ref"] == item["evaluation_ref"]
    assert validate_catalog_v2(repo / "catalog_v2") == []

    idempotent = sync_catalog_v2(
        repo,
        blueprint_paths=[blueprint],
        manifest_paths=[manifest],
    )
    assert idempotent.changed is False


def test_sync_rejects_manifest_mismatch_without_touching_catalog_v2(
    tmp_path: Path,
) -> None:
    repo, blueprint, manifest = _fixture_repo(tmp_path, 1)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["outputs"][0]["sha256"] = "0" * 64
    _write_json(manifest, manifest_data)
    before = _tree_digest(repo / "catalog_v2")

    with pytest.raises(SyncError, match="sha256 does not match"):
        sync_catalog_v2(
            repo,
            blueprint_paths=[blueprint],
            manifest_paths=[manifest],
            apply=True,
        )
    assert _tree_digest(repo / "catalog_v2") == before


def test_sync_requires_manifest_for_blueprint_outputs(tmp_path: Path) -> None:
    repo, blueprint, manifest = _fixture_repo(tmp_path, 1)
    manifest.unlink()
    before = _tree_digest(repo / "catalog_v2")

    with pytest.raises(SyncError, match="require a generated manifest"):
        sync_catalog_v2(repo, blueprint_paths=[blueprint])
    assert _tree_digest(repo / "catalog_v2") == before


def test_sync_projection_is_deterministic_across_clean_roots(tmp_path: Path) -> None:
    repo_a, blueprint_a, manifest_a = _fixture_repo(tmp_path / "a", 3)
    repo_b, blueprint_b, manifest_b = _fixture_repo(tmp_path / "b", 3)

    sync_catalog_v2(
        repo_a,
        blueprint_paths=[blueprint_a],
        manifest_paths=[manifest_a],
        apply=True,
    )
    sync_catalog_v2(
        repo_b,
        blueprint_paths=[blueprint_b],
        manifest_paths=[manifest_b],
        apply=True,
    )

    assert _tree_digest(repo_a / "catalog_v2") == _tree_digest(repo_b / "catalog_v2")
