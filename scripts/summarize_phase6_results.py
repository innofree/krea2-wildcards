#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from run_remote_prompt_matrix import load_jobs
from summarize_results import METRICS, parse_boolean, parse_metric


MINIMUM_SEEDS = 3
MINIMUM_PAIRWISE_CASES = 96
MINIMUM_PRESETS = 100
MINIMUM_RANDOM_SAMPLES = 20
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH_FIELDS = ("matrix_path", "scored_path")
EVIDENCE_DIGEST_FIELDS = ("matrix_sha256", "scored_sha256")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_repository_input(path: Path, *, field: str) -> tuple[Path, str]:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe repository-relative path")
    resolved = (ROOT / path).resolve()
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"{field} must remain inside the repository") from exc
    if not resolved.is_file():
        raise ValueError(f"{field} must reference an existing repository file")
    return resolved, relative.as_posix()


def evidence_metadata(
    matrix: Path,
    scored: Path,
    *,
    matrix_path: str,
    scored_path: str,
) -> dict[str, str]:
    return {
        "matrix_path": matrix_path,
        "matrix_sha256": file_sha256(matrix),
        "scored_path": scored_path,
        "scored_sha256": file_sha256(scored),
    }


def validate_report_freshness(
    report: dict[str, Any],
    matrix: Path,
    scored: Path,
    *,
    matrix_path: str,
    scored_path: str,
) -> None:
    expected = evidence_metadata(
        matrix,
        scored,
        matrix_path=matrix_path,
        scored_path=scored_path,
    )
    if any(report.get(field) != expected[field] for field in EVIDENCE_PATH_FIELDS):
        raise ValueError("report evidence path mismatch")
    if any(report.get(field) != expected[field] for field in EVIDENCE_DIGEST_FIELDS):
        raise ValueError("report evidence digest mismatch")


def _load_scored(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("scored result contains no rows")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        test_id = (row.get("test_id") or "").strip()
        if not test_id or test_id in seen:
            raise ValueError(f"line {line_number}: test_id is missing or duplicated")
        seen.add(test_id)
        try:
            seed = int((row.get("seed") or "").strip())
            factors = json.loads((row.get("factors_json") or "{}").strip())
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"line {line_number}: seed or factors_json is invalid"
            ) from exc
        if not isinstance(factors, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in factors.items()
        ):
            raise ValueError(
                f"line {line_number}: factors_json must contain text pairs"
            )
        values: dict[str, Any] = {
            "test_id": test_id,
            "style_id": (row.get("style_id") or "").strip(),
            "mode": (row.get("mode") or "").strip(),
            "seed": seed,
            "factors": factors,
            "critical_failure": parse_boolean(
                row.get("critical_failure"),
                field=f"line {line_number}.critical_failure",
            ),
        }
        if not values["style_id"] or not values["mode"]:
            raise ValueError(f"line {line_number}: style_id and mode are required")
        for metric in METRICS:
            values[metric] = parse_metric(
                row.get(metric), field=f"line {line_number}.{metric}"
            )
        validated.append(values)
    return validated


def _cross_check(
    jobs: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    expected = {job["test_id"]: job for job in jobs}
    actual = {row["test_id"]: row for row in rows}
    if set(actual) != set(expected):
        raise ValueError(
            "scored result does not exactly cover the matrix; "
            f"missing={len(set(expected) - set(actual))}, extra={len(set(actual) - set(expected))}"
        )
    ordered: list[dict[str, Any]] = []
    for job in jobs:
        row = actual[job["test_id"]]
        for key in ("style_id", "mode", "seed", "factors"):
            if row[key] != job[key]:
                raise ValueError(
                    f"scored result metadata differs from matrix for {job['test_id']}"
                )
        ordered.append(row)
    return ordered


def _averages(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        metric: round(sum(float(row[metric]) for row in rows) / len(rows), 3)
        for metric in METRICS
    }


def _case_groups(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["style_id"], row["mode"])].append(row)
    return grouped


def _validate_case_seeds(
    groups: dict[tuple[str, str], list[dict[str, Any]]],
) -> set[int]:
    seed_sets = [{row["seed"] for row in case_rows} for case_rows in groups.values()]
    if any(len(seeds) < MINIMUM_SEEDS for seeds in seed_sets):
        raise ValueError(f"every case requires at least {MINIMUM_SEEDS} distinct seeds")
    if any(
        len(seeds) != len(case_rows)
        for seeds, case_rows in zip(seed_sets, groups.values())
    ):
        raise ValueError("a case contains duplicate seeds")
    first = seed_sets[0]
    if any(seeds != first for seeds in seed_sets[1:]):
        raise ValueError("all cases must use the same seed set")
    return first


def _quality_passed(rows: list[dict[str, Any]]) -> bool:
    averages = _averages(rows)
    return (
        not any(row["critical_failure"] for row in rows)
        and averages["prompt_adherence"] >= 4
        and averages["style_fidelity"] >= 3
        and averages["stability"] >= 3
        and averages["compatibility"] >= 3
    )


def summarize(
    kind: str, jobs: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    rows = _cross_check(jobs, rows)
    groups = _case_groups(rows)
    seeds = _validate_case_seeds(groups)
    critical_failures = sum(bool(row["critical_failure"]) for row in rows)
    common: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed",
        "complete": True,
        "matrix_jobs": len(jobs),
        "distinct_seeds": len(seeds),
        "seeds": sorted(seeds),
        "metrics": _averages(rows),
    }

    if kind == "single-axis":
        axes = sorted({row["factors"].get("axis") for row in rows})
        valid = (
            {"linework", "coloring"}.issubset(set(axes))
            and len(groups) >= 4
            and critical_failures == 0
            and _quality_passed(rows)
        )
        common.update(
            {
                "report_type": "single_axis_coverage",
                "tested_axes": axes,
                "total_cases": len(groups),
                "critical_failures": critical_failures,
                "complete": valid,
                "status": "passed" if valid else "failed",
            }
        )
    elif kind == "pairwise":
        pair_types = sorted({row["factors"].get("pair_type") for row in rows})
        valid = (
            len(groups) >= MINIMUM_PAIRWISE_CASES
            and len(pair_types) == 6
            and critical_failures == 0
            and _quality_passed(rows)
        )
        common.update(
            {
                "report_type": "pairwise_coverage",
                "covered_pair_types": pair_types,
                "cases_per_pair_type": dict(
                    sorted(
                        Counter(
                            case_rows[0]["factors"]["pair_type"]
                            for case_rows in groups.values()
                        ).items()
                    )
                ),
                "total_cases": len(groups),
                "critical_failures": critical_failures,
                "complete": valid,
                "status": "passed" if valid else "failed",
            }
        )
    elif kind == "presets":
        valid = (
            len(groups) >= MINIMUM_PRESETS
            and critical_failures == 0
            and _quality_passed(rows)
        )
        common.update(
            {
                "report_type": "preset_conflict_audit",
                "presets_tested": len(groups),
                "critical_conflicts": critical_failures,
                "complete": valid,
                "status": "passed" if valid else "failed",
            }
        )
    elif kind == "random-utility":
        usable = sum(_quality_passed(case_rows) for case_rows in groups.values())
        valid = len(groups) >= MINIMUM_RANDOM_SAMPLES
        common.update(
            {
                "report_type": "random_utility",
                "sample_count": len(groups),
                "usable_count": usable,
                "utility_rate": round(usable / len(groups), 3),
                "critical_failures": critical_failures,
                "complete": valid,
                "status": "passed" if valid else "failed",
            }
        )
    elif kind == "benchmark":
        valid = len(seeds) >= 5 and len(rows) >= 5
        common.update(
            {
                "report_type": "krea2_turbo_benchmark",
                "model": "krea2_turbo_mxfp8",
                "sample_count": len(rows),
                "critical_failures": critical_failures,
                "complete": valid,
                "status": "passed" if valid else "failed",
            }
        )
    elif kind == "artist-abc":
        by_artist: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in rows:
            by_artist[row["style_id"]][row["mode"]].append(row)
        required_modes = {"native_name", "visual_signature", "hybrid"}
        recommendations: dict[str, str] = {}
        for artist_id, modes in sorted(by_artist.items()):
            if set(modes) != required_modes:
                raise ValueError(f"{artist_id} does not cover all A/B/C modes")
            viable = {
                mode: values
                for mode, values in modes.items()
                if not any(row["critical_failure"] for row in values)
            }
            if not viable:
                raise ValueError(f"{artist_id} has no recommendable A/B/C mode")
            recommendations[artist_id] = max(
                viable,
                key=lambda mode: (
                    _averages(viable[mode])["style_fidelity"],
                    _averages(viable[mode])["stability"],
                    _averages(viable[mode])["prompt_adherence"],
                    _averages(viable[mode])["compatibility"],
                    mode == "visual_signature",
                ),
            )
        valid = bool(by_artist) and critical_failures == 0
        common.update(
            {
                "report_type": "artist_abc_coverage",
                "modes": sorted(required_modes),
                "artist_count": len(by_artist),
                "recommended_modes_recorded": len(recommendations),
                "recommended_modes": recommendations,
                "critical_failures": critical_failures,
                "complete": valid,
                "status": "passed" if valid else "failed",
            }
        )
    else:
        raise ValueError(f"unsupported summary kind: {kind}")
    return common


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize cross-checked Phase 6 image reviews"
    )
    parser.add_argument(
        "kind",
        choices=(
            "single-axis",
            "pairwise",
            "presets",
            "random-utility",
            "benchmark",
            "artist-abc",
        ),
    )
    parser.add_argument("scored", type=Path)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        matrix, matrix_path = safe_repository_input(args.matrix, field="matrix")
        scored, scored_path = safe_repository_input(args.scored, field="scored")
        initial_evidence = evidence_metadata(
            matrix,
            scored,
            matrix_path=matrix_path,
            scored_path=scored_path,
        )
        document = summarize(args.kind, load_jobs(matrix), _load_scored(scored))
        final_evidence = evidence_metadata(
            matrix,
            scored,
            matrix_path=matrix_path,
            scored_path=scored_path,
        )
        if final_evidence != initial_evidence:
            raise ValueError("Phase 6 evidence input changed while summarizing")
        document.update(final_evidence)
        validate_report_freshness(
            document,
            matrix,
            scored,
            matrix_path=matrix_path,
            scored_path=scored_path,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"Wrote {document['report_type']} report: "
            f"status={document['status']} complete={document['complete']}."
        )
        return 0 if document["complete"] else 1
    except OSError:
        print("ERROR: unable to read or write Phase 6 evidence files")
        return 2
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
