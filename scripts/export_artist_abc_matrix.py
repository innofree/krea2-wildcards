#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from common import load_yaml
from export_artist_native_matrix import ARTIST_ID_RE, FIXED_SCENE
from run_remote_prompt_matrix import validate_job


DEFAULT_REGISTRY = Path("research/artist_registry.yaml")
DEFAULT_OUTPUT = Path("tests/prompt_matrix/artist_abc.jsonl")
DEFAULT_SEEDS = (1001, 2002, 3003)
EXPECTED_ARTISTS = 8
EXPECTED_SEEDS = 3
MODES = ("native_name", "visual_signature", "hybrid")
MODE_CODES = {"native_name": "N", "visual_signature": "S", "hybrid": "H"}
STYLE_CONDITION_MARKER = " Style condition: "
SIGNATURE_MAP_KIND = "artist_abc_signature_map"
NAME_REFERENCE_RE = re.compile(r"\b(?:in the style of|artist reference|artwork by)\b", re.I)


def _normalized_words(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def validate_artist_ids(artist_ids: Iterable[str]) -> tuple[str, ...]:
    values = tuple(artist_ids)
    if len(values) != EXPECTED_ARTISTS:
        raise ValueError(f"exactly {EXPECTED_ARTISTS} explicit artist IDs are required")
    if len(values) != len(set(values)):
        raise ValueError("artist IDs must be distinct")
    if any(not ARTIST_ID_RE.fullmatch(value) for value in values):
        raise ValueError("artist IDs must match artist_###")
    return tuple(sorted(values))


def validate_seeds(seeds: Iterable[int]) -> tuple[int, ...]:
    values = tuple(seeds)
    if len(values) != EXPECTED_SEEDS:
        raise ValueError(f"exactly {EXPECTED_SEEDS} seeds are required")
    if len(values) != len(set(values)):
        raise ValueError("seeds must be distinct")
    if any(
        isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64
        for seed in values
    ):
        raise ValueError("seeds must be 64-bit unsigned integers")
    return tuple(sorted(values))


def _clean_display_name(artist_id: str, record: Any) -> str:
    if not isinstance(record, dict):
        raise ValueError(f"registry artist must be a mapping: {artist_id}")
    name = record.get("display_name")
    if (
        not isinstance(name, str)
        or not name.strip()
        or name != name.strip()
        or "\n" in name
        or "\r" in name
    ):
        raise ValueError(f"registry display_name must be a clean line: {artist_id}")
    return name


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    document = load_yaml(path)
    artists = document.get("artists") if isinstance(document, dict) else None
    if not isinstance(artists, dict):
        raise ValueError("artist registry must contain an artists mapping")
    validated: dict[str, dict[str, Any]] = {}
    for artist_id, record in artists.items():
        if not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(f"invalid registry artist ID: {artist_id!r}")
        _clean_display_name(artist_id, record)
        validated[artist_id] = record
    return validated


def _identity_phrases(record: dict[str, Any]) -> set[str]:
    values: list[str] = [record["display_name"]]
    aliases = record.get("aliases", [])
    if isinstance(aliases, list):
        values.extend(value for value in aliases if isinstance(value, str))
    source_tags = record.get("source_tags", {})
    if isinstance(source_tags, dict):
        values.extend(value for value in source_tags.values() if isinstance(value, str))
    return {phrase for value in values if (phrase := _normalized_words(value))}


def _clean_signature(
    artist_id: str,
    value: Any,
    forbidden_identities: set[str],
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\x00" in value
        or len(value) > 2000
    ):
        raise ValueError(f"signature_prompt must be clean non-empty text: {artist_id}")
    if NAME_REFERENCE_RE.search(value):
        raise ValueError(f"signature_prompt must be name-free: {artist_id}")
    normalized = f" {_normalized_words(value)} "
    for identity in forbidden_identities:
        if f" {identity} " in normalized:
            raise ValueError(f"signature_prompt contains artist identity: {artist_id}")

    # Reuse the generic resolved-matrix validator for wildcard, endpoint, account,
    # path, and NUL checks before any prompt is emitted.
    validate_job(
        {
            "schema_version": 1,
            "test_id": "SignatureValidation",
            "style_id": artist_id,
            "label": artist_id,
            "mode": "visual_signature",
            "seed": 0,
            "prompt": value,
            "factors": {},
        },
        1,
    )
    return value


def load_signature_map(
    path: Path,
    registry: dict[str, dict[str, Any]],
) -> dict[str, str]:
    document = load_yaml(path)
    if not isinstance(document, dict):
        raise ValueError("signature map must be a mapping")
    if set(document) != {"schema_version", "kind", "artists"}:
        raise ValueError("signature map must contain only schema_version, kind, and artists")
    if document.get("schema_version") != 1:
        raise ValueError("signature map schema_version must be 1")
    if document.get("kind") != SIGNATURE_MAP_KIND:
        raise ValueError(f"signature map kind must be {SIGNATURE_MAP_KIND}")
    artists = document.get("artists")
    if not isinstance(artists, dict):
        raise ValueError("signature map artists must be a mapping")

    forbidden_identities = {
        identity
        for registry_record in registry.values()
        for identity in _identity_phrases(registry_record)
    }
    signatures: dict[str, str] = {}
    for artist_id, entry in artists.items():
        if not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id):
            raise ValueError(f"invalid signature-map artist ID: {artist_id!r}")
        if artist_id not in registry:
            raise ValueError(f"signature-map artist is absent from registry: {artist_id}")
        if not isinstance(entry, dict) or set(entry) != {"signature_prompt"}:
            raise ValueError(
                f"signature-map entry must contain only signature_prompt: {artist_id}"
            )
        signatures[artist_id] = _clean_signature(
            artist_id,
            entry.get("signature_prompt"),
            forbidden_identities,
        )
    return signatures


def _test_id(artist_id: str, mode: str, seed: int) -> str:
    artist_number = artist_id.removeprefix("artist_")
    return f"ABC{artist_number}{MODE_CODES[mode]}{seed}"


def _style_condition(mode: str, display_name: str, signature: str) -> str:
    native_clause = f"Native-name reference: {display_name}."
    signature_clause = f"Name-free visual signature: {signature}"
    if mode == "native_name":
        return native_clause
    if mode == "visual_signature":
        return signature_clause
    if mode == "hybrid":
        return f"{native_clause} {signature_clause}"
    raise ValueError(f"unsupported comparison mode: {mode}")


def validate_matrix(
    rows: list[dict[str, Any]],
    artist_ids: tuple[str, ...],
    seeds: tuple[int, ...],
) -> None:
    expected = {
        (artist_id, mode, seed)
        for artist_id in artist_ids
        for mode in MODES
        for seed in seeds
    }
    actual = {(row["style_id"], row["mode"], row["seed"]) for row in rows}
    if actual != expected or len(rows) != EXPECTED_ARTISTS * len(MODES) * EXPECTED_SEEDS:
        raise ValueError("artist A/B/C matrix does not have exact 8x3x3 coverage")
    if len({row["test_id"] for row in rows}) != len(rows):
        raise ValueError("artist A/B/C matrix contains duplicate deterministic IDs")
    if Counter(row["mode"] for row in rows) != Counter({mode: 24 for mode in MODES}):
        raise ValueError("artist A/B/C matrix mode coverage is invalid")


def artist_abc_rows(
    registry_path: Path,
    signature_map_path: Path,
    artist_ids: Iterable[str],
    seeds: Iterable[int] = DEFAULT_SEEDS,
) -> list[dict[str, Any]]:
    selected = validate_artist_ids(artist_ids)
    seed_values = validate_seeds(seeds)
    registry = load_registry(registry_path)
    missing_registry = sorted(set(selected) - set(registry))
    if missing_registry:
        raise ValueError(f"selected artist is absent from registry: {missing_registry}")
    signatures = load_signature_map(signature_map_path, registry)
    missing_signatures = sorted(set(selected) - set(signatures))
    if missing_signatures:
        raise ValueError(f"selected artist lacks a name-free signature: {missing_signatures}")

    rows: list[dict[str, Any]] = []
    for artist_id in selected:
        display_name = _clean_display_name(artist_id, registry[artist_id])
        signature = signatures[artist_id]
        for mode in MODES:
            condition = _style_condition(mode, display_name, signature)
            for seed in seed_values:
                row = {
                    "schema_version": 1,
                    "test_id": _test_id(artist_id, mode, seed),
                    "style_id": artist_id,
                    "label": artist_id,
                    "mode": mode,
                    "seed": seed,
                    "prompt": f"{FIXED_SCENE}{STYLE_CONDITION_MARKER}{condition}",
                    "factors": {"artist": artist_id, "comparison_mode": mode},
                }
                validate_job(row, len(rows) + 1)
                rows.append(row)
    validate_matrix(rows, selected, seed_values)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export an exact deterministic 8-artist native/signature/hybrid A/B/C matrix"
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--signature-map", type=Path, required=True)
    parser.add_argument("--artist", action="append", required=True)
    parser.add_argument("--seed", action="append", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        rows = artist_abc_rows(
            args.registry,
            args.signature_map,
            args.artist,
            args.seed or DEFAULT_SEEDS,
        )
        write_jsonl(args.output, rows)
        print("Wrote 72 resolved prompts: 8 artists x 3 modes x 3 seeds.")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
