#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from common import load_yaml


DEFAULT_REGISTRY = Path("research/artist_registry.yaml")
DEFAULT_OUTPUT = Path("tests/prompt_matrix/artist_native_name.jsonl")
DEFAULT_SEEDS = (1001, 2002, 3003)
EXPECTED_ARTISTS = 300
ARTIST_ID_RE = re.compile(r"^artist_[0-9]{3}$")

FIXED_SCENE = (
    "Depict one adult woman in a balanced standing pose, wearing a plain fitted long-sleeve "
    "top and straight trousers on an uncluttered warm-grey studio cyclorama. Use an eye-level "
    "full-length camera and broad neutral diffused lighting, with her head, both hands, and both "
    "feet fully visible. Preserve natural anatomy and a clean image without text, logos, or "
    "watermarks."
)


def validate_seeds(seeds: Iterable[int]) -> tuple[int, ...]:
    values = tuple(seeds)
    if not values:
        raise ValueError("at least one seed is required")
    if len(values) != len(set(values)):
        raise ValueError("seeds must be distinct")
    if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in values):
        raise ValueError("seeds must be non-negative integers")
    return values


def artist_rows(
    registry_path: Path,
    seeds: Iterable[int] = DEFAULT_SEEDS,
    *,
    expected_artists: int = EXPECTED_ARTISTS,
) -> list[dict[str, Any]]:
    seed_values = validate_seeds(seeds)
    document = load_yaml(registry_path)
    artists = document.get("artists") if isinstance(document, dict) else None
    if not isinstance(artists, dict):
        raise ValueError("artist registry must contain an artists mapping")
    if len(artists) != expected_artists:
        raise ValueError(
            f"artist registry must contain exactly {expected_artists} artists; found {len(artists)}"
        )

    rows: list[dict[str, Any]] = []
    for artist_id in sorted(artists):
        artist = artists[artist_id]
        if not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(f"invalid artist internal id: {artist_id!r}")
        if not isinstance(artist, dict):
            raise ValueError(f"artist record must be a mapping: {artist_id}")
        display_name = artist.get("display_name")
        if (
            not isinstance(display_name, str)
            or not display_name.strip()
            or display_name != display_name.strip()
            or "\n" in display_name
            or "\r" in display_name
        ):
            raise ValueError(f"artist display_name must be a clean non-empty line: {artist_id}")

        prompt = (
            f"Create an original illustration using {display_name} as the only artist-style "
            f"reference. {FIXED_SCENE}"
        )
        for seed in seed_values:
            rows.append(
                {
                    "schema_version": 1,
                    "test_id": f"AN{len(rows) + 1:06d}",
                    "style_id": artist_id,
                    "label": display_name,
                    "mode": "native_name",
                    "seed": seed,
                    "prompt": prompt,
                }
            )
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the deterministic native-name artist benchmark matrix"
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", action="append", type=int, default=None)
    args = parser.parse_args()

    try:
        rows = artist_rows(args.registry, args.seed or DEFAULT_SEEDS)
        write_jsonl(args.output, rows)
        seeds = validate_seeds(args.seed or DEFAULT_SEEDS)
        print(
            f"Wrote {len(rows)} resolved prompt(s): {EXPECTED_ARTISTS} artists x "
            f"{len(seeds)} seed(s)."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
