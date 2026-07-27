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
