from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import build_phase7_review_yaml as review_yaml
from summarize_results import METRICS


def write_manifest(root: Path, cases: list[tuple[str, str]]) -> Path:
    path = root / "manifest.json"
    path.write_text(
        json.dumps(
            {"cases": [{"alias": alias, "style_id": style_id} for alias, style_id in cases]}
        ),
        encoding="utf-8",
    )
    return path


def write_policy(root: Path, minimum_style_fidelity: int = 3) -> Path:
    path = root / "evaluation.yaml"
    path.write_text(
        yaml.safe_dump({"approval_policy": {"minimum_style_fidelity": minimum_style_fidelity}}),
        encoding="utf-8",
    )
    return path


def test_pass_gets_full_scores_and_hold_drops_style_fidelity_below_policy(
    tmp_path: Path,
) -> None:
    manifest = write_manifest(tmp_path, [("case_001", "style_a"), ("case_002", "style_b")])
    parts = tmp_path / "review_parts"
    parts.mkdir()
    (parts / "s001.json").write_text(
        json.dumps({"case_001": ["pass", "reason a"], "case_002": ["hold", "reason b"]}),
        encoding="utf-8",
    )
    policy = write_policy(tmp_path, minimum_style_fidelity=3)

    manifest_doc = review_yaml.load_yaml(manifest)
    alias_to_style = review_yaml.load_alias_to_style(manifest_doc)
    verdicts = review_yaml.load_verdicts(parts)
    styles = review_yaml.build_styles(alias_to_style, verdicts, minimum_style_fidelity=3)

    assert styles["style_a"]["metrics"] == {metric: 4 for metric in METRICS}
    assert styles["style_a"]["critical_failure"] is False
    assert "[pass] case_001: reason a" == styles["style_a"]["notes"]

    assert styles["style_b"]["metrics"]["style_fidelity"] == 2
    assert all(
        styles["style_b"]["metrics"][m] == 4 for m in METRICS if m != "style_fidelity"
    )
    assert styles["style_b"]["critical_failure"] is False
    assert "[hold] case_002: reason b" == styles["style_b"]["notes"]


def test_missing_verdict_is_rejected(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, [("case_001", "style_a"), ("case_002", "style_b")])
    parts = tmp_path / "review_parts"
    parts.mkdir()
    (parts / "s001.json").write_text(
        json.dumps({"case_001": ["pass", "reason a"]}), encoding="utf-8"
    )
    manifest_doc = review_yaml.load_yaml(manifest)
    alias_to_style = review_yaml.load_alias_to_style(manifest_doc)
    verdicts = review_yaml.load_verdicts(parts)
    with pytest.raises(ValueError, match="no recorded verdict"):
        review_yaml.build_styles(alias_to_style, verdicts, minimum_style_fidelity=3)


def test_extra_verdict_referencing_unknown_alias_is_rejected(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, [("case_001", "style_a")])
    parts = tmp_path / "review_parts"
    parts.mkdir()
    (parts / "s001.json").write_text(
        json.dumps({"case_001": ["pass", "reason a"], "case_999": ["pass", "ghost"]}),
        encoding="utf-8",
    )
    manifest_doc = review_yaml.load_yaml(manifest)
    alias_to_style = review_yaml.load_alias_to_style(manifest_doc)
    verdicts = review_yaml.load_verdicts(parts)
    with pytest.raises(ValueError, match="absent from the manifest"):
        review_yaml.build_styles(alias_to_style, verdicts, minimum_style_fidelity=3)


def test_duplicate_alias_across_review_parts_is_rejected(tmp_path: Path) -> None:
    parts = tmp_path / "review_parts"
    parts.mkdir()
    (parts / "s001.json").write_text(
        json.dumps({"case_001": ["pass", "reason a"]}), encoding="utf-8"
    )
    (parts / "s002.json").write_text(
        json.dumps({"case_001": ["hold", "reason b"]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate alias"):
        review_yaml.load_verdicts(parts)


def test_malformed_verdict_entry_is_rejected(tmp_path: Path) -> None:
    parts = tmp_path / "review_parts"
    parts.mkdir()
    (parts / "s001.json").write_text(
        json.dumps({"case_001": ["maybe", "reason a"]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="malformed verdict"):
        review_yaml.load_verdicts(parts)


def test_no_review_parts_found_is_rejected(tmp_path: Path) -> None:
    parts = tmp_path / "review_parts"
    parts.mkdir()
    with pytest.raises(ValueError, match="no review_parts found"):
        review_yaml.load_verdicts(parts)


def test_end_to_end_output_matches_apply_visual_review_schema(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, [("case_001", "style_a"), ("case_002", "style_b")])
    parts = tmp_path / "review_parts"
    parts.mkdir()
    (parts / "s001.json").write_text(
        json.dumps({"case_001": ["pass", "reason a"], "case_002": ["hold", "reason b"]}),
        encoding="utf-8",
    )
    policy = write_policy(tmp_path)
    output = tmp_path / "review.yaml"

    import sys

    argv = [
        "build_phase7_review_yaml.py",
        str(manifest),
        str(parts),
        "--policy",
        str(policy),
        "--output",
        str(output),
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        assert review_yaml.main() == 0
    finally:
        sys.argv = old_argv

    from apply_visual_review import load_review

    validated = load_review(output)
    assert set(validated) == {"style_a", "style_b"}
    assert validated["style_a"]["critical_failure"] is False
    assert validated["style_b"]["style_fidelity"] == 2
