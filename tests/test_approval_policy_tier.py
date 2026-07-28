from __future__ import annotations

from pathlib import Path

import pytest

from check_completion_criteria import _approval_policy, _approved_and_valid
from common import load_yaml, required_approval_seeds


ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "catalog" / "evaluation.yaml"


def validation(**overrides):
    base = {
        "status": "approved",
        "tested_seeds": 3,
        "prompt_adherence": 4,
        "style_fidelity": 4,
        "stability": 4,
        "compatibility": 4,
        "critical_failures": 0,
    }
    base.update(overrides)
    return base


def item(family: str, **overrides):
    return {"family": family, "validation": validation(**overrides)}


def test_policy_is_read_from_the_catalog_not_hardcoded() -> None:
    """The completion gate once hardcoded a 5-seed floor, which silently ignored
    the family tier and undercounted every promoted atomic axis item."""
    policy = _approval_policy(ROOT)
    expected = load_yaml(EVALUATION)["approval_policy"]
    assert policy == expected
    assert policy["minimum_approval_seeds"] == 3
    assert policy["complete_scene_approval_seeds"] == 5


def test_atomic_axis_items_clear_at_three_seeds() -> None:
    policy = _approval_policy(ROOT)
    assert required_approval_seeds(policy, item("lighting")) == 3
    assert _approved_and_valid(item("lighting", tested_seeds=3), policy)
    assert not _approved_and_valid(item("lighting", tested_seeds=2), policy)


def test_complete_scene_items_still_need_five_seeds() -> None:
    policy = _approval_policy(ROOT)
    for family in ("style_pack", "artist_signature", "preset"):
        assert required_approval_seeds(policy, item(family)) == 5, family
        assert not _approved_and_valid(item(family, tested_seeds=3), policy), family
        assert not _approved_and_valid(item(family, tested_seeds=4), policy), family
        assert _approved_and_valid(item(family, tested_seeds=5), policy), family


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_adherence", 3),
        ("style_fidelity", 2),
        ("stability", 2),
        ("compatibility", 2),
        ("critical_failures", 1),
    ],
)
def test_metric_minimums_still_gate_approval(field: str, value: int) -> None:
    policy = _approval_policy(ROOT)
    assert not _approved_and_valid(item("lighting", **{field: value}), policy)


def test_non_approved_status_is_never_valid() -> None:
    policy = _approval_policy(ROOT)
    for status in ("generated", "testing", "rejected", "limited"):
        assert not _approved_and_valid(item("lighting", status=status), policy)
