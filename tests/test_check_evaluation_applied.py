from __future__ import annotations

from copy import deepcopy

import pytest

from check_evaluation_applied import validate_applied_evaluation
from common import canonical_prompt_sha256


def fixture_documents() -> tuple[dict[str, object], dict[str, object]]:
    prompt = "A precise illustrated visual signature."
    digest = canonical_prompt_sha256(prompt)
    result = {
        "style_id": "artist_signature_one",
        "tested_seeds": 3,
        "recommended_status": "testing",
        "critical_failures": 0,
        "averages": {
            "prompt_adherence": 4.0,
            "style_fidelity": 4.0,
            "stability": 4.0,
            "character_quality": 4.0,
            "composition_quality": 4.0,
            "compatibility": 4.0,
            "distinctiveness": 4.0,
            "prompt_efficiency": 4.0,
        },
        "evaluated_prompt_sha256": digest,
    }
    summary: dict[str, object] = {
        "schema_version": 1,
        "style_count": 1,
        "styles": [result],
    }
    catalog: dict[str, object] = {
        "items": {
            "artist_signature_one": {
                "prompt": prompt,
                "validation": {
                    "tested_seeds": 3,
                    "status": "testing",
                    "last_evaluation": "repair_v1",
                    "evaluated_prompt_sha256": digest,
                    "prompt_adherence": 4.0,
                    "style_fidelity": 4.0,
                    "stability": 4.0,
                    "compatibility": 4.0,
                    "critical_failures": 0,
                },
            }
        }
    }
    return summary, catalog


def test_exact_applied_evaluation_is_reusable() -> None:
    summary, catalog = fixture_documents()

    assert validate_applied_evaluation(summary, catalog, "repair_v1") == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "generated"),
        ("tested_seeds", 5),
        ("last_evaluation", "other"),
        ("prompt_adherence", 3.0),
        ("critical_failures", 1),
    ],
)
def test_applied_evaluation_rejects_catalog_drift(field: str, value: object) -> None:
    summary, catalog = fixture_documents()
    changed = deepcopy(catalog)
    changed["items"]["artist_signature_one"]["validation"][field] = value

    with pytest.raises(ValueError, match="exact applied evaluation value"):
        validate_applied_evaluation(summary, changed, "repair_v1")


def test_applied_evaluation_rejects_unexpected_evaluation_id_reuse() -> None:
    summary, catalog = fixture_documents()
    changed = deepcopy(catalog)
    changed["items"]["unrelated"] = {
        "prompt": "Another prompt.",
        "validation": {
            "status": "testing",
            "last_evaluation": "repair_v1",
        },
    }

    with pytest.raises(ValueError, match="evaluation-id set"):
        validate_applied_evaluation(summary, changed, "repair_v1")
