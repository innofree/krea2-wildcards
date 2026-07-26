from __future__ import annotations

import hashlib
import json
from pathlib import Path

from common import load_yaml


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_baseline_reproducibility_proof_is_exact() -> None:
    settings = load_yaml(ROOT / "tests/baseline/settings.yaml")
    reproducibility = settings["reproducibility"]
    proof = json.loads((ROOT / reproducibility["proof"]).read_text(encoding="utf-8"))

    assert sha256(ROOT / proof["workflow"]) == proof["workflow_sha256"]
    assert proof["workflow_sha256"] == reproducibility["workflow_sha256"]
    assert sha256(ROOT / proof["reference_image"]) == proof["image_sha256"]
    assert sha256(ROOT / proof["repeat_image"]) == proof["image_sha256"]
    assert proof["pixel_absolute_error"] == 0
    assert proof["selected_metadata_equal"] is True
    assert proof["result"] == "exact_reproduction"
