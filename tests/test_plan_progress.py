from __future__ import annotations

from pathlib import Path

from check_plan_progress import collect_progress


ROOT = Path(__file__).resolve().parents[1]


def test_plan_progress_tracks_catalog_targets() -> None:
    progress = collect_progress(ROOT / "catalog/roadmap.yaml", ROOT / "catalog")
    targets = {item["id"]: item for item in progress["targets"]}

    assert targets["approved_art_styles"]["target"] == 150
    assert targets["approved_artist_signatures"]["target"] == 200
    assert targets["style_pack_items"]["target"] == 200
    assert targets["artist_signature_items"]["target"] == 300
    assert targets["fashion_items"]["target"] == 500
    assert targets["preset_items"]["target"] == 200
    assert targets["total_library_items"]["target"] == 3750
    assert targets["approved_art_styles"]["current"] >= 21
    assert targets["approved_artist_signatures"]["current"] >= 200
    assert targets["total_library_items"]["current"] >= 50
    assert progress["complete"]
