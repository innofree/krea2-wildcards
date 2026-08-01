from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from common import SUBJECT_IDENTITY
from export_artist_visual_signature_matrix import (
    ARTIST_REFERENCE_RE,
    CATALOG_QUALITY_SUFFIX,
    ILLUSTRATED_BENCHMARK_FINISH,
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
        "shading, centered full-length framing, and sparse geometric accents."
    )


def lifecycle_neutral_real_catalog(tmp_path: Path) -> Path:
    document = yaml.safe_load(
        (ROOT / "catalog/artists.yaml").read_text(encoding="utf-8")
    )
    for item in document["items"].values():
        item["validation"] = {"status": "generated", "tested_seeds": 0}
    path = tmp_path / "artists.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_real_catalog_exports_exact_generated_three_seed_matrix(
    tmp_path: Path,
) -> None:
    catalog_path = lifecycle_neutral_real_catalog(tmp_path)
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
    for row in rows:
        assert set(row["factors"]) == {
            "line_language",
            "face_design",
            "eye_design",
            "body_design",
            "palette_language",
            "light_modeling",
            "framing_language",
            "ornament_language",
            "evaluated_prompt_sha256",
        }
        assert row["factors"]["evaluated_prompt_sha256"] == (
            "sha256_"
            + hashlib.sha256(
                catalog["items"][row["style_id"]]["prompt"].encode("utf-8")
            ).hexdigest()
        )
    assert len({row["test_id"] for row in rows}) == 900
    assert all(row["test_id"].startswith("VS") for row in rows)
    for row in rows:
        prompt = row["prompt"]
        assert SUBJECT_IDENTITY in prompt
        assert (
            "standing character-design portrait framed from mid-thigh upward" in prompt
        )
        assert "show both complete hands clearly" in prompt
        assert (
            "broad readable surfaces for the requested palette and ornament" in prompt
        )
        assert "quiet uncluttered studio ground" in prompt
        assert "face and both eyes large enough" in prompt
        assert "visual signature controls silhouette" in prompt
        assert (
            "clearly hand-drawn two-dimensional character-design illustration" in prompt
        )
        assert "unmistakably legible at contact-sheet scale" in prompt
        assert "contour character" in prompt
        assert "eye construction" in prompt
        assert "composition" in prompt
        assert "recurring motifs" in prompt
        assert "coherent illustrated anatomy" in prompt
        assert "clean garment shapes" in prompt
        assert "no text, logos, or watermarks" in prompt
        assert prompt.count(ILLUSTRATED_BENCHMARK_FINISH) == 1
        assert "Preserve realistic skin texture" not in prompt
        assert "@" not in prompt and "__" not in prompt and "::" not in prompt
        assert all(token not in prompt for token in ("{", "}", "[", "]"))
        assert not ARTIST_REFERENCE_RE.search(prompt)


def test_real_catalog_prompts_are_the_exact_evaluated_signature_bodies(
    tmp_path: Path,
) -> None:
    catalog_path = lifecycle_neutral_real_catalog(tmp_path)
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))["items"]
    rows = signature_rows(catalog_path)
    row_by_style = {row["style_id"]: row for row in rows}

    assert len(row_by_style) == 300
    for style_id, item in catalog.items():
        catalog_prompt = item["prompt"]
        evaluated_prompt = row_by_style[style_id]["prompt"]
        assert CATALOG_QUALITY_SUFFIX not in catalog_prompt
        assert (
            f"Every listed property must be visibly expressed: {catalog_prompt} "
            in evaluated_prompt
        )
        assert evaluated_prompt.count(catalog_prompt) == 1
        assert (
            row_by_style[style_id]["factors"]["evaluated_prompt_sha256"]
            == "sha256_"
            + hashlib.sha256(catalog_prompt.encode("utf-8")).hexdigest()
        )


def test_legacy_matrix_can_omit_prompt_digests_without_changing_other_factors(
    tmp_path: Path,
) -> None:
    rows = signature_rows(
        lifecycle_neutral_real_catalog(tmp_path),
        seeds=(1001,),
        limit_signatures=1,
        include_prompt_digest=False,
    )

    assert len(rows) == 1
    assert set(rows[0]["factors"]) == {
        "line_language",
        "face_design",
        "eye_design",
        "body_design",
        "palette_language",
        "light_modeling",
        "framing_language",
        "ornament_language",
    }


def test_signature_brief_precedes_fixed_scene_for_prompt_priority(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "artists.yaml"
    prompt = clean_prompt()
    write_catalog(
        catalog,
        {"artist_signature_generated": signature_item("generated", prompt)},
    )

    [row] = signature_rows(catalog, seeds=(1001,))

    assert row["prompt"].index("narrow architectural lines") < row["prompt"].index(
        f"Create exactly {SUBJECT_IDENTITY}"
    )


def test_status_and_extension_seed_filters_select_actual_catalog_ids(
    tmp_path: Path,
) -> None:
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


def test_diverse_calibration_subset_is_deterministic(tmp_path: Path) -> None:
    catalog_path = lifecycle_neutral_real_catalog(tmp_path)
    rows = signature_rows(catalog_path, limit_signatures=5)

    assert len(rows) == 15
    assert len({row["style_id"] for row in rows}) == 5
    assert {row["seed"] for row in rows} == {1001, 2002, 3003}
    assert rows == signature_rows(catalog_path, limit_signatures=5)


def test_calibration_subset_maximizes_feature_axis_coverage(tmp_path: Path) -> None:
    catalog_path = lifecycle_neutral_real_catalog(tmp_path)
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))["items"]
    rows = signature_rows(catalog_path, limit_signatures=5)
    style_ids = list(dict.fromkeys(row["style_id"] for row in rows))

    coverage = {
        axis: {
            value
            for style_id in style_ids
            for value in catalog[style_id]["feature_axes"][axis]
        }
        for axis in next(iter(catalog.values()))["feature_axes"]
    }
    assert {axis: len(values) for axis, values in coverage.items()} == {
        "line_language": 5,
        "face_design": 4,
        "eye_design": 4,
        "body_design": 4,
        "palette_language": 5,
        "light_modeling": 5,
        "framing_language": 4,
        "ornament_language": 4,
    }
    assert sum(len(values) for values in coverage.values()) == 35


@pytest.mark.parametrize("limit", [0, -1, 301])
def test_calibration_subset_rejects_invalid_limits(
    tmp_path: Path, limit: int
) -> None:
    with pytest.raises(ValueError, match="limit_signatures"):
        signature_rows(
            lifecycle_neutral_real_catalog(tmp_path),
            limit_signatures=limit,
        )


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

    with pytest.raises(
        ValueError, match="artist-name reference|unresolved wildcard|emphasis syntax"
    ):
        signature_rows(catalog)


def test_export_rejects_legacy_realistic_quality_suffix(tmp_path: Path) -> None:
    catalog = tmp_path / "artists.yaml"
    write_catalog(
        catalog,
        {
            "artist_signature_legacy": signature_item(
                "generated", f"{clean_prompt()} {CATALOG_QUALITY_SUFFIX}"
            )
        },
    )

    with pytest.raises(ValueError, match="unvalidated realistic quality suffix"):
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
    catalog = lifecycle_neutral_real_catalog(tmp_path)
    outputs = [tmp_path / "one.jsonl", tmp_path / "two.jsonl"]
    for output in outputs:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/export_artist_visual_signature_matrix.py"),
                "--catalog",
                str(catalog),
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

    assert (
        hashlib.sha256(outputs[0].read_bytes()).hexdigest()
        == hashlib.sha256(outputs[1].read_bytes()).hexdigest()
    )


def test_cli_refuses_to_replace_a_different_matrix(tmp_path: Path) -> None:
    catalog = lifecycle_neutral_real_catalog(tmp_path)
    output = tmp_path / "existing.jsonl"
    original = '{"preserved":true}\n'
    output.write_text(original, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/export_artist_visual_signature_matrix.py"),
            "--catalog",
            str(catalog),
            "--limit-signatures",
            "1",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "refusing to overwrite a different versioned prompt matrix" in result.stdout
    assert output.read_text(encoding="utf-8") == original


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
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
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
