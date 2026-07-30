#!/usr/bin/env python3
"""Turn a completed segmented sheet review into the review.yaml apply_visual_review.py expects.

The sheet-by-sheet workflow records one pass/hold verdict and a reasoning note per
item across many review_parts/sNNN.json files (schema: {alias: [verdict, note]}).
apply_visual_review.py instead wants a single review.yaml mapping every catalog
style_id to a full METRICS score plus critical_failure and notes. This script does
that translation, and only that -- it does not re-judge anything.

"pass" gets scores that clear every catalog/evaluation.yaml threshold, so
summarize_results.py's own quality_passed check (not this script) is what turns it
into an "approved" recommendation. "hold" gets style_fidelity dropped one point
below the policy's minimum_style_fidelity, with critical_failure left false --
that fails quality_passed without asserting a critical failure that was not
observed, and produces "rejected" through the same policy-driven derivation.
Rejected here means "not approved on this evidence", not "permanently excluded":
a later evaluation-id can move any of these items forward once the outstanding
question (an unreadable sub-attribute, or a confirmed defect) is resolved.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import dump_yaml, load_yaml
from summarize_results import METRICS

VALID_VERDICTS = {"pass", "hold"}


def load_alias_to_style(manifest: dict[str, Any]) -> dict[str, str]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest has no cases")
    mapping: dict[str, str] = {}
    for case in cases:
        alias = case.get("alias")
        style_id = case.get("style_id")
        if not isinstance(alias, str) or not isinstance(style_id, str):
            raise ValueError("manifest case is missing alias or style_id")
        mapping[alias] = style_id
    return mapping


def load_verdicts(review_parts: Path) -> dict[str, tuple[str, str]]:
    verdicts: dict[str, tuple[str, str]] = {}
    paths = sorted(review_parts.glob("s*.json"))
    if not paths:
        raise ValueError(f"no review_parts found under {review_parts}")
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"{path} must contain a JSON object")
        for alias, entry in document.items():
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or entry[0] not in VALID_VERDICTS
                or not isinstance(entry[1], str)
                or not entry[1].strip()
            ):
                raise ValueError(f"{path}: {alias} has a malformed verdict entry")
            if alias in verdicts:
                raise ValueError(f"duplicate alias across review_parts: {alias}")
            verdicts[alias] = (entry[0], entry[1].strip())
    return verdicts


def build_styles(
    alias_to_style: dict[str, str],
    verdicts: dict[str, tuple[str, str]],
    *,
    minimum_style_fidelity: int,
) -> dict[str, dict[str, Any]]:
    missing_verdict = sorted(set(alias_to_style) - set(verdicts))
    if missing_verdict:
        raise ValueError(
            f"{len(missing_verdict)} manifest case(s) have no recorded verdict, "
            f"starting with {missing_verdict[0]}"
        )
    extra_verdict = sorted(set(verdicts) - set(alias_to_style))
    if extra_verdict:
        raise ValueError(
            f"{len(extra_verdict)} verdict(s) reference aliases absent from the "
            f"manifest, starting with {extra_verdict[0]}"
        )

    styles: dict[str, dict[str, Any]] = {}
    for alias, style_id in alias_to_style.items():
        verdict, note = verdicts[alias]
        metrics = {metric: 4 for metric in METRICS}
        if verdict == "hold":
            metrics["style_fidelity"] = minimum_style_fidelity - 1
        if style_id in styles:
            raise ValueError(f"duplicate style_id across cases: {style_id}")
        styles[style_id] = {
            "metrics": metrics,
            "critical_failure": False,
            "notes": f"[{verdict}] {alias}: {note}",
        }
    return styles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="review/manifest.json")
    parser.add_argument("review_parts", type=Path, help="review_parts/ directory")
    parser.add_argument("--policy", type=Path, default=Path("catalog/evaluation.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest = load_yaml(args.manifest)
        if not isinstance(manifest, dict):
            raise ValueError(f"{args.manifest} must contain a JSON object")
        alias_to_style = load_alias_to_style(manifest)
        verdicts = load_verdicts(args.review_parts)
        policy_document = load_yaml(args.policy)
        policy = (
            policy_document.get("approval_policy")
            if isinstance(policy_document, dict)
            else None
        )
        if not isinstance(policy, dict) or "minimum_style_fidelity" not in policy:
            raise ValueError(f"{args.policy} has no approval_policy.minimum_style_fidelity")
        minimum_style_fidelity = int(policy["minimum_style_fidelity"])
        styles = build_styles(
            alias_to_style, verdicts, minimum_style_fidelity=minimum_style_fidelity
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    document = {
        "schema_version": 1,
        "review_method": "partitioned_contact_sheet_visual_review",
        "styles": styles,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml(document, args.output)
    pass_count = sum(1 for v in verdicts.values() if v[0] == "pass")
    hold_count = sum(1 for v in verdicts.values() if v[0] == "hold")
    print(f"wrote {args.output}: {len(styles)} styles ({pass_count} pass, {hold_count} hold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
