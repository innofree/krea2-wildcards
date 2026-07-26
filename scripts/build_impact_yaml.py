#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from common import dump_yaml, iter_leaf_lists, load_yaml


DEFAULT_SOURCE = Path("build/preview-wildcards")
DEFAULT_OUTPUT = Path("build/impact-wildcards/krea2_complete_pack.yaml")


def _source_files(sources: Path | Iterable[Path]) -> list[Path]:
    candidates = [sources] if isinstance(sources, Path) else list(sources)
    files: set[Path] = set()
    for candidate in candidates:
        if candidate.is_dir():
            files.update(path for path in candidate.rglob("*.yaml") if path.is_file())
        elif candidate.is_file():
            files.add(candidate)
        else:
            raise ValueError(f"canonical runtime source not found: {candidate}")
    if not files:
        raise ValueError("canonical runtime source has no YAML files")
    return sorted(files)


def impact_compatible_document(
    sources: Path | Iterable[Path],
) -> dict[str, dict[str, list[str]]]:
    """Flatten one file or a whole canonical runtime tree into one Impact bundle."""

    flattened: dict[str, list[str]] = {}
    for source in _source_files(sources):
        data = load_yaml(source)
        if not isinstance(data, dict) or list(data) != ["krea2"]:
            raise ValueError(f"{source}: canonical runtime must contain only the krea2 root")
        for parts, values in iter_leaf_lists(data):
            if not parts or parts[0] != "krea2" or len(parts) < 2:
                raise ValueError(f"invalid canonical runtime path: {'/'.join(parts)}")
            relative_path = "/".join(parts[1:])
            if relative_path in flattened:
                raise ValueError(f"duplicate Impact runtime path: {relative_path}")
            if not values or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(f"invalid values at {'/'.join(parts)}")
            flattened[relative_path] = values

    if not flattened:
        raise ValueError("canonical runtime has no wildcard leaves")
    return {"krea2": flattened}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flatten canonical nested YAML for the deployed Impact Pack loader"
    )
    parser.add_argument(
        "--source",
        action="append",
        type=Path,
        help="canonical runtime YAML file or directory; may be repeated",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        document = impact_compatible_document(args.source or DEFAULT_SOURCE)
        dump_yaml(document, args.output)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Built {len(document['krea2'])} Impact-compatible wildcard path(s) into {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
