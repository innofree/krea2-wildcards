from __future__ import annotations

from pathlib import Path

import pytest

import export_artist_abc_matrix as abc_export
from apply_artist_native_observations import (
    AXIS_MAPPING,
    STABLE_SOURCE_STATUS,
    STABLE_VISUAL_STATUS,
    UNSTABLE_SOURCE_STATUS,
    UNSTABLE_VISUAL_STATUS,
)
from common import dump_yaml, load_yaml
from merge_artist_native_observations import AXES
from select_artist_abc_candidates import (
    build_signature_map,
    load_selection_inputs,
    main,
    select_diverse_candidates,
)


def observation(
    index: int,
    *,
    confidence: int = 4,
    stable: bool = True,
    vocabulary: str = "shared restrained",
) -> dict[str, object]:
    return {
        "axes": {
            axis: f"{vocabulary} {axis.replace('_', ' ')} treatment remains visible."
            for axis in AXES
        },
        "confidence": confidence,
        "stable_across_seeds": stable,
        "notes": f"Observed visual treatment group {index} remains reviewable.",
    }


def fixture_documents(
    artist_count: int = 10,
) -> tuple[dict[str, object], dict[str, object]]:
    registry_artists: dict[str, object] = {}
    observations: dict[str, object] = {}
    for index in range(1, artist_count + 1):
        artist_id = f"artist_{index:03d}"
        item = observation(index)
        registry_artists[artist_id] = {
            "display_name": f"Sensitive Reference {index}",
            "aliases": [f"Private Alias {index}"],
            "source_tags": {
                "danbooru": f"sensitive_reference_{index}",
                "anima": f"@Sensitive Reference {index}",
                "novelai": None,
            },
            "source_status": STABLE_SOURCE_STATUS,
            "evidence": {"source_ref": "pinned_snapshot", "tag_id": index},
            "visual_signature": {
                "status": STABLE_VISUAL_STATUS,
                "axes": {
                    registry_axis: item["axes"][observation_axis]
                    for observation_axis, registry_axis in AXIS_MAPPING.items()
                },
            },
            "runtime_signature_ref": None,
        }
        observations[artist_id] = item
    registry = {
        "schema_version": 1,
        "registry": "artist_research",
        "source_snapshot": {"source_ref": "pinned_snapshot"},
        "artists": registry_artists,
    }
    merged = {
        "schema_version": 1,
        "kind": "artist_native_observations",
        "artist_count": artist_count,
        "axis_order": list(AXES),
        "artists": observations,
    }
    return registry, merged


def write_fixtures(
    root: Path,
    *,
    artist_count: int = 10,
) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    registry, merged = fixture_documents(artist_count)
    registry_path = root / "registry.yaml"
    observations_path = root / "observations.yaml"
    dump_yaml(registry, registry_path)
    dump_yaml(merged, observations_path)
    return registry_path, observations_path, registry, merged


def test_eligibility_requires_observation_and_registry_stability(
    tmp_path: Path,
) -> None:
    registry_path, observations_path, registry, merged = write_fixtures(
        tmp_path, artist_count=10
    )
    merged["artists"]["artist_001"]["confidence"] = 2
    merged["artists"]["artist_002"]["stable_across_seeds"] = False
    for artist_id in ("artist_001", "artist_002"):
        registry["artists"][artist_id]["source_status"] = UNSTABLE_SOURCE_STATUS
        registry["artists"][artist_id]["visual_signature"]["status"] = (
            UNSTABLE_VISUAL_STATUS
        )
    registry["artists"]["artist_003"]["source_status"] = UNSTABLE_SOURCE_STATUS
    registry["artists"]["artist_003"]["visual_signature"]["status"] = (
        UNSTABLE_VISUAL_STATUS
    )
    dump_yaml(registry, registry_path)
    dump_yaml(merged, observations_path)

    loaded_registry, loaded_observations = load_selection_inputs(
        observations_path, registry_path
    )
    document = build_signature_map(
        loaded_registry,
        loaded_observations,
        count=7,
    )

    assert len(document["artists"]) == 7
    assert {"artist_001", "artist_002", "artist_003"}.isdisjoint(document["artists"])


def test_diversity_selection_is_deterministic_and_not_first_ids() -> None:
    eligible = {f"artist_{index:03d}": observation(index) for index in range(1, 11)}
    eligible["artist_009"] = observation(
        9,
        vocabulary="angular cyan etched",
    )
    eligible["artist_010"] = observation(
        10,
        vocabulary="organic amber stippled",
    )

    forward = select_diverse_candidates(eligible, 3)
    reverse = select_diverse_candidates(dict(reversed(eligible.items())), 3)

    assert forward == reverse
    assert {"artist_009", "artist_010"} <= set(forward)
    assert forward != ("artist_001", "artist_002", "artist_003")


def test_ties_use_confidence_then_artist_id() -> None:
    eligible = {
        "artist_003": observation(3, confidence=4),
        "artist_002": observation(2, confidence=5),
        "artist_001": observation(1, confidence=5),
    }

    assert select_diverse_candidates(eligible, 2) == (
        "artist_001",
        "artist_002",
    )


def test_insufficient_stable_candidates_is_rejected(tmp_path: Path) -> None:
    registry_path, observations_path, registry, merged = write_fixtures(
        tmp_path, artist_count=8
    )
    for index in range(2, 9):
        artist_id = f"artist_{index:03d}"
        merged["artists"][artist_id]["stable_across_seeds"] = False
        registry["artists"][artist_id]["source_status"] = UNSTABLE_SOURCE_STATUS
        registry["artists"][artist_id]["visual_signature"]["status"] = (
            UNSTABLE_VISUAL_STATUS
        )
    dump_yaml(registry, registry_path)
    dump_yaml(merged, observations_path)
    loaded_registry, loaded_observations = load_selection_inputs(
        observations_path, registry_path
    )

    with pytest.raises(ValueError, match="insufficient eligible stable observations"):
        build_signature_map(loaded_registry, loaded_observations, count=2)


def test_identity_bearing_observation_is_rejected(tmp_path: Path) -> None:
    registry_path, observations_path, _, merged = write_fixtures(
        tmp_path, artist_count=8
    )
    merged["artists"]["artist_001"]["axes"]["palette"] = (
        "Sensitive Reference 1 uses a muted palette."
    )
    dump_yaml(merged, observations_path)

    with pytest.raises(ValueError, match="forbidden canonical identity"):
        load_selection_inputs(observations_path, registry_path)


@pytest.mark.parametrize(
    ("unsafe", "message"),
    [
        ("Use __private/style__ contours.", "unresolved wildcard"),
        ("Use {strong} contours.", "emphasis syntax"),
        ("Use (contours:1.3) throughout.", "emphasis syntax"),
    ],
)
def test_signature_rejects_wildcard_and_emphasis(
    tmp_path: Path,
    unsafe: str,
    message: str,
) -> None:
    registry_path, observations_path, registry, merged = write_fixtures(
        tmp_path, artist_count=8
    )
    merged["artists"]["artist_001"]["axes"]["linework"] = unsafe
    registry["artists"]["artist_001"]["visual_signature"]["axes"]["linework"] = unsafe
    dump_yaml(registry, registry_path)
    dump_yaml(merged, observations_path)
    loaded_registry, loaded_observations = load_selection_inputs(
        observations_path, registry_path
    )

    with pytest.raises(ValueError, match=message):
        build_signature_map(loaded_registry, loaded_observations, count=8)


def test_default_count_output_is_exporter_compatible(tmp_path: Path) -> None:
    registry_path, observations_path, _, _ = write_fixtures(tmp_path, artist_count=10)
    registry, observations = load_selection_inputs(observations_path, registry_path)
    document = build_signature_map(registry, observations)
    signature_map = tmp_path / "signature_map.yaml"
    dump_yaml(document, signature_map)

    exporter_registry = abc_export.load_registry(registry_path)
    signatures = abc_export.load_signature_map(signature_map, exporter_registry)
    rows = abc_export.artist_abc_rows(
        registry_path,
        signature_map,
        document["artists"],
    )

    assert set(document) == {"schema_version", "kind", "artists"}
    assert len(signatures) == len(document["artists"]) == 8
    assert len(rows) == 72
    for artist_id, entry in document["artists"].items():
        assert set(entry) == {"signature_prompt"}
        assert all(
            observation_text.rstrip(" .;:") in entry["signature_prompt"]
            for observation_text in observations[artist_id]["axes"].values()
        )


def test_cli_is_atomic_and_requires_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path, observations_path, _, _ = write_fixtures(tmp_path, artist_count=8)
    output = tmp_path / "selected.yaml"
    output.write_text("sentinel\n", encoding="utf-8")
    arguments = [
        "--observations",
        str(observations_path),
        "--registry",
        str(registry_path),
        "--output",
        str(output),
    ]

    assert main(arguments) == 1
    assert output.read_text(encoding="utf-8") == "sentinel\n"
    assert "pass --overwrite" in capsys.readouterr().out
    assert main([*arguments, "--overwrite"]) == 0
    assert load_yaml(output)["kind"] == abc_export.SIGNATURE_MAP_KIND
    assert not list(tmp_path.glob(".selected.yaml.*"))
