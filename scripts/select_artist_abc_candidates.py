#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Sequence

import export_artist_abc_matrix as abc_export
from apply_artist_native_observations import (
    AXIS_MAPPING,
    STABLE_SOURCE_STATUS,
    STABLE_VISUAL_STATUS,
    _load_yaml_mapping,
    atomic_dump_yaml,
    forbidden_identity_names,
    load_merged_observations,
    redact_error,
    validate_registry,
)
from merge_artist_native_observations import AXES


DEFAULT_OBSERVATIONS = Path("tests/reports/artist_native_screen_v0_7/observations.yaml")
DEFAULT_REGISTRY = Path("research/artist_registry.yaml")
DEFAULT_COUNT = 8
EMPHASIS_RE = re.compile(r"[{}\[\]]|\([^()\r\n]*:\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\)")


def load_selection_inputs(
    observations_path: Path,
    registry_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    registry = _load_yaml_mapping(registry_path, source="artist registry")
    raw_artists = registry.get("artists")
    if not isinstance(raw_artists, dict) or not raw_artists:
        raise ValueError("registry artists must be a non-empty mapping")
    artist_ids = validate_registry(registry, expected_artists=len(raw_artists))
    observations = load_merged_observations(
        observations_path,
        registry_artist_ids=artist_ids,
        forbidden_names=forbidden_identity_names(registry),
    )
    return registry, observations


def _registry_observation_matches(
    record: dict[str, Any], observation: dict[str, Any]
) -> bool:
    signature = record["visual_signature"]
    if (
        signature["status"] != STABLE_VISUAL_STATUS
        or record["source_status"] != STABLE_SOURCE_STATUS
    ):
        return False
    registry_axes = signature["axes"]
    return all(
        registry_axes[registry_axis] == observation["axes"][observation_axis]
        for observation_axis, registry_axis in AXIS_MAPPING.items()
    )


def eligible_observations(
    registry: dict[str, Any],
    observations: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    artists = registry["artists"]
    if set(artists) != set(observations):
        raise ValueError("observations and registry must have exact artist coverage")
    eligible: dict[str, dict[str, Any]] = {}
    for artist_id in sorted(observations):
        observation = observations[artist_id]
        if (
            observation["stable_across_seeds"] is True
            and observation["confidence"] >= 3
            and _registry_observation_matches(artists[artist_id], observation)
        ):
            eligible[artist_id] = observation
    return eligible


def normalized_axis_features(observation: dict[str, Any]) -> frozenset[str]:
    axes = observation.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(AXES):
        raise ValueError("candidate observation must contain exactly eight axes")
    features: set[str] = set()
    for axis in AXES:
        normalized = abc_export._normalized_words(axes[axis])
        if not normalized:
            raise ValueError(f"candidate {axis} observation has no normalized words")
        features.add(f"{axis}:phrase:{normalized}")
        features.update(f"{axis}:token:{token}" for token in normalized.split())
    return frozenset(features)


def select_diverse_candidates(
    eligible: dict[str, dict[str, Any]], count: int
) -> tuple[str, ...]:
    if type(count) is not int or count < 1:
        raise ValueError("--count must be a positive integer")
    if len(eligible) < count:
        raise ValueError(
            f"insufficient eligible stable observations; requested={count}, "
            f"eligible={len(eligible)}"
        )
    features = {
        artist_id: normalized_axis_features(observation)
        for artist_id, observation in eligible.items()
    }
    remaining = set(eligible)
    seen: set[str] = set()
    selected: list[str] = []
    while len(selected) < count:
        artist_id = min(
            remaining,
            key=lambda candidate: (
                -len(features[candidate] - seen),
                -eligible[candidate]["confidence"],
                candidate,
            ),
        )
        selected.append(artist_id)
        seen.update(features[artist_id])
        remaining.remove(artist_id)
    return tuple(selected)


def _forbidden_export_identities(registry: dict[str, Any]) -> set[str]:
    return {
        identity
        for record in registry["artists"].values()
        for identity in abc_export._identity_phrases(record)
    }


def compose_signature_prompt(
    artist_id: str,
    observation: dict[str, Any],
    forbidden_identities: set[str],
) -> str:
    axes = observation.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(AXES):
        raise ValueError(f"{artist_id}: signature requires exactly eight axes")
    fragments: list[str] = []
    for axis in AXES:
        value = axes[axis]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{artist_id}: {axis} must be non-empty text")
        fragments.append(value.rstrip(" .;:"))
    prompt = f"Use {'; '.join(fragments)}."
    if EMPHASIS_RE.search(prompt):
        raise ValueError(f"{artist_id}: signature_prompt contains emphasis syntax")
    return abc_export._clean_signature(artist_id, prompt, forbidden_identities)


def build_signature_map(
    registry: dict[str, Any],
    observations: dict[str, dict[str, Any]],
    *,
    count: int = DEFAULT_COUNT,
) -> dict[str, Any]:
    eligible = eligible_observations(registry, observations)
    selected = select_diverse_candidates(eligible, count)
    forbidden_identities = _forbidden_export_identities(registry)
    return {
        "schema_version": 1,
        "kind": abc_export.SIGNATURE_MAP_KIND,
        "artists": {
            artist_id: {
                "signature_prompt": compose_signature_prompt(
                    artist_id,
                    observations[artist_id],
                    forbidden_identities,
                )
            }
            for artist_id in sorted(selected)
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Select diverse stable native observations for the deterministic artist A/B/C matrix"
        )
    )
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.output.resolve() in {
            args.observations.resolve(),
            args.registry.resolve(),
        }:
            raise ValueError("output must not replace an input file")
        if args.output.exists() and not args.overwrite:
            raise ValueError("output exists; pass --overwrite to replace it")
        registry, observations = load_selection_inputs(
            args.observations,
            args.registry,
        )
        document = build_signature_map(
            registry,
            observations,
            count=args.count,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_dump_yaml(document, args.output)
        print(
            f"Selected {len(document['artists'])} diverse stable candidate(s) into "
            f"{args.output.name}."
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {redact_error(str(exc))}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
