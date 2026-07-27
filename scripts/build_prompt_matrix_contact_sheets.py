#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from run_remote_prompt_matrix import (
    ACCOUNT_AT_HOST_RE,
    HOME_PATH_RE,
    IPV4_RE,
    MODE_RE,
    SAFE_ID_RE,
    STYLE_ID_RE,
    URL_RE,
    _clean_factors,
    load_jobs,
    redact_error,
)
from export_artist_visual_signature_matrix import (
    LEGACY_BENCHMARK_PROFILE,
    REPAIR_BENCHMARK_PROFILE,
    REPAIR_SEEDS,
    RETEST_SEEDS,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTED_SEEDS = 3
DEFAULT_CASES_PER_SHEET = 10
MANIFEST_KIND = "resolved_prompt_matrix_contact_sheet_review"
LEGACY_PILOT_SEEDS = (1001, 2002, 3003)
PROMPT_DIGEST_RE = re.compile(r"^sha256_[0-9a-f]{64}$")


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("review artifacts must remain inside the repository") from exc
    if (
        URL_RE.search(relative)
        or IPV4_RE.search(relative)
        or HOME_PATH_RE.search(relative)
        or ACCOUNT_AT_HOST_RE.search(relative)
    ):
        raise ValueError("review path contains forbidden connection data")
    return relative


def validate_seed_sets(
    jobs: list[dict[str, Any]], expected_seeds: int
) -> tuple[int, ...]:
    by_case: dict[tuple[str, str], set[int]] = defaultdict(set)
    for job in jobs:
        key = (job["mode"], job["style_id"])
        seed = job["seed"]
        if seed in by_case[key]:
            raise ValueError("duplicate style/mode and seed")
        by_case[key].add(seed)

    incomplete = sorted(
        key for key, seeds in by_case.items() if len(seeds) != expected_seeds
    )
    if incomplete:
        cases = ", ".join(f"{mode}/{style_id}" for mode, style_id in incomplete)
        raise ValueError(
            f"expected exactly {expected_seeds} seeds for every style/mode; "
            f"incomplete cases: {cases}"
        )

    seed_sets = {tuple(sorted(seeds)) for seeds in by_case.values()}
    if len(seed_sets) != 1:
        raise ValueError("all style/mode cases must use the same seed set")
    return next(iter(seed_sets))


def load_matrix(
    path: Path, *, expected_seeds: int
) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, str]],
    tuple[int, ...],
]:
    jobs = load_jobs(path)
    seeds = validate_seed_sets(jobs, expected_seeds)
    matrix_jobs: dict[str, dict[str, Any]] = {}
    factors_by_case: dict[tuple[str, str], dict[str, str]] = {}
    for job in jobs:
        case = (job["mode"], job["style_id"])
        factors = dict(job["factors"])
        previous = factors_by_case.setdefault(case, factors)
        if previous != factors:
            raise ValueError(
                "matrix factors must remain constant across seeds for every style/mode"
            )
        matrix_jobs[job["test_id"]] = {
            "test_id": job["test_id"],
            "style_id": job["style_id"],
            "mode": job["mode"],
            "seed": job["seed"],
            "factors": factors,
        }
    return matrix_jobs, factors_by_case, seeds


def _scorecard_image(raw_value: str, *, line_number: int) -> tuple[Path, str]:
    if not raw_value:
        raise ValueError(f"line {line_number}: image_path is required")
    raw_path = Path(raw_value)
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError(
            f"line {line_number}: image_path must be a safe repository-relative path"
        )
    image = (ROOT / raw_path).resolve()
    relative = repo_relative(image)
    if not image.is_file():
        raise ValueError(f"line {line_number}: image is missing")
    return image, relative


def load_scorecard(
    path: Path, matrix_jobs: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_test_ids: set[str] = set()
    seen_case_seeds: set[tuple[str, str, int]] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"test_id", "style_id", "mode", "seed", "image_path"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("scorecard is missing matrix identity or image columns")
        for line_number, raw in enumerate(reader, start=2):
            test_id = (raw.get("test_id") or "").strip()
            expected = matrix_jobs.get(test_id)
            if expected is None:
                raise ValueError(f"line {line_number}: test_id is absent from matrix")
            if test_id in seen_test_ids:
                raise ValueError(f"line {line_number}: duplicate test_id and case seed")

            style_id = (raw.get("style_id") or "").strip()
            mode = (raw.get("mode") or "").strip()
            try:
                seed = int((raw.get("seed") or "").strip())
            except ValueError as exc:
                raise ValueError(
                    f"line {line_number}: seed must be an integer"
                ) from exc
            if (
                style_id != expected["style_id"]
                or mode != expected["mode"]
                or seed != expected["seed"]
            ):
                raise ValueError(
                    f"line {line_number}: scorecard identity does not match matrix"
                )

            case_seed = (mode, style_id, seed)
            if case_seed in seen_case_seeds:
                raise ValueError(f"line {line_number}: duplicate style/mode and seed")
            image, image_path = _scorecard_image(
                (raw.get("image_path") or "").strip(), line_number=line_number
            )
            seen_test_ids.add(test_id)
            seen_case_seeds.add(case_seed)
            rows.append(
                {
                    "test_id": test_id,
                    "style_id": style_id,
                    "mode": mode,
                    "seed": seed,
                    "factors": dict(expected["factors"]),
                    "image": image,
                    "image_path": image_path,
                }
            )

    missing = sorted(set(matrix_jobs) - seen_test_ids)
    if missing:
        raise ValueError(f"scorecard does not cover {len(missing)} matrix test(s)")
    if not rows:
        raise ValueError("scorecard contains no matrix rows")
    return rows


def _standalone_identity(
    raw: dict[str, str | None], *, line_number: int
) -> tuple[str, str, str, int]:
    raw_test_id = raw.get("test_id") or ""
    test_id = raw_test_id.strip()
    if raw_test_id != test_id or not SAFE_ID_RE.fullmatch(test_id):
        raise ValueError(f"line {line_number}: invalid test_id")

    raw_style_id = raw.get("style_id") or ""
    style_id = raw_style_id.strip()
    if raw_style_id != style_id or not STYLE_ID_RE.fullmatch(style_id):
        raise ValueError(f"line {line_number}: invalid style_id")

    raw_mode = raw.get("mode") or ""
    mode = raw_mode.strip()
    if raw_mode != mode or not MODE_RE.fullmatch(mode):
        raise ValueError(f"line {line_number}: invalid mode")

    try:
        seed = int((raw.get("seed") or "").strip())
    except ValueError as exc:
        raise ValueError(f"line {line_number}: seed must be an integer") from exc
    if not 0 <= seed < 2**64:
        raise ValueError(f"line {line_number}: seed must be a 64-bit unsigned integer")
    return test_id, style_id, mode, seed


def _standalone_factors(raw_value: str, *, line_number: int) -> dict[str, str]:
    if not raw_value.strip():
        raise ValueError(f"line {line_number}: factors_json is required")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"line {line_number}: factors_json must be valid JSON"
        ) from exc
    return _clean_factors(value, line_number=line_number)


def _profile_seed_stages(
    profile: str,
    *,
    expected_seeds: int,
) -> dict[int, str | None]:
    if profile == REPAIR_BENCHMARK_PROFILE:
        pilot_seeds = REPAIR_SEEDS
        pilot_stage = "pilot"
    elif profile == LEGACY_BENCHMARK_PROFILE:
        pilot_seeds = LEGACY_PILOT_SEEDS
        pilot_stage = None
    else:
        raise ValueError(f"unsupported mixed benchmark profile: {profile}")

    if expected_seeds == len(pilot_seeds):
        return {seed: pilot_stage for seed in pilot_seeds}
    if expected_seeds == len(RETEST_SEEDS):
        extension_stage = (
            "extension" if profile == REPAIR_BENCHMARK_PROFILE else None
        )
        return {seed: extension_stage for seed in RETEST_SEEDS}
    if expected_seeds == len(pilot_seeds) + len(RETEST_SEEDS):
        expected = {seed: pilot_stage for seed in pilot_seeds}
        extension_stage = (
            "extension" if profile == REPAIR_BENCHMARK_PROFILE else None
        )
        expected.update({seed: extension_stage for seed in RETEST_SEEDS})
        return expected
    raise ValueError(
        "mixed artist benchmark scorecards require exact two-, three-, or "
        "five-seed profile sets"
    )


def _mixed_artist_case_factors(
    rows: list[dict[str, Any]],
    *,
    expected_seeds: int,
) -> tuple[dict[tuple[str, str], dict[str, str]], tuple[int, ...]]:
    by_case: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[(row["mode"], row["style_id"])].append(row)

    factors_by_case: dict[tuple[str, str], dict[str, str]] = {}
    all_seeds: set[int] = set()
    for case, case_rows in sorted(by_case.items()):
        if len(case_rows) != expected_seeds:
            raise ValueError(
                f"expected exactly {expected_seeds} seeds for every style/mode; "
                f"incomplete case: {case[0]}/{case[1]}"
            )
        profiles = {
            row["factors"].get(
                "benchmark_profile",
                LEGACY_BENCHMARK_PROFILE,
            )
            for row in case_rows
        }
        if len(profiles) != 1:
            raise ValueError(
                f"mixed benchmark profiles within style/mode: {case[0]}/{case[1]}"
            )
        profile = next(iter(profiles))
        expected = _profile_seed_stages(profile, expected_seeds=expected_seeds)
        actual_seeds = {row["seed"] for row in case_rows}
        if actual_seeds != set(expected):
            raise ValueError(
                f"{profile} case {case[0]}/{case[1]} does not contain its exact "
                f"{expected_seeds}-seed set"
            )

        normalized: list[dict[str, str]] = []
        legacy_extension_digests: set[str] = set()
        legacy_pilot_digests: set[str] = set()
        for row in case_rows:
            factors = dict(row["factors"])
            stage = factors.pop("benchmark_stage", None)
            expected_stage = expected[row["seed"]]
            if stage != expected_stage:
                raise ValueError(
                    f"{profile} seed {row['seed']} has benchmark_stage "
                    f"{stage!r}; expected {expected_stage!r}"
                )
            digest = factors.pop("evaluated_prompt_sha256", None)
            if profile == REPAIR_BENCHMARK_PROFILE:
                if (
                    not isinstance(digest, str)
                    or not PROMPT_DIGEST_RE.fullmatch(digest)
                ):
                    raise ValueError(
                        f"{profile} case {case[0]}/{case[1]} is missing a valid "
                        "evaluated prompt digest"
                    )
                factors["evaluated_prompt_sha256"] = digest
            elif row["seed"] in RETEST_SEEDS:
                if (
                    not isinstance(digest, str)
                    or not PROMPT_DIGEST_RE.fullmatch(digest)
                ):
                    raise ValueError(
                        "legacy extension prompt digests must be valid and identical"
                    )
                legacy_extension_digests.add(digest)
            elif digest is not None:
                if not isinstance(digest, str) or not PROMPT_DIGEST_RE.fullmatch(
                    digest
                ):
                    raise ValueError(
                        "legacy pilot prompt digests must be absent or valid"
                    )
                legacy_pilot_digests.add(digest)
            normalized.append(factors)
        if any(factors != normalized[0] for factors in normalized[1:]):
            raise ValueError(
                f"{profile} case {case[0]}/{case[1]} may vary only "
                "benchmark_stage across seeds"
            )
        if profile == LEGACY_BENCHMARK_PROFILE:
            if len(legacy_extension_digests) != 1:
                raise ValueError(
                    "legacy extension prompt digests must be valid and identical"
                )
            extension_digest = next(iter(legacy_extension_digests))
            if legacy_pilot_digests not in (set(), {extension_digest}):
                raise ValueError(
                    "legacy pilot prompt digests do not match the extension"
                )
            normalized[0]["evaluated_prompt_sha256"] = extension_digest
        factors_by_case[case] = normalized[0]
        all_seeds.update(actual_seeds)
    return factors_by_case, tuple(sorted(all_seeds))


def load_standalone_scorecard(
    path: Path, *, expected_seeds: int
) -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, str], dict[str, str]],
    tuple[int, ...],
]:
    rows: list[dict[str, Any]] = []
    seen_case_seeds: set[tuple[str, str, int]] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "test_id",
            "style_id",
            "mode",
            "seed",
            "image_path",
            "factors_json",
        }
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                "scorecard-only mode requires test_id, style_id, mode, seed, "
                "image_path, and factors_json columns"
            )
        for line_number, raw in enumerate(reader, start=2):
            test_id, style_id, mode, seed = _standalone_identity(
                raw, line_number=line_number
            )
            case = (mode, style_id)
            case_seed = (*case, seed)
            if case_seed in seen_case_seeds:
                raise ValueError(f"line {line_number}: duplicate style/mode and seed")
            factors = _standalone_factors(
                raw.get("factors_json") or "", line_number=line_number
            )
            image, image_path = _scorecard_image(
                (raw.get("image_path") or "").strip(), line_number=line_number
            )
            seen_case_seeds.add(case_seed)
            rows.append(
                {
                    "test_id": test_id,
                    "style_id": style_id,
                    "mode": mode,
                    "seed": seed,
                    "factors": factors,
                    "image": image,
                    "image_path": image_path,
                }
            )

    if not rows:
        raise ValueError("scorecard contains no matrix rows")
    has_repair_profile = any(
        row["factors"].get("benchmark_profile") == REPAIR_BENCHMARK_PROFILE
        for row in rows
    )
    if has_repair_profile:
        factors_by_case, seeds = _mixed_artist_case_factors(
            rows,
            expected_seeds=expected_seeds,
        )
    else:
        factors_by_case = {}
        for row in rows:
            case = (row["mode"], row["style_id"])
            previous = factors_by_case.setdefault(case, row["factors"])
            if previous != row["factors"]:
                raise ValueError(
                    "factors must remain constant across seeds for every style/mode"
                )
        seeds = validate_seed_sets(rows, expected_seeds)
    return rows, factors_by_case, seeds


def assign_aliases(rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    cases = sorted({(row["mode"], row["style_id"]) for row in rows})
    return {case: f"case_{index:03d}" for index, case in enumerate(cases, start=1)}


def sheet_plan(
    rows: list[dict[str, Any]],
    aliases: dict[tuple[str, str], str],
    output: Path,
    *,
    cases_per_sheet: int,
) -> list[dict[str, Any]]:
    by_mode: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for case in sorted(aliases):
        by_mode[case[0]].append(case)

    planned: list[dict[str, Any]] = []
    for mode, cases in sorted(by_mode.items()):
        sheet_count = (len(cases) + cases_per_sheet - 1) // cases_per_sheet
        for sheet_index, start in enumerate(
            range(0, len(cases), cases_per_sheet), start=1
        ):
            chunk = cases[start : start + cases_per_sheet]
            selected = set(chunk)
            chunk_rows = [
                {**row, "alias": aliases[(row["mode"], row["style_id"])]}
                for row in rows
                if (row["mode"], row["style_id"]) in selected
            ]
            planned.append(
                {
                    "mode": mode,
                    "sheet_index": sheet_index,
                    "sheet_count_for_mode": sheet_count,
                    "case_count": len(chunk),
                    "image_count": len(chunk_rows),
                    "path": output / f"prompt_matrix_{mode}_{sheet_index:03d}.png",
                    "rows": chunk_rows,
                }
            )
    return planned


def render_sheet(
    title: str,
    rows: list[dict[str, Any]],
    output: Path,
    expected_seeds: int,
) -> None:
    montage = shutil.which("montage")
    if montage is None:
        raise RuntimeError("ImageMagick montage is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".prompt-matrix-labels-", dir=output.parent
    ) as temp_name:
        temp = Path(temp_name)
        inputs: list[str] = []
        for row in sorted(rows, key=lambda item: (item["alias"], item["seed"])):
            link = temp / f"{row['alias']}__{row['seed']}.png"
            link.symlink_to(row["image"])
            inputs.append(str(link))
        result = subprocess.run(
            [
                montage,
                "-label",
                "%t",
                *inputs,
                "-thumbnail",
                "256x256",
                "-tile",
                f"{expected_seeds}x",
                "-geometry",
                "+8+26",
                "-background",
                "#1f1f1f",
                "-fill",
                "white",
                "-title",
                title,
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"contact sheet rendering failed for mode {title.split()[0]}"
        )


def manifest_document(
    scorecard: Path,
    matrix: Path | None,
    rows: list[dict[str, Any]],
    factors_by_case: dict[tuple[str, str], dict[str, str]],
    aliases: dict[tuple[str, str], str],
    planned: list[dict[str, Any]],
    seeds: tuple[int, ...],
    *,
    expected_seeds: int,
    cases_per_sheet: int,
) -> dict[str, Any]:
    by_case: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[(row["mode"], row["style_id"])].append(row)

    sheets = [
        {
            "mode": sheet["mode"],
            "sheet_index": sheet["sheet_index"],
            "path": repo_relative(sheet["path"]),
            "case_count": sheet["case_count"],
            "image_count": sheet["image_count"],
        }
        for sheet in planned
    ]
    modes: dict[str, dict[str, Any]] = {}
    for mode in sorted({case[0] for case in aliases}):
        mode_sheets = [sheet for sheet in sheets if sheet["mode"] == mode]
        modes[mode] = {
            "case_count": sum(1 for case in aliases if case[0] == mode),
            "image_count": sum(sheet["image_count"] for sheet in mode_sheets),
            "sheet_count": len(mode_sheets),
            "sheets": [sheet["path"] for sheet in mode_sheets],
        }

    cases = []
    for case in sorted(aliases):
        mode, style_id = case
        items = []
        benchmark_stages: set[str] = set()
        for row in sorted(by_case[case], key=lambda item: item["seed"]):
            item = {
                "test_id": row["test_id"],
                "seed": row["seed"],
                "image_path": row["image_path"],
            }
            benchmark_stage = row["factors"].get("benchmark_stage")
            if isinstance(benchmark_stage, str):
                item["benchmark_stage"] = benchmark_stage
                benchmark_stages.add(benchmark_stage)
            items.append(item)
        case_document = {
            "alias": aliases[case],
            "style_id": style_id,
            "mode": mode,
            "factors": dict(sorted(factors_by_case[case].items())),
            "items": items,
        }
        if benchmark_stages:
            case_document["benchmark_stages"] = sorted(benchmark_stages)
        cases.append(case_document)

    return {
        "schema_version": 1,
        "kind": MANIFEST_KIND,
        "scorecard": repo_relative(scorecard),
        "matrix": repo_relative(matrix) if matrix is not None else None,
        "expected_seeds_per_case": expected_seeds,
        "seeds": list(seeds),
        "cases_per_sheet": cases_per_sheet,
        "case_count": len(aliases),
        "style_count": len({row["style_id"] for row in rows}),
        "image_count": len(rows),
        "sheet_count": len(sheets),
        "modes": modes,
        "sheets": sheets,
        "cases": cases,
    }


def _manifest_sheet_paths(document: dict[str, Any], output: Path) -> set[Path]:
    if document.get("kind") != MANIFEST_KIND or not isinstance(
        document.get("sheets"), list
    ):
        raise ValueError(
            "existing review manifest is not a prompt-matrix contact sheet"
        )
    paths: set[Path] = set()
    for sheet in document["sheets"]:
        if not isinstance(sheet, dict) or not isinstance(sheet.get("path"), str):
            raise ValueError("existing review manifest has invalid sheet paths")
        raw = Path(sheet["path"])
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError("existing review manifest has unsafe sheet paths")
        path = (ROOT / raw).resolve()
        repo_relative(path)
        if path.parent != output.resolve() or path.suffix.lower() != ".png":
            raise ValueError("existing review manifest has unsafe sheet paths")
        paths.add(path)
    return paths


def prepare_output(
    output: Path, planned_paths: set[Path], *, overwrite: bool
) -> set[Path]:
    if output.resolve() == ROOT.resolve():
        raise ValueError("review output cannot be the repository root")
    repo_relative(output)
    if output.is_symlink():
        raise ValueError("review output cannot be a symbolic link")
    if output.exists() and not output.is_dir():
        raise ValueError("review output must be a directory")
    if not output.exists() or not any(output.iterdir()):
        return set()
    if not overwrite:
        raise ValueError(
            "review output already exists; pass --overwrite to replace sheets"
        )

    manifest_path = output / "manifest.json"
    previous_sheets: set[Path]
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError("existing review manifest must be a JSON object")
        previous_sheets = _manifest_sheet_paths(existing, output)
        allowed = previous_sheets | {manifest_path.resolve()}
    else:
        previous_sheets = {
            path.resolve() for path in planned_paths if path.resolve().is_file()
        }
        allowed = set(previous_sheets)

    entries = list(output.iterdir())
    if any(entry.is_dir() or entry.resolve() not in allowed for entry in entries):
        raise ValueError(
            "review output contains unrecognized artifacts; refusing overwrite"
        )
    return previous_sheets


def build_review(
    scorecard: Path,
    matrix: Path | None,
    output: Path,
    *,
    expected_seeds: int,
    cases_per_sheet: int,
    overwrite: bool,
) -> dict[str, Any]:
    if expected_seeds < 1:
        raise ValueError("expected_seeds must be at least 1")
    if cases_per_sheet < 1:
        raise ValueError("cases_per_sheet must be at least 1")
    repo_relative(scorecard)
    if matrix is not None:
        repo_relative(matrix)
        matrix_jobs, factors_by_case, seeds = load_matrix(
            matrix, expected_seeds=expected_seeds
        )
        rows = load_scorecard(scorecard, matrix_jobs)
    else:
        rows, factors_by_case, seeds = load_standalone_scorecard(
            scorecard, expected_seeds=expected_seeds
        )
    aliases = assign_aliases(rows)
    planned = sheet_plan(rows, aliases, output, cases_per_sheet=cases_per_sheet)
    planned_paths = {sheet["path"].resolve() for sheet in planned}
    previous_sheets = prepare_output(output, planned_paths, overwrite=overwrite)
    document = manifest_document(
        scorecard,
        matrix,
        rows,
        factors_by_case,
        aliases,
        planned,
        seeds,
        expected_seeds=expected_seeds,
        cases_per_sheet=cases_per_sheet,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-stage-", dir=output.parent
    ) as stage_name:
        stage = Path(stage_name)
        staged: list[tuple[Path, Path]] = []
        for sheet in planned:
            staged_path = stage / sheet["path"].name
            render_sheet(
                f"{sheet['mode']} {sheet['sheet_index']}/{sheet['sheet_count_for_mode']}",
                sheet["rows"],
                staged_path,
                expected_seeds,
            )
            if not staged_path.is_file():
                raise RuntimeError("contact sheet renderer did not create its output")
            staged.append((staged_path, sheet["path"]))

        output.mkdir(parents=True, exist_ok=True)
        for staged_path, final_path in staged:
            staged_path.replace(final_path)

    stale = previous_sheets - planned_paths
    for path in sorted(stale):
        if path.exists() or path.is_symlink():
            path.unlink()
    manifest_temp = output / ".manifest.json.tmp"
    manifest_temp.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_temp.replace(output / "manifest.json")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build privacy-safe contact sheets for a resolved prompt-matrix scorecard"
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-seeds", type=int, default=DEFAULT_EXPECTED_SEEDS)
    parser.add_argument("--cases-per-sheet", type=int, default=DEFAULT_CASES_PER_SHEET)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.expected_seeds < 1:
            raise ValueError("--expected-seeds must be at least 1")
        if args.cases_per_sheet < 1:
            raise ValueError("--cases-per-sheet must be at least 1")
        output = args.output or args.scorecard.parent / "review"
        document = build_review(
            args.scorecard,
            args.matrix,
            output,
            expected_seeds=args.expected_seeds,
            cases_per_sheet=args.cases_per_sheet,
            overwrite=args.overwrite,
        )
        print(
            f"Built {document['sheet_count']} contact sheet(s) for "
            f"{document['case_count']} case(s) across {len(document['modes'])} mode(s)."
        )
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {redact_error(str(exc), None)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
