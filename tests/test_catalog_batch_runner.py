from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from run_remote_catalog_batch import catalog_jobs, limit_style_jobs, pending_jobs, write_scorecard


ROOT = Path(__file__).resolve().parents[1]


def test_completed_style_retest_matrix_has_16_styles_and_32_jobs() -> None:
    summary = json.loads(
        (ROOT / "tests/reports/style_retest_v0_4/approval_summary.json").read_text(
            encoding="utf-8"
        )
    )
    selected = {style["style_id"] for style in summary["styles"]}
    jobs = catalog_jobs(
        ROOT / "catalog/art_styles.yaml",
        ROOT / "catalog/family_templates.yaml",
        {"approved"},
        (4004, 5005),
        selected,
    )
    assert len({job["style_id"] for job in jobs}) == 16
    assert len(jobs) == 32
    assert len({job["family"] for job in jobs}) == 7


def test_completed_screen_manifest_retains_45_style_evidence() -> None:
    manifest = json.loads(
        (ROOT / "tests/reports/style_screen_v0_3/review/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["style_count"] == 45
    assert manifest["image_count"] == 135


def test_style_limit_keeps_every_seed_for_selected_styles() -> None:
    jobs = [
        {"style_id": style_id, "seed": seed}
        for style_id in ("one", "two", "three")
        for seed in (1001, 2002, 3003)
    ]
    limited = limit_style_jobs(jobs, 2)
    assert {job["style_id"] for job in limited} == {"one", "two"}
    assert len(limited) == 6


def _blank_png(width: int, height: int) -> bytes:
    """A real, decodable 8-bit greyscale PNG.

    Synthesised rather than copied out of tests/reports, because .gitignore keeps
    the generated images out of the repo and a fixture read from there only
    resolves in a checkout that happens to have leftovers. Resume validation only
    reads the IHDR dimensions, so the pixels are free to be blank.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


def test_resume_accepts_only_complete_matching_runs(tmp_path: Path) -> None:
    output = tmp_path / "batch"
    run_dir = output / "runs/example_style_seed_42"
    run_dir.mkdir(parents=True)
    image = run_dir / "image_01.png"
    image.write_bytes(_blank_png(1024, 1024))
    record = {
        "style_id": "example_style",
        "seed": 42,
        "remote": "private_comfyui",
        "images": [str(image)],
    }
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    jobs = [
        {
            "style_id": "example_style",
            "family": "example_family",
            "seed": 42,
            "template": Path("example.txt"),
        }
    ]

    assert pending_jobs(jobs, output, resume=True) == []


def test_scorecard_is_lf_only_and_stale_content_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "scorecard.csv"
    jobs = [{"style_id": "example_style", "seed": 42}]

    write_scorecard(path, jobs)
    assert b"\r" not in path.read_bytes()
    write_scorecard(path, jobs)
    path.write_text("stale\n", encoding="utf-8")

    try:
        write_scorecard(path, jobs)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("stale scorecard must be rejected")
