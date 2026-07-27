from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from audit_runtime_coverage import audit
from common import dump_yaml


RUNTIME_FILE = "approved.yaml"
RUNTIME_PATH = "krea2/styles/approved_example"
RESOLVED_PROMPT = "A centered figure uses clean contours and soft neutral shading."
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_runtime_coverage.py"


def write_manifest(path: Path, items: list[dict[str, object]]) -> None:
    prompt_count = sum(
        item["prompt_count"] for item in items if type(item.get("prompt_count")) is int
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "included_statuses": ["approved"],
                "item_count": len(items),
                "prompt_count": prompt_count,
                "files": [RUNTIME_FILE],
                "items": items,
            }
        ),
        encoding="utf-8",
    )


def valid_item(**updates: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "approved_example",
        "runtime_file": RUNTIME_FILE,
        "runtime_path": RUNTIME_PATH,
        "prompt_count": 1,
        "status": "approved",
    }
    item.update(updates)
    return item


def write_runtime(path: Path, values: list[str]) -> None:
    dump_yaml(
        {"krea2": {"styles": {"approved_example": values}}},
        path,
    )


def make_valid_case(tmp_path: Path) -> tuple[Path, Path, list[Path]]:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    write_runtime(runtime_root / RUNTIME_FILE, [RESOLVED_PROMPT])

    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest_path, [valid_item()])

    artifact = tmp_path / "build/impact-production/krea2_complete_pack.yaml"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("approved artifact\n", encoding="utf-8")

    run_dir = tmp_path / "reports/run_one"
    run_dir.mkdir(parents=True)
    image = run_dir / "image_01.png"
    image.write_bytes(b"image")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "resolved_prompt": RESOLVED_PROMPT,
                "remote": "private_comfyui",
                "seed": 6006,
                "images": ["image_01.png"],
                "endpoint": "MUST_NOT_APPEAR",
            }
        ),
        encoding="utf-8",
    )
    return runtime_root, manifest_path, [Path("reports/run_one/run.json")]


def test_valid_approved_runtime_and_resolved_prompt_log_pass(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)

    report = audit(runtime_root, manifest_path, prompt_logs)

    assert report["complete"] is True
    assert report["status"] == "passed"
    assert report["runtime_files_expected"] == 1
    assert report["runtime_files_loaded"] == 1
    assert report["wildcard_paths_expected"] == 1
    assert report["wildcard_paths_resolved"] == 1
    assert report["unresolved_wildcards"] == 0
    assert report["novelai_brace_conflicts"] == 0
    assert report["catalog_runtime_separated"] is True
    assert report["final_prompt_logs_saved"] is True
    assert report["final_prompt_log_count"] == 1
    assert (
        report["manifest_sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    artifact = tmp_path / "build/impact-production/krea2_complete_pack.yaml"
    assert report["production_artifact"] == (
        "build/impact-production/krea2_complete_pack.yaml"
    )
    assert (
        report["production_artifact_sha256"]
        == hashlib.sha256(artifact.read_bytes()).hexdigest()
    )
    assert report["production_artifact_bytes"] == artifact.stat().st_size
    assert report["prompt_logs"] == [
        {
            "path": "reports/run_one/run.json",
            "sha256": hashlib.sha256(
                (tmp_path / "reports/run_one/run.json").read_bytes()
            ).hexdigest(),
        }
    ]
    serialized = json.dumps(report)
    assert RESOLVED_PROMPT not in serialized
    assert "MUST_NOT_APPEAR" not in serialized


def test_unresolved_wildcards_and_braces_fail_with_exact_counts(
    tmp_path: Path,
) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    write_runtime(
        runtime_root / RUNTIME_FILE,
        ["A __krea2/styles/other__ figure has {graphic} edges and __unresolved__."],
    )

    report = audit(runtime_root, manifest_path, prompt_logs)

    assert report["complete"] is False
    assert report["status"] == "failed"
    assert report["wildcard_paths_resolved"] == 1
    assert report["unresolved_wildcards"] == 2
    assert report["novelai_brace_conflicts"] == 2


@pytest.mark.parametrize(
    ("scenario", "expected_loaded", "expected_resolved"),
    [
        ("missing_file", 0, 0),
        ("extra_file", 1, 1),
        ("path_mismatch", 1, 0),
    ],
)
def test_runtime_file_set_or_manifest_path_mismatch_fails(
    tmp_path: Path,
    scenario: str,
    expected_loaded: int,
    expected_resolved: int,
) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    if scenario == "missing_file":
        (runtime_root / RUNTIME_FILE).unlink()
    elif scenario == "extra_file":
        write_runtime(runtime_root / "unexpected.yaml", [RESOLVED_PROMPT])
    else:
        write_manifest(
            manifest_path,
            [
                valid_item(
                    id="missing_example",
                    runtime_path="krea2/styles/missing_example",
                )
            ],
        )

    report = audit(runtime_root, manifest_path, prompt_logs)

    assert report["complete"] is False
    assert report["status"] == "failed"
    assert report["runtime_files_loaded"] == expected_loaded
    assert report["wildcard_paths_resolved"] == expected_resolved


def test_catalog_metadata_key_in_runtime_fails_separation(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    dump_yaml(
        {"krea2": {"styles": {"validation": [RESOLVED_PROMPT]}}},
        runtime_root / RUNTIME_FILE,
    )
    write_manifest(
        manifest_path,
        [valid_item(id="validation", runtime_path="krea2/styles/validation")],
    )

    report = audit(runtime_root, manifest_path, prompt_logs)

    assert report["wildcard_paths_resolved"] == 1
    assert report["catalog_runtime_separated"] is False
    assert report["complete"] is False
    assert report["status"] == "failed"


@pytest.mark.parametrize("manifest_case", ["malformed_path", "duplicate_path"])
def test_malformed_or_duplicate_manifest_path_is_rejected(
    tmp_path: Path, manifest_case: str
) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    if manifest_case == "malformed_path":
        items = [valid_item(runtime_path="")]
        message = "invalid runtime metadata"
    else:
        items = [valid_item(), valid_item()]
        message = "duplicate wildcard path"
    write_manifest(manifest_path, items)

    with pytest.raises(ValueError, match=message):
        audit(runtime_root, manifest_path, prompt_logs)


def test_missing_resolved_prompt_log_fails(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    (tmp_path / prompt_logs[0]).write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lacks a resolved prompt"):
        audit(runtime_root, manifest_path, prompt_logs)


def test_multiple_explicit_prompt_logs_are_validated_and_recorded(
    tmp_path: Path,
) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    second_dir = tmp_path / "reports/run_two"
    second_dir.mkdir(parents=True)
    second_image = second_dir / "image_01.png"
    second_image.write_bytes(b"second image")
    second_run = second_dir / "run.json"
    second_run.write_text(
        json.dumps(
            {
                "resolved_prompt": "A second private resolved prompt.",
                "remote": "private_comfyui",
                "seed": 7007,
                "images": ["reports/run_two/image_01.png"],
            }
        ),
        encoding="utf-8",
    )
    prompt_logs.append(Path("reports/run_two/run.json"))

    report = audit(runtime_root, manifest_path, prompt_logs)

    assert report["complete"] is True
    assert report["final_prompt_log_count"] == 2
    assert [item["path"] for item in report["prompt_logs"]] == [
        "reports/run_one/run.json",
        "reports/run_two/run.json",
    ]
    assert "A second private resolved prompt." not in json.dumps(report)


def test_no_prompt_log_fails_clearly(tmp_path: Path) -> None:
    runtime_root, manifest_path, _ = make_valid_case(tmp_path)

    with pytest.raises(ValueError, match="at least one --prompt-log"):
        audit(runtime_root, manifest_path, [])


@pytest.mark.parametrize(
    "prompt_log",
    [Path("../outside/run.json"), Path("/outside/run.json")],
)
def test_prompt_log_must_be_safe_repository_relative(
    tmp_path: Path, prompt_log: Path
) -> None:
    runtime_root, manifest_path, _ = make_valid_case(tmp_path)

    with pytest.raises(ValueError, match="safe repository-relative"):
        audit(runtime_root, manifest_path, [prompt_log])


def test_prompt_log_symlink_is_rejected(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    linked = tmp_path / "reports/linked-run.json"
    linked.symlink_to(tmp_path / prompt_logs[0])

    with pytest.raises(ValueError, match="must not traverse symbolic links"):
        audit(runtime_root, manifest_path, [Path("reports/linked-run.json")])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("remote", "other_remote", "invalid remote metadata"),
        ("seed", True, "invalid seed metadata"),
        ("images", ["../image_01.png"], "invalid image references"),
        ("images", ["missing.png"], "invalid image references"),
    ],
)
def test_prompt_log_metadata_must_be_valid(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    run_path = tmp_path / prompt_logs[0]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run[field] = value
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        audit(runtime_root, manifest_path, prompt_logs)


def test_manifest_and_production_artifact_hashes_track_current_bytes(
    tmp_path: Path,
) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    first = audit(runtime_root, manifest_path, prompt_logs)
    artifact = tmp_path / "build/impact-production/krea2_complete_pack.yaml"
    artifact.write_text("approved artifact changed\n", encoding="utf-8")
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )

    second = audit(runtime_root, manifest_path, prompt_logs)

    assert second["manifest_sha256"] != first["manifest_sha256"]
    assert second["production_artifact_sha256"] != first["production_artifact_sha256"]
    assert second["production_artifact_bytes"] == artifact.stat().st_size


def test_manifest_item_id_must_match_its_runtime_path(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    write_manifest(manifest_path, [valid_item(id="different_id")])

    with pytest.raises(ValueError, match="invalid id or runtime path"):
        audit(runtime_root, manifest_path, prompt_logs)


def test_manifest_prompt_count_must_match_approved_items(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prompt_count"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="prompt count is inconsistent"):
        audit(runtime_root, manifest_path, prompt_logs)


def test_cli_accepts_explicit_repository_relative_prompt_log(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_logs = make_valid_case(tmp_path)
    output = tmp_path / "runtime_coverage.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--runtime",
            str(runtime_root),
            "--manifest",
            str(manifest_path),
            "--prompt-log",
            prompt_logs[0].as_posix(),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["complete"] is True
    assert report["prompt_logs"][0]["path"] == prompt_logs[0].as_posix()
