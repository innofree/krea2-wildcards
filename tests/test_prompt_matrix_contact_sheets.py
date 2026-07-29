from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import build_prompt_matrix_contact_sheets as matrix_sheets


def write_fixture(
    root: Path,
    *,
    cases: tuple[tuple[str, str], ...] = (
        ("reference", "beta_style"),
        ("native", "zeta_style"),
        ("native", "alpha_style"),
    ),
    seeds: tuple[int, ...] = (101, 202),
) -> tuple[Path, Path, list[dict[str, str]]]:
    matrix = root / "tests/prompt_matrix/resolved_fixture.jsonl"
    scorecard = root / "tests/reports/resolved_fixture/scorecard.csv"
    matrix.parent.mkdir(parents=True)
    scorecard.parent.mkdir(parents=True)
    jobs: list[dict[str, object]] = []
    score_rows: list[dict[str, str]] = []
    index = 0
    for mode, style_id in cases:
        for seed in seeds:
            index += 1
            test_id = f"PM{index:06d}"
            image = scorecard.parent / "runs" / test_id / "image_01.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fixture image")
            jobs.append(
                {
                    "schema_version": 1,
                    "test_id": test_id,
                    "style_id": style_id,
                    "label": f"Private Display Label {index}",
                    "mode": mode,
                    "seed": seed,
                    "prompt": f"SECRET_PROMPT_CONTENT for resolved case {index}",
                    "factors": {"camera": "eye_level"},
                }
            )
            score_rows.append(
                {
                    "test_id": test_id,
                    "style_id": style_id,
                    "mode": mode,
                    "seed": str(seed),
                    "image_path": image.relative_to(root).as_posix(),
                }
            )
    matrix.write_text(
        "".join(json.dumps(job) + "\n" for job in reversed(jobs)),
        encoding="utf-8",
    )
    write_scorecard(scorecard, list(reversed(score_rows)))
    return matrix, scorecard, score_rows


def write_scorecard(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["test_id", "style_id", "mode", "seed", "image_path"],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_standalone_fixture(
    root: Path,
    *,
    cases: tuple[tuple[str, str], ...] = (
        ("reference", "beta_style"),
        ("reference", "alpha_style"),
    ),
    seeds: tuple[int, ...] = (101, 202, 303, 404, 505),
) -> tuple[Path, list[dict[str, str]]]:
    scorecard = root / "tests/reports/merged_fixture/scorecard.csv"
    scorecard.parent.mkdir(parents=True)
    rows: list[dict[str, str]] = []
    index = 0
    for mode, style_id in cases:
        for seed_index, seed in enumerate(seeds):
            index += 1
            image = scorecard.parent / "images" / f"image_{index:03d}.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"fixture image")
            rows.append(
                {
                    "test_id": f"REUSED{seed_index % 3:03d}",
                    "style_id": style_id,
                    "mode": mode,
                    "seed": str(seed),
                    "image_path": image.relative_to(root).as_posix(),
                    "factors_json": json.dumps({"camera": "eye_level"}),
                    "prompt": "SECRET_MERGED_PROMPT",
                    "label": "Private Merged Label",
                    "endpoint": "SHOULD_NOT_PERSIST",
                }
            )
    write_standalone_scorecard(scorecard, rows)
    return scorecard, rows


def write_standalone_scorecard(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "test_id",
                "style_id",
                "mode",
                "seed",
                "image_path",
                "factors_json",
                "prompt",
                "label",
                "endpoint",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_mixed_artist_standalone_fixture(
    root: Path,
    *,
    repair_profile: str = "artist_visual_signature_repair_v0_8_3",
    repair_pilot_seeds: tuple[int, int, int] = (6101, 6202, 6303),
) -> tuple[Path, list[dict[str, str]]]:
    scorecard = root / "tests/reports/mixed_artist_fixture/scorecard.csv"
    scorecard.parent.mkdir(parents=True)
    rows: list[dict[str, str]] = []
    profiles = (
        ("artist_legacy", (1001, 2002, 3003, 4004, 5005), None),
        (
            "artist_repair",
            (*repair_pilot_seeds, 4004, 5005),
            repair_profile,
        ),
    )
    for style_id, seeds, profile in profiles:
        for seed in seeds:
            image = scorecard.parent / "images" / f"{style_id}_{seed}.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"fixture image")
            factors = {
                "line_language": "crisp_measured",
            }
            if profile is not None:
                factors["evaluated_prompt_sha256"] = "sha256_" + "a" * 64
                factors["benchmark_profile"] = profile
                factors["benchmark_stage"] = (
                    "pilot" if seed in set(repair_pilot_seeds) else "extension"
                )
            elif seed in {4004, 5005}:
                factors["evaluated_prompt_sha256"] = "sha256_" + "a" * 64
            rows.append(
                {
                    "test_id": f"MIXED{len(rows) + 1:03d}",
                    "style_id": style_id,
                    "mode": "visual_signature",
                    "seed": str(seed),
                    "image_path": image.relative_to(root).as_posix(),
                    "factors_json": json.dumps(factors, sort_keys=True),
                    "prompt": "MUST_NOT_PERSIST",
                    "label": "Private Label",
                    "endpoint": "MUST_NOT_PERSIST",
                }
            )
    write_standalone_scorecard(scorecard, rows)
    return scorecard, rows


def nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value))
    return set()


def test_build_groups_modes_assigns_sorted_aliases_and_excludes_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, _ = write_fixture(tmp_path)
    output = scorecard.parent / "review"
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    rendered: list[tuple[str, list[dict[str, Any]], Path, int]] = []

    def fake_render(
        title: str,
        rows: list[dict[str, Any]],
        sheet: Path,
        expected_seeds: int,
    ) -> None:
        rendered.append((title, rows, sheet, expected_seeds))
        sheet.write_bytes(b"sheet")

    monkeypatch.setattr(matrix_sheets, "render_sheet", fake_render)
    document = matrix_sheets.build_review(
        scorecard,
        matrix,
        output,
        expected_seeds=2,
        cases_per_sheet=1,
        overwrite=False,
    )

    assert [
        (case["alias"], case["mode"], case["style_id"]) for case in document["cases"]
    ] == [
        ("case_001", "native", "alpha_style"),
        ("case_002", "native", "zeta_style"),
        ("case_003", "reference", "beta_style"),
    ]
    assert document["case_count"] == 3
    assert document["image_count"] == 6
    assert document["sheet_count"] == len(rendered) == 3
    assert document["modes"]["native"]["sheet_count"] == 2
    assert document["modes"]["reference"]["sheet_count"] == 1
    assert all(expected == 2 for *_, expected in rendered)
    assert all(
        {
            "alias",
            "test_id",
            "style_id",
            "mode",
            "seed",
            "factors",
            "image",
            "image_path",
        }
        == set(row)
        for _, rows, _, _ in rendered
        for row in rows
    )

    raw = (output / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(raw)
    assert "SECRET_PROMPT_CONTENT" not in raw
    assert "Private Display Label" not in raw
    assert {"prompt", "label", "endpoint", "api_url", "remote"}.isdisjoint(
        nested_keys(manifest)
    )
    assert set(manifest["cases"][0]["items"][0]) == {
        "test_id",
        "seed",
        "image_path",
    }
    assert manifest["cases"][0]["factors"] == {"camera": "eye_level"}

    first_content = raw
    matrix_sheets.build_review(
        scorecard,
        matrix,
        output,
        expected_seeds=2,
        cases_per_sheet=1,
        overwrite=True,
    )
    assert (output / "manifest.json").read_text(encoding="utf-8") == first_content


def test_render_sheet_uses_only_alias_and_seed_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    images = []
    for index in range(4):
        image = tmp_path / f"private_source_{index}.png"
        image.write_bytes(b"fixture")
        images.append(image)
    rows = [
        {"alias": alias, "seed": seed, "image": image}
        for (alias, seed), image in zip(
            [
                ("case_002", 202),
                ("case_001", 202),
                ("case_002", 101),
                ("case_001", 101),
            ],
            images,
            strict=True,
        )
    ]
    command: list[str] = []

    def fake_run(args: list[str], **_: object) -> SimpleNamespace:
        command.extend(args)
        Path(args[-1]).write_bytes(b"sheet")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(matrix_sheets.shutil, "which", lambda _: "/usr/bin/montage")
    monkeypatch.setattr(matrix_sheets.subprocess, "run", fake_run)
    output = tmp_path / "sheet.png"
    matrix_sheets.render_sheet("native 1/1", rows, output, 2)

    input_start = command.index("%t") + 1
    input_end = command.index("-thumbnail")
    labels = [Path(value).stem for value in command[input_start:input_end]]
    assert labels == [
        "case_001__101",
        "case_001__202",
        "case_002__101",
        "case_002__202",
    ]
    assert all("private_source" not in label for label in labels)


def test_scorecard_requires_exact_matrix_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, score_rows = write_fixture(tmp_path)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    write_scorecard(scorecard, score_rows[:-1])
    matrix_jobs, _, _ = matrix_sheets.load_matrix(matrix, expected_seeds=2)

    with pytest.raises(ValueError, match="does not cover 1 matrix test"):
        matrix_sheets.load_scorecard(scorecard, matrix_jobs)


def test_scorecard_rejects_extra_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, score_rows = write_fixture(tmp_path)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    extra = dict(score_rows[0])
    extra["test_id"] = "EXTRA001"
    write_scorecard(scorecard, [*score_rows, extra])
    matrix_jobs, _, _ = matrix_sheets.load_matrix(matrix, expected_seeds=2)

    with pytest.raises(ValueError, match="test_id is absent from matrix"):
        matrix_sheets.load_scorecard(scorecard, matrix_jobs)


def test_matrix_rejects_missing_or_inconsistent_seed_sets(tmp_path: Path) -> None:
    matrix, _, _ = write_fixture(tmp_path)
    jobs = [
        json.loads(line) for line in matrix.read_text(encoding="utf-8").splitlines()
    ]
    jobs = [
        job
        for job in jobs
        if not (job["style_id"] == "alpha_style" and job["seed"] == 202)
    ]
    matrix.write_text("".join(json.dumps(job) + "\n" for job in jobs), encoding="utf-8")

    with pytest.raises(ValueError, match="expected exactly 2 seeds"):
        matrix_sheets.load_matrix(matrix, expected_seeds=2)

    for job in jobs:
        if job["style_id"] == "alpha_style" and job["seed"] == 101:
            replacement = dict(job)
            replacement["test_id"] = "PM999999"
            replacement["seed"] = 303
            jobs.append(replacement)
            break
    matrix.write_text("".join(json.dumps(job) + "\n" for job in jobs), encoding="utf-8")
    with pytest.raises(ValueError, match="same seed set"):
        matrix_sheets.load_matrix(matrix, expected_seeds=2)


def test_scorecard_rejects_missing_image_and_duplicate_case_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, score_rows = write_fixture(tmp_path)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    matrix_jobs, _, _ = matrix_sheets.load_matrix(matrix, expected_seeds=2)
    missing = tmp_path / score_rows[0]["image_path"]
    missing.unlink()

    with pytest.raises(ValueError, match="image is missing"):
        matrix_sheets.load_scorecard(scorecard, matrix_jobs)

    missing.write_bytes(b"fixture")
    write_scorecard(scorecard, [*score_rows, dict(score_rows[0])])
    with pytest.raises(ValueError, match="duplicate test_id and case seed"):
        matrix_sheets.load_scorecard(scorecard, matrix_jobs)


def test_scorecard_and_output_reject_paths_outside_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    matrix, scorecard, score_rows = write_fixture(repo)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fixture")
    score_rows[0]["image_path"] = str(outside)
    write_scorecard(scorecard, score_rows)
    monkeypatch.setattr(matrix_sheets, "ROOT", repo)
    matrix_jobs, _, _ = matrix_sheets.load_matrix(matrix, expected_seeds=2)

    with pytest.raises(ValueError, match="safe repository-relative path"):
        matrix_sheets.load_scorecard(scorecard, matrix_jobs)

    with pytest.raises(ValueError, match="artifacts must remain inside"):
        matrix_sheets.prepare_output(
            tmp_path / "outside-review", set(), overwrite=False
        )

    private_identity = ".".join(("10", "20", "30", "40"))
    identity_path = repo / "tests/reports" / private_identity / "image.png"
    identity_path.parent.mkdir(parents=True)
    identity_path.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="forbidden connection data"):
        matrix_sheets.repo_relative(identity_path)


def test_scorecard_only_build_accepts_five_seed_merge_with_reused_test_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scorecard, _ = write_standalone_fixture(tmp_path)
    output = scorecard.parent / "review"
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)

    def fake_render(
        _: str, rows: list[dict[str, Any]], sheet: Path, expected_seeds: int
    ) -> None:
        assert len(rows) == 10
        assert expected_seeds == 5
        sheet.write_bytes(b"sheet")

    monkeypatch.setattr(matrix_sheets, "render_sheet", fake_render)
    document = matrix_sheets.build_review(
        scorecard,
        None,
        output,
        expected_seeds=5,
        cases_per_sheet=10,
        overwrite=False,
    )

    assert document["matrix"] is None
    assert document["seeds"] == [101, 202, 303, 404, 505]
    assert document["case_count"] == 2
    assert document["image_count"] == 10
    assert [case["alias"] for case in document["cases"]] == [
        "case_001",
        "case_002",
    ]
    assert [case["style_id"] for case in document["cases"]] == [
        "alpha_style",
        "beta_style",
    ]
    assert all(len(case["items"]) == 5 for case in document["cases"])
    assert any(
        len({item["test_id"] for item in case["items"]}) < 5
        for case in document["cases"]
    )

    raw = (output / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(raw)
    assert "SECRET_MERGED_PROMPT" not in raw
    assert "Private Merged Label" not in raw
    assert "SHOULD_NOT_PERSIST" not in raw
    assert {"prompt", "label", "endpoint", "api_url", "remote"}.isdisjoint(
        nested_keys(manifest)
    )


def test_scorecard_only_rejects_duplicate_case_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scorecard, rows = write_standalone_fixture(tmp_path)
    duplicate = dict(rows[0])
    duplicate["test_id"] = "DIFFERENT001"
    write_standalone_scorecard(scorecard, [*rows, duplicate])
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="duplicate style/mode and seed"):
        matrix_sheets.load_standalone_scorecard(scorecard, expected_seeds=5)


def test_scorecard_only_rejects_malformed_unsafe_or_inconsistent_factors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scorecard, rows = write_standalone_fixture(tmp_path)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)

    malformed = [dict(row) for row in rows]
    malformed[0]["factors_json"] = "{broken"
    write_standalone_scorecard(scorecard, malformed)
    with pytest.raises(ValueError, match="factors_json must be valid JSON"):
        matrix_sheets.load_standalone_scorecard(scorecard, expected_seeds=5)

    unsafe = [dict(row) for row in rows]
    unsafe[0]["factors_json"] = json.dumps({"bad key": "eye_level"})
    write_standalone_scorecard(scorecard, unsafe)
    with pytest.raises(ValueError, match="invalid factor name"):
        matrix_sheets.load_standalone_scorecard(scorecard, expected_seeds=5)

    inconsistent = [dict(row) for row in rows]
    inconsistent[1]["factors_json"] = json.dumps({"camera": "low_angle"})
    write_standalone_scorecard(scorecard, inconsistent)
    with pytest.raises(ValueError, match="factors must remain constant"):
        matrix_sheets.load_standalone_scorecard(scorecard, expected_seeds=5)


def test_scorecard_only_accepts_exact_mixed_artist_profiles_and_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scorecard, _ = write_mixed_artist_standalone_fixture(tmp_path)
    output = scorecard.parent / "review"
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)

    def fake_render(
        _: str, rows: list[dict[str, Any]], sheet: Path, expected_seeds: int
    ) -> None:
        assert len(rows) == 10
        assert expected_seeds == 5
        sheet.write_bytes(b"sheet")

    monkeypatch.setattr(matrix_sheets, "render_sheet", fake_render)
    document = matrix_sheets.build_review(
        scorecard,
        None,
        output,
        expected_seeds=5,
        cases_per_sheet=10,
        overwrite=False,
    )

    assert document["seeds"] == [1001, 2002, 3003, 4004, 5005, 6101, 6202, 6303]
    cases = {case["style_id"]: case for case in document["cases"]}
    assert "benchmark_stages" not in cases["artist_legacy"]
    assert (
        cases["artist_legacy"]["factors"]["evaluated_prompt_sha256"]
        == "sha256_" + "a" * 64
    )
    repair = cases["artist_repair"]
    assert repair["benchmark_stages"] == ["extension", "pilot"]
    assert "benchmark_stage" not in repair["factors"]
    assert repair["factors"]["evaluated_prompt_sha256"] == "sha256_" + "a" * 64
    assert {
        (item["seed"], item["benchmark_stage"]) for item in repair["items"]
    } == {
        (6101, "pilot"),
        (6202, "pilot"),
        (6303, "pilot"),
        (4004, "extension"),
        (5005, "extension"),
    }


def test_scorecard_only_accepts_reinforced_axis_repair_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scorecard, _ = write_mixed_artist_standalone_fixture(
        tmp_path,
        repair_profile=(
            "artist_visual_signature_repair_reinforced_axis_v0_8_8"
        ),
        repair_pilot_seeds=(13101, 13202, 13303),
    )
    output = scorecard.parent / "review"
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)

    def fake_render(
        _: str, rows: list[dict[str, Any]], sheet: Path, expected_seeds: int
    ) -> None:
        assert len(rows) == 10
        assert expected_seeds == 5
        sheet.write_bytes(b"sheet")

    monkeypatch.setattr(matrix_sheets, "render_sheet", fake_render)
    document = matrix_sheets.build_review(
        scorecard,
        None,
        output,
        expected_seeds=5,
        cases_per_sheet=10,
        overwrite=False,
    )
    repair = next(
        case for case in document["cases"] if case["style_id"] == "artist_repair"
    )
    assert {
        (item["seed"], item["benchmark_stage"]) for item in repair["items"]
    } == {
        (13101, "pilot"),
        (13202, "pilot"),
        (13303, "pilot"),
        (4004, "extension"),
        (5005, "extension"),
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("digest", "may vary only benchmark_stage"),
        ("stage", "expected 'pilot'"),
        ("seed", "does not contain its exact 5-seed set"),
        ("missing_digest", "missing a valid evaluated prompt digest"),
    ),
)
def test_scorecard_only_mixed_artist_profiles_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    scorecard, rows = write_mixed_artist_standalone_fixture(tmp_path)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    repair_rows = [row for row in rows if row["style_id"] == "artist_repair"]
    target = next(row for row in repair_rows if row["seed"] == "6202")
    factors = json.loads(target["factors_json"])
    if mutation == "digest":
        factors["evaluated_prompt_sha256"] = "sha256_" + "b" * 64
        target["factors_json"] = json.dumps(factors, sort_keys=True)
    elif mutation == "stage":
        factors["benchmark_stage"] = "extension"
        target["factors_json"] = json.dumps(factors, sort_keys=True)
    elif mutation == "seed":
        target["seed"] = "7777"
    else:
        del factors["evaluated_prompt_sha256"]
        target["factors_json"] = json.dumps(factors, sort_keys=True)
    write_standalone_scorecard(scorecard, rows)

    with pytest.raises(ValueError, match=message):
        matrix_sheets.load_standalone_scorecard(scorecard, expected_seeds=5)


@pytest.mark.parametrize("mutation", ("missing", "mismatch"))
def test_scorecard_only_mixed_legacy_extension_digest_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    scorecard, rows = write_mixed_artist_standalone_fixture(tmp_path)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    target = next(
        row
        for row in rows
        if row["style_id"] == "artist_legacy" and row["seed"] == "4004"
    )
    factors = json.loads(target["factors_json"])
    if mutation == "missing":
        del factors["evaluated_prompt_sha256"]
    else:
        factors["evaluated_prompt_sha256"] = "sha256_" + "b" * 64
    target["factors_json"] = json.dumps(factors, sort_keys=True)
    write_standalone_scorecard(scorecard, rows)

    with pytest.raises(
        ValueError,
        match="legacy extension prompt digests must be valid and identical",
    ):
        matrix_sheets.load_standalone_scorecard(scorecard, expected_seeds=5)


def _build_with_stub_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cases: tuple[tuple[str, str], ...],
    cases_per_sheet: int,
    spread_cases: bool,
) -> tuple[dict[str, Any], list[tuple[str, list[dict[str, Any]]]]]:
    matrix, scorecard, _ = write_fixture(tmp_path, cases=cases)
    monkeypatch.setattr(matrix_sheets, "ROOT", tmp_path)
    rendered: list[tuple[str, list[dict[str, Any]]]] = []

    def fake_render(
        title: str, rows: list[dict[str, Any]], sheet: Path, expected_seeds: int
    ) -> None:
        rendered.append((sheet.name, rows))
        sheet.write_bytes(b"sheet")

    monkeypatch.setattr(matrix_sheets, "render_sheet", fake_render)
    document = matrix_sheets.build_review(
        scorecard,
        matrix,
        scorecard.parent / "review",
        expected_seeds=2,
        cases_per_sheet=cases_per_sheet,
        overwrite=False,
        spread_cases=spread_cases,
    )
    return document, rendered


def test_manifest_records_which_cases_each_sheet_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-sheet verdict has to name the cases it covers.

    Aliases are numbered over the sorted case list before chunking, so under
    --spread-cases a sheet holds a strided selection that the alias order alone
    cannot reconstruct. Recording a verdict against the wrong case set is how a
    sheet review silently approves items it never displayed.
    """
    cases = tuple(("native", f"style_{index:02d}") for index in range(1, 13))
    document, rendered = _build_with_stub_render(
        tmp_path, monkeypatch, cases=cases, cases_per_sheet=4, spread_cases=True
    )

    assert document["spread_cases"] is True
    assert document["cases_per_sheet"] == 4
    assert [sheet["case_aliases"] for sheet in document["sheets"]] == [
        ["case_001", "case_004", "case_007", "case_010"],
        ["case_002", "case_005", "case_008", "case_011"],
        ["case_003", "case_006", "case_009", "case_012"],
    ]

    # The recorded aliases must be exactly what was drawn on that sheet.
    by_name = {name: rows for name, rows in rendered}
    for sheet in document["sheets"]:
        drawn = {row["alias"] for row in by_name[Path(sheet["path"]).name]}
        assert drawn == set(sheet["case_aliases"]), sheet["sheet_index"]


def test_sheet_case_aliases_partition_every_case_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = tuple(("native", f"style_{index:02d}") for index in range(1, 13))
    for spread in (False, True):
        document, _ = _build_with_stub_render(
            tmp_path / f"spread_{spread}",
            monkeypatch,
            cases=cases,
            cases_per_sheet=5,
            spread_cases=spread,
        )
        assert document["spread_cases"] is spread
        flat = [
            alias for sheet in document["sheets"] for alias in sheet["case_aliases"]
        ]
        assert sorted(flat) == [case["alias"] for case in document["cases"]], spread
        assert len(flat) == len(set(flat)) == document["case_count"], spread
