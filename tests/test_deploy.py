from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest

import deploy_remote_wildcards as deploy
from build_impact_yaml import impact_compatible_document
from common import dump_yaml, iter_leaf_lists, item_status, iter_catalog_items, load_yaml
from deploy_remote_wildcards import (
    DEFAULT_SOURCE,
    approved_manifest_item_count,
    atomic_write_evidence,
    deployment_evidence,
    deployment_id_from_evidence,
    krea2_namespace,
    remote_queue_empty,
    rsync_command,
)


ROOT = Path(__file__).resolve().parents[1]


def write_approved_manifest(path: Path, item_count: int = 2) -> None:
    items = [
        {
            "id": f"approved_{index}",
            "status": "approved",
            "runtime_file": "krea2/style/complete_pack.yaml",
            "runtime_path": f"krea2/style/complete_pack/approved_{index}",
            "prompt_count": 1,
        }
        for index in range(1, item_count + 1)
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "included_statuses": ["approved"],
                "item_count": item_count,
                "prompt_count": item_count,
                "files": ["krea2/style/complete_pack.yaml"],
                "items": items,
            }
        ),
        encoding="utf-8",
    )


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


def test_deployment_evidence_is_redacted_and_written_atomically(tmp_path: Path) -> None:
    artifact = tmp_path / "preview.yaml"
    artifact.write_text("krea2: {}\n", encoding="utf-8")
    document = deployment_evidence(
        artifact,
        applied=True,
        status="passed",
        expected_paths=42,
        digest="a" * 64,
        approved_items=21,
        evidence_path=Path("tests/reports/deployments/test-preview.json"),
    )
    output = Path("tests/reports/deployments/test-preview.json")

    previous = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        atomic_write_evidence(output, document)
    finally:
        os.chdir(previous)

    raw = (tmp_path / output).read_text(encoding="utf-8")
    assert "private_comfyui" in raw
    assert "ssh" not in raw.lower()
    assert "api" not in raw.lower()
    assert str(tmp_path) not in raw
    assert not list((tmp_path / output.parent).glob(".test-preview.json.*"))
    assert document["schema_version"] == 1
    assert document["deployment_id"] == "test-preview"
    assert document["deployment_type"] == "preview"
    assert document["approved_items"] == 21
    assert document["verification"] == {
        "checksum_match": True,
        "exact_krea2_namespace": True,
        "impact_reload": True,
        "smoke_completed": False,
        "queue_empty": True,
    }
    assert document["smoke"] is None


def test_deployment_evidence_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must remain relative"):
        atomic_write_evidence(tmp_path / "outside.json", {})


def test_deployment_id_rejects_unsafe_relative_filename() -> None:
    assert (
        deployment_id_from_evidence(
            Path("tests/reports/deployments/production_v2.json")
        )
        == "production_v2"
    )
    with pytest.raises(ValueError, match="must remain relative"):
        deployment_id_from_evidence(Path("tests/reports/deployments/bad name.json"))


@pytest.mark.parametrize(
    "mutation",
    ["non_approved", "stale_items", "stale_prompts", "duplicate_id"],
)
def test_manifest_must_be_current_approved_only(
    tmp_path: Path, mutation: str
) -> None:
    manifest = tmp_path / "wildcards-manifest.json"
    write_approved_manifest(manifest)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if mutation == "non_approved":
        document["included_statuses"] = ["testing", "approved"]
    elif mutation == "stale_items":
        document["item_count"] = 3
    elif mutation == "stale_prompts":
        document["prompt_count"] = 3
    else:
        document["items"][1]["id"] = document["items"][0]["id"]
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError):
        approved_manifest_item_count(manifest)


def test_dry_run_evidence_is_non_applied_and_cannot_pass_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    DEFAULT_SOURCE.parent.mkdir(parents=True)
    DEFAULT_SOURCE.write_text("krea2: {}\n", encoding="utf-8")

    document = deployment_evidence(
        DEFAULT_SOURCE,
        applied=False,
        status="dry-run",
        expected_paths=2,
        digest="b" * 64,
        approved_items=2,
        evidence_path=Path("tests/reports/deployments/production_dry_run.json"),
        checksum_match=False,
        exact_krea2_namespace=False,
        impact_reload=False,
        queue_empty=False,
    )

    assert document["deployment_type"] == "production"
    assert document["status"] == "dry-run"
    assert document["mode"] == "dry-run"
    assert document["applied"] is False
    assert not any(document["verification"].values())
    assert document["smoke"] is None


def test_remote_queue_requires_empty_running_and_pending_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deploy,
        "get_json",
        lambda _url: {"queue_running": [], "queue_pending": []},
    )
    assert remote_queue_empty("private_api") is True

    monkeypatch.setattr(
        deploy,
        "get_json",
        lambda _url: {"queue_running": [["job"]], "queue_pending": []},
    )
    assert remote_queue_empty("private_api") is False


def test_apply_writes_completion_compatible_evidence_after_queue_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    DEFAULT_SOURCE.parent.mkdir(parents=True)
    dump_yaml(
        {
            "krea2": {
                "style/complete_pack/approved_one": ["First approved treatment."],
                "style/complete_pack/approved_two": ["Second approved treatment."],
            }
        },
        DEFAULT_SOURCE,
    )
    manifest = Path("wildcards-manifest.json")
    write_approved_manifest(manifest)
    evidence = Path("tests/reports/deployments/production_test.json")
    events: list[str] = []

    monkeypatch.setattr(
        deploy,
        "run",
        lambda command: subprocess.CompletedProcess(command, 0, "", ""),
    )
    monkeypatch.setattr(
        deploy,
        "remote_krea2_namespace",
        lambda _api: events.append("preflight") or set(),
    )
    monkeypatch.setattr(
        deploy,
        "remote_sha256",
        lambda _target, _path: deploy.sha256(DEFAULT_SOURCE),
    )
    monkeypatch.setattr(deploy, "refresh", lambda _api: events.append("reload"))
    monkeypatch.setattr(
        deploy,
        "verify_remote_paths",
        lambda _api, _expected: events.append("namespace") or (set(), set()),
    )
    monkeypatch.setattr(
        deploy,
        "remote_queue_empty",
        lambda _api: events.append("queue") or True,
    )

    result = deploy.main(
        [
            "--source",
            str(DEFAULT_SOURCE),
            "--manifest",
            str(manifest),
            "--ssh-target",
            "ssh_alias",
            "--remote-dir",
            "wildcard_store",
            "--api-url",
            "private_api",
            "--evidence",
            str(evidence),
            "--apply",
        ]
    )

    assert result == 0
    assert events == ["preflight", "reload", "namespace", "queue"]
    document = json.loads(evidence.read_text(encoding="utf-8"))
    assert document["deployment_id"] == "production_test"
    assert document["deployment_type"] == "production"
    assert document["status"] == "passed"
    assert document["applied"] is True
    assert document["approved_items"] == 2
    assert document["verification"] == {
        "checksum_match": True,
        "exact_krea2_namespace": True,
        "impact_reload": True,
        "queue_empty": True,
        "smoke_completed": False,
    }
    assert document["smoke"] is None
    raw = evidence.read_text(encoding="utf-8")
    assert "ssh_alias" not in raw
    assert "wildcard_store" not in raw
    assert "private_api" not in raw
