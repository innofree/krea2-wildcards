#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Sequence

import yaml

from common import dump_yaml, load_yaml
from export_artist_native_matrix import ARTIST_ID_RE


DEFAULT_EXPECTED_ARTISTS = 300
AXES = (
    "linework",
    "face",
    "eyes",
    "body",
    "palette",
    "light_shading",
    "framing",
    "ornament",
)
PART_FIELDS = {"schema_version", "artists"}
ENTRY_FIELDS = {"axes", "confidence", "stable_across_seeds", "notes"}
MAX_AXIS_TEXT = 240
MAX_NOTES_TEXT = 500

URL_RE = re.compile(r"(?:https?|ssh)://", re.IGNORECASE)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
HOME_PATH_RE = re.compile(r"(?:/home/|/Users/)[A-Za-z0-9_.-]+")
WINDOWS_HOME_RE = re.compile(
    r"[A-Za-z]:\\(?:Users|Documents and Settings)\\", re.IGNORECASE
)
ACCOUNT_AT_HOST_RE = re.compile(
    r"(?<![<\w])[a-z_][a-z0-9_.-]*@[a-z0-9][a-z0-9.-]+",
    re.IGNORECASE,
)
IDENTITY_REFERENCE_RE = re.compile(
    r"\b(?:canonical name|display name|artist-style reference|in the style of|inspired by|prompt)\b",
    re.IGNORECASE,
)
ARTIST_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9_])artist_[0-9]{3}(?![A-Za-z0-9_])")
FORBIDDEN_MANIFEST_KEYS = {
    "account",
    "account_path",
    "api_url",
    "canonical_name",
    "display_name",
    "endpoint",
    "label",
    "prompt",
    "resolved_prompt",
    "ssh_target",
}


def _validate_expected_count(artist_ids: set[str], expected_artists: int) -> None:
    if expected_artists < 1:
        raise ValueError("--expected-artists must be at least 1")
    if len(artist_ids) != expected_artists:
        raise ValueError(
            f"coverage source must contain exactly {expected_artists} artists; "
            f"found {len(artist_ids)}"
        )


def _clean_forbidden_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).casefold()
    return value or None


def load_matrix_coverage(
    path: Path, *, expected_artists: int
) -> tuple[set[str], tuple[str, ...]]:
    artist_ids: set[str] = set()
    forbidden_names: set[str] = set()
    row_count = 0
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row_count += 1
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"matrix line {line_number}: invalid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"matrix line {line_number}: row must be a JSON object")
        artist_id = raw.get("style_id")
        if not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(f"matrix line {line_number}: invalid native artist id")
        if raw.get("mode") != "native_name":
            raise ValueError(f"matrix line {line_number}: mode must be native_name")
        artist_ids.add(artist_id)
        forbidden_name = _clean_forbidden_name(raw.get("label"))
        if forbidden_name is not None:
            forbidden_names.add(forbidden_name)
    if row_count == 0:
        raise ValueError("matrix contains no rows")
    _validate_expected_count(artist_ids, expected_artists)
    return artist_ids, tuple(sorted(forbidden_names))


def _mapping_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key).casefold() for key in value)
        for child in value.values():
            keys.update(_mapping_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_mapping_keys(child))
    return keys


def load_manifest_coverage(path: Path, *, expected_artists: int) -> set[str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("native review manifest contains invalid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("native review manifest must be a JSON object")
    if document.get("kind") != "artist_native_name_contact_sheet_review":
        raise ValueError("manifest is not an artist native contact-sheet review")
    forbidden = sorted(_mapping_keys(document) & FORBIDDEN_MANIFEST_KEYS)
    if forbidden:
        raise ValueError(
            "native review manifest contains forbidden identity or connection fields"
        )
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("native review manifest items must be a non-empty list")
    artist_ids: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest item {index}: expected an object")
        artist_id = item.get("artist_id")
        if not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(f"manifest item {index}: invalid native artist id")
        artist_ids.add(artist_id)
    artist_count = document.get("artist_count")
    if type(artist_count) is not int or artist_count != len(artist_ids):
        raise ValueError("native review manifest artist_count does not match its items")
    _validate_expected_count(artist_ids, expected_artists)
    return artist_ids


def _contains_ipv4(value: str) -> bool:
    for match in IPV4_RE.finditer(value):
        try:
            ipaddress.ip_address(match.group())
        except ValueError:
            continue
        return True
    return False


def _contains_forbidden_name(value: str, forbidden_names: tuple[str, ...]) -> bool:
    normalized = " ".join(value.split()).casefold()
    for name in forbidden_names:
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized):
            return True
    return False


def _clean_observation_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    forbidden_names: tuple[str, ...],
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\n" in value
        or "\r" in value
        or "\x00" in value
    ):
        raise ValueError(f"{field} must be clean, non-empty single-line text")
    if len(value) > max_length:
        raise ValueError(f"{field} exceeds the {max_length}-character limit")
    if (
        URL_RE.search(value)
        or _contains_ipv4(value)
        or HOME_PATH_RE.search(value)
        or WINDOWS_HOME_RE.search(value)
        or ACCOUNT_AT_HOST_RE.search(value)
    ):
        raise ValueError(f"{field} contains forbidden connection or account data")
    if IDENTITY_REFERENCE_RE.search(value) or ARTIST_REFERENCE_RE.search(value):
        raise ValueError(f"{field} contains a forbidden identity or prompt reference")
    if _contains_forbidden_name(value, forbidden_names):
        raise ValueError(f"{field} contains a forbidden canonical identity")
    return value


def load_observation_part(
    path: Path,
    *,
    part_number: int,
    forbidden_names: tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    try:
        document = load_yaml(path)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"observation part {part_number} contains invalid YAML"
        ) from exc
    if not isinstance(document, dict):
        raise ValueError(f"observation part {part_number} must be a mapping")
    unknown = sorted(str(key) for key in set(document) - PART_FIELDS)
    if unknown:
        raise ValueError(f"observation part {part_number} has unknown top-level fields")
    if document.get("schema_version", 1) != 1:
        raise ValueError(f"observation part {part_number} schema_version must be 1")
    artists = document.get("artists")
    if not isinstance(artists, dict) or not artists:
        raise ValueError(
            f"observation part {part_number} artists must be a non-empty mapping"
        )

    validated: dict[str, dict[str, Any]] = {}
    for artist_id, raw in artists.items():
        if not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(
                f"observation part {part_number} contains an invalid artist id"
            )
        if not isinstance(raw, dict) or set(raw) != ENTRY_FIELDS:
            raise ValueError(
                f"{artist_id} must contain exactly axes, confidence, stable_across_seeds, notes"
            )
        raw_axes = raw["axes"]
        if not isinstance(raw_axes, dict) or set(raw_axes) != set(AXES):
            raise ValueError(
                f"{artist_id}.axes must contain exactly the eight observation axes"
            )
        axes = {
            axis: _clean_observation_text(
                raw_axes[axis],
                field=f"{artist_id}.axes.{axis}",
                max_length=MAX_AXIS_TEXT,
                forbidden_names=forbidden_names,
            )
            for axis in AXES
        }
        confidence = raw["confidence"]
        if type(confidence) is not int or not 1 <= confidence <= 5:
            raise ValueError(f"{artist_id}.confidence must be an integer from 1 to 5")
        stable = raw["stable_across_seeds"]
        if type(stable) is not bool:
            raise ValueError(f"{artist_id}.stable_across_seeds must be a boolean")
        notes = _clean_observation_text(
            raw["notes"],
            field=f"{artist_id}.notes",
            max_length=MAX_NOTES_TEXT,
            forbidden_names=forbidden_names,
        )
        validated[artist_id] = {
            "axes": axes,
            "confidence": confidence,
            "stable_across_seeds": stable,
            "notes": notes,
        }
    return validated


def merge_observation_parts(
    paths: list[Path],
    expected_artist_ids: set[str],
    *,
    forbidden_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one observation part is required")
    merged: dict[str, dict[str, Any]] = {}
    for part_number, path in enumerate(paths, start=1):
        observations = load_observation_part(
            path,
            part_number=part_number,
            forbidden_names=forbidden_names,
        )
        duplicate = sorted(set(merged) & set(observations))
        if duplicate:
            raise ValueError(f"duplicate artist observations: {duplicate}")
        merged.update(observations)

    missing = sorted(expected_artist_ids - set(merged))
    extra = sorted(set(merged) - expected_artist_ids)
    if missing or extra:
        raise ValueError(
            f"artist observation coverage mismatch; missing={missing}, extra={extra}"
        )
    return {
        "schema_version": 1,
        "kind": "artist_native_observations",
        "artist_count": len(merged),
        "axis_order": list(AXES),
        "artists": {artist_id: merged[artist_id] for artist_id in sorted(merged)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge partitioned, name-free artist native contact-sheet observations"
    )
    parser.add_argument("parts", nargs="+", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--matrix", type=Path, help="native-name matrix JSONL coverage source"
    )
    source.add_argument(
        "--manifest", type=Path, help="redacted native review manifest coverage source"
    )
    parser.add_argument(
        "--expected-artists", type=int, default=DEFAULT_EXPECTED_ARTISTS
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        if args.matrix is not None:
            expected, forbidden_names = load_matrix_coverage(
                args.matrix,
                expected_artists=args.expected_artists,
            )
        else:
            expected = load_manifest_coverage(
                args.manifest,
                expected_artists=args.expected_artists,
            )
            forbidden_names = ()
        document = merge_observation_parts(
            args.parts,
            expected,
            forbidden_names=forbidden_names,
        )
        dump_yaml(document, args.output)
        print(
            f"Merged {document['artist_count']} artist observation(s) into {args.output.name}."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        message = str(exc)
        message = URL_RE.sub("<redacted_endpoint>", message)
        message = IPV4_RE.sub("<redacted_address>", message)
        message = HOME_PATH_RE.sub("<redacted_account_path>", message)
        message = WINDOWS_HOME_RE.sub("<redacted_account_path>", message)
        message = ACCOUNT_AT_HOST_RE.sub("<redacted_account>", message)
        print(f"ERROR: {message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
