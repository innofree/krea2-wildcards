from __future__ import annotations

from pathlib import Path

import pytest

from refresh_generation_manifest import refreshed_manifest, validate_catalog_against_generation


def item(prompt: str, status: str = "generated", seeds: int = 0) -> dict[str, object]:
    validation: dict[str, object] = {"status": status, "tested_seeds": seeds}
    if status != "generated":
        validation["last_evaluation"] = "screen_v1"
    return {
        "prompt": prompt,
        "generation": {"collection_id": "styles"},
        "validation": validation,
    }


def test_validation_only_change_is_accepted() -> None:
    expected = {"one": item("Prompt.")}
    current = {"one": item("Prompt.", "testing", 3)}
    validate_catalog_against_generation(current, expected, ["one"])


def test_managed_prompt_change_is_rejected() -> None:
    expected = {"one": item("Prompt.")}
    current = {"one": item("Changed prompt.", "testing", 3)}
    with pytest.raises(ValueError, match="managed content changed"):
        validate_catalog_against_generation(current, expected, ["one"])


def test_persisted_retry_profile_is_accepted() -> None:
    expected = {"one": item("Primary prompt.")}
    expected["one"]["_retry_prompt"] = "Retry prompt."
    current = {"one": item("Retry prompt.", "testing", 3)}
    current["one"]["generation"]["prompt_profile"] = "retry"
    validate_catalog_against_generation(current, expected, ["one"])


def test_unexpected_retry_profile_is_rejected() -> None:
    expected = {"one": item("Primary prompt.")}
    current = {"one": item("Primary prompt.", "testing", 3)}
    current["one"]["generation"]["prompt_profile"] = "retry"
    with pytest.raises(ValueError, match="unexpected retry prompt profile"):
        validate_catalog_against_generation(current, expected, ["one"])


def test_refresh_updates_output_and_collection_hash(tmp_path: Path) -> None:
    catalog = tmp_path / "styles.yaml"
    catalog.write_text("catalog\n", encoding="utf-8")
    manifest = {
        "outputs": [
            {
                "output_file": "styles.yaml",
                "sha256": "old",
                "collection_ids": ["styles"],
            }
        ],
        "collections": [
            {"id": "styles", "output_file": "styles.yaml", "output_sha256": "old"}
        ],
    }
    updated = refreshed_manifest(manifest, "styles.yaml", catalog)
    digest = updated["outputs"][0]["sha256"]
    assert digest != "old"
    assert updated["collections"][0]["output_sha256"] == digest
