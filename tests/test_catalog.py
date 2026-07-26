from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from common import KEY_RE, VALID_STATUSES, item_prompts, iter_catalog_items, load_yaml


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
PROHIBITED = re.compile(
    r"\b(?:velyra|1girl|1boy|child|minor|underage|anime|manga|illustration|cgi|digital[- ]art|2d|3d[- ]render)\b",
    re.I,
)


def test_initial_style_pack_count_and_schema() -> None:
    sources = load_yaml(CATALOG / "sources.yaml")["sources"]
    compatibility = load_yaml(CATALOG / "compatibility.yaml")
    families = compatibility["style_families"]
    entries = list(iter_catalog_items(CATALOG))
    style_entries = [entry for entry in entries if entry[0].name == "art_styles.yaml"]

    assert len(style_entries) == 50
    assert {item["family"] for _, _, item in style_entries} == set(families)

    assert Counter(item["validation"]["status"] for _, _, item in style_entries) == {
        "approved": 21,
        "rejected": 29,
    }

    for source_path, item_id, item in style_entries:
        assert KEY_RE.fullmatch(item_id), (source_path, item_id)
        assert len(item["visual_axes"]) >= 5
        assert item["family"] in families
        assert set(item["source_refs"]) <= set(sources)
        assert item["validation"]["status"] in VALID_STATUSES
        if item["validation"]["status"] == "approved":
            assert item["validation"]["tested_seeds"] == 5
            assert item["validation"]["last_evaluation"] in {
                "family_retest_v0_2",
                "style_retest_v0_4",
            }
        else:
            assert item["validation"]["tested_seeds"] == 3
            assert item["validation"]["last_evaluation"] == "style_screen_v0_3"
        assert item["runtime"]["path"][-1] == item_id
        assert item["runtime"]["file"].endswith(".yaml")
        prompts = item_prompts(item)
        assert len(prompts) == 1
        assert not PROHIBITED.search(prompts[0]), (item_id, prompts[0])
        assert not re.search(r"[{}\[\]]|(?<!\w)@[a-z0-9_]", prompts[0], re.I)


def test_approved_entries_require_real_evaluation() -> None:
    evaluation = load_yaml(CATALOG / "evaluation.yaml")["approval_policy"]
    for _, item_id, item in iter_catalog_items(CATALOG):
        if item["validation"]["status"] != "approved":
            continue
        validation = item["validation"]
        assert validation["tested_seeds"] >= evaluation["minimum_approval_seeds"], item_id
        assert validation["prompt_adherence"] >= evaluation["minimum_prompt_adherence"]
        assert validation["style_fidelity"] >= evaluation["minimum_style_fidelity"]
        assert validation["stability"] >= evaluation["minimum_stability"]
        assert validation["compatibility"] >= evaluation["minimum_compatibility"]
        assert validation.get("critical_failures", 0) <= evaluation["maximum_critical_failures"]


def test_screened_entries_match_quality_gate_status() -> None:
    policy = load_yaml(CATALOG / "evaluation.yaml")["approval_policy"]
    for source, item_id, item in iter_catalog_items(CATALOG):
        validation = item["validation"]
        if validation.get("last_evaluation") != "style_screen_v0_3":
            continue
        quality_passed = (
            validation["prompt_adherence"] >= policy["minimum_prompt_adherence"]
            and validation["style_fidelity"] >= policy["minimum_style_fidelity"]
            and validation["stability"] >= policy["minimum_stability"]
            and validation["compatibility"] >= policy["minimum_compatibility"]
            and validation["critical_failures"] <= policy["maximum_critical_failures"]
        )
        assert (validation["status"] == "testing") is quality_passed, (source, item_id)


def test_extension_retest_entries_are_approved_at_five_seeds() -> None:
    for source, item_id, item in iter_catalog_items(CATALOG):
        validation = item["validation"]
        if validation.get("last_evaluation") != "style_retest_v0_4":
            continue
        assert validation["status"] == "approved", (source, item_id)
        assert validation["tested_seeds"] == 5, (source, item_id)
