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
    assert targets["total_library_items"]["current"] >= 50

    # Population targets are untouched by the subject fragmentation: it rewrote
    # every prompt but created and deleted nothing.
    population = [item for item in progress["targets"] if not item["id"].startswith("approved_")]
    assert population, "roadmap lost its population targets"
    for target in population:
        assert target["complete"], target["id"]

    # The two approval targets are what the fragmentation reset. Each verdict was
    # evidence about a prompt string the rewrite replaced, so both counts fell back
    # to what the hand-maintained catalog carries without any Phase 6/7 promotion:
    # 29 art_style packs, and no artist signature at all. approved_art_styles had
    # been sitting exactly on 150 as 21 art_styles + 129 style_expansion, and the
    # camera/preset merge added 8 more hand-maintained packs. Both targets stay
    # incomplete until a coverage gate runs against the new prompts.
    assert targets["approved_art_styles"]["current"] == 29
    assert targets["approved_artist_signatures"]["current"] == 0
    assert not targets["approved_art_styles"]["complete"]
    assert not targets["approved_artist_signatures"]["complete"]
