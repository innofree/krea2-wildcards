from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from export_artist_visual_signature_matrix import (
    ARTIST_REFERENCE_RE,
    CATALOG_QUALITY_SUFFIX,
    signature_rows,
    validate_statuses,
)


ROOT = Path(__file__).resolve().parents[1]


def signature_item(status: str, prompt: str) -> dict[str, object]:
    axes = [f"axis_{index}" for index in range(8)]
    return {
        "family": "artist_signature",
        "visual_axes": axes,
        "feature_axes": {axis: [f"value_{index}"] for index, axis in enumerate(axes)},
        "prompt": prompt,
        "validation": {"status": status, "tested_seeds": 0},
        "generation": {"kind": "artist_signature"},
    }


def write_catalog(path: Path, items: dict[str, dict[str, object]]) -> None:
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "catalog": "artists", "items": items},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def clean_prompt() -> str:
    return (
        "An adult portrait uses narrow architectural lines, a softly rounded face, layered irises, "
        "natural long-limbed proportions, a restrained blue and clay palette, clean two-step "
        "shading, centered full-length framing, and sparse geometric accents. "
        f"{CATALOG_QUALITY_SUFFIX}"
    )


def test_real_catalog_exports_exact_generated_three_seed_matrix() -> None:
    catalog_path = ROOT / "catalog/artists.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    generated = {
        style_id
        for style_id, item in catalog["items"].items()
        if item["validation"]["status"] == "generated"
    }

    rows = signature_rows(catalog_path)

    assert len(generated) == 300
    assert len(rows) == 900
    assert {row["style_id"] for row in rows} == generated
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    assert {row["mode"] for row in rows} == {"visual_signature"}
    assert len({row["test_id"] for row in rows}) == 900
    assert all(row["test_id"].startswith("VS") for row in rows)
    for row in rows:
        prompt = row["prompt"]
        assert "exactly one adult woman" in prompt
        assert "warm-grey studio cyclorama" in prompt
        assert "eye-level full-length camera" in prompt
        assert "realistic skin texture" in prompt
        assert "coherent hands" in prompt
        assert "believable fabric" in prompt
        assert "natural proportions" in prompt
        assert "cinematic depth" in prompt
        assert "no text, logos, or watermarks" in prompt
        assert prompt.count("Preserve realistic skin texture") == 1
        assert "@" not in prompt and "__" not in prompt and "::" not in prompt
        assert all(token not in prompt for token in ("{", "}", "[", "]"))
        assert not ARTIST_REFERENCE_RE.search(prompt)


def test_status_and_extension_seed_filters_select_actual_catalog_ids(tmp_path: Path) -> None:
    catalog = tmp_path / "artists.yaml"
    write_catalog(
        catalog,
        {
            "artist_signature_generated": signature_item("generated", clean_prompt()),
            "artist_signature_testing": signature_item("testing", clean_prompt()),
            "artist_signature_approved": signature_item("approved", clean_prompt()),
            "artist_signature_rejected": signature_item(
                "rejected", "Artwork influenced by Ignored Name with narrow lines."
            ),
        },
    )

    rows = signature_rows(
        catalog,
        (4004, 5005),
        statuses=("testing", "approved"),
    )

    assert len(rows) == 4
    assert {row["style_id"] for row in rows} == {
        "artist_signature_testing",
        "artist_signature_approved",
    }
    assert {row["seed"] for row in rows} == {4004, 5005}
    assert rows[0]["style_id"] == "artist_signature_approved"


@pytest.mark.parametrize(
    "prompt",
    [
        "Use @sample_name with narrow lines.",
        "Use __krea2/artist_signature/all__ with narrow lines.",
        "Use {strong narrow lines} and a rounded face.",
        "Use [weak shading] and a rounded face.",
        "Use 1.2::narrow lines and a rounded face.",
        "Artwork influenced by Sample Name with narrow lines.",
        "Use one artist's recognizable linework.",
    ],
)
def test_export_rejects_named_or_model_specific_prompt_syntax(
    tmp_path: Path, prompt: str
) -> None:
    catalog = tmp_path / "artists.yaml"
    write_catalog(
        catalog,
        {"artist_signature_unsafe": signature_item("generated", prompt)},
    )

    with pytest.raises(ValueError, match="artist-name reference|unresolved wildcard|emphasis syntax"):
        signature_rows(catalog)


def test_status_filter_rejects_duplicates_and_empty_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="distinct"):
        validate_statuses(["generated", "generated"])
    catalog = tmp_path / "artists.yaml"
    write_catalog(
        catalog,
        {"artist_signature_generated": signature_item("generated", clean_prompt())},
    )
    with pytest.raises(ValueError, match="no artist signatures matched"):
        signature_rows(catalog, statuses=("approved",))


def test_cli_is_byte_deterministic_and_defaults_to_900_rows(tmp_path: Path) -> None:
    outputs = [tmp_path / "one.jsonl", tmp_path / "two.jsonl"]
    for output in outputs:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/export_artist_visual_signature_matrix.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout or result.stderr
        assert "900 resolved prompt(s)" in result.stdout
        assert len(output.read_text(encoding="utf-8").splitlines()) == 900

    assert hashlib.sha256(outputs[0].read_bytes()).hexdigest() == hashlib.sha256(
        outputs[1].read_bytes()
    ).hexdigest()


def test_cli_accepts_repeated_statuses_and_extension_seeds(tmp_path: Path) -> None:
    catalog = tmp_path / "artists.yaml"
    output = tmp_path / "extension.jsonl"
    write_catalog(
        catalog,
        {
            "artist_signature_generated": signature_item("generated", clean_prompt()),
            "artist_signature_testing": signature_item("testing", clean_prompt()),
            "artist_signature_approved": signature_item("approved", clean_prompt()),
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/export_artist_visual_signature_matrix.py"),
            "--catalog",
            str(catalog),
            "--output",
            str(output),
            "--status",
            "testing",
            "--status",
            "approved",
            "--seed",
            "4004",
            "--seed",
            "5005",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert {row["style_id"] for row in rows} == {
        "artist_signature_testing",
        "artist_signature_approved",
    }
    assert {row["seed"] for row in rows} == {4004, 5005}
    assert "statuses=testing,approved" in result.stdout


def test_cli_help_documents_repeatable_status_and_seed_filters() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/export_artist_visual_signature_matrix.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    normalized = " ".join(result.stdout.split())
    assert "--status {approved,generated,testing}" in normalized
    assert "repeat for multiple statuses" in normalized
    assert "--seed SEED" in normalized
    assert "repeat for extension seeds" in normalized
