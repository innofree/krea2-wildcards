from __future__ import annotations

import json
from pathlib import Path

import pytest

from common import dump_yaml, load_yaml
from merge_artist_native_observations import (
    AXES,
    load_manifest_coverage,
    load_matrix_coverage,
    load_observation_part,
    main,
    merge_observation_parts,
)


def observation(stem: str = "Controlled") -> dict[str, object]:
    return {
        "axes": {
            axis: f"{stem} {axis.replace('_', ' ')} treatment remains visually distinct."
            for axis in AXES
        },
        "confidence": 4,
        "stable_across_seeds": True,
        "notes": "The visual traits repeat consistently across the reviewed seeds.",
    }


def write_part(path: Path, artists: dict[str, dict[str, object]]) -> None:
    dump_yaml({"schema_version": 1, "artists": artists}, path)


def write_matrix(path: Path, artist_count: int = 2) -> list[str]:
    labels: list[str] = []
    rows: list[dict[str, object]] = []
    for index in range(1, artist_count + 1):
        artist_id = f"artist_{index:03d}"
        label = f"Canonical Visible Name {index}"
        labels.append(label)
        for seed in (1001, 2002, 3003):
            rows.append(
                {
                    "schema_version": 1,
                    "test_id": f"AN{len(rows) + 1:06d}",
                    "style_id": artist_id,
                    "label": label,
                    "mode": "native_name",
                    "seed": seed,
                    "prompt": f"Private identity-bearing benchmark prompt for {label}.",
                }
            )
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return labels


def write_manifest(path: Path, artist_count: int = 2) -> None:
    items = [
        {"test_id": f"AN{index:06d}", "artist_id": f"artist_{index:03d}", "seed": 1001}
        for index in range(1, artist_count + 1)
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "artist_native_name_contact_sheet_review",
                "artist_count": artist_count,
                "items": items,
            }
        ),
        encoding="utf-8",
    )


def test_matrix_merge_is_sorted_deterministic_and_redacted(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    labels = write_matrix(matrix)
    expected, forbidden_names = load_matrix_coverage(matrix, expected_artists=2)
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_part(first, {"artist_002": observation("Angular")})
    write_part(second, {"artist_001": observation("Tapered")})

    forward = merge_observation_parts(
        [first, second], expected, forbidden_names=forbidden_names
    )
    reverse = merge_observation_parts(
        [second, first], expected, forbidden_names=forbidden_names
    )

    assert forward == reverse
    assert forward["axis_order"] == list(AXES)
    assert list(forward["artists"]) == ["artist_001", "artist_002"]
    assert list(forward["artists"]["artist_001"]["axes"]) == list(AXES)
    output = tmp_path / "merged.yaml"
    dump_yaml(forward, output)
    raw = output.read_text(encoding="utf-8")
    assert all(label not in raw for label in labels)
    assert "benchmark prompt" not in raw
    assert "matrix.jsonl" not in raw
    assert "first.yaml" not in raw


def test_merge_rejects_duplicate_missing_and_extra_artists(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_part(first, {"artist_001": observation()})
    write_part(second, {"artist_001": observation("Bold")})
    with pytest.raises(ValueError, match="duplicate artist observations"):
        merge_observation_parts([first, second], {"artist_001"})

    with pytest.raises(ValueError, match=r"missing=\['artist_002'\]"):
        merge_observation_parts([first], {"artist_001", "artist_002"})

    with pytest.raises(ValueError, match=r"extra=\['artist_001'\]"):
        merge_observation_parts([first], {"artist_002"})


@pytest.mark.parametrize("axis_change", ["missing", "extra"])
def test_part_requires_exact_eight_axes(tmp_path: Path, axis_change: str) -> None:
    value = observation()
    axes = value["axes"]
    assert isinstance(axes, dict)
    if axis_change == "missing":
        del axes["ornament"]
    else:
        axes["rendering"] = "Unexpected extra axis."
    part = tmp_path / "part.yaml"
    write_part(part, {"artist_001": value})

    with pytest.raises(ValueError, match="exactly the eight observation axes"):
        load_observation_part(part, part_number=1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("confidence", True, "integer from 1 to 5"),
        ("confidence", 6, "integer from 1 to 5"),
        ("stable_across_seeds", 1, "must be a boolean"),
    ],
)
def test_part_validates_confidence_and_stability(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    record = observation()
    record[field] = value
    part = tmp_path / "part.yaml"
    write_part(part, {"artist_001": record})

    with pytest.raises(ValueError, match=message):
        load_observation_part(part, part_number=1)


def test_part_rejects_canonical_name_and_connection_text(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.jsonl"
    labels = write_matrix(matrix, artist_count=1)
    _, forbidden_names = load_matrix_coverage(matrix, expected_artists=1)
    record = observation()
    axes = record["axes"]
    assert isinstance(axes, dict)
    axes["linework"] = f"{labels[0]} uses fine contours."
    part = tmp_path / "part.yaml"
    write_part(part, {"artist_001": record})
    with pytest.raises(ValueError, match="forbidden canonical identity"):
        load_observation_part(part, part_number=1, forbidden_names=forbidden_names)

    axes["linework"] = "See https://private.invalid for the linework notes."
    write_part(part, {"artist_001": record})
    with pytest.raises(ValueError, match="forbidden connection or account data"):
        load_observation_part(part, part_number=1, forbidden_names=forbidden_names)


def test_manifest_defines_coverage_and_rejects_identity_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest)
    assert load_manifest_coverage(manifest, expected_artists=2) == {
        "artist_001",
        "artist_002",
    }

    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["items"][0]["label"] = "Identity Must Not Be Copied"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden identity or connection fields"):
        load_manifest_coverage(manifest, expected_artists=2)


def test_cli_requires_overwrite_and_supports_expected_artists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, artist_count=1)
    part = tmp_path / "part.yaml"
    output = tmp_path / "merged.yaml"
    write_part(part, {"artist_001": observation()})
    arguments = [
        str(part),
        "--manifest",
        str(manifest),
        "--expected-artists",
        "1",
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    assert load_yaml(output)["artist_count"] == 1
    assert main(arguments) == 1
    assert "pass --overwrite" in capsys.readouterr().out
    assert main([*arguments, "--overwrite"]) == 0


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    part = tmp_path / "duplicate.yaml"
    part.write_text(
        "schema_version: 1\nartists:\n  artist_001: {}\n  artist_001: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contains invalid YAML"):
        load_observation_part(part, part_number=1)
