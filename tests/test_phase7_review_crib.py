from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import build_phase7_review_crib as crib

MANIFEST_KIND = "resolved_prompt_matrix_contact_sheet_review"


def write_catalog(root: Path, count: int = 6) -> Path:
    items = {
        f"linework_coloring_item_{index:02d}": {
            "family": "linework_coloring",
            "feature_axes": {
                "linework": [f"line_{index:02d}"],
                "coloring": [f"colour_{index:02d}"],
                "accent_light": ["controlled_rim" if index % 2 else "reflected_color"],
            },
            "prompt": f"body {index}",
        }
        for index in range(1, count + 1)
    }
    path = root / "catalog.yaml"
    path.write_text(yaml.safe_dump({"items": items}), encoding="utf-8")
    return path


def write_manifest(
    root: Path,
    *,
    style_ids: list[str],
    sheet_aliases: list[list[str]],
    include_case_aliases: bool = True,
    kind: str = MANIFEST_KIND,
) -> Path:
    cases = [
        {"alias": f"case_{index:03d}", "style_id": style_id, "mode": "mass_axis"}
        for index, style_id in enumerate(style_ids, start=1)
    ]
    sheets = []
    for index, aliases in enumerate(sheet_aliases, start=1):
        sheet: dict[str, object] = {
            "mode": "mass_axis",
            "sheet_index": index,
            "path": f"review/sheet_{index:03d}.png",
            "case_count": len(aliases),
            "image_count": len(aliases) * 3,
        }
        if include_case_aliases:
            sheet["case_aliases"] = aliases
        sheets.append(sheet)
    path = root / "manifest.json"
    path.write_text(
        json.dumps({"kind": kind, "sheets": sheets, "cases": cases}), encoding="utf-8"
    )
    return path


def test_crib_lists_each_sheet_in_sheet_order_with_catalog_attributes(
    tmp_path: Path,
) -> None:
    catalog = write_catalog(tmp_path)
    style_ids = sorted(crib.load_catalog_items(catalog))
    manifest = write_manifest(
        tmp_path,
        style_ids=style_ids,
        sheet_aliases=[
            ["case_001", "case_003", "case_005"],
            ["case_002", "case_004", "case_006"],
        ],
    )
    text = crib.render_crib(
        crib.load_manifest(manifest), crib.load_catalog_items(catalog)
    )

    assert "## sheet 001  (3 cases)  review/sheet_001.png" in text
    assert "## sheet 002  (3 cases)  review/sheet_002.png" in text
    sheet_one = text.split("## sheet 002")[0]
    # The strided membership, not the alias numbering, decides sheet contents.
    assert "case_001" in sheet_one and "case_003" in sheet_one
    assert "case_002" not in sheet_one
    assert "line_01" in sheet_one and "colour_05" in sheet_one


def test_excluded_axis_is_marked_rather_than_dropped(tmp_path: Path) -> None:
    """An unreadable attribute must stay visible as unjudged.

    Silently omitting it would make the crib look like a complete verdict
    checklist, which is how an attribute nobody could see gets recorded as
    approved.
    """
    catalog = write_catalog(tmp_path)
    style_ids = sorted(crib.load_catalog_items(catalog))
    manifest = write_manifest(
        tmp_path, style_ids=style_ids, sheet_aliases=[[f"case_{i:03d}" for i in range(1, 7)]]
    )
    text = crib.render_crib(
        crib.load_manifest(manifest),
        crib.load_catalog_items(catalog),
        excluded=("accent_light",),
    )

    assert "Excluded from the sheet verdict" in text
    assert "accent_light [EXCLUDED]" in text
    assert "controlled_rim" in text and "reflected_color" in text


def test_unknown_excluded_axis_is_rejected(tmp_path: Path) -> None:
    catalog = write_catalog(tmp_path)
    style_ids = sorted(crib.load_catalog_items(catalog))
    manifest = write_manifest(
        tmp_path, style_ids=style_ids, sheet_aliases=[[f"case_{i:03d}" for i in range(1, 7)]]
    )
    with pytest.raises(ValueError, match="not catalog feature axes"):
        crib.render_crib(
            crib.load_manifest(manifest),
            crib.load_catalog_items(catalog),
            excluded=("shading",),
        )


def test_manifest_without_case_aliases_fails_closed(tmp_path: Path) -> None:
    catalog = write_catalog(tmp_path)
    style_ids = sorted(crib.load_catalog_items(catalog))
    manifest = write_manifest(
        tmp_path,
        style_ids=style_ids,
        sheet_aliases=[[f"case_{i:03d}" for i in range(1, 7)]],
        include_case_aliases=False,
    )
    with pytest.raises(ValueError, match="predates per-sheet case_aliases"):
        crib.load_manifest(manifest)


def test_manifest_of_the_wrong_kind_is_rejected(tmp_path: Path) -> None:
    catalog = write_catalog(tmp_path)
    style_ids = sorted(crib.load_catalog_items(catalog))
    manifest = write_manifest(
        tmp_path,
        style_ids=style_ids,
        sheet_aliases=[[f"case_{i:03d}" for i in range(1, 7)]],
        kind="something_else",
    )
    with pytest.raises(ValueError, match="not a prompt-matrix contact sheet"):
        crib.load_manifest(manifest)


def test_case_absent_from_the_catalog_is_reported(tmp_path: Path) -> None:
    catalog = write_catalog(tmp_path)
    manifest = write_manifest(
        tmp_path,
        style_ids=["linework_coloring_item_01", "linework_coloring_missing"],
        sheet_aliases=[["case_001", "case_002"]],
    )
    with pytest.raises(ValueError, match="absent from the catalog"):
        crib.render_crib(
            crib.load_manifest(manifest), crib.load_catalog_items(catalog)
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("3", (3,)),
        ("1-3", (1, 2, 3)),
        ("11-20", tuple(range(11, 21))),
        ("3,1,2", (1, 2, 3)),
        ("1-3,7", (1, 2, 3, 7)),
        ("2-2", (2,)),
    ],
)
def test_sheet_selection_parsing(raw: str | None, expected: tuple[int, ...] | None) -> None:
    assert crib.parse_sheets(raw) == expected


def test_inverted_sheet_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="inverted"):
        crib.parse_sheets("10-1")
