#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml


SOURCE_REF = "anima_tagger_artifacts_snapshot"
SOURCE_REVISION = "3819f8341e6675df3b0034bcdab37b0de9f6c56e"
SOURCE_SHA256 = "4ec8f9a7e70956b00d892a8105bf421a519d9b86e8fb17ce333010b69dedebd4"
SOURCE_URL = (
    "https://huggingface.co/datasets/freedumb2000/anima-tagger-artifacts/resolve/"
    f"{SOURCE_REVISION}/tags.sqlite"
)
AXES = (
    "linework",
    "face_design",
    "eye_design",
    "body_design",
    "coloring",
    "shading",
    "composition",
    "ornament",
)


class RegistryError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_database(path: Path) -> None:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "krea2-wildcards-research/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except OSError as exc:
        raise RegistryError(f"cannot fetch pinned artist tag snapshot: {exc}") from exc


def split_aliases(value: str) -> list[str]:
    return sorted({alias.strip() for alias in value.split(",") if alias.strip()})


def load_artists(database: Path, *, limit: int, minimum_posts: int) -> list[dict[str, Any]]:
    if limit < 1:
        raise RegistryError("limit must be at least 1")
    if minimum_posts < 1:
        raise RegistryError("minimum posts must be at least 1")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tags)").fetchall()
        }
        required = {"id", "name", "category", "post_count", "aliases"}
        if not required <= columns:
            raise RegistryError(f"tags table lacks required columns: {sorted(required - columns)}")
        rows = connection.execute(
            """
            SELECT id, name, post_count, aliases
            FROM tags
            WHERE category = 1 AND post_count >= ?
            ORDER BY post_count DESC, name ASC
            LIMIT ?
            """,
            (minimum_posts, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        raise RegistryError(f"cannot read artist tag snapshot: {exc}") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if len(rows) != limit:
        raise RegistryError(f"snapshot yielded {len(rows)} artists; expected {limit}")
    return [dict(row) for row in rows]


def build_registry(
    artists: list[dict[str, Any]],
    *,
    accessed: str,
    minimum_posts: int,
    database_sha256: str,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    seen_tags: set[str] = set()
    for index, artist in enumerate(artists, start=1):
        tag = artist["name"]
        if not isinstance(tag, str) or not tag or tag in seen_tags:
            raise RegistryError(f"artist tag must be unique non-empty text: {tag!r}")
        seen_tags.add(tag)
        internal_id = f"artist_{index:03d}"
        records[internal_id] = {
            "display_name": tag.replace("_", " "),
            "aliases": split_aliases(artist.get("aliases") or ""),
            "source_tags": {
                "danbooru": tag,
                "anima": "@" + tag.replace("_", " "),
                "novelai": None,
            },
            "source_status": "tag_identity_verified_signature_pending",
            "evidence": {
                "source_ref": SOURCE_REF,
                "tag_id": int(artist["id"]),
                "category": "artist",
                "post_count": int(artist["post_count"]),
            },
            "visual_signature": {
                "status": "pending_native_krea_observation",
                "axes": {axis: None for axis in AXES},
            },
            "runtime_signature_ref": None,
        }
    return {
        "schema_version": 1,
        "registry": "artist_research",
        "source_snapshot": {
            "source_ref": SOURCE_REF,
            "revision": SOURCE_REVISION,
            "artifact": "tags.sqlite",
            "sha256": database_sha256,
            "accessed": accessed,
            "selection": {
                "category": "artist",
                "minimum_post_count": minimum_posts,
                "order": ["post_count_desc", "tag_name_asc"],
                "limit": len(records),
            },
        },
        "artists": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic canonical artist research registry from a pinned tag snapshot"
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research/artist_registry.yaml"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--minimum-posts", type=int, default=50)
    parser.add_argument("--accessed", default="2026-07-26")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        database = args.database
        if database is None:
            temporary = tempfile.TemporaryDirectory(prefix="krea2-artist-registry-")
            database = Path(temporary.name) / "tags.sqlite"
            fetch_database(database)
        if not database.is_file():
            raise RegistryError(f"database does not exist: {database}")
        database_hash = sha256(database)
        if database_hash != SOURCE_SHA256:
            raise RegistryError(
                f"database sha256 mismatch: expected {SOURCE_SHA256}, got {database_hash}"
            )
        document = build_registry(
            load_artists(database, limit=args.limit, minimum_posts=args.minimum_posts),
            accessed=args.accessed,
            minimum_posts=args.minimum_posts,
            database_sha256=database_hash,
        )
        if not args.apply:
            print(
                f"DRY RUN: {len(document['artists'])} canonical artist tag record(s); "
                "signatures remain pending native Krea observation."
            )
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )
        print(f"Wrote {len(document['artists'])} artist research record(s) to {args.output}.")
        return 0
    except (OSError, RegistryError) as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
