from __future__ import annotations

import sqlite3
from pathlib import Path

from build_artist_research_registry import AXES, build_registry, load_artists, split_aliases


def fixture_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE tags (id INTEGER, name TEXT, category INTEGER, post_count INTEGER, aliases TEXT)"
    )
    connection.executemany(
        "INSERT INTO tags VALUES (?, ?, ?, ?, ?)",
        [
            (1, "second_artist", 1, 75, "alias_b, alias_a"),
            (2, "first_artist", 1, 100, ""),
            (3, "general_tag", 0, 1000, ""),
            (4, "too_small", 1, 49, ""),
        ],
    )
    connection.commit()
    connection.close()


def test_registry_selection_identity_and_pending_axes(tmp_path: Path) -> None:
    database = tmp_path / "tags.sqlite"
    fixture_database(database)
    rows = load_artists(database, limit=2, minimum_posts=50)
    document = build_registry(
        rows,
        accessed="2026-07-26",
        minimum_posts=50,
        database_sha256="a" * 64,
    )

    assert list(document["artists"]) == ["artist_001", "artist_002"]
    first = document["artists"]["artist_001"]
    assert first["display_name"] == "first artist"
    assert first["source_tags"] == {
        "danbooru": "first_artist",
        "anima": "@first artist",
        "novelai": None,
    }
    assert set(first["visual_signature"]["axes"]) == set(AXES)
    assert set(first["visual_signature"]["axes"].values()) == {None}
    assert document["artists"]["artist_002"]["aliases"] == ["alias_a", "alias_b"]


def test_alias_normalization_is_unique_and_sorted() -> None:
    assert split_aliases(" beta, alpha, beta, , gamma ") == ["alpha", "beta", "gamma"]
