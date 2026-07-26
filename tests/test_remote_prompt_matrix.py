from __future__ import annotations

import csv
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import run_remote_prompt_matrix as runner


ROOT = Path(__file__).resolve().parents[1]


def matrix_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": 1,
        "test_id": "PAIR0001",
        "style_id": "pairwise_one",
        "label": "Pairwise one",
        "mode": "pairwise",
        "seed": 1001,
        "prompt": "A fully resolved prompt for one adult subject in a fixed studio.",
        "factors": {"style": "soft_ink", "camera": "eye_level"},
    }
    row.update(overrides)
    return row


def write_matrix(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def fake_png(width: int = 1024, height: int = 1024) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", width, height)


def test_load_jobs_accepts_resolved_pairwise_metadata(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    write_matrix(matrix, [matrix_row()])

    jobs = runner.load_jobs(matrix)

    assert jobs[0]["factors"] == {"style": "soft_ink", "camera": "eye_level"}
    assert jobs[0]["prompt"].startswith("A fully resolved")


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([matrix_row(prompt="Use __krea2/style/all__ here.")], "unresolved wildcard"),
        ([matrix_row(prompt="Fetch http://private.invalid before rendering.")], "connection data"),
        ([matrix_row(api_url="private.invalid")], "unknown field"),
        ([matrix_row(seed=True)], "64-bit unsigned"),
        ([matrix_row(), matrix_row()], "duplicate test_id"),
        (
            [matrix_row(), matrix_row(test_id="PAIR0002")],
            "duplicate style_id, mode, and seed",
        ),
    ],
)
def test_load_jobs_rejects_unsafe_or_ambiguous_rows(
    tmp_path: Path, rows: list[dict[str, object]], message: str
) -> None:
    matrix = tmp_path / "matrix.jsonl"
    write_matrix(matrix, rows)
    with pytest.raises(ValueError, match=message):
        runner.load_jobs(matrix)


def test_resume_requires_matching_redacted_1024_run(tmp_path: Path) -> None:
    job = runner.validate_job(matrix_row(), 1)
    output = tmp_path / "output"
    run_dir = runner.run_dir_for(output, job)
    run_dir.mkdir(parents=True)
    (run_dir / "image_01.png").write_bytes(fake_png())
    metadata = {
        "test_id": job["test_id"],
        "style_id": job["style_id"],
        "mode": job["mode"],
        "seed": job["seed"],
        "remote": "private_comfyui",
        "resolved_prompt": job["prompt"],
        "factors": job["factors"],
        "images": ["image_01.png"],
    }
    (run_dir / "run.json").write_text(json.dumps(metadata), encoding="utf-8")

    assert runner.pending_jobs([job], output, resume=True) == []
    metadata["api_url"] = "forbidden"
    (run_dir / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden api_url"):
        runner.pending_jobs([job], output, resume=True)


def test_resume_rejects_wrong_image_dimensions(tmp_path: Path) -> None:
    job = runner.validate_job(matrix_row(), 1)
    run_dir = runner.run_dir_for(tmp_path, job)
    run_dir.mkdir(parents=True)
    (run_dir / "image_01.png").write_bytes(fake_png(512, 1024))
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "test_id": job["test_id"],
                "style_id": job["style_id"],
                "mode": job["mode"],
                "seed": job["seed"],
                "remote": "private_comfyui",
                "resolved_prompt": job["prompt"],
                "factors": job["factors"],
                "images": ["image_01.png"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dimensions"):
        runner.validate_complete_run(run_dir, job)


def test_submit_job_guards_queue_and_records_only_private_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = runner.validate_job(matrix_row(), 1)
    workflow = json.loads((ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8"))
    events: list[str] = []

    monkeypatch.setattr(runner, "require_empty_queue", lambda _url: events.append("queue"))
    monkeypatch.setattr(
        runner,
        "http_json",
        lambda url, payload: {"prompt_id": "prompt-safe"},
    )
    monkeypatch.setattr(
        runner,
        "wait_for_result",
        lambda _url, _prompt_id, _timeout: {"outputs": {"one": {"images": [{}]}}},
    )

    def download(_url: str, _record: object, output: Path, dimensions: tuple[int, int]):
        assert dimensions == (1024, 1024)
        output.mkdir(parents=True)
        image = output / "image_01.png"
        image.write_bytes(fake_png())
        return [image]

    monkeypatch.setattr(runner, "download_images", download)
    run_dir = tmp_path / "run"
    runner.submit_job("http://private.invalid", workflow, job, run_dir, timeout=5)

    assert events == ["queue", "queue"]
    raw = (run_dir / "run.json").read_text(encoding="utf-8")
    assert "private_comfyui" in raw
    assert "http://private.invalid" not in raw
    runner.validate_complete_run(run_dir, job)


def test_scorecard_and_manifest_have_complete_generic_identity(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    workflow = tmp_path / "workflow.json"
    output = tmp_path / "output"
    write_matrix(matrix, [matrix_row()])
    workflow.write_text("{}\n", encoding="utf-8")
    jobs = runner.load_jobs(matrix)

    runner.write_scorecard(output / "scorecard.csv", output, jobs)
    document = runner.manifest_document(matrix, workflow, output, jobs)
    runner.write_manifest(output / "manifest.json", document)

    with (output / "scorecard.csv").open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["test_id"] == "PAIR0001"
    assert row["mode"] == "pairwise"
    assert json.loads(row["factors_json"])["camera"] == "eye_level"
    assert document["remote"] == "private_comfyui"
    assert document["job_count"] == document["completed_count"] == 1
    assert "api_url" not in json.dumps(document)


def test_existing_scorecard_must_match_completed_matrix(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    output = tmp_path / "output"
    write_matrix(matrix, [matrix_row()])
    jobs = runner.load_jobs(matrix)
    scorecard = output / "scorecard.csv"

    runner.write_scorecard(scorecard, output, jobs)
    runner.write_scorecard(scorecard, output, jobs)
    scorecard.write_text("stale\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        runner.write_scorecard(scorecard, output, jobs)


def test_cli_defaults_to_offline_dry_run(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    write_matrix(matrix, [matrix_row()])
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_remote_prompt_matrix.py"), str(matrix)],
        cwd=ROOT,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout or result.stderr
    assert "DRY RUN complete" in result.stdout
    assert "private.invalid" not in result.stdout


def test_error_redaction_hides_remote_and_account_paths() -> None:
    private_ip = ".".join(("10", "1", "2", "3"))
    remote = "http://" + private_ip + ":8188"
    account_path = "/" + "/".join(("home", "private-user", "work"))
    redacted = runner.redact_error(
        f"failed at {remote} in {account_path}",
        remote,
    )
    assert private_ip not in redacted
    assert "private-user" not in redacted
    assert "<REDACTED_REMOTE>" in redacted
    assert "<REDACTED_HOME>" in redacted
