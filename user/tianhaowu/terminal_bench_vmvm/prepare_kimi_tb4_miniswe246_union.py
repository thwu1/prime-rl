#!/usr/bin/env python3
"""Materialize an opaque 25/38/3 Kimi TB4 MiniSWE provider-union plan.

Its output names the separate certifier adapter that re-opens both runs before publication.
No task member is written to stdout or to the aggregate plan/receipt.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import kimi_tb4_provider_split as split

SCHEMA_VERSION = 1
PLAN_KIND = "kimi-tb4-miniswe246-provider-union-plan"
PARTITION_KIND = "kimi-tb4-miniswe246-provider-union-partition"
CERTIFIER_ADAPTER = "kimi-tb4-miniswe246-provider-union-v1"
SANDOQ_ROLE = "sandoq_firecracker"
VMVM_ROLE = "vmvm_cpu"
GPU_ROLE = "gpu_unsupported"
SANDOQ_TASKS = 25
VMVM_TASKS = 38
GPU_TASKS = 3
CPU_TASKS = SANDOQ_TASKS + VMVM_TASKS
SANDOQ_CPU_LIMIT = 2
SANDOQ_MEMORY_LIMIT_BYTES = 4 * split.GIB
SANDOQ_DISK_LIMIT_BYTES = 10 * split.GIB
DEFAULT_SANDOQ_CONCURRENCY = 24
DEFAULT_VMVM_CONCURRENCY = 4
MINISWE_VERSION = "2.4.6"
VERIFIERS_COMMIT = "dcc2132667c52b2dd02b4c76c96643dd6537e5e0"
PROVIDER_PROFILE_SHA256 = "7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df"
FULL_TUNNEL_RECEIPT_SHA256 = "39108c28f052f4689e863fedaa81430b479915797a4e6836ed090344c5ee3276"
FULL_RESOURCE_RECEIPT_SHA256 = "ce3fc3ed2ead1aaf8c71fc35e5dae324f1be9d51b4e7fffff7bc99d1a47adbf6"
LEGACY_BASE_CONFIG_SHA256 = "de0e1961bf5440c257de8c623698955d80893079a78e7f5e05b9913174b4e9d1"
BASE_CONFIG_SHA256 = "3c3ad8ea3f8001b307bac59f024fd7d8927bef2c6467cffd5b18c9d9d4480e64"
LEGACY_REQUEST_TIMEOUT_SECONDS = 43_200
LEGACY_ROLLOUT_TIMEOUT_SECONDS = 36_000
LEGACY_SESSION_TIMEOUT_SECONDS = 43_200
REQUEST_TIMEOUT_SECONDS = 144_000
ROLLOUT_TIMEOUT_SECONDS = 129_600
SESSION_TIMEOUT_SECONDS = 144_000
LEGACY_TIMEOUT_CONTRACT = {
    "request_seconds": LEGACY_REQUEST_TIMEOUT_SECONDS,
    "rollout_seconds": LEGACY_ROLLOUT_TIMEOUT_SECONDS,
    "session_seconds": LEGACY_SESSION_TIMEOUT_SECONDS,
}
TIMEOUT_CONTRACT = {
    "request_seconds": REQUEST_TIMEOUT_SECONDS,
    "rollout_seconds": ROLLOUT_TIMEOUT_SECONDS,
    "session_seconds": SESSION_TIMEOUT_SECONDS,
}
FULL_TUNNEL_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-full-tunnel-20260922/run-1537377/receipt.json"
)
FULL_RESOURCE_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-full-resource-20260922/run-1537410/receipt.json"
)
SANDOQ_SELECTOR = "sandoq-firecracker.tasks.txt"
VMVM_SELECTOR = "vmvm-cpu.tasks.txt"
GPU_SELECTOR = "gpu-unsupported.tasks.txt"
SANDOQ_CONFIG = "sandoq-firecracker.toml"
VMVM_CONFIG = "vmvm-cpu.toml"
PARTITION_RECEIPT = "partition.json"
LAUNCH_PLAN = "launch-plan.json"
RUN_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class UnionPreparationError(ValueError):
    """A union input failed an aggregate-only, fail-closed contract."""


@dataclass(frozen=True, slots=True)
class UnionPartition:
    sandoq_firecracker: tuple[str, ...]
    vmvm_cpu: tuple[str, ...]
    gpu_unsupported: tuple[str, ...]
    compose_required: tuple[str, ...]


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _base_config_path() -> Path:
    return _workflow_dir() / "configs/eval/servers/cpu-132-021_8103/tb4_kimi_k3_miniswe246_union.extended.base.toml"


def _legacy_base_config_path() -> Path:
    return _workflow_dir() / "configs/eval/servers/cpu-132-021_8103/tb4_kimi_k3_miniswe246_union.base.toml"


def _provider_profile_path() -> Path:
    return _workflow_dir() / "configs/provider_context/use2/kimi_sandoq_firecracker_host.json"


def _read(
    path: Path,
    *,
    code: str,
    maximum_bytes: int = 8 * 1024 * 1024,
    private: bool = False,
) -> bytes:
    try:
        return split.read_regular(
            path,
            code=code,
            maximum_bytes=maximum_bytes,
            private=private,
        )
    except split.KimiProviderSplitError as error:
        raise UnionPreparationError(code) from error


def _json(body: bytes, *, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise UnionPreparationError(code) from error
    if not isinstance(value, dict) or split.canonical_json(value) != body:
        raise UnionPreparationError(code)
    return value


def _artifact(path: Path, body: bytes) -> dict[str, int | str]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _read_artifact(
    record: object,
    *,
    code: str,
    private: bool,
) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise UnionPreparationError(code)
    path = Path(str(record.get("path", "")))
    if not path.is_absolute() or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None:
        raise UnionPreparationError(code)
    body = _read(path, code=code, private=private)
    if record.get("bytes") != len(body) or record.get("sha256") != _sha256(body):
        raise UnionPreparationError(code)
    return path, body


def _fixed_provider_evidence() -> dict[str, dict[str, int | str]]:
    profile_path = _provider_profile_path().resolve(strict=True)
    profile_body = _read(profile_path, code="provider_profile_invalid")
    if _sha256(profile_body) != PROVIDER_PROFILE_SHA256:
        raise UnionPreparationError("provider_profile_invalid")
    profile = _json(profile_body, code="provider_profile_invalid")
    expected_profile = {
        "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "cluster_identifier": "use2",
        "effective_task_network": "public",
        "environment": "oci-runner-firecracker",
        "provider_token_file": "/home/tianhaowu/.config/oci-runner/firecracker-token",
        "runtime_resource_receipt": str(FULL_RESOURCE_RECEIPT),
        "runtime_resource_receipt_sha256": FULL_RESOURCE_RECEIPT_SHA256,
        "runtime_tunnel_receipt": str(FULL_TUNNEL_RECEIPT),
        "runtime_tunnel_receipt_sha256": FULL_TUNNEL_RECEIPT_SHA256,
        "schema_version": 4,
        "task_network": "host",
        "transport_mode": "auto",
    }
    if profile != expected_profile:
        raise UnionPreparationError("provider_profile_invalid")

    tunnel_path = FULL_TUNNEL_RECEIPT.resolve(strict=True)
    tunnel_body = _read(tunnel_path, code="tunnel_receipt_invalid", private=True)
    tunnel = _json(tunnel_body, code="tunnel_receipt_invalid")
    if (
        _sha256(tunnel_body) != FULL_TUNNEL_RECEIPT_SHA256
        or tunnel
        != {
            "cleanup_verified": True,
            "create_session_verified": True,
            "environment": "oci-runner-firecracker",
            "kind": "sandoq-firecracker-tunnel-capability",
            "port_names": ["exec", "tunnel"],
            "schema_version": 1,
            "slurm_job_id": tunnel.get("slurm_job_id"),
            "state": "passed",
            "tunnel_available": True,
        }
        or re.fullmatch(r"[1-9][0-9]*", str(tunnel.get("slurm_job_id", ""))) is None
    ):
        raise UnionPreparationError("tunnel_receipt_invalid")

    resource_path = FULL_RESOURCE_RECEIPT.resolve(strict=True)
    resource_body = _read(resource_path, code="resource_receipt_invalid", private=True)
    resource = _json(resource_body, code="resource_receipt_invalid")
    if (
        _sha256(resource_body) != FULL_RESOURCE_RECEIPT_SHA256
        or set(resource)
        != {
            "command_exit_code",
            "elapsed_seconds",
            "environment",
            "kind",
            "requested_cpu",
            "requested_disk_gb",
            "requested_memory_gb",
            "runtime_stop_completed",
            "sandbox_started",
            "schema_version",
            "slurm_job_id",
            "state",
            "tunnel_roundtrip_verified",
        }
        or resource.get("schema_version") != 1
        or resource.get("kind") != "sandoq-full-resource-tunnel-capability"
        or resource.get("state") != "passed"
        or resource.get("environment") != "oci-runner-firecracker"
        or resource.get("requested_cpu") != 2
        or resource.get("requested_memory_gb") != 4
        or resource.get("requested_disk_gb") != 10
        or resource.get("command_exit_code") != 0
        or resource.get("sandbox_started") is not True
        or resource.get("tunnel_roundtrip_verified") is not True
        or resource.get("runtime_stop_completed") is not True
        or re.fullmatch(r"[1-9][0-9]*", str(resource.get("slurm_job_id", ""))) is None
    ):
        raise UnionPreparationError("resource_receipt_invalid")
    return {
        "provider_profile": _artifact(profile_path, profile_body),
        "full_tunnel_receipt": _artifact(tunnel_path, tunnel_body),
        "full_resource_receipt": _artifact(resource_path, resource_body),
    }


def derive_union_partition(entries: Sequence[split.ManifestEntry]) -> UnionPartition:
    baseline = split.derive_partition(entries)
    sandoq_members = frozenset(
        entry.task_id
        for entry in entries
        if not entry.requires_compose
        and all(
            request.gpu_count == 0
            and request.cpu_count <= SANDOQ_CPU_LIMIT
            and request.memory_bytes <= SANDOQ_MEMORY_LIMIT_BYTES
            and request.disk_bytes <= SANDOQ_DISK_LIMIT_BYTES
            for request in split._phase_requests(entry)
        )
    )
    gpu_members = frozenset(baseline.gpu_unsupported)
    sandoq = tuple(entry.task_id for entry in entries if entry.task_id in sandoq_members)
    vmvm = tuple(
        entry.task_id for entry in entries if entry.task_id not in sandoq_members and entry.task_id not in gpu_members
    )
    gpu = tuple(entry.task_id for entry in entries if entry.task_id in gpu_members)
    groups = (set(sandoq), set(vmvm), set(gpu))
    vmvm_entries = [entry for entry in entries if entry.task_id in groups[1]]
    required_cpu = max(
        request.cpu_count * split.LARGE_RESOURCE_MULTIPLIER
        for entry in vmvm_entries
        for request in split._phase_requests(entry)
    )
    required_memory = max(
        request.memory_bytes * split.LARGE_RESOURCE_MULTIPLIER
        for entry in vmvm_entries
        for request in split._phase_requests(entry)
    )
    required_disk = max(
        request.disk_bytes * split.LARGE_RESOURCE_MULTIPLIER
        for entry in vmvm_entries
        for request in split._phase_requests(entry)
    )
    if (
        (len(sandoq), len(vmvm), len(gpu)) != (SANDOQ_TASKS, VMVM_TASKS, GPU_TASKS)
        or any(groups[left] & groups[right] for left in range(3) for right in range(left + 1, 3))
        or set().union(*groups) != {entry.task_id for entry in entries}
        or not set(baseline.compose_required).issubset(groups[1])
        or required_cpu > split.LARGE_MIN_CPU_COUNT
        or required_memory + max(split.MIN_MEMORY_HEADROOM_BYTES, math.ceil(split.LARGE_MIN_OUTER_MEMORY_BYTES * 0.1))
        > split.LARGE_MIN_OUTER_MEMORY_BYTES
        or required_disk + split.DISK_HEADROOM_BYTES > split.LARGE_MIN_DISK_AVAILABLE_BYTES
    ):
        raise UnionPreparationError("partition_contract_invalid")
    return UnionPartition(sandoq, vmvm, gpu, baseline.compose_required)


def _selector_payload(members: Sequence[str]) -> bytes:
    return split._selector_payload(members)


def _partition_receipt(manifest_sha256: str, partition: UnionPartition) -> dict[str, Any]:
    selectors = {
        SANDOQ_ROLE: _selector_payload(partition.sandoq_firecracker),
        VMVM_ROLE: _selector_payload(partition.vmvm_cpu),
        GPU_ROLE: _selector_payload(partition.gpu_unsupported),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": PARTITION_KIND,
        "state": "materialized",
        "manifest_sha256": manifest_sha256,
        "partition": {
            "total": split.TOTAL_TASKS,
            SANDOQ_ROLE: SANDOQ_TASKS,
            VMVM_ROLE: VMVM_TASKS,
            GPU_ROLE: GPU_TASKS,
            "compose_required_cpu": split.COMPOSE_CPU_TASKS,
            "disjoint": True,
            "exhaustive": True,
            "canonical_order": "manifest-entry-order",
        },
        "selectors": {role: {"bytes": len(body), "sha256": _sha256(body)} for role, body in selectors.items()},
        "policy": {
            SANDOQ_ROLE: {
                "selection": "declared-resource-envelope-v1",
                "max_cpu": SANDOQ_CPU_LIMIT,
                "max_memory_bytes": SANDOQ_MEMORY_LIMIT_BYTES,
                "max_disk_bytes": SANDOQ_DISK_LIMIT_BYTES,
                "resource_multiplier": 1.0,
                "compose_supported": False,
                "environment": "oci-runner-firecracker",
                "task_network": "host",
                "host_tunnel": "sandoq",
                "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
                "runtime_tunnel_receipt_sha256": FULL_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": FULL_RESOURCE_RECEIPT_SHA256,
            },
            VMVM_ROLE: {
                "resource_multiplier": 2.0,
                "compose_supported": True,
                "sandbox_provider": "vmvm",
            },
            GPU_ROLE: "deterministic-unsupported-outcome",
        },
    }


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value == value and value not in {float("inf"), float("-inf")}:
        return repr(value)
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise UnionPreparationError("base_config_invalid")


def _render_toml(value: dict[str, Any]) -> bytes:
    lines = ["# Generated private MiniSWE 2.4.6 TB4 union lane."]

    def emit(table: dict[str, Any], prefix: tuple[str, ...]) -> None:
        if prefix:
            lines.extend(("", "[" + ".".join(prefix) + "]"))
        for key, item in table.items():
            if not isinstance(item, dict):
                lines.append(f"{key} = {_toml_value(item)}")
        for key, item in table.items():
            if isinstance(item, dict):
                emit(item, (*prefix, key))

    emit(value, ())
    body = ("\n".join(lines) + "\n").encode()
    try:
        if tomllib.loads(body.decode()) != value:
            raise UnionPreparationError("generated_config_invalid")
    except tomllib.TOMLDecodeError as error:
        raise UnionPreparationError("generated_config_invalid") from error
    return body


def _timeout_contract(value: dict[str, Any]) -> dict[str, int]:
    client = value.get("client")
    harness = value.get("harness")
    timeouts = value.get("timeout")
    if not isinstance(client, dict) or not isinstance(harness, dict) or not isinstance(timeouts, dict):
        raise UnionPreparationError("base_config_contract_invalid")
    overrides = harness.get("config_overrides")
    if not isinstance(overrides, list):
        raise UnionPreparationError("base_config_contract_invalid")
    for contract in (LEGACY_TIMEOUT_CONTRACT, TIMEOUT_CONTRACT):
        request = contract["request_seconds"]
        rollout = contract["rollout_seconds"]
        if (
            client.get("timeout") == request
            and timeouts
            == {
                "setup": 3_600,
                "rollout": rollout,
                "finalize": 3_600,
                "scoring": 21_600,
            }
            and f"environment.timeout={rollout}" in overrides
            and f"model.model_kwargs.timeout={request}" in overrides
        ):
            return dict(contract)
    raise UnionPreparationError("base_config_contract_invalid")


def _base_config(path: Path) -> tuple[dict[str, Any], bytes]:
    canonical = path.resolve(strict=True)
    accepted = {
        _base_config_path().resolve(strict=True): BASE_CONFIG_SHA256,
        _legacy_base_config_path().resolve(strict=True): LEGACY_BASE_CONFIG_SHA256,
    }
    if canonical not in accepted:
        raise UnionPreparationError("base_config_path_invalid")
    body = _read(canonical, code="base_config_invalid", maximum_bytes=2 * 1024 * 1024)
    if _sha256(body) != accepted[canonical]:
        raise UnionPreparationError("base_config_digest_mismatch")
    try:
        value = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise UnionPreparationError("base_config_invalid") from error
    client = value.get("client") if isinstance(value, dict) else None
    sampling = value.get("sampling") if isinstance(value, dict) else None
    taskset = value.get("taskset") if isinstance(value, dict) else None
    harness = value.get("harness") if isinstance(value, dict) else None
    rollout_retry = value.get("retries", {}).get("rollout") if isinstance(value, dict) else None
    timeout_contract = _timeout_contract(value)
    if (
        value.get("model") != "Kimi-K3"
        or value.get("num_tasks") != split.TOTAL_TASKS
        or value.get("num_rollouts") != 1
        or value.get("max_turns") != 200
        or any(
            value.get(key) != split.MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or value.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or client.get("max_retries") != 0
        or client.get("outbound_body_denylist") != ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"]
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
        or taskset.get("use_declared_images") is not True
        or taskset.get("enable_compose") is not False
        or taskset.get("resource_multiplier") != 1.0
        or taskset.get("verifier_runtime_retries") != 0
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != MINISWE_VERSION
        or harness.get("config_file") != "mini"
        or "runtime" in harness
        or harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
        or "agent.step_limit=200" not in harness.get("config_overrides", ())
        or "model.model_kwargs.parallel_tool_calls=false" not in harness.get("config_overrides", ())
        or not isinstance(rollout_retry, dict)
        or rollout_retry.get("max_retries") != 0
    ):
        raise UnionPreparationError("base_config_contract_invalid")
    if canonical == _base_config_path().resolve(strict=True) and timeout_contract != TIMEOUT_CONTRACT:
        raise UnionPreparationError("base_config_contract_invalid")
    if canonical == _legacy_base_config_path().resolve(strict=True) and timeout_contract != LEGACY_TIMEOUT_CONTRACT:
        raise UnionPreparationError("base_config_contract_invalid")
    return value, body


def _lane_config(
    base: dict[str, Any],
    *,
    role: str,
    selector: Path,
    selector_sha256: str,
    image_manifest: Path,
    dataset_dir: Path,
    concurrency: int,
) -> dict[str, Any]:
    if role not in {SANDOQ_ROLE, VMVM_ROLE}:
        raise UnionPreparationError("lane_role_invalid")
    value = copy.deepcopy(base)
    session_timeout = _timeout_contract(value)["session_seconds"]
    is_sandoq = role == SANDOQ_ROLE
    value["num_tasks"] = SANDOQ_TASKS if is_sandoq else VMVM_TASKS
    value["max_concurrent"] = concurrency
    value["multiplex"] = concurrency
    value["client"]["max_connections"] = concurrency
    value["client"]["max_keepalive_connections"] = concurrency
    taskset = value["taskset"]
    taskset["dataset_dir"] = str(dataset_dir)
    taskset["task_file"] = str(selector)
    taskset["task_file_sha256"] = selector_sha256
    taskset["image_manifest"] = str(image_manifest)
    taskset["enable_compose"] = not is_sandoq
    taskset["resource_multiplier"] = 1.0 if is_sandoq else 2.0
    if is_sandoq:
        value["harness"]["runtime"] = {
            "type": "sandoq",
            "mode": "oci-runner",
            "session_timeout": session_timeout,
            "network_access": True,
            "host_tunnel": "sandoq",
            "buffered_chat_completions": True,
            "guest_tunnel_url": "http://127.0.0.1:8485",
            "tunnel_pool_size": 4,
            "tunnel_ready_timeout": 30,
            "expected_environment": "oci-runner-firecracker",
            "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
        }
    else:
        value["harness"]["runtime"] = {
            "type": "vmvm",
            "session_timeout": session_timeout,
            "tenant_id": "async_2347641",
            "lease_ttl": "60s",
            "max_session_buffer_size": 67_108_864,
        }
    return value


def _provider_neutral_config(value: dict[str, Any]) -> dict[str, Any]:
    neutral = copy.deepcopy(value)
    neutral["num_tasks"] = 0
    neutral["max_concurrent"] = 0
    neutral["multiplex"] = 0
    neutral["client"]["max_connections"] = 0
    neutral["client"]["max_keepalive_connections"] = 0
    neutral["taskset"]["task_file"] = "opaque"
    neutral["taskset"]["task_file_sha256"] = "0" * 64
    neutral["taskset"]["enable_compose"] = "provider-specific"
    neutral["taskset"]["resource_multiplier"] = "provider-specific"
    neutral["harness"]["runtime"] = {"type": "provider-specific"}
    return neutral


def _verify_bundle(directory: Path, files: dict[str, bytes]) -> None:
    expected = split._committed_bundle_files(files)
    try:
        root = directory.resolve(strict=True)
        metadata = directory.lstat()
        names = {entry.name for entry in os.scandir(root)}
    except OSError as error:
        raise UnionPreparationError("union_bundle_invalid") from error
    if (
        root != directory
        or directory.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or names != set(expected)
    ):
        raise UnionPreparationError("union_bundle_invalid")
    for name, body in expected.items():
        if _read(root / name, code="union_bundle_invalid", private=True) != body:
            raise UnionPreparationError("union_bundle_invalid")


def _plan_value(
    *,
    output: Path,
    eval_root: Path,
    run_label: str,
    manifest: Path,
    manifest_body: bytes,
    image_manifest: Path,
    image_manifest_body: bytes,
    base_config: Path,
    base_body: bytes,
    provider_evidence: dict[str, dict[str, int | str]],
    partition: UnionPartition,
    receipt_body: bytes,
    sandoq_config_body: bytes,
    vmvm_config_body: bytes,
    timeout_contract: dict[str, int],
    sandoq_concurrency: int,
    vmvm_concurrency: int,
) -> dict[str, Any]:
    selectors = {
        SANDOQ_ROLE: _selector_payload(partition.sandoq_firecracker),
        VMVM_ROLE: _selector_payload(partition.vmvm_cpu),
        GPU_ROLE: _selector_payload(partition.gpu_unsupported),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "state": "materialized",
        "evaluation": {
            "denominator": split.TOTAL_TASKS,
            "pass_at_1": True,
            "all_sandoq_allowed": False,
            "certification_eligible": True,
            "blocked_on": [],
            "required_certifier_adapter": CERTIFIER_ADAPTER,
            "legacy_31_32_certificates_accepted": False,
        },
        "source": {
            "manifest": _artifact(manifest, manifest_body),
            "image_manifest": _artifact(image_manifest, image_manifest_body),
            "base_config": _artifact(base_config, base_body),
            "partition_receipt": _artifact(output / PARTITION_RECEIPT, receipt_body),
            **provider_evidence,
        },
        "contracts": {
            "model": "Kimi-K3",
            "harness": {"id": "mini-swe-agent", "version": MINISWE_VERSION},
            "verifiers_commit": VERIFIERS_COMMIT,
            "context_tokens": split.MAX_SEQUENCE_TOKENS,
            "generation_tokens": split.SAMPLING_MAX_TOKENS,
            "timeouts": dict(timeout_contract),
            "reasoning_required": True,
            "exact_provider_json_required": True,
            "request_graph_match_required": True,
        },
        "lanes": {
            SANDOQ_ROLE: {
                "provider": "sandoq",
                "count": SANDOQ_TASKS,
                "concurrency": sandoq_concurrency,
                "resource_multiplier": 1.0,
                "selector": _artifact(output / SANDOQ_SELECTOR, selectors[SANDOQ_ROLE]),
                "config": _artifact(output / SANDOQ_CONFIG, sandoq_config_body),
                "output_dir": str(eval_root / f"tb4-kimi-{run_label}-miniswe246-sandoq-firecracker"),
            },
            VMVM_ROLE: {
                "provider": "vmvm",
                "count": VMVM_TASKS,
                "concurrency": vmvm_concurrency,
                "resource_multiplier": 2.0,
                "selector": _artifact(output / VMVM_SELECTOR, selectors[VMVM_ROLE]),
                "config": _artifact(output / VMVM_CONFIG, vmvm_config_body),
                "output_dir": str(eval_root / f"tb4-kimi-{run_label}-miniswe246-vmvm-cpu"),
            },
            GPU_ROLE: {
                "provider": "unsupported",
                "count": GPU_TASKS,
                "selector_sha256": _sha256(selectors[GPU_ROLE]),
            },
        },
    }


def materialize(
    *,
    manifest: Path,
    manifest_sha256: str,
    image_manifest: Path,
    dataset_dir: Path,
    base_config: Path,
    output: Path,
    eval_root: Path,
    run_label: str,
    sandoq_concurrency: int = DEFAULT_SANDOQ_CONCURRENCY,
    vmvm_concurrency: int = DEFAULT_VMVM_CONCURRENCY,
) -> dict[str, Any]:
    if (
        RUN_LABEL_RE.fullmatch(run_label or "") is None
        or not 1 <= sandoq_concurrency <= SANDOQ_TASKS
        or not 1 <= vmvm_concurrency <= VMVM_TASKS
    ):
        raise UnionPreparationError("launch_parameters_invalid")
    manifest_body = _read(manifest, code="resource_manifest_invalid", private=True)
    if SHA256_RE.fullmatch(manifest_sha256 or "") is None or _sha256(manifest_body) != manifest_sha256:
        raise UnionPreparationError("resource_manifest_digest_mismatch")
    try:
        _manifest_value, entries = split.parse_manifest(manifest_body, manifest_sha256)
    except split.KimiProviderSplitError as error:
        raise UnionPreparationError("resource_manifest_invalid") from error
    partition = derive_union_partition(entries)
    image_manifest = image_manifest.resolve(strict=True)
    image_body = _read(image_manifest, code="image_manifest_invalid")
    if _sha256(image_body) != split.CANONICAL_IMAGE_MANIFEST_SHA256:
        raise UnionPreparationError("image_manifest_invalid")
    base, base_body = _base_config(base_config)
    provider_evidence = _fixed_provider_evidence()
    dataset_dir = dataset_dir.resolve(strict=True)
    eval_root = eval_root.resolve(strict=True)
    output = Path(os.path.abspath(output))
    if (
        not dataset_dir.is_dir()
        or not eval_root.is_dir()
        or output.exists()
        or output.is_symlink()
        or output.parent.resolve(strict=True) != output.parent
    ):
        raise UnionPreparationError("output_or_dataset_invalid")
    receipt = _partition_receipt(manifest_sha256, partition)
    receipt_body = split.canonical_json(receipt)
    sandoq_selector_body = _selector_payload(partition.sandoq_firecracker)
    vmvm_selector_body = _selector_payload(partition.vmvm_cpu)
    gpu_selector_body = _selector_payload(partition.gpu_unsupported)
    sandoq_config = _lane_config(
        base,
        role=SANDOQ_ROLE,
        selector=output / SANDOQ_SELECTOR,
        selector_sha256=_sha256(sandoq_selector_body),
        image_manifest=image_manifest,
        dataset_dir=dataset_dir,
        concurrency=sandoq_concurrency,
    )
    vmvm_config = _lane_config(
        base,
        role=VMVM_ROLE,
        selector=output / VMVM_SELECTOR,
        selector_sha256=_sha256(vmvm_selector_body),
        image_manifest=image_manifest,
        dataset_dir=dataset_dir,
        concurrency=vmvm_concurrency,
    )
    if _provider_neutral_config(sandoq_config) != _provider_neutral_config(vmvm_config):
        raise UnionPreparationError("lane_contract_mismatch")
    sandoq_config_body = _render_toml(sandoq_config)
    vmvm_config_body = _render_toml(vmvm_config)
    plan = _plan_value(
        output=output,
        eval_root=eval_root,
        run_label=run_label,
        manifest=manifest.resolve(strict=True),
        manifest_body=manifest_body,
        image_manifest=image_manifest,
        image_manifest_body=image_body,
        base_config=base_config.resolve(strict=True),
        base_body=base_body,
        provider_evidence=provider_evidence,
        partition=partition,
        receipt_body=receipt_body,
        sandoq_config_body=sandoq_config_body,
        vmvm_config_body=vmvm_config_body,
        timeout_contract=_timeout_contract(base),
        sandoq_concurrency=sandoq_concurrency,
        vmvm_concurrency=vmvm_concurrency,
    )
    files = {
        SANDOQ_SELECTOR: sandoq_selector_body,
        VMVM_SELECTOR: vmvm_selector_body,
        GPU_SELECTOR: gpu_selector_body,
        SANDOQ_CONFIG: sandoq_config_body,
        VMVM_CONFIG: vmvm_config_body,
        PARTITION_RECEIPT: receipt_body,
        LAUNCH_PLAN: split.canonical_json(plan),
    }
    try:
        split._publish_private_bundle(output, files)
    except split.KimiProviderSplitError as error:
        raise UnionPreparationError("union_bundle_publish_failed") from error
    _verify_bundle(output, files)
    return {
        "state": "materialized",
        SANDOQ_ROLE: SANDOQ_TASKS,
        VMVM_ROLE: VMVM_TASKS,
        GPU_ROLE: GPU_TASKS,
        "total": split.TOTAL_TASKS,
        "all_sandoq_allowed": False,
        "certifier_adapter_required": True,
        "plan_sha256": _sha256(files[LAUNCH_PLAN]),
    }


def verify_launch_plan(plan_path: Path, expected_sha256: str, role: str) -> dict[str, str | int]:
    if role not in {SANDOQ_ROLE, VMVM_ROLE}:
        raise UnionPreparationError("lane_role_invalid")
    plan_body = _read(plan_path, code="launch_plan_invalid", private=True)
    if (
        plan_path.name != LAUNCH_PLAN
        or SHA256_RE.fullmatch(expected_sha256 or "") is None
        or _sha256(plan_body) != expected_sha256
    ):
        raise UnionPreparationError("launch_plan_invalid")
    plan = _json(plan_body, code="launch_plan_invalid")
    evaluation = plan.get("evaluation")
    contracts = plan.get("contracts")
    source = plan.get("source")
    lanes = plan.get("lanes")
    base_contracts = {
        "model": "Kimi-K3",
        "harness": {"id": "mini-swe-agent", "version": MINISWE_VERSION},
        "verifiers_commit": VERIFIERS_COMMIT,
        "context_tokens": split.MAX_SEQUENCE_TOKENS,
        "generation_tokens": split.SAMPLING_MAX_TOKENS,
        "reasoning_required": True,
        "exact_provider_json_required": True,
        "request_graph_match_required": True,
    }
    accepted_contracts = [base_contracts]
    for timeout_contract in (LEGACY_TIMEOUT_CONTRACT, TIMEOUT_CONTRACT):
        accepted_contracts.append({**base_contracts, "timeouts": timeout_contract})
    if (
        set(plan) != {"schema_version", "kind", "state", "evaluation", "source", "contracts", "lanes"}
        or plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("kind") != PLAN_KIND
        or plan.get("state") != "materialized"
        or evaluation
        != {
            "denominator": split.TOTAL_TASKS,
            "pass_at_1": True,
            "all_sandoq_allowed": False,
            "certification_eligible": True,
            "blocked_on": [],
            "required_certifier_adapter": CERTIFIER_ADAPTER,
            "legacy_31_32_certificates_accepted": False,
        }
        or contracts not in accepted_contracts
        or not isinstance(source, dict)
        or set(source)
        != {
            "manifest",
            "image_manifest",
            "base_config",
            "partition_receipt",
            "provider_profile",
            "full_tunnel_receipt",
            "full_resource_receipt",
        }
        or not isinstance(lanes, dict)
        or set(lanes) != {SANDOQ_ROLE, VMVM_ROLE, GPU_ROLE}
    ):
        raise UnionPreparationError("launch_plan_contract_invalid")
    manifest_path, manifest_body = _read_artifact(source["manifest"], code="resource_manifest_invalid", private=True)
    manifest_sha256 = _sha256(manifest_body)
    try:
        _manifest_value, entries = split.parse_manifest(manifest_body, manifest_sha256)
    except split.KimiProviderSplitError as error:
        raise UnionPreparationError("resource_manifest_invalid") from error
    partition = derive_union_partition(entries)
    image_path, image_body = _read_artifact(source["image_manifest"], code="image_manifest_invalid", private=False)
    if _sha256(image_body) != split.CANONICAL_IMAGE_MANIFEST_SHA256:
        raise UnionPreparationError("image_manifest_invalid")
    base_path, base_body = _read_artifact(source["base_config"], code="base_config_invalid", private=False)
    base, expected_base_body = _base_config(base_path)
    if base_body != expected_base_body:
        raise UnionPreparationError("base_config_invalid")
    timeout_contract = _timeout_contract(base)
    if (isinstance(contracts, dict) and "timeouts" in contracts and contracts["timeouts"] != timeout_contract) or (
        isinstance(contracts, dict) and "timeouts" not in contracts and timeout_contract != LEGACY_TIMEOUT_CONTRACT
    ):
        raise UnionPreparationError("launch_plan_contract_invalid")
    evidence = _fixed_provider_evidence()
    if any(source[name] != record for name, record in evidence.items()):
        raise UnionPreparationError("provider_evidence_invalid")
    receipt = _partition_receipt(manifest_sha256, partition)
    receipt_body = split.canonical_json(receipt)
    receipt_path, observed_receipt = _read_artifact(
        source["partition_receipt"], code="partition_receipt_invalid", private=True
    )
    if receipt_path != plan_path.parent / PARTITION_RECEIPT or observed_receipt != receipt_body:
        raise UnionPreparationError("partition_receipt_invalid")

    selectors = {
        SANDOQ_ROLE: (SANDOQ_SELECTOR, partition.sandoq_firecracker),
        VMVM_ROLE: (VMVM_SELECTOR, partition.vmvm_cpu),
        GPU_ROLE: (GPU_SELECTOR, partition.gpu_unsupported),
    }
    lane_files: dict[str, bytes] = {
        PARTITION_RECEIPT: receipt_body,
        LAUNCH_PLAN: plan_body,
    }
    lane_configs: dict[str, dict[str, Any]] = {}
    for lane_role in (SANDOQ_ROLE, VMVM_ROLE):
        lane = lanes.get(lane_role)
        expected_count = SANDOQ_TASKS if lane_role == SANDOQ_ROLE else VMVM_TASKS
        expected_provider = "sandoq" if lane_role == SANDOQ_ROLE else "vmvm"
        expected_multiplier = 1.0 if lane_role == SANDOQ_ROLE else 2.0
        expected_config_name = SANDOQ_CONFIG if lane_role == SANDOQ_ROLE else VMVM_CONFIG
        if (
            not isinstance(lane, dict)
            or set(lane)
            != {
                "provider",
                "count",
                "concurrency",
                "resource_multiplier",
                "selector",
                "config",
                "output_dir",
            }
            or lane.get("provider") != expected_provider
            or lane.get("count") != expected_count
            or lane.get("resource_multiplier") != expected_multiplier
            or type(lane.get("concurrency")) is not int
            or not 1 <= lane["concurrency"] <= expected_count
            or not isinstance(lane.get("output_dir"), str)
            or not Path(lane["output_dir"]).is_absolute()
        ):
            raise UnionPreparationError("launch_lane_invalid")
        selector_name, members = selectors[lane_role]
        selector_path, selector_body = _read_artifact(lane["selector"], code="launch_selector_invalid", private=True)
        config_path, config_body = _read_artifact(lane["config"], code="launch_config_invalid", private=True)
        expected_selector = _selector_payload(members)
        if (
            selector_path != plan_path.parent / selector_name
            or selector_body != expected_selector
            or config_path != plan_path.parent / expected_config_name
        ):
            raise UnionPreparationError("launch_lane_invalid")
        try:
            config = tomllib.loads(config_body.decode())
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise UnionPreparationError("launch_config_invalid") from error
        taskset = config.get("taskset")
        if not isinstance(taskset, dict):
            raise UnionPreparationError("launch_config_invalid")
        expected_config = _lane_config(
            base,
            role=lane_role,
            selector=selector_path,
            selector_sha256=_sha256(selector_body),
            image_manifest=image_path,
            dataset_dir=Path(str(taskset.get("dataset_dir", ""))),
            concurrency=lane["concurrency"],
        )
        if config != expected_config:
            raise UnionPreparationError("launch_config_invalid")
        lane_configs[lane_role] = config
        lane_files[selector_name] = selector_body
        lane_files[expected_config_name] = config_body
    gpu_lane = lanes.get(GPU_ROLE)
    gpu_body = _selector_payload(partition.gpu_unsupported)
    if gpu_lane != {
        "provider": "unsupported",
        "count": GPU_TASKS,
        "selector_sha256": _sha256(gpu_body),
    }:
        raise UnionPreparationError("gpu_lane_invalid")
    lane_files[GPU_SELECTOR] = _read(
        plan_path.parent / GPU_SELECTOR,
        code="launch_selector_invalid",
        private=True,
    )
    if lane_files[GPU_SELECTOR] != gpu_body:
        raise UnionPreparationError("gpu_lane_invalid")
    if _provider_neutral_config(lane_configs[SANDOQ_ROLE]) != _provider_neutral_config(lane_configs[VMVM_ROLE]):
        raise UnionPreparationError("lane_contract_mismatch")
    _verify_bundle(plan_path.parent, lane_files)
    selected_lane = lanes[role]
    return {
        "role": role,
        "stage": "tb4-miniswe246-sandoq-union" if role == SANDOQ_ROLE else "tb4-miniswe246-vmvm-union",
        "provider": selected_lane["provider"],
        "config": selected_lane["config"]["path"],
        "config_sha256": selected_lane["config"]["sha256"],
        "selector": selected_lane["selector"]["path"],
        "selector_sha256": selected_lane["selector"]["sha256"],
        "count": selected_lane["count"],
        "concurrency": selected_lane["concurrency"],
        "output_dir": selected_lane["output_dir"],
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "certifier_adapter": CERTIFIER_ADAPTER,
    }


def verify_smoke_selector(
    manifest: Path,
    manifest_sha256: str,
    selector: Path,
    selector_sha256: str,
) -> dict[str, str | int]:
    """Prove an opaque one-task smoke is inside the certified Sandoq envelope."""

    manifest_body = _read(manifest, code="resource_manifest_invalid", private=True)
    selector_body = _read(selector, code="smoke_selector_invalid", private=False)
    if (
        SHA256_RE.fullmatch(manifest_sha256 or "") is None
        or _sha256(manifest_body) != manifest_sha256
        or SHA256_RE.fullmatch(selector_sha256 or "") is None
        or _sha256(selector_body) != selector_sha256
    ):
        raise UnionPreparationError("smoke_selector_invalid")
    try:
        _manifest, entries = split.parse_manifest(manifest_body, manifest_sha256)
        selected = tuple(line for line in selector_body.decode().splitlines() if line)
    except (UnicodeDecodeError, split.KimiProviderSplitError) as error:
        raise UnionPreparationError("smoke_selector_invalid") from error
    partition = derive_union_partition(entries)
    if (
        len(selected) != 1
        or len(set(selected)) != 1
        or selector_body != _selector_payload(selected)
        or selected[0] not in frozenset(partition.sandoq_firecracker)
    ):
        raise UnionPreparationError("smoke_selector_invalid")
    return {
        "state": "passed",
        "count": 1,
        "selector_sha256": selector_sha256,
        "resource_policy": "declared-resource-envelope-v1",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize_parser = commands.add_parser("materialize")
    materialize_parser.add_argument("--manifest", type=Path, required=True)
    materialize_parser.add_argument("--manifest-sha256", required=True)
    materialize_parser.add_argument("--image-manifest", type=Path, required=True)
    materialize_parser.add_argument("--dataset-dir", type=Path, required=True)
    materialize_parser.add_argument("--base-config", type=Path, default=_base_config_path())
    materialize_parser.add_argument("--output", type=Path, required=True)
    materialize_parser.add_argument("--eval-root", type=Path, required=True)
    materialize_parser.add_argument("--run-label", required=True)
    materialize_parser.add_argument(
        "--sandoq-concurrency",
        type=int,
        default=DEFAULT_SANDOQ_CONCURRENCY,
    )
    materialize_parser.add_argument(
        "--vmvm-concurrency",
        type=int,
        default=DEFAULT_VMVM_CONCURRENCY,
    )
    verify = commands.add_parser("verify")
    verify.add_argument("--launch-plan", type=Path, required=True)
    verify.add_argument("--launch-plan-sha256", required=True)
    verify.add_argument("--role", choices=(SANDOQ_ROLE, VMVM_ROLE), required=True)
    verify.add_argument("--format", choices=("json", "tsv"), default="json")
    smoke = commands.add_parser("verify-smoke")
    smoke.add_argument("--manifest", type=Path, required=True)
    smoke.add_argument("--manifest-sha256", required=True)
    smoke.add_argument("--selector", type=Path, required=True)
    smoke.add_argument("--selector-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "materialize":
            result = materialize(
                manifest=args.manifest,
                manifest_sha256=args.manifest_sha256,
                image_manifest=args.image_manifest,
                dataset_dir=args.dataset_dir,
                base_config=args.base_config,
                output=args.output,
                eval_root=args.eval_root,
                run_label=args.run_label,
                sandoq_concurrency=args.sandoq_concurrency,
                vmvm_concurrency=args.vmvm_concurrency,
            )
        elif args.command == "verify":
            result = verify_launch_plan(
                args.launch_plan,
                args.launch_plan_sha256,
                args.role,
            )
        else:
            result = verify_smoke_selector(
                args.manifest,
                args.manifest_sha256,
                args.selector,
                args.selector_sha256,
            )
    except (OSError, RuntimeError, ValueError):
        print("kimi_tb4_miniswe246_union_failed", file=sys.stderr)
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
            "manifest",
            "manifest_sha256",
            "certifier_adapter",
        )
        values = tuple(str(result[field]) for field in fields)
        if any("\t" in value or "\n" in value for value in values):
            print("kimi_tb4_miniswe246_union_failed", file=sys.stderr)
            return 2
        print("\t".join(values))
    else:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
