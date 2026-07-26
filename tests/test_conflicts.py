from __future__ import annotations

from pathlib import Path

from check_conflicts import conflict_pairs, find_conflicts
from common import load_yaml


ROOT = Path(__file__).resolve().parents[1]


def test_conflict_pairs_are_bidirectional_and_detectable() -> None:
    data = load_yaml(ROOT / "catalog/compatibility.yaml")
    pairs = conflict_pairs(data)

    assert ("chibi_proportions", "elongated_fashion_proportions") in pairs
    assert find_conflicts(
        {"elongated_fashion_proportions", "chibi_proportions", "soft_cel"}, pairs
    ) == [("chibi_proportions", "elongated_fashion_proportions")]
    assert find_conflicts({"soft_cel", "pastel"}, pairs) == []
