#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from common import iter_leaf_lists, load_yaml


DEFAULT_SOURCE = Path("build/impact-production/krea2_complete_pack.yaml")
DEFAULT_REMOTE_NAME = "krea2_complete_pack.yaml"
SSH_TARGET_ENV = "KREA2_COMFY_SSH_TARGET"
REMOTE_DIR_ENV = "KREA2_COMFY_REMOTE_WILDCARD_DIR"
API_URL_ENV = "KREA2_COMFY_API_URL"
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy a built wildcard YAML artifact to remote ComfyUI; dry-run by default"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--ssh-target", default=os.environ.get(SSH_TARGET_ENV))
    parser.add_argument("--remote-dir", default=os.environ.get(REMOTE_DIR_ENV))
    parser.add_argument("--remote-name", default=DEFAULT_REMOTE_NAME)
    parser.add_argument("--api-url", default=os.environ.get(API_URL_ENV))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the transfer, checksum check, Impact reload, and path verification",
    )
    return parser.parse_args()


def runtime_paths(path: Path) -> set[str]:
    data = load_yaml(path)
    if not isinstance(data, dict) or list(data) != ["krea2"]:
        raise ValueError("runtime YAML must contain only the krea2 root")
    return {f"__{'/'.join(parts)}__" for parts, values in iter_leaf_lists(data) if values}


def rsync_command(
    source: Path,
    ssh_target: str,
    remote_path: PurePosixPath,
    apply: bool,
    backup_suffix: str | None = None,
) -> list[str]:
    command = ["rsync", "-av", "--checksum", "--itemize-changes"]
    if apply:
        command.extend(["--backup", f"--suffix={backup_suffix or '.bak'}"])
    else:
        command.append("--dry-run")
    command.extend([str(source), f"{ssh_target}:{remote_path}"])
    return command


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_sha256(ssh_target: str, remote_path: PurePosixPath) -> str:
    result = run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            ssh_target,
            f"sha256sum {shlex.quote(str(remote_path))}",
        ]
    )
    return result.stdout.split()[0]


def rollback_remote(
    ssh_target: str,
    remote_path: PurePosixPath,
    backup_suffix: str,
) -> None:
    backup_path = PurePosixPath(f"{remote_path}{backup_suffix}")
    command = (
        f"test -f {shlex.quote(str(backup_path))} && "
        f"mv -f {shlex.quote(str(backup_path))} {shlex.quote(str(remote_path))}"
    )
    run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            ssh_target,
            command,
        ]
    )


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, method="GET")
    with NO_PROXY_OPENER.open(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"GET request returned HTTP {response.status}")
        payload = response.read()
    return json.loads(payload) if payload else {}


def refresh(api_url: str) -> None:
    url = f"{api_url.rstrip('/')}/impact/wildcards/refresh"
    request = urllib.request.Request(url, method="GET")
    with NO_PROXY_OPENER.open(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"wildcard refresh returned HTTP {response.status}")


def verify_remote_paths(api_url: str, expected: set[str]) -> tuple[set[str], set[str]]:
    url = f"{api_url.rstrip('/')}/impact/wildcards/list"
    payload = get_json(url)
    available = set(payload.get("data", []))
    namespace = krea2_namespace(available)
    return expected - namespace, namespace - expected


def krea2_namespace(available: set[str]) -> set[str]:
    return {path for path in available if path.startswith("__krea2/")}


def remote_krea2_namespace(api_url: str) -> set[str]:
    url = f"{api_url.rstrip('/')}/impact/wildcards/list"
    payload = get_json(url)
    return krea2_namespace(set(payload.get("data", [])))


def main() -> int:
    args = parse_args()
    transfer_complete = False
    backup_suffix = ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    previous_namespace: set[str] | None = None
    try:
        missing_settings = [
            name
            for name, value in (
                (SSH_TARGET_ENV, args.ssh_target),
                (REMOTE_DIR_ENV, args.remote_dir),
                (API_URL_ENV, args.api_url),
            )
            if not value
        ]
        if missing_settings:
            raise ValueError(
                "missing remote configuration: "
                + ", ".join(missing_settings)
                + "; set environment variables or pass the matching CLI options"
            )
        remote_path = PurePosixPath(args.remote_dir) / args.remote_name
        if not args.source.is_file():
            raise FileNotFoundError(
                f"runtime artifact not found: {args.source}; build the selected artifact first"
            )
        expected = runtime_paths(args.source)
        if len(expected) < 2:
            raise ValueError(f"deployment artifact has too few runtime paths: {len(expected)}")
        if args.apply:
            previous_namespace = remote_krea2_namespace(args.api_url)

        command = rsync_command(
            args.source,
            args.ssh_target,
            remote_path,
            apply=args.apply,
            backup_suffix=backup_suffix,
        )
        display_command = command[:-1] + [f"<SSH_TARGET>:<REMOTE_WILDCARD_DIR>/{args.remote_name}"]
        print("Command:", shlex.join(display_command))
        result = run(command)
        transfer_complete = args.apply
        if result.stdout.strip():
            print(result.stdout.rstrip())
        if not args.apply:
            print("DRY RUN complete. Re-run with --apply to deploy and reload.")
            return 0

        local_digest = sha256(args.source)
        remote_digest = remote_sha256(args.ssh_target, remote_path)
        if local_digest != remote_digest:
            raise RuntimeError(
                f"checksum mismatch: local={local_digest} remote={remote_digest}"
            )
        print(f"Checksum OK: {local_digest}")

        refresh(args.api_url)
        missing, unexpected = verify_remote_paths(args.api_url, expected)
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing={len(missing)}")
            if unexpected:
                details.append(f"stale={len(unexpected)}")
            raise RuntimeError(
                "remote krea2 namespace mismatch after refresh: " + ", ".join(details)
            )
        print(f"Remote verification OK: {len(expected)} wildcard path(s).")
        return 0
    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        rollback_error: Exception | None = None
        if args.apply and transfer_complete:
            try:
                rollback_remote(args.ssh_target, remote_path, backup_suffix)
                refresh(args.api_url)
                restored_namespace = remote_krea2_namespace(args.api_url)
                if previous_namespace is None or restored_namespace != previous_namespace:
                    raise RuntimeError("rollback namespace does not match pre-deploy state")
                print("Rollback verified against the pre-deploy namespace.", file=sys.stderr)
            except Exception as rollback_exc:  # preserve the original deployment failure
                rollback_error = rollback_exc
        if isinstance(exc, subprocess.CalledProcessError):
            details = exc.stderr.strip() or exc.stdout.strip()
            for sensitive in (args.ssh_target, args.remote_dir, args.api_url):
                if sensitive:
                    details = details.replace(str(sensitive), "<REDACTED_REMOTE>")
            print(f"ERROR: command failed: {details}", file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        if rollback_error is not None:
            print("ERROR: automatic rollback could not be verified", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
