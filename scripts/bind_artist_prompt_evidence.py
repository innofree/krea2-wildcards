#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from common import canonical_prompt_sha256, load_yaml
from export_artist_visual_signature_matrix import (
    FIXED_SCENE,
    ILLUSTRATED_BENCHMARK_FINISH,
    LEGACY_BENCHMARK_PROFILE,
    REPAIR_BENCHMARK_PROFILE,
    REPAIR_FIXED_SCENE,
    REPAIR_ILLUSTRATED_BENCHMARK_FINISH,
    REPAIR_SEEDS,
    RETEST_SEEDS,
    prompt_for_profile,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_TYPE = "artist_prompt_evidence_binding"
PROMPT_PREFIX = (
    "Treat this visual signature as the controlling design brief. Every listed property "
    "must be visibly expressed: "
)
PROMPT_SUFFIX = f" {FIXED_SCENE} {ILLUSTRATED_BENCHMARK_FINISH}"
REPAIR_PROMPT_PREFIX = (
    "Treat this visual signature as the controlling design brief. Every listed property "
    "must be visibly and independently expressed without merging one visual axis into another: "
)
REPAIR_PROMPT_SUFFIX = (
    f" {REPAIR_FIXED_SCENE} {REPAIR_ILLUSTRATED_BENCHMARK_FINISH}"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "binding_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relative_file(path: Path, root: Path) -> tuple[str, Path]:
    root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evidence path must remain inside repository root: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"evidence file is missing: {relative.as_posix()}")
    return relative.as_posix(), resolved


def build_binding(matrix_path: Path, catalog_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    matrix_name, matrix = relative_file(matrix_path, root)
    catalog_name, catalog = relative_file(catalog_path, root)
    catalog_document = load_yaml(catalog)
    items = catalog_document.get("items") if isinstance(catalog_document, dict) else None
    if not isinstance(items, dict) or not items:
        raise ValueError("artist catalog must contain a non-empty items mapping")

    style_digests: dict[str, str] = {}
    style_rows: dict[str, int] = {}
    seen_test_ids: set[str] = set()
    row_count = 0
    matrix_profiles: set[str] = set()
    repair_stages: set[str] = set()
    grouped_seeds: dict[tuple[str, str, str], set[int]] = {}
    for line_number, line in enumerate(
        matrix.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"matrix line {line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"matrix line {line_number}: row must be an object")
        test_id = row.get("test_id")
        style_id = row.get("style_id")
        prompt = row.get("prompt")
        if not isinstance(test_id, str) or not test_id:
            raise ValueError(f"matrix line {line_number}: test_id is required")
        if test_id in seen_test_ids:
            raise ValueError(f"matrix line {line_number}: duplicate test_id")
        seen_test_ids.add(test_id)
        item = items.get(style_id) if isinstance(style_id, str) else None
        if not isinstance(item, dict):
            raise ValueError(
                f"matrix line {line_number}: style is missing from artist catalog"
            )
        body = item.get("prompt")
        digest = canonical_prompt_sha256(body)
        factors = row.get("factors")
        if not isinstance(factors, dict):
            raise ValueError(f"matrix line {line_number}: factors must be an object")
        row_profile = factors.get("benchmark_profile")
        if row_profile is None:
            profile = LEGACY_BENCHMARK_PROFILE
            if "benchmark_stage" in factors:
                raise ValueError(
                    f"matrix line {line_number}: legacy profile cannot declare benchmark_stage"
                )
            stage = "legacy"
        elif row_profile == REPAIR_BENCHMARK_PROFILE:
            profile = row_profile
            stage = factors.get("benchmark_stage")
            if stage not in {"pilot", "extension"}:
                raise ValueError(
                    f"matrix line {line_number}: repair profile requires a valid "
                    "benchmark_stage"
                )
            repair_stages.add(stage)
        else:
            raise ValueError(
                f"matrix line {line_number}: unsupported benchmark_profile"
            )
        matrix_profiles.add(profile)
        if profile == REPAIR_BENCHMARK_PROFILE:
            seed = row.get("seed")
            expected_seeds = REPAIR_SEEDS if stage == "pilot" else RETEST_SEEDS
            if type(seed) is not int or seed not in expected_seeds:
                raise ValueError(
                    f"matrix line {line_number}: repair profile has an invalid seed"
                )
        else:
            seed = row.get("seed")
            if type(seed) is not int:
                raise ValueError(f"matrix line {line_number}: seed must be an integer")
        identity = (profile, stage, style_id)
        style_seed_set = grouped_seeds.setdefault(identity, set())
        if seed in style_seed_set:
            raise ValueError(
                f"matrix line {line_number}: duplicate style/profile/stage seed"
            )
        style_seed_set.add(seed)
        expected_prompt = prompt_for_profile(
            body,
            profile,
            feature_axes=item.get("feature_axes"),
        )
        if prompt != expected_prompt:
            raise ValueError(
                f"matrix line {line_number}: resolved prompt does not exactly bind "
                f"the current catalog body for {style_id!r}"
            )
        if isinstance(factors, dict) and "evaluated_prompt_sha256" in factors:
            if factors["evaluated_prompt_sha256"] != f"sha256_{digest}":
                raise ValueError(
                    f"matrix line {line_number}: embedded prompt digest is stale"
                )
        previous = style_digests.setdefault(style_id, digest)
        if previous != digest:
            raise ValueError(f"matrix style {style_id!r} has inconsistent prompt digests")
        style_rows[style_id] = style_rows.get(style_id, 0) + 1
        row_count += 1
    if not row_count:
        raise ValueError("artist prompt matrix contains no rows")
    for (profile, stage, style_id), seeds in grouped_seeds.items():
        if profile != REPAIR_BENCHMARK_PROFILE:
            continue
        expected_seeds = set(REPAIR_SEEDS if stage == "pilot" else RETEST_SEEDS)
        if seeds != expected_seeds:
            raise ValueError(
                f"repair profile style {style_id!r} does not contain the exact "
                f"{stage} seeds"
            )

    document: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": ARTIFACT_TYPE,
        "source_matrix": {
            "path": matrix_name,
            "sha256": file_sha256(matrix),
            "row_count": row_count,
        },
        "catalog": {
            "path": catalog_name,
            "sha256": file_sha256(catalog),
        },
        "style_count": len(style_digests),
        "style_row_counts": dict(sorted(style_rows.items())),
        "styles": dict(sorted(style_digests.items())),
    }
    document["binding_sha256"] = payload_sha256(document)
    if matrix_profiles == {REPAIR_BENCHMARK_PROFILE}:
        document["benchmark_profile"] = REPAIR_BENCHMARK_PROFILE
        if len(repair_stages) == 1:
            document["benchmark_stage"] = next(iter(repair_stages))
        else:
            document["benchmark_stages"] = sorted(repair_stages)
        document["binding_sha256"] = payload_sha256(document)
    elif REPAIR_BENCHMARK_PROFILE in matrix_profiles:
        document["benchmark_profiles"] = sorted(matrix_profiles)
        document["repair_benchmark_stages"] = sorted(repair_stages)
        document["binding_sha256"] = payload_sha256(document)
    return document


def load_validated_binding_document(
    path: Path,
    *,
    root: Path | None = None,
    expected_catalog: Path | None = None,
) -> dict[str, Any]:
    binding_path = path.resolve()
    if not binding_path.is_file():
        raise ValueError(f"prompt binding is missing: {path}")
    try:
        document = json.loads(binding_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("prompt binding must be valid JSON") from exc
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or document.get("artifact_type") != ARTIFACT_TYPE
    ):
        raise ValueError("prompt binding has invalid schema metadata")
    if document.get("binding_sha256") != payload_sha256(document):
        raise ValueError("prompt binding payload digest is stale")
    source = document.get("source_matrix")
    catalog = document.get("catalog")
    if not isinstance(source, dict) or not isinstance(catalog, dict):
        raise ValueError("prompt binding is missing source metadata")
    matrix_name = source.get("path")
    catalog_name = catalog.get("path")
    if not isinstance(matrix_name, str) or not isinstance(catalog_name, str):
        raise ValueError("prompt binding source paths must be strings")
    for name in (matrix_name, catalog_name):
        pure = PurePosixPath(name)
        if pure.is_absolute() or not pure.parts or ".." in pure.parts:
            raise ValueError("prompt binding source paths must be safe relative paths")
    if root is None:
        candidates = (binding_path.parent, *binding_path.parents)
        root = next(
            (
                candidate
                for candidate in candidates
                if (candidate / matrix_name).is_file()
                and (candidate / catalog_name).is_file()
            ),
            None,
        )
        if root is None:
            raise ValueError("cannot resolve prompt binding repository root")
    try:
        binding_path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("prompt binding must remain inside repository root") from exc
    matrix_path = root / matrix_name
    catalog_path = root / catalog_name
    if expected_catalog is not None and catalog_path.resolve() != expected_catalog.resolve():
        raise ValueError("prompt binding catalog does not match the target catalog")
    expected = build_binding(matrix_path, catalog_path, root=root)
    if document != expected:
        raise ValueError("prompt binding no longer matches its matrix or catalog")
    styles = document.get("styles")
    if not isinstance(styles, dict) or any(
        not isinstance(style_id, str)
        or not isinstance(digest, str)
        or not SHA256_RE.fullmatch(digest)
        for style_id, digest in styles.items()
    ):
        raise ValueError("prompt binding styles must map IDs to raw SHA256 digests")
    return document


def load_validated_binding(
    path: Path,
    *,
    root: Path | None = None,
    expected_catalog: Path | None = None,
) -> dict[str, str]:
    document = load_validated_binding_document(
        path,
        root=root,
        expected_catalog=expected_catalog,
    )
    return dict(document["styles"])


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to replace a different prompt binding: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bind immutable artist prompt-matrix evidence to exact catalog prompt bodies"
    )
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/artists.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        document = build_binding(args.matrix, args.catalog, root=args.root)
        atomic_write_json(args.output, document)
        print(
            f"Bound {document['style_count']} artist prompt(s) across "
            f"{document['source_matrix']['row_count']} immutable matrix row(s)."
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
