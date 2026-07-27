#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from common import iter_leaf_lists, load_yaml


DEFAULT_SOURCE = Path("build/impact-production/krea2_complete_pack.yaml")
DEFAULT_MANIFEST = Path("wildcards-manifest.json")
DEFAULT_REMOTE_NAME = "krea2_complete_pack.yaml"
SSH_TARGET_ENV = "KREA2_COMFY_SSH_TARGET"
REMOTE_DIR_ENV = "KREA2_COMFY_REMOTE_WILDCARD_DIR"
API_URL_ENV = "KREA2_COMFY_API_URL"
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SAFE_DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
FULL_URL_RE = re.compile(r"(?:https?|ssh)://[^\s'\"<>]+", re.IGNORECASE)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
HOME_PATH_RE = re.compile(r"(?:/home/|/Users/)[^\s'\"<>]+")
ACCOUNT_AT_HOST_RE = re.compile(
    r"(?<![<\w])[a-z_][a-z0-9_.-]*@[a-z0-9][a-z0-9.-]+", re.IGNORECASE
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy a built wildcard YAML artifact to remote ComfyUI; dry-run by default"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ssh-target", default=os.environ.get(SSH_TARGET_ENV))
    parser.add_argument("--remote-dir", default=os.environ.get(REMOTE_DIR_ENV))
    parser.add_argument("--remote-name", default=DEFAULT_REMOTE_NAME)
    parser.add_argument("--api-url", default=os.environ.get(API_URL_ENV))
    parser.add_argument(
        "--evidence",
        type=Path,
        help="write a redacted relative-path JSON deployment record",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the transfer, checksum check, Impact reload, and path verification",
    )
    return parser.parse_args(argv)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("JSON object contains a duplicate key")
        document[key] = value
    return document


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def approved_manifest_item_count(path: Path) -> int:
    document = load_json_object(path, label="wildcard manifest")
    if document.get("schema_version") != 1:
        raise ValueError("wildcard manifest schema_version must be 1")
    if document.get("included_statuses") != ["approved"]:
        raise ValueError("wildcard manifest must be approved-only")
    files = document.get("files")
    if (
        not isinstance(files, list)
        or not files
        or not all(isinstance(value, str) and value for value in files)
        or len(files) != len(set(files))
    ):
        raise ValueError("wildcard manifest files must be unique non-empty text")
    items = document.get("items")
    item_count = document.get("item_count")
    if (
        not isinstance(items, list)
        or not items
        or isinstance(item_count, bool)
        or not isinstance(item_count, int)
        or item_count != len(items)
    ):
        raise ValueError("wildcard manifest item_count must match its non-empty items")
    identifiers: set[str] = set()
    prompt_count = 0
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("status") != "approved":
            raise ValueError(f"wildcard manifest item {index} must be approved")
        identifier = item.get("id")
        prompts = item.get("prompt_count")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
            or isinstance(prompts, bool)
            or not isinstance(prompts, int)
            or prompts < 1
        ):
            raise ValueError(f"wildcard manifest item {index} has invalid metadata")
        identifiers.add(identifier)
        prompt_count += prompts
    recorded_prompts = document.get("prompt_count")
    if (
        isinstance(recorded_prompts, bool)
        or not isinstance(recorded_prompts, int)
        or recorded_prompts != prompt_count
    ):
        raise ValueError("wildcard manifest prompt_count does not match its items")
    return item_count


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


def deployment_id_from_evidence(path: Path) -> str:
    pure = PurePosixPath(path.as_posix())
    if (
        path.is_absolute()
        or ".." in pure.parts
        or path.suffix != ".json"
        or not SAFE_DEPLOYMENT_ID_RE.fullmatch(path.stem)
        or IPV4_RE.search(path.stem)
    ):
        raise ValueError("deployment evidence path must remain relative")
    return path.stem


def atomic_write_evidence(
    path: Path, document: dict[str, Any], *, root: Path | None = None
) -> None:
    deployment_id_from_evidence(path)
    base = (root or Path.cwd()).resolve()
    target = (base / path).resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("deployment evidence path must remain inside the repository") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def deployment_evidence(
    source: Path,
    *,
    applied: bool,
    status: str,
    expected_paths: int,
    digest: str,
    approved_items: int = 0,
    evidence_path: Path | None = None,
    deployment_type: str | None = None,
    checksum_match: bool | None = None,
    exact_krea2_namespace: bool | None = None,
    impact_reload: bool | None = None,
    queue_empty: bool | None = None,
) -> dict[str, Any]:
    if (
        status not in {"passed", "failed", "dry-run"}
        or type(approved_items) is not int
        or approved_items < 0
        or type(expected_paths) is not int
        or expected_paths < 0
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not SAFE_DEPLOYMENT_ID_RE.fullmatch(source.name)
        or IPV4_RE.search(source.name)
    ):
        raise ValueError("deployment evidence metadata is invalid")
    successful_apply = applied and status == "passed"
    if evidence_path is not None:
        deployment_id = deployment_id_from_evidence(evidence_path)
    else:
        fallback = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem).strip("_.-")
        deployment_id = fallback if SAFE_DEPLOYMENT_ID_RE.fullmatch(fallback) else "deployment"
    if deployment_type is None:
        deployment_type = (
            "production"
            if source.resolve(strict=False) == DEFAULT_SOURCE.resolve(strict=False)
            else "preview"
        )
    if deployment_type not in {"production", "preview"}:
        raise ValueError("deployment_type must be production or preview")
    return {
        "schema_version": 1,
        "deployment_id": deployment_id,
        "deployment_type": deployment_type,
        "status": status,
        "remote": "private_comfyui",
        "mode": "apply" if applied else "dry-run",
        "applied": successful_apply,
        "approved_items": approved_items,
        "artifact": {
            "name": source.name,
            "sha256": digest,
            "bytes": source.stat().st_size,
            "wildcard_path_count": expected_paths,
        },
        "verification": {
            "checksum_match": successful_apply
            if checksum_match is None
            else checksum_match,
            "exact_krea2_namespace": successful_apply
            if exact_krea2_namespace is None
            else exact_krea2_namespace,
            "impact_reload": successful_apply
            if impact_reload is None
            else impact_reload,
            "smoke_completed": False,
            "queue_empty": successful_apply if queue_empty is None else queue_empty,
        },
        "smoke": None,
    }


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
    document = json.loads(payload) if payload else {}
    if not isinstance(document, dict):
        raise RuntimeError("remote API response must be a JSON object")
    return document


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


def remote_queue_empty(api_url: str) -> bool:
    payload = get_json(f"{api_url.rstrip('/')}/queue")
    running = payload.get("queue_running")
    pending = payload.get("queue_pending")
    if not isinstance(running, list) or not isinstance(pending, list):
        raise RuntimeError("remote queue response is invalid")
    return not running and not pending


def redact_private_text(message: str, sensitive_values: Sequence[object] = ()) -> str:
    for sensitive in sensitive_values:
        if sensitive:
            message = message.replace(str(sensitive), "<REDACTED_PRIVATE>")
    message = FULL_URL_RE.sub("<REDACTED_ENDPOINT>", message)
    message = IPV4_RE.sub("<REDACTED_ADDRESS>", message)
    message = HOME_PATH_RE.sub("<REDACTED_ACCOUNT_PATH>", message)
    return ACCOUNT_AT_HOST_RE.sub("<REDACTED_ACCOUNT>", message)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    transfer_complete = False
    backup_suffix = ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    previous_namespace: set[str] | None = None
    expected: set[str] = set()
    local_digest = ""
    approved_items = 0
    checksum_match = False
    exact_namespace = False
    impact_reload = False
    queue_empty = False
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
        approved_items = approved_manifest_item_count(args.manifest)
        expected = runtime_paths(args.source)
        if len(expected) < 2:
            raise ValueError(f"deployment artifact has too few runtime paths: {len(expected)}")
        local_digest = sha256(args.source)
        if args.apply:
            previous_namespace = remote_krea2_namespace(args.api_url)

        command = rsync_command(
            args.source,
            args.ssh_target,
            remote_path,
            apply=args.apply,
            backup_suffix=backup_suffix,
        )
        display_command = command[:-2] + [
            "<LOCAL_ARTIFACT>",
            "<SSH_TARGET>:<REMOTE_WILDCARD_DIR>/<REMOTE_NAME>",
        ]
        print("Command:", shlex.join(display_command))
        result = run(command)
        transfer_complete = args.apply
        if result.stdout.strip():
            print(result.stdout.rstrip())
        if not args.apply:
            if args.evidence:
                atomic_write_evidence(
                    args.evidence,
                    deployment_evidence(
                        args.source,
                        applied=False,
                        status="dry-run",
                        expected_paths=len(expected),
                        digest=local_digest,
                        approved_items=approved_items,
                        evidence_path=args.evidence,
                        checksum_match=False,
                        exact_krea2_namespace=False,
                        impact_reload=False,
                        queue_empty=False,
                    ),
                )
            print("DRY RUN complete. Re-run with --apply to deploy and reload.")
            return 0

        remote_digest = remote_sha256(args.ssh_target, remote_path)
        if local_digest != remote_digest:
            raise RuntimeError(
                f"checksum mismatch: local={local_digest} remote={remote_digest}"
            )
        checksum_match = True
        print(f"Checksum OK: {local_digest}")

        refresh(args.api_url)
        impact_reload = True
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
        exact_namespace = True
        print(f"Remote verification OK: {len(expected)} wildcard path(s).")
        queue_empty = remote_queue_empty(args.api_url)
        if not queue_empty:
            raise RuntimeError("remote queue is not empty after refresh")
        if args.evidence:
            atomic_write_evidence(
                args.evidence,
                deployment_evidence(
                    args.source,
                    applied=True,
                    status="passed",
                    expected_paths=len(expected),
                    digest=local_digest,
                    approved_items=approved_items,
                    evidence_path=args.evidence,
                    checksum_match=checksum_match,
                    exact_krea2_namespace=exact_namespace,
                    impact_reload=impact_reload,
                    queue_empty=queue_empty,
                ),
            )
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
            details = redact_private_text(
                details,
                (args.ssh_target, args.remote_dir, args.api_url, args.source),
            )
            print(f"ERROR: command failed: {details}", file=sys.stderr)
        else:
            print(
                "ERROR: "
                + redact_private_text(
                    str(exc),
                    (args.ssh_target, args.remote_dir, args.api_url, args.source),
                ),
                file=sys.stderr,
            )
        if rollback_error is not None:
            print("ERROR: automatic rollback could not be verified", file=sys.stderr)
        if args.evidence and args.source.is_file() and local_digest:
            try:
                atomic_write_evidence(
                    args.evidence,
                    deployment_evidence(
                        args.source,
                        applied=args.apply,
                        status="failed",
                        expected_paths=len(expected),
                        digest=local_digest,
                        approved_items=approved_items,
                        evidence_path=args.evidence,
                        checksum_match=checksum_match,
                        exact_krea2_namespace=exact_namespace,
                        impact_reload=impact_reload,
                        queue_empty=queue_empty,
                    ),
                )
            except (OSError, ValueError):
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
