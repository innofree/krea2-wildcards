from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from export_artist_abc_matrix import (
    DEFAULT_SEEDS,
    FIXED_SCENE,
    MODES,
    STYLE_CONDITION_MARKER,
    artist_abc_rows,
    validate_artist_ids,
)
from run_remote_prompt_matrix import validate_job


ROOT = Path(__file__).resolve().parents[1]
ARTIST_IDS = tuple(f"artist_{index:03d}" for index in range(1, 9))


def fixture_registry(path: Path) -> None:
    artists = {
        artist_id: {
            "display_name": f"reference name {index:03d}",
            "aliases": [],
            "source_tags": {"danbooru": f"reference_name_{index:03d}"},
        }
        for index, artist_id in enumerate(ARTIST_IDS, start=1)
    }
    path.write_text(yaml.safe_dump({"artists": artists}, sort_keys=False), encoding="utf-8")


def fixture_signature_map(path: Path, *, omit: str | None = None) -> dict[str, str]:
    signatures = {
        artist_id: (
            f"Use fine charcoal contour group {index}, muted mineral coloring, "
            "shallow matte shading, centered full-length spacing, and sparse geometric ornament."
        )
        for index, artist_id in enumerate(ARTIST_IDS, start=1)
        if artist_id != omit
    }
    document = {
        "schema_version": 1,
        "kind": "artist_abc_signature_map",
        "artists": {
            artist_id: {"signature_prompt": signature}
            for artist_id, signature in signatures.items()
        },
    }
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return signatures


def fixtures(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    registry = tmp_path / "registry.yaml"
    signature_map = tmp_path / "signature_map.yaml"
    fixture_registry(registry)
    signatures = fixture_signature_map(signature_map)
    return registry, signature_map, signatures


def test_exact_eight_by_three_by_three_comparison_matrix(tmp_path: Path) -> None:
    registry, signature_map, signatures = fixtures(tmp_path)
    rows = artist_abc_rows(registry, signature_map, reversed(ARTIST_IDS))

    assert len(rows) == 72
    assert len({row["test_id"] for row in rows}) == 72
    assert {row["style_id"] for row in rows} == set(ARTIST_IDS)
    assert {row["seed"] for row in rows} == set(DEFAULT_SEEDS)
    assert Counter(row["mode"] for row in rows) == Counter({mode: 24 for mode in MODES})
    assert rows[0]["test_id"] == "ABC001N1001"
    assert rows[-1]["test_id"] == "ABC008H3003"

    grouped: dict[tuple[str, int], dict[str, dict[str, object]]] = {}
    for row in rows:
        validate_job(row, 1)
        grouped.setdefault((row["style_id"], row["seed"]), {})[row["mode"]] = row
        assert "__" not in row["prompt"]
        assert "http://" not in row["prompt"]
        assert row["prompt"].split(STYLE_CONDITION_MARKER, 1)[0] == FIXED_SCENE

    assert all(set(mode_rows) == set(MODES) for mode_rows in grouped.values())
    for (artist_id, _seed), mode_rows in grouped.items():
        signature = signatures[artist_id]
        native = mode_rows["native_name"]["prompt"]
        visual = mode_rows["visual_signature"]["prompt"]
        hybrid = mode_rows["hybrid"]["prompt"]
        assert signature not in native
        assert signature in visual
        assert signature in hybrid
        display_name = f"reference name {int(artist_id[-3:]):03d}"
        assert display_name in native and display_name in hybrid
        assert display_name not in visual
        native_condition = native.split(STYLE_CONDITION_MARKER, 1)[1]
        visual_condition = visual.split(STYLE_CONDITION_MARKER, 1)[1]
        hybrid_condition = hybrid.split(STYLE_CONDITION_MARKER, 1)[1]
        assert hybrid_condition == f"{native_condition} {visual_condition}"


def test_output_is_byte_deterministic_across_selection_order(tmp_path: Path) -> None:
    registry, signature_map, _ = fixtures(tmp_path)
    selections = [ARTIST_IDS, tuple(reversed(ARTIST_IDS))]
    outputs = []
    for index, selection in enumerate(selections):
        output = tmp_path / f"matrix_{index}.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/export_artist_abc_matrix.py"),
                "--registry",
                str(registry),
                "--signature-map",
                str(signature_map),
                "--output",
                str(output),
                *[argument for artist in selection for argument in ("--artist", artist)],
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout or result.stderr
        assert "72 resolved prompts" in result.stdout
        assert len(output.read_text(encoding="utf-8").splitlines()) == 72
        outputs.append(output)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs]
    assert hashes[0] == hashes[1]


def test_selection_and_signature_coverage_are_strict(tmp_path: Path) -> None:
    registry, signature_map, _ = fixtures(tmp_path)
    with pytest.raises(ValueError, match="exactly 8"):
        validate_artist_ids(ARTIST_IDS[:7])
    with pytest.raises(ValueError, match="distinct"):
        validate_artist_ids((*ARTIST_IDS[:7], ARTIST_IDS[0]))

    fixture_signature_map(signature_map, omit="artist_008")
    with pytest.raises(ValueError, match="lacks a name-free signature"):
        artist_abc_rows(registry, signature_map, ARTIST_IDS)


@pytest.mark.parametrize(
    ("signature", "message"),
    [
        ("Use reference name 001 with thin lines and muted color.", "artist identity"),
        ("Use __private/style__ with thin lines and muted color.", "unresolved wildcard"),
        ("Fetch http://private.invalid then use thin lines.", "connection data"),
        ("Create artwork by a named painter with thin lines.", "name-free"),
    ],
)
def test_signature_map_rejects_names_wildcards_and_endpoints(
    tmp_path: Path,
    signature: str,
    message: str,
) -> None:
    registry, signature_map, _ = fixtures(tmp_path)
    document = yaml.safe_load(signature_map.read_text(encoding="utf-8"))
    document["artists"]["artist_001"]["signature_prompt"] = signature
    signature_map.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        artist_abc_rows(registry, signature_map, ARTIST_IDS)


def test_jsonl_rows_contain_only_generic_runner_fields(tmp_path: Path) -> None:
    registry, signature_map, _ = fixtures(tmp_path)
    rows = artist_abc_rows(registry, signature_map, ARTIST_IDS)
    allowed = {
        "schema_version",
        "test_id",
        "style_id",
        "label",
        "mode",
        "seed",
        "prompt",
        "factors",
    }
    assert all(set(row) == allowed for row in rows)
    assert all(row["label"].startswith("artist_") for row in rows)
    assert all(json.loads(json.dumps(row))["factors"]["artist"] == row["style_id"] for row in rows)
