from __future__ import annotations

import copy
from pathlib import Path

import pytest

from apply_artist_native_observations import (
    AXIS_MAPPING,
    INITIAL_SOURCE_STATUS,
    INITIAL_VISUAL_STATUS,
    STABLE_SOURCE_STATUS,
    STABLE_VISUAL_STATUS,
    UNSTABLE_SOURCE_STATUS,
    UNSTABLE_VISUAL_STATUS,
    apply_observations,
    forbidden_identity_names,
    load_merged_observations,
    main,
    redact_error,
    validate_registry,
)
from common import dump_yaml, load_yaml
from merge_artist_native_observations import AXES


def registry_document(artist_count: int = 300) -> dict[str, object]:
    artists = {}
    for index in range(1, artist_count + 1):
        artist_id = f"artist_{index:03d}"
        artists[artist_id] = {
            "display_name": f"Sensitive Canonical Name {index}",
            "aliases": [f"Private Alias {index}"],
            "source_tags": {
                "danbooru": f"sensitive_canonical_name_{index}",
                "anima": f"@Sensitive Canonical Name {index}",
                "novelai": None,
            },
            "source_status": INITIAL_SOURCE_STATUS,
            "evidence": {
                "source_ref": "pinned_snapshot",
                "tag_id": index,
            },
            "visual_signature": {
                "status": INITIAL_VISUAL_STATUS,
                "axes": {registry_axis: None for registry_axis in AXIS_MAPPING.values()},
            },
            "runtime_signature_ref": None,
        }
    return {
        "schema_version": 1,
        "registry": "artist_research",
        "source_snapshot": {"source_ref": "pinned_snapshot"},
        "artists": artists,
    }


def observation(
    *, confidence: int = 4, stable: bool = True, stem: str = "Controlled"
) -> dict[str, object]:
    return {
        "axes": {
            axis: f"{stem} {axis.replace('_', ' ')} traits remain visually repeatable."
            for axis in AXES
        },
        "confidence": confidence,
        "stable_across_seeds": stable,
        "notes": "The visual traits repeat consistently across the reviewed seeds.",
    }


def merged_document(artist_count: int = 300) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "artist_native_observations",
        "artist_count": artist_count,
        "axis_order": list(AXES),
        "artists": {
            f"artist_{index:03d}": observation(stem=f"Controlled variant {index}")
            for index in range(1, artist_count + 1)
        },
    }


def load_observations(
    tmp_path: Path,
    registry: dict[str, object],
    merged: dict[str, object],
    *,
    expected_artists: int,
) -> dict[str, dict[str, object]]:
    observations_path = tmp_path / "observations.yaml"
    dump_yaml(merged, observations_path)
    artist_ids = validate_registry(registry, expected_artists=expected_artists)
    return load_merged_observations(
        observations_path,
        registry_artist_ids=artist_ids,
        forbidden_names=forbidden_identity_names(registry),
    )


def test_applies_exact_axis_mapping_status_threshold_and_preserves_fields(
    tmp_path: Path,
) -> None:
    registry = registry_document(artist_count=3)
    merged = merged_document(artist_count=3)
    merged["artists"]["artist_001"] = observation(confidence=3, stable=True)
    merged["artists"]["artist_002"] = observation(confidence=2, stable=True)
    merged["artists"]["artist_003"] = observation(confidence=5, stable=False)
    before = copy.deepcopy(registry)
    observations = load_observations(
        tmp_path, registry, merged, expected_artists=3
    )

    updated, counts = apply_observations(registry, observations)

    assert counts == {"stable": 1, "unstable": 2, "changed": 3}
    assert registry == before
    for observation_axis, registry_axis in AXIS_MAPPING.items():
        assert (
            updated["artists"]["artist_001"]["visual_signature"]["axes"][
                registry_axis
            ]
            == observations["artist_001"]["axes"][observation_axis]
        )
    assert (
        updated["artists"]["artist_001"]["visual_signature"]["status"]
        == STABLE_VISUAL_STATUS
    )
    assert updated["artists"]["artist_001"]["source_status"] == STABLE_SOURCE_STATUS
    for artist_id in ("artist_002", "artist_003"):
        assert (
            updated["artists"][artist_id]["visual_signature"]["status"]
            == UNSTABLE_VISUAL_STATUS
        )
        assert updated["artists"][artist_id]["source_status"] == UNSTABLE_SOURCE_STATUS
    for artist_id in before["artists"]:
        for field in ("display_name", "source_tags", "evidence", "runtime_signature_ref"):
            assert updated["artists"][artist_id][field] == before["artists"][artist_id][field]
        assert "confidence" not in updated["artists"][artist_id]
        assert "stable_across_seeds" not in updated["artists"][artist_id]
        assert "notes" not in updated["artists"][artist_id]


def test_requires_exact_contiguous_registry(tmp_path: Path) -> None:
    registry = registry_document(artist_count=3)
    registry["artists"]["artist_004"] = registry["artists"].pop("artist_003")
    with pytest.raises(ValueError, match=r"missing=1, extra=1"):
        validate_registry(registry, expected_artists=3)


def test_partial_observation_subset_is_allowed(tmp_path: Path) -> None:
    registry = registry_document(artist_count=3)
    merged = merged_document(artist_count=3)
    del merged["artists"]["artist_003"]
    merged["artist_count"] = 2
    observations_path = tmp_path / "partial.yaml"
    dump_yaml(merged, observations_path)

    observations = load_merged_observations(
        observations_path,
        registry_artist_ids=validate_registry(registry, expected_artists=3),
        forbidden_names=forbidden_identity_names(registry),
    )

    assert set(observations) == {"artist_001", "artist_002"}


def test_observation_referencing_unknown_artist_id_is_rejected(
    tmp_path: Path,
) -> None:
    registry = registry_document(artist_count=3)
    merged = merged_document(artist_count=3)
    merged["artists"]["artist_999"] = merged["artists"].pop("artist_003")
    merged["artist_count"] = 3
    observations_path = tmp_path / "unknown.yaml"
    dump_yaml(merged, observations_path)

    with pytest.raises(ValueError, match="not in the registry"):
        load_merged_observations(
            observations_path,
            registry_artist_ids=validate_registry(registry, expected_artists=3),
            forbidden_names=forbidden_identity_names(registry),
        )


def test_conflicting_non_null_axis_and_status_are_rejected(tmp_path: Path) -> None:
    registry = registry_document(artist_count=2)
    merged = merged_document(artist_count=2)
    observations = load_observations(
        tmp_path, registry, merged, expected_artists=2
    )
    registry["artists"]["artist_002"]["visual_signature"]["axes"]["linework"] = (
        "Different existing observation."
    )
    with pytest.raises(ValueError, match="existing non-null observation conflicts"):
        apply_observations(registry, observations)

    registry = registry_document(artist_count=2)
    registry["artists"]["artist_002"]["visual_signature"]["status"] = (
        UNSTABLE_VISUAL_STATUS
    )
    registry["artists"]["artist_002"]["source_status"] = UNSTABLE_SOURCE_STATUS
    with pytest.raises(ValueError, match="existing observation status conflicts"):
        apply_observations(registry, observations)


def test_dry_run_apply_atomicity_and_idempotence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = tmp_path / "registry.yaml"
    observations_path = tmp_path / "observations.yaml"
    dump_yaml(registry_document(), registry_path)
    dump_yaml(merged_document(), observations_path)
    before = registry_path.read_bytes()
    arguments = [str(observations_path), "--registry", str(registry_path)]

    assert main(arguments) == 0
    dry_output = capsys.readouterr().out
    assert registry_path.read_bytes() == before
    assert "DRY RUN" in dry_output
    assert "Sensitive Canonical Name" not in dry_output

    assert main([*arguments, "--apply"]) == 0
    first_output = capsys.readouterr().out
    first_apply = registry_path.read_bytes()
    assert first_apply != before
    assert "changed=300" in first_output
    assert not list(tmp_path.glob(".registry.yaml.*"))

    assert main([*arguments, "--apply"]) == 0
    second_output = capsys.readouterr().out
    assert registry_path.read_bytes() == first_apply
    assert "changed=0" in second_output


def test_cli_conflict_leaves_registry_unchanged_and_redacts_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = tmp_path / "registry.yaml"
    observations_path = tmp_path / "observations.yaml"
    registry = registry_document()
    registry["artists"]["artist_300"]["visual_signature"]["axes"]["linework"] = (
        "Existing contradictory observation."
    )
    dump_yaml(registry, registry_path)
    dump_yaml(merged_document(), observations_path)
    before = registry_path.read_bytes()

    assert main([str(observations_path), "--registry", str(registry_path), "--apply"]) == 1
    output = capsys.readouterr().out
    assert registry_path.read_bytes() == before
    assert "Sensitive Canonical Name" not in output
    assert "existing non-null observation conflicts" in output


@pytest.mark.parametrize(
    "forbidden_text",
    [
        "See https://private.invalid:8188 for palette details.",
        "Sensitive Canonical Name 1 uses precise palette details.",
    ],
)
def test_direct_merged_input_rejects_endpoint_and_canonical_identity(
    tmp_path: Path, forbidden_text: str
) -> None:
    registry = registry_document(artist_count=1)
    merged = merged_document(artist_count=1)
    merged["artists"]["artist_001"]["axes"]["palette"] = forbidden_text
    path = tmp_path / "unsafe.yaml"
    dump_yaml(merged, path)

    with pytest.raises(ValueError, match="forbidden"):
        load_merged_observations(
            path,
            registry_artist_ids=validate_registry(registry, expected_artists=1),
            forbidden_names=forbidden_identity_names(registry),
        )


def test_duplicate_yaml_key_and_extra_metadata_are_rejected(tmp_path: Path) -> None:
    registry = registry_document(artist_count=1)
    artist_ids = validate_registry(registry, expected_artists=1)
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_merged_observations(
            duplicate,
            registry_artist_ids=artist_ids,
            forbidden_names=forbidden_identity_names(registry),
        )

    merged = merged_document(artist_count=1)
    merged["canonical_name"] = "must not be accepted"
    extra = tmp_path / "extra.yaml"
    dump_yaml(merged, extra)
    with pytest.raises(ValueError, match="unexpected or missing metadata"):
        load_merged_observations(
            extra,
            registry_artist_ids=artist_ids,
            forbidden_names=forbidden_identity_names(registry),
        )


def test_loaded_registry_round_trip_has_no_observation_metadata(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    observations_path = tmp_path / "observations.yaml"
    dump_yaml(registry_document(), registry_path)
    dump_yaml(merged_document(), observations_path)

    assert main([str(observations_path), "--registry", str(registry_path), "--apply"]) == 0
    applied = load_yaml(registry_path)
    for record in applied["artists"].values():
        assert set(record["visual_signature"]) == {"status", "axes"}
        assert not ({"confidence", "stable_across_seeds", "notes"} & set(record))


def test_error_redaction_hides_connection_and_account_data() -> None:
    endpoint = "https:" + "//private.invalid:8188/api"
    address = ".".join(("192", "0", "2", "10"))
    account_path = "/".join(("", "home", "example-account", "private"))
    account = "operator" + "@" + "example.invalid"
    message = f"{endpoint} {address} {account_path} {account}"

    redacted = redact_error(message)

    assert "private.invalid" not in redacted
    assert address not in redacted
    assert "example-account" not in redacted
    assert account not in redacted
    assert "<redacted_endpoint>" in redacted
    assert "<redacted_address>" in redacted
    assert "<redacted_account_path>" in redacted
    assert "<redacted_account>" in redacted
