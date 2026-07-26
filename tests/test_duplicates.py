from __future__ import annotations

from collections import Counter

from check_duplicates import find_duplicates, multiset_ratio_upper_bound


def test_exact_duplicates_are_global_across_families() -> None:
    entries = [
        ("one", "same prompt", "family_a"),
        ("two", "same prompt", "family_b"),
    ]
    exact, near, _ = find_duplicates(entries, 0.94)
    assert exact == [("one", "two")]
    assert near == []


def test_near_duplicates_are_checked_within_family() -> None:
    entries = [
        ("one", "precise red garment with a long clean silhouette", "fashion"),
        ("two", "precise red garment with a long clear silhouette", "fashion"),
    ]
    _, near, comparisons = find_duplicates(entries, 0.85)
    assert comparisons == 1
    assert near and near[0][:2] == ("one", "two")


def test_cross_family_mode_expands_candidate_scope() -> None:
    entries = [
        ("one", "soft pale light around a calm adult subject", "first"),
        ("two", "soft pale light around one calm adult subject", "second"),
    ]
    assert find_duplicates(entries, 0.85)[2] == 0
    assert find_duplicates(entries, 0.85, cross_family=True)[2] == 1


def test_precomputed_multiset_bound_matches_sequence_matcher_quick_bound() -> None:
    left = "controlled tapered linework with quiet mineral color"
    right = "quiet mineral color with controlled tapered contours"
    bound = multiset_ratio_upper_bound(
        Counter(left), Counter(right), len(left) + len(right)
    )

    from difflib import SequenceMatcher

    assert bound == SequenceMatcher(None, left, right).quick_ratio()
