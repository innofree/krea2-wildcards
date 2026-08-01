from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from run_sharded_prompt_matrix import (
    merge,
    parse_shard_workflows,
    parse_weights,
    shard,
)


def _rows(n: int) -> list[dict]:
    return [{"test_id": f"P{i:04d}", "style_id": f"style_{i}", "seed": 1001} for i in range(n)]


def test_shard_partitions_exactly_with_no_overlap() -> None:
    """The union of all shards must equal the input, with nothing duplicated."""
    rows = _rows(900)
    buckets = shard(rows, [2.0, 1.0, 1.0])
    ids = [set(r["test_id"] for r in bucket) for bucket in buckets]
    assert ids[0] & ids[1] == set()
    assert ids[0] & ids[2] == set()
    assert ids[1] & ids[2] == set()
    assert ids[0] | ids[1] | ids[2] == {r["test_id"] for r in rows}
    assert len(buckets[0]) + len(buckets[1]) + len(buckets[2]) == 900


def test_shard_respects_weight_proportions() -> None:
    rows = _rows(1000)
    buckets = shard(rows, [2.0, 1.0, 1.0])
    assert len(buckets[0]) == 500
    assert len(buckets[1]) == 250
    assert len(buckets[2]) == 250


def test_shard_rejects_weights_that_starve_a_bucket() -> None:
    with pytest.raises(ValueError, match="no work"):
        shard(_rows(2), [100.0, 0.001])


def test_parse_weights_defaults_to_equal_split() -> None:
    assert parse_weights(None, 3) == [1.0, 1.0, 1.0]


def test_parse_weights_rejects_wrong_count_or_nonpositive() -> None:
    with pytest.raises(ValueError, match="3 comma"):
        parse_weights("2,1", 3)
    with pytest.raises(ValueError, match="positive"):
        parse_weights("2,-1", 2)


def test_shard_workflow_falls_back_to_the_primary_for_unspecified_endpoints() -> None:
    """A GPU without the primary checkpoint gets its own workflow; others don't need one."""
    paths = parse_shard_workflows(["", "tests/baseline/workflow_int8_a6000.json"], 3)
    assert paths == [None, Path("tests/baseline/workflow_int8_a6000.json"), None]


def test_shard_workflow_rejects_more_overrides_than_endpoints() -> None:
    with pytest.raises(ValueError, match="only 2 endpoint"):
        parse_shard_workflows(["a", "b", "c"], 2)


def _write_shard(shard_dir: Path, jobs: dict[str, dict], *, workflow_sha: str) -> None:
    runs = shard_dir / "runs"
    rows = []
    for test_id, job in jobs.items():
        run_dir = runs / test_id
        run_dir.mkdir(parents=True)
        (run_dir / "image_01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        rows.append(
            {
                "test_id": test_id,
                "seed": "1001",
                "style_id": job["style_id"],
                "image_path": (run_dir / "image_01.png").as_posix(),
            }
        )
    with (shard_dir / "scorecard.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["test_id", "seed", "style_id", "image_path"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    state = {
        "schema_version": 1,
        "kind": "remote_prompt_matrix_run_state",
        "matrix_sha256": f"matrix-{workflow_sha}",
        "run_id": f"run-{workflow_sha}",
        "workflow_source_sha256": workflow_sha,
        "status": "completed",
        "jobs": {tid: {"workflow_sha256": workflow_sha, "remote_status": "success"} for tid in jobs},
    }
    (shard_dir / "run-state.json").write_text(json.dumps(state), encoding="utf-8")


def test_merge_folds_shards_and_drops_the_per_shard_only_fields(tmp_path: Path) -> None:
    """workflow_source_sha256 describes one shard's checkpoint, so a merge spanning
    two checkpoints (the actual A6000/PRO6000 case) must not keep it at the header
    level -- each job's own workflow_sha256 is still correct and is what survives."""
    output = tmp_path / "merged"
    shard_a = output / "shard_1"
    shard_b = output / "shard_2"
    _write_shard(shard_a, {"P0001": {"style_id": "s1"}}, workflow_sha="mxfp8-hash")
    _write_shard(shard_b, {"P0002": {"style_id": "s2"}}, workflow_sha="int8-hash")

    summary = merge(output, [shard_a, shard_b])
    assert summary == {"jobs": 2, "rows": 2}

    state = json.loads((output / "run-state.json").read_text())
    assert "matrix_sha256" not in state
    assert "run_id" not in state
    assert "workflow_source_sha256" not in state
    assert state["jobs"]["P0001"]["workflow_sha256"] == "mxfp8-hash"
    assert state["jobs"]["P0002"]["workflow_sha256"] == "int8-hash"
    assert state["kind"] == "sharded_prompt_matrix_run"
    assert state["shard_count"] == 2

    assert (output / "runs" / "P0001" / "image_01.png").is_file()
    assert (output / "runs" / "P0002" / "image_01.png").is_file()
    assert not shard_a.exists()
    assert not shard_b.exists()

    rows = list(csv.DictReader((output / "scorecard.csv").open(encoding="utf-8")))
    assert [r["test_id"] for r in rows] == ["P0001", "P0002"]
    assert rows[0]["image_path"] == (output / "runs" / "P0001" / "image_01.png").as_posix()


def test_merge_rejects_shards_that_share_a_test_id(tmp_path: Path) -> None:
    output = tmp_path / "merged"
    shard_a = output / "shard_1"
    shard_b = output / "shard_2"
    _write_shard(shard_a, {"P0001": {"style_id": "s1"}}, workflow_sha="a")
    _write_shard(shard_b, {"P0001": {"style_id": "s1-dupe"}}, workflow_sha="b")
    with pytest.raises(ValueError, match="share test id"):
        merge(output, [shard_a, shard_b])
