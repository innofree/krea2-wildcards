from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from generate_catalog_expansion import (
    GENERATOR_ID,
    apply_compilation,
    compile_expansion,
    file_sha256,
)
from lint_wildcards import lint_file


def collection() -> dict:
    return {
        "id": "sample_character",
        "kind": "character_design",
        "output_file": "generated_characters.yaml",
        "family": "character_design",
        "runtime": {
            "file": "krea2/character/design_language.yaml",
            "path_prefix": ["krea2", "character", "design_language"],
        },
        "source_refs": ["internal_taxonomy_v1"],
        "target_count": 7,
        "dimensions": [
            {
                "id": "silhouette",
                "values": [
                    {"id": "tall", "text": "a tall balanced adult silhouette"},
                    {"id": "compact", "text": "a compact grounded adult silhouette"},
                    {"id": "broad", "text": "a broad stable adult silhouette"},
                ],
            },
            {
                "id": "palette",
                "values": [
                    {"id": "mineral", "text": "a quiet blue and ivory mineral palette"},
                    {"id": "earth", "text": "a warm clay and olive earth palette"},
                ],
            },
        ],
        "templates": [
            {
                "id": "portrait",
                "text": (
                    "An adult subject has {silhouette} with {palette}. Preserve realistic skin "
                    "texture, coherent hands, believable fabric, natural proportions, cinematic "
                    "depth, and a frame free of text, logos, and watermarks."
                ),
            },
            {
                "id": "editorial",
                "text": (
                    "A composed adult subject uses {silhouette} and {palette}. Preserve realistic "
                    "skin texture, coherent hands, believable fabric, natural proportions, "
                    "cinematic depth, and a frame free of text, logos, and watermarks."
                ),
            },
        ],
        "compatibility": {"avoid": ["chibi_proportions"]},
    }


def fixture_tree(tmp_path: Path, raw_collection: dict | None = None) -> tuple[Path, Path, Path, Path]:
    blueprints = tmp_path / "blueprints"
    output = tmp_path / "catalog"
    blueprints.mkdir(parents=True)
    output.mkdir(parents=True)
    sources = output / "sources.yaml"
    sources.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "catalog": "sources",
                "sources": {"internal_taxonomy_v1": {"title": "Fixture source"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (blueprints / "sample.yaml").write_text(
        yaml.safe_dump(
            {"schema_version": 1, "collections": [raw_collection or collection()]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return blueprints, output, sources, tmp_path / "build/manifest.json"


def compile_fixture(tmp_path: Path, raw_collection: dict | None = None):
    blueprints, output, sources, manifest = fixture_tree(tmp_path, raw_collection)
    return compile_expansion(blueprints, output, sources, manifest), output, manifest


def set_managed_validations(
    output: Path,
    manifest: Path,
    statuses: dict[str, tuple[str, int]],
) -> None:
    catalog_path = output / "generated_characters.yaml"
    document = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    for item_id, (status, tested_seeds) in statuses.items():
        document["items"][item_id]["validation"] = {
            "model": "krea2_turbo",
            "tested_seeds": tested_seeds,
            "status": status,
        }
    catalog_path.write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    evidence = json.loads(manifest.read_text(encoding="utf-8"))
    evidence["outputs"][0]["sha256"] = file_sha256(catalog_path)
    manifest.write_text(json.dumps(evidence), encoding="utf-8")


def test_exact_selection_is_deterministic_unique_and_balanced(tmp_path: Path) -> None:
    first, _, _ = compile_fixture(tmp_path)
    second = compile_expansion(
        tmp_path / "blueprints",
        tmp_path / "catalog",
        tmp_path / "catalog/sources.yaml",
        tmp_path / "build/manifest.json",
    )
    items = first.documents["generated_characters.yaml"]["items"]

    assert len(items) == 7
    assert first.rendered == second.rendered
    assert first.manifest == second.manifest
    assert len(set(items)) == 7
    assert len({item["prompt"].lower().strip(".,;:") for item in items.values()}) == 7

    for axis in ("silhouette", "palette"):
        counts = Counter(item["feature_axes"][axis][0] for item in items.values())
        assert max(counts.values()) - min(counts.values()) <= 1
    template_counts = Counter(item["generation"]["template_id"] for item in items.values())
    assert max(template_counts.values()) - min(template_counts.values()) <= 1


def test_output_items_match_schema_v1_contract(tmp_path: Path) -> None:
    compilation, _, _ = compile_fixture(tmp_path)
    item_id, item = next(iter(compilation.documents["generated_characters.yaml"]["items"].items()))

    assert item["family"] == "character_design"
    assert item["visual_axes"]
    assert set(item["feature_axes"]) == {"silhouette", "palette"}
    assert item["source_refs"] == ["internal_taxonomy_v1"]
    assert item["runtime"]["path"][-1] == item_id
    assert item["validation"] == {
        "model": "krea2_turbo",
        "tested_seeds": 0,
        "status": "generated",
    }


def test_product_too_small_is_rejected(tmp_path: Path) -> None:
    raw = collection()
    raw["target_count"] = 13

    with pytest.raises(ValueError, match="Cartesian product is too small"):
        compile_fixture(tmp_path, raw)


def test_item_id_length_is_bounded_for_run_directory_safety(tmp_path: Path) -> None:
    raw = collection()
    raw["dimensions"][0]["values"][0]["id"] = "value_" + "x" * 170

    with pytest.raises(ValueError, match="overlong item ID"):
        compile_fixture(tmp_path, raw)


def test_duplicate_ids_and_normalized_text_are_rejected(tmp_path: Path) -> None:
    raw = collection()
    raw["dimensions"][0]["values"][1]["id"] = "tall"
    with pytest.raises(ValueError, match="duplicate value ID"):
        compile_fixture(tmp_path, raw)

    other = tmp_path / "other"
    raw = collection()
    raw["dimensions"][0]["values"][1]["text"] = "  a tall balanced adult silhouette  "
    with pytest.raises(ValueError, match="trimmed"):
        compile_fixture(other, raw)

    third = tmp_path / "third"
    raw = collection()
    raw["dimensions"][0]["values"][1]["text"] = "A TALL   balanced adult silhouette."
    with pytest.raises(ValueError, match="duplicate normalized value text"):
        compile_fixture(third, raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("output_file", "../outside.yaml"),
        ("output_file", "sources.yaml"),
        ("runtime_file", "../runtime.yaml"),
    ],
)
def test_unsafe_paths_are_rejected(tmp_path: Path, field: str, value: str) -> None:
    raw = collection()
    if field == "runtime_file":
        raw["runtime"]["file"] = value
    else:
        raw[field] = value

    with pytest.raises(ValueError, match="safe"):
        compile_fixture(tmp_path, raw)


def test_missing_and_unknown_placeholders_are_rejected(tmp_path: Path) -> None:
    raw = collection()
    raw["templates"][0]["text"] = "An adult subject has {silhouette} with controlled detail."
    with pytest.raises(ValueError, match="missing placeholder"):
        compile_fixture(tmp_path, raw)

    other = tmp_path / "other"
    raw = collection()
    raw["templates"][0]["text"] += " {unknown_axis}"
    with pytest.raises(ValueError, match="unknown placeholder"):
        compile_fixture(other, raw)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "an anime character rendering",
        "a schoolgirl character design",
        "score_9 polished visual treatment",
        "a tagged_value visual treatment",
        "a {wildcard|choice} visual treatment",
    ],
)
def test_invalid_prose_and_tokens_are_rejected(tmp_path: Path, unsafe_text: str) -> None:
    raw = collection()
    raw["dimensions"][0]["values"][0]["text"] = unsafe_text

    with pytest.raises(ValueError, match="syntax|token|subject|prose"):
        compile_fixture(tmp_path, raw)


def test_repeated_quality_words_and_adjacent_duplicates_are_rejected(tmp_path: Path) -> None:
    raw = collection()
    raw["templates"][0]["text"] = (
        "A polished adult subject has {silhouette} with {palette} and a polished finish. "
        "Preserve realistic skin texture, coherent hands, believable fabric, natural proportions, "
        "cinematic depth, and a frame free of text, logos, and watermarks."
    )
    with pytest.raises(ValueError, match="abstract quality word 'polished'"):
        compile_fixture(tmp_path, raw)

    other = tmp_path / "other"
    raw = collection()
    raw["dimensions"][0]["values"][0]["text"] = "a balanced balanced adult silhouette"
    with pytest.raises(ValueError, match="adjacent word 'balanced'"):
        compile_fixture(other, raw)


def test_repeated_structural_nouns_are_allowed_by_generator_and_linter(tmp_path: Path) -> None:
    raw = collection()
    raw["templates"][0]["text"] = (
        "Light shapes {silhouette} with {palette}. Light remains coherent while reflected light "
        "supports the adult subject, realistic skin texture, coherent hands, believable fabric, "
        "natural proportions, cinematic depth, and a frame free of text, logos, and watermarks."
    )
    compilation, _, _ = compile_fixture(tmp_path, raw)
    assert compilation.manifest["total_item_count"] == 7

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    safe_path = runtime / "safe.yaml"
    safe_path.write_text(
        yaml.safe_dump(
            {
                "krea2": {
                    "lighting": {
                        "structural": [
                            "Soft light shapes the face while reflected light keeps shadow-side light readable"
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert lint_file(safe_path, max_length=600) == []


def test_runtime_linter_uses_the_same_quality_and_adjacent_word_policy(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    path = runtime / "invalid.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "krea2": {
                    "style": {
                        "quality_repeat": [
                            "A polished adult portrait with a polished visual finish"
                        ],
                        "adjacent_repeat": ["Controlled light light across an adult portrait"],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    errors = lint_file(path, max_length=600)

    assert any("abstract quality word 'polished'" in error for error in errors)
    assert any("adjacent word 'light'" in error for error in errors)


def test_apply_is_atomic_writes_manifest_and_can_be_repeated(tmp_path: Path) -> None:
    compilation, output, manifest = compile_fixture(tmp_path)
    apply_compilation(compilation, output, manifest)
    catalog_path = output / "generated_characters.yaml"
    document = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    evidence = json.loads(manifest.read_text(encoding="utf-8"))

    assert len(document["items"]) == 7
    assert evidence["generator"] == GENERATOR_ID
    assert evidence["total_item_count"] == 7
    assert evidence["outputs"][0]["sha256"] == file_sha256(catalog_path)
    assert not Path(evidence["outputs"][0]["path"]).is_absolute()
    assert evidence["collections"][0]["product_size"] == 12
    assert not list(output.glob(".generated_characters.yaml.*"))
    assert not list(manifest.parent.glob(".manifest.json.*"))

    repeated = compile_expansion(
        tmp_path / "blueprints",
        output,
        output / "sources.yaml",
        manifest,
    )
    apply_compilation(repeated, output, manifest)
    assert file_sha256(catalog_path) == evidence["outputs"][0]["sha256"]


def test_existing_unrelated_items_are_preserved(tmp_path: Path) -> None:
    blueprints, output, sources, manifest = fixture_tree(tmp_path)
    existing = {
        "schema_version": 1,
        "catalog": "generated_characters",
        "items": {
            "hand_authored": {
                "prompt": "A hand-authored mature portrait with restrained color and clear spacing"
            }
        },
    }
    (output / "generated_characters.yaml").write_text(
        yaml.safe_dump(existing, sort_keys=False), encoding="utf-8"
    )

    compilation = compile_expansion(blueprints, output, sources, manifest)
    apply_compilation(compilation, output, manifest)
    document = yaml.safe_load((output / "generated_characters.yaml").read_text(encoding="utf-8"))

    assert "hand_authored" in document["items"]
    assert len(document["items"]) == 8
    assert compilation.manifest["outputs"][0]["generated_item_count"] == 7
    assert compilation.manifest["outputs"][0]["item_count"] == 8


def test_override_resets_rejected_item_and_preserves_unchanged_approval(
    tmp_path: Path,
) -> None:
    compilation, output, manifest = compile_fixture(tmp_path)
    apply_compilation(compilation, output, manifest)
    item_ids = list(compilation.documents["generated_characters.yaml"]["items"])
    approved_id, rejected_id = item_ids[:2]
    set_managed_validations(
        output,
        manifest,
        {approved_id: ("approved", 5), rejected_id: ("rejected", 3)},
    )

    blueprint_path = tmp_path / "blueprints/sample.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    blueprint["collections"][0]["prompt_overrides"] = {
        rejected_id: "Show three unmistakable vertical light bands around the adult figure."
    }
    blueprint_path.write_text(
        yaml.safe_dump(blueprint, sort_keys=False), encoding="utf-8"
    )

    revised = compile_expansion(
        tmp_path / "blueprints", output, output / "sources.yaml", manifest
    )
    items = revised.documents["generated_characters.yaml"]["items"]

    assert items[approved_id]["validation"] == {
        "model": "krea2_turbo",
        "tested_seeds": 5,
        "status": "approved",
    }
    assert items[rejected_id]["validation"] == {
        "model": "krea2_turbo",
        "tested_seeds": 0,
        "status": "generated",
    }
    assert "three unmistakable vertical light bands" in items[rejected_id]["prompt"]


def test_retry_profile_rewrites_only_rejected_items(tmp_path: Path) -> None:
    raw = collection()
    raw["templates"] = raw["templates"][:1]
    raw["target_count"] = 6
    compilation, output, manifest = compile_fixture(tmp_path, raw)
    apply_compilation(compilation, output, manifest)
    initial_items = compilation.documents["generated_characters.yaml"]["items"]
    approved_id, rejected_id = list(initial_items)[:2]
    set_managed_validations(
        output,
        manifest,
        {approved_id: ("approved", 5), rejected_id: ("rejected", 3)},
    )

    blueprint_path = tmp_path / "blueprints/sample.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    blueprint["collections"][0]["retry"] = {
        "template": (
            "Photograph one adult with {silhouette} and {palette}. Keep realistic skin, "
            "coherent hands, believable fabric, natural proportions, cinematic depth, and no "
            "text, logos, or watermarks."
        ),
        "dimensions": {
            "silhouette": {
                "tall": "three unmistakable tall light columns behind the adult",
                "compact": "one compact circular light field behind the adult",
                "broad": "a broad hard-edged arch surrounding the adult",
            },
            "palette": {
                "mineral": "only slate blue and warm ivory across the frame",
                "earth": "only warm clay and muted olive across the frame",
            },
        },
    }
    blueprint["collections"][0]["retry_prompt_overrides"] = {
        rejected_id: "Add one unmistakable floor-to-ceiling torn paper mural behind the adult."
    }
    blueprint_path.write_text(
        yaml.safe_dump(blueprint, sort_keys=False), encoding="utf-8"
    )

    revised = compile_expansion(
        tmp_path / "blueprints", output, output / "sources.yaml", manifest
    )
    items = revised.documents["generated_characters.yaml"]["items"]

    assert items[approved_id]["prompt"] == initial_items[approved_id]["prompt"]
    assert items[approved_id]["validation"]["status"] == "approved"
    assert items[rejected_id]["prompt"] != initial_items[rejected_id]["prompt"]
    assert "floor-to-ceiling torn paper mural" in items[rejected_id]["prompt"]
    assert items[rejected_id]["validation"] == {
        "model": "krea2_turbo",
        "tested_seeds": 0,
        "status": "generated",
    }
    assert items[rejected_id]["generation"]["prompt_profile"] == "retry"
    assert all("_retry_prompt" not in item for item in items.values())

    apply_compilation(revised, output, manifest)
    repeated = compile_expansion(
        tmp_path / "blueprints", output, output / "sources.yaml", manifest
    )
    assert repeated.rendered == revised.rendered
    assert repeated.manifest == revised.manifest


def test_retry_profile_requires_exact_dimension_value_coverage(tmp_path: Path) -> None:
    raw = collection()
    raw["retry"] = {
        "template": "Photograph one adult with {silhouette} and {palette} in a clean studio.",
        "dimensions": {
            "silhouette": {
                "tall": "three tall light columns behind the adult",
                "compact": "one compact circular field behind the adult",
            },
            "palette": {
                "mineral": "a slate blue and ivory palette",
                "earth": "a clay and olive palette",
            },
        },
    }

    with pytest.raises(ValueError, match="must exactly match collection values"):
        compile_fixture(tmp_path, raw)


def test_override_cannot_rewrite_approved_item(tmp_path: Path) -> None:
    compilation, output, manifest = compile_fixture(tmp_path)
    apply_compilation(compilation, output, manifest)
    approved_id = next(iter(compilation.documents["generated_characters.yaml"]["items"]))
    set_managed_validations(output, manifest, {approved_id: ("approved", 5)})

    blueprint_path = tmp_path / "blueprints/sample.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    blueprint["collections"][0]["prompt_overrides"] = {
        approved_id: "Show three unmistakable vertical light bands around the adult figure."
    }
    blueprint_path.write_text(
        yaml.safe_dump(blueprint, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="refusing to rewrite managed 'approved' item"):
        compile_expansion(
            tmp_path / "blueprints", output, output / "sources.yaml", manifest
        )


def test_override_for_unselected_item_is_rejected(tmp_path: Path) -> None:
    raw = collection()
    raw["prompt_overrides"] = {
        "sample_character_unselected_value": (
            "Show three unmistakable vertical light bands around the adult figure."
        )
    }

    with pytest.raises(ValueError, match="override.*unselected item"):
        compile_fixture(tmp_path, raw)


def test_tampered_managed_output_is_never_overwritten(tmp_path: Path) -> None:
    compilation, output, manifest = compile_fixture(tmp_path)
    apply_compilation(compilation, output, manifest)
    path = output / "generated_characters.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# external change\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed outside"):
        compile_expansion(tmp_path / "blueprints", output, output / "sources.yaml", manifest)


def test_blueprint_digest_uses_sorted_raw_file_hash_records(tmp_path: Path) -> None:
    compilation, _, _ = compile_fixture(tmp_path)
    records = compilation.manifest["blueprints"]
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    assert compilation.manifest["blueprint_digest"] == hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()
