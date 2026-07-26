#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common import item_prompts, item_status, iter_catalog_items


SUBJECT = (
    "An adult woman stands in a relaxed three-quarter pose against a neutral studio backdrop. "
    "Her expression is composed and attentive, with both hands clearly visible."
)
FINISH = (
    "Preserve natural proportions, coherent hands, believable fabric structure, cinematic depth, "
    "and a clean image without text, logos, or watermarks."
)


def records(catalog: Path, statuses: set[str], seeds: list[int]):
    index = 1
    for _, item_id, item in iter_catalog_items(catalog):
        if item_status(item) not in statuses:
            continue
        for prompt in item_prompts(item):
            for seed in seeds:
                yield {
                    "test_id": f"ST{index:04d}",
                    "seed": seed,
                    "style_id": item_id,
                    "status": item_status(item),
                    "prompt": f"{prompt}. {SUBJECT} {FINISH}",
                }
                index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Export fixed-subject style benchmark prompts")
    parser.add_argument("--catalog", type=Path, default=Path("catalog"))
    parser.add_argument("--output", type=Path, default=Path("tests/prompt_matrix/styles.jsonl"))
    parser.add_argument("--status", action="append", default=None)
    parser.add_argument("--seed", action="append", type=int, default=None)
    args = parser.parse_args()

    rows = list(
        records(
            args.catalog,
            set(args.status or ["generated", "testing", "approved"]),
            args.seed or [1001, 2002, 3003],
        )
    )
    if not rows:
        print("ERROR: no matching prompts")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == ".csv":
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(rows[0]), lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
    else:
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} test prompt(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
