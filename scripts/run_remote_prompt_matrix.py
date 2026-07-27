#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
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


def validate_complete_run(run_dir: Path, job: dict[str, Any]) -> None:
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


def pending_jobs(
    jobs: list[dict[str, Any]], output: Path, *, resume: bool
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
            validate_complete_run(run_dir, job)
    return pending


def submit_job(
    api_url: str,
    workflow: dict[str, Any],
    job: dict[str, Any],
    run_dir: Path,
    *,
    timeout: int,
) -> None:
    require_empty_queue(api_url)
    prompt_id = enqueue_job(api_url, workflow, job)
    collect_job(
        api_url,
        prompt_id,
        job,
        run_dir,
        timeout=timeout,
        queue_depth=1,
    )
    require_empty_queue(api_url)


def enqueue_job(
    api_url: str,
    workflow: dict[str, Any],
    job: dict[str, Any],
) -> str:
    prepared = prepare_workflow(workflow, job["prompt"], job["test_id"], job["seed"])
    result = http_json(
        f"{api_url.rstrip('/')}/prompt",
        {"prompt": prepared, "client_id": str(uuid.uuid4())},
    )
    prompt_id = result.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise RuntimeError("remote submission rejected")
    return prompt_id


def collect_job(
    api_url: str,
    prompt_id: str,
    job: dict[str, Any],
    run_dir: Path,
    *,
    timeout: int,
    queue_depth: int,
) -> None:
    remote_record = wait_for_result(api_url, prompt_id, timeout)
    images = download_images(api_url, remote_record, run_dir, EXPECTED_DIMENSIONS)
    if [path.name for path in images] != ["image_01.png"]:
        raise RuntimeError("remote result did not produce the expected local image")
    metadata = {
        "schema_version": 1,
        "test_id": job["test_id"],
        "style_id": job["style_id"],
        "label": job["label"],
        "mode": job["mode"],
        "seed": job["seed"],
        "remote": "private_comfyui",
        "prompt_id": prompt_id,
        "resolved_prompt": job["prompt"],
        "factors": job["factors"],
        "images": ["image_01.png"],
        "queue_depth": queue_depth,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_pending_jobs(
    api_url: str,
    workflow: dict[str, Any],
    pending: list[dict[str, Any]],
    output: Path,
    *,
    timeout: int,
    queue_depth: int,
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

    active: list[tuple[dict[str, Any], str]] = []
    submitted = 0
    completed = 0
    while submitted < len(pending) or active:
        while submitted < len(pending) and len(active) < queue_depth:
            job = pending[submitted]
            prompt_id = enqueue_job(api_url, workflow, job)
            active.append((job, prompt_id))
            submitted += 1
            print(
                f"[queued {submitted}/{len(pending)} depth={len(active)}] "
                f"{job['test_id']} style={job['style_id']} "
                f"mode={job['mode']} seed={job['seed']}",
                flush=True,
            )
        job, prompt_id = active.pop(0)
        collect_job(
            api_url,
            prompt_id,
            job,
            run_dir_for(output, job),
            timeout=timeout,
            queue_depth=queue_depth,
        )
        completed += 1
        print(
            f"[completed {completed}/{len(pending)} queued={len(active)}] "
            f"{job['test_id']}",
            flush=True,
        )


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
        if not api_url:
            raise ValueError(f"set {API_URL_ENV} before --submit")
        if args.timeout < 1:
            raise ValueError("--timeout must be at least 1 second")
        if not 1 <= args.queue_depth <= 256:
            raise ValueError("--queue-depth must be between 1 and 256")

        pending = pending_jobs(jobs, args.output, resume=args.resume)
        print(
            f"Resume preflight: complete={len(jobs) - len(pending)} pending={len(pending)}"
        )
        prepared = prepare_workflow(
            workflow, jobs[0]["prompt"], jobs[0]["test_id"], jobs[0]["seed"]
        )
        validate_remote_nodes(api_url, prepared)
        require_empty_queue(api_url)
        run_pending_jobs(
            api_url,
            workflow,
            pending,
            args.output,
            timeout=args.timeout,
            queue_depth=args.queue_depth,
        )
        require_empty_queue(api_url)
        for job in jobs:
            validate_complete_run(run_dir_for(args.output, job), job)
        write_scorecard(args.output / "scorecard.csv", args.output, jobs)
        write_manifest(
            args.output / "manifest.json",
            manifest_document(
                args.matrix,
                args.workflow,
                args.output,
                jobs,
                queue_depth=args.queue_depth,
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
