#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from check_sensitive_data import scan_text


ROOT = Path(__file__).resolve().parents[1]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_TEXT_CHUNKS = {b"tEXt", b"zTXt", b"iTXt"}
MAX_TEXT_CHUNK_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, order=True)
class Finding:
    scope: str
    source: str
    category: str


@dataclass(frozen=True)
class GitScanResult:
    repository_present: bool
    findings: tuple[Finding, ...]


def _decompress_text(payload: bytes) -> bytes | None:
    try:
        decompressor = zlib.decompressobj()
        text = decompressor.decompress(payload, MAX_TEXT_CHUNK_BYTES + 1)
        if len(text) > MAX_TEXT_CHUNK_BYTES or decompressor.unconsumed_tail:
            return None
        text += decompressor.flush(MAX_TEXT_CHUNK_BYTES + 1 - len(text))
    except zlib.error:
        return None
    if len(text) > MAX_TEXT_CHUNK_BYTES or not decompressor.eof:
        return None
    return text


def _split_null(payload: bytes) -> tuple[bytes, bytes] | None:
    if b"\0" not in payload:
        return None
    return tuple(payload.split(b"\0", 1))  # type: ignore[return-value]


def _decode_png_text(chunk_type: bytes, payload: bytes) -> str | None:
    if chunk_type == b"tEXt":
        parts = _split_null(payload)
        if parts is None:
            return None
        keyword, text = parts
        return f"{keyword.decode('latin-1')} {text.decode('latin-1')}"

    if chunk_type == b"zTXt":
        parts = _split_null(payload)
        if parts is None:
            return None
        keyword, compressed = parts
        if not compressed or compressed[0] != 0:
            return None
        text = _decompress_text(compressed[1:])
        if text is None:
            return None
        return f"{keyword.decode('latin-1')} {text.decode('latin-1')}"

    if chunk_type == b"iTXt":
        parts = _split_null(payload)
        if parts is None:
            return None
        keyword, remainder = parts
        if len(remainder) < 2:
            return None
        compression_flag, compression_method = remainder[:2]
        language_parts = _split_null(remainder[2:])
        if language_parts is None:
            return None
        language, remainder = language_parts
        translated_parts = _split_null(remainder)
        if translated_parts is None:
            return None
        translated_keyword, text_payload = translated_parts
        if compression_flag == 1:
            if compression_method != 0:
                return None
            decompressed = _decompress_text(text_payload)
            if decompressed is None:
                return None
            text_payload = decompressed
        elif compression_flag != 0:
            return None
        fields = (
            keyword.decode("latin-1"),
            language.decode("ascii", errors="replace"),
            translated_keyword.decode("utf-8", errors="replace"),
            text_payload.decode("utf-8", errors="replace"),
        )
        return " ".join(fields)

    return None


def extract_png_text(data: bytes) -> tuple[str, ...]:
    """Return decoded PNG textual metadata without inspecting compressed pixels."""
    if not data.startswith(PNG_SIGNATURE):
        return ()
    offset = len(PNG_SIGNATURE)
    text_chunks: list[str] = []
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        chunk_end = data_end + 4
        if data_end < data_start or chunk_end > len(data):
            break
        if chunk_type in PNG_TEXT_CHUNKS:
            decoded = _decode_png_text(chunk_type, data[data_start:data_end])
            if decoded is not None:
                text_chunks.append(decoded)
        offset = chunk_end
        if chunk_type == b"IEND":
            break
    return tuple(text_chunks)


def scan_payload(data: bytes, account_name: str) -> set[str]:
    if data.startswith(PNG_SIGNATURE):
        texts = extract_png_text(data)
    else:
        try:
            texts = (data.decode("utf-8"),)
        except UnicodeDecodeError:
            return set()
    return set().union(*(scan_text(text, account_name) for text in texts)) if texts else set()


def scan_artifacts(root: Path, account_name: str) -> tuple[Finding, ...]:
    findings: set[Finding] = set()
    paths = set(root.rglob("run.json")) | set(root.rglob("*.png"))
    for path in sorted(paths):
        if ".git" in path.relative_to(root).parts:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        relative_path = path.relative_to(root).as_posix()
        path_categories = scan_text(relative_path, account_name)
        source = "<redacted-path>" if path_categories else relative_path
        for category in scan_payload(data, account_name) | path_categories:
            findings.add(Finding("artifact", source, category))
    return tuple(sorted(findings))


def _git(repo: Path, *args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Git history query failed")
    return result.stdout


def find_git_root(start: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return Path(result.stdout.decode("utf-8").strip())
    except UnicodeDecodeError:
        return None


def _reachable_objects(repo: Path) -> tuple[tuple[str, str], ...]:
    lines = _git(repo, "rev-list", "--objects", "--all", "--reflog").splitlines()
    object_ids = sorted({line.split(maxsplit=1)[0].decode("ascii") for line in lines if line})
    objects: list[tuple[str, str]] = []
    for object_id in object_ids:
        object_type = _git(repo, "cat-file", "-t", object_id).decode("ascii").strip()
        objects.append((object_id, object_type))
    return tuple(objects)


def scan_git_history(start: Path, account_name: str) -> GitScanResult:
    repo = find_git_root(start)
    if repo is None:
        return GitScanResult(False, ())

    findings: set[Finding] = set()
    objects = _reachable_objects(repo)
    for object_id, object_type in objects:
        if object_type == "blob":
            data = _git(repo, "cat-file", "blob", object_id)
            categories = scan_payload(data, account_name)
            source = f"blob {object_id[:12]}"
        elif object_type == "commit":
            data = _git(repo, "show", "-s", "--format=%B", object_id)
            categories = scan_payload(data, account_name)
            source = f"commit {object_id[:12]}"
        else:
            continue
        for category in categories:
            findings.add(Finding("git-history", source, category))

    ref_names = _git(repo, "for-each-ref", "--format=%(refname)").splitlines()
    for index, ref_name in enumerate(ref_names, start=1):
        for category in scan_payload(ref_name, account_name):
            findings.add(Finding("git-ref", f"ref #{index}", category))

    reflog_subjects = _git(repo, "reflog", "show", "--all", "--format=%gs").splitlines()
    for index, subject in enumerate(reflog_subjects, start=1):
        for category in scan_payload(subject, account_name):
            findings.add(Finding("git-reflog", f"entry #{index}", category))

    return GitScanResult(True, tuple(sorted(findings)))


def render_findings(findings: tuple[Finding, ...]) -> str:
    lines = ["ERROR: sensitive literals detected in retained records:"]
    lines.extend(
        f"- {finding.scope} {finding.source}: {finding.category}" for finding in findings
    )
    return "\n".join(lines)


def main() -> int:
    account_name = Path.home().name
    artifact_findings = scan_artifacts(ROOT, account_name)
    try:
        git_result = scan_git_history(ROOT, account_name)
    except RuntimeError:
        print("ERROR: Git history scan could not be completed.", file=sys.stderr)
        return 2

    findings = tuple(sorted((*artifact_findings, *git_result.findings)))
    if findings:
        print(render_findings(findings), file=sys.stderr)
        return 1
    if git_result.repository_present:
        print("OK: retained Git history and runtime artifacts contain no sensitive literals.")
    else:
        print("OK: no Git repository present; runtime artifacts contain no sensitive literals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
