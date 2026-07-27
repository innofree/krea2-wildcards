from __future__ import annotations

import re
from pathlib import Path

from build_runtime_yaml import compile_catalog
from common import iter_leaf_lists, load_yaml


ROOT = Path(__file__).resolve().parents[1]
WILDCARD_RE = re.compile(r"__([a-z0-9_/]+)__")
GROUP_RE = re.compile(r"\{([^{}]+)\}")
PROHIBITED = re.compile(
    r"\b(?:velyra|child|minor|underage|anime|manga|illustration|cgi|digital[- ]art|2d|3d[- ]render)\b",
    re.I,
)
EXPANSION_TEMPLATE_PREFIX = "benchmark_expansion_"
EXPANSION_BLUEPRINTS = (
    ROOT / "catalog/blueprints/people_and_style.yaml",
    ROOT / "catalog/blueprints/scene_and_control.yaml",
)
FIXED_COMPLEMENT_MARKERS = {
    "style_pack": (
        "one adult woman",
        "plain fitted long-sleeve top",
        "balanced standing pose",
        "warm-grey studio cyclorama",
        "eye-level full-length camera",
        "cyclorama geometry fixed",
        "style visibly control palette",
    ),
    "artist_signature": (
        "standing character-design portrait",
        "mid-thigh upward",
        "both complete hands",
        "quiet uncluttered studio",
        "selected signature controls silhouette",
    ),
    "media_rendering": (
        "plain tailored coat",
        "balanced standing pose",
        "studio cyclorama",
        "eye-level full-length camera",
    ),
    "linework_coloring": (
        "plain long-sleeve top",
        "balanced standing pose",
        "studio cyclorama",
        "eye-level full-length camera",
    ),
    "character_design": (
        "relaxed neutral stance",
        "studio cyclorama",
        "full length at eye level",
        "broad diffused light",
    ),
    "hair_design": (
        "plain collared shirt",
        "relaxed upright posture",
        "chest-up eye-level camera",
        "broad diffused lighting",
    ),
    "fashion": (
        "balanced full-length contrapposto",
        "studio cyclorama",
        "eye-level camera",
        "broad diffused lighting",
    ),
    "pose": (
        "plain long-sleeve top",
        "warm-grey studio cyclorama",
        "broad diffused light",
        "eye-level full-length camera",
    ),
    "camera": (
        "balanced contrapposto",
        "warm-grey studio cyclorama",
        "broad diffused lighting",
    ),
    "lighting": (
        "balanced contrapposto",
        "studio cyclorama",
        "eye-level full-length camera",
    ),
    "background": (
        "balanced contrapposto",
        "full length at eye level",
        "broad neutral diffused light",
    ),
    "effect": (
        "balanced contrapposto",
        "charcoal long-sleeve top",
        "warm-grey studio cyclorama",
        "eye-level full-length camera",
        "broad diffused lighting",
    ),
}


def expansion_collections() -> dict[str, dict]:
    collections: dict[str, dict] = {}
    for blueprint_path in EXPANSION_BLUEPRINTS:
        for collection in load_yaml(blueprint_path)["collections"]:
            family = collection["family"]
            assert family not in collections, family
            collections[family] = collection
    return collections


def test_all_template_wildcards_resolve_in_preview(tmp_path: Path) -> None:
    output = tmp_path / "wildcards"
    compile_catalog(ROOT / "catalog", output, {"generated", "testing", "approved"})
    available: set[str] = set()
    for path in output.rglob("*.yaml"):
        for leaf_path, _ in iter_leaf_lists(load_yaml(path)):
            available.add("/".join(leaf_path))

    inputs = [
        *sorted(
            path
            for path in (ROOT / "templates").glob("*.txt")
            if not path.name.startswith(EXPANSION_TEMPLATE_PREFIX)
        ),
        ROOT / "tests/baseline/reference_prompts.txt",
    ]
    for path in inputs:
        text = path.read_text(encoding="utf-8")
        references = WILDCARD_RE.findall(text)
        assert references, path
        assert set(references) <= available, (path, set(references) - available)


def test_scene_templates_follow_prompt_pool_safety_and_option_counts() -> None:
    for path in sorted((ROOT / "templates").glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        is_artist_signature = (
            path.name == "benchmark_expansion_artist_signature.txt"
        )
        assert "adult" in text.lower(), path
        if is_artist_signature:
            assert "clearly hand-drawn two-dimensional" in text.lower(), path
            assert "coherent illustrated anatomy" in text.lower(), path
            assert "readable hands" in text.lower(), path
            assert "realistic skin texture" not in text.lower(), path
        else:
            assert "realistic skin texture" in text.lower(), path
            assert "coherent hands" in text.lower(), path
            assert "believable fabric" in text.lower(), path
            assert "natural proportions" in text.lower(), path
            assert "cinematic depth" in text.lower(), path
        assert "no text, logos, or watermarks" in text.lower() or "no generated text, logos, or watermarks" in text.lower(), path
        if not is_artist_signature:
            assert not PROHIBITED.search(text), path
        assert "BREAK," not in text

        groups = GROUP_RE.findall(text)
        for group in groups:
            assert "|" in group
            assert not re.search(r"\bor\b", group, re.I)
        if not path.name.startswith(("style_benchmark", EXPANSION_TEMPLATE_PREFIX)):
            option_counts = [group.count("|") + 1 for group in groups]
            assert option_counts == [6, 6, 4, 3, 3, 3], (path, option_counts)


def test_expansion_template_registry_has_exact_family_and_token_coverage() -> None:
    registry_data = load_yaml(ROOT / "catalog/expansion_templates.yaml")
    assert registry_data["schema_version"] == 1
    assert registry_data["catalog"] == "expansion_templates"

    registry = registry_data["templates"]
    collections = expansion_collections()
    assert set(registry) == set(collections)

    registered_paths = {ROOT / relative_path for relative_path in registry.values()}
    actual_paths = set((ROOT / "templates").glob(f"{EXPANSION_TEMPLATE_PREFIX}*.txt"))
    assert registered_paths == actual_paths

    for family, collection in collections.items():
        relative_path = registry[family]
        assert relative_path == f"templates/{EXPANSION_TEMPLATE_PREFIX}{family}.txt"
        template_path = ROOT / relative_path
        text = template_path.read_text(encoding="utf-8").strip()
        expected_reference = "/".join([*collection["runtime"]["path_prefix"], "all"])
        expected_token = f"__{expected_reference}__"
        assert WILDCARD_RE.findall(text) == [expected_reference], template_path
        assert text.count(expected_token) == 1, template_path


def test_expansion_templates_are_fixed_safe_benchmark_prompts() -> None:
    registry = load_yaml(ROOT / "catalog/expansion_templates.yaml")["templates"]
    quality_constraints = (
        "adult",
        "realistic skin texture",
        "coherent hands",
        "believable fabric",
        "natural proportions",
        "cinematic depth",
        "no text, logos, or watermarks",
    )

    for family, relative_path in registry.items():
        template_path = ROOT / relative_path
        text = template_path.read_text(encoding="utf-8").strip()
        lowered = text.lower()
        if family == "artist_signature":
            assert "clearly hand-drawn two-dimensional" in lowered, template_path
            assert "coherent illustrated anatomy" in lowered, template_path
            assert "realistic skin texture" not in lowered, template_path
            assert "cinematic depth" not in lowered, template_path
        else:
            assert all(
                constraint in lowered for constraint in quality_constraints
            ), template_path
        if family != "artist_signature":
            assert not PROHIBITED.search(text), template_path
        assert not GROUP_RE.findall(text), template_path
        assert "{" not in text and "}" not in text and "|" not in text, template_path
        assert "BREAK," not in text, template_path
        assert 3 <= len(re.findall(r"[.!?](?:\s|$)", text)) <= 5, template_path
        for marker in FIXED_COMPLEMENT_MARKERS.get(family, ()):
            assert marker in lowered, (template_path, marker)

    controlled_axis_words = re.compile(
        r"\b(?:wears|standing|seated|camera|lighting|palette|cyclorama)\b",
        re.I,
    )
    for family in ("preset",):
        text = (ROOT / registry[family]).read_text(encoding="utf-8")
        assert not controlled_axis_words.search(text), (family, text)


def test_style_pack_template_does_not_neutralize_style_control_axes() -> None:
    path = ROOT / "templates/benchmark_expansion_style_pack.txt"
    text = path.read_text(encoding="utf-8").lower()

    assert "broad neutral diffused lighting" not in text
    assert "palette, tonal divisions, surface texture, atmosphere, and edge behavior" in text
