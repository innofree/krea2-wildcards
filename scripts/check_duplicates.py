#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from common import item_prompts, iter_catalog_items, normalized_phrase


Entry = tuple[str, str, str]


def multiset_ratio_upper_bound(
    left_counts: Counter[str],
    right_counts: Counter[str],
    combined_length: int,
) -> float:
    """Return the same character-multiset upper bound as SequenceMatcher.quick_ratio."""

    matches = sum(
        min(count, right_counts.get(character, 0))
        for character, count in left_counts.items()
    )
    return 2 * matches / combined_length


def find_duplicates(
    entries: list[Entry], threshold: float, *, cross_family: bool = False
) -> tuple[list[tuple[str, str]], list[tuple[str, str, float]], int]:
    exact: list[tuple[str, str]] = []
    exact_index: dict[str, list[str]] = defaultdict(list)
    for item_id, prompt, _ in entries:
        for previous in exact_index[prompt]:
            exact.append((previous, item_id))
        exact_index[prompt].append(item_id)

    groups: dict[str, list[Entry]] = defaultdict(list)
    if cross_family:
        groups["*"] = entries
    else:
        for entry in entries:
            groups[entry[2]].append(entry)

    near: list[tuple[str, str, float]] = []
    comparisons = 0
    character_counts = {prompt: Counter(prompt) for _, prompt, _ in entries}
    for group_entries in groups.values():
        for index, (left_id, left, _) in enumerate(group_entries):
            for right_id, right, _ in group_entries[index + 1 :]:
                if left == right:
                    continue
                comparisons += 1
                length_upper_bound = 2 * min(len(left), len(right)) / (len(left) + len(right))
                if length_upper_bound < threshold:
                    continue
                if multiset_ratio_upper_bound(
                    character_counts[left],
                    character_counts[right],
                    len(left) + len(right),
                ) < threshold:
                    continue
                matcher = SequenceMatcher(None, left, right)
                ratio = matcher.ratio()
                if ratio >= threshold:
                    near.append((left_id, right_id, ratio))
    return exact, near, comparisons


def main() -> int:
    parser = argparse.ArgumentParser(description="Find duplicate catalog prompts")
    parser.add_argument("catalog", nargs="?", type=Path, default=Path("catalog"))
    parser.add_argument("--near-threshold", type=float, default=0.94)
    parser.add_argument(
        "--cross-family",
        action="store_true",
        help="compare near duplicates across all families; slower and intended for final audits",
    )
    args = parser.parse_args()

    entries: list[Entry] = []
    for source, item_id, item in iter_catalog_items(args.catalog):
        family = item.get("family") if isinstance(item, dict) else None
        comparison_family = family if isinstance(family, str) and family else source.name
        entries.extend(
            (item_id, normalized_phrase(prompt), comparison_family)
            for prompt in item_prompts(item)
        )

    exact, near, comparisons = find_duplicates(
        entries, args.near_threshold, cross_family=args.cross_family
    )

    for left, right in exact:
        print(f"EXACT: {left} == {right}")
    for left, right, ratio in near:
        print(f"NEAR {ratio:.3f}: {left} ~= {right}")
    if exact or near:
        print(f"FAILED: {len(exact)} exact and {len(near)} near duplicate(s).")
        return 1
    scope = "global" if args.cross_family else "family-scoped"
    print(
        f"OK: {len(entries)} prompt(s), no duplicates at {args.near_threshold:.2f} threshold "
        f"({scope}, {comparisons} near comparison(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
