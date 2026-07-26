#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
HOME_PATH_RE = re.compile(r"(?:/home/|/Users/)[A-Za-z0-9_.-]+")
ACCOUNT_AT_HOST_RE = re.compile(
    r"(?<![<\w])([a-z_][a-z0-9_.-]*)@([a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+)",
    re.IGNORECASE,
)
SKIP_DIR_NAMES = {".git", ".pytest_cache", "__pycache__"}
SKIP_FILE_NAMES = {".env"}


def scan_text(text: str, account_name: str | None = None) -> set[str]:
    findings: set[str] = set()
    for match in IPV4_RE.finditer(text):
        try:
            ipaddress.ip_address(match.group())
        except ValueError:
            continue
        findings.add("IP address literal")
    if HOME_PATH_RE.search(text):
        findings.add("account home path")
    for match in ACCOUNT_AT_HOST_RE.finditer(text):
        if not match.group(2).lower().endswith(".invalid"):
            findings.add("account-at-host identifier")
    if account_name and re.search(rf"(?<![\w-]){re.escape(account_name)}(?![\w-])", text):
        findings.add("local account name")
    return findings


def should_skip(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIR_NAMES or part.endswith(".egg-info") for part in relative.parts):
        return True
    if path.name in SKIP_FILE_NAMES or (path.name.startswith(".env.") and path.name != ".env.example"):
        return True
    return False


def main() -> int:
    account_name = Path.home().name
    findings: list[str] = []
    for path in sorted(item for item in ROOT.rglob("*") if item.is_file()):
        if should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for category in sorted(scan_text(line, account_name)):
                findings.append(f"{path.relative_to(ROOT)}:{line_number}: {category}")
    if findings:
        print("ERROR: sensitive record literals detected:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("OK: no server IP, account identifier, or account home path literals detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
