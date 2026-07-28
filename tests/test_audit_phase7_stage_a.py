from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import pytest
from PIL import Image

from audit_phase7_stage_a import audit


COLUMNS = ["test_id", "seed", "style_id", "mode", "factors_json", "image_path"]


def write_png(path: Path, *, flat: bool = False, size=(1024, 1024), tint=0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (128, 128, 128))
    if not flat:
        rng = random.Random(tint)
        pixels = [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(size[0] * size[1])
        ]
        image.putdata(pixels)
    image.save(path)


def build_run(
    tmp_path: Path,
    *,
    items: int = 2,
    seeds=(1001, 2002, 3003),
    flat_item: str | None = None,
    duplicate_item: str | None = None,
    drop_seed_item: str | None = None,
    failed_test_id: str | None = None,
) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "run"
    rows: list[dict[str, str]] = []
    jobs: dict[str, dict[str, object]] = {}
    counter = 0
    for index in range(items):
        style_id = f"effect_item_{index:03d}"
        for seed_index, seed in enumerate(seeds):
            if drop_seed_item == style_id and seed_index == len(seeds) - 1:
                continue
            counter += 1
            test_id = f"P7{counter:06d}"
            relative = Path("run") / "runs" / test_id / "image_01.png"
            write_png(
                tmp_path / relative,
                flat=flat_item == style_id,
                tint=0 if duplicate_item == style_id else counter,
            )
            rows.append(
                {
                    "test_id": test_id,
                    "seed": str(seed),
                    "style_id": style_id,
                    "mode": "mass_axis_effect",
                    "factors_json": "{}",
                    "image_path": relative.as_posix(),
                }
            )
            digest = f"{counter:064x}"
            if duplicate_item == style_id:
                digest = f"{0:064x}"
            jobs[test_id] = {
                "completion_status": "completed",
                "remote_status": "success",
                "image_sha256": digest,
            }
    if failed_test_id is not None:
        jobs[failed_test_id]["remote_status"] = "error"

    run_dir.mkdir(parents=True, exist_ok=True)
    scorecard = run_dir / "scorecard.csv"
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    run_state = run_dir / "run-state.json"
    run_state.write_text(
        json.dumps({"schema_version": 1, "jobs": jobs}), encoding="utf-8"
    )
    return scorecard, run_state, tmp_path


def run_audit(tmp_path: Path, **kwargs):
    scorecard, run_state, root = build_run(tmp_path, **kwargs)
    return audit(
        scorecard, run_state, axis="effect", expected_seeds=3, root=root
    )


def test_clean_run_passes_every_item(tmp_path: Path) -> None:
    report = run_audit(tmp_path)
    assert report["status"] == "passed"
    assert report["complete"] is True
    assert report["item_count"] == 2
    assert report["passed_count"] == 2
    assert report["failed_item_ids"] == []
    assert report["report_type"] == "phase7_stage_a_audit"


def test_flat_image_is_rejected_without_a_model_call(tmp_path: Path) -> None:
    report = run_audit(tmp_path, flat_item="effect_item_000")
    assert report["status"] == "failed"
    assert report["failed_item_ids"] == ["effect_item_000"]
    reasons = " ".join(report["items"]["effect_item_000"]["reasons"])
    assert "flat" in reasons or "degenerate" in reasons
    assert report["items"]["effect_item_001"]["passed"] is True


def test_seed_identical_output_is_rejected(tmp_path: Path) -> None:
    report = run_audit(tmp_path, duplicate_item="effect_item_001")
    assert report["failed_item_ids"] == ["effect_item_001"]
    assert "seeds produced identical images" in (
        report["items"]["effect_item_001"]["reasons"]
    )


def test_missing_seed_is_rejected(tmp_path: Path) -> None:
    report = run_audit(tmp_path, drop_seed_item="effect_item_000")
    assert report["failed_item_ids"] == ["effect_item_000"]
    assert report["items"]["effect_item_000"]["seed_count"] == 2
    assert any(
        "expected 3 distinct seed(s)" in reason
        for reason in report["items"]["effect_item_000"]["reasons"]
    )


def test_unsuccessful_remote_job_is_rejected(tmp_path: Path) -> None:
    report = run_audit(tmp_path, failed_test_id="P7000001")
    assert report["failed_item_ids"] == ["effect_item_000"]
    assert any(
        "remote_status" in reason
        for reason in report["items"]["effect_item_000"]["reasons"]
    )


def test_missing_image_is_rejected(tmp_path: Path) -> None:
    scorecard, run_state, root = build_run(tmp_path)
    rows = list(csv.DictReader(scorecard.open(encoding="utf-8")))
    (root / rows[0]["image_path"]).unlink()
    report = audit(scorecard, run_state, axis="effect", expected_seeds=3, root=root)
    assert report["failed_item_ids"] == ["effect_item_000"]
    assert any(
        "missing" in reason for reason in report["items"]["effect_item_000"]["reasons"]
    )


def test_wrong_resolution_is_rejected(tmp_path: Path) -> None:
    scorecard, run_state, root = build_run(tmp_path)
    rows = list(csv.DictReader(scorecard.open(encoding="utf-8")))
    write_png(root / rows[0]["image_path"], size=(512, 512), tint=99)
    report = audit(scorecard, run_state, axis="effect", expected_seeds=3, root=root)
    assert report["failed_item_ids"] == ["effect_item_000"]
    assert any(
        "512x512" in reason
        for reason in report["items"]["effect_item_000"]["reasons"]
    )


def test_frame_measurements_are_recorded(tmp_path: Path) -> None:
    report = run_audit(tmp_path)
    frames = report["items"]["effect_item_000"]["frames"]
    assert len(frames) == 3
    for frame in frames.values():
        assert frame["width"] == 1024
        assert frame["height"] == 1024
        assert frame["luminance_stddev"] > 4.0
        assert frame["luminance_levels"] >= 8


def test_invalid_expected_seeds_is_rejected(tmp_path: Path) -> None:
    scorecard, run_state, root = build_run(tmp_path)
    with pytest.raises(ValueError, match="expected_seeds"):
        audit(scorecard, run_state, axis="effect", expected_seeds=0, root=root)
