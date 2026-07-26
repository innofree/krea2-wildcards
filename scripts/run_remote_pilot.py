#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path


PILOT_STYLES = (
    "crystal_iris_pastel",
    "angular_impact",
    "prismatic_key_visual",
    "sumi_mist",
    "minimal_studio",
)
PILOT_SEEDS = (1001, 2002, 3003)
API_URL_ENV = "KREA2_COMFY_API_URL"
DEFAULT_OUTPUT = Path("tests/reports/family_retest_v0_2")
PILOT_TEMPLATES = {
    "crystal_iris_pastel": Path("templates/style_benchmark_refined_pastel.txt"),
    "angular_impact": Path("templates/style_benchmark_graphic_action.txt"),
    "prismatic_key_visual": Path("templates/style_benchmark_luminous_game.txt"),
    "sumi_mist": Path("templates/style_benchmark_ink_wash.txt"),
    "minimal_studio": Path("templates/style_benchmark_editorial_fashion.txt"),
}
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


def pilot_jobs(seeds: tuple[int, ...] = PILOT_SEEDS) -> list[tuple[str, int]]:
    return [(style_id, seed) for style_id in PILOT_STYLES for seed in seeds]


def write_scorecard(
    path: Path,
    run_root: Path = Path("tests/reports/runs"),
    jobs: list[tuple[str, int]] | None = None,
    overwrite: bool = False,
) -> None:
    if path.exists() and not overwrite:
        print(f"Scorecard already exists and was preserved: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["test_id", "seed", "style_id", "image_path", *METRICS, "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index, (style_id, seed) in enumerate(jobs or pilot_jobs(), start=1):
            writer.writerow(
                {
                    "test_id": f"PILOT{index:03d}",
                    "seed": seed,
                    "style_id": style_id,
                    "image_path": (
                        f"{run_root}/{style_id}_seed_{seed}/image_01.png"
                    ),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 5-style by 3-seed remote pilot")
    parser.add_argument("--api-url", default=os.environ.get(API_URL_ENV))
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--seed",
        action="append",
        type=int,
        help="seed to run; repeat for a custom extension set",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scorecard", type=Path)
    parser.add_argument("--overwrite-scorecard", action="store_true")
    args = parser.parse_args()

    seeds = tuple(args.seed) if args.seed else PILOT_SEEDS
    jobs = pilot_jobs(seeds)
    scorecard = args.scorecard or args.output / "scorecard.csv"
    print(f"Pilot matrix: {len(PILOT_STYLES)} styles x {len(seeds)} seeds = {len(jobs)} images")
    if not args.submit:
        for style_id, seed in jobs:
            print(f"DRY RUN: {style_id} seed={seed}")
        print("Re-run with --submit to queue jobs sequentially.")
        return 0
    if not args.api_url:
        print(f"ERROR: set {API_URL_ENV} or pass --api-url before --submit")
        return 1

    runner = Path(__file__).with_name("run_remote_benchmark.py")
    child_env = os.environ.copy()
    child_env[API_URL_ENV] = args.api_url
    for index, (style_id, seed) in enumerate(jobs, start=1):
        template = PILOT_TEMPLATES[style_id]
        if not template.is_file():
            print(f"ERROR: benchmark template not found: {template}")
            return 1
        print(f"[{index}/{len(jobs)}] {style_id} seed={seed}", flush=True)
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "--style-id",
                style_id,
                "--template",
                str(template),
                "--output",
                str(args.output),
                "--seed",
                str(seed),
                "--submit",
            ],
            check=False,
            env=child_env,
        )
        if result.returncode != 0:
            print(f"ERROR: pilot stopped at {style_id} seed={seed}")
            return result.returncode
    write_scorecard(
        scorecard,
        run_root=args.output / "runs",
        jobs=jobs,
        overwrite=args.overwrite_scorecard,
    )
    print(f"Pilot completed. Scorecard: {scorecard}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
