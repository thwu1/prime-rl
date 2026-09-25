#!/usr/bin/env python3
"""Materialize and certify the server-scoped Kimi Sandoq production lane.

All public output is aggregate-only.  Task membership is read only from sealed
private inputs and is never included in a receipt, exception, or CLI message.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import audit_traces
import export_sft as sft
from certify_direct_kimi import _validate_cleanup
from direct_qwen_union_contract import canonical_json, read_regular
from eval_run_identity import load_eval_run_identity
from materialize_qwen_provider_union import (
    CANONICAL_DATASET_REVISION,
    CANONICAL_DATASET_TREE,
    CANONICAL_SOURCE_COUNT,
    CANONICAL_SOURCE_SHA256,
    SANDOQ_COUNT,
    VMVM_COUNT,
    _task_payload,
    derive_partition,
    verify_canonical_dataset,
)
from verifiers.v1.tasksets.harbor_v1.taskset import parse_resources

SCHEMA_VERSION = 1
PROMOTION_SCHEMA_VERSION = 2
LAUNCH_SCHEMA_VERSION = 2
TRACE_SCHEMA_VERSION = 3
MODEL = "Kimi-K3"
DEPLOYMENT_NAMESPACE = "cpu-132-021_8103"
CAPACITY_PROFILE = "sandoq-c64-w2-v1"
PER_WORKER_CAPACITY = 2
MAX_FORWARDED_CAPACITY = 48
ZERO_WORKER_COUNTS_SHA256 = hashlib.sha256((json.dumps([0] * 24, separators=(",", ":")) + "\n").encode()).hexdigest()
ROUTER_IMPLEMENTATION = "direct-kimi-transparent-v2"
SELECTOR_KIND = "kimi-k3-max-sandoq-selector"
CAPACITY_SELECTOR_KIND = "kimi-k3-max-sandoq-capacity-selector"
PROMOTION_KIND = "kimi-k3-max-sandoq-promotion"
LAUNCH_KIND = "kimi-k3-max-sandoq-launch"
TRACE_KIND = "kimi-k3-max-sandoq-traces"
TB4_KIND = "direct-kimi-sandoq-tb4"
CAPACITY_KIND = "direct-kimi-sandoq-capacity"
ROTATION_KIND = "sandoq-auth-rotation"
MAX_CAPACITY = 64
MAX_SEQUENCE_TOKENS = 262_144
MAX_GENERATION_TOKENS = 32_768
PROVIDER_ENVIRONMENT = "oci-runner-firecracker"
PROVIDER_TASK_NETWORK = "host"
PROVIDER_PROFILE_SHA256 = "7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df"
RUNTIME_TUNNEL_RECEIPT_SHA256 = "39108c28f052f4689e863fedaa81430b479915797a4e6836ed090344c5ee3276"
RUNTIME_RESOURCE_RECEIPT_SHA256 = "ce3fc3ed2ead1aaf8c71fc35e5dae324f1be9d51b4e7fffff7bc99d1a47adbf6"
MINISWE_VERSION = "2.4.6"
MINISWE_COMPATIBILITY_KIND = "qwen-miniswe246-sandoq-three-step-smoke"
MINISWE_COMPATIBILITY_ENVIRONMENT = "oci-runner-firecracker-small"
MINISWE_COMPATIBILITY_SHA256 = "cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220"
VERIFIERS_COMMIT = "3df6efa9e9f6bdc8a013df7759a03074aec79111"
EXPECTED_TASK_COUNT = SANDOQ_COUNT
EXPECTED_SOURCE_COUNT = CANONICAL_SOURCE_COUNT
EXPECTED_EXCLUDED_COUNT = VMVM_COUNT
CAPACITY_SELECTOR_COUNT = 64
TEMPLATE_SHA256 = "97140036bb7f1b8b8a21fd488c2c45e16258376bbe46128dff3873e27a37d514"
IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
MEMBER_RE = re.compile(r"[^/\\\x00\r\n\t]+\Z")
MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_RESULTS_ROW_BYTES = 128 * 1024 * 1024
QUALIFIED_CPU_CORES = 2.0
QUALIFIED_MEMORY_GIB = 4.0
QUALIFIED_DISK_GIB = 10.0
FIRECRACKER_PROVIDER_TOKEN_PATH_SHA256 = "19f886485a27dd272af667283ebeb57293a08723782af6c4bc83a05dca6dedc0"
TERMINAL_STATES = frozenset(
    {
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "TIMEOUT",
    }
)


class KimiProductionError(RuntimeError):
    """A fail-closed error represented by a stable aggregate-only code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Artifact:
    path: str
    bytes: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class TraceAudit:
    artifact: Artifact
    traces: int
    error_traces: int
    zero_reward_traces: int
    positive_traces: int
    positive_model_io_turns: int
    positive_sampled_tokens: int


def _production_contracts() -> dict[str, Any]:
    return {
        "capacity_profile": CAPACITY_PROFILE,
        "per_worker_capacity": PER_WORKER_CAPACITY,
        "max_forwarded_capacity": MAX_FORWARDED_CAPACITY,
        "sandbox_environment": PROVIDER_ENVIRONMENT,
        "task_network": PROVIDER_TASK_NETWORK,
        "network_access": True,
        "host_tunnel": "sandoq",
        "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
        "runtime_tunnel_receipt_sha256": RUNTIME_TUNNEL_RECEIPT_SHA256,
        "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
        "harness": {"id": "mini-swe-agent", "version": MINISWE_VERSION},
        "lease_duration": "12h",
        "managed_shell_recovery": "definitive-404-410-single-replay-v1",
        "network_selection": "declared-no-network-tasks-explicit-public-host-tunnel-v1",
        "ecr_rotation_guard_required": True,
        "cleanup_required": True,
        "exact_provider_json_required": True,
    }


def _plain_int(value: object, *, minimum: int = 0, maximum: int | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return False
    return maximum is None or value <= maximum


def _strict_json(body: bytes, code: str, *, canonical: bool = False) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise KimiProductionError(code) from error
    if not isinstance(value, dict) or (canonical and canonical_json(value) != body):
        raise KimiProductionError(code)
    return value


def _stable_artifact(path: Path, code: str, *, private: bool = False) -> tuple[Artifact, bytes]:
    try:
        normalized = Path(os.path.normpath(path))
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except (OSError, RuntimeError) as error:
        raise KimiProductionError(code) from error
    if (
        not path.is_absolute()
        or path != normalized
        or path != resolved
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or (private and stat.S_IMODE(metadata.st_mode) != 0o600)
    ):
        raise KimiProductionError(code)
    try:
        body = read_regular(path, max_bytes=MAX_METADATA_BYTES)
    except (OSError, ValueError) as error:
        raise KimiProductionError(code) from error
    return Artifact(str(path), len(body), hashlib.sha256(body).hexdigest()), body


def _private_root(path: Path) -> Path:
    try:
        normalized = Path(os.path.normpath(path))
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except (OSError, RuntimeError) as error:
        raise KimiProductionError("private_output_root_invalid") from error
    if (
        not path.is_absolute()
        or path != normalized
        or path != resolved
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise KimiProductionError("private_output_root_invalid")
    return resolved


def _publish_bundle(root: Path, outputs: Mapping[Path, bytes]) -> None:
    root = _private_root(root)
    if not outputs:
        raise KimiProductionError("output_bundle_empty")
    names: list[str] = []
    for path in outputs:
        if path.parent != root or path.name in {"", ".", ".."} or path != root / path.name:
            raise KimiProductionError("output_path_invalid")
        names.append(path.name)
    if len(names) != len(set(names)) or any(os.path.lexists(root / name) for name in names):
        raise KimiProductionError("output_namespace_not_fresh")

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    temporary: list[tuple[str, str]] = []
    published: list[str] = []
    try:
        for path, body in outputs.items():
            name = path.name
            temp_name = f".{name}.{os.urandom(16).hex()}"
            handle = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=descriptor,
            )
            try:
                with os.fdopen(handle, "wb", closefd=False) as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(handle)
            temporary.append((name, temp_name))
        for name, temp_name in temporary:
            os.link(temp_name, name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
            published.append(name)
        for _, temp_name in temporary:
            os.unlink(temp_name, dir_fd=descriptor)
        os.fsync(descriptor)
    except BaseException as error:
        for name in published:
            try:
                os.unlink(name, dir_fd=descriptor)
            except OSError:
                pass
        raise KimiProductionError("output_publish_failed") from error
    finally:
        for _, temp_name in temporary:
            try:
                os.unlink(temp_name, dir_fd=descriptor)
            except OSError:
                pass
        os.close(descriptor)


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _canonical_source_path() -> Path:
    return _workflow_dir() / "configs/eval/mobius_valid_tasks_2500.txt"


def _canonical_template_path() -> Path:
    return _workflow_dir() / "configs/eval/servers/cpu-132-021_8103/mobius_kimi_k3_max_sandoq_2499.template.toml"


def _artifact_record(path: Path, code: str, *, private: bool = False) -> dict[str, int | str]:
    artifact, _body = _stable_artifact(path, code, private=private)
    return artifact.as_dict()


def _resource_coverage(dataset: Path, members: Sequence[str]) -> dict[str, Any]:
    if len(members) != EXPECTED_TASK_COUNT or len(set(members)) != EXPECTED_TASK_COUNT:
        raise KimiProductionError("resource_coverage_invalid")
    vector: list[dict[str, Any]] = []
    modes = Counter()
    maxima = {
        "agent": {"cpu_cores": 0.0, "memory_gib": 0.0, "disk_gib": 0.0},
        "verifier": {"cpu_cores": 0.0, "memory_gib": 0.0, "disk_gib": 0.0},
    }
    for member in members:
        metadata_path = dataset / member / "task.toml"
        try:
            raw = tomllib.loads(read_regular(metadata_path, max_bytes=MAX_METADATA_BYTES).decode("utf-8"))
            environment = raw.get("environment", {})
            verifier = raw.get("verifier", {})
            if not isinstance(environment, dict) or not isinstance(verifier, dict):
                raise ValueError("metadata shape")
            verifier_environment = verifier.get("environment")
            mode = verifier.get("environment_mode")
            if mode is None:
                mode = "separate" if verifier_environment is not None else "shared"
            if mode not in {"shared", "separate"}:
                raise ValueError("verifier mode")
            if mode == "separate":
                if not isinstance(verifier_environment, dict):
                    raise ValueError("verifier environment")
                effective_verifier_environment = verifier_environment
            else:
                effective_verifier_environment = environment
            resources = {
                "agent": parse_resources(environment, 1.0),
                "verifier": parse_resources(effective_verifier_environment, 1.0),
            }
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError) as error:
            raise KimiProductionError("resource_coverage_invalid") from error
        record: dict[str, Any] = {"verifier_mode": mode}
        for role, request in resources.items():
            values = (request.cpu, request.memory, request.disk)
            if (
                request.gpu is not None
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values)
                or any(not math.isfinite(float(value)) or float(value) <= 0 for value in values)
                or float(request.cpu) > QUALIFIED_CPU_CORES
                or float(request.memory) > QUALIFIED_MEMORY_GIB
                or float(request.disk) > QUALIFIED_DISK_GIB
            ):
                raise KimiProductionError("resource_coverage_invalid")
            normalized = {
                "cpu_cores": float(request.cpu),
                "memory_gib": float(request.memory),
                "disk_gib": float(request.disk),
                "gpu_count": 0,
            }
            record[role] = normalized
            for key in ("cpu_cores", "memory_gib", "disk_gib"):
                maxima[role][key] = max(maxima[role][key], normalized[key])
        modes[mode] += 1
        vector.append(record)
    if modes != Counter({"shared": EXPECTED_TASK_COUNT}):
        raise KimiProductionError("resource_coverage_invalid")
    return {
        "schema_version": 1,
        "kind": "declared-resource-envelope-v1",
        "selected_count": EXPECTED_TASK_COUNT,
        "verifier_modes": {"shared": EXPECTED_TASK_COUNT, "separate": 0},
        "agent_maximum": maxima["agent"],
        "verifier_maximum": maxima["verifier"],
        "qualified_request": {
            "cpu_cores": QUALIFIED_CPU_CORES,
            "memory_gib": QUALIFIED_MEMORY_GIB,
            "disk_gib": QUALIFIED_DISK_GIB,
            "gpu_count": 0,
        },
        "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
        "all_selected_within_qualified_request": True,
        "resource_vector_sha256": hashlib.sha256(canonical_json(vector)).hexdigest(),
        "membership_disclosed": False,
    }


def _selector_receipt(selector_body: bytes, resource_coverage: Mapping[str, Any]) -> dict[str, Any]:
    selection = {
        "all_source_tasks_declared_no_network": True,
        "compose_detection": "harbor-compose-precedence-v1",
        "excluded_count": EXPECTED_EXCLUDED_COUNT,
        "membership_disclosed": False,
        "order": "approved-source-order",
        "selected_count": EXPECTED_TASK_COUNT,
        "selected_sha256": hashlib.sha256(selector_body).hexdigest(),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SELECTOR_KIND,
        "state": "materialized",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "approved_source": {
            "count": EXPECTED_SOURCE_COUNT,
            "sha256": CANONICAL_SOURCE_SHA256,
        },
        "dataset": {
            "revision": CANONICAL_DATASET_REVISION,
            "tree": CANONICAL_DATASET_TREE,
        },
        "selection": selection,
        "selection_contract_sha256": hashlib.sha256(canonical_json(selection)).hexdigest(),
        "resource_coverage": dict(resource_coverage),
        "resource_coverage_sha256": hashlib.sha256(canonical_json(resource_coverage)).hexdigest(),
    }


def _opaque_capacity_members(members: Sequence[str]) -> tuple[str, ...]:
    if len(members) != EXPECTED_TASK_COUNT or len(set(members)) != EXPECTED_TASK_COUNT:
        raise KimiProductionError("opaque_capacity_selection_invalid")
    ranked = sorted(
        range(len(members)),
        key=lambda index: hashlib.sha256(f"kimi-c64-capacity-v1:{index}".encode()).digest(),
    )[:CAPACITY_SELECTOR_COUNT]
    return tuple(members[index] for index in sorted(ranked))


def materialize_capacity_selector(
    *,
    source: Path,
    dataset: Path,
    selector: Path,
    receipt: Path,
    private_output_root: Path,
) -> dict[str, Any]:
    root = _private_root(private_output_root)
    try:
        if source.resolve(strict=True) != _canonical_source_path():
            raise KimiProductionError("approved_source_path_invalid")
        source_body = read_regular(source)
        if hashlib.sha256(source_body).hexdigest() != CANONICAL_SOURCE_SHA256:
            raise KimiProductionError("approved_source_invalid")
        partition = derive_partition(source_body, verify_canonical_dataset(dataset))
    except KimiProductionError:
        raise
    except Exception as error:
        raise KimiProductionError("opaque_capacity_selection_invalid") from error
    if partition.no_network_count != EXPECTED_SOURCE_COUNT or len(partition.sandoq) != EXPECTED_TASK_COUNT:
        raise KimiProductionError("opaque_capacity_selection_invalid")
    selected = _opaque_capacity_members(partition.sandoq)
    selector_body = _task_payload(selected)
    selection = {
        "algorithm": "sha256-canonical-index-v1",
        "candidate_count": EXPECTED_TASK_COUNT,
        "membership_disclosed": False,
        "selected_count": CAPACITY_SELECTOR_COUNT,
        "selected_sha256": hashlib.sha256(selector_body).hexdigest(),
    }
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": CAPACITY_SELECTOR_KIND,
        "state": "materialized",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "approved_source": {"count": EXPECTED_SOURCE_COUNT, "sha256": CANONICAL_SOURCE_SHA256},
        "dataset": {"revision": CANONICAL_DATASET_REVISION, "tree": CANONICAL_DATASET_TREE},
        "selection": selection,
        "selection_contract_sha256": hashlib.sha256(canonical_json(selection)).hexdigest(),
    }
    _publish_bundle(root, {selector: selector_body, receipt: canonical_json(value)})
    return {
        "state": "materialized",
        "candidate_count": EXPECTED_TASK_COUNT,
        "selected_count": CAPACITY_SELECTOR_COUNT,
        "selector_sha256": selection["selected_sha256"],
    }


def materialize_selector(
    *,
    source: Path,
    dataset: Path,
    selector: Path,
    receipt: Path,
    private_output_root: Path,
) -> dict[str, Any]:
    root = _private_root(private_output_root)
    try:
        if source.resolve(strict=True) != _canonical_source_path():
            raise KimiProductionError("approved_source_path_invalid")
        source_body = read_regular(source)
    except (OSError, ValueError) as error:
        if isinstance(error, KimiProductionError):
            raise
        raise KimiProductionError("approved_source_invalid") from error
    if hashlib.sha256(source_body).hexdigest() != CANONICAL_SOURCE_SHA256:
        raise KimiProductionError("approved_source_invalid")
    try:
        dataset = verify_canonical_dataset(dataset)
        partition = derive_partition(source_body, dataset)
    except Exception as error:
        raise KimiProductionError("opaque_selection_invalid") from error
    if (
        partition.no_network_count != EXPECTED_SOURCE_COUNT
        or len(partition.sandoq) != EXPECTED_TASK_COUNT
        or len(partition.vmvm) != EXPECTED_EXCLUDED_COUNT
    ):
        raise KimiProductionError("opaque_selection_invalid")
    selector_body = _task_payload(partition.sandoq)
    value = _selector_receipt(selector_body, _resource_coverage(dataset, partition.sandoq))
    _publish_bundle(root, {selector: selector_body, receipt: canonical_json(value)})
    return {
        "state": "materialized",
        "approved_count": EXPECTED_SOURCE_COUNT,
        "selected_count": EXPECTED_TASK_COUNT,
        "excluded_count": EXPECTED_EXCLUDED_COUNT,
        "selector_sha256": value["selection"]["selected_sha256"],
    }


def validate_selector(
    *,
    source: Path,
    dataset: Path,
    selector: Path,
    receipt: Path,
    receipt_sha256: str,
) -> tuple[dict[str, Any], Artifact]:
    source_artifact, source_body = _stable_artifact(source, "approved_source_invalid")
    if source.resolve(strict=True) != _canonical_source_path() or source_artifact.sha256 != CANONICAL_SOURCE_SHA256:
        raise KimiProductionError("approved_source_invalid")
    try:
        dataset = verify_canonical_dataset(dataset)
        partition = derive_partition(source_body, dataset)
    except Exception as error:
        raise KimiProductionError("opaque_selection_invalid") from error
    expected_body = _task_payload(partition.sandoq)
    selector_artifact, selector_body = _stable_artifact(selector, "selector_invalid", private=True)
    receipt_artifact, receipt_body = _stable_artifact(receipt, "selector_receipt_invalid", private=True)
    expected_receipt = _selector_receipt(expected_body, _resource_coverage(dataset, partition.sandoq))
    if (
        receipt_artifact.sha256 != receipt_sha256
        or selector_body != expected_body
        or receipt_body != canonical_json(expected_receipt)
        or selector_artifact.sha256 != expected_receipt["selection"]["selected_sha256"]
    ):
        raise KimiProductionError("selector_receipt_invalid")
    return expected_receipt, selector_artifact


def _replace_once(text: str, old: str, new: str, code: str) -> str:
    if text.count(old) != 1:
        raise KimiProductionError(code)
    return text.replace(old, new)


def materialize_config(template_body: bytes, selector: Path, selector_sha256: str, concurrency: int) -> bytes:
    if hashlib.sha256(template_body).hexdigest() != TEMPLATE_SHA256:
        raise KimiProductionError("config_template_invalid")
    if not _plain_int(concurrency, minimum=1, maximum=MAX_CAPACITY):
        raise KimiProductionError("requested_concurrency_invalid")
    try:
        text = template_body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise KimiProductionError("config_template_invalid") from error
    replacements = (
        ("max_concurrent = 1", f"max_concurrent = {concurrency}"),
        ("multiplex = 1", f"multiplex = {concurrency}"),
        ("max_connections = 1", f"max_connections = {concurrency}"),
        ("max_keepalive_connections = 1", f"max_keepalive_connections = {concurrency}"),
        ('task_file = "__KIMI_SANDOQ_OPAQUE_SELECTOR__"', f"task_file = {json.dumps(str(selector))}"),
        (
            'task_file_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"',
            f'task_file_sha256 = "{selector_sha256}"',
        ),
    )
    for old, new in replacements:
        text = _replace_once(text, old, new, "config_template_shape_invalid")
    body = text.encode("utf-8")
    _validate_config(body, selector=selector, selector_sha256=selector_sha256, concurrency=concurrency)
    return body


def _validate_config(body: bytes, *, selector: Path, selector_sha256: str, concurrency: int) -> dict[str, Any]:
    try:
        config = tomllib.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise KimiProductionError("resolved_config_invalid") from error
    client = config.get("client")
    sampling = config.get("sampling")
    taskset = config.get("taskset")
    harness = config.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    timeouts = config.get("timeout")
    retries = config.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
    if (
        config.get("model") != MODEL
        or config.get("num_tasks") != EXPECTED_TASK_COUNT
        or config.get("num_rollouts") != 1
        or config.get("max_concurrent") != concurrency
        or config.get("multiplex") != concurrency
        or config.get("max_turns") != 200
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or config.get("rich") is not False
        or config.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("timeout") != 43_200
        or client.get("connect_timeout") != 120
        or client.get("max_connections") != concurrency
        or client.get("max_keepalive_connections") != concurrency
        or client.get("max_retries") != 0
        or set(client.get("outbound_body_denylist", ()))
        != {"logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"}
        or not isinstance(sampling, dict)
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("max_tokens") != MAX_GENERATION_TOKENS
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, dict)
        or taskset.get("dataset_revision") != CANONICAL_DATASET_REVISION
        or taskset.get("task_file") != str(selector)
        or taskset.get("task_file_sha256") != selector_sha256
        or taskset.get("image_manifest_sha256") != IMAGE_MANIFEST_SHA256
        or taskset.get("enable_compose") is not False
        or taskset.get("verifier_runtime_retries") != 0
        or taskset.get("resource_multiplier") != 1.0
        or taskset.get("oracle_solution_network_mode") != "declared"
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != "2.4.6"
        or harness.get("config_file") != "mini"
        or harness.get("config_overrides")
        != [
            "agent.step_limit=200",
            "environment.environment_class=local",
            "environment.timeout=36000",
            "model.model_kwargs.drop_params=true",
            "model.model_kwargs.timeout=43200",
            "model.model_kwargs.temperature=1.0",
            "model.model_kwargs.top_p=1.0",
            "model.model_kwargs.parallel_tool_calls=false",
        ]
        or harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
        or not isinstance(runtime, dict)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("session_timeout") != 43_200
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("buffered_chat_completions") is not True
        or runtime.get("guest_tunnel_url") != "http://127.0.0.1:8485"
        or runtime.get("tunnel_pool_size") != 4
        or runtime.get("tunnel_ready_timeout") != 30
        or runtime.get("expected_environment") != PROVIDER_ENVIRONMENT
        or timeouts != {"setup": 3_600, "rollout": 36_000, "finalize": 3_600, "scoring": 21_600}
        or not isinstance(rollout_retries, dict)
        or rollout_retries.get("max_retries") != 0
    ):
        raise KimiProductionError("resolved_config_contract_invalid")
    return config


def _json_artifact(
    path: Path, expected_sha256: str, code: str, *, private: bool = False
) -> tuple[dict[str, Any], Artifact]:
    if SHA256_RE.fullmatch(expected_sha256 or "") is None:
        raise KimiProductionError(code)
    artifact, body = _stable_artifact(path, code, private=private)
    if artifact.sha256 != expected_sha256:
        raise KimiProductionError(code)
    return _strict_json(body, code), artifact


def _validate_recovery_receipt(
    path: Path,
    expected_sha256: str,
    *,
    mode: str,
) -> Artifact:
    value, artifact = _json_artifact(path, expected_sha256, "recovery_receipt_invalid", private=True)
    expected_keys = {
        "schema_version",
        "state",
        "probe_kind",
        "mode",
        "idle_seconds",
        "lease_profile",
        "lease_duration",
        "renewal_interval",
        "recovery_policy",
        "provider_environment",
        "task_network",
        "network_access",
        "host_tunnel",
        "provider_token_file_path_sha256",
        "provider_profile_sha256",
        "runtime_tunnel_receipt_sha256",
        "runtime_resource_receipt_sha256",
        "miniswe_compatibility_receipt_sha256",
        "provider_context_contract_sha256",
        "outer_cleanup_verified",
        "duration_seconds",
        "shell_replaced",
        "managed_shell_recovery_count",
        "state_preserved",
    }
    duration = value.get("duration_seconds")
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 4
        or value.get("state") != "passed"
        or value.get("probe_kind") != "task-free-managed-shell-recovery"
        or value.get("mode") != mode
        or value.get("idle_seconds") != (0 if mode == "forced-delete" else value.get("idle_seconds"))
        or (mode == "idle-endurance" and not _plain_int(value.get("idle_seconds"), minimum=3_900))
        or value.get("lease_profile") != "kimi-tb4-long"
        or value.get("lease_duration") != "12h"
        or value.get("renewal_interval") != "5m"
        or value.get("recovery_policy") != "definitive-404-410-single-replay-v1"
        or value.get("provider_environment") != PROVIDER_ENVIRONMENT
        or value.get("task_network") != PROVIDER_TASK_NETWORK
        or value.get("network_access") is not True
        or value.get("host_tunnel") != "sandoq"
        or value.get("provider_token_file_path_sha256") != FIRECRACKER_PROVIDER_TOKEN_PATH_SHA256
        or value.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or value.get("runtime_tunnel_receipt_sha256") != RUNTIME_TUNNEL_RECEIPT_SHA256
        or value.get("runtime_resource_receipt_sha256") != RUNTIME_RESOURCE_RECEIPT_SHA256
        or value.get("miniswe_compatibility_receipt_sha256") != MINISWE_COMPATIBILITY_SHA256
        or SHA256_RE.fullmatch(str(value.get("provider_context_contract_sha256", ""))) is None
        or value.get("outer_cleanup_verified") is not True
        or value.get("shell_replaced") is not True
        or value.get("managed_shell_recovery_count") != 1
        or value.get("state_preserved") is not True
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or duration <= 0
    ):
        raise KimiProductionError("recovery_receipt_invalid")
    return artifact


def _validate_miniswe_compatibility_receipt(path: Path, expected_sha256: str) -> Artifact:
    if expected_sha256 != MINISWE_COMPATIBILITY_SHA256:
        raise KimiProductionError("miniswe_compatibility_receipt_invalid")
    value, artifact = _json_artifact(
        path,
        expected_sha256,
        "miniswe_compatibility_receipt_invalid",
        private=True,
    )
    trajectory = value.get("trajectory_audit")
    relay = value.get("relay_audit")
    model_calls = value.get("model_calls")
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "model",
        "sandbox_environment",
        "task_network",
        "model_calls",
        "prior_reasoning_forwarded_calls",
        "tool_result_forwarded_calls",
        "program_exit_code",
        "cleanup_verified",
        "elapsed_seconds",
        "selected_task_sha256",
        "task_identity_sha256",
        "raw_trace_sha256",
        "relay_audit",
        "trajectory_audit",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("kind") != MINISWE_COMPATIBILITY_KIND
        or value.get("state") != "passed"
        or value.get("model") != "Qwen3.8-2.4T-A95B"
        or value.get("sandbox_environment") != MINISWE_COMPATIBILITY_ENVIRONMENT
        or value.get("task_network") != PROVIDER_TASK_NETWORK
        or not _plain_int(model_calls, minimum=1, maximum=3)
        or value.get("prior_reasoning_forwarded_calls") != model_calls - 1
        or value.get("tool_result_forwarded_calls") != model_calls - 1
        or value.get("program_exit_code") != 0
        or value.get("cleanup_verified") is not True
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in ("selected_task_sha256", "task_identity_sha256", "raw_trace_sha256")
        )
        or not isinstance(relay, list)
        or len(relay) != model_calls
        or not isinstance(trajectory, dict)
        or trajectory.get("mini_version") != MINISWE_VERSION
        or trajectory.get("exit_status") != "Submitted"
        or trajectory.get("native_submit_marker_actions") != 1
        or trajectory.get("assistant_reasoning_messages") != model_calls
        or trajectory.get("api_calls") != model_calls
        or not _plain_int(trajectory.get("tool_observations"), minimum=1, maximum=3)
    ):
        raise KimiProductionError("miniswe_compatibility_receipt_invalid")
    for index, observation in enumerate(relay, start=1):
        if (
            not isinstance(observation, dict)
            or observation.get("call") != index
            or observation.get("status_code") != 200
            or observation.get("response_reasoning_field") != "reasoning_content"
            or observation.get("response_reasoning_present") is not True
            or observation.get("response_tool_calls") != 1
            or observation.get("request_prior_reasoning_messages") != index - 1
            or observation.get("request_tool_results") != index - 1
        ):
            raise KimiProductionError("miniswe_compatibility_receipt_invalid")
    return artifact


def _validate_provider_context_snapshot(path: Path) -> Artifact:
    artifact, body = _stable_artifact(path, "provider_context_snapshot_invalid", private=True)
    value = _strict_json(body, "provider_context_snapshot_invalid", canonical=True)
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "provider_environment",
            "effective_task_network",
            "task_network",
            "network_access",
            "allow_dockerhub_fallback",
            "provider_profile_sha256",
            "provider_token_file_path_sha256",
            "runtime_tunnel_receipt_sha256",
            "runtime_resource_receipt_sha256",
            "provider_context_contract_sha256",
        }
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-provider-context-snapshot"
        or value.get("state") != "validated"
        or value.get("provider_environment") != PROVIDER_ENVIRONMENT
        or value.get("effective_task_network") != "public"
        or value.get("task_network") != PROVIDER_TASK_NETWORK
        or value.get("network_access") is not True
        or value.get("allow_dockerhub_fallback") is not False
        or value.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or value.get("provider_token_file_path_sha256") != FIRECRACKER_PROVIDER_TOKEN_PATH_SHA256
        or value.get("runtime_tunnel_receipt_sha256") != RUNTIME_TUNNEL_RECEIPT_SHA256
        or value.get("runtime_resource_receipt_sha256") != RUNTIME_RESOURCE_RECEIPT_SHA256
        or SHA256_RE.fullmatch(str(value.get("provider_context_contract_sha256", ""))) is None
    ):
        raise KimiProductionError("provider_context_snapshot_invalid")
    return artifact


def _validate_tb4_miniswe_union_certificate(
    value: dict[str, Any],
    artifact: Artifact,
) -> tuple[dict[str, Any], Artifact]:
    unsigned = dict(value)
    claimed = unsigned.pop("tb4_certificate_sha256", None)
    counts = value.get("counts")
    scores = value.get("scores")
    policy = value.get("policy")
    providers = value.get("providers")
    trace = value.get("trace_audit")
    artifacts = value.get("artifacts")
    expected_partition = {
        "sandoq_firecracker": 25,
        "vmvm_cpu": 38,
        "gpu_unsupported": 3,
    }
    base_policy = {
        "expected_tasks": 66,
        "expected_supported_tasks": 63,
        "rollouts_per_task": 1,
        "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        "min_supported_pass_rate": 7 / 63,
        "max_supported_pass_rate": 0.22,
        "provider_partition": expected_partition,
        "harness": {"id": "mini-swe-agent", "version": MINISWE_VERSION},
        "tool_exit_evidence_required": True,
    }
    accepted_policies = [base_policy]
    for timeouts in (
        {"request_seconds": 43_200, "rollout_seconds": 36_000, "session_seconds": 43_200},
        {"request_seconds": 144_000, "rollout_seconds": 129_600, "session_seconds": 144_000},
    ):
        accepted_policies.append({**base_policy, "timeouts": timeouts})
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "model",
            "adapter",
            "launch_plan_sha256",
            "manifest_sha256",
            "results_sha256",
            "deployment",
            "counts",
            "scores",
            "policy",
            "providers",
            "trace_audit",
            "artifacts",
            "implementation_sha256",
            "tb4_certificate_sha256",
        }
        or value.get("schema_version") != 2
        or value.get("kind") != TB4_KIND
        or value.get("state") != "passed"
        or value.get("model") != MODEL
        or value.get("adapter") != "kimi-tb4-miniswe246-provider-union-v1"
        or claimed != hashlib.sha256(canonical_json(unsigned)).hexdigest()
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in ("launch_plan_sha256", "manifest_sha256", "results_sha256", "implementation_sha256")
        )
        or not isinstance(value.get("deployment"), dict)
        or set(value["deployment"]) != {"endpoint_bundle_sha256", "source_spec_sha256", "worker_generation_sha256"}
        or any(SHA256_RE.fullmatch(str(value["deployment"].get(key, ""))) is None for key in value["deployment"])
        or counts
        != {
            "observed_traces": 66,
            "supported_tasks": 63,
            "cpu_unsupported_tasks": 3,
            "supported_passes": counts.get("supported_passes") if isinstance(counts, dict) else None,
            "trace_failures": 0,
            "global_problems": 0,
        }
        or not _plain_int(counts.get("supported_passes"), minimum=7, maximum=63)
        or not isinstance(scores, dict)
        or set(scores) != {"supported_pass_rate", "all_task_pass_rate"}
        or not isinstance(scores.get("supported_pass_rate"), (int, float))
        or isinstance(scores.get("supported_pass_rate"), bool)
        or not math.isclose(scores["supported_pass_rate"], counts["supported_passes"] / 63)
        or not math.isclose(scores.get("all_task_pass_rate", -1), counts["supported_passes"] / 66)
        or not 7 / 63 <= scores["supported_pass_rate"] <= 0.22
        or policy not in accepted_policies
        or not isinstance(providers, dict)
        or set(providers) != {"sandoq_firecracker", "vmvm_cpu"}
        or not isinstance(trace, dict)
        or trace.get("cpu_traces") != 63
        or trace.get("unsupported_gpu_outcomes") != 3
        or trace.get("total_traces") != 66
        or trace.get("trace_failures") != 0
        or trace.get("reasoning_required") is not True
        or trace.get("request_graph_match_required") is not True
        or trace.get("exact_provider_json_required") is not True
        or not _plain_int(trace.get("model_io_turns"), minimum=63)
        or not _plain_int(trace.get("sampled_tokens"), minimum=1)
        or not _plain_int(trace.get("tool_observations"), minimum=63)
        or not _plain_int(trace.get("successful_tool_exits"), minimum=0)
        or not _plain_int(trace.get("nonzero_tool_exits"), minimum=0)
        or trace.get("missing_tool_exits") != 0
        or trace["successful_tool_exits"] + trace["nonzero_tool_exits"] != trace["tool_observations"]
        or not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "results",
            "sandoq_lane_certificate",
            "vmvm_lane_certificate",
            "launch_plan",
            "partition_receipt",
        }
    ):
        raise KimiProductionError("tb4_promotion_invalid")
    sandoq = providers["sandoq_firecracker"]
    vmvm = providers["vmvm_cpu"]
    if (
        not isinstance(sandoq, dict)
        or sandoq
        != {
            "state": "passed",
            "task_count": 25,
            "passes": sandoq.get("passes"),
            "cleanup_state": "passed",
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "runtime_tunnel_receipt_sha256": RUNTIME_TUNNEL_RECEIPT_SHA256,
            "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
        }
        or not _plain_int(sandoq.get("passes"), minimum=0, maximum=25)
        or not isinstance(vmvm, dict)
        or set(vmvm) != {"state", "task_count", "passes", "cleanup_state", "capacity"}
        or vmvm.get("state") != "passed"
        or vmvm.get("task_count") != 38
        or not _plain_int(vmvm.get("passes"), minimum=0, maximum=38)
        or vmvm.get("cleanup_state") != "passed"
        or not isinstance(vmvm.get("capacity"), dict)
        or vmvm["capacity"].get("provider") != "vmvm"
        or sandoq["passes"] + vmvm["passes"] != counts["supported_passes"]
    ):
        raise KimiProductionError("tb4_promotion_invalid")
    for name, record in artifacts.items():
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
            raise KimiProductionError("tb4_promotion_invalid")
        observed = _artifact_record(Path(str(record["path"])), "tb4_artifact_changed", private=True)
        if observed != record:
            raise KimiProductionError("tb4_artifact_changed")
    if (
        artifacts["results"]["sha256"] != value["results_sha256"]
        or artifacts["launch_plan"]["sha256"] != value["launch_plan_sha256"]
    ):
        raise KimiProductionError("tb4_promotion_invalid")
    return value, artifact


def _validate_tb4_certificate(path: Path, expected_sha256: str) -> tuple[dict[str, Any], Artifact]:
    value, artifact = _json_artifact(path, expected_sha256, "tb4_promotion_invalid")
    if value.get("schema_version") == 3:
        try:
            from certify_kimi_tb4_sandoq_clamped_union import validate_certificate

            validated = validate_certificate(path, expected_sha256)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            raise KimiProductionError("tb4_promotion_invalid") from error
        if validated != value:
            raise KimiProductionError("tb4_promotion_invalid")
        return value, artifact
    if value.get("schema_version") == 2:
        validated = _validate_tb4_miniswe_union_certificate(value, artifact)
        try:
            from certify_kimi_tb4_miniswe246_union import validate_union_certificate

            validate_union_certificate(path, expected_sha256)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            raise KimiProductionError("tb4_promotion_invalid") from error
        return validated
    unsigned = dict(value)
    claimed = unsigned.pop("tb4_certificate_sha256", None)
    scores = value.get("scores")
    counts = value.get("counts")
    policy = value.get("policy")
    cleanup = value.get("pool_cleanup")
    artifacts = value.get("artifacts")
    expected_artifacts = {
        "cleanup_audit",
        "config",
        "eval_invocations",
        "eval_run_identity",
        "inputs_manifest",
        "provenance",
        "results",
        "router_receipt",
        "smoke_checkpoint",
    }
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "model",
            "eval_run_identity_sha256",
            "results_sha256",
            "task_file_sha256",
            "worker_manifest_sha256",
            "source_spec_sha256",
            "endpoint_bundle_sha256",
            "worker_count",
            "counts",
            "scores",
            "policy",
            "pool_cleanup",
            "artifacts",
            "tb4_certificate_sha256",
        }
        or value.get("schema_version") != 1
        or value.get("kind") != TB4_KIND
        or value.get("state") != "passed"
        or value.get("model") != MODEL
        or claimed != hashlib.sha256(canonical_json(unsigned)).hexdigest()
        or value.get("worker_count") != 24
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in (
                "eval_run_identity_sha256",
                "results_sha256",
                "task_file_sha256",
                "worker_manifest_sha256",
                "source_spec_sha256",
                "endpoint_bundle_sha256",
            )
        )
        or not isinstance(scores, dict)
        or set(scores) != {"supported_pass_rate", "all_task_pass_rate"}
        or not isinstance(counts, dict)
        or set(counts)
        != {
            "observed_traces",
            "supported_tasks",
            "cpu_unsupported_tasks",
            "supported_passes",
            "trace_failures",
            "global_problems",
        }
        or not isinstance(policy, dict)
        or set(policy)
        != {
            "expected_tasks",
            "expected_supported_tasks",
            "rollouts_per_task",
            "max_sequence_tokens",
            "min_supported_pass_rate",
            "max_supported_pass_rate",
            "router_policy",
            "request_id_headers",
            "request_timeout_seconds",
            "retries",
        }
        or policy.get("expected_tasks") != 66
        or policy.get("expected_supported_tasks") != 63
        or policy.get("rollouts_per_task") != 1
        or policy.get("max_sequence_tokens") != MAX_SEQUENCE_TOKENS
        or policy.get("min_supported_pass_rate") != 0.04
        or policy.get("max_supported_pass_rate") != 0.22
        or policy.get("router_policy") != "consistent_hash"
        or policy.get("request_id_headers") != ["x-session-id"]
        or policy.get("request_timeout_seconds") != 43_200
        or policy.get("retries") != 0
        or counts.get("observed_traces") != 66
        or counts.get("supported_tasks") != 63
        or counts.get("cpu_unsupported_tasks") != 3
        or counts.get("trace_failures") != 0
        or counts.get("global_problems") != 0
        or not _plain_int(counts.get("supported_passes"))
        or counts["supported_passes"] > counts["supported_tasks"]
        or not isinstance(scores.get("supported_pass_rate"), (int, float))
        or isinstance(scores.get("supported_pass_rate"), bool)
        or not isinstance(scores.get("all_task_pass_rate"), (int, float))
        or isinstance(scores.get("all_task_pass_rate"), bool)
        or float(scores["supported_pass_rate"]) != counts["supported_passes"] / 63
        or float(scores["all_task_pass_rate"]) != counts["supported_passes"] / 66
        or not 0.04 <= float(scores["supported_pass_rate"]) <= 0.22
        or not isinstance(cleanup, dict)
        or set(cleanup) != {"audit_sha256", "assignment_measured_high_water", "outer_session_high_water", "failures"}
        or SHA256_RE.fullmatch(str(cleanup.get("audit_sha256", ""))) is None
        or cleanup.get("assignment_measured_high_water") != 24
        or cleanup.get("outer_session_high_water") != 24
        or cleanup.get("failures") != 0
        or not isinstance(artifacts, dict)
        or set(artifacts) != expected_artifacts
    ):
        raise KimiProductionError("tb4_promotion_invalid")
    for name, record in artifacts.items():
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise KimiProductionError("tb4_promotion_invalid")
        observed = _artifact_record(Path(str(record["path"])), "tb4_artifact_changed")
        if observed["path"] != record["path"] or observed["sha256"] != record["sha256"]:
            raise KimiProductionError("tb4_artifact_changed")
    if (
        artifacts["results"]["sha256"] != value["results_sha256"]
        or artifacts["cleanup_audit"]["sha256"] != cleanup["audit_sha256"]
    ):
        raise KimiProductionError("tb4_promotion_invalid")
    return value, artifact


def _source_binding(project_root: Path, expected_revision: str) -> dict[str, Any]:
    if REVISION_RE.fullmatch(expected_revision or "") is None:
        raise KimiProductionError("source_identity_invalid")
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise KimiProductionError("source_identity_invalid") from error
    if root != project_root or project_root.is_symlink():
        raise KimiProductionError("source_identity_invalid")

    def git(directory: Path, *arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-c", "core.fsmonitor=false", "-C", str(directory), *arguments],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=120,
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise KimiProductionError("source_identity_invalid") from error
        return result.stdout.decode("ascii", errors="strict").strip()

    commit = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    dirty = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if commit != expected_revision or dirty or REVISION_RE.fullmatch(tree) is None:
        raise KimiProductionError("source_identity_invalid")
    files = {
        "pipeline": root / "user/tianhaowu/terminal_bench_vmvm/kimi_sandoq_production.py",
        "stage": root / "user/tianhaowu/terminal_bench_vmvm/run_direct_kimi_sandoq_production_stage.sh",
        "launcher": root
        / "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/run_mobius_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch",
        "sft_finalizer": root / "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_sft.py",
        "sft_launcher": root
        / "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/finalize_mobius_kimi_k3_sandoq_cpu-132-021_8103.sbatch",
        "ecr_guard": root / "user/tianhaowu/terminal_bench_vmvm/sandoq_ecr_rotation.py",
        "cleanup": root / "user/tianhaowu/terminal_bench_vmvm/run_sandoq_verified_cleanup.py",
        "provider_context": root / "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/sandoq_provider_context.py",
        "provider_profile": root
        / "user/tianhaowu/terminal_bench_vmvm/configs/provider_context/use2/kimi_sandoq_firecracker_host.json",
        "eval_identity": root / "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
        "direct_workers": root / "user/tianhaowu/terminal_bench_vmvm/direct_kimi_workers.py",
        "direct_router": root / "user/tianhaowu/terminal_bench_vmvm/direct_kimi_router.py",
        "capacity_certifier": root / "user/tianhaowu/terminal_bench_vmvm/direct_kimi_capacity.py",
        "capacity_launcher": root / "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/"
        "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch",
        "trace_auditor": root / "user/tianhaowu/terminal_bench_vmvm/audit_traces.py",
        "tb4_clamped_certifier": root / "user/tianhaowu/terminal_bench_vmvm/certify_kimi_tb4_sandoq_clamped_union.py",
        "sft_exporter": root / "user/tianhaowu/terminal_bench_vmvm/export_sft.py",
    }
    return {
        "project_root": str(root),
        "prime_rl_commit": commit,
        "prime_rl_tree": tree,
        "files": {name: _artifact_record(path, "source_identity_invalid") for name, path in files.items()},
    }


def _validate_capacity_certificate(
    path: Path,
    expected_sha256: str,
    *,
    required_concurrency: int,
) -> tuple[dict[str, Any], Artifact]:
    value, artifact = _json_artifact(path, expected_sha256, "capacity_certificate_invalid")
    if (
        value.get("schema_version") != 4
        or value.get("kind") != CAPACITY_KIND
        or value.get("state") != "passed"
        or value.get("capacity_profile") != CAPACITY_PROFILE
        or value.get("endpoint_identifier") != DEPLOYMENT_NAMESPACE
        or not _plain_int(value.get("qualified_concurrency"), minimum=required_concurrency, maximum=MAX_CAPACITY)
    ):
        raise KimiProductionError("capacity_certificate_invalid")
    try:
        from direct_kimi_capacity import validate_capacity_certificate

        validated = validate_capacity_certificate(
            path,
            expected_sha256=expected_sha256,
            required_concurrency=required_concurrency,
            expected_endpoint_identifier=DEPLOYMENT_NAMESPACE,
            expected_worker_manifest_sha256=str(value["worker_manifest_sha256"]),
            expected_config_sha256=str(value["config"]["source_sha256"]),
        )
    except (ImportError, KeyError, TypeError, ValueError) as error:
        raise KimiProductionError("capacity_certificate_invalid") from error
    if not isinstance(validated, dict) or validated.get("qualified_concurrency") != value["qualified_concurrency"]:
        raise KimiProductionError("capacity_certificate_invalid")
    return value, artifact


def create_promotion(
    *,
    tb4_certificate: Path,
    tb4_certificate_sha256: str,
    forced_delete_receipt: Path,
    forced_delete_receipt_sha256: str,
    idle_recovery_receipt: Path,
    idle_recovery_receipt_sha256: str,
    capacity_certificate: Path,
    capacity_certificate_sha256: str,
    miniswe_compatibility_receipt: Path,
    miniswe_compatibility_receipt_sha256: str,
    requested_concurrency: int,
    output: Path,
    private_output_root: Path,
) -> dict[str, Any]:
    if not _plain_int(requested_concurrency, minimum=1, maximum=MAX_CAPACITY):
        raise KimiProductionError("requested_concurrency_invalid")
    tb4, tb4_artifact = _validate_tb4_certificate(tb4_certificate, tb4_certificate_sha256)
    forced = _validate_recovery_receipt(
        forced_delete_receipt,
        forced_delete_receipt_sha256,
        mode="forced-delete",
    )
    idle = _validate_recovery_receipt(
        idle_recovery_receipt,
        idle_recovery_receipt_sha256,
        mode="idle-endurance",
    )
    capacity, capacity_artifact = _validate_capacity_certificate(
        capacity_certificate,
        capacity_certificate_sha256,
        required_concurrency=requested_concurrency,
    )
    miniswe_compatibility = _validate_miniswe_compatibility_receipt(
        miniswe_compatibility_receipt,
        miniswe_compatibility_receipt_sha256,
    )
    tb4_deployment = tb4.get("deployment") if tb4.get("schema_version") in {2, 3} else tb4
    if capacity.get("endpoint_bundle_sha256") != tb4_deployment.get("endpoint_bundle_sha256"):
        raise KimiProductionError("promotion_endpoint_mismatch")
    value = {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "kind": PROMOTION_KIND,
        "state": "passed",
        "model": MODEL,
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "requested_concurrency": requested_concurrency,
        "qualified_concurrency": capacity["qualified_concurrency"],
        "prerequisites": {
            "tb4": tb4_artifact.as_dict(),
            "forced_delete_recovery": forced.as_dict(),
            "idle_endurance_recovery": idle.as_dict(),
            "route_capacity": capacity_artifact.as_dict(),
            "miniswe_compatibility": miniswe_compatibility.as_dict(),
        },
        "endpoint": {
            "identifier": DEPLOYMENT_NAMESPACE,
            "endpoint_bundle_sha256": capacity.get("endpoint_bundle_sha256"),
            "source_spec_sha256": tb4_deployment.get("source_spec_sha256"),
            "router_implementation_sha256": capacity.get("source", {}).get("router_implementation_sha256"),
        },
        "capacity_source": {
            "prime_rl_commit": capacity.get("source", {}).get("prime_rl_commit"),
            "prime_rl_tree_sha256": capacity.get("source", {}).get("prime_rl_tree_sha256"),
            "verifiers_commit": capacity.get("source", {}).get("verifiers_commit"),
        },
        "contracts": _production_contracts(),
    }
    unsigned = canonical_json(value)
    value["promotion_sha256"] = hashlib.sha256(unsigned).hexdigest()
    _publish_bundle(_private_root(private_output_root), {output: canonical_json(value)})
    return {
        "state": "passed",
        "requested_concurrency": requested_concurrency,
        "qualified_concurrency": capacity["qualified_concurrency"],
        "promotion_sha256": value["promotion_sha256"],
    }


def validate_promotion(
    path: Path, expected_sha256: str, *, required_concurrency: int
) -> tuple[dict[str, Any], Artifact]:
    value, artifact = _json_artifact(path, expected_sha256, "promotion_certificate_invalid", private=True)
    unsigned = dict(value)
    claimed = unsigned.pop("promotion_sha256", None)
    prerequisites = value.get("prerequisites")
    endpoint = value.get("endpoint")
    capacity_source = value.get("capacity_source")
    contracts = value.get("contracts")
    if (
        value.get("schema_version") != PROMOTION_SCHEMA_VERSION
        or value.get("kind") != PROMOTION_KIND
        or value.get("state") != "passed"
        or value.get("model") != MODEL
        or value.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or value.get("requested_concurrency") != required_concurrency
        or not _plain_int(value.get("qualified_concurrency"), minimum=required_concurrency, maximum=MAX_CAPACITY)
        or claimed != hashlib.sha256(canonical_json(unsigned)).hexdigest()
        or not isinstance(prerequisites, dict)
        or set(prerequisites)
        != {
            "tb4",
            "forced_delete_recovery",
            "idle_endurance_recovery",
            "route_capacity",
            "miniswe_compatibility",
        }
        or not isinstance(endpoint, dict)
        or endpoint.get("identifier") != DEPLOYMENT_NAMESPACE
        or any(
            SHA256_RE.fullmatch(str(endpoint.get(key, ""))) is None
            for key in ("endpoint_bundle_sha256", "source_spec_sha256", "router_implementation_sha256")
        )
        or contracts != _production_contracts()
        or not isinstance(capacity_source, dict)
        or set(capacity_source) != {"prime_rl_commit", "prime_rl_tree_sha256", "verifiers_commit"}
        or REVISION_RE.fullmatch(str(capacity_source.get("prime_rl_commit", ""))) is None
        or SHA256_RE.fullmatch(str(capacity_source.get("prime_rl_tree_sha256", ""))) is None
        or capacity_source.get("verifiers_commit") != VERIFIERS_COMMIT
    ):
        raise KimiProductionError("promotion_certificate_invalid")
    for record in prerequisites.values():
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
            raise KimiProductionError("promotion_certificate_invalid")
        observed = _artifact_record(Path(str(record["path"])), "promotion_prerequisite_changed", private=False)
        if observed != record:
            raise KimiProductionError("promotion_prerequisite_changed")
    tb4, _tb4_artifact = _validate_tb4_certificate(
        Path(str(prerequisites["tb4"]["path"])),
        str(prerequisites["tb4"]["sha256"]),
    )
    _validate_recovery_receipt(
        Path(str(prerequisites["forced_delete_recovery"]["path"])),
        str(prerequisites["forced_delete_recovery"]["sha256"]),
        mode="forced-delete",
    )
    _validate_recovery_receipt(
        Path(str(prerequisites["idle_endurance_recovery"]["path"])),
        str(prerequisites["idle_endurance_recovery"]["sha256"]),
        mode="idle-endurance",
    )
    capacity, _capacity_artifact = _validate_capacity_certificate(
        Path(str(prerequisites["route_capacity"]["path"])),
        str(prerequisites["route_capacity"]["sha256"]),
        required_concurrency=required_concurrency,
    )
    _validate_miniswe_compatibility_receipt(
        Path(str(prerequisites["miniswe_compatibility"]["path"])),
        str(prerequisites["miniswe_compatibility"]["sha256"]),
    )
    tb4_deployment = tb4.get("deployment") if tb4.get("schema_version") in {2, 3} else tb4
    expected_endpoint = {
        "identifier": DEPLOYMENT_NAMESPACE,
        "endpoint_bundle_sha256": capacity.get("endpoint_bundle_sha256"),
        "source_spec_sha256": tb4_deployment.get("source_spec_sha256"),
        "router_implementation_sha256": capacity.get("source", {}).get("router_implementation_sha256"),
    }
    expected_capacity_source = {
        "prime_rl_commit": capacity.get("source", {}).get("prime_rl_commit"),
        "prime_rl_tree_sha256": capacity.get("source", {}).get("prime_rl_tree_sha256"),
        "verifiers_commit": capacity.get("source", {}).get("verifiers_commit"),
    }
    if (
        capacity.get("endpoint_bundle_sha256") != tb4_deployment.get("endpoint_bundle_sha256")
        or value.get("qualified_concurrency") != capacity.get("qualified_concurrency")
        or endpoint != expected_endpoint
        or capacity_source != expected_capacity_source
    ):
        raise KimiProductionError("promotion_certificate_invalid")
    return value, artifact


def _validate_worker_manifest(
    path: Path,
    expected_sha256: str,
) -> tuple[dict[str, Any], Artifact]:
    artifact, _body = _stable_artifact(path, "worker_manifest_invalid", private=True)
    if artifact.sha256 != expected_sha256:
        raise KimiProductionError("worker_manifest_invalid")
    try:
        from direct_kimi_workers import validate_saved_manifest

        value = validate_saved_manifest(path)
    except (OSError, TypeError, ValueError) as error:
        raise KimiProductionError("worker_manifest_invalid") from error
    router = value.get("router")
    if (
        value.get("schema_version") != 3
        or not isinstance(router, dict)
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier") != DEPLOYMENT_NAMESPACE
        or router.get("implementation") != ROUTER_IMPLEMENTATION
        or router.get("policy") != "consistent_hash"
        or router.get("request_id_headers") != ["x-session-id"]
        or router.get("max_concurrent_requests") != MAX_CAPACITY
        or router.get("per_worker_capacity") != PER_WORKER_CAPACITY
        or router.get("retries") != 0
        or len(value.get("workers", ())) != 24
        or SHA256_RE.fullmatch(str(value.get("source_spec_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("endpoint_bundle_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(router.get("implementation_sha256", ""))) is None
    ):
        raise KimiProductionError("worker_manifest_invalid")
    return value, artifact


def _launch_value(
    *,
    source: Mapping[str, Any],
    selector: Artifact,
    selector_receipt: Artifact,
    config: Artifact,
    template: Artifact,
    image_manifest: Artifact,
    promotion: Artifact,
    promotion_value: Mapping[str, Any],
    worker_manifest: Artifact,
    worker_value: Mapping[str, Any],
    concurrency: int,
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "kind": LAUNCH_KIND,
        "state": "authorized",
        "model": MODEL,
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "source": dict(source),
        "inputs": {
            "approved_source": {
                "count": EXPECTED_SOURCE_COUNT,
                "sha256": CANONICAL_SOURCE_SHA256,
            },
            "dataset": {
                "revision": CANONICAL_DATASET_REVISION,
                "tree": CANONICAL_DATASET_TREE,
            },
            "selector": selector.as_dict(),
            "selector_receipt": selector_receipt.as_dict(),
            "config_template": template.as_dict(),
            "resolved_config": config.as_dict(),
            "image_manifest": image_manifest.as_dict(),
            "promotion": promotion.as_dict(),
            "worker_manifest": worker_manifest.as_dict(),
        },
        "deployment": {
            "capacity_profile": CAPACITY_PROFILE,
            "per_worker_capacity": PER_WORKER_CAPACITY,
            "max_forwarded_capacity": MAX_FORWARDED_CAPACITY,
            "endpoint_identifier": DEPLOYMENT_NAMESPACE,
            "endpoint_bundle_sha256": worker_value["endpoint_bundle_sha256"],
            "source_spec_sha256": worker_value["source_spec_sha256"],
            "router_implementation_sha256": worker_value["router"]["implementation_sha256"],
            "worker_count": len(worker_value["workers"]),
        },
        "execution": {
            "cleanup_must_succeed": True,
            "ecr_rotation_guard_required": True,
            "sandbox_environment": PROVIDER_ENVIRONMENT,
            "task_network": PROVIDER_TASK_NETWORK,
            "network_access": True,
            "host_tunnel": "sandoq",
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "runtime_tunnel_receipt_sha256": RUNTIME_TUNNEL_RECEIPT_SHA256,
            "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
            "harness": {"id": "mini-swe-agent", "version": MINISWE_VERSION},
            "lease_duration": "12h",
            "lease_profile": "kimi-tb4-long",
            "managed_shell_recovery": "definitive-404-410-single-replay-v1",
            "pool_size": concurrency,
            "requested_concurrency": concurrency,
            "retries": 0,
            "run_output_dir": str(output_dir),
        },
        "capture": {
            "exact_provider_json": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "model_io": True,
            "model_io_contract": "kimi-k3-max",
            "reasoning": True,
            "request_graph": True,
        },
        "promotion_sha256": promotion_value["promotion_sha256"],
    }


def create_launch(
    *,
    project_root: Path,
    expected_revision: str,
    source: Path,
    dataset: Path,
    selector: Path,
    selector_receipt: Path,
    selector_receipt_sha256: str,
    template: Path,
    image_manifest: Path,
    worker_manifest: Path,
    worker_manifest_sha256: str,
    promotion: Path,
    promotion_sha256: str,
    concurrency: int,
    run_output_dir: Path,
    config_output: Path,
    launch_output: Path,
    private_output_root: Path,
) -> dict[str, Any]:
    if not _plain_int(concurrency, minimum=1, maximum=MAX_CAPACITY):
        raise KimiProductionError("requested_concurrency_invalid")
    root = _private_root(private_output_root)
    selector_value, selector_artifact = validate_selector(
        source=source,
        dataset=dataset,
        selector=selector,
        receipt=selector_receipt,
        receipt_sha256=selector_receipt_sha256,
    )
    selector_receipt_artifact, _body = _stable_artifact(
        selector_receipt,
        "selector_receipt_invalid",
        private=True,
    )
    promotion_value, promotion_artifact = validate_promotion(
        promotion,
        promotion_sha256,
        required_concurrency=concurrency,
    )
    template_artifact, template_body = _stable_artifact(template, "config_template_invalid")
    if template.resolve(strict=True) != _canonical_template_path() or template_artifact.sha256 != TEMPLATE_SHA256:
        raise KimiProductionError("config_template_invalid")
    image_artifact, _image_body = _stable_artifact(image_manifest, "image_manifest_invalid")
    if image_artifact.sha256 != IMAGE_MANIFEST_SHA256:
        raise KimiProductionError("image_manifest_invalid")
    worker_value, worker_artifact = _validate_worker_manifest(worker_manifest, worker_manifest_sha256)
    endpoint = promotion_value["endpoint"]
    if (
        worker_value["endpoint_bundle_sha256"] != endpoint["endpoint_bundle_sha256"]
        or worker_value["source_spec_sha256"] != endpoint["source_spec_sha256"]
        or worker_value["router"]["implementation_sha256"] != endpoint["router_implementation_sha256"]
    ):
        raise KimiProductionError("launch_endpoint_mismatch")
    config_body = materialize_config(
        template_body,
        Path(selector_artifact.path),
        selector_artifact.sha256,
        concurrency,
    )
    config_artifact = Artifact(str(config_output), len(config_body), hashlib.sha256(config_body).hexdigest())
    source_value = _source_binding(project_root, expected_revision)
    if promotion_value.get("capacity_source", {}).get("prime_rl_commit") != source_value["prime_rl_commit"]:
        raise KimiProductionError("launch_capacity_source_mismatch")
    try:
        normalized_output = Path(os.path.normpath(run_output_dir))
        if (
            not run_output_dir.is_absolute()
            or run_output_dir != normalized_output
            or run_output_dir.name in {"", ".", ".."}
            or os.path.lexists(run_output_dir)
            or run_output_dir == root
            or run_output_dir.is_relative_to(root)
            or root.is_relative_to(run_output_dir)
        ):
            raise KimiProductionError("run_output_path_invalid")
    except (OSError, ValueError) as error:
        if isinstance(error, KimiProductionError):
            raise
        raise KimiProductionError("run_output_path_invalid") from error
    if selector_value["selection"]["selected_sha256"] != selector_artifact.sha256:
        raise KimiProductionError("selector_receipt_invalid")
    value = _launch_value(
        source=source_value,
        selector=selector_artifact,
        selector_receipt=selector_receipt_artifact,
        config=config_artifact,
        template=template_artifact,
        image_manifest=image_artifact,
        promotion=promotion_artifact,
        promotion_value=promotion_value,
        worker_manifest=worker_artifact,
        worker_value=worker_value,
        concurrency=concurrency,
        output_dir=run_output_dir,
    )
    value["launch_sha256"] = hashlib.sha256(canonical_json(value)).hexdigest()
    _publish_bundle(root, {config_output: config_body, launch_output: canonical_json(value)})
    return {
        "state": "authorized",
        "concurrency": concurrency,
        "launch_sha256": value["launch_sha256"],
        "selector_count": EXPECTED_TASK_COUNT,
    }


def _record_artifact(value: object, code: str, *, private: bool = False) -> tuple[Path, Artifact]:
    if not isinstance(value, dict) or set(value) != {"path", "bytes", "sha256"}:
        raise KimiProductionError(code)
    try:
        path = Path(str(value["path"]))
        size = value["bytes"]
        digest = value["sha256"]
    except (KeyError, TypeError, ValueError) as error:
        raise KimiProductionError(code) from error
    if not _plain_int(size) or SHA256_RE.fullmatch(str(digest)) is None:
        raise KimiProductionError(code)
    observed, _body = _stable_artifact(path, code, private=private)
    if observed != Artifact(str(path), size, str(digest)):
        raise KimiProductionError(code)
    return path, observed


def validate_launch(
    path: Path,
    expected_sha256: str,
    *,
    revalidate_source: bool = True,
) -> dict[str, Any]:
    value, artifact = _json_artifact(path, expected_sha256, "launch_certificate_invalid", private=True)
    unsigned = dict(value)
    claimed = unsigned.pop("launch_sha256", None)
    inputs = value.get("inputs")
    deployment = value.get("deployment")
    execution = value.get("execution")
    capture = value.get("capture")
    source = value.get("source")
    if (
        value.get("schema_version") != LAUNCH_SCHEMA_VERSION
        or value.get("kind") != LAUNCH_KIND
        or value.get("state") != "authorized"
        or value.get("model") != MODEL
        or value.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or claimed != hashlib.sha256(canonical_json(unsigned)).hexdigest()
        or not isinstance(inputs, dict)
        or set(inputs)
        != {
            "approved_source",
            "dataset",
            "selector",
            "selector_receipt",
            "config_template",
            "resolved_config",
            "image_manifest",
            "promotion",
            "worker_manifest",
        }
        or inputs.get("approved_source") != {"count": EXPECTED_SOURCE_COUNT, "sha256": CANONICAL_SOURCE_SHA256}
        or inputs.get("dataset") != {"revision": CANONICAL_DATASET_REVISION, "tree": CANONICAL_DATASET_TREE}
        or not isinstance(deployment, dict)
        or deployment.get("capacity_profile") != CAPACITY_PROFILE
        or deployment.get("per_worker_capacity") != PER_WORKER_CAPACITY
        or deployment.get("max_forwarded_capacity") != MAX_FORWARDED_CAPACITY
        or deployment.get("endpoint_identifier") != DEPLOYMENT_NAMESPACE
        or deployment.get("worker_count") != 24
        or any(
            SHA256_RE.fullmatch(str(deployment.get(key, ""))) is None
            for key in ("endpoint_bundle_sha256", "source_spec_sha256", "router_implementation_sha256")
        )
        or not isinstance(execution, dict)
        or not _plain_int(execution.get("requested_concurrency"), minimum=1, maximum=MAX_CAPACITY)
        or execution.get("pool_size") != execution.get("requested_concurrency")
        or execution.get("retries") != 0
        or execution.get("sandbox_environment") != PROVIDER_ENVIRONMENT
        or execution.get("task_network") != PROVIDER_TASK_NETWORK
        or execution.get("network_access") is not True
        or execution.get("host_tunnel") != "sandoq"
        or execution.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or execution.get("runtime_tunnel_receipt_sha256") != RUNTIME_TUNNEL_RECEIPT_SHA256
        or execution.get("runtime_resource_receipt_sha256") != RUNTIME_RESOURCE_RECEIPT_SHA256
        or execution.get("harness") != {"id": "mini-swe-agent", "version": MINISWE_VERSION}
        or execution.get("lease_duration") != "12h"
        or execution.get("lease_profile") != "kimi-tb4-long"
        or execution.get("managed_shell_recovery") != "definitive-404-410-single-replay-v1"
        or execution.get("cleanup_must_succeed") is not True
        or execution.get("ecr_rotation_guard_required") is not True
        or not isinstance(execution.get("run_output_dir"), str)
        or capture
        != {
            "exact_provider_json": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "model_io": True,
            "model_io_contract": "kimi-k3-max",
            "reasoning": True,
            "request_graph": True,
        }
        or not isinstance(source, dict)
    ):
        raise KimiProductionError("launch_certificate_invalid")
    concurrency = execution["requested_concurrency"]
    records: dict[str, tuple[Path, Artifact]] = {}
    for name in (
        "selector",
        "selector_receipt",
        "config_template",
        "resolved_config",
        "image_manifest",
        "promotion",
        "worker_manifest",
    ):
        records[name] = _record_artifact(
            inputs[name],
            "launch_input_changed",
            private=name in {"selector", "selector_receipt", "resolved_config", "promotion", "worker_manifest"},
        )
    if (
        records["config_template"][1].sha256 != TEMPLATE_SHA256
        or records["image_manifest"][1].sha256 != IMAGE_MANIFEST_SHA256
    ):
        raise KimiProductionError("launch_input_changed")
    config_body = records["resolved_config"][0].read_bytes()
    _validate_config(
        config_body,
        selector=records["selector"][0],
        selector_sha256=records["selector"][1].sha256,
        concurrency=concurrency,
    )
    promotion, _promotion_artifact = validate_promotion(
        records["promotion"][0],
        records["promotion"][1].sha256,
        required_concurrency=concurrency,
    )
    if promotion["promotion_sha256"] != value.get("promotion_sha256"):
        raise KimiProductionError("launch_promotion_mismatch")
    worker, _worker_artifact = _validate_worker_manifest(
        records["worker_manifest"][0],
        records["worker_manifest"][1].sha256,
    )
    if (
        deployment["endpoint_bundle_sha256"] != worker["endpoint_bundle_sha256"]
        or deployment["source_spec_sha256"] != worker["source_spec_sha256"]
        or deployment["router_implementation_sha256"] != worker["router"]["implementation_sha256"]
    ):
        raise KimiProductionError("launch_endpoint_mismatch")
    if revalidate_source:
        project_root = Path(str(source.get("project_root", "")))
        rebound = _source_binding(project_root, str(source.get("prime_rl_commit", "")))
        if rebound != source:
            raise KimiProductionError("launch_source_changed")
    run_output_dir = Path(execution["run_output_dir"])
    if not run_output_dir.is_absolute() or run_output_dir != Path(os.path.normpath(run_output_dir)):
        raise KimiProductionError("run_output_path_invalid")
    return {
        "artifact": artifact.as_dict(),
        "value": value,
        "config": str(records["resolved_config"][0]),
        "selector": str(records["selector"][0]),
        "selector_sha256": records["selector"][1].sha256,
        "worker_manifest": str(records["worker_manifest"][0]),
        "worker_manifest_sha256": records["worker_manifest"][1].sha256,
        "output_dir": str(run_output_dir),
        "concurrency": concurrency,
    }


def _strict_reward(trace: Mapping[str, Any]) -> float:
    rewards = trace.get("rewards")
    if not isinstance(rewards, Mapping) or not rewards:
        raise KimiProductionError("trace_reward_invalid")
    values = tuple(rewards.values())
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
        for value in values
    ):
        raise KimiProductionError("trace_reward_invalid")
    reward = float(sum(values))
    if reward not in {0.0, 1.0}:
        raise KimiProductionError("trace_reward_invalid")
    return reward


def _positive_observations(trace: Mapping[str, Any]) -> tuple[int, int]:
    nodes = trace.get("nodes")
    if not isinstance(nodes, list):
        return 0, 0
    turns = 0
    tokens = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("sampled") is not True:
            continue
        if node.get("model_io") is not None:
            turns += 1
        usage = audit_traces._usage_tokens(node)
        if usage is not None:
            tokens += usage[1]
    return turns, tokens


def audit_pass_only_results(
    results: Path,
    selector: Path,
    *,
    trace_validator: Callable[[dict[str, Any]], None] | None = None,
) -> TraceAudit:
    selector_artifact, selector_body = _stable_artifact(selector, "selector_invalid", private=True)
    try:
        members = tuple(selector_body.decode("utf-8").splitlines())
    except UnicodeDecodeError as error:
        raise KimiProductionError("selector_invalid") from error
    if (
        len(members) != EXPECTED_TASK_COUNT
        or len(set(members)) != EXPECTED_TASK_COUNT
        or any(MEMBER_RE.fullmatch(member) is None for member in members)
    ):
        raise KimiProductionError("selector_invalid")
    expected = frozenset(members)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(results, flags)
    except OSError as error:
        raise KimiProductionError("results_invalid") from error
    digest = hashlib.sha256()
    size = 0
    seen_ids: set[str] = set()
    seen_tasks: set[str] = set()
    counts: Counter[str] = Counter()
    default_validator = trace_validator is None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise KimiProductionError("results_invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            while True:
                raw = stream.readline(MAX_RESULTS_ROW_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_RESULTS_ROW_BYTES or not raw.endswith(b"\n") or not raw.strip():
                    raise KimiProductionError("results_invalid")
                digest.update(raw)
                size += len(raw)
                trace = _strict_json(raw, "results_invalid")
                trace_id = trace.get("id")
                slug = audit_traces._task_slug(trace)
                if (
                    not isinstance(trace_id, str)
                    or not trace_id
                    or trace_id in seen_ids
                    or slug not in expected
                    or slug in seen_tasks
                ):
                    raise KimiProductionError("trace_identity_invalid")
                seen_ids.add(trace_id)
                seen_tasks.add(slug)
                errors = trace.get("errors")
                if not isinstance(errors, list):
                    raise KimiProductionError("trace_errors_invalid")
                counts["traces"] += 1
                if errors:
                    counts["error_traces"] += 1
                    continue
                reward = _strict_reward(trace)
                if reward == 0.0:
                    counts["zero_reward_traces"] += 1
                    continue
                if trace_validator is not None:
                    trace_validator(trace)
                else:
                    problems = audit_traces._audit_trace(
                        trace,
                        require_reasoning=True,
                        max_sequence_tokens=MAX_SEQUENCE_TOKENS,
                        require_token_data=False,
                        require_logprobs=False,
                        require_model_io=True,
                        model_io_contract=audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
                        require_request_graph_match=True,
                        require_exact_provider_json=True,
                        require_clean_stop=True,
                    )
                    if problems:
                        raise KimiProductionError("positive_trace_invalid")
                    try:
                        sft._validate_trainable_trace(
                            trace,
                            reward=reward,
                            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
                            require_exact_provider_json=True,
                        )
                    except sft.ExportError as error:
                        raise KimiProductionError("positive_trace_invalid") from error
                turns, sampled_tokens = _positive_observations(trace)
                if default_validator and (turns < 1 or sampled_tokens < 1):
                    raise KimiProductionError("positive_trace_invalid")
                counts["positive_traces"] += 1
                counts["positive_model_io_turns"] += turns
                counts["positive_sampled_tokens"] += sampled_tokens
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or size != before.st_size
        or seen_tasks != expected
        or counts["traces"] != EXPECTED_TASK_COUNT
        or counts["error_traces"] + counts["zero_reward_traces"] + counts["positive_traces"] != EXPECTED_TASK_COUNT
    ):
        raise KimiProductionError("trace_coverage_invalid")
    del selector_artifact
    return TraceAudit(
        artifact=Artifact(str(results.resolve()), size, digest.hexdigest()),
        traces=counts["traces"],
        error_traces=counts["error_traces"],
        zero_reward_traces=counts["zero_reward_traces"],
        positive_traces=counts["positive_traces"],
        positive_model_io_turns=counts["positive_model_io_turns"],
        positive_sampled_tokens=counts["positive_sampled_tokens"],
    )


def _validate_rotation_audit(
    path: Path,
    *,
    identity_sha256: str,
    results_sha256: str,
) -> Artifact:
    artifact, body = _stable_artifact(path, "rotation_audit_invalid", private=True)
    value = _strict_json(body, "rotation_audit_invalid", canonical=True)
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "refresh_source",
        "token_path_policy",
        "atomic_same_path",
        "monitor_started_before_rollout",
        "monitor_stopped_after_rollout",
        "maximum_refresh_interval_seconds",
        "fail_closed_before_expiry_seconds",
        "run_duration_seconds",
        "successful_replacements",
        "maximum_observed_refresh_gap_seconds",
        "maximum_observed_heartbeat_gap_seconds",
        "minimum_observed_expiry_margin_seconds",
        "batch_heartbeats",
        "liveness_failures",
        "expired_observations",
        "credential_payload_records",
        "eval_run_identity_sha256",
        "results_sha256",
        "raw_rotator_log_sha256",
        "raw_batch_guard_log_sha256",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("kind") != ROTATION_KIND
        or value.get("state") != "passed"
        or value.get("refresh_source") != "login-side-service"
        or value.get("token_path_policy") != "private-mode-0600-atomic-replace"
        or value.get("atomic_same_path") is not True
        or value.get("monitor_started_before_rollout") is not True
        or value.get("monitor_stopped_after_rollout") is not True
        or value.get("liveness_failures") != 0
        or value.get("expired_observations") != 0
        or value.get("credential_payload_records") != 0
        or value.get("eval_run_identity_sha256") != identity_sha256
        or value.get("results_sha256") != results_sha256
        or not _plain_int(value.get("successful_replacements"), minimum=1)
        or not _plain_int(value.get("batch_heartbeats"), minimum=2)
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in ("raw_rotator_log_sha256", "raw_batch_guard_log_sha256")
        )
    ):
        raise KimiProductionError("rotation_audit_invalid")
    return artifact


def _validate_run_identity(
    run_dir: Path,
    *,
    launch: Mapping[str, Any],
    launch_artifact: Artifact,
) -> tuple[dict[str, Any], str]:
    try:
        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
    except (OSError, ValueError) as error:
        raise KimiProductionError("eval_identity_invalid") from error
    identity = envelope.get("identity")
    identity_sha256 = envelope.get("eval_run_identity_sha256")
    if not isinstance(identity, dict) or SHA256_RE.fullmatch(str(identity_sha256)) is None:
        raise KimiProductionError("eval_identity_invalid")
    source = identity.get("source")
    config = identity.get("config")
    inputs = identity.get("inputs")
    deployment = identity.get("deployment")
    router = deployment.get("router") if isinstance(deployment, dict) else None
    contract = identity.get("contract")
    execution = identity.get("execution")
    launch_inputs = launch["inputs"]
    concurrency = launch["execution"]["requested_concurrency"]
    if (
        identity.get("role") != "kimi-direct-mobius"
        or not isinstance(source, dict)
        or source.get("sandbox_provider") != "sandoq"
        or not isinstance(config, dict)
        or config.get("source", {}).get("sha256") != launch_inputs["resolved_config"]["sha256"]
        or not isinstance(inputs, dict)
        or inputs.get("task_file", {}).get("sha256") != launch_inputs["selector"]["sha256"]
        or inputs.get("task_file", {}).get("count") != EXPECTED_TASK_COUNT
        or inputs.get("image_manifest", {}).get("sha256") != IMAGE_MANIFEST_SHA256
        or not isinstance(deployment, dict)
        or deployment.get("kind") != "direct_kimi"
        or not isinstance(router, dict)
        or router.get("implementation") != ROUTER_IMPLEMENTATION
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier") != DEPLOYMENT_NAMESPACE
        or router.get("provider_concurrency") != MAX_CAPACITY
        or router.get("per_worker_capacity") != PER_WORKER_CAPACITY
        or deployment.get("worker_manifest", {}).get("sha256") != launch_inputs["worker_manifest"]["sha256"]
        or deployment.get("endpoint_bundle_sha256") != launch["deployment"]["endpoint_bundle_sha256"]
        or deployment.get("spec_sha256") != launch["deployment"]["source_spec_sha256"]
        or deployment.get("promotion_certificate") != {"path": launch_artifact.path, "sha256": launch_artifact.sha256}
        or not isinstance(contract, dict)
        or contract.get("model") != MODEL
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "max"
        or contract.get("thinking") != {"enable_thinking": True, "preserve_thinking": True}
        or contract.get("context_tokens")
        != {
            "max_input_tokens": MAX_SEQUENCE_TOKENS,
            "max_output_tokens": MAX_SEQUENCE_TOKENS,
            "max_total_tokens": MAX_SEQUENCE_TOKENS,
        }
        or contract.get("sampling_max_tokens") != MAX_GENERATION_TOKENS
        or contract.get("capture_model_io") is not True
        or contract.get("retain_traces") is not False
        or not isinstance(execution, dict)
        or any(
            execution.get(key) != concurrency
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or execution.get("cleanup_must_succeed") is not True
        or execution.get("runtime", {}).get("type") != "sandoq"
        or execution.get("runtime", {}).get("session_timeout") != 43_200
        or execution.get("runtime", {}).get("network_access") is not True
        or execution.get("runtime", {}).get("host_tunnel") != "sandoq"
        or execution.get("runtime", {}).get("buffered_chat_completions") is not True
        or execution.get("runtime", {}).get("expected_environment") != PROVIDER_ENVIRONMENT
        or execution.get("sandoq_environment", {}).get("environment") != PROVIDER_ENVIRONMENT
        or execution.get("sandoq_environment", {}).get("task_network") != "public"
        or execution.get("sandoq_environment", {}).get("provider_task_network") != PROVIDER_TASK_NETWORK
        or execution.get("sandoq_environment", {}).get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or execution.get("sandoq_environment", {}).get("runtime_tunnel_receipt_sha256") != RUNTIME_TUNNEL_RECEIPT_SHA256
        or execution.get("sandoq_environment", {}).get("runtime_resource_receipt_sha256")
        != RUNTIME_RESOURCE_RECEIPT_SHA256
        or execution.get("sandoq_environment", {}).get("miniswe_compatibility_receipt_sha256")
        != MINISWE_COMPATIBILITY_SHA256
        or execution.get("sandoq_environment", {}).get("tunnel_policy") != "native-sandoq-reverse-tunnel"
        or execution.get("sandoq_environment", {}).get("allow_dockerhub_fallback") is not False
        or execution.get("sandoq_environment", {}).get("pool_size") != concurrency
        or execution.get("sandoq_environment", {}).get("lease_profile") != "kimi-tb4-long"
        or execution.get("sandoq_environment", {}).get("lease_duration") != "12h"
        or execution.get("sandoq_environment", {}).get("managed_shell_recovery")
        != "definitive-404-410-single-replay-v1"
    ):
        raise KimiProductionError("eval_identity_invalid")
    return identity, str(identity_sha256)


def _validate_router_receipt(
    path: Path,
    *,
    identity_sha256: str,
    worker_manifest_sha256: str,
    endpoint_bundle_sha256: str,
    router_implementation_sha256: str,
    concurrency: int,
    minimum_chat_requests: int,
) -> tuple[Artifact, dict[str, Any]]:
    artifact, body = _stable_artifact(path, "router_receipt_invalid", private=True)
    value = _strict_json(body, "router_receipt_invalid", canonical=True)
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "eval_run_identity_sha256",
        "invocation_identity_sha256",
        "worker_manifest_sha256",
        "endpoint_bundle_sha256",
        "active_workers",
        "implementation",
        "implementation_sha256",
        "policy",
        "request_id_headers",
        "request_timeout_seconds",
        "retries",
        "source_generation_revalidated",
        "max_active_requests",
        "total_requests",
        "chat_requests",
        "worker_request_counts_sha256",
        "capacity_profile",
        "endpoint_identifier",
        "configured_capacity",
        "configured_per_worker_capacity",
        "active_forwarded_requests",
        "worker_active_request_counts_sha256",
        "worker_session_counts_sha256",
        "active_worker_waiters",
        "worker_waiting_request_counts_sha256",
        "max_active_forwarded_requests",
        "worker_max_active_request_counts_sha256",
        "max_active_chat_requests",
        "capacity_rejections",
        "queue_overflow_rejections",
        "route_tracking_overflows",
        "cross_route_anomalies",
        "worker_queue_timeouts",
        "upstream_http_429",
        "upstream_http_5xx",
        "tracked_sessions",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 5
        or value.get("kind") != "direct-kimi-router-final"
        or value.get("state") != "passed"
        or value.get("eval_run_identity_sha256") != identity_sha256
        or SHA256_RE.fullmatch(str(value.get("invocation_identity_sha256", ""))) is None
        or value.get("worker_manifest_sha256") != worker_manifest_sha256
        or value.get("endpoint_bundle_sha256") != endpoint_bundle_sha256
        or value.get("active_workers") != 24
        or value.get("implementation") != ROUTER_IMPLEMENTATION
        or value.get("implementation_sha256") != router_implementation_sha256
        or value.get("policy") != "consistent_hash"
        or value.get("request_id_headers") != ["x-session-id"]
        or value.get("request_timeout_seconds") != 43_200
        or value.get("retries") != 0
        or value.get("source_generation_revalidated") is not True
        or value.get("capacity_profile") != CAPACITY_PROFILE
        or value.get("endpoint_identifier") != DEPLOYMENT_NAMESPACE
        or value.get("configured_capacity") != MAX_CAPACITY
        or value.get("configured_per_worker_capacity") != PER_WORKER_CAPACITY
        or not _plain_int(value.get("active_forwarded_requests"), minimum=0, maximum=0)
        or value.get("worker_active_request_counts_sha256") != ZERO_WORKER_COUNTS_SHA256
        or SHA256_RE.fullmatch(str(value.get("worker_session_counts_sha256", ""))) is None
        or not _plain_int(value.get("active_worker_waiters"), minimum=0, maximum=0)
        or value.get("worker_waiting_request_counts_sha256") != ZERO_WORKER_COUNTS_SHA256
        or value.get("capacity_rejections") != 0
        or value.get("queue_overflow_rejections") != 0
        or value.get("route_tracking_overflows") != 0
        or value.get("cross_route_anomalies") != 0
        or value.get("worker_queue_timeouts") != 0
        or value.get("upstream_http_429") != 0
        or value.get("upstream_http_5xx") != 0
        or not _plain_int(value.get("max_active_requests"), minimum=1, maximum=concurrency)
        or not _plain_int(value.get("max_active_chat_requests"), minimum=1, maximum=concurrency)
        or not _plain_int(
            value.get("max_active_forwarded_requests"),
            minimum=1,
            maximum=min(concurrency, MAX_FORWARDED_CAPACITY),
        )
        or value["max_active_forwarded_requests"] > value["max_active_chat_requests"]
        or not _plain_int(value.get("total_requests"), minimum=minimum_chat_requests)
        or not _plain_int(value.get("chat_requests"), minimum=minimum_chat_requests)
        or value["total_requests"] < value["chat_requests"]
        or not _plain_int(value.get("tracked_sessions"), minimum=1, maximum=65_536)
        or value["tracked_sessions"] > value["chat_requests"]
        or SHA256_RE.fullmatch(str(value.get("worker_request_counts_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("worker_max_active_request_counts_sha256", ""))) is None
    ):
        raise KimiProductionError("router_receipt_invalid")
    return artifact, value


def _provenance_job_id(path: Path) -> str:
    _artifact, body = _stable_artifact(path, "provenance_invalid", private=True)
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise KimiProductionError("provenance_invalid") from error
    values = [line.removeprefix("slurm_job_id=") for line in lines if line.startswith("slurm_job_id=")]
    if len(values) != 1 or not values[0].isdigit():
        raise KimiProductionError("provenance_invalid")
    return values[0]


def record_terminal_job(
    *,
    provenance: Path,
    output: Path,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, Any]:
    job_id = _provenance_job_id(provenance)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"SLURM_CONF", "SLURM_CLUSTERS", "SQUEUE_FORMAT", "SACCT_FORMAT"}
    }
    try:
        accounting = runner(
            [
                "sacct",
                "-j",
                job_id,
                "-X",
                "-n",
                "-P",
                "-o",
                "JobIDRaw,State,ExitCode,DerivedExitCode,Restarts,Cluster",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
            env=environment,
        )
        queue = runner(
            ["squeue", "-h", "-j", job_id, "-o", "%i|%T"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise KimiProductionError("scheduler_observation_failed") from error
    rows = [line.split("|") for line in accounting.stdout.decode("utf-8", errors="strict").splitlines() if line]
    if (
        accounting.returncode != 0
        or queue.returncode != 0
        or queue.stdout.strip()
        or len(rows) != 1
        or len(rows[0]) != 6
        or rows[0][0] != job_id
        or rows[0][1].removesuffix("+") not in TERMINAL_STATES
        or rows[0][4] not in {"", "0"}
        or not rows[0][5]
    ):
        raise KimiProductionError("evaluation_job_not_terminal")
    row = rows[0]
    value = {
        "schema_version": 1,
        "kind": "kimi-k3-max-sandoq-terminal-job",
        "state": "terminal",
        "job_id": job_id,
        "cluster": row[5],
        "scheduler_state": row[1].removesuffix("+"),
        "exit_code": row[2],
        "derived_exit_code": row[3],
        "restarts": 0,
        "queue_rows": 0,
        "sacct_sha256": hashlib.sha256(accounting.stdout).hexdigest(),
        "squeue_sha256": hashlib.sha256(queue.stdout).hexdigest(),
        "provenance_sha256": _artifact_record(provenance, "provenance_invalid", private=True)["sha256"],
    }
    _publish_bundle(_private_root(output.parent), {output: canonical_json(value)})
    return {
        "state": "terminal",
        "scheduler_state": value["scheduler_state"],
        "job_id": job_id,
    }


def _validate_terminal_receipt(
    path: Path,
    expected_sha256: str,
    *,
    provenance: Path,
) -> Artifact:
    value, artifact = _json_artifact(path, expected_sha256, "terminal_receipt_invalid", private=True)
    job_id = _provenance_job_id(provenance)
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "job_id",
        "cluster",
        "scheduler_state",
        "exit_code",
        "derived_exit_code",
        "restarts",
        "queue_rows",
        "sacct_sha256",
        "squeue_sha256",
        "provenance_sha256",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("kind") != "kimi-k3-max-sandoq-terminal-job"
        or value.get("state") != "terminal"
        or value.get("job_id") != job_id
        or value.get("scheduler_state") not in TERMINAL_STATES
        or value.get("restarts") != 0
        or value.get("queue_rows") != 0
        or value.get("provenance_sha256") != _artifact_record(provenance, "provenance_invalid", private=True)["sha256"]
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in ("sacct_sha256", "squeue_sha256"))
    ):
        raise KimiProductionError("terminal_receipt_invalid")
    return artifact


def certify_traces(
    *,
    launch_certificate: Path,
    launch_certificate_sha256: str,
    run_dir: Path,
    rotation_audit: Path,
    terminal_receipt: Path,
    terminal_receipt_sha256: str,
    output: Path,
) -> dict[str, Any]:
    validated = validate_launch(launch_certificate, launch_certificate_sha256)
    launch = validated["value"]
    launch_artifact = Artifact(**validated["artifact"])
    try:
        run = run_dir.resolve(strict=True)
        if run != run_dir or run.is_symlink() or str(run) != validated["output_dir"]:
            raise KimiProductionError("run_directory_invalid")
    except OSError as error:
        raise KimiProductionError("run_directory_invalid") from error
    lock_path = run / ".writer.lock"
    try:
        lock = lock_path.open("rb")
    except OSError as error:
        raise KimiProductionError("writer_lock_invalid") from error
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KimiProductionError("writer_active") from error
        identity, identity_sha256 = _validate_run_identity(
            run,
            launch=launch,
            launch_artifact=launch_artifact,
        )
        results = audit_pass_only_results(run / "results.jsonl", Path(validated["selector"]))
        terminal = _validate_terminal_receipt(
            terminal_receipt,
            terminal_receipt_sha256,
            provenance=run / "provenance.txt",
        )
        rotation = _validate_rotation_audit(
            rotation_audit,
            identity_sha256=identity_sha256,
            results_sha256=results.artifact.sha256,
        )
        concurrency = validated["concurrency"]
        cleanup, cleanup_body = _validate_cleanup(
            run / "sandoq_cleanup_audit.json",
            expected_count=EXPECTED_TASK_COUNT,
            expected_concurrency=concurrency,
            require_saturation=True,
        )
        cleanup_artifact, _body = _stable_artifact(
            run / "sandoq_cleanup_audit.json",
            "cleanup_audit_invalid",
            private=True,
        )
        router, router_value = _validate_router_receipt(
            run / "direct_kimi_router_final.json",
            identity_sha256=identity_sha256,
            worker_manifest_sha256=validated["worker_manifest_sha256"],
            endpoint_bundle_sha256=launch["deployment"]["endpoint_bundle_sha256"],
            router_implementation_sha256=launch["deployment"]["router_implementation_sha256"],
            concurrency=concurrency,
            minimum_chat_requests=results.positive_traces + results.zero_reward_traces,
        )
        provider_context = _validate_provider_context_snapshot(run / "sandoq-provider-context.json")
        artifacts = {
            "launch_certificate": launch_artifact.as_dict(),
            "results": results.artifact.as_dict(),
            "eval_run_identity": _artifact_record(run / "eval_run_identity.json", "run_artifact_invalid", private=True),
            "eval_invocations": _artifact_record(run / "eval_invocations.jsonl", "run_artifact_invalid", private=True),
            "provenance": _artifact_record(run / "provenance.txt", "run_artifact_invalid", private=True),
            "router_receipt": router.as_dict(),
            "cleanup_audit": cleanup_artifact.as_dict(),
            "rotation_audit": rotation.as_dict(),
            "terminal_receipt": terminal.as_dict(),
            "provider_context": provider_context.as_dict(),
        }
        value = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "kind": TRACE_KIND,
            "state": "passed",
            "model": MODEL,
            "deployment_namespace": DEPLOYMENT_NAMESPACE,
            "eval_run_identity_sha256": identity_sha256,
            "launch_sha256": launch["launch_sha256"],
            "coverage": {
                "expected_tasks": EXPECTED_TASK_COUNT,
                "observed_traces": results.traces,
                "error_traces": results.error_traces,
                "zero_reward_traces": results.zero_reward_traces,
                "positive_traces": results.positive_traces,
                "disjoint": True,
                "exhaustive": True,
            },
            "capture": {
                "exact_provider_json": True,
                "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
                "model_io_contract": "kimi-k3-max",
                "positive_model_io_turns": results.positive_model_io_turns,
                "positive_sampled_tokens": results.positive_sampled_tokens,
                "reasoning": True,
                "request_graph": True,
            },
            "execution": {
                "concurrency": concurrency,
                "capacity_profile": CAPACITY_PROFILE,
                "per_worker_capacity": PER_WORKER_CAPACITY,
                "max_forwarded_capacity": MAX_FORWARDED_CAPACITY,
                "active_forwarded_requests": router_value["active_forwarded_requests"],
                "worker_active_request_counts_sha256": router_value["worker_active_request_counts_sha256"],
                "worker_session_counts_sha256": router_value["worker_session_counts_sha256"],
                "active_worker_waiters": router_value["active_worker_waiters"],
                "worker_waiting_request_counts_sha256": router_value["worker_waiting_request_counts_sha256"],
                "max_active_forwarded_requests": router_value["max_active_forwarded_requests"],
                "worker_max_active_request_counts_sha256": router_value["worker_max_active_request_counts_sha256"],
                "worker_queue_timeouts": router_value["worker_queue_timeouts"],
                "upstream_http_429": router_value["upstream_http_429"],
                "upstream_http_5xx": router_value["upstream_http_5xx"],
                "sandbox_environment": PROVIDER_ENVIRONMENT,
                "task_network": PROVIDER_TASK_NETWORK,
                "host_tunnel": "sandoq",
                "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
                "runtime_tunnel_receipt_sha256": RUNTIME_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
                "provider_context_sha256": provider_context.sha256,
                "miniswe_version": MINISWE_VERSION,
                "cleanup_failures": cleanup["failures"],
                "assignment_measured_high_water": cleanup["assignment_measured_high_water"],
                "outer_session_high_water": cleanup["outer_session_high_water"],
                "ecr_rotation_passed": True,
            },
            "sft": {
                "selection": "pass-only",
                "expected_selected_traces": results.positive_traces,
                "require_exact_provider_json": True,
                "preflight_required": True,
            },
            "artifacts": artifacts,
        }
        value["trace_certificate_sha256"] = hashlib.sha256(canonical_json(value)).hexdigest()
        _publish_bundle(_private_root(output.parent), {output: canonical_json(value)})
        return {
            "state": "passed",
            "observed_traces": results.traces,
            "positive_traces": results.positive_traces,
            "zero_reward_traces": results.zero_reward_traces,
            "error_traces": results.error_traces,
            "trace_certificate_sha256": value["trace_certificate_sha256"],
        }
    finally:
        lock.close()


def validate_trace_certificate(path: Path, expected_sha256: str) -> dict[str, Any]:
    value, certificate_artifact = _json_artifact(
        path,
        expected_sha256,
        "trace_certificate_invalid",
        private=True,
    )
    unsigned = dict(value)
    claimed = unsigned.pop("trace_certificate_sha256", None)
    coverage = value.get("coverage")
    capture = value.get("capture")
    execution = value.get("execution")
    sft_value = value.get("sft")
    artifacts = value.get("artifacts")
    if (
        value.get("schema_version") != TRACE_SCHEMA_VERSION
        or value.get("kind") != TRACE_KIND
        or value.get("state") != "passed"
        or value.get("model") != MODEL
        or value.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or SHA256_RE.fullmatch(str(value.get("eval_run_identity_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("launch_sha256", ""))) is None
        or claimed != hashlib.sha256(canonical_json(unsigned)).hexdigest()
        or not isinstance(coverage, dict)
        or coverage.get("expected_tasks") != EXPECTED_TASK_COUNT
        or coverage.get("observed_traces") != EXPECTED_TASK_COUNT
        or any(not _plain_int(coverage.get(key)) for key in ("error_traces", "zero_reward_traces", "positive_traces"))
        or coverage["error_traces"] + coverage["zero_reward_traces"] + coverage["positive_traces"]
        != EXPECTED_TASK_COUNT
        or coverage.get("disjoint") is not True
        or coverage.get("exhaustive") is not True
        or capture
        != {
            "exact_provider_json": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "model_io_contract": "kimi-k3-max",
            "positive_model_io_turns": capture.get("positive_model_io_turns") if isinstance(capture, dict) else None,
            "positive_sampled_tokens": capture.get("positive_sampled_tokens") if isinstance(capture, dict) else None,
            "reasoning": True,
            "request_graph": True,
        }
        or not _plain_int(capture.get("positive_model_io_turns"), minimum=coverage["positive_traces"])
        or not _plain_int(capture.get("positive_sampled_tokens"), minimum=1)
        or not isinstance(execution, dict)
        or execution.get("capacity_profile") != CAPACITY_PROFILE
        or execution.get("per_worker_capacity") != PER_WORKER_CAPACITY
        or execution.get("max_forwarded_capacity") != MAX_FORWARDED_CAPACITY
        or not _plain_int(execution.get("active_forwarded_requests"), minimum=0, maximum=0)
        or execution.get("worker_active_request_counts_sha256") != ZERO_WORKER_COUNTS_SHA256
        or SHA256_RE.fullmatch(str(execution.get("worker_session_counts_sha256", ""))) is None
        or not _plain_int(execution.get("active_worker_waiters"), minimum=0, maximum=0)
        or execution.get("worker_waiting_request_counts_sha256") != ZERO_WORKER_COUNTS_SHA256
        or not _plain_int(
            execution.get("max_active_forwarded_requests"),
            minimum=1,
            maximum=min(execution.get("concurrency", 0), MAX_FORWARDED_CAPACITY),
        )
        or SHA256_RE.fullmatch(str(execution.get("worker_max_active_request_counts_sha256", ""))) is None
        or execution.get("worker_queue_timeouts") != 0
        or execution.get("upstream_http_429") != 0
        or execution.get("upstream_http_5xx") != 0
        or execution.get("sandbox_environment") != PROVIDER_ENVIRONMENT
        or execution.get("task_network") != PROVIDER_TASK_NETWORK
        or execution.get("host_tunnel") != "sandoq"
        or execution.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or execution.get("runtime_tunnel_receipt_sha256") != RUNTIME_TUNNEL_RECEIPT_SHA256
        or execution.get("runtime_resource_receipt_sha256") != RUNTIME_RESOURCE_RECEIPT_SHA256
        or SHA256_RE.fullmatch(str(execution.get("provider_context_sha256", ""))) is None
        or execution.get("miniswe_version") != MINISWE_VERSION
        or not _plain_int(execution.get("concurrency"), minimum=1, maximum=MAX_CAPACITY)
        or execution.get("cleanup_failures") != 0
        or execution.get("assignment_measured_high_water") != execution.get("concurrency")
        or execution.get("outer_session_high_water") != execution.get("concurrency")
        or execution.get("ecr_rotation_passed") is not True
        or sft_value
        != {
            "selection": "pass-only",
            "expected_selected_traces": coverage["positive_traces"],
            "require_exact_provider_json": True,
            "preflight_required": True,
        }
        or not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "launch_certificate",
            "results",
            "eval_run_identity",
            "eval_invocations",
            "provenance",
            "router_receipt",
            "cleanup_audit",
            "rotation_audit",
            "terminal_receipt",
            "provider_context",
        }
    ):
        raise KimiProductionError("trace_certificate_invalid")
    records = {
        name: _record_artifact(record, "trace_artifact_changed", private=True) for name, record in artifacts.items()
    }
    launch = validate_launch(
        records["launch_certificate"][0],
        records["launch_certificate"][1].sha256,
    )
    if launch["value"]["launch_sha256"] != value["launch_sha256"]:
        raise KimiProductionError("trace_launch_mismatch")
    run_dir = records["results"][0].parent
    if str(run_dir) != launch["output_dir"]:
        raise KimiProductionError("trace_launch_mismatch")
    _identity, identity_sha256 = _validate_run_identity(
        run_dir,
        launch=launch["value"],
        launch_artifact=Artifact(**launch["artifact"]),
    )
    if identity_sha256 != value["eval_run_identity_sha256"]:
        raise KimiProductionError("trace_certificate_invalid")
    audited = audit_pass_only_results(records["results"][0], Path(launch["selector"]))
    if (
        audited.artifact != records["results"][1]
        or audited.traces != coverage["observed_traces"]
        or audited.error_traces != coverage["error_traces"]
        or audited.zero_reward_traces != coverage["zero_reward_traces"]
        or audited.positive_traces != coverage["positive_traces"]
        or audited.positive_model_io_turns != capture["positive_model_io_turns"]
        or audited.positive_sampled_tokens != capture["positive_sampled_tokens"]
    ):
        raise KimiProductionError("trace_certificate_invalid")
    _router_artifact, router_value = _validate_router_receipt(
        records["router_receipt"][0],
        identity_sha256=identity_sha256,
        worker_manifest_sha256=launch["worker_manifest_sha256"],
        endpoint_bundle_sha256=launch["value"]["deployment"]["endpoint_bundle_sha256"],
        router_implementation_sha256=launch["value"]["deployment"]["router_implementation_sha256"],
        concurrency=launch["concurrency"],
        minimum_chat_requests=audited.positive_traces + audited.zero_reward_traces,
    )
    if _router_artifact != records["router_receipt"][1] or any(
        execution.get(key) != router_value.get(key)
        for key in (
            "active_forwarded_requests",
            "worker_active_request_counts_sha256",
            "worker_session_counts_sha256",
            "active_worker_waiters",
            "worker_waiting_request_counts_sha256",
            "max_active_forwarded_requests",
            "worker_max_active_request_counts_sha256",
            "worker_queue_timeouts",
            "upstream_http_429",
            "upstream_http_5xx",
        )
    ):
        raise KimiProductionError("trace_certificate_invalid")
    _validate_terminal_receipt(
        records["terminal_receipt"][0],
        records["terminal_receipt"][1].sha256,
        provenance=records["provenance"][0],
    )
    _validate_rotation_audit(
        records["rotation_audit"][0],
        identity_sha256=value["eval_run_identity_sha256"],
        results_sha256=audited.artifact.sha256,
    )
    provider_context = _validate_provider_context_snapshot(records["provider_context"][0])
    if provider_context.sha256 != execution["provider_context_sha256"]:
        raise KimiProductionError("trace_certificate_invalid")
    return {
        "artifact": certificate_artifact.as_dict(),
        "value": value,
        "run_dir": str(run_dir),
        "results": str(records["results"][0]),
        "selected_traces": coverage["positive_traces"],
    }


def write_cleanup_command(
    *,
    project_root: Path,
    expected_revision: str,
    output_dir: Path,
    owner: str,
    pool_socket: Path,
    output: Path,
) -> dict[str, Any]:
    source = _source_binding(project_root, expected_revision)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", owner):
        raise KimiProductionError("cleanup_command_invalid")
    root = _private_root(output_dir)
    control = _private_root(root / "control")
    if output.parent != control or pool_socket.suffix != ".sock":
        raise KimiProductionError("cleanup_command_invalid")
    workflow = project_root / "user/tianhaowu/terminal_bench_vmvm"
    provider = project_root / "deps/sandoq-provider"
    cleanup = workflow / "run_sandoq_verified_cleanup.py"
    sanitizer = workflow / "sanitize_sandoq_cleanup_audit.py"
    provider_cleanup = provider / "recipes/sandoq_swerebench_v2_oci/verify_pool_cleanup.py"
    arguments = [
        sys.executable,
        "-B",
        str(cleanup),
        "--output-dir",
        str(root),
        "--provider-cleanup",
        str(provider_cleanup),
        "--base-url",
        "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "--owner",
        owner,
        "--concurrency",
        "32",
        "--event-log",
        str(root / "pool_events.jsonl"),
        "--wal",
        str(control / "sandoq-pool.wal.jsonl"),
        "--drain-marker",
        str(pool_socket.with_suffix(".drained.json")),
        "--sanitized-output",
        str(root / "sandoq_cleanup_audit.json"),
        "--project-root",
        str(project_root),
        "--provider-root",
        str(provider),
        "--expected-prime-commit",
        source["prime_rl_commit"],
        "--expected-prime-tree",
        source["prime_rl_tree"],
        "--expected-self-sha256",
        str(_artifact_record(cleanup, "cleanup_command_invalid")["sha256"]),
        "--expected-sanitizer-sha256",
        str(_artifact_record(sanitizer, "cleanup_command_invalid")["sha256"]),
        "--expected-provider-cleanup-sha256",
        str(_artifact_record(provider_cleanup, "cleanup_command_invalid")["sha256"]),
    ]
    body = canonical_json(arguments)
    _publish_bundle(control, {output: body})
    return {"state": "written", "sha256": hashlib.sha256(body).hexdigest()}


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise KimiProductionError("arguments_invalid")


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    selector = commands.add_parser("materialize-selector")
    selector.add_argument("--source", type=Path, required=True)
    selector.add_argument("--dataset", type=Path, required=True)
    selector.add_argument("--selector", type=Path, required=True)
    selector.add_argument("--receipt", type=Path, required=True)
    selector.add_argument("--private-output-root", type=Path, required=True)

    capacity_selector = commands.add_parser("materialize-capacity-selector")
    capacity_selector.add_argument("--source", type=Path, required=True)
    capacity_selector.add_argument("--dataset", type=Path, required=True)
    capacity_selector.add_argument("--selector", type=Path, required=True)
    capacity_selector.add_argument("--receipt", type=Path, required=True)
    capacity_selector.add_argument("--private-output-root", type=Path, required=True)

    promotion = commands.add_parser("promote")
    promotion.add_argument("--tb4-certificate", type=Path, required=True)
    promotion.add_argument("--tb4-certificate-sha256", required=True)
    promotion.add_argument("--forced-delete-receipt", type=Path, required=True)
    promotion.add_argument("--forced-delete-receipt-sha256", required=True)
    promotion.add_argument("--idle-recovery-receipt", type=Path, required=True)
    promotion.add_argument("--idle-recovery-receipt-sha256", required=True)
    promotion.add_argument("--capacity-certificate", type=Path, required=True)
    promotion.add_argument("--capacity-certificate-sha256", required=True)
    promotion.add_argument("--miniswe-compatibility-receipt", type=Path, required=True)
    promotion.add_argument("--miniswe-compatibility-receipt-sha256", required=True)
    promotion.add_argument("--requested-concurrency", type=int, required=True)
    promotion.add_argument("--output", type=Path, required=True)
    promotion.add_argument("--private-output-root", type=Path, required=True)

    launch = commands.add_parser("create-launch")
    launch.add_argument("--project-root", type=Path, required=True)
    launch.add_argument("--expected-revision", required=True)
    launch.add_argument("--source", type=Path, required=True)
    launch.add_argument("--dataset", type=Path, required=True)
    launch.add_argument("--selector", type=Path, required=True)
    launch.add_argument("--selector-receipt", type=Path, required=True)
    launch.add_argument("--selector-receipt-sha256", required=True)
    launch.add_argument("--template", type=Path, required=True)
    launch.add_argument("--image-manifest", type=Path, required=True)
    launch.add_argument("--worker-manifest", type=Path, required=True)
    launch.add_argument("--worker-manifest-sha256", required=True)
    launch.add_argument("--promotion", type=Path, required=True)
    launch.add_argument("--promotion-sha256", required=True)
    launch.add_argument("--concurrency", type=int, required=True)
    launch.add_argument("--run-output-dir", type=Path, required=True)
    launch.add_argument("--config-output", type=Path, required=True)
    launch.add_argument("--launch-output", type=Path, required=True)
    launch.add_argument("--private-output-root", type=Path, required=True)

    validator = commands.add_parser("validate-launch")
    validator.add_argument("--launch", type=Path, required=True)
    validator.add_argument("--launch-sha256", required=True)
    validator.add_argument("--format", choices=("json", "tsv"), default="json")

    cleanup = commands.add_parser("cleanup-command")
    cleanup.add_argument("--project-root", type=Path, required=True)
    cleanup.add_argument("--expected-revision", required=True)
    cleanup.add_argument("--output-dir", type=Path, required=True)
    cleanup.add_argument("--owner", required=True)
    cleanup.add_argument("--pool-socket", type=Path, required=True)
    cleanup.add_argument("--output", type=Path, required=True)

    terminal = commands.add_parser("record-terminal")
    terminal.add_argument("--provenance", type=Path, required=True)
    terminal.add_argument("--output", type=Path, required=True)

    certificate = commands.add_parser("certify")
    certificate.add_argument("--launch-certificate", type=Path, required=True)
    certificate.add_argument("--launch-certificate-sha256", required=True)
    certificate.add_argument("--run-dir", type=Path, required=True)
    certificate.add_argument("--rotation-audit", type=Path, required=True)
    certificate.add_argument("--terminal-receipt", type=Path, required=True)
    certificate.add_argument("--terminal-receipt-sha256", required=True)
    certificate.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "materialize-selector":
            summary = materialize_selector(
                source=args.source,
                dataset=args.dataset,
                selector=args.selector,
                receipt=args.receipt,
                private_output_root=args.private_output_root,
            )
        elif args.command == "materialize-capacity-selector":
            summary = materialize_capacity_selector(
                source=args.source,
                dataset=args.dataset,
                selector=args.selector,
                receipt=args.receipt,
                private_output_root=args.private_output_root,
            )
        elif args.command == "promote":
            summary = create_promotion(
                tb4_certificate=args.tb4_certificate,
                tb4_certificate_sha256=args.tb4_certificate_sha256,
                forced_delete_receipt=args.forced_delete_receipt,
                forced_delete_receipt_sha256=args.forced_delete_receipt_sha256,
                idle_recovery_receipt=args.idle_recovery_receipt,
                idle_recovery_receipt_sha256=args.idle_recovery_receipt_sha256,
                capacity_certificate=args.capacity_certificate,
                capacity_certificate_sha256=args.capacity_certificate_sha256,
                miniswe_compatibility_receipt=args.miniswe_compatibility_receipt,
                miniswe_compatibility_receipt_sha256=args.miniswe_compatibility_receipt_sha256,
                requested_concurrency=args.requested_concurrency,
                output=args.output,
                private_output_root=args.private_output_root,
            )
        elif args.command == "create-launch":
            summary = create_launch(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                source=args.source,
                dataset=args.dataset,
                selector=args.selector,
                selector_receipt=args.selector_receipt,
                selector_receipt_sha256=args.selector_receipt_sha256,
                template=args.template,
                image_manifest=args.image_manifest,
                worker_manifest=args.worker_manifest,
                worker_manifest_sha256=args.worker_manifest_sha256,
                promotion=args.promotion,
                promotion_sha256=args.promotion_sha256,
                concurrency=args.concurrency,
                run_output_dir=args.run_output_dir,
                config_output=args.config_output,
                launch_output=args.launch_output,
                private_output_root=args.private_output_root,
            )
        elif args.command == "validate-launch":
            validated = validate_launch(args.launch, args.launch_sha256)
            if args.format == "tsv":
                print(
                    "\t".join(
                        str(validated[key])
                        for key in (
                            "config",
                            "selector",
                            "selector_sha256",
                            "worker_manifest",
                            "worker_manifest_sha256",
                            "output_dir",
                            "concurrency",
                        )
                    )
                )
                return 0
            summary = {
                "state": "authorized",
                "concurrency": validated["concurrency"],
                "selected_count": EXPECTED_TASK_COUNT,
            }
        elif args.command == "cleanup-command":
            summary = write_cleanup_command(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                output_dir=args.output_dir,
                owner=args.owner,
                pool_socket=args.pool_socket,
                output=args.output,
            )
        elif args.command == "record-terminal":
            summary = record_terminal_job(
                provenance=args.provenance,
                output=args.output,
            )
        else:
            summary = certify_traces(
                launch_certificate=args.launch_certificate,
                launch_certificate_sha256=args.launch_certificate_sha256,
                run_dir=args.run_dir,
                rotation_audit=args.rotation_audit,
                terminal_receipt=args.terminal_receipt,
                terminal_receipt_sha256=args.terminal_receipt_sha256,
                output=args.output,
            )
    except KimiProductionError as error:
        print(json.dumps({"code": error.code, "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print('{"code":"internal_error","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
