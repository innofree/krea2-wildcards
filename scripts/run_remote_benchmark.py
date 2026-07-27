#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import load_yaml
from deploy_remote_wildcards import load_json_object


API_URL_ENV = "KREA2_COMFY_API_URL"
DEFAULT_WORKFLOW = Path("tests/baseline/workflow.json")
DEFAULT_TEMPLATE = Path("templates/style_benchmark.txt")
DEFAULT_OUTPUT = Path("tests/reports")
DEFAULT_CATALOG = Path("catalog/art_styles.yaml")
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or submit a reproducible Krea2 wildcard benchmark run"
    )
    parser.add_argument("--api-url", default=os.environ.get(API_URL_ENV))
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--style-id", default="crystal_iris_pastel")
    parser.add_argument("--seed", type=int, default=1001)
    parser.add_argument(
        "--deployment-evidence",
        type=Path,
        help="bind a production smoke run to a passed deployment evidence record",
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--submit",
        action="store_true",
        help="submit the prepared workflow to the remote ComfyUI queue",
    )
    return parser.parse_args()


def catalog_style_ids(catalog_path: Path) -> set[str]:
    data = load_yaml(catalog_path)
    items = data.get("items", {}) if isinstance(data, dict) else {}
    return set(items) if isinstance(items, dict) else set()


def catalog_style_prompt(catalog_path: Path, style_id: str) -> str:
    data = load_yaml(catalog_path)
    items = data.get("items", {}) if isinstance(data, dict) else {}
    item = items.get(style_id) if isinstance(items, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("prompt"), str):
        raise ValueError(f"catalog prompt not found for style: {style_id}")
    return item["prompt"].strip()


def catalog_runtime_path(catalog_path: Path, style_id: str) -> list[str]:
    data = load_yaml(catalog_path)
    items = data.get("items", {}) if isinstance(data, dict) else {}
    item = items.get(style_id) if isinstance(items, dict) else None
    runtime = item.get("runtime") if isinstance(item, dict) else None
    path = runtime.get("path") if isinstance(runtime, dict) else None
    if (
        not isinstance(path, list)
        or len(path) < 2
        or path[-1] != style_id
        or not all(isinstance(part, str) and part for part in path)
    ):
        raise ValueError(f"catalog runtime path not found for style: {style_id}")
    return path


def wildcard_tokens(catalog_path: Path, style_id: str) -> tuple[str, str]:
    path = catalog_runtime_path(catalog_path, style_id)
    aggregate = f"__{'/'.join([*path[:-1], 'all'])}__"
    leaf = f"__{'/'.join(path)}__"
    return aggregate, leaf


def benchmark_prompt(
    template_path: Path,
    style_id: str,
    catalog_path: Path = DEFAULT_CATALOG,
) -> str:
    text = template_path.read_text(encoding="utf-8").strip()
    aggregate, leaf = wildcard_tokens(catalog_path, style_id)
    if text.count(aggregate) != 1:
        raise ValueError(f"template must contain exactly one {aggregate}")
    return text.replace(aggregate, leaf)


def resolved_benchmark_prompt(
    template_path: Path, catalog_path: Path, style_id: str
) -> str:
    wildcard_prompt = benchmark_prompt(template_path, style_id, catalog_path)
    _, leaf = wildcard_tokens(catalog_path, style_id)
    return wildcard_prompt.replace(leaf, catalog_style_prompt(catalog_path, style_id))


def nodes_by_type(workflow: dict[str, Any], class_type: str) -> list[dict[str, Any]]:
    return [node for node in workflow.values() if node.get("class_type") == class_type]


def prepare_workflow(
    workflow: dict[str, Any], prompt: str, style_id: str, seed: int
) -> dict[str, Any]:
    prepared = copy.deepcopy(workflow)
    wildcard_nodes = nodes_by_type(prepared, "ImpactWildcardProcessor")
    sampler_nodes = nodes_by_type(prepared, "KSampler")
    save_nodes = nodes_by_type(prepared, "SaveImage")
    if len(wildcard_nodes) != 1 or len(sampler_nodes) != 1 or len(save_nodes) != 1:
        raise ValueError("workflow requires exactly one ImpactWildcardProcessor, KSampler, and SaveImage")

    wildcard_inputs = wildcard_nodes[0]["inputs"]
    wildcard_inputs["wildcard_text"] = prompt
    wildcard_inputs["populated_text"] = prompt
    wildcard_inputs["mode"] = "fixed"
    wildcard_inputs["seed"] = seed
    sampler_nodes[0]["inputs"]["seed"] = seed
    save_nodes[0]["inputs"]["filename_prefix"] = (
        f"krea2-wildcards/smoke/{style_id}_seed_{seed}"
    )
    return prepared


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with NO_PROXY_OPENER.open(request, timeout=timeout) as response:
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"{request.method} request returned HTTP {response.status}")
    return json.loads(body) if body else {}


def validate_remote_nodes(api_url: str, workflow: dict[str, Any]) -> None:
    class_types = sorted({str(node.get("class_type")) for node in workflow.values()})
    missing = []
    for class_type in class_types:
        encoded = urllib.parse.quote(class_type, safe="")
        info = http_json(f"{api_url.rstrip('/')}/object_info/{encoded}")
        if class_type not in info:
            missing.append(class_type)
    if missing:
        raise ValueError(f"remote node class(es) missing: {', '.join(missing)}")


def wait_for_result(api_url: str, prompt_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    url = f"{api_url.rstrip('/')}/history/{prompt_id}"
    while time.monotonic() < deadline:
        history = http_json(url)
        if prompt_id in history:
            record = history[prompt_id]
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError("remote generation failed; inspect private server logs")
            if record.get("outputs"):
                return record
        time.sleep(2)
    raise TimeoutError(f"generation did not finish within {timeout} seconds")


def png_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 24 or image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("downloaded result is not a valid PNG")
    return struct.unpack(">II", image_bytes[16:24])


def workflow_dimensions(workflow: dict[str, Any]) -> tuple[int, int]:
    latent_nodes = nodes_by_type(workflow, "EmptyLatentImage")
    if len(latent_nodes) != 1:
        raise ValueError("workflow requires exactly one EmptyLatentImage")
    inputs = latent_nodes[0].get("inputs", {})
    return int(inputs["width"]), int(inputs["height"])


def queue_counts(api_url: str) -> tuple[int, int]:
    payload = http_json(f"{api_url.rstrip('/')}/queue")
    return len(payload.get("queue_running", [])), len(payload.get("queue_pending", []))


def require_empty_queue(api_url: str) -> None:
    running, pending = queue_counts(api_url)
    if running or pending:
        raise RuntimeError(
            f"remote queue is not empty: running={running}, pending={pending}"
        )


def record_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def deployment_binding(path: Path) -> dict[str, str]:
    document = load_json_object(path, label="deployment evidence")
    verification = document.get("verification")
    artifact = document.get("artifact")
    manifest = document.get("manifest")
    deployment = document.get("deployment")
    if (
        document.get("schema_version") != 2
        or document.get("deployment_type") != "production"
        or document.get("status") != "passed"
        or document.get("mode") != "apply"
        or document.get("applied") is not True
        or not isinstance(verification, dict)
        or not all(
            verification.get(key) is True
            for key in (
                "checksum_match",
                "exact_krea2_namespace",
                "impact_reload",
                "queue_empty",
            )
        )
        or not isinstance(artifact, dict)
        or not isinstance(manifest, dict)
        or not isinstance(deployment, dict)
    ):
        raise ValueError("deployment evidence is not a passed production apply")
    binding = {
        "deployment_id": document.get("deployment_id"),
        "deployment_nonce": deployment.get("nonce"),
        "artifact_sha256": artifact.get("sha256"),
        "manifest_sha256": manifest.get("sha256"),
        "deployed_at_utc": deployment.get("completed_at_utc"),
    }
    if (
        not isinstance(binding["deployment_id"], str)
        or not binding["deployment_id"]
        or not isinstance(binding["deployment_nonce"], str)
        or len(binding["deployment_nonce"]) != 32
        or any(character not in "0123456789abcdef" for character in binding["deployment_nonce"])
        or any(
            not isinstance(binding[key], str)
            or len(binding[key]) != 64
            or any(character not in "0123456789abcdef" for character in binding[key])
            for key in ("artifact_sha256", "manifest_sha256")
        )
        or not isinstance(binding["deployed_at_utc"], str)
    ):
        raise ValueError("deployment evidence binding is invalid")
    try:
        deployed_at = datetime.fromisoformat(
            binding["deployed_at_utc"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("deployment evidence timestamp is invalid") from exc
    if not binding["deployed_at_utc"].endswith("Z") or deployed_at.tzinfo != timezone.utc:
        raise ValueError("deployment evidence timestamp is invalid")
    return binding


def smoke_run_directory(
    output: Path,
    style_id: str,
    seed: int,
    binding: dict[str, str] | None,
) -> Path:
    name = f"{style_id}_seed_{seed}"
    if binding is not None:
        name += (
            f"_{binding['deployment_id']}_{binding['deployment_nonce'][:12]}"
        )
    return output / "runs" / name


def reusable_smoke_run(
    run_dir: Path,
    *,
    style_id: str,
    seed: int,
    binding: dict[str, str],
) -> bool:
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        return False
    try:
        document = load_json_object(run_path, label="smoke run")
    except (OSError, ValueError):
        return False
    if (
        document.get("style_id") != style_id
        or document.get("seed") != seed
        or document.get("remote") != "private_comfyui"
        or document.get("deployment") != binding
    ):
        return False
    images = document.get("images")
    if not isinstance(images, list) or not images:
        return False
    for raw in images:
        if not isinstance(raw, str) or not raw:
            return False
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts or not path.is_file():
            return False
    return all(
        isinstance(document.get(key), str) and document[key].endswith("Z")
        for key in ("started_at_utc", "completed_at_utc")
    )


def download_images(
    api_url: str,
    record: dict[str, Any],
    output_dir: Path,
    expected_dimensions: tuple[int, int],
) -> list[Path]:
    image_specs = []
    for node_output in record.get("outputs", {}).values():
        image_specs.extend(node_output.get("images", []))
    if not image_specs:
        raise RuntimeError("completed workflow returned no images")
    if len(image_specs) != 1:
        raise RuntimeError(f"expected one image, received {len(image_specs)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, spec in enumerate(image_specs, start=1):
        query = urllib.parse.urlencode(
            {
                "filename": spec["filename"],
                "subfolder": spec.get("subfolder", ""),
                "type": spec.get("type", "output"),
            }
        )
        request = urllib.request.Request(f"{api_url.rstrip('/')}/view?{query}")
        with NO_PROXY_OPENER.open(request, timeout=60) as response:
            image_bytes = response.read()
        dimensions = png_dimensions(image_bytes)
        if dimensions != expected_dimensions:
            raise ValueError(
                f"image dimensions {dimensions} do not match expected {expected_dimensions}"
            )
        path = output_dir / f"image_{index:02d}.png"
        path.write_bytes(image_bytes)
        paths.append(path)
    return paths


def main() -> int:
    args = parse_args()
    try:
        valid_styles = catalog_style_ids(args.catalog)
        if args.style_id not in valid_styles:
            raise ValueError(f"unknown style id: {args.style_id}")
        workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
        dimensions = workflow_dimensions(workflow)
        catalog_path = args.catalog
        prompt = benchmark_prompt(args.template, args.style_id, catalog_path)
        resolved_prompt = resolved_benchmark_prompt(
            args.template, catalog_path, args.style_id
        )
        prepared = prepare_workflow(workflow, prompt, args.style_id, args.seed)
        binding = (
            deployment_binding(args.deployment_evidence)
            if args.deployment_evidence is not None
            else None
        )
        run_dir = smoke_run_directory(
            args.output, args.style_id, args.seed, binding
        )
        if args.submit and run_dir.exists():
            if binding is not None and reusable_smoke_run(
                run_dir,
                style_id=args.style_id,
                seed=args.seed,
                binding=binding,
            ):
                print(
                    "Reusing completed production smoke run: "
                    f"{record_path(run_dir / 'run.json')}"
                )
                return 0
            raise FileExistsError(f"run directory already exists: {record_path(run_dir)}")
        if not args.api_url:
            raise ValueError(
                f"missing remote API URL; set {API_URL_ENV} or pass --api-url"
            )
        validate_remote_nodes(args.api_url, prepared)
        print(
            f"Prepared style={args.style_id} seed={args.seed} "
            f"nodes={len(prepared)} remote=private_comfyui"
        )
        if not args.submit:
            print("DRY RUN complete. Re-run with --submit to queue one image.")
            return 0

        require_empty_queue(args.api_url)
        started_at_utc = utc_timestamp()
        if binding is not None:
            deployed_at = datetime.fromisoformat(
                binding["deployed_at_utc"].replace("Z", "+00:00")
            )
            started_at = datetime.fromisoformat(
                started_at_utc.replace("Z", "+00:00")
            )
            if started_at < deployed_at:
                raise ValueError("production smoke cannot start before deployment")

        client_id = str(uuid.uuid4())
        result = http_json(
            f"{args.api_url.rstrip('/')}/prompt",
            {"prompt": prepared, "client_id": client_id},
        )
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError("remote submission rejected")
        print(f"Queued prompt_id={prompt_id}")
        record = wait_for_result(args.api_url, prompt_id, args.timeout)

        images = download_images(args.api_url, record, run_dir, dimensions)
        run_dir.mkdir(parents=True, exist_ok=True)
        require_empty_queue(args.api_url)
        metadata = {
            "schema_version": 2 if binding is not None else 1,
            "prompt_id": prompt_id,
            "style_id": args.style_id,
            "seed": args.seed,
            "remote": "private_comfyui",
            "catalog": record_path(catalog_path),
            "template": record_path(args.template),
            "wildcard_prompt": prompt,
            "resolved_prompt": resolved_prompt,
            "images": [record_path(path) for path in images],
            "started_at_utc": started_at_utc,
            "completed_at_utc": utc_timestamp(),
        }
        if binding is not None:
            metadata["deployment"] = binding
        (run_dir / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Completed with {len(images)} image(s): {run_dir}")
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        message = str(exc)
        for sensitive in (args.api_url, os.environ.get(API_URL_ENV)):
            if sensitive:
                message = message.replace(str(sensitive), "<REDACTED_REMOTE>")
        print(f"ERROR: {message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
