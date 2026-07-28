#!/usr/bin/env python3
"""Phase 7 Stage A: deterministic prefilter over a completed axis run.

Mass promotion cannot afford a model call per image. Stage A removes the
failures a model is not needed for -- missing seeds, unsuccessful jobs, wrong
resolution, corrupt files, seed-identical output, and flat degenerate frames --
so only survivors reach the batched contact-sheet review.

Every check here is reproducible from the run evidence on disk. Nothing in this
script scores quality; a Stage A pass only means the frame is worth looking at.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


EXPECTED_DIMENSIONS = (1024, 1024)
MINIMUM_STDDEV = 4.0
MINIMUM_LUMINANCE_LEVELS = 8
SUCCESS_COMPLETION = "completed"
SUCCESS_REMOTE = "success"


def load_scorecard(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"scorecard has no rows: {path}")
    required = {"test_id", "seed", "style_id", "mode", "image_path"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"scorecard is missing columns: {sorted(missing)}")
    return rows


def load_run_state(path: Path) -> dict[str, dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError(f"run state has no jobs mapping: {path}")
    return jobs


def inspect_image(path: Path) -> tuple[list[str], dict[str, Any]]:
    """Deterministic per-frame checks. Returns (failure reasons, measurements)."""
    if not path.is_file():
        return [f"image is missing: {path}"], {}
    try:
        with Image.open(path) as image:
            image.load()
            size = image.size
            grey = image.convert("L")
    except (OSError, ValueError) as exc:
        return [f"image is unreadable: {path} ({exc})"], {}

    reasons: list[str] = []
    if size != EXPECTED_DIMENSIONS:
        reasons.append(f"image is {size[0]}x{size[1]}, expected 1024x1024")
    stddev = ImageStat.Stat(grey).stddev[0]
    levels = len(set(grey.getdata()))
    if stddev < MINIMUM_STDDEV:
        reasons.append(f"image is flat: luminance stddev {stddev:.2f}")
    if levels < MINIMUM_LUMINANCE_LEVELS:
        reasons.append(f"image is degenerate: {levels} luminance level(s)")
    return reasons, {
        "width": size[0],
        "height": size[1],
        "luminance_stddev": round(stddev, 3),
        "luminance_levels": levels,
    }


def audit(
    scorecard: Path,
    run_state: Path,
    *,
    axis: str,
    expected_seeds: int,
    root: Path,
) -> dict[str, Any]:
    if expected_seeds < 1:
        raise ValueError("expected_seeds must be at least 1")
    rows = load_scorecard(scorecard)
    jobs = load_run_state(run_state)

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["style_id"], []).append(row)

    items: dict[str, Any] = {}
    for style_id, style_rows in sorted(grouped.items()):
        reasons: list[str] = []
        seeds = {row["seed"] for row in style_rows}
        if len(seeds) != expected_seeds:
            reasons.append(
                f"expected {expected_seeds} distinct seed(s), found {len(seeds)}"
            )

        digests: dict[str, str] = {}
        frames: dict[str, Any] = {}
        for row in sorted(style_rows, key=lambda entry: entry["test_id"]):
            test_id = row["test_id"]
            job = jobs.get(test_id)
            if not isinstance(job, dict):
                reasons.append(f"{test_id}: absent from run state")
                continue
            if job.get("completion_status") != SUCCESS_COMPLETION:
                reasons.append(
                    f"{test_id}: completion_status={job.get('completion_status')!r}"
                )
            if job.get("remote_status") != SUCCESS_REMOTE:
                reasons.append(f"{test_id}: remote_status={job.get('remote_status')!r}")
            digest = job.get("image_sha256")
            if isinstance(digest, str) and digest:
                digests[test_id] = digest
            else:
                reasons.append(f"{test_id}: run state has no image_sha256")

            image_reasons, measurements = inspect_image(root / row["image_path"])
            reasons.extend(f"{test_id}: {reason}" for reason in image_reasons)
            frames[test_id] = {"seed": row["seed"], **measurements}

        if digests and len(set(digests.values())) != len(digests):
            reasons.append("seeds produced identical images")

        items[style_id] = {
            "passed": not reasons,
            "seed_count": len(seeds),
            "frames": frames,
            "reasons": reasons,
        }

    failed = sorted(key for key, value in items.items() if not value["passed"])
    return {
        "schema_version": 1,
        "report_type": "phase7_stage_a_audit",
        "axis": axis,
        "scorecard": scorecard.as_posix(),
        "run_state": run_state.as_posix(),
        "expected_seeds": expected_seeds,
        "item_count": len(items),
        "passed_count": len(items) - len(failed),
        "failed_count": len(failed),
        "failed_item_ids": failed,
        "status": "passed" if not failed else "failed",
        "complete": not failed,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Phase 7 Stage A deterministic prefilter"
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--run-state", type=Path, required=True)
    parser.add_argument("--axis", required=True)
    parser.add_argument("--expected-seeds", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="base directory the scorecard image paths are relative to",
    )
    args = parser.parse_args()
    try:
        report = audit(
            args.scorecard,
            args.run_state,
            axis=args.axis,
            expected_seeds=args.expected_seeds,
            root=args.root,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(
        f"Stage A ({report['axis']}): {report['passed_count']}/{report['item_count']} "
        f"item(s) passed; report={args.output}"
    )
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
