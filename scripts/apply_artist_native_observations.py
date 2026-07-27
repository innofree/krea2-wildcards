#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Sequence

import yaml

from common import dump_yaml, load_yaml
from export_artist_native_matrix import ARTIST_ID_RE
from merge_artist_native_observations import (
    ACCOUNT_AT_HOST_RE,
    AXES as OBSERVATION_AXES,
    ENTRY_FIELDS,
    HOME_PATH_RE,
    IPV4_RE,
    URL_RE,
    WINDOWS_HOME_RE,
    _clean_observation_text,
)


DEFAULT_EXPECTED_ARTISTS = 300
REGISTRY_AXES = (
    "linework",
    "face_design",
    "eye_design",
    "body_design",
    "coloring",
    "shading",
    "composition",
    "ornament",
)
AXIS_MAPPING = dict(zip(OBSERVATION_AXES, REGISTRY_AXES, strict=True))

INITIAL_VISUAL_STATUS = "pending_native_krea_observation"
STABLE_VISUAL_STATUS = "native_krea_observed_signature_pending_runtime"
UNSTABLE_VISUAL_STATUS = "native_krea_observation_unstable"
INITIAL_SOURCE_STATUS = "tag_identity_verified_signature_pending"
STABLE_SOURCE_STATUS = (
    "tag_identity_verified_native_krea_observed_signature_pending_runtime"
)
UNSTABLE_SOURCE_STATUS = "tag_identity_verified_native_krea_observation_unstable"

MERGED_FIELDS = {
    "schema_version",
    "kind",
    "artist_count",
    "axis_order",
    "artists",
}
PROTECTED_FIELDS = (
    "display_name",
    "source_tags",
    "evidence",
    "runtime_signature_ref",
)
FULL_URL_RE = re.compile(r"(?:https?|ssh)://[^\s'\"<>]+", re.IGNORECASE)
FULL_HOME_PATH_RE = re.compile(r"(?:/home/|/Users/)[^\s'\"<>]+")


def _expected_artist_ids(expected_artists: int) -> set[str]:
    if expected_artists < 1 or expected_artists > 999:
        raise ValueError("expected artist count must be from 1 to 999")
    return {f"artist_{index:03d}" for index in range(1, expected_artists + 1)}


def _validate_artist_ids(
    artist_ids: set[Any], *, expected_artists: int, source: str
) -> set[str]:
    if any(
        not isinstance(artist_id, str) or not ARTIST_ID_RE.fullmatch(artist_id)
        for artist_id in artist_ids
    ):
        raise ValueError(f"{source} contains an invalid artist_### id")
    validated = {str(artist_id) for artist_id in artist_ids}
    expected = _expected_artist_ids(expected_artists)
    missing = expected - validated
    extra = validated - expected
    if missing or extra:
        raise ValueError(
            f"{source} must cover artist_001 through artist_{expected_artists:03d} "
            f"exactly; missing={len(missing)}, extra={len(extra)}"
        )
    return validated


def _load_yaml_mapping(path: Path, *, source: str) -> dict[str, Any]:
    try:
        document = load_yaml(path)
    except yaml.YAMLError as exc:
        raise ValueError(f"{source} contains invalid YAML") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{source} must be a mapping")
    return document


def validate_registry(
    document: dict[str, Any], *, expected_artists: int = DEFAULT_EXPECTED_ARTISTS
) -> set[str]:
    if document.get("schema_version") != 1:
        raise ValueError("registry schema_version must be 1")
    if document.get("registry") != "artist_research":
        raise ValueError("registry must be artist_research")
    artists = document.get("artists")
    if not isinstance(artists, dict):
        raise ValueError("registry artists must be a mapping")
    artist_ids = _validate_artist_ids(
        set(artists), expected_artists=expected_artists, source="registry"
    )

    valid_status_pairs = {
        (INITIAL_VISUAL_STATUS, INITIAL_SOURCE_STATUS),
        (STABLE_VISUAL_STATUS, STABLE_SOURCE_STATUS),
        (UNSTABLE_VISUAL_STATUS, UNSTABLE_SOURCE_STATUS),
    }
    for artist_id in sorted(artist_ids):
        record = artists[artist_id]
        if not isinstance(record, dict):
            raise ValueError(f"{artist_id}: registry record must be a mapping")
        missing_protected = [field for field in PROTECTED_FIELDS if field not in record]
        if missing_protected:
            raise ValueError(f"{artist_id}: registry record lacks protected fields")
        if not isinstance(record["display_name"], str) or not record["display_name"]:
            raise ValueError(f"{artist_id}: display_name must be non-empty text")
        if not isinstance(record["source_tags"], dict):
            raise ValueError(f"{artist_id}: source_tags must be a mapping")
        if not isinstance(record["evidence"], dict):
            raise ValueError(f"{artist_id}: evidence must be a mapping")

        signature = record.get("visual_signature")
        if not isinstance(signature, dict):
            raise ValueError(f"{artist_id}: visual_signature must be a mapping")
        axes = signature.get("axes")
        if not isinstance(axes, dict) or set(axes) != set(REGISTRY_AXES):
            raise ValueError(
                f"{artist_id}: visual_signature.axes must contain the exact registry axes"
            )
        status_pair = (signature.get("status"), record.get("source_status"))
        if status_pair not in valid_status_pairs:
            raise ValueError(f"{artist_id}: registry observation statuses are inconsistent")
        for axis, value in axes.items():
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(
                    f"{artist_id}.visual_signature.axes.{axis} must be null or text"
                )
    return artist_ids


def _identity_variants(value: str) -> set[str]:
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        return set()
    variants = {normalized, normalized.lstrip("@")}
    variants.update(value.replace("_", " ") for value in tuple(variants))
    return {variant for variant in variants if variant}


def forbidden_identity_names(registry: dict[str, Any]) -> tuple[str, ...]:
    names: set[str] = set()
    artists = registry["artists"]
    for record in artists.values():
        names.update(_identity_variants(record["display_name"]))
        aliases = record.get("aliases")
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str):
                    names.update(_identity_variants(alias))
        for source_tag in record["source_tags"].values():
            if isinstance(source_tag, str):
                names.update(_identity_variants(source_tag))
    return tuple(sorted(names))


def _forbidden_identity_pattern(names: tuple[str, ...]) -> re.Pattern[str] | None:
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _clean_merged_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    forbidden_pattern: re.Pattern[str] | None,
) -> str:
    cleaned = _clean_observation_text(
        value,
        field=field,
        max_length=max_length,
        forbidden_names=(),
    )
    normalized = " ".join(cleaned.split()).casefold()
    if forbidden_pattern is not None and forbidden_pattern.search(normalized):
        raise ValueError(f"{field} contains a forbidden canonical identity")
    return cleaned


def load_merged_observations(
    path: Path,
    *,
    expected_artist_ids: set[str],
    forbidden_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    document = _load_yaml_mapping(path, source="merged observations")
    if set(document) != MERGED_FIELDS:
        raise ValueError("merged observations contain unexpected or missing metadata")
    if document.get("schema_version") != 1:
        raise ValueError("merged observations schema_version must be 1")
    if document.get("kind") != "artist_native_observations":
        raise ValueError("input is not merged artist native observations")
    if document.get("axis_order") != list(OBSERVATION_AXES):
        raise ValueError("merged observations axis_order is invalid")
    artists = document.get("artists")
    if not isinstance(artists, dict):
        raise ValueError("merged observations artists must be a mapping")
    if type(document.get("artist_count")) is not int or document["artist_count"] != len(
        artists
    ):
        raise ValueError("merged observations artist_count does not match artists")
    if set(artists) != expected_artist_ids:
        missing = expected_artist_ids - set(artists)
        extra = set(artists) - expected_artist_ids
        raise ValueError(
            "merged observation coverage does not exactly match the registry; "
            f"missing={len(missing)}, extra={len(extra)}"
        )

    forbidden_pattern = _forbidden_identity_pattern(forbidden_names)
    validated: dict[str, dict[str, Any]] = {}
    for artist_id in sorted(expected_artist_ids):
        raw = artists[artist_id]
        if not isinstance(raw, dict) or set(raw) != ENTRY_FIELDS:
            raise ValueError(
                f"{artist_id}: observation must contain exactly axes, confidence, "
                "stable_across_seeds, notes"
            )
        raw_axes = raw["axes"]
        if not isinstance(raw_axes, dict) or set(raw_axes) != set(OBSERVATION_AXES):
            raise ValueError(f"{artist_id}: observation axes must contain exactly eight axes")
        axes = {
            axis: _clean_merged_text(
                raw_axes[axis],
                field=f"{artist_id}.axes.{axis}",
                max_length=240,
                forbidden_pattern=forbidden_pattern,
            )
            for axis in OBSERVATION_AXES
        }
        confidence = raw["confidence"]
        if type(confidence) is not int or not 1 <= confidence <= 5:
            raise ValueError(f"{artist_id}: confidence must be an integer from 1 to 5")
        stable = raw["stable_across_seeds"]
        if type(stable) is not bool:
            raise ValueError(f"{artist_id}: stable_across_seeds must be a boolean")
        notes = _clean_merged_text(
            raw["notes"],
            field=f"{artist_id}.notes",
            max_length=500,
            forbidden_pattern=forbidden_pattern,
        )
        validated[artist_id] = {
            "axes": axes,
            "confidence": confidence,
            "stable_across_seeds": stable,
            "notes": notes,
        }
    return validated


def apply_observations(
    registry: dict[str, Any], observations: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, int]]:
    registry_ids = set(registry["artists"])
    if set(observations) != registry_ids:
        raise ValueError("observation coverage does not exactly match the registry")
    updated = copy.deepcopy(registry)
    counts = {"stable": 0, "unstable": 0, "changed": 0}

    for artist_id in sorted(registry_ids):
        original_record = registry["artists"][artist_id]
        record = updated["artists"][artist_id]
        observation = observations[artist_id]
        stable = (
            observation["stable_across_seeds"] is True
            and observation["confidence"] >= 3
        )
        if stable:
            desired_visual = STABLE_VISUAL_STATUS
            desired_source = STABLE_SOURCE_STATUS
            counts["stable"] += 1
        else:
            desired_visual = UNSTABLE_VISUAL_STATUS
            desired_source = UNSTABLE_SOURCE_STATUS
            counts["unstable"] += 1

        current_pair = (
            record["visual_signature"]["status"],
            record["source_status"],
        )
        desired_pair = (desired_visual, desired_source)
        initial_pair = (INITIAL_VISUAL_STATUS, INITIAL_SOURCE_STATUS)
        if current_pair not in {initial_pair, desired_pair}:
            raise ValueError(f"{artist_id}: existing observation status conflicts")

        changed = current_pair != desired_pair
        target_axes = record["visual_signature"]["axes"]
        for observation_axis, registry_axis in AXIS_MAPPING.items():
            value = observation["axes"][observation_axis]
            current = target_axes[registry_axis]
            if current is not None and current != value:
                raise ValueError(
                    f"{artist_id}: existing non-null observation conflicts at {registry_axis}"
                )
            if current is None:
                target_axes[registry_axis] = value
                changed = True

        record["visual_signature"]["status"] = desired_visual
        record["source_status"] = desired_source
        for field in PROTECTED_FIELDS:
            if record[field] != original_record[field]:
                raise ValueError(f"{artist_id}: protected registry fields changed")
        if changed:
            counts["changed"] += 1

    return updated, counts


def atomic_dump_yaml(document: dict[str, Any], path: Path) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        dump_yaml(document, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def redact_error(message: str) -> str:
    message = FULL_URL_RE.sub("<redacted_endpoint>", message)
    message = URL_RE.sub("<redacted_endpoint>", message)
    message = IPV4_RE.sub("<redacted_address>", message)
    message = FULL_HOME_PATH_RE.sub("<redacted_account_path>", message)
    message = HOME_PATH_RE.sub("<redacted_account_path>", message)
    message = WINDOWS_HOME_RE.sub("<redacted_account_path>", message)
    return ACCOUNT_AT_HOST_RE.sub("<redacted_account>", message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply name-free merged native observations to the artist registry"
    )
    parser.add_argument("observations", type=Path)
    parser.add_argument(
        "--registry", type=Path, default=Path("research/artist_registry.yaml")
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = _load_yaml_mapping(args.registry, source="artist registry")
        artist_ids = validate_registry(registry)
        observations = load_merged_observations(
            args.observations,
            expected_artist_ids=artist_ids,
            forbidden_names=forbidden_identity_names(registry),
        )
        updated, counts = apply_observations(registry, observations)
        summary = (
            f"{len(artist_ids)} name-free artist observation(s); "
            f"stable={counts['stable']}, unstable={counts['unstable']}, "
            f"changed={counts['changed']}"
        )
        if not args.apply:
            print(f"DRY RUN: validated {summary}; registry unchanged.")
            return 0
        if counts["changed"]:
            atomic_dump_yaml(updated, args.registry)
        print(f"Applied {summary}.")
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {redact_error(str(exc))}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
