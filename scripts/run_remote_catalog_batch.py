#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import load_yaml
from run_remote_benchmark import API_URL_ENV, png_dimensions, require_empty_queue


DEFAULT_CATALOG = Path("catalog/art_styles.yaml")
DEFAULT_TEMPLATES = Path("catalog/family_templates.yaml")
DEFAULT_SEEDS = (1001, 2002, 3003)
METRICS = (
    "prompt_adherence",
    "style_fidelity",
    "stability",
    "character_quality",
    "composition_quality",
    "compatibility",
    "distinctiveness",
    "prompt_efficiency",
    "critical_failure",
)


def catalog_jobs(
    catalog_path: Path,
    template_catalog_path: Path,
    statuses: set[str],
    seeds: tuple[int, ...],
    selected_styles: set[str] | None = None,
) -> list[dict[str, Any]]:
    catalog = load_yaml(catalog_path)
    items = catalog.get("items", {}) if isinstance(catalog, dict) else {}
    template_catalog = load_yaml(template_catalog_path)
    templates = (
        template_catalog.get("templates", {})
        if isinstance(template_catalog, dict)
        else {}
    )
    if not isinstance(items, dict) or not isinstance(templates, dict):
        raise ValueError("catalog items and family templates must be mappings")

    jobs = []
    for style_id, item in items.items():
        if selected_styles is not None and style_id not in selected_styles:
            continue
        validation = item.get("validation", {}) if isinstance(item, dict) else {}
        if validation.get("status") not in statuses:
            continue
        family = item.get("family")
        template = templates.get(family)
        if not isinstance(template, str):
            raise ValueError(f"no benchmark template for family: {family}")
        template_path = Path(template)
        if not template_path.is_file():
            raise ValueError(f"benchmark template not found: {template_path}")
        for seed in seeds:
            jobs.append(
                {
                    "style_id": style_id,
                    "family": family,
                    "seed": seed,
                    "template": template_path,
                    "catalog": catalog_path,
                }
            )
    if selected_styles is not None:
        found = {job["style_id"] for job in jobs}
        missing = selected_styles - found
        if missing:
            raise ValueError(
                "selected style(s) did not match requested statuses: "
                + ", ".join(sorted(missing))
            )
    if not jobs:
        raise ValueError("no catalog jobs matched the requested filters")
    return jobs


def validate_complete_run(run_dir: Path, job: dict[str, Any]) -> None:
    record_path = run_dir / "run.json"
    if not record_path.is_file():
        raise ValueError(f"partial run lacks run.json: {run_dir}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if (
        record.get("style_id") != job["style_id"]
        or record.get("seed") != job["seed"]
        or record.get("remote") != "private_comfyui"
        or "api_url" in record
    ):
        raise ValueError(f"run metadata mismatch: {run_dir}")
    images = record.get("images")
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError(f"run must record exactly one image: {run_dir}")
    image_path = Path(images[0])
    if not image_path.is_file():
        raise ValueError(f"recorded image is missing: {run_dir}")
    if png_dimensions(image_path.read_bytes()) != (1024, 1024):
        raise ValueError(f"recorded image dimensions are invalid: {run_dir}")


def limit_style_jobs(
    jobs: list[dict[str, Any]], limit_styles: int | None
) -> list[dict[str, Any]]:
    if limit_styles is None:
        return jobs
    if limit_styles < 1:
        raise ValueError("--limit-styles must be at least 1")
    selected: list[str] = []
    selected_set: set[str] = set()
    for job in jobs:
        if job["style_id"] not in selected_set:
            selected.append(job["style_id"])
            selected_set.add(job["style_id"])
        if len(selected) == limit_styles:
            break
    return [job for job in jobs if job["style_id"] in selected_set]


def pending_jobs(
    jobs: list[dict[str, Any]], output: Path, resume: bool
) -> list[dict[str, Any]]:
    pending = []
    for job in jobs:
        run_dir = output / "runs" / f"{job['style_id']}_seed_{job['seed']}"
        if not run_dir.exists():
            pending.append(job)
            continue
        if not resume:
            raise FileExistsError(f"run directory already exists: {run_dir}")
        validate_complete_run(run_dir, job)
    return pending


def write_scorecard(path: Path, jobs: list[dict[str, Any]]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["test_id", "seed", "style_id", "image_path", *METRICS, "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, job in enumerate(jobs, start=1):
            style_id = job["style_id"]
            seed = job["seed"]
            writer.writerow(
                {
                    "test_id": f"SCREEN{index:04d}",
                    "seed": seed,
                    "style_id": style_id,
                    "image_path": f"{path.parent}/runs/{style_id}_seed_{seed}/image_01.png",
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a catalog-driven family-compatible remote benchmark batch"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--templates", type=Path, default=DEFAULT_TEMPLATES)
    parser.add_argument("--status", action="append", default=None)
    parser.add_argument("--style-id", action="append", default=None)
    parser.add_argument("--seed", action="append", type=int, default=None)
    parser.add_argument("--limit-styles", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    try:
        jobs = catalog_jobs(
            args.catalog,
            args.templates,
            set(args.status or ["generated"]),
            tuple(args.seed or DEFAULT_SEEDS),
            set(args.style_id) if args.style_id else None,
        )
        jobs = limit_style_jobs(jobs, args.limit_styles)
        print(
            f"Catalog matrix: {len({job['style_id'] for job in jobs})} styles x "
            f"{len({job['seed'] for job in jobs})} seeds = {len(jobs)} images"
        )
        if not args.submit:
            for job in jobs:
                print(
                    f"DRY RUN: {job['style_id']} family={job['family']} "
                    f"seed={job['seed']} template={job['template']}"
                )
            return 0
        if args.output is None:
            raise ValueError("--output is required with --submit")
        api_url = os.environ.get(API_URL_ENV)
        if not api_url:
            raise ValueError(f"set {API_URL_ENV} before --submit")
        pending = pending_jobs(jobs, args.output, args.resume)
        print(f"Resume preflight: complete={len(jobs) - len(pending)} pending={len(pending)}")
        require_empty_queue(api_url)

        runner = Path(__file__).with_name("run_remote_benchmark.py")
        for index, job in enumerate(pending, start=1):
            print(
                f"[{index}/{len(pending)}] {job['style_id']} seed={job['seed']}",
                flush=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--style-id",
                    job["style_id"],
                    "--catalog",
                    str(job["catalog"]),
                    "--seed",
                    str(job["seed"]),
                    "--template",
                    str(job["template"]),
                    "--output",
                    str(args.output),
                    "--timeout",
                    str(args.timeout),
                    "--submit",
                ],
                check=False,
                env=os.environ.copy(),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"batch stopped at {job['style_id']} seed={job['seed']}"
                )
        require_empty_queue(api_url)
        for job in jobs:
            run_dir = args.output / "runs" / f"{job['style_id']}_seed_{job['seed']}"
            validate_complete_run(run_dir, job)
        write_scorecard(args.output / "scorecard.csv", jobs)
        print(f"Batch completed: {len(jobs)} verified run(s).")
        return 0
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
