#!/usr/bin/env python3
"""Spread one prompt matrix across several ComfyUI endpoints, then merge the run.

run_remote_prompt_matrix.py takes one endpoint from the environment and does an
empty-queue preflight, so a single invocation owns a single box for the whole run.
That is the right contract -- the preflight is what makes a run's provenance
trustworthy -- but it means a 900-image axis takes as long as the slowest thing in
the queue even when other GPUs sit idle.

This shards the matrix, runs one unmodified child process per endpoint against its
own output directory, and merges the results into the layout every downstream tool
already expects: one runs/ tree, one scorecard.csv, one run-state.json. Nothing
here reimplements submission, download, or verification; each shard is the real
runner with its own KREA2_COMFY_API_URL.

Shards are interleaved rather than chunked, so a shard is never a contiguous block
of near-identical catalog items -- the same reason contact sheets stride.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

RUNNER = Path(__file__).resolve().parent / "run_remote_prompt_matrix.py"


def load_matrix(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError(f"matrix has no rows: {path}")
    return rows


def parse_weights(raw: str | None, count: int) -> list[float]:
    if not raw:
        return [1.0] * count
    weights = [float(part) for part in raw.split(",")]
    if len(weights) != count:
        raise ValueError(f"--weights needs {count} comma-separated values")
    if any(w <= 0 for w in weights):
        raise ValueError("--weights must all be positive")
    return weights


def shard(rows: list[dict[str, Any]], weights: list[float]) -> list[list[dict[str, Any]]]:
    """Interleave rows across shards in proportion to weight.

    Deterministic and stateless: shard membership depends only on row order and the
    weights, so a rerun with the same arguments reproduces the same split and
    --resume still works per shard.
    """
    total = sum(weights)
    quota = [w / total for w in weights]
    buckets: list[list[dict[str, Any]]] = [[] for _ in weights]
    credit = [0.0] * len(weights)
    for row in rows:
        for index, share in enumerate(quota):
            credit[index] += share
        target = max(range(len(credit)), key=lambda i: credit[i])
        buckets[target].append(row)
        credit[target] -= 1.0
    empty = [i for i, bucket in enumerate(buckets) if not bucket]
    if empty:
        raise ValueError(f"weights left shard(s) {empty} with no work")
    return buckets


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_shard_workflows(raw: list[str] | None, count: int) -> list[Path | None]:
    """--shard-workflow overrides --workflow per shard, e.g. for a checkpoint that
    only exists on some endpoints. Positional: same order as --api-url. A shard
    left unspecified (fewer entries than endpoints) falls back to --workflow."""
    if not raw:
        return [None] * count
    if len(raw) > count:
        raise ValueError(f"--shard-workflow given {len(raw)} time(s) but only {count} endpoint(s)")
    paths: list[Path | None] = [Path(p) if p else None for p in raw]
    paths += [None] * (count - len(paths))
    return paths


def launch(
    matrix: Path,
    output: Path,
    api_url: str,
    *,
    workflow: Path | None,
    queue_depth: int,
    resume: bool,
    submit: bool,
) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        str(RUNNER),
        str(matrix),
        "--output",
        str(output),
        "--batch-size",
        "1",
        "--queue-depth",
        str(queue_depth),
    ]
    if workflow is not None:
        command += ["--workflow", str(workflow)]
    if resume:
        command.append("--resume")
    if submit:
        command.append("--submit")
    environment = dict(os.environ, KREA2_COMFY_API_URL=api_url)
    return subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def merge(output: Path, shard_dirs: list[Path]) -> dict[str, Any]:
    """Fold the shard directories into the single-run layout, then delete them."""
    runs = output / "runs"
    runs.mkdir(parents=True, exist_ok=True)

    scorecard_rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    jobs: dict[str, Any] = {}
    state_header: dict[str, Any] | None = None

    for shard_dir in shard_dirs:
        state_path = shard_dir / "run-state.json"
        if not state_path.is_file():
            raise ValueError(f"shard produced no run-state.json: {shard_dir}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        shard_jobs = state.get("jobs")
        if not isinstance(shard_jobs, dict) or not shard_jobs:
            raise ValueError(f"shard run-state has no jobs: {state_path}")
        collision = set(jobs) & set(shard_jobs)
        if collision:
            raise ValueError(f"shards share test id(s): {sorted(collision)[:5]}")
        jobs.update(shard_jobs)
        if state_header is None:
            state_header = {k: v for k, v in state.items() if k != "jobs"}

        card_path = shard_dir / "scorecard.csv"
        if not card_path.is_file():
            raise ValueError(f"shard produced no scorecard.csv: {shard_dir}")
        with card_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = fieldnames or list(reader.fieldnames or [])
            for row in reader:
                # Rewrite the shard-local image path to the merged layout.
                row["image_path"] = (
                    row["image_path"]
                    .replace(f"{shard_dir.as_posix()}/runs/", f"{runs.as_posix()}/")
                )
                scorecard_rows.append(row)

        for run_dir in sorted((shard_dir / "runs").iterdir()):
            if not run_dir.is_dir():
                continue
            destination = runs / run_dir.name
            if destination.exists():
                raise ValueError(f"merged run directory already exists: {destination}")
            shutil.move(str(run_dir), str(destination))

    if fieldnames is None or state_header is None:
        raise ValueError("no shard produced any output")

    scorecard_rows.sort(key=lambda row: row["test_id"])
    with (output / "scorecard.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(scorecard_rows)

    # matrix_sha256, run_id and workflow_source_sha256 describe one shard, so they
    # would misdescribe the merge -- especially workflow_source_sha256 when shards
    # ran different checkpoints on purpose (e.g. an Int8 variant on a GPU that
    # lacks the primary Mxfp8 file). Stage A reads only `jobs`, and each job's own
    # `workflow_sha256` is already correct per shard, so nothing downstream loses
    # provenance; the honest thing at the header level is to say what this is.
    state_header.pop("matrix_sha256", None)
    state_header.pop("run_id", None)
    state_header.pop("workflow_source_sha256", None)
    merged_state = {
        **state_header,
        "kind": "sharded_prompt_matrix_run",
        "shard_count": len(shard_dirs),
        "jobs": jobs,
    }
    (output / "run-state.json").write_text(
        json.dumps(merged_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for shard_dir in shard_dirs:
        shutil.rmtree(shard_dir)

    return {"jobs": len(jobs), "rows": len(scorecard_rows)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one prompt matrix across several ComfyUI endpoints and merge the result"
    )
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--api-url",
        action="append",
        required=True,
        help="repeat once per endpoint, e.g. --api-url http://a:8188 --api-url http://b:8188",
    )
    parser.add_argument(
        "--weights",
        help="comma-separated relative throughput per endpoint, e.g. 2,1,1 for one fast box",
    )
    parser.add_argument("--workflow", type=Path)
    parser.add_argument(
        "--shard-workflow",
        action="append",
        help=(
            "override --workflow for one shard, positional with --api-url, e.g. "
            "--shard-workflow '' --shard-workflow tests/baseline/workflow_int8.json "
            "--shard-workflow tests/baseline/workflow_int8.json for a primary endpoint "
            "plus two running a different checkpoint. Empty string keeps --workflow."
        ),
    )
    parser.add_argument("--queue-depth", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    try:
        rows = load_matrix(args.matrix)
        weights = parse_weights(args.weights, len(args.api_url))
        buckets = shard(rows, weights)
        shard_dirs = [args.output / f"shard_{i + 1}" for i in range(len(buckets))]
        shard_workflows = parse_shard_workflows(args.shard_workflow, len(args.api_url))

        processes = []
        for index, (bucket, shard_dir, api_url, shard_workflow) in enumerate(
            zip(buckets, shard_dirs, args.api_url, shard_workflows), start=1
        ):
            effective_workflow = shard_workflow or args.workflow
            shard_matrix = args.output / f"shard_{index}.jsonl"
            write_jsonl(shard_matrix, bucket)
            workflow_note = f" workflow={effective_workflow}" if effective_workflow else ""
            print(
                f"shard {index}: {len(bucket)} job(s) -> {api_url} "
                f"(weight {weights[index - 1]:g}){workflow_note}"
            )
            if not args.submit:
                continue
            processes.append(
                (
                    index,
                    api_url,
                    launch(
                        shard_matrix,
                        shard_dir,
                        api_url,
                        workflow=effective_workflow,
                        queue_depth=args.queue_depth,
                        resume=args.resume,
                        submit=True,
                    ),
                )
            )

        if not args.submit:
            print(f"DRY RUN: {len(rows)} job(s) across {len(buckets)} shard(s).")
            print("Re-run with --submit to execute.")
            return 0

        failures = []
        for index, api_url, process in processes:
            output_text, _ = process.communicate()
            tail = [line for line in (output_text or "").splitlines() if line.strip()][-3:]
            print(f"--- shard {index} ({api_url}) exit={process.returncode}")
            for line in tail:
                print(f"    {line}")
            if process.returncode != 0:
                failures.append(index)
        if failures:
            print(f"ERROR: shard(s) {failures} failed; not merging.", file=sys.stderr)
            return 1

        summary = merge(args.output, shard_dirs)
        print(
            f"Merged {summary['jobs']} job(s) and {summary['rows']} scorecard row(s) "
            f"into {args.output}."
        )
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
