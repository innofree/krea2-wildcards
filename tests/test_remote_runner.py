from __future__ import annotations

import json
from pathlib import Path

from run_remote_benchmark import (
    benchmark_prompt,
    prepare_workflow,
    resolved_benchmark_prompt,
)
from run_remote_pilot import PILOT_TEMPLATES, pilot_jobs, write_scorecard


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_workflow_sets_leaf_prompt_seed_and_output_prefix() -> None:
    workflow = json.loads((ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8"))
    prompt = benchmark_prompt(ROOT / "templates/style_benchmark.txt", "sumi_mist")
    prepared = prepare_workflow(workflow, prompt, "sumi_mist", 2002)

    assert "__krea2/style/complete_pack/sumi_mist__" in prepared["4"]["inputs"]["populated_text"]
    assert prepared["4"]["inputs"]["mode"] == "fixed"
    assert prepared["4"]["inputs"]["seed"] == 2002
    assert prepared["8"]["inputs"]["seed"] == 2002
    assert prepared["10"]["inputs"]["filename_prefix"].endswith("sumi_mist_seed_2002")


def test_baseline_workflow_has_no_lora_nodes() -> None:
    workflow = json.loads((ROOT / "tests/baseline/workflow.json").read_text(encoding="utf-8"))
    class_types = {node["class_type"] for node in workflow.values()}
    assert not any("lora" in class_type.lower() for class_type in class_types)
    assert workflow["8"]["inputs"]["steps"] == 8
    assert workflow["8"]["inputs"]["cfg"] == 1.0
    assert workflow["8"]["inputs"]["sampler_name"] == "euler"
    assert workflow["8"]["inputs"]["scheduler"] == "simple"


def test_resolved_prompt_logs_exact_catalog_value() -> None:
    resolved = resolved_benchmark_prompt(
        ROOT / "templates/style_benchmark.txt",
        ROOT / "catalog/art_styles.yaml",
        "crystal_iris_pastel",
    )
    assert "__krea2/" not in resolved
    assert "Refined character artwork with thin tapered contours" in resolved


def test_benchmark_prompt_uses_catalog_runtime_route(tmp_path: Path) -> None:
    catalog = tmp_path / "items.yaml"
    catalog.write_text(
        """items:\n  soft_turn:\n    prompt: a soft turning pose\n    runtime:\n      path: [krea2, pose, standing, soft_turn]\n""",
        encoding="utf-8",
    )
    template = tmp_path / "template.txt"
    template.write_text(
        "__krea2/pose/standing/all__. An adult subject in a fixed studio.",
        encoding="utf-8",
    )
    prompt = benchmark_prompt(template, "soft_turn", catalog)
    assert "__krea2/pose/standing/soft_turn__" in prompt
    assert resolved_benchmark_prompt(template, catalog, "soft_turn").startswith(
        "a soft turning pose"
    )


def test_pilot_matrix_has_five_styles_and_three_seeds() -> None:
    jobs = pilot_jobs()
    assert len(jobs) == 15
    assert len({style_id for style_id, _ in jobs}) == 5
    assert {seed for _, seed in jobs} == {1001, 2002, 3003}
    assert set(PILOT_TEMPLATES) == {style_id for style_id, _ in jobs}
    assert {seed for _, seed in pilot_jobs((4004, 5005))} == {4004, 5005}
    assert len(pilot_jobs((4004, 5005))) == 10


def test_family_benchmark_templates_fix_scene_axes() -> None:
    for template in PILOT_TEMPLATES.values():
        text = (ROOT / template).read_text(encoding="utf-8")
        assert text.count("__krea2/style/complete_pack/all__") == 1
        assert "An adult " in text
        assert "{" not in text and "}" not in text
        assert "realistic skin texture" in text
        assert "no text, logos, or watermarks" in text


def test_every_style_family_has_a_fixed_benchmark_template() -> None:
    from common import load_yaml

    templates = load_yaml(ROOT / "catalog/family_templates.yaml")["templates"]
    families = load_yaml(ROOT / "catalog/compatibility.yaml")["style_families"]
    assert set(templates) == set(families)
    for template in templates.values():
        assert (ROOT / template).is_file()


def test_existing_scorecard_is_preserved_without_explicit_overwrite(tmp_path: Path) -> None:
    scorecard = tmp_path / "pilot.csv"
    scorecard.write_text("manually scored\n", encoding="utf-8")
    write_scorecard(scorecard)
    assert scorecard.read_text(encoding="utf-8") == "manually scored\n"
