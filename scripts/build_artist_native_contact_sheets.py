#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Sequence

import build_contact_sheets as contact
from export_artist_native_matrix import ARTIST_ID_RE
from run_remote_prompt_matrix import load_jobs


DEFAULT_MATRIX = Path("tests/prompt_matrix/artist_native_name.jsonl")
FAMILY = "artist_native_name"
DEFAULT_EXPECTED_ARTISTS = 300
DEFAULT_EXPECTED_SEEDS = 3
DEFAULT_ARTISTS_PER_SHEET = 10


def load_native_matrix(
    path: Path,
    *,
    expected_artists: int,
    expected_seeds: int,
) -> dict[str, dict[str, Any]]:
    jobs = load_jobs(path)
    identities: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for job in jobs:
        artist_id = job["style_id"]
        if job["mode"] != "native_name":
            raise ValueError(f"matrix test {job['test_id']!r} is not native_name mode")
        if not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(f"matrix test {job['test_id']!r} has invalid native artist id")
        identities[job["test_id"]] = {
            "test_id": job["test_id"],
            "artist_id": artist_id,
            "style_id": artist_id,
            "mode": "native_name",
            "seed": job["seed"],
        }
        rows.append({"style_id": artist_id, "seed": job["seed"]})

    artist_count = len({row["style_id"] for row in rows})
    if artist_count != expected_artists:
        raise ValueError(
            f"matrix must contain exactly {expected_artists} native artists; found {artist_count}"
        )
    contact.validate_seed_matrix(rows, expected_seeds)
    return identities


def load_native_scorecard(
    path: Path,
    matrix_jobs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_test_ids: set[str] = set()
    seen_artist_seeds: set[tuple[str, int]] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"test_id", "style_id", "mode", "seed", "image_path"}
        if not required.issubset(fields):
            raise ValueError("scorecard is missing native identity or image columns")
        for line_number, raw in enumerate(reader, start=2):
            test_id = (raw.get("test_id") or "").strip()
            expected = matrix_jobs.get(test_id)
            if expected is None:
                raise ValueError(f"line {line_number}: test_id is absent from native matrix")
            if test_id in seen_test_ids:
                raise ValueError(f"line {line_number}: duplicate test_id")

            artist_id = (raw.get("style_id") or "").strip()
            mode = (raw.get("mode") or "").strip()
            try:
                seed = int((raw.get("seed") or "").strip())
            except ValueError as exc:
                raise ValueError(f"line {line_number}: seed must be an integer") from exc
            if artist_id != expected["artist_id"] or mode != expected["mode"] or seed != expected["seed"]:
                raise ValueError(f"line {line_number}: scorecard identity does not match native matrix")

            identity = (artist_id, seed)
            if identity in seen_artist_seeds:
                raise ValueError(f"line {line_number}: duplicate native artist and seed")

            raw_image = (raw.get("image_path") or "").strip()
            if not raw_image:
                raise ValueError(f"line {line_number}: image_path is required")
            image = Path(raw_image)
            if not image.is_absolute():
                image = contact.ROOT / image
            image_path = contact.repo_relative(image)
            if not image.is_file():
                raise ValueError(f"line {line_number}: image is missing")
            expected_image = (path.parent / "runs" / test_id / "image_01.png").resolve()
            if image.resolve() != expected_image:
                raise ValueError(
                    f"line {line_number}: image path must use the redacted test_id run directory"
                )

            seen_test_ids.add(test_id)
            seen_artist_seeds.add(identity)
            rows.append(
                {
                    "test_id": test_id,
                    "artist_id": artist_id,
                    "style_id": artist_id,
                    "family": FAMILY,
                    "seed": seed,
                    "image": image.resolve(),
                    "image_path": image_path,
                }
            )

    missing = sorted(set(matrix_jobs) - seen_test_ids)
    if missing:
        raise ValueError(f"scorecard does not cover {len(missing)} native matrix test(s)")
    if not rows:
        raise ValueError("scorecard contains no native rows")
    return rows


def sheet_plan(
    rows: list[dict[str, Any]],
    output: Path,
    *,
    artists_per_sheet: int,
) -> list[tuple[Path, list[dict[str, Any]]]]:
    artist_ids = sorted({row["artist_id"] for row in rows})
    sheet_count = (len(artist_ids) + artists_per_sheet - 1) // artists_per_sheet
    planned: list[tuple[Path, list[dict[str, Any]]]] = []
    for chunk_index, start in enumerate(range(0, len(artist_ids), artists_per_sheet), start=1):
        selected = set(artist_ids[start : start + artists_per_sheet])
        chunk_rows = [row for row in rows if row["artist_id"] in selected]
        suffix = f"_{chunk_index:03d}" if sheet_count > 1 else ""
        planned.append((output / f"{FAMILY}{suffix}.png", chunk_rows))
    return planned


def manifest_document(
    scorecard: Path,
    matrix: Path,
    rows: list[dict[str, Any]],
    sheets: list[Path],
    *,
    expected_seeds: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "artist_native_name_contact_sheet_review",
        "scorecard": contact.repo_relative(scorecard),
        "matrix": contact.repo_relative(matrix),
        "family": FAMILY,
        "expected_seeds_per_artist": expected_seeds,
        "artist_count": len({row["artist_id"] for row in rows}),
        "image_count": len(rows),
        "sheets": [contact.repo_relative(sheet) for sheet in sheets],
        "items": [
            {
                "test_id": row["test_id"],
                "artist_id": row["artist_id"],
                "seed": row["seed"],
                "image_path": row["image_path"],
            }
            for row in sorted(rows, key=lambda item: (item["artist_id"], item["seed"]))
        ],
    }


def build_review(
    scorecard: Path,
    matrix: Path,
    output: Path,
    *,
    expected_artists: int,
    expected_seeds: int,
    artists_per_sheet: int,
    overwrite: bool,
    dry_run: bool,
) -> dict[str, Any]:
    matrix_jobs = load_native_matrix(
        matrix,
        expected_artists=expected_artists,
        expected_seeds=expected_seeds,
    )
    rows = load_native_scorecard(scorecard, matrix_jobs)
    contact.validate_seed_matrix(rows, expected_seeds)
    contact.repo_relative(output)
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise ValueError("review output already exists; pass --overwrite to replace sheets")

    planned = sheet_plan(rows, output, artists_per_sheet=artists_per_sheet)
    document = manifest_document(
        scorecard,
        matrix,
        rows,
        [sheet for sheet, _ in planned],
        expected_seeds=expected_seeds,
    )
    if dry_run:
        return document

    output.mkdir(parents=True, exist_ok=True)
    total_sheets = len(planned)
    for index, (sheet, chunk_rows) in enumerate(planned, start=1):
        contact.render_sheet(
            f"{FAMILY} {index}/{total_sheets}",
            chunk_rows,
            sheet,
            expected_seeds,
        )
    (output / "manifest.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build redacted contact sheets for a native-name artist scorecard without catalog IDs"
        )
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-artists", type=int, default=DEFAULT_EXPECTED_ARTISTS)
    parser.add_argument("--expected-seeds", type=int, default=DEFAULT_EXPECTED_SEEDS)
    parser.add_argument(
        "--artists-per-sheet",
        type=int,
        default=DEFAULT_ARTISTS_PER_SHEET,
        help="split the native family into bounded sheets (default: 10 artists)",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate matrix, scorecard, images, coverage, seeds, and split without writing",
    )
    args = parser.parse_args(argv)

    try:
        if args.expected_artists < 1:
            raise ValueError("--expected-artists must be at least 1")
        if args.expected_seeds < 1:
            raise ValueError("--expected-seeds must be at least 1")
        if args.artists_per_sheet < 1:
            raise ValueError("--artists-per-sheet must be at least 1")
        output = args.output or args.scorecard.parent / "review"
        document = build_review(
            args.scorecard,
            args.matrix,
            output,
            expected_artists=args.expected_artists,
            expected_seeds=args.expected_seeds,
            artists_per_sheet=args.artists_per_sheet,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        prefix = "DRY RUN:" if args.dry_run else "Built"
        print(
            f"{prefix} {document['artist_count']} native artist(s), "
            f"{document['image_count']} image(s), {len(document['sheets'])} sheet(s)."
        )
        return 0
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
