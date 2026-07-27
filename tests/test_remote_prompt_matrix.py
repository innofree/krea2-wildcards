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
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


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
        (
            [matrix_row(prompt="Fetch http://private.invalid before rendering.")],
            "connection data",
        ),
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


def test_load_jobs_rejects_raw_ipv4_in_persisted_label(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    private_ip = ".".join(("10", "20", "30", "40"))
    write_matrix(matrix, [matrix_row(label=f"server {private_ip}")])
    with pytest.raises(ValueError, match="connection data"):
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
    workflow = json.loads(
        (ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8")
    )
    events: list[str] = []

    monkeypatch.setattr(
        runner, "require_empty_queue", lambda _url: events.append("queue")
    )
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
    assert json.loads(raw)["queue_depth"] == 1
    runner.validate_complete_run(run_dir, job)


def test_queue_depth_fills_then_collects_in_submission_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = [
        runner.validate_job(
            matrix_row(
                test_id=f"PAIR{index:04d}",
                style_id=f"pairwise_{index}",
                seed=1000 + index,
            ),
            index,
        )
        for index in range(1, 6)
    ]
    events: list[str] = []

    def enqueue(
        _url: str,
        _workflow: object,
        job: dict[str, object],
        _state: dict[str, object],
        _state_path: Path,
    ) -> str:
        events.append(f"queue:{job['test_id']}")
        return f"prompt-{job['test_id']}"

    def collect(
        _url: str,
        _prompt_id: str,
        job: dict[str, object],
        _run_dir: Path,
        *,
        timeout: int,
        queue_depth: int,
        batch_size: int,
        workflow_sha256: str,
    ) -> None:
        assert timeout == 10
        assert queue_depth == 2
        assert batch_size == 1
        assert workflow_sha256 == "a" * 64
        events.append(f"collect:{job['test_id']}")

    monkeypatch.setattr(runner, "enqueue_and_journal", enqueue)
    monkeypatch.setattr(runner, "collect_job", collect)
    monkeypatch.setattr(runner, "unknown_external_queue_count", lambda *_args: 0)
    monkeypatch.setattr(
        runner,
        "mark_state_job_completed",
        lambda state, job, _run_dir: state["jobs"][job["test_id"]].update(
            {"completion_status": "completed"}
        ),
    )
    state = {
        "client_id": "client",
        "jobs": {
            job["test_id"]: {
                "workflow_sha256": "a" * 64,
                "completion_status": "pending",
            }
            for job in jobs
        },
    }

    runner.run_pending_jobs(
        "http://private.invalid",
        {},
        jobs,
        tmp_path,
        timeout=10,
        queue_depth=2,
        state=state,
        state_path=tmp_path / "run-state.json",
    )

    assert events == [
        "queue:PAIR0001",
        "queue:PAIR0002",
        "collect:PAIR0001",
        "queue:PAIR0003",
        "collect:PAIR0002",
        "queue:PAIR0004",
        "collect:PAIR0003",
        "queue:PAIR0005",
        "collect:PAIR0004",
        "collect:PAIR0005",
    ]


def test_enqueue_journal_uses_stable_client_and_durable_prompt_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = [
        runner.validate_job(
            matrix_row(
                test_id=f"PAIR{index:04d}",
                style_id=f"pairwise_{index}",
                seed=1000 + index,
            ),
            index,
        )
        for index in range(1, 3)
    ]
    workflow = json.loads(
        (ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8")
    )
    state = {
        "client_id": "stable-client",
        "jobs": {
            job["test_id"]: {
                "workflow_sha256": runner.prepared_workflow_sha256(workflow, job),
                "completion_status": "pending",
            }
            for job in jobs
        },
    }
    state_path = tmp_path / "run-state.json"
    payloads: list[dict[str, object]] = []

    def post(_url: str, payload: dict[str, object]) -> dict[str, str]:
        payloads.append(payload)
        return {"prompt_id": f"prompt-{len(payloads)}"}

    monkeypatch.setattr(runner, "http_json", post)

    for job in jobs:
        runner.enqueue_and_journal(
            "http://private.invalid", workflow, job, state, state_path
        )

    assert [payload["client_id"] for payload in payloads] == [
        "stable-client",
        "stable-client",
    ]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["jobs"]["PAIR0001"]["prompt_id"] == "prompt-1"
    assert persisted["jobs"]["PAIR0002"]["prompt_id"] == "prompt-2"
    assert not list(tmp_path.glob("*.tmp"))


def test_resume_reconciles_unjournaled_owned_history_without_resubmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = runner.validate_job(matrix_row(), 1)
    workflow = json.loads(
        (ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8")
    )
    prepared = runner.prepare_workflow(
        workflow, job["prompt"], job["test_id"], job["seed"]
    )
    state = {
        "client_id": "stable-client",
        "jobs": {
            job["test_id"]: {
                "workflow_sha256": runner.value_sha256(prepared),
                "submission_status": "not_submitted",
                "completion_status": "pending",
            }
        },
    }
    state_path = tmp_path / "run-state.json"

    def get(url: str, _payload: object = None) -> dict[str, object]:
        if url.endswith("/queue"):
            return {"queue_running": [], "queue_pending": []}
        if url.endswith("/history"):
            return {
                "recovered-prompt": {
                    "prompt": [
                        1,
                        "recovered-prompt",
                        prepared,
                        {"client_id": "stable-client"},
                        ["9"],
                    ],
                    "outputs": {"9": {"images": [{}]}},
                }
            }
        raise AssertionError(url)

    monkeypatch.setattr(runner, "http_json", get)
    runner.reconcile_owned_remote_jobs(
        "http://private.invalid", workflow, [job], state, state_path
    )

    assert state["jobs"][job["test_id"]]["prompt_id"] == "recovered-prompt"
    assert state["jobs"][job["test_id"]]["submission_status"] == "history"
    assert (
        json.loads(state_path.read_text(encoding="utf-8"))["jobs"][job["test_id"]][
            "prompt_id"
        ]
        == "recovered-prompt"
    )


def test_external_queue_halts_refill_but_harvests_owned_active_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = [
        runner.validate_job(
            matrix_row(
                test_id=f"PAIR{index:04d}",
                style_id=f"pairwise_{index}",
                seed=1000 + index,
            ),
            index,
        )
        for index in range(1, 3)
    ]
    state = {
        "client_id": "stable-client",
        "jobs": {
            jobs[0]["test_id"]: {
                "prompt_id": "owned-active",
                "workflow_sha256": "a" * 64,
                "completion_status": "pending",
            },
            jobs[1]["test_id"]: {
                "workflow_sha256": "b" * 64,
                "completion_status": "pending",
            },
        },
    }
    events: list[str] = []
    monkeypatch.setattr(runner, "unknown_external_queue_count", lambda *_args: 1)
    monkeypatch.setattr(
        runner,
        "enqueue_and_journal",
        lambda *_args: pytest.fail("external queue must prevent refill"),
    )

    def collect(
        _url: str,
        _prompt_id: str,
        job: dict[str, object],
        _run_dir: Path,
        **_kwargs: object,
    ) -> None:
        events.append(f"collect:{job['test_id']}")

    monkeypatch.setattr(runner, "collect_job", collect)
    monkeypatch.setattr(
        runner,
        "mark_state_job_completed",
        lambda current_state, job, _run_dir: current_state["jobs"][
            job["test_id"]
        ].update({"completion_status": "completed"}),
    )

    with pytest.raises(RuntimeError, match="unknown external queue"):
        runner.run_pending_jobs(
            "http://private.invalid",
            {},
            jobs,
            tmp_path,
            timeout=10,
            queue_depth=2,
            state=state,
            state_path=tmp_path / "run-state.json",
        )
    assert events == ["collect:PAIR0001"]
    assert state["jobs"]["PAIR0001"]["completion_status"] == "completed"


def test_collection_failure_isolated_and_other_owned_result_harvested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = [
        runner.validate_job(
            matrix_row(
                test_id=f"PAIR{index:04d}",
                style_id=f"pairwise_{index}",
                seed=1000 + index,
            ),
            index,
        )
        for index in range(1, 4)
    ]
    state = {
        "client_id": "stable-client",
        "jobs": {
            job["test_id"]: {
                **(
                    {"prompt_id": f"prompt-{job['test_id']}"}
                    if index < 2
                    else {}
                ),
                "workflow_sha256": "a" * 64,
                "completion_status": "pending",
            }
            for index, job in enumerate(jobs)
        },
    }
    events: list[str] = []
    monkeypatch.setattr(runner, "unknown_external_queue_count", lambda *_args: 0)

    def collect(
        _url: str,
        _prompt_id: str,
        job: dict[str, object],
        _run_dir: Path,
        **_kwargs: object,
    ) -> None:
        events.append(f"collect:{job['test_id']}")
        if job["test_id"] == "PAIR0001":
            raise RuntimeError("remote failed")

    monkeypatch.setattr(runner, "collect_job", collect)
    monkeypatch.setattr(
        runner,
        "mark_state_job_completed",
        lambda current_state, job, _run_dir: current_state["jobs"][
            job["test_id"]
        ].update({"completion_status": "completed"}),
    )
    monkeypatch.setattr(
        runner,
        "enqueue_and_journal",
        lambda *_args: pytest.fail("failure must stop new submissions"),
    )

    with pytest.raises(RuntimeError, match="preserving available owned results"):
        runner.run_pending_jobs(
            "http://private.invalid",
            {},
            jobs,
            tmp_path,
            timeout=10,
            queue_depth=2,
            state=state,
            state_path=tmp_path / "run-state.json",
        )
    assert events == ["collect:PAIR0001", "collect:PAIR0002"]
    assert state["jobs"]["PAIR0001"]["completion_status"] == "failed"
    assert state["jobs"]["PAIR0002"]["completion_status"] == "completed"
    assert state["jobs"]["PAIR0003"]["completion_status"] == "pending"


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
    assert document["queue_depth"] == 1
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


def test_schema_two_run_verifies_prompt_workflow_image_status_and_depth_hashes(
    tmp_path: Path,
) -> None:
    job = runner.validate_job(matrix_row(), 1)
    workflow = json.loads(
        (ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8")
    )
    run_dir = runner.run_dir_for(tmp_path, job)
    run_dir.mkdir(parents=True)
    image_path = run_dir / "image_01.png"
    image_path.write_bytes(fake_png())
    metadata = {
        "schema_version": 2,
        "test_id": job["test_id"],
        "style_id": job["style_id"],
        "label": job["label"],
        "mode": job["mode"],
        "seed": job["seed"],
        "remote": "private_comfyui",
        "resolved_prompt": job["prompt"],
        "resolved_prompt_sha256": runner.text_sha256(job["prompt"]),
        "workflow_sha256": runner.prepared_workflow_sha256(workflow, job),
        "factors": job["factors"],
        "images": ["image_01.png"],
        "image_sha256": runner.file_sha256(image_path),
        "queue_depth": 32,
        "batch_size": 1,
        "status": "completed",
        "remote_status": "success",
    }
    (run_dir / "run.json").write_text(json.dumps(metadata), encoding="utf-8")

    runner.validate_complete_run(run_dir, job, workflow=workflow)
    metadata["image_sha256"] = "0" * 64
    (run_dir / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="image_sha256 mismatch"):
        runner.validate_complete_run(run_dir, job, workflow=workflow)


@pytest.mark.parametrize(
    ("prior_queue_depth", "expected_queue_depth"),
    [(7, 7), (None, 1)],
)
def test_completed_resume_is_offline_noop_and_preserves_queue_depth_provenance(
    tmp_path: Path,
    prior_queue_depth: int | None,
    expected_queue_depth: int,
) -> None:
    matrix = tmp_path / "matrix.jsonl"
    output = tmp_path / "output"
    write_matrix(matrix, [matrix_row()])
    job = runner.load_jobs(matrix)[0]
    run_dir = runner.run_dir_for(output, job)
    run_dir.mkdir(parents=True)
    (run_dir / "image_01.png").write_bytes(fake_png())
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
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
    runner.write_scorecard(output / "scorecard.csv", output, [job])
    manifest = runner.manifest_document(
        matrix,
        ROOT / "tests/baseline/workflow.json",
        output,
        [job],
        queue_depth=prior_queue_depth or 1,
    )
    if prior_queue_depth is None:
        manifest.pop("queue_depth")
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_remote_prompt_matrix.py"),
            str(matrix),
            "--submit",
            "--resume",
            "--output",
            str(output),
            "--queue-depth",
            "32",
        ],
        cwd=ROOT,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout or result.stderr
    assert "Matrix already complete" in result.stdout
    assert json.loads(
        (output / "manifest.json").read_text(encoding="utf-8")
    )["queue_depth"] == expected_queue_depth


def test_cli_defaults_to_offline_dry_run(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    write_matrix(matrix, [matrix_row()])
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_remote_prompt_matrix.py"),
            str(matrix),
        ],
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
