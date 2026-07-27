from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

import build_artist_native_contact_sheets as native_sheets


ROOT = Path(__file__).resolve().parents[1]


def write_fixture(
    root: Path,
    *,
    artist_count: int = 2,
    seeds: tuple[int, ...] = (1001, 2002),
) -> tuple[Path, Path, list[str]]:
    matrix = root / "tests/prompt_matrix/artist_native_name.jsonl"
    scorecard = root / "tests/reports/artist_native_fixture/scorecard.csv"
    matrix.parent.mkdir(parents=True)
    scorecard.parent.mkdir(parents=True)
    jobs: list[dict[str, object]] = []
    score_rows: list[dict[str, object]] = []
    canonical_names: list[str] = []
    index = 0
    for artist_index in range(1, artist_count + 1):
        artist_id = f"artist_{artist_index:03d}"
        canonical_name = f"Canonical Visible Name {artist_index}"
        canonical_names.append(canonical_name)
        for seed in seeds:
            index += 1
            test_id = f"AN{index:06d}"
            image = (
                root
                / "tests/reports/artist_native_fixture/runs"
                / test_id
                / "image_01.png"
            )
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fixture image")
            jobs.append(
                {
                    "schema_version": 1,
                    "test_id": test_id,
                    "style_id": artist_id,
                    "label": canonical_name,
                    "mode": "native_name",
                    "seed": seed,
                    "prompt": (
                        f"Create an original illustration using {canonical_name} as the only "
                        "artist-style reference. Depict one adult woman in a fixed studio."
                    ),
                }
            )
            score_rows.append(
                {
                    "test_id": test_id,
                    "style_id": artist_id,
                    "label": canonical_name,
                    "mode": "native_name",
                    "seed": seed,
                    "image_path": image.relative_to(root).as_posix(),
                }
            )
    matrix.write_text(
        "".join(json.dumps(job) + "\n" for job in jobs), encoding="utf-8"
    )
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["test_id", "style_id", "label", "mode", "seed", "image_path"],
        )
        writer.writeheader()
        writer.writerows(score_rows)
    return matrix, scorecard, canonical_names


def test_build_writes_redacted_native_manifest_and_bounded_sheets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, canonical_names = write_fixture(tmp_path)
    output = scorecard.parent / "review"
    monkeypatch.setattr(native_sheets.contact, "ROOT", tmp_path)
    rendered: list[tuple[str, list[dict[str, object]], Path, int]] = []

    def fake_render(
        title: str,
        rows: list[dict[str, object]],
        sheet: Path,
        expected_seeds: int,
    ) -> None:
        rendered.append((title, rows, sheet, expected_seeds))
        sheet.write_bytes(b"sheet")

    monkeypatch.setattr(native_sheets.contact, "render_sheet", fake_render)
    document = native_sheets.build_review(
        scorecard,
        matrix,
        output,
        expected_artists=2,
        expected_seeds=2,
        artists_per_sheet=1,
        overwrite=False,
        dry_run=False,
    )

    assert document["artist_count"] == 2
    assert document["image_count"] == 4
    assert len(document["sheets"]) == len(rendered) == 2
    assert all(title.startswith("artist_native_name ") for title, *_ in rendered)
    assert all(expected_seeds == 2 for *_, expected_seeds in rendered)
    assert all("label" not in row and "prompt" not in row for _, rows, _, _ in rendered for row in rows)
    raw = (output / "manifest.json").read_text(encoding="utf-8")
    assert all(name not in raw for name in canonical_names)
    manifest = json.loads(raw)

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert {"prompt", "label"}.isdisjoint(keys(manifest))
    assert set(document["items"][0]) == {"test_id", "artist_id", "seed", "image_path"}
    assert {item["artist_id"] for item in document["items"]} == {
        "artist_001",
        "artist_002",
    }


def test_cli_dry_run_validates_fixture_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    matrix, scorecard, canonical_names = write_fixture(tmp_path)
    output = scorecard.parent / "review"
    monkeypatch.setattr(native_sheets.contact, "ROOT", tmp_path)

    result = native_sheets.main(
        [
            str(scorecard),
            "--matrix",
            str(matrix),
            "--output",
            str(output),
            "--expected-artists",
            "2",
            "--expected-seeds",
            "2",
            "--artists-per-sheet",
            "1",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr().out
    assert result == 0
    assert "DRY RUN: 2 native artist(s), 4 image(s), 2 sheet(s)." in captured
    assert all(name not in captured for name in canonical_names)
    assert not output.exists()


def test_native_scorecard_requires_exact_matrix_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, _ = write_fixture(tmp_path)
    monkeypatch.setattr(native_sheets.contact, "ROOT", tmp_path)
    rows = list(csv.DictReader(scorecard.open(encoding="utf-8", newline="")))
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows[:-1])
    jobs = native_sheets.load_native_matrix(
        matrix, expected_artists=2, expected_seeds=2
    )

    with pytest.raises(ValueError, match="does not cover 1 native matrix test"):
        native_sheets.load_native_scorecard(scorecard, jobs)


def test_native_scorecard_rejects_image_outside_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    matrix, scorecard, _ = write_fixture(repo, artist_count=1, seeds=(1001,))
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fixture image")
    rows = list(csv.DictReader(scorecard.open(encoding="utf-8", newline="")))
    rows[0]["image_path"] = str(outside)
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(native_sheets.contact, "ROOT", repo)
    jobs = native_sheets.load_native_matrix(
        matrix, expected_artists=1, expected_seeds=1
    )

    with pytest.raises(ValueError, match="review artifacts must remain inside the repository"):
        native_sheets.load_native_scorecard(scorecard, jobs)


def test_native_scorecard_rejects_name_bearing_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix, scorecard, _ = write_fixture(tmp_path, artist_count=1, seeds=(1001,))
    rows = list(csv.DictReader(scorecard.open(encoding="utf-8", newline="")))
    named_image = scorecard.parent / "runs/Canonical Visible Name/image_01.png"
    named_image.parent.mkdir(parents=True)
    named_image.write_bytes(b"fixture image")
    rows[0]["image_path"] = named_image.relative_to(tmp_path).as_posix()
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(native_sheets.contact, "ROOT", tmp_path)
    jobs = native_sheets.load_native_matrix(
        matrix, expected_artists=1, expected_seeds=1
    )

    with pytest.raises(ValueError, match="redacted test_id run directory"):
        native_sheets.load_native_scorecard(scorecard, jobs)


def test_cli_help_describes_matrix_split_and_dry_run() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_artist_native_contact_sheets.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--matrix" in result.stdout
    assert "--artists-per-sheet" in result.stdout
    assert "--dry-run" in result.stdout
    assert "without catalog IDs" in " ".join(result.stdout.split())
