from __future__ import annotations

import json
from pathlib import Path

from run_remote_catalog_batch import catalog_jobs, limit_style_jobs, pending_jobs


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


def test_resume_accepts_only_complete_matching_runs(tmp_path: Path) -> None:
    source_image = (
        ROOT
        / "tests/reports/production_smoke_v0_1/runs/crystal_iris_pastel_seed_6006/image_01.png"
    )
    output = tmp_path / "batch"
    run_dir = output / "runs/example_style_seed_42"
    run_dir.mkdir(parents=True)
    image = run_dir / "image_01.png"
    image.write_bytes(source_image.read_bytes())
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
