from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_runtime_coverage import audit
from common import dump_yaml


RUNTIME_FILE = "approved.yaml"
RUNTIME_PATH = "krea2/styles/approved_example"
RESOLVED_PROMPT = "A centered figure uses clean contours and soft neutral shading."


def write_manifest(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "included_statuses": ["approved"],
                "files": [RUNTIME_FILE],
                "items": items,
            }
        ),
        encoding="utf-8",
    )


def valid_item(**updates: object) -> dict[str, object]:
    item: dict[str, object] = {
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


def make_valid_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    write_runtime(runtime_root / RUNTIME_FILE, [RESOLVED_PROMPT])

    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest_path, [valid_item()])

    prompt_log_root = tmp_path / "reports"
    run_dir = prompt_log_root / "run_one"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"resolved_prompt": RESOLVED_PROMPT}),
        encoding="utf-8",
    )
    return runtime_root, manifest_path, prompt_log_root


def test_valid_approved_runtime_and_resolved_prompt_log_pass(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_log_root = make_valid_case(tmp_path)

    report = audit(runtime_root, manifest_path, prompt_log_root)

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


def test_unresolved_wildcards_and_braces_fail_with_exact_counts(
    tmp_path: Path,
) -> None:
    runtime_root, manifest_path, prompt_log_root = make_valid_case(tmp_path)
    write_runtime(
        runtime_root / RUNTIME_FILE,
        ["A __krea2/styles/other__ figure has {graphic} edges and __unresolved__."],
    )

    report = audit(runtime_root, manifest_path, prompt_log_root)

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
    runtime_root, manifest_path, prompt_log_root = make_valid_case(tmp_path)
    if scenario == "missing_file":
        (runtime_root / RUNTIME_FILE).unlink()
    elif scenario == "extra_file":
        write_runtime(runtime_root / "unexpected.yaml", [RESOLVED_PROMPT])
    else:
        write_manifest(
            manifest_path,
            [valid_item(runtime_path="krea2/styles/missing_example")],
        )

    report = audit(runtime_root, manifest_path, prompt_log_root)

    assert report["complete"] is False
    assert report["status"] == "failed"
    assert report["runtime_files_loaded"] == expected_loaded
    assert report["wildcard_paths_resolved"] == expected_resolved


def test_catalog_metadata_key_in_runtime_fails_separation(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_log_root = make_valid_case(tmp_path)
    dump_yaml(
        {"krea2": {"styles": {"validation": [RESOLVED_PROMPT]}}},
        runtime_root / RUNTIME_FILE,
    )
    write_manifest(
        manifest_path,
        [valid_item(runtime_path="krea2/styles/validation")],
    )

    report = audit(runtime_root, manifest_path, prompt_log_root)

    assert report["wildcard_paths_resolved"] == 1
    assert report["catalog_runtime_separated"] is False
    assert report["complete"] is False
    assert report["status"] == "failed"


@pytest.mark.parametrize("manifest_case", ["malformed_path", "duplicate_path"])
def test_malformed_or_duplicate_manifest_path_is_rejected(
    tmp_path: Path, manifest_case: str
) -> None:
    runtime_root, manifest_path, prompt_log_root = make_valid_case(tmp_path)
    if manifest_case == "malformed_path":
        items = [valid_item(runtime_path="")]
        message = "invalid runtime metadata"
    else:
        items = [valid_item(), valid_item()]
        message = "duplicate wildcard path"
    write_manifest(manifest_path, items)

    with pytest.raises(ValueError, match=message):
        audit(runtime_root, manifest_path, prompt_log_root)


def test_missing_resolved_prompt_log_fails(tmp_path: Path) -> None:
    runtime_root, manifest_path, prompt_log_root = make_valid_case(tmp_path)
    (prompt_log_root / "run_one" / "run.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )

    report = audit(runtime_root, manifest_path, prompt_log_root)

    assert report["final_prompt_logs_saved"] is False
    assert report["final_prompt_log_count"] == 0
    assert report["complete"] is False
    assert report["status"] == "failed"
