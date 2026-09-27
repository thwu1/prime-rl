#!/usr/bin/env python3
"""Materialize the private 52+14 Kimi TB4 Firecracker-small diagnostic."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Sequence

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union

SCHEMA_VERSION = 1
KIND = "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic-plan"
STAGE = "tb4-miniswe246-sandoq-small-full"
ADAPTER = "kimi-tb4-miniswe246-sandoq-small-diagnostic-v1"
SUPPORTED_TASKS = 52
COMPOSE_UNSUPPORTED_TASKS = 11
GPU_UNSUPPORTED_TASKS = 3
CONCURRENCY = 24
CPU_CAP = 1
MEMORY_MB_CAP = 2_048
STORAGE_MB_CAP = 10_240
BASE_CONFIG_SHA256 = "aa5737800031e79d560127cc025f5b379396767f46e81eaa0eb4f1dde02a7b08"
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
SMOKE_RECEIPT_SHA256 = "d62cde918a7f153269054d1670ad8af6b77976e20a2b9e2aecb07dd389307029"
DEFAULT_SMOKE_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/"
    "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic/run-1592194/receipt.json"
)
SUPPORTED_SELECTOR = "sandoq-small-supported.tasks.txt"
COMPOSE_SELECTOR = "compose-unsupported.tasks.txt"
GPU_SELECTOR = "gpu-unsupported.tasks.txt"
CONFIG = "sandoq-small-supported.toml"
PLAN = "launch-plan.json"
RUN_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class SmallDiagnosticError(ValueError):
    """A small-Firecracker diagnostic input failed closed."""


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _base_config_path() -> Path:
    return (
        _workflow_dir()
        / "configs/eval/servers/cpu-132-021_8103/"
        "tb4_kimi_k3_miniswe246_sandoq_firecracker_small_full.base.toml"
    )


def _provider_profile_path() -> Path:
    return (
        _workflow_dir()
        / "configs/provider_context/use2/cpu-132-021_8103/"
        "kimi_sandoq_firecracker_small_host.json"
    )


def _read(path: Path, *, code: str, private: bool = False) -> bytes:
    try:
        return split.read_regular(path, code=code, private=private)
    except (OSError, ValueError) as error:
        raise SmallDiagnosticError(code) from error


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _artifact(path: Path, body: bytes) -> dict[str, int | str]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _json(body: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmallDiagnosticError(code) from error
    if not isinstance(value, dict) or split.canonical_json(value) != body:
        raise SmallDiagnosticError(code)
    return value


def _load_base() -> tuple[dict[str, Any], bytes, Path]:
    path = _base_config_path().resolve(strict=True)
    body = _read(path, code="base_config_invalid")
    if _sha256(body) != BASE_CONFIG_SHA256:
        raise SmallDiagnosticError("base_config_invalid")
    try:
        value = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SmallDiagnosticError("base_config_invalid") from error
    client = value.get("client")
    sampling = value.get("sampling")
    taskset = value.get("taskset")
    harness = value.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    timeout = value.get("timeout")
    rollout_retry = value.get("retries", {}).get("rollout")
    if (
        value.get("model") != "Kimi-K3"
        or value.get("num_tasks") != SUPPORTED_TASKS
        or value.get("num_rollouts") != 1
        or value.get("max_concurrent") != CONCURRENCY
        or value.get("multiplex") != CONCURRENCY
        or value.get("max_turns") != 200
        or any(value.get(key) != split.MAX_SEQUENCE_TOKENS for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
        or value.get("retain_traces") is not False
        or value.get("rich") is not False
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or client.get("max_retries") != 0
        or client.get("timeout") != union.REQUEST_TIMEOUT_SECONDS
        or client.get("max_connections") != CONCURRENCY
        or client.get("max_keepalive_connections") != CONCURRENCY
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != split.SAMPLING_MAX_TOKENS
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, dict)
        or taskset.get("dataset_dir") != "__PRIVATE_DATASET__"
        or taskset.get("task_file") != "__PRIVATE_SELECTOR__"
        or taskset.get("task_file_sha256") != "0" * 64
        or taskset.get("image_manifest") != "__PRIVATE_IMAGE_MANIFEST__"
        or taskset.get("image_manifest_sha256") != split.CANONICAL_IMAGE_MANIFEST_SHA256
        or taskset.get("enable_compose") is not False
        or taskset.get("resource_multiplier") != 1.0
        or taskset.get("resource_cpu_cap") != CPU_CAP
        or taskset.get("resource_memory_mb_cap") != MEMORY_MB_CAP
        or taskset.get("resource_storage_mb_cap") != STORAGE_MB_CAP
        or taskset.get("verifier_runtime_retries") != 0
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != union.MINISWE_VERSION
        or harness.get("config_file") != "mini"
        or harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "1"}
        or harness.get("config_overrides")
        != [
            "agent.step_limit=200",
            "environment.environment_class=local",
            "environment.timeout=129600",
            "model.model_kwargs.drop_params=true",
            "model.model_kwargs.timeout=144000",
            "model.model_kwargs.temperature=1.0",
            "model.model_kwargs.top_p=1.0",
            "model.model_kwargs.parallel_tool_calls=false",
        ]
        or runtime
        != {
            "type": "sandoq",
            "mode": "oci-runner",
            "session_timeout": union.SESSION_TIMEOUT_SECONDS,
            "network_access": True,
            "host_tunnel": "sandoq",
            "buffered_chat_completions": True,
            "guest_tunnel_url": "http://127.0.0.1:8485",
            "tunnel_pool_size": 4,
            "tunnel_ready_timeout": 30,
            "provisioning_retries": union.SANDOQ_PROVISIONING_RETRIES,
            "expected_environment": "oci-runner-firecracker-small",
            "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
        }
        or timeout
        != {"setup": 3_600, "rollout": 129_600, "finalize": 3_600, "scoring": 21_600}
        or not isinstance(rollout_retry, dict)
        or rollout_retry.get("max_retries") != 0
    ):
        raise SmallDiagnosticError("base_config_contract_invalid")
    return value, body, path


def _provider_profile() -> tuple[bytes, Path]:
    path = _provider_profile_path().resolve(strict=True)
    body = _read(path, code="provider_profile_invalid")
    if _sha256(body) != PROVIDER_PROFILE_SHA256:
        raise SmallDiagnosticError("provider_profile_invalid")
    value = _json(body, code="provider_profile_invalid")
    if (
        value.get("environment") != "oci-runner-firecracker-small"
        or value.get("effective_task_network") != "public"
        or value.get("task_network") != "host"
        or value.get("transport_mode") != "auto"
    ):
        raise SmallDiagnosticError("provider_profile_invalid")
    return body, path


def _smoke_receipt(path: Path, expected_sha256: str) -> tuple[bytes, Path]:
    canonical = path.resolve(strict=True)
    body = _read(canonical, code="smoke_receipt_invalid", private=True)
    if expected_sha256 != SMOKE_RECEIPT_SHA256 or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("smoke_receipt_invalid")
    value = _json(body, code="smoke_receipt_invalid")
    if (
        value.get("kind") != "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic"
        or value.get("status") != "diagnostic_passed"
        or value.get("sandbox_environment") != "oci-runner-firecracker-small"
        or value.get("harness_version") != union.MINISWE_VERSION
        or value.get("task_count") != 1
        or value.get("model_calls") != 3
        or value.get("sandbox_lifecycle") is not True
        or value.get("shell_execution") is not True
        or value.get("reasoning_content_retained") is not True
        or value.get("cleanup") is not True
        or value.get("sticky_routing") is not True
        or value.get("router_healthy") is not True
    ):
        raise SmallDiagnosticError("smoke_receipt_invalid")
    return body, canonical


def _render_config(
    base: dict[str, Any],
    *,
    selector: Path,
    selector_sha256: str,
    image_manifest: Path,
    dataset_dir: Path,
) -> bytes:
    value = copy.deepcopy(base)
    taskset = value["taskset"]
    taskset["dataset_dir"] = str(dataset_dir)
    taskset["task_file"] = str(selector)
    taskset["task_file_sha256"] = selector_sha256
    taskset["image_manifest"] = str(image_manifest)
    return union._render_toml(value)


def _expected_plan(
    *,
    directory: Path,
    run_output: Path,
    full_output: Path,
    manifest: Path,
    manifest_body: bytes,
    image_manifest: Path,
    image_body: bytes,
    base_path: Path,
    base_body: bytes,
    profile_path: Path,
    profile_body: bytes,
    smoke_path: Path,
    smoke_body: bytes,
    supported_body: bytes,
    compose_body: bytes,
    gpu_body: bytes,
    config_body: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "materialized",
        "evaluation": {
            "denominator": split.TOTAL_TASKS,
            "executed_tasks": SUPPORTED_TASKS,
            "compose_unsupported": COMPOSE_UNSUPPORTED_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "pass_at_1": True,
            "certification_eligible": False,
            "official_comparable": False,
            "result_label": "resource-clamped-firecracker-small-diagnostic",
        },
        "contracts": {
            "model": "Kimi-K3",
            "harness": {"id": "mini-swe-agent", "version": union.MINISWE_VERSION},
            "context_tokens": split.MAX_SEQUENCE_TOKENS,
            "generation_tokens": split.SAMPLING_MAX_TOKENS,
            "max_turns": 200,
            "reasoning_required": True,
            "model_io_response_kind": "normalized_stream_response",
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
            "model_retries": 0,
            "zero_model_resume_attempts": 1,
            "timeouts": dict(union.TIMEOUT_CONTRACT),
            "resource_caps": {"cpu": CPU_CAP, "memory_mb": MEMORY_MB_CAP, "storage_mb": STORAGE_MB_CAP},
        },
        "source": {
            "manifest": _artifact(manifest, manifest_body),
            "image_manifest": _artifact(image_manifest, image_body),
            "base_config": _artifact(base_path, base_body),
            "provider_profile": _artifact(profile_path, profile_body),
            "smoke_receipt": _artifact(smoke_path, smoke_body),
        },
        "lane": {
            "stage": STAGE,
            "provider": "sandoq",
            "environment": "oci-runner-firecracker-small",
            "count": SUPPORTED_TASKS,
            "concurrency": CONCURRENCY,
            "selector": _artifact(directory / SUPPORTED_SELECTOR, supported_body),
            "config": _artifact(directory / CONFIG, config_body),
            "output_dir": str(run_output),
        },
        "unsupported": {
            "compose": _artifact(directory / COMPOSE_SELECTOR, compose_body),
            "gpu": _artifact(directory / GPU_SELECTOR, gpu_body),
        },
        "full_output_dir": str(full_output),
        "required_adapter": ADAPTER,
    }


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_LABEL_RE.fullmatch(args.run_label or "") is None:
        raise SmallDiagnosticError("run_label_invalid")
    manifest = args.manifest.resolve(strict=True)
    manifest_body = _read(manifest, code="resource_manifest_invalid", private=True)
    if SHA256_RE.fullmatch(args.manifest_sha256 or "") is None or _sha256(manifest_body) != args.manifest_sha256:
        raise SmallDiagnosticError("resource_manifest_invalid")
    try:
        _manifest, entries = split.parse_manifest(manifest_body, args.manifest_sha256)
        partition = union.derive_union_partition(entries)
    except (OSError, ValueError) as error:
        raise SmallDiagnosticError("resource_manifest_invalid") from error
    image_manifest = args.image_manifest.resolve(strict=True)
    image_body = _read(image_manifest, code="image_manifest_invalid")
    if _sha256(image_body) != split.CANONICAL_IMAGE_MANIFEST_SHA256:
        raise SmallDiagnosticError("image_manifest_invalid")
    dataset_dir = args.dataset_dir.resolve(strict=True)
    eval_root = args.eval_root.resolve(strict=True)
    if not dataset_dir.is_dir() or not eval_root.is_dir():
        raise SmallDiagnosticError("dataset_or_eval_root_invalid")
    base, base_body, base_path = _load_base()
    profile_body, profile_path = _provider_profile()
    smoke_body, smoke_path = _smoke_receipt(args.smoke_receipt, args.smoke_receipt_sha256)
    directory = Path(os.path.abspath(args.output))
    run_output = eval_root / f"tb4-kimi-{args.run_label}-miniswe246-sandoq-firecracker-small"
    # Publish the denominator-complete view beneath the private run directory.
    # The shared eval root is intentionally not itself mode 0700.
    full_output = run_output / "full-denominator"
    if directory.exists() or directory.is_symlink() or run_output.exists() or full_output.exists():
        raise SmallDiagnosticError("output_not_fresh")
    supported_body = union._selector_payload(partition.sandoq_firecracker)
    compose_body = union._selector_payload(partition.compose_required)
    gpu_body = union._selector_payload(partition.gpu_unsupported)
    if (len(partition.sandoq_firecracker), len(partition.compose_required), len(partition.gpu_unsupported)) != (
        SUPPORTED_TASKS,
        COMPOSE_UNSUPPORTED_TASKS,
        GPU_UNSUPPORTED_TASKS,
    ):
        raise SmallDiagnosticError("partition_invalid")
    config_body = _render_config(
        base,
        selector=directory / SUPPORTED_SELECTOR,
        selector_sha256=_sha256(supported_body),
        image_manifest=image_manifest,
        dataset_dir=dataset_dir,
    )
    plan = _expected_plan(
        directory=directory,
        run_output=run_output,
        full_output=full_output,
        manifest=manifest,
        manifest_body=manifest_body,
        image_manifest=image_manifest,
        image_body=image_body,
        base_path=base_path,
        base_body=base_body,
        profile_path=profile_path,
        profile_body=profile_body,
        smoke_path=smoke_path,
        smoke_body=smoke_body,
        supported_body=supported_body,
        compose_body=compose_body,
        gpu_body=gpu_body,
        config_body=config_body,
    )
    files = {
        SUPPORTED_SELECTOR: supported_body,
        COMPOSE_SELECTOR: compose_body,
        GPU_SELECTOR: gpu_body,
        CONFIG: config_body,
        PLAN: split.canonical_json(plan),
    }
    try:
        split._publish_private_bundle(directory, files)
    except (OSError, ValueError) as error:
        raise SmallDiagnosticError("bundle_publish_failed") from error
    return {
        "state": "materialized",
        "executed_tasks": SUPPORTED_TASKS,
        "unsupported_tasks": COMPOSE_UNSUPPORTED_TASKS + GPU_UNSUPPORTED_TASKS,
        "denominator": split.TOTAL_TASKS,
        "concurrency": CONCURRENCY,
        "certification_eligible": False,
        "plan_sha256": _sha256(files[PLAN]),
    }


def verify(path: Path, expected_sha256: str) -> dict[str, Any]:
    body = _read(path, code="plan_invalid", private=True)
    if path.name != PLAN or SHA256_RE.fullmatch(expected_sha256 or "") is None or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("plan_invalid")
    plan = _json(body, code="plan_invalid")
    if (
        plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("kind") != KIND
        or plan.get("state") != "materialized"
        or plan.get("required_adapter") != ADAPTER
        or plan.get("evaluation")
        != {
            "denominator": split.TOTAL_TASKS,
            "executed_tasks": SUPPORTED_TASKS,
            "compose_unsupported": COMPOSE_UNSUPPORTED_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "pass_at_1": True,
            "certification_eligible": False,
            "official_comparable": False,
            "result_label": "resource-clamped-firecracker-small-diagnostic",
        }
    ):
        raise SmallDiagnosticError("plan_invalid")
    source = plan.get("source")
    lane = plan.get("lane")
    unsupported = plan.get("unsupported")
    if not isinstance(source, dict) or not isinstance(lane, dict) or not isinstance(unsupported, dict):
        raise SmallDiagnosticError("plan_invalid")
    records: dict[str, tuple[Path, bytes]] = {}
    for section, names, private in (
        (source, ("manifest", "smoke_receipt"), True),
        (source, ("image_manifest", "base_config", "provider_profile"), False),
        (lane, ("selector", "config"), True),
        (unsupported, ("compose", "gpu"), True),
    ):
        for name in names:
            record = section.get(name)
            if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
                raise SmallDiagnosticError("plan_invalid")
            artifact_path = Path(str(record["path"]))
            artifact_body = _read(artifact_path, code="plan_artifact_invalid", private=private)
            if _artifact(artifact_path, artifact_body) != record:
                raise SmallDiagnosticError("plan_artifact_invalid")
            records[name] = (artifact_path, artifact_body)
    manifest_path, manifest_body = records["manifest"]
    try:
        _manifest, entries = split.parse_manifest(manifest_body, _sha256(manifest_body))
        partition = union.derive_union_partition(entries)
    except (OSError, ValueError) as error:
        raise SmallDiagnosticError("resource_manifest_invalid") from error
    supported_body = union._selector_payload(partition.sandoq_firecracker)
    compose_body = union._selector_payload(partition.compose_required)
    gpu_body = union._selector_payload(partition.gpu_unsupported)
    if records["selector"][1] != supported_body or records["compose"][1] != compose_body or records["gpu"][1] != gpu_body:
        raise SmallDiagnosticError("partition_invalid")
    base, base_body, base_path = _load_base()
    profile_body, profile_path = _provider_profile()
    smoke_body, smoke_path = _smoke_receipt(records["smoke_receipt"][0], SMOKE_RECEIPT_SHA256)
    image_path, image_body = records["image_manifest"]
    if (
        records["base_config"] != (base_path, base_body)
        or records["provider_profile"] != (profile_path, profile_body)
        or records["smoke_receipt"] != (smoke_path, smoke_body)
        or _sha256(image_body) != split.CANONICAL_IMAGE_MANIFEST_SHA256
    ):
        raise SmallDiagnosticError("plan_source_invalid")
    config_path, config_body = records["config"]
    try:
        config = tomllib.loads(config_body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SmallDiagnosticError("config_invalid") from error
    dataset_dir = Path(str(config.get("taskset", {}).get("dataset_dir", "")))
    expected_config = _render_config(
        base,
        selector=records["selector"][0],
        selector_sha256=_sha256(supported_body),
        image_manifest=image_path,
        dataset_dir=dataset_dir,
    )
    if config_body != expected_config:
        raise SmallDiagnosticError("config_invalid")
    if lane != {
        "stage": STAGE,
        "provider": "sandoq",
        "environment": "oci-runner-firecracker-small",
        "count": SUPPORTED_TASKS,
        "concurrency": CONCURRENCY,
        "selector": _artifact(records["selector"][0], supported_body),
        "config": _artifact(config_path, config_body),
        "output_dir": lane.get("output_dir"),
    } or not Path(str(lane.get("output_dir", ""))).is_absolute():
        raise SmallDiagnosticError("lane_invalid")
    full_output = Path(str(plan.get("full_output_dir", "")))
    if not full_output.is_absolute():
        raise SmallDiagnosticError("full_output_invalid")
    expected_files = {
        SUPPORTED_SELECTOR: supported_body,
        COMPOSE_SELECTOR: compose_body,
        GPU_SELECTOR: gpu_body,
        CONFIG: config_body,
        PLAN: body,
    }
    try:
        union._verify_bundle(path.parent, expected_files)
    except (OSError, ValueError) as error:
        raise SmallDiagnosticError("bundle_invalid") from error
    return {
        "stage": STAGE,
        "provider": "sandoq",
        "config": str(config_path),
        "config_sha256": _sha256(config_body),
        "selector": str(records["selector"][0]),
        "selector_sha256": _sha256(supported_body),
        "count": SUPPORTED_TASKS,
        "concurrency": CONCURRENCY,
        "output_dir": lane["output_dir"],
        "full_output_dir": str(full_output),
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_body),
        "adapter": ADAPTER,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("materialize")
    make.add_argument("--manifest", type=Path, required=True)
    make.add_argument("--manifest-sha256", required=True)
    make.add_argument("--image-manifest", type=Path, required=True)
    make.add_argument("--dataset-dir", type=Path, required=True)
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--eval-root", type=Path, required=True)
    make.add_argument("--run-label", required=True)
    make.add_argument("--smoke-receipt", type=Path, default=DEFAULT_SMOKE_RECEIPT)
    make.add_argument("--smoke-receipt-sha256", default=SMOKE_RECEIPT_SHA256)
    check = commands.add_parser("verify")
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--plan-sha256", required=True)
    check.add_argument("--format", choices=("json", "tsv"), default="json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = materialize(args) if args.command == "materialize" else verify(args.plan, args.plan_sha256)
    except (OSError, RuntimeError, ValueError):
        print("kimi_tb4_sandoq_small_full_failed", file=sys.stderr)
        return 2
    if args.command == "verify" and args.format == "tsv":
        fields = (
            "stage",
            "provider",
            "config",
            "config_sha256",
            "selector",
            "selector_sha256",
            "count",
            "concurrency",
            "output_dir",
            "full_output_dir",
            "manifest",
            "manifest_sha256",
            "adapter",
        )
        values = tuple(str(result[field]) for field in fields)
        if any("\t" in value or "\n" in value for value in values):
            print("kimi_tb4_sandoq_small_full_failed", file=sys.stderr)
            return 2
        print("\t".join(values))
    else:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
