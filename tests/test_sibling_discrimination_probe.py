from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import build_sibling_discrimination_probe as probe


def item(**axes: str) -> dict[str, Any]:
    return {"feature_axes": {axis: [value] for axis, value in axes.items()}}


def test_signature_drops_only_the_axis_under_test() -> None:
    subject = item(linework="fine_tapered", coloring="warm_earth", shading="soft_two_band")
    assert probe.feature_signature(subject, without="shading") == (
        ("coloring", "warm_earth"),
        ("linework", "fine_tapered"),
    )


def test_pairs_hold_every_other_axis_identical() -> None:
    """The probe is only meaningful if the pair differs in one axis alone.

    Calibration compared maximally separated combinations, which answers whether
    the axis responds, not whether two siblings are distinguishable. A pair that
    also differed in palette would reproduce that same confusion.
    """
    items = {
        "a": item(linework="crisp_uniform", coloring="warm_earth", shading="soft_two_band"),
        "b": item(linework="crisp_uniform", coloring="warm_earth", shading="crisp_shape_shadow"),
        # same shading pair, but a different palette: must not be matched
        "c": item(linework="crisp_uniform", coloring="airy_pastel", shading="soft_two_band"),
        "d": item(linework="rounded_soft", coloring="warm_earth", shading="crisp_shape_shadow"),
    }
    pairs = probe.find_matched_pairs(items, "shading", "soft_two_band", "crisp_shape_shadow")
    assert pairs == [("a", "b")]


def test_pairs_are_found_in_both_argument_orders() -> None:
    items = {
        "a": item(coloring="warm_earth", shading="soft_two_band"),
        "b": item(coloring="warm_earth", shading="crisp_shape_shadow"),
    }
    forward = probe.find_matched_pairs(items, "shading", "soft_two_band", "crisp_shape_shadow")
    reverse = probe.find_matched_pairs(items, "shading", "crisp_shape_shadow", "soft_two_band")
    assert forward == [("a", "b")]
    assert reverse == [("b", "a")]


def test_unrelated_values_are_ignored() -> None:
    items = {
        "a": item(shading="soft_two_band"),
        "b": item(shading="transparent_glaze"),
    }
    assert probe.find_matched_pairs(items, "shading", "soft_two_band", "crisp_shape_shadow") == []


def test_item_without_feature_axes_is_rejected() -> None:
    with pytest.raises(ValueError, match="no feature_axes"):
        probe.feature_signature({"prompt": "body"}, without="shading")


def test_catalog_without_item_mapping_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump({"items": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="item mapping"):
        probe.load_catalog_items(path)


def test_real_catalog_supplies_matched_pairs_for_every_flagged_collapse() -> None:
    """Each pair flagged as possibly indistinguishable must be measurable."""
    items = probe.load_catalog_items(
        probe.ROOT / "catalog/linework_coloring.yaml"
    )
    flagged = [
        ("shading", "fine_tonal_hatching", "broad_blended_plane"),
        ("shading", "soft_two_band", "crisp_shape_shadow"),
        ("shading", "broad_blended_plane", "transparent_glaze"),
        ("shading", "subtle_contact_shadow", "crisp_shape_shadow"),
        ("linework", "fine_tapered", "crisp_uniform"),
        ("linework", "angular_precise", "crisp_uniform"),
        ("coloring", "warm_earth", "skin_centered_neutral"),
        ("coloring", "airy_pastel", "limited_two_tone"),
        ("accent_light", "controlled_rim", "reflected_color"),
    ]
    for axis, left, right in flagged:
        pairs = probe.find_matched_pairs(items, axis, left, right)
        assert pairs, (axis, left, right)
        for left_id, right_id in pairs:
            assert probe.axis_value(items[left_id], axis) == left
            assert probe.axis_value(items[right_id], axis) == right
            assert probe.feature_signature(
                items[left_id], without=axis
            ) == probe.feature_signature(items[right_id], without=axis)
