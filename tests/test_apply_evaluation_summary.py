from __future__ import annotations

import pytest

from apply_evaluation_summary import update_catalog


def summary(status: str = "testing") -> dict[str, object]:
    return {
        "styles": [
            {
                "style_id": "one",
                "tested_seeds": 3,
                "averages": {
                    "prompt_adherence": 4,
                    "style_fidelity": 3,
                    "stability": 5,
                    "compatibility": 5,
                },
                "critical_failures": 0,
                "recommended_status": status,
            }
        ]
    }


def test_update_catalog_persists_lifecycle_and_metrics() -> None:
    catalog = {"items": {"one": {"validation": {"status": "generated"}}}}
    assert update_catalog(catalog, summary(), "screen_v1", {"generated"}) == 1
    assert catalog["items"]["one"]["validation"] == {
        "status": "testing",
        "tested_seeds": 3,
        "last_evaluation": "screen_v1",
        "prompt_adherence": 4,
        "style_fidelity": 3,
        "stability": 5,
        "compatibility": 5,
        "critical_failures": 0,
    }


def test_update_catalog_rejects_unexpected_source_status() -> None:
    catalog = {"items": {"one": {"validation": {"status": "approved"}}}}
    with pytest.raises(ValueError, match="disallowed source status"):
        update_catalog(catalog, summary(), "screen_v1", {"generated"})


def test_update_catalog_rejects_unknown_recommendation() -> None:
    catalog = {"items": {"one": {"validation": {"status": "generated"}}}}
    with pytest.raises(ValueError, match="invalid recommendation"):
        update_catalog(catalog, summary("limited"), "screen_v1", {"generated"})
