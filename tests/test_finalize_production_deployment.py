from __future__ import annotations

import json
from pathlib import Path

import pytest

from deploy_remote_wildcards import (
    DEFAULT_MANIFEST,
    DEFAULT_SOURCE,
    atomic_write_evidence,
    deployment_evidence,
    sha256,
)
from finalize_production_deployment import discover_smoke_run, finalize, main


EVIDENCE_PATH = Path("tests/reports/deployments/production_test.json")
SMOKE_PATH = Path("tests/reports/production_smoke/runs/smoke_one/run.json")
RESOLVED_PROMPT = "A centered adult portrait uses clean edges and soft neutral light."
DEPLOYED_AT = "2026-07-27T12:00:00Z"
STARTED_AT = "2026-07-27T12:00:01Z"
COMPLETED_AT = "2026-07-27T12:00:02Z"
DEPLOYMENT_NONCE = "d" * 32


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def write_manifest(path: Path, item_count: int = 2) -> None:
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
    write_json(
        path,
        {
            "schema_version": 1,
            "included_statuses": ["approved"],
            "item_count": item_count,
            "prompt_count": item_count,
            "files": ["krea2/style/complete_pack.yaml"],
            "items": items,
        },
    )


def make_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    artifact = root / DEFAULT_SOURCE
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        "krea2:\n  style/complete_pack/one: [First treatment.]\n"
        "  style/complete_pack/two: [Second treatment.]\n",
        encoding="utf-8",
    )
    manifest = root / DEFAULT_MANIFEST
    write_manifest(manifest)
    evidence = deployment_evidence(
        artifact,
        applied=True,
        status="passed",
        expected_paths=2,
        digest=sha256(artifact),
        manifest_name=manifest.name,
        manifest_digest=sha256(manifest),
        manifest_bytes=manifest.stat().st_size,
        approved_items=2,
        evidence_path=EVIDENCE_PATH,
        deployment_type="production",
        checksum_match=True,
        exact_krea2_namespace=True,
        impact_reload=True,
        queue_empty=True,
        deployed_at_utc=DEPLOYED_AT,
        deployment_nonce=DEPLOYMENT_NONCE,
    )
    atomic_write_evidence(EVIDENCE_PATH, evidence, root=root)
    write_json(
        root / SMOKE_PATH,
        {
            "seed": 6006,
            "remote": "private_comfyui",
            "resolved_prompt": RESOLVED_PROMPT,
            "images": ["smoke_output.png"],
            "started_at_utc": STARTED_AT,
            "completed_at_utc": COMPLETED_AT,
            "deployment": {
                "deployment_id": EVIDENCE_PATH.stem,
                "deployment_nonce": DEPLOYMENT_NONCE,
                "artifact_sha256": sha256(artifact),
                "manifest_sha256": sha256(manifest),
                "deployed_at_utc": DEPLOYED_AT,
            },
        },
    )
    return root


def test_finalize_cross_checks_and_atomically_records_redacted_smoke(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)

    document = finalize(
        root=root,
        evidence_path=EVIDENCE_PATH,
        smoke_run_path=SMOKE_PATH,
    )

    assert document["verification"]["smoke_completed"] is True
    smoke_path = root / SMOKE_PATH
    assert document["smoke"] == {
        "seed": 6006,
        "run_record": SMOKE_PATH.as_posix(),
        "run_record_sha256": sha256(smoke_path),
        "deployment_id": EVIDENCE_PATH.stem,
        "deployment_nonce": DEPLOYMENT_NONCE,
        "artifact_sha256": sha256(root / DEFAULT_SOURCE),
        "manifest_sha256": sha256(root / DEFAULT_MANIFEST),
        "started_at_utc": STARTED_AT,
        "completed_at_utc": COMPLETED_AT,
    }
    raw = (root / EVIDENCE_PATH).read_text(encoding="utf-8")
    assert RESOLVED_PROMPT not in raw
    assert "smoke_output.png" not in raw
    assert "private_comfyui" in raw
    assert str(root) not in raw
    assert not list((root / EVIDENCE_PATH.parent).glob(".production_test.json.*"))

    before = (root / EVIDENCE_PATH).read_bytes()
    repeated = finalize(
        root=root,
        evidence_path=EVIDENCE_PATH,
        smoke_run_path=SMOKE_PATH,
    )
    assert repeated == document
    assert (root / EVIDENCE_PATH).read_bytes() == before


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("preview", "not a passed production apply"),
        ("dry_run", "not a passed production apply"),
        ("approved_items", "approved item count is stale"),
        ("prior_gate", "verification gates have not passed"),
        ("deployment_id", "id does not match"),
    ],
)
def test_finalize_rejects_stale_or_nonproduction_evidence(
    tmp_path: Path, mutation: str, message: str
) -> None:
    root = make_repository(tmp_path)
    path = root / EVIDENCE_PATH
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "preview":
        evidence["deployment_type"] = "preview"
    elif mutation == "dry_run":
        evidence["status"] = "dry-run"
        evidence["mode"] = "dry-run"
        evidence["applied"] = False
    elif mutation == "approved_items":
        evidence["approved_items"] = 1
    elif mutation == "prior_gate":
        evidence["verification"]["queue_empty"] = False
    else:
        evidence["deployment_id"] = "production_stale"
    write_json(path, evidence)

    with pytest.raises(ValueError, match=message):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=SMOKE_PATH,
        )


def test_finalize_rejects_stale_artifact_checksum(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    with (root / DEFAULT_SOURCE).open("a", encoding="utf-8") as handle:
        handle.write("# changed after deployment\n")

    with pytest.raises(ValueError, match="artifact evidence is stale or mismatched"):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=SMOKE_PATH,
        )


def test_finalize_rejects_stale_manifest_checksum(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    with (root / DEFAULT_MANIFEST).open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(ValueError, match="manifest evidence is stale or mismatched"):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=SMOKE_PATH,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("deployment_nonce", "e" * 32, "does not belong"),
        ("artifact_sha256", "e" * 64, "does not belong"),
        ("deployment_id", "other_deployment", "does not belong"),
    ],
)
def test_finalize_rejects_smoke_bound_to_another_deployment(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    root = make_repository(tmp_path)
    smoke_path = root / SMOKE_PATH
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    smoke["deployment"][field] = value
    write_json(smoke_path, smoke)

    with pytest.raises(ValueError, match=message):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=SMOKE_PATH,
        )


def test_finalize_rejects_smoke_started_before_deployment(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    smoke_path = root / SMOKE_PATH
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    smoke["started_at_utc"] = "2026-07-27T11:59:59Z"
    write_json(smoke_path, smoke)

    with pytest.raises(ValueError, match="chronology is invalid"):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=SMOKE_PATH,
        )


def test_discover_smoke_run_selects_only_current_deployment(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    stale = root / "tests/reports/production_smoke/runs/stale/run.json"
    stale_document = json.loads((root / SMOKE_PATH).read_text(encoding="utf-8"))
    stale_document["deployment"]["deployment_nonce"] = "e" * 32
    write_json(stale, stale_document)

    assert discover_smoke_run(
        root=root,
        evidence_path=EVIDENCE_PATH,
        smoke_root=Path("tests/reports/production_smoke"),
    ) == SMOKE_PATH


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("seed", True, "seed must be an integer"),
        ("remote", "unredacted_remote", "remote marker is invalid"),
        ("resolved_prompt", "", "resolved_prompt is incomplete"),
        (
            "resolved_prompt",
            "A __krea2/style/example__ portrait with {weight}.",
            "resolved_prompt is incomplete",
        ),
        ("images", [], "must record non-empty outputs"),
        ("images", ["../outside.png"], "must remain relative"),
    ],
)
def test_finalize_rejects_invalid_smoke_fields_or_outputs(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    root = make_repository(tmp_path)
    smoke_path = root / SMOKE_PATH
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    smoke[field] = value
    write_json(smoke_path, smoke)

    with pytest.raises(ValueError, match=message):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=SMOKE_PATH,
        )


def test_finalize_rejects_absolute_outside_and_non_run_json_paths(
    tmp_path: Path,
) -> None:
    root = make_repository(tmp_path)
    outside = tmp_path / "run.json"
    write_json(
        outside,
        {
            "seed": 7007,
            "remote": "private_comfyui",
            "resolved_prompt": RESOLVED_PROMPT,
            "images": ["outside.png"],
        },
    )
    with pytest.raises(ValueError, match="repository-relative"):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=outside.resolve(),
        )
    with pytest.raises(ValueError, match="repository-relative"):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=Path("../run.json"),
        )

    wrong_name = SMOKE_PATH.with_name("smoke.json")
    write_json(root / wrong_name, json.loads((root / SMOKE_PATH).read_text()))
    with pytest.raises(ValueError, match="run.json"):
        finalize(
            root=root,
            evidence_path=EVIDENCE_PATH,
            smoke_run_path=wrong_name,
        )


def test_finalizer_cli_does_not_echo_rejected_absolute_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repository(tmp_path)
    rejected = (tmp_path / "private-location" / "run.json").resolve()

    result = main(
        [
            "--root",
            str(root),
            "--evidence",
            str(EVIDENCE_PATH),
            "--smoke-run",
            str(rejected),
        ]
    )

    assert result == 1
    output = capsys.readouterr().out
    assert str(rejected) not in output
    assert output == "ERROR: production deployment finalization failed validation.\n"
