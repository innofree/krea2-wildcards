from __future__ import annotations

import pytest

from apply_evaluation_summary import update_catalog, validate_transition_gate
from common import canonical_prompt_sha256


PROMPT = "An exact canonical visual signature prompt."


def summary(
    status: str = "testing", *, prompt_sha256: str | None = None
) -> dict[str, object]:
    return {
        "styles": [
            {
                "style_id": "one",
                "evaluated_prompt_sha256": (
                    prompt_sha256 or canonical_prompt_sha256(PROMPT)
                ),
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
    catalog = {
        "items": {
            "one": {
                "prompt": PROMPT,
                "validation": {"status": "generated"},
            }
        }
    }
    assert update_catalog(catalog, summary(), "screen_v1", {"generated"}) == 1
    assert catalog["items"]["one"]["validation"] == {
        "status": "testing",
        "tested_seeds": 3,
        "last_evaluation": "screen_v1",
        "evaluated_prompt_sha256": canonical_prompt_sha256(PROMPT),
        "prompt_adherence": 4,
        "style_fidelity": 3,
        "stability": 5,
        "compatibility": 5,
        "critical_failures": 0,
    }


def test_update_catalog_rejects_unexpected_source_status() -> None:
    catalog = {
        "items": {
            "one": {"prompt": PROMPT, "validation": {"status": "approved"}}
        }
    }
    with pytest.raises(ValueError, match="disallowed source status"):
        update_catalog(catalog, summary(), "screen_v1", {"generated"})


def test_update_catalog_rejects_unknown_recommendation() -> None:
    catalog = {
        "items": {
            "one": {"prompt": PROMPT, "validation": {"status": "generated"}}
        }
    }
    with pytest.raises(ValueError, match="invalid recommendation"):
        update_catalog(catalog, summary("limited"), "screen_v1", {"generated"})


def test_transition_gate_requires_exact_source_set_and_seed_count() -> None:
    catalog = {
        "items": {
            "one": {"validation": {"status": "generated"}},
            "two": {"prompt": PROMPT, "validation": {"status": "generated"}},
        }
    }
    catalog["items"]["one"]["prompt"] = PROMPT
    document = summary()
    with pytest.raises(ValueError, match="exactly match"):
        validate_transition_gate(
            catalog,
            document,
            {"generated"},
            require_exact_source_set=True,
            required_tested_seeds=3,
        )

    document["styles"].append(
        {
            **document["styles"][0],
            "style_id": "two",
            "tested_seeds": 2,
        }
    )
    with pytest.raises(ValueError, match="exactly 3 tested seeds"):
        validate_transition_gate(
            catalog,
            document,
            {"generated"},
            require_exact_source_set=True,
            required_tested_seeds=3,
        )


def test_transition_gate_enforces_allowed_and_minimum_recommendations() -> None:
    catalog = {
        "items": {
            "one": {"prompt": PROMPT, "validation": {"status": "testing"}}
        }
    }
    document = summary("approved")
    document["styles"][0]["tested_seeds"] = 5

    with pytest.raises(ValueError, match="disallowed recommendation"):
        validate_transition_gate(
            catalog,
            document,
            {"testing"},
            allowed_recommendations={"rejected"},
        )
    with pytest.raises(ValueError, match="minimum is 2"):
        validate_transition_gate(
            catalog,
            document,
            {"testing"},
            required_tested_seeds=5,
            allowed_recommendations={"approved", "rejected"},
            minimum_recommendations={"approved": 2},
        )

    assert validate_transition_gate(
        catalog,
        document,
        {"testing"},
        require_exact_source_set=True,
        required_tested_seeds=5,
        allowed_recommendations={"approved", "rejected"},
        minimum_recommendations={"approved": 1},
    ) == {"approved": 1}


def test_missing_or_stale_evaluated_prompt_digest_is_rejected() -> None:
    catalog = {
        "items": {
            "one": {"prompt": PROMPT, "validation": {"status": "generated"}}
        }
    }
    missing = summary()
    del missing["styles"][0]["evaluated_prompt_sha256"]  # type: ignore[index]
    with pytest.raises(ValueError, match="missing a valid evaluated_prompt_sha256"):
        validate_transition_gate(catalog, missing, {"generated"})

    stale = summary(prompt_sha256=canonical_prompt_sha256("A previous prompt."))
    with pytest.raises(ValueError, match="is stale"):
        validate_transition_gate(catalog, stale, {"generated"})
