#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from common import KEY_RE, iter_leaf_lists, load_yaml, normalized_phrase


FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("forbidden subject token", re.compile(r"\b(?:1girl|1boy)\b", re.I)),
    ("quality score tag", re.compile(r"\b(?:score_\d+|absurdres)\b", re.I)),
    ("artist tag", re.compile(r"(?<!\w)@[a-z0-9_]", re.I)),
    ("legacy BREAK delimiter", re.compile(r"\bBREAK\s*,", re.I)),
    ("forbidden name", re.compile(r"\bvelyra\b", re.I)),
    (
        "youth-coded subject",
        re.compile(r"\b(?:child|minor|schoolgirl|schoolboy|underage|young teen)\b", re.I),
    ),
    ("inline wildcard brace", re.compile(r"[{}]")),
    ("NovelAI emphasis bracket", re.compile(r"\[[^\]]+\]")),
)
ABSTRACT_QUALITY_WORDS = frozenset(
    {
        "amazing",
        "beautiful",
        "best",
        "breathtaking",
        "detailed",
        "exceptional",
        "exquisite",
        "gorgeous",
        "masterpiece",
        "perfect",
        "polished",
        "professional",
        "quality",
        "stunning",
    }
)


def repetition_issue(value: str) -> str | None:
    """Return a plan-aligned prose repetition issue, if present."""

    words = re.findall(r"[a-z]+", value.lower())
    for left, right in zip(words, words[1:]):
        if left == right:
            return f"repeats adjacent word {left!r}"
    for word in sorted(ABSTRACT_QUALITY_WORDS):
        if words.count(word) >= 2:
            return f"repeats abstract quality word {word!r}"
    return None


def lint_file(path: Path, max_length: int) -> list[str]:
    errors: list[str] = []
    raw = path.read_text(encoding="utf-8")
    if "\t" in raw:
        errors.append(f"{path}: contains a tab character")
    if "\ufffd" in raw:
        errors.append(f"{path}: contains Unicode replacement character")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw):
        errors.append(f"{path}: contains a control character")

    try:
        data = load_yaml(path)
    except (OSError, yaml.YAMLError) as exc:
        return [*errors, f"{path}: invalid YAML: {exc}"]
    if not isinstance(data, dict) or list(data) != ["krea2"]:
        errors.append(f"{path}: runtime root must contain only the 'krea2' key")
        return errors

    seen: dict[str, str] = {}
    try:
        leaves = list(iter_leaf_lists(data))
    except ValueError as exc:
        return [*errors, f"{path}: {exc}"]

    for path_parts, values in leaves:
        label = "/".join(path_parts)
        for key in path_parts:
            if not KEY_RE.fullmatch(key):
                errors.append(f"{path}: {label}: invalid snake_case key {key!r}")
        if not values:
            errors.append(f"{path}: {label}: empty list")
            continue
        for index, value in enumerate(values):
            entry = f"{path}: {label}[{index}]"
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{entry}: expected a non-empty string")
                continue
            compact = re.sub(r"\s+", " ", value.strip())
            if len(compact) > max_length:
                errors.append(f"{entry}: exceeds {max_length} characters")
            if value.rstrip().endswith(","):
                errors.append(f"{entry}: has a trailing comma")
            for description, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(value):
                    errors.append(f"{entry}: contains {description}")
            if path_parts[-1] != "all":
                repetition = repetition_issue(compact)
                if repetition:
                    errors.append(f"{entry}: {repetition}")

            # The aggregate `all` list deliberately repeats leaf prompts.
            if path_parts[-1] != "all":
                normalized = normalized_phrase(value)
                if normalized in seen:
                    errors.append(
                        f"{entry}: duplicate of {seen[normalized]}"
                    )
                else:
                    seen[normalized] = entry
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint runtime wildcard YAML")
    parser.add_argument("root", nargs="?", type=Path, default=Path("wildcards"))
    parser.add_argument("--max-length", type=int, default=600)
    args = parser.parse_args()

    paths = sorted(args.root.rglob("*.yaml"))
    if not paths:
        print(f"ERROR: no YAML files found under {args.root}")
        return 1
    errors = [error for path in paths for error in lint_file(path, args.max_length)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"FAILED: {len(errors)} issue(s) in {len(paths)} file(s).", file=sys.stderr)
        return 1
    print(f"OK: {len(paths)} runtime YAML file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
