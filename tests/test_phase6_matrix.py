from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest
import yaml

from export_phase6_matrix import (
    PAIRWISE_SPECS,
    benchmark_rows,
    pairwise_rows,
    preset_rows,
    random_utility_rows,
    single_axis_rows,
)


def _item(item_id: str, family: str, *, status: str = "generated") -> dict[str, object]:
    return {
        "family": family,
        "prompt": f"Observable visual direction for {item_id}.",
        "validation": {"status": status},
    }


def _write_catalog(
    root: Path, name: str, family: str, count: int, *, status: str = "generated"
) -> None:
    items = {
        f"{family}_{index:03d}": _item(f"{family}_{index:03d}", family, status=status)
        for index in range(1, count + 1)
    }
    path = root / "catalog" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "items": items}, sort_keys=False),
        encoding="utf-8",
    )


def _phase6_catalogs(root: Path) -> None:
    _write_catalog(root, "style_expansion", "style_pack", 16, status="approved")
    _write_catalog(root, "art_styles", "style_pack", 0, status="approved")
    _write_catalog(root, "artists", "artist_signature", 24, status="approved")
    _write_catalog(root, "character_designs", "character_design", 16)
    _write_catalog(root, "poses", "pose", 16)
    _write_catalog(root, "lighting", "lighting", 16)
    _write_catalog(root, "backgrounds", "background", 16)
    _write_catalog(root, "linework_coloring", "linework_coloring", 16)
    _write_catalog(root, "cameras", "camera", 16)
    _write_catalog(root, "presets", "preset", 100)


def test_single_axis_matrix_changes_two_axes_at_three_seeds() -> None:
    rows = single_axis_rows()
    assert len(rows) == 12
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    assert len({row["style_id"] for row in rows}) == 4
    assert Counter(row["factors"]["axis"] for row in rows) == {
        "linework": 6,
        "coloring": 6,
    }
    by_case: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_case[row["style_id"]].add(row["prompt"])
    assert all(len(prompts) == 1 for prompts in by_case.values())


def test_pairwise_matrix_covers_six_types_with_sixteen_cases_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    monkeypatch.chdir(tmp_path)
    rows = pairwise_rows()
    assert len(rows) == 6 * 16 * 3
    assert len({row["style_id"] for row in rows}) == 96
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    counts = Counter(row["factors"]["pair_type"] for row in rows)
    assert counts == {spec[0]: 16 * 3 for spec in PAIRWISE_SPECS}


def test_preset_random_and_benchmark_matrices_are_bounded_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    monkeypatch.chdir(tmp_path)

    presets = preset_rows()
    assert len(presets) == 100 * 3
    assert len({row["style_id"] for row in presets}) == 100

    random_a = random_utility_rows()
    random_b = random_utility_rows()
    assert random_a == random_b
    assert len(random_a) == 20 * 3
    assert len({row["style_id"] for row in random_a}) == 20

    benchmark = benchmark_rows()
    assert len(benchmark) == 5
    assert {row["seed"] for row in benchmark} == {1001, 2002, 3003, 4004, 5005}
    assert {row["mode"] for row in benchmark} == {"krea2_turbo_benchmark"}


def test_pairwise_refuses_unapproved_artist_signatures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phase6_catalogs(tmp_path)
    artists = tmp_path / "catalog/artists.yaml"
    document = yaml.safe_load(artists.read_text(encoding="utf-8"))
    for item in document["items"].values():
        item["validation"]["status"] = "testing"
    artists.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="need 16 artist_signature"):
        pairwise_rows()


def test_rows_are_json_serializable_without_connection_fields() -> None:
    encoded = json.dumps(single_axis_rows())
    assert "api_url" not in encoded
    assert "remote" not in encoded
