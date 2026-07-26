from __future__ import annotations

import json
import struct
import subprocess
import zlib
from pathlib import Path

from check_sensitive_history import (
    PNG_SIGNATURE,
    extract_png_text,
    render_findings,
    scan_artifacts,
    scan_git_history,
    scan_payload,
)


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def png_with_chunks(*chunks: tuple[bytes, bytes]) -> bytes:
    return PNG_SIGNATURE + b"".join(png_chunk(kind, payload) for kind, payload in chunks) + png_chunk(b"IEND", b"")


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_png_scanner_reads_text_chunks_but_ignores_pixel_stream() -> None:
    address = ".".join(str(part) for part in (10, 21, 31, 41))
    account = "runtimeacct"
    pixels_only = png_with_chunks((b"IDAT", f"/home/{account} http://{address}".encode()))
    assert extract_png_text(pixels_only) == ()
    assert scan_payload(pixels_only, account) == set()

    text = f"endpoint\0http://{address} /home/{account}/service".encode()
    with_text = png_with_chunks((b"tEXt", text))
    assert scan_payload(with_text, account) == {
        "IP address literal",
        "account home path",
        "local account name",
    }


def test_png_scanner_reads_compressed_and_international_text() -> None:
    address = ".".join(str(part) for part in (172, 20, 30, 40))
    compressed_text = b"endpoint\0\0" + zlib.compress(f"http://{address}".encode())
    account_path = "/".join(("", "home", "renderacct", "job"))
    international_text = b"workflow\0\x00\x00en\0label\0" + account_path.encode()
    image = png_with_chunks(
        (b"zTXt", compressed_text),
        (b"iTXt", international_text),
    )
    assert len(extract_png_text(image)) == 2
    assert scan_payload(image, "renderacct") == {
        "IP address literal",
        "account home path",
        "local account name",
    }


def test_artifact_scan_and_report_do_not_echo_matched_values(tmp_path: Path) -> None:
    address = ".".join(str(part) for part in (192, 168, 51, 61))
    account = "privateacct"
    run_dir = tmp_path / "tests" / "reports" / "runs" / account
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"api_url": f"http://{address}", "path": f"/home/{account}/run"}),
        encoding="utf-8",
    )
    (run_dir / "image.png").write_bytes(
        png_with_chunks((b"tEXt", f"workflow\0{account}@host.example".encode()))
    )

    findings = scan_artifacts(tmp_path, account)
    rendered = render_findings(findings)
    assert findings
    assert address not in rendered
    assert account not in rendered
    assert "/home/" not in rendered


def test_git_scan_skips_cleanly_when_repository_is_absent(tmp_path: Path) -> None:
    result = scan_git_history(tmp_path, "privateacct")
    assert result.repository_present is False
    assert result.findings == ()


def test_git_scan_accepts_an_empty_repository(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    result = scan_git_history(tmp_path, "privateacct")
    assert result.repository_present is True
    assert result.findings == ()


def test_git_scan_includes_objects_retained_only_by_reflog_and_redacts_values(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "History Test")
    git(repo, "config", "user.email", "history@example.invalid")
    (repo / "record.txt").write_text("clean\n", encoding="utf-8")
    git(repo, "add", "record.txt")
    git(repo, "commit", "-q", "-m", "clean base")

    address = ".".join(str(part) for part in (10, 61, 71, 81))
    account = "historyacct"
    (repo / "record.txt").write_text(
        f"http://{address} /home/{account}/service\n", encoding="utf-8"
    )
    git(repo, "add", "record.txt")
    git(repo, "commit", "-q", "-m", "temporary record")
    git(repo, "reset", "--hard", "HEAD~1")

    result = scan_git_history(repo, account)
    rendered = render_findings(result.findings)
    assert result.repository_present is True
    assert any(finding.scope == "git-history" for finding in result.findings)
    assert address not in rendered
    assert account not in rendered
    assert "/home/" not in rendered


def test_git_scan_checks_ref_names_and_reflog_subjects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "History Test")
    git(repo, "config", "user.email", "history@example.invalid")
    (repo / "record.txt").write_text("clean\n", encoding="utf-8")
    git(repo, "add", "record.txt")
    git(repo, "commit", "-q", "-m", "clean base")

    account = "refaccount"
    git(repo, "branch", account)
    address = ".".join(str(part) for part in (10, 91, 101, 111))
    git(repo, "commit", "--allow-empty", "-q", "-m", f"contact http://{address}")

    result = scan_git_history(repo, account)
    scopes = {finding.scope for finding in result.findings}
    assert "git-ref" in scopes
    assert "git-reflog" in scopes
