#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from run_remote_benchmark import (
    API_URL_ENV,
    DEFAULT_WORKFLOW,
    download_images,
    http_json,
    png_dimensions,
    prepare_workflow,
    record_path,
    require_empty_queue,
    validate_remote_nodes,
    wait_for_result,
    workflow_dimensions,
)
from run_remote_catalog_batch import METRICS


SAFE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
STYLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,179}$")
MODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WILDCARD_RE = re.compile(r"__[A-Za-z0-9][A-Za-z0-9_./-]*__")
URL_RE = re.compile(r"https?://", re.IGNORECASE)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
HOME_PATH_RE = re.compile(r"(?:/home/|/Users/)[A-Za-z0-9_.-]+")
ACCOUNT_AT_HOST_RE = re.compile(
    r"(?<![<\w])[a-z_][a-z0-9_.-]*@[a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+",
    re.IGNORECASE,
)
EXPECTED_DIMENSIONS = (1024, 1024)
RUN_STATE_NAME = "run-state.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_FIELDS = {
    "schema_version",
    "test_id",
    "style_id",
    "label",
    "mode",
    "seed",
    "prompt",
    "factors",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def _clean_label(value: Any, *, line_number: int, style_id: str) -> str:
    if value is None:
        return style_id
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\n" in value
        or "\r" in value
        or len(value) > 200
    ):
        raise ValueError(f"line {line_number}: label must be a clean non-empty line")
    if (
        URL_RE.search(value)
        or IPV4_RE.search(value)
        or HOME_PATH_RE.search(value)
        or ACCOUNT_AT_HOST_RE.search(value)
    ):
        raise ValueError(
            f"line {line_number}: label contains forbidden connection data"
        )
    return value


def _clean_factors(value: Any, *, line_number: int) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"line {line_number}: factors must be a mapping")
    factors: dict[str, str] = {}
    for key, factor in value.items():
        if not isinstance(key, str) or not MODE_RE.fullmatch(key):
            raise ValueError(f"line {line_number}: invalid factor name")
        if not isinstance(factor, str) or not STYLE_ID_RE.fullmatch(factor):
            raise ValueError(f"line {line_number}: invalid factor value for {key}")
        factors[key] = factor
    return factors


def validate_job(raw: Any, line_number: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"line {line_number}: job must be a JSON object")
    unknown = sorted(set(raw) - ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"line {line_number}: unknown field(s): {', '.join(unknown)}")
    if raw.get("schema_version", 1) != 1:
        raise ValueError(f"line {line_number}: schema_version must be 1")

    test_id = raw.get("test_id")
    style_id = raw.get("style_id")
    mode = raw.get("mode")
    seed = raw.get("seed")
    prompt = raw.get("prompt")
    if not isinstance(test_id, str) or not SAFE_ID_RE.fullmatch(test_id):
        raise ValueError(f"line {line_number}: invalid test_id")
    if not isinstance(style_id, str) or not STYLE_ID_RE.fullmatch(style_id):
        raise ValueError(f"line {line_number}: invalid style_id")
    if not isinstance(mode, str) or not MODE_RE.fullmatch(mode):
        raise ValueError(f"line {line_number}: invalid mode")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ValueError(f"line {line_number}: seed must be a 64-bit unsigned integer")
    if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
        raise ValueError(f"line {line_number}: prompt must be non-empty text")
    prompt = prompt.strip()
    if WILDCARD_RE.search(prompt):
        raise ValueError(f"line {line_number}: prompt contains an unresolved wildcard")
    if (
        URL_RE.search(prompt)
        or IPV4_RE.search(prompt)
        or HOME_PATH_RE.search(prompt)
        or ACCOUNT_AT_HOST_RE.search(prompt)
    ):
        raise ValueError(
            f"line {line_number}: prompt contains forbidden connection data"
        )

    return {
        "schema_version": 1,
        "test_id": test_id,
        "style_id": style_id,
        "label": _clean_label(
            raw.get("label"), line_number=line_number, style_id=style_id
        ),
        "mode": mode,
        "seed": seed,
        "prompt": prompt,
        "factors": _clean_factors(raw.get("factors"), line_number=line_number),
    }


def load_jobs(path: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen_test_ids: set[str] = set()
    seen_matrix_keys: set[tuple[str, str, int]] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON") from exc
        job = validate_job(raw, line_number)
        if job["test_id"] in seen_test_ids:
            raise ValueError(f"line {line_number}: duplicate test_id")
        matrix_key = (job["style_id"], job["mode"], job["seed"])
        if matrix_key in seen_matrix_keys:
            raise ValueError(f"line {line_number}: duplicate style_id, mode, and seed")
        seen_test_ids.add(job["test_id"])
        seen_matrix_keys.add(matrix_key)
        jobs.append(job)
    if not jobs:
        raise ValueError("prompt matrix contains no jobs")
    return jobs


def run_dir_for(output: Path, job: dict[str, Any]) -> Path:
    return output / "runs" / job["test_id"]


def prepared_workflow_sha256(
    workflow: dict[str, Any], job: dict[str, Any]
) -> str:
    prepared = prepare_workflow(
        workflow, job["prompt"], job["test_id"], job["seed"]
    )
    return value_sha256(prepared)


def workflow_batch_size(workflow: dict[str, Any]) -> int:
    values = [
        node["inputs"]["batch_size"]
        for node in workflow.values()
        if isinstance(node, dict)
        and isinstance(node.get("inputs"), dict)
        and "batch_size" in node["inputs"]
    ]
    if len(values) != 1:
        raise ValueError("workflow must define exactly one batch_size input")
    value = values[0]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("workflow batch_size must be a positive integer")
    return value


def validate_complete_run(
    run_dir: Path,
    job: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> None:
    metadata_path = run_dir / "run.json"
    if not metadata_path.is_file():
        raise ValueError(f"partial run lacks run.json: {record_path(run_dir)}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "test_id": job["test_id"],
        "style_id": job["style_id"],
        "mode": job["mode"],
        "seed": job["seed"],
        "remote": "private_comfyui",
        "resolved_prompt": job["prompt"],
        "factors": job["factors"],
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError(f"run metadata mismatch: {record_path(run_dir)}")
    if "api_url" in metadata:
        raise ValueError(
            f"run metadata contains forbidden api_url: {record_path(run_dir)}"
        )
    images = metadata.get("images")
    if images != ["image_01.png"]:
        raise ValueError(
            f"run must record exactly one relative image: {record_path(run_dir)}"
        )
    image_path = run_dir / images[0]
    if not image_path.is_file():
        raise ValueError(f"recorded image is missing: {record_path(run_dir)}")
    if png_dimensions(image_path.read_bytes()) != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"recorded image dimensions are invalid: {record_path(run_dir)}"
        )
    schema_version = metadata.get("schema_version", 1)
    if schema_version == 1:
        if "label" in metadata and metadata["label"] != job["label"]:
            raise ValueError(f"run metadata label mismatch: {record_path(run_dir)}")
        return
    if schema_version != 2:
        raise ValueError(f"unsupported run metadata schema: {record_path(run_dir)}")
    hash_expectations = {
        "resolved_prompt_sha256": text_sha256(job["prompt"]),
        "image_sha256": file_sha256(image_path),
    }
    if workflow is not None:
        hash_expectations["workflow_sha256"] = prepared_workflow_sha256(
            workflow, job
        )
    for key, expected_hash in hash_expectations.items():
        if metadata.get(key) != expected_hash:
            raise ValueError(
                f"run metadata {key} mismatch: {record_path(run_dir)}"
            )
    if not SHA256_RE.fullmatch(str(metadata.get("workflow_sha256", ""))):
        raise ValueError(
            f"run metadata workflow_sha256 is invalid: {record_path(run_dir)}"
        )
    if metadata.get("label") != job["label"]:
        raise ValueError(f"run metadata label mismatch: {record_path(run_dir)}")
    if metadata.get("status") != "completed":
        raise ValueError(f"run status is not completed: {record_path(run_dir)}")
    if not isinstance(metadata.get("remote_status"), str) or not metadata[
        "remote_status"
    ]:
        raise ValueError(
            f"run remote_status is missing: {record_path(run_dir)}"
        )
    queue_depth = metadata.get("queue_depth")
    if (
        isinstance(queue_depth, bool)
        or not isinstance(queue_depth, int)
        or not 1 <= queue_depth <= 256
    ):
        raise ValueError(
            f"run queue_depth provenance is invalid: {record_path(run_dir)}"
        )
    if metadata.get("batch_size") != 1:
        raise ValueError(
            f"run batch_size provenance is invalid: {record_path(run_dir)}"
        )


def pending_jobs(
    jobs: list[dict[str, Any]],
    output: Path,
    *,
    resume: bool,
    workflow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for job in jobs:
        run_dir = run_dir_for(output, job)
        if not run_dir.exists():
            pending.append(job)
        elif not resume:
            raise FileExistsError(
                f"run directory already exists: {record_path(run_dir)}"
            )
        else:
            validate_complete_run(run_dir, job, workflow=workflow)
    return pending


def run_state_path(output: Path) -> Path:
    return output / RUN_STATE_NAME


def run_state_document(
    matrix: Path,
    workflow_path: Path,
    workflow: dict[str, Any],
    jobs: list[dict[str, Any]],
    *,
    queue_depth: int,
    batch_size: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "remote_prompt_matrix_run_state",
        "remote": "private_comfyui",
        "run_id": str(uuid.uuid4()),
        "client_id": str(uuid.uuid4()),
        "matrix_sha256": file_sha256(matrix),
        "workflow_source_sha256": file_sha256(workflow_path),
        "queue_depth": queue_depth,
        "batch_size": batch_size,
        "status": "active",
        "jobs": {
            job["test_id"]: {
                "resolved_prompt_sha256": text_sha256(job["prompt"]),
                "workflow_sha256": prepared_workflow_sha256(workflow, job),
                "submission_status": "not_submitted",
                "completion_status": "pending",
            }
            for job in jobs
        },
    }


def load_or_create_run_state(
    output: Path,
    matrix: Path,
    workflow_path: Path,
    workflow: dict[str, Any],
    jobs: list[dict[str, Any]],
    *,
    queue_depth: int,
    batch_size: int = 1,
) -> tuple[dict[str, Any], bool]:
    path = run_state_path(output)
    if not path.exists():
        document = run_state_document(
            matrix,
            workflow_path,
            workflow,
            jobs,
            queue_depth=queue_depth,
            batch_size=batch_size,
        )
        atomic_write_json(path, document)
        return document, True

    document = json.loads(path.read_text(encoding="utf-8"))
    expected_top_level = {
        "schema_version": 1,
        "kind": "remote_prompt_matrix_run_state",
        "remote": "private_comfyui",
        "matrix_sha256": file_sha256(matrix),
        "workflow_source_sha256": file_sha256(workflow_path),
        "queue_depth": queue_depth,
        "batch_size": batch_size,
    }
    if any(document.get(key) != value for key, value in expected_top_level.items()):
        raise ValueError("existing run state does not match this matrix execution")
    for identifier in ("run_id", "client_id"):
        try:
            uuid.UUID(str(document.get(identifier)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"run state has invalid {identifier}") from exc
    expected_job_ids = {job["test_id"] for job in jobs}
    state_jobs = document.get("jobs")
    if not isinstance(state_jobs, dict) or set(state_jobs) != expected_job_ids:
        raise ValueError("run state job set does not match prompt matrix")
    for job in jobs:
        entry = state_jobs[job["test_id"]]
        if not isinstance(entry, dict):
            raise ValueError("run state job entry must be a mapping")
        expected_hashes = {
            "resolved_prompt_sha256": text_sha256(job["prompt"]),
            "workflow_sha256": prepared_workflow_sha256(workflow, job),
        }
        if any(entry.get(key) != value for key, value in expected_hashes.items()):
            raise ValueError(f"run state hash mismatch for {job['test_id']}")
    return document, False


def mark_state_job_completed(
    state: dict[str, Any], job: dict[str, Any], run_dir: Path
) -> None:
    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    image_path = run_dir / "image_01.png"
    entry = state["jobs"][job["test_id"]]
    entry["completion_status"] = "completed"
    entry["image_sha256"] = file_sha256(image_path)
    entry["remote_status"] = str(metadata.get("remote_status") or "legacy_complete")
    prompt_id = metadata.get("prompt_id")
    if isinstance(prompt_id, str) and prompt_id:
        existing = entry.get("prompt_id")
        if existing is not None and existing != prompt_id:
            raise ValueError("run metadata prompt identity conflicts with run state")
        entry["prompt_id"] = prompt_id
        entry["submission_status"] = "history"
    entry.pop("failure_type", None)


def _remote_prompt_parts(
    value: Any, *, fallback_prompt_id: str | None = None
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    prompt_id = fallback_prompt_id
    workflow = None
    client_id = None
    if isinstance(value, (list, tuple)):
        if len(value) > 1 and isinstance(value[1], str):
            prompt_id = value[1]
        if len(value) > 2 and isinstance(value[2], dict):
            workflow = value[2]
        extra = value[3] if len(value) > 3 else None
        if isinstance(extra, dict) and isinstance(extra.get("client_id"), str):
            client_id = extra["client_id"]
    elif isinstance(value, dict):
        if isinstance(value.get("prompt_id"), str):
            prompt_id = value["prompt_id"]
        if isinstance(value.get("prompt"), dict):
            workflow = value["prompt"]
        extra = value.get("extra_data")
        if isinstance(extra, dict) and isinstance(extra.get("client_id"), str):
            client_id = extra["client_id"]
    return prompt_id, workflow, client_id


def _history_prompt_parts(
    prompt_id: str, record: Any
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    if not isinstance(record, dict):
        return prompt_id, None, None
    prompt = record.get("prompt")
    if prompt is None:
        return _remote_prompt_parts(record, fallback_prompt_id=prompt_id)
    return _remote_prompt_parts(prompt, fallback_prompt_id=prompt_id)


def queue_prompt_parts(payload: dict[str, Any]) -> list[
    tuple[str | None, dict[str, Any] | None, str | None]
]:
    parts = []
    for key in ("queue_running", "queue_pending"):
        entries = payload.get(key, [])
        if not isinstance(entries, list):
            raise RuntimeError("remote queue returned an invalid structure")
        parts.extend(_remote_prompt_parts(entry) for entry in entries)
    return parts


def reconcile_owned_remote_jobs(
    api_url: str,
    workflow: dict[str, Any],
    jobs: list[dict[str, Any]],
    state: dict[str, Any],
    state_path: Path,
) -> None:
    expected_by_hash = {
        prepared_workflow_sha256(workflow, job): job["test_id"] for job in jobs
    }
    if len(expected_by_hash) != len(jobs):
        raise ValueError("prepared workflows are not uniquely identifiable")
    client_id = state["client_id"]
    discovered: dict[str, tuple[str, str]] = {}

    def register(test_id: str, prompt_id: str, location: str) -> None:
        prior = discovered.get(test_id)
        if prior is not None and prior[0] != prompt_id:
            raise RuntimeError("multiple owned remote prompts match one matrix job")
        discovered[test_id] = (prompt_id, location)

    queue = http_json(f"{api_url.rstrip('/')}/queue")
    for prompt_id, prepared, owner in queue_prompt_parts(queue):
        if owner != client_id:
            continue
        if prompt_id is None or prepared is None:
            raise RuntimeError("owned queued prompt lacks recoverable identity")
        workflow_hash = value_sha256(prepared)
        test_id = expected_by_hash.get(workflow_hash)
        if test_id is None:
            raise RuntimeError("owned queued prompt does not match this matrix")
        register(test_id, prompt_id, "queued")

    history = http_json(f"{api_url.rstrip('/')}/history")
    if not isinstance(history, dict):
        raise RuntimeError("remote history returned an invalid structure")
    for prompt_id, record in history.items():
        if not isinstance(prompt_id, str):
            continue
        recovered_id, prepared, owner = _history_prompt_parts(prompt_id, record)
        if owner != client_id:
            continue
        if recovered_id is None or prepared is None:
            raise RuntimeError("owned history prompt lacks recoverable identity")
        workflow_hash = value_sha256(prepared)
        test_id = expected_by_hash.get(workflow_hash)
        if test_id is None:
            raise RuntimeError("owned history prompt does not match this matrix")
        register(test_id, recovered_id, "history")

    changed = False
    for test_id, (prompt_id, location) in discovered.items():
        entry = state["jobs"][test_id]
        existing = entry.get("prompt_id")
        if existing is not None and existing != prompt_id:
            raise RuntimeError("run state prompt identity conflicts with remote history")
        if existing is None or entry.get("submission_status") != location:
            entry["prompt_id"] = prompt_id
            entry["submission_status"] = location
            changed = True
    if changed:
        atomic_write_json(state_path, state)


def unknown_external_queue_count(
    api_url: str, state: dict[str, Any]
) -> int:
    payload = http_json(f"{api_url.rstrip('/')}/queue")
    owned_ids = {
        entry.get("prompt_id")
        for entry in state["jobs"].values()
        if isinstance(entry, dict) and isinstance(entry.get("prompt_id"), str)
    }
    unknown = 0
    for prompt_id, _prepared, client_id in queue_prompt_parts(payload):
        if prompt_id in owned_ids or client_id == state["client_id"]:
            continue
        unknown += 1
    return unknown


def enqueue_job(
    api_url: str,
    workflow: dict[str, Any],
    job: dict[str, Any],
    *,
    client_id: str | None = None,
) -> tuple[str, str]:
    prepared = prepare_workflow(workflow, job["prompt"], job["test_id"], job["seed"])
    prepared_hash = value_sha256(prepared)
    result = http_json(
        f"{api_url.rstrip('/')}/prompt",
        {"prompt": prepared, "client_id": client_id or str(uuid.uuid4())},
    )
    prompt_id = result.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise RuntimeError("remote submission rejected")
    return prompt_id, prepared_hash


def enqueue_and_journal(
    api_url: str,
    workflow: dict[str, Any],
    job: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
) -> str:
    prompt_id, workflow_hash = enqueue_job(
        api_url,
        workflow,
        job,
        client_id=state["client_id"],
    )
    entry = state["jobs"][job["test_id"]]
    if workflow_hash != entry["workflow_sha256"]:
        raise RuntimeError("prepared workflow changed during submission")
    entry["prompt_id"] = prompt_id
    entry["submission_status"] = "queued"
    entry["completion_status"] = "pending"
    atomic_write_json(state_path, state)
    return prompt_id


def collect_job(
    api_url: str,
    prompt_id: str,
    job: dict[str, Any],
    run_dir: Path,
    *,
    timeout: int,
    queue_depth: int,
    batch_size: int,
    workflow_sha256: str,
) -> None:
    remote_record = wait_for_result(api_url, prompt_id, timeout)
    images = download_images(api_url, remote_record, run_dir, EXPECTED_DIMENSIONS)
    if [path.name for path in images] != ["image_01.png"]:
        raise RuntimeError("remote result did not produce the expected local image")
    metadata = {
        "schema_version": 2,
        "test_id": job["test_id"],
        "style_id": job["style_id"],
        "label": job["label"],
        "mode": job["mode"],
        "seed": job["seed"],
        "remote": "private_comfyui",
        "prompt_id": prompt_id,
        "resolved_prompt": job["prompt"],
        "resolved_prompt_sha256": text_sha256(job["prompt"]),
        "workflow_sha256": workflow_sha256,
        "factors": job["factors"],
        "images": ["image_01.png"],
        "image_sha256": file_sha256(images[0]),
        "queue_depth": queue_depth,
        "batch_size": batch_size,
        "status": "completed",
        "remote_status": str(
            remote_record.get("status", {}).get("status_str") or "success"
        ),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_dir / "run.json", metadata)


def submit_job(
    api_url: str,
    workflow: dict[str, Any],
    job: dict[str, Any],
    run_dir: Path,
    *,
    timeout: int,
) -> None:
    require_empty_queue(api_url)
    prompt_id, workflow_hash = enqueue_job(api_url, workflow, job)
    collect_job(
        api_url,
        prompt_id,
        job,
        run_dir,
        timeout=timeout,
        queue_depth=1,
        batch_size=1,
        workflow_sha256=workflow_hash,
    )
    require_empty_queue(api_url)


def run_pending_jobs(
    api_url: str,
    workflow: dict[str, Any],
    pending: list[dict[str, Any]],
    output: Path,
    *,
    timeout: int,
    queue_depth: int,
    state: dict[str, Any] | None = None,
    state_path: Path | None = None,
) -> None:
    if queue_depth == 1:
        for index, job in enumerate(pending, start=1):
            print(
                f"[{index}/{len(pending)}] {job['test_id']} "
                f"style={job['style_id']} mode={job['mode']} seed={job['seed']}",
                flush=True,
            )
            submit_job(
                api_url,
                workflow,
                job,
                run_dir_for(output, job),
                timeout=timeout,
            )
        return

    if state is None or state_path is None:
        raise ValueError("queue depth greater than 1 requires durable run state")

    active: list[tuple[dict[str, Any], str]] = []
    waiting: list[dict[str, Any]] = []
    for job in pending:
        prompt_id = state["jobs"][job["test_id"]].get("prompt_id")
        if isinstance(prompt_id, str):
            active.append((job, prompt_id))
        else:
            waiting.append(job)
    submitted = len(active)
    completed = 0
    failures: list[str] = []
    halt_new_submissions = False
    while waiting or active:
        while waiting and len(active) < queue_depth and not halt_new_submissions:
            external_count = unknown_external_queue_count(api_url, state)
            if external_count:
                failures.append(
                    f"detected {external_count} unknown external queue job(s)"
                )
                halt_new_submissions = True
                break
            job = waiting.pop(0)
            prompt_id = enqueue_and_journal(
                api_url, workflow, job, state, state_path
            )
            active.append((job, prompt_id))
            submitted += 1
            print(
                f"[queued {submitted}/{len(pending)} depth={len(active)}] "
                f"{job['test_id']} style={job['style_id']} "
                f"mode={job['mode']} seed={job['seed']}",
                flush=True,
            )
        if not active:
            break
        job, prompt_id = active.pop(0)
        entry = state["jobs"][job["test_id"]]
        try:
            collect_job(
                api_url,
                prompt_id,
                job,
                run_dir_for(output, job),
                timeout=timeout,
                queue_depth=queue_depth,
                batch_size=1,
                workflow_sha256=entry["workflow_sha256"],
            )
        except (
            OSError,
            TypeError,
            ValueError,
            RuntimeError,
            TimeoutError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ) as exc:
            entry["completion_status"] = "failed"
            entry["failure_type"] = type(exc).__name__
            atomic_write_json(state_path, state)
            failures.append(f"{job['test_id']} failed ({type(exc).__name__})")
            halt_new_submissions = True
        else:
            mark_state_job_completed(
                state, job, run_dir_for(output, job)
            )
            atomic_write_json(state_path, state)
            completed += 1
            print(
                f"[completed {completed}/{len(pending)} queued={len(active)}] "
                f"{job['test_id']}",
                flush=True,
            )
    if failures:
        raise RuntimeError(
            "batch halted after preserving available owned results: "
            + "; ".join(failures)
        )
    if waiting:
        raise RuntimeError("batch halted before all pending jobs were submitted")


def scorecard_content(output: Path, jobs: list[dict[str, Any]]) -> str:
    fields = [
        "test_id",
        "seed",
        "style_id",
        "label",
        "mode",
        "factors_json",
        "image_path",
        *METRICS,
        "notes",
    ]
    from io import StringIO

    handle = StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for job in jobs:
        image_path = run_dir_for(output, job) / "image_01.png"
        writer.writerow(
            {
                "test_id": job["test_id"],
                "seed": job["seed"],
                "style_id": job["style_id"],
                "label": job["label"],
                "mode": job["mode"],
                "factors_json": json.dumps(job["factors"], sort_keys=True),
                "image_path": record_path(image_path),
            }
        )
    return handle.getvalue()


def write_scorecard(path: Path, output: Path, jobs: list[dict[str, Any]]) -> None:
    content = scorecard_content(output, jobs)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError("existing scorecard does not match the completed matrix")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def manifest_document(
    matrix: Path,
    workflow_path: Path,
    output: Path,
    jobs: list[dict[str, Any]],
    *,
    queue_depth: int = 1,
    batch_size: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "resolved_prompt_matrix_run",
        "remote": "private_comfyui",
        "matrix": record_path(matrix),
        "matrix_sha256": file_sha256(matrix),
        "workflow": record_path(workflow_path),
        "workflow_sha256": file_sha256(workflow_path),
        "dimensions": list(EXPECTED_DIMENSIONS),
        "queue_depth": queue_depth,
        "batch_size": batch_size,
        "job_count": len(jobs),
        "completed_count": len(jobs),
        "style_count": len({job["style_id"] for job in jobs}),
        "modes": dict(sorted(Counter(job["mode"] for job in jobs).items())),
        "seeds": sorted({job["seed"] for job in jobs}),
        "scorecard": record_path(output / "scorecard.csv"),
        "runs": [
            {
                "test_id": job["test_id"],
                "style_id": job["style_id"],
                "mode": job["mode"],
                "seed": job["seed"],
                "run": record_path(run_dir_for(output, job) / "run.json"),
            }
            for job in jobs
        ],
    }


def write_manifest(path: Path, document: dict[str, Any]) -> None:
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != document:
            raise ValueError("existing manifest does not match the completed matrix")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def redact_error(message: str, api_url: str | None) -> str:
    if api_url:
        message = message.replace(api_url, "<REDACTED_REMOTE>")
    message = HOME_PATH_RE.sub("<REDACTED_HOME>", message)
    message = ACCOUNT_AT_HOST_RE.sub("<REDACTED_ACCOUNT>", message)
    message = IPV4_RE.sub("<REDACTED_IP>", message)
    return message


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a fully resolved prompt JSONL matrix on private ComfyUI"
    )
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--queue-depth",
        type=int,
        default=1,
        help="maximum number of this matrix's jobs queued after an empty-queue preflight",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="expected workflow batch size; prompt-matrix evidence requires exactly 1",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    api_url = os.environ.get(API_URL_ENV)
    try:
        jobs = load_jobs(args.matrix)
        workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
        dimensions = workflow_dimensions(workflow)
        if dimensions != EXPECTED_DIMENSIONS:
            raise ValueError(
                f"workflow dimensions must be {EXPECTED_DIMENSIONS[0]}x{EXPECTED_DIMENSIONS[1]}"
            )
        actual_batch_size = workflow_batch_size(workflow)
        if args.batch_size != 1 or actual_batch_size != args.batch_size:
            raise ValueError(
                "prompt-matrix evidence requires --batch-size 1 and a workflow batch_size of 1"
            )
        for job in jobs:
            prepare_workflow(workflow, job["prompt"], job["test_id"], job["seed"])
        modes = ", ".join(
            f"{key}={value}"
            for key, value in sorted(Counter(job["mode"] for job in jobs).items())
        )
        print(
            f"Prompt matrix: {len(jobs)} job(s), "
            f"{len({job['style_id'] for job in jobs})} style(s), modes[{modes}]"
        )
        if not args.submit:
            print(
                "DRY RUN complete. Re-run with --submit and --output to execute remotely."
            )
            return 0
        if args.output is None:
            raise ValueError("--output is required with --submit")
        if args.timeout < 1:
            raise ValueError("--timeout must be at least 1 second")
        if not 1 <= args.queue_depth <= 256:
            raise ValueError("--queue-depth must be between 1 and 256")

        pending = pending_jobs(
            jobs,
            args.output,
            resume=args.resume,
            workflow=workflow,
        )
        print(
            f"Resume preflight: complete={len(jobs) - len(pending)} pending={len(pending)}"
        )
        if not pending:
            for job in jobs:
                validate_complete_run(
                    run_dir_for(args.output, job), job, workflow=workflow
                )
            write_scorecard(args.output / "scorecard.csv", args.output, jobs)
            manifest_path = args.output / "manifest.json"
            manifest_queue_depth = args.queue_depth
            if manifest_path.exists():
                prior_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                prior_depth = prior_manifest.get("queue_depth", 1)
                if (
                    not isinstance(prior_depth, int)
                    or isinstance(prior_depth, bool)
                    or not 1 <= prior_depth <= 256
                ):
                    raise ValueError("existing manifest has invalid queue_depth")
                manifest_queue_depth = prior_depth
                if "queue_depth" not in prior_manifest:
                    prior_manifest["queue_depth"] = prior_depth
                prior_batch_size = prior_manifest.get("batch_size", 1)
                if prior_batch_size != 1:
                    raise ValueError("existing manifest has invalid batch_size")
                if "batch_size" not in prior_manifest:
                    prior_manifest["batch_size"] = 1
                atomic_write_json(manifest_path, prior_manifest)
            write_manifest(
                manifest_path,
                manifest_document(
                    args.matrix,
                    args.workflow,
                    args.output,
                    jobs,
                    queue_depth=manifest_queue_depth,
                    batch_size=args.batch_size,
                ),
            )
            completed_state_path = run_state_path(args.output)
            if completed_state_path.exists():
                completed_state_header = json.loads(
                    completed_state_path.read_text(encoding="utf-8")
                )
                completed_state_depth = completed_state_header.get("queue_depth")
                if (
                    isinstance(completed_state_depth, bool)
                    or not isinstance(completed_state_depth, int)
                    or not 1 <= completed_state_depth <= 256
                ):
                    raise ValueError("existing run state has invalid queue_depth")
                completed_state, _created = load_or_create_run_state(
                    args.output,
                    args.matrix,
                    args.workflow,
                    workflow,
                    jobs,
                    queue_depth=completed_state_depth,
                    batch_size=args.batch_size,
                )
                for job in jobs:
                    mark_state_job_completed(
                        completed_state, job, run_dir_for(args.output, job)
                    )
                completed_state["status"] = "completed"
                atomic_write_json(completed_state_path, completed_state)
            print(
                f"Matrix already complete: {len(jobs)} verified 1024x1024 PNG run(s)."
            )
            return 0
        if not api_url:
            raise ValueError(f"set {API_URL_ENV} before --submit")
        prepared = prepare_workflow(
            workflow, jobs[0]["prompt"], jobs[0]["test_id"], jobs[0]["seed"]
        )
        validate_remote_nodes(api_url, prepared)
        state = None
        state_path = None
        state_created = False
        if args.queue_depth > 1:
            state_path = run_state_path(args.output)
            state, state_created = load_or_create_run_state(
                args.output,
                args.matrix,
                args.workflow,
                workflow,
                jobs,
                queue_depth=args.queue_depth,
                batch_size=args.batch_size,
            )
            pending_ids = {job["test_id"] for job in pending}
            for job in jobs:
                if job["test_id"] not in pending_ids:
                    mark_state_job_completed(
                        state, job, run_dir_for(args.output, job)
                    )
            atomic_write_json(state_path, state)
            if state_created:
                require_empty_queue(api_url)
            else:
                reconcile_owned_remote_jobs(
                    api_url, workflow, jobs, state, state_path
                )
        else:
            require_empty_queue(api_url)
        run_pending_jobs(
            api_url,
            workflow,
            pending,
            args.output,
            timeout=args.timeout,
            queue_depth=args.queue_depth,
            state=state,
            state_path=state_path,
        )
        for job in jobs:
            validate_complete_run(
                run_dir_for(args.output, job), job, workflow=workflow
            )
        if state is not None and state_path is not None:
            state["status"] = "completed"
            atomic_write_json(state_path, state)
        require_empty_queue(api_url)
        write_scorecard(args.output / "scorecard.csv", args.output, jobs)
        write_manifest(
            args.output / "manifest.json",
            manifest_document(
                args.matrix,
                args.workflow,
                args.output,
                jobs,
                queue_depth=args.queue_depth,
                batch_size=args.batch_size,
            ),
        )
        print(f"Matrix completed: {len(jobs)} verified 1024x1024 PNG run(s).")
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {redact_error(str(exc), api_url)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
