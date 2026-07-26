from __future__ import annotations

from datetime import date
from pathlib import Path

from common import load_yaml


ROOT = Path(__file__).resolve().parents[1]

PHASE_ONE_DOMAIN_SOURCE_IDS = {
    "blender_animation_keyframes_manual",
    "blender_camera_manual",
    "getty_aat_costume_vocabulary",
    "getty_tgn_place_type_vocabulary",
    "cie_international_lighting_vocabulary",
}
PHASE_ONE_REQUIRED_DOMAINS = {
    "animation",
    "cinematography",
    "fashion",
    "environment",
    "color",
    "lighting",
}


def test_sources_have_usage_license_and_evidence() -> None:
    sources = load_yaml(ROOT / "catalog/sources.yaml")["sources"]
    assert len(sources) >= 10
    for source_id, source in sources.items():
        assert source["title"], source_id
        assert source["kind"], source_id
        assert source["usage"], source_id
        assert source["license_note"], source_id
        assert source["evidence_summary"], source_id
        if "url" in source:
            assert source["url"].startswith("https://"), source_id
            assert date.fromisoformat(source["accessed"]), source_id


def test_phase_one_core_external_sources_are_registered() -> None:
    sources = load_yaml(ROOT / "catalog/sources.yaml")["sources"]
    assert {
        "novelai_official_tagging",
        "novelai_official_character_creation",
        "anima_official_model_card",
        "danbooru_official_repository",
        "dynamicprompts_official_repository",
    } <= set(sources)


def test_phase_one_domain_terminology_sources_are_registered() -> None:
    sources = load_yaml(ROOT / "catalog/sources.yaml")["sources"]
    assert PHASE_ONE_DOMAIN_SOURCE_IDS <= set(sources)

    covered_domains = {
        domain
        for source_id in PHASE_ONE_DOMAIN_SOURCE_IDS
        for domain in sources[source_id]["domains"]
    }
    assert PHASE_ONE_REQUIRED_DOMAINS <= covered_domains


def test_phase_one_domain_sources_are_traceable_authoritative_references() -> None:
    sources = load_yaml(ROOT / "catalog/sources.yaml")["sources"]
    allowed_kinds = {
        "official_manual",
        "institutional_controlled_vocabulary",
        "international_standard",
    }
    for source_id in PHASE_ONE_DOMAIN_SOURCE_IDS:
        source = sources[source_id]
        assert source["kind"] in allowed_kinds, source_id
        assert source["url"].startswith("https://"), source_id
        assert date.fromisoformat(source["accessed"]), source_id
        assert source["locator"], source_id
        assert source["domains"], source_id
        assert source["usage"], source_id
        assert source["license_note"], source_id
        assert source["evidence_summary"], source_id
