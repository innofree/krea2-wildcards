from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml
from PIL import Image

from screen_axis_saturation import screen


def _write_image(path: Path, rgb: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), rgb).save(path)


def _fixture(root: Path, entries: list[tuple[str, str, tuple[int, int, int]]]) -> tuple[Path, Path]:
    """entries: (item_id, coloring value, colour). One seed per item."""
    items = {
        item_id: {"family": "linework_coloring", "feature_axes": {"coloring": [value]}}
        for item_id, value, _ in entries
    }
    catalog = root / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"schema_version": 1, "items": items}, sort_keys=False),
        encoding="utf-8",
    )
    rows = []
    for index, (item_id, _, rgb) in enumerate(entries, start=1):
        image = root / "runs" / f"C{index:04d}" / "image_01.png"
        _write_image(image, rgb)
        rows.append(
            {
                "test_id": f"C{index:04d}",
                "seed": "1001",
                "style_id": item_id,
                "image_path": image.relative_to(root).as_posix(),
            }
        )
    scorecard = root / "scorecard.csv"
    with scorecard.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["test_id", "seed", "style_id", "image_path"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    return scorecard, catalog


def test_a_muted_palette_is_not_an_outlier_against_its_own_group(tmp_path: Path) -> None:
    """The comparison is within a coloring value, never across them.

    This is the whole reason the screen exists. airy_pastel measured 0.098 in the
    pilot and deep_jewel 0.164-0.229, so any absolute threshold that catches a real
    collapse also condemns the pastel palette for doing exactly what it is named
    for. Grouping first removes the conflict.
    """
    scorecard, catalog = _fixture(
        tmp_path,
        [
            ("pastel_a", "airy_pastel", (245, 235, 240)),
            ("pastel_b", "airy_pastel", (240, 238, 245)),
            ("jewel_a", "deep_jewel", (20, 90, 60)),
            ("jewel_b", "deep_jewel", (25, 40, 110)),
        ],
    )
    report = screen(
        scorecard, catalog, group_axis="coloring", root=tmp_path, deviation=0.5
    )
    assert report["outlier_total"] == 0
    by_value = {group["value"]: group for group in report["groups"]}
    assert by_value["airy_pastel"]["median_saturation"] < 0.1
    assert by_value["deep_jewel"]["median_saturation"] > 0.5


def test_a_collapsed_item_surfaces_against_its_saturated_peers(tmp_path: Path) -> None:
    """The shape plan.md 7.18 described: a normal median with a tail beneath it."""
    scorecard, catalog = _fixture(
        tmp_path,
        [
            ("jewel_a", "deep_jewel", (20, 90, 60)),
            ("jewel_b", "deep_jewel", (25, 40, 110)),
            ("jewel_c", "deep_jewel", (30, 80, 70)),
            ("jewel_grey", "deep_jewel", (90, 90, 90)),
        ],
    )
    report = screen(
        scorecard, catalog, group_axis="coloring", root=tmp_path, deviation=0.5
    )
    assert report["outlier_total"] == 1
    [group] = report["groups"]
    assert [entry["item_id"] for entry in group["outliers"]] == ["jewel_grey"]
    assert group["outliers"][0]["mean_saturation"] == 0.0


def test_items_missing_the_group_axis_are_reported_not_dropped(tmp_path: Path) -> None:
    scorecard, catalog = _fixture(
        tmp_path, [("jewel_a", "deep_jewel", (20, 90, 60))]
    )
    document = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    document["items"]["jewel_a"]["feature_axes"] = {}
    catalog.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    report = screen(
        scorecard, catalog, group_axis="coloring", root=tmp_path, deviation=0.5
    )
    assert report["ungrouped_item_ids"] == ["jewel_a"]
    assert report["groups"] == []


def test_a_missing_image_is_an_error_rather_than_a_silent_gap(tmp_path: Path) -> None:
    scorecard, catalog = _fixture(
        tmp_path, [("jewel_a", "deep_jewel", (20, 90, 60))]
    )
    (tmp_path / "runs" / "C0001" / "image_01.png").unlink()
    with pytest.raises(ValueError, match="missing image"):
        screen(scorecard, catalog, group_axis="coloring", root=tmp_path, deviation=0.5)
