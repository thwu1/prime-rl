#!/usr/bin/env python3
"""Validate and snapshot the fixed direct-worker Qwen deployment."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
import re
import tempfile
import tomllib
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EXPECTED_MODEL = "Qwen3.8-2.4T-A95B"
EXPECTED_ENDPOINTS = 16
EXPECTED_SPEC_SHA256 = "516c386c646abda61b73ffe2b2a820c38a826e2311327154cd775ed29e60215a"
EXPECTED_ENDPOINT_BUNDLE_SHA256 = "77b513b09002201df0464586e0ac69932348f7fcdbe298213e910be74275160b"
EXPECTED_ENDPOINT_KEYS = frozenset({"host", "port", "started_at"})
EXPECTED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "deployment_root",
        "model",
        "spec_sha256",
        "endpoint_bundle_sha256",
        "approved_task_allowlist_sha256",
        "workers",
        "router",
    }
)
EXPECTED_WORKER_KEYS = frozenset({"metadata_file", "metadata_sha256", "host", "port", "started_at"})
FORBIDDEN_REQUEST_FIELDS = frozenset({"logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"})
HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
ENDPOINT_FILE_RE = re.compile(r"^[1-9][0-9]*\.json$")
MAX_METADATA_BYTES = 16 * 1024
MAX_MODELS_BYTES = 1 << 20
MAX_DIRECT_CONCURRENCY = 64
PRODUCTION_PROVIDER_CONCURRENCY = 32
LEGACY_PRODUCTION_PROVIDER_CONCURRENCY = 16
ROUTER_QUEUE_TIMEOUT_SECONDS = 7_200
PRODUCTION_MODEL_TIMEOUT_SECONDS = 15_000
AFFINITY_MANIFEST_SCHEMA_VERSION = 2
ROUTER_MANIFEST_SCHEMA_VERSION = 3
ADMISSION_SCHEMA_VERSION = 1
ROUTER_POLICY = "consistent_hash"
ROUTER_REQUEST_ID_HEADERS = ("x-session-id",)
ROUTING_TRANSITION_FILENAME = "qwen_router_transition.json"
ADMISSION_TRANSITION_FILENAME = "qwen_router_admission_transition.json"
ROUTING_EPOCH1_MANIFEST_FILENAME = "direct_workers.epoch-1.json"
ROUTING_EPOCH1_ROWS_FILENAME = "qwen_router_epoch1_rows.sha256"
ROUTING_EPOCH1_SOURCE_CONFIG_FILENAME = "source_config.epoch-1.toml"
ROUTING_EPOCH2_MANIFEST_FILENAME = "direct_workers.epoch-2.json"
ROUTING_EPOCH2_CONFIG_FILENAME = "config.epoch-2.toml"
ROUTING_EPOCH2_ROWS_FILENAME = "qwen_router_epoch2_lineage.jsonl"
ROUTING_EPOCH2_SOURCE_CONFIG_FILENAME = "source_config.epoch-2.toml"
ROUTING_EPOCH2_INPUTS_MANIFEST_FILENAME = "manifest.epoch-2.json"
ROUTING_EPOCH2_PROVENANCE_FILENAME = "provenance.epoch-2.txt"
ROUTING_TRANSITION_KIND = "qwen-direct-router-policy-transition"
ADMISSION_TRANSITION_KIND = "qwen-direct-router-admission-transition"
ADMISSION_VERIFIERS_REVISION = "04d999177f320e195e3335593688934f32e899d3"
ADMISSION_RESUME_MODULE_SHA256 = "091e99d44d59672422973d0db3abeaaac3ae68599c37e5964326d43fe5c9eb07"
MIGRATION_INCOMPLETE_FILENAME = ".migration_incomplete"


class DirectWorkerError(ValueError):
    """The direct-worker deployment or evaluation config is not the pinned one."""


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def reject_incomplete_migration(run_dir: Path) -> None:
    marker = run_dir / MIGRATION_INCOMPLETE_FILENAME
    if marker.exists() or marker.is_symlink():
        raise DirectWorkerError("direct_worker_migration_incomplete")


@dataclass(frozen=True)
class Worker:
    metadata_file: str
    metadata_sha256: str
    host: str
    port: int
    started_at: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _task_allowlist_count(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise DirectWorkerError("eval_approved_task_file_unreadable") from error
    tasks = [line.strip().split("\t", 1)[0] for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if any(not task for task in tasks):
        raise DirectWorkerError("eval_approved_task_file_entry_invalid")
    if len(tasks) != len(set(tasks)):
        raise DirectWorkerError("eval_approved_task_file_duplicates")
    return len(tasks)


def provider_concurrency(config: dict[str, Any]) -> int:
    """Return the explicitly pinned HTTP/provider concurrency for an eval."""
    max_concurrent = config.get("max_concurrent")
    client = config.get("client")
    if not isinstance(client, dict):
        raise DirectWorkerError("eval_client_invalid")
    fields = ("max_connections", "max_keepalive_connections")
    values = tuple(client.get(field) for field in fields)
    for field, value in zip(fields, values, strict=True):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not isinstance(max_concurrent, int)
            or isinstance(max_concurrent, bool)
            or not 1 <= value <= max_concurrent
        ):
            raise DirectWorkerError(f"eval_client_{field}_invalid")
    if values[0] != values[1]:
        raise DirectWorkerError("eval_client_provider_concurrency_mismatch")
    value = values[0]
    allowed = (
        {LEGACY_PRODUCTION_PROVIDER_CONCURRENCY, PRODUCTION_PROVIDER_CONCURRENCY}
        if max_concurrent == MAX_DIRECT_CONCURRENCY
        else {min(max_concurrent, EXPECTED_ENDPOINTS)}
    )
    if value not in allowed:
        raise DirectWorkerError("eval_client_provider_concurrency_invalid")
    return value


def endpoint_bundle_sha256(paths: list[Path]) -> str:
    """Hash the same stable ``sha256sum *.json`` representation used operationally."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(f"{_sha256(path)}  {path.name}\n".encode())
    return digest.hexdigest()


def _read_json_object(path: Path, max_bytes: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise DirectWorkerError(f"metadata_too_large:{path.name}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectWorkerError(f"metadata_invalid_json:{path.name}") from error
    if not isinstance(value, dict):
        raise DirectWorkerError(f"metadata_not_object:{path.name}")
    return value


def load_workers(
    deployment_root: Path,
    *,
    expected_spec_sha256: str = EXPECTED_SPEC_SHA256,
    expected_bundle_sha256: str = EXPECTED_ENDPOINT_BUNDLE_SHA256,
    expected_count: int = EXPECTED_ENDPOINTS,
) -> tuple[list[Worker], str, str]:
    root = deployment_root.resolve(strict=True)
    spec = root / "spec.yaml"
    endpoints_dir = root / "endpoints"
    if not spec.is_file() or spec.is_symlink():
        raise DirectWorkerError("spec_missing_or_symlink")
    spec_sha256 = _sha256(spec)
    if spec_sha256 != expected_spec_sha256:
        raise DirectWorkerError("spec_sha256_mismatch")
    if not endpoints_dir.is_dir() or endpoints_dir.is_symlink():
        raise DirectWorkerError("endpoints_directory_missing_or_symlink")

    paths = sorted(endpoints_dir.iterdir(), key=lambda path: path.name)
    if any(not path.is_file() or path.is_symlink() or ENDPOINT_FILE_RE.fullmatch(path.name) is None for path in paths):
        raise DirectWorkerError("unexpected_endpoint_directory_entry")
    if len(paths) != expected_count:
        raise DirectWorkerError(f"endpoint_count={len(paths)} expected={expected_count}")
    bundle_sha256 = endpoint_bundle_sha256(paths)
    if bundle_sha256 != expected_bundle_sha256:
        raise DirectWorkerError("endpoint_bundle_sha256_mismatch")

    workers: list[Worker] = []
    addresses: set[tuple[str, int]] = set()
    for path in paths:
        value = _read_json_object(path)
        if set(value) != EXPECTED_ENDPOINT_KEYS:
            raise DirectWorkerError(f"metadata_fields_invalid:{path.name}")
        host = value["host"]
        port = value["port"]
        started_at = value["started_at"]
        if not isinstance(host, str) or HOST_RE.fullmatch(host) is None:
            raise DirectWorkerError(f"metadata_host_invalid:{path.name}")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise DirectWorkerError(f"metadata_port_invalid:{path.name}")
        if not isinstance(started_at, str) or not started_at.strip():
            raise DirectWorkerError(f"metadata_started_at_invalid:{path.name}")
        address = (host, port)
        if address in addresses:
            raise DirectWorkerError(f"duplicate_endpoint:{path.name}")
        addresses.add(address)
        workers.append(Worker(path.name, _sha256(path), host, port, started_at))
    return workers, spec_sha256, bundle_sha256


def validate_eval_config(
    path: Path,
    *,
    approved_task_file: Path | None = None,
    approved_task_file_sha256: str | None = None,
) -> str:
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DirectWorkerError("eval_config_unreadable") from error

    if config.get("model") != EXPECTED_MODEL:
        raise DirectWorkerError("eval_model_mismatch")
    if not _is_plain_int(config.get("num_rollouts")) or config.get("num_rollouts") != 1:
        raise DirectWorkerError("eval_num_rollouts_mismatch")
    num_tasks = config.get("num_tasks")
    if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
        raise DirectWorkerError("eval_num_tasks_invalid")
    max_concurrent = config.get("max_concurrent")
    if (
        isinstance(max_concurrent, bool)
        or not isinstance(max_concurrent, int)
        or not 1 <= max_concurrent <= MAX_DIRECT_CONCURRENCY
    ):
        raise DirectWorkerError("eval_max_concurrent_invalid")
    multiplex = config.get("multiplex")
    if isinstance(multiplex, bool) or not isinstance(multiplex, int) or multiplex != max_concurrent:
        raise DirectWorkerError("eval_multiplex_invalid")
    for field in ("max_input_tokens", "max_output_tokens", "max_total_tokens"):
        value = config.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 262_144:
            raise DirectWorkerError(f"eval_{field}_invalid")

    taskset = config.get("taskset")
    if not isinstance(taskset, dict) or taskset.get("id") != "terminal-bench-vmvm":
        raise DirectWorkerError("eval_taskset_invalid")
    if "tasks" in taskset:
        raise DirectWorkerError("eval_inline_tasks_forbidden")
    task_file_value = taskset.get("task_file")
    task_file_sha256 = taskset.get("task_file_sha256")
    if not isinstance(task_file_value, str) or not task_file_value:
        raise DirectWorkerError("eval_approved_task_file_missing")
    if not isinstance(task_file_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", task_file_sha256) is None:
        raise DirectWorkerError("eval_approved_task_file_hash_missing")
    task_file = Path(task_file_value)
    if not task_file.is_absolute():
        task_file = Path.cwd() / task_file
    try:
        observed_task_file_sha256 = _sha256(task_file.resolve(strict=True))
    except OSError as error:
        raise DirectWorkerError("eval_approved_task_file_unreadable") from error
    if observed_task_file_sha256 != task_file_sha256:
        raise DirectWorkerError("eval_approved_task_file_hash_mismatch")
    if _task_allowlist_count(task_file) != num_tasks:
        raise DirectWorkerError("eval_approved_task_file_count_mismatch")
    if (approved_task_file is None) != (approved_task_file_sha256 is None):
        raise DirectWorkerError("external_task_approval_incomplete")
    if approved_task_file is not None and approved_task_file_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", approved_task_file_sha256) is None:
            raise DirectWorkerError("external_task_approval_hash_invalid")
        try:
            observed_approval_sha256 = _sha256(approved_task_file.resolve(strict=True))
        except OSError as error:
            raise DirectWorkerError("external_task_approval_unreadable") from error
        if observed_approval_sha256 != approved_task_file_sha256:
            raise DirectWorkerError("external_task_approval_hash_mismatch")
        if task_file_sha256 != approved_task_file_sha256:
            raise DirectWorkerError("eval_task_file_not_externally_approved")

    client = config.get("client")
    if not isinstance(client, dict) or client.get("type") != "eval":
        raise DirectWorkerError("eval_client_invalid")
    if client.get("capture_model_io") is not True:
        raise DirectWorkerError("eval_model_io_capture_disabled")
    if set(client.get("outbound_body_denylist") or []) != FORBIDDEN_REQUEST_FIELDS:
        raise DirectWorkerError("eval_request_denylist_mismatch")
    if client.get("timeout") != 7_200:
        raise DirectWorkerError("eval_client_timeout_mismatch")
    # vllm-router 0.1.26 implements ``max_concurrent_requests`` with a
    # replenishing token bucket, not a strict in-flight semaphore.  The one
    # shared HTTP/1.1 pool is therefore the authoritative provider bound.
    provider_concurrency(config)

    sampling = config.get("sampling")
    if not isinstance(sampling, dict):
        raise DirectWorkerError("eval_sampling_missing")
    if FORBIDDEN_REQUEST_FIELDS.intersection(sampling):
        raise DirectWorkerError("eval_sampling_requests_forbidden_fields")
    sampling_max_tokens = sampling.get("max_tokens")
    if (
        isinstance(sampling_max_tokens, bool)
        or not isinstance(sampling_max_tokens, int)
        or not 1 <= sampling_max_tokens <= 32_768
    ):
        raise DirectWorkerError("eval_output_token_limit_mismatch")
    template = sampling.get("chat_template_kwargs")
    if not isinstance(template, dict) or template.get("enable_thinking") is not True:
        raise DirectWorkerError("eval_thinking_not_enabled")
    if template.get("preserve_thinking") is not True:
        raise DirectWorkerError("eval_thinking_not_preserved")

    harness = config.get("harness")
    if not isinstance(harness, dict) or harness.get("id") != "mini-swe-agent":
        raise DirectWorkerError("eval_harness_invalid")
    config_overrides = harness.get("config_overrides")
    if not isinstance(config_overrides, list) or not all(isinstance(value, str) for value in config_overrides):
        raise DirectWorkerError("eval_harness_config_overrides_invalid")
    if max_concurrent == MAX_DIRECT_CONCURRENCY:
        timeout_overrides = [value for value in config_overrides if value.startswith("model.model_kwargs.timeout=")]
        if timeout_overrides != [f"model.model_kwargs.timeout={PRODUCTION_MODEL_TIMEOUT_SECONDS}"]:
            raise DirectWorkerError("eval_model_timeout_mismatch")
    runtime = harness.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("type") != "vmvm":
        raise DirectWorkerError("eval_runtime_not_vmvm")
    harness_env = harness.get("env")
    if not isinstance(harness_env, dict) or harness_env.get("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT") != "10":
        raise DirectWorkerError("eval_model_retry_policy_mismatch")
    retries = config.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
    retry_include = rollout_retries.get("include") if isinstance(rollout_retries, dict) else None
    if (
        not isinstance(rollout_retries, dict)
        or rollout_retries.get("max_retries") != 2
        or not isinstance(retry_include, list)
        or not all(isinstance(item, str) for item in retry_include)
        or set(retry_include) != {"ProviderError", "SandboxError", "TunnelError", "InterceptionError"}
    ):
        raise DirectWorkerError("eval_rollout_retry_policy_mismatch")
    return task_file_sha256


def _probe_worker(worker: Worker, model: str, timeout: float) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{worker.url}/health", timeout=timeout) as response:
            if response.status != 200:
                raise DirectWorkerError(f"health_status:{worker.metadata_file}:{response.status}")
            response.read(1)
        with opener.open(f"{worker.url}/v1/models", timeout=timeout) as response:
            if response.status != 200:
                raise DirectWorkerError(f"models_status:{worker.metadata_file}:{response.status}")
            raw = response.read(MAX_MODELS_BYTES + 1)
    except DirectWorkerError:
        raise
    except Exception as error:
        raise DirectWorkerError(f"worker_unreachable:{worker.metadata_file}:{type(error).__name__}") from error
    if len(raw) > MAX_MODELS_BYTES:
        raise DirectWorkerError(f"models_response_too_large:{worker.metadata_file}")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectWorkerError(f"models_invalid_json:{worker.metadata_file}") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    model_ids = (
        [item.get("id") for item in data]
        if isinstance(data, list) and all(isinstance(item, dict) for item in data)
        else []
    )
    if model_ids != [model]:
        raise DirectWorkerError(f"models_mismatch:{worker.metadata_file}")


def probe_workers(
    workers: list[Worker], model: str = EXPECTED_MODEL, concurrency: int = 8, timeout: float = 30
) -> None:
    if not 1 <= concurrency <= 8:
        raise DirectWorkerError("probe_concurrency_invalid")
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_probe_worker, worker, model, timeout) for worker in workers]
        for future in concurrent.futures.as_completed(futures):
            future.result()


def derive_ports(output_dir: Path) -> tuple[int, int]:
    digest = hashlib.sha256(str(output_dir.resolve()).encode()).digest()
    return 20_000 + int.from_bytes(digest[:4], "big") % 10_000, 40_000 + int.from_bytes(digest[4:8], "big") % 10_000


def _atomic_write(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise DirectWorkerError("direct_worker_manifest_already_exists") from error
            temporary.unlink()
        else:
            os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _manifest(
    deployment_root: Path,
    workers: list[Worker],
    spec_sha256: str,
    bundle_sha256: str,
    approved_task_allowlist_sha256: str,
    router_port: int,
    metrics_port: int,
    rollout_concurrency: int = 8,
    provider_concurrency: int | None = None,
    schema_version: int = ROUTER_MANIFEST_SCHEMA_VERSION,
) -> dict[str, Any]:
    if provider_concurrency is None:
        provider_concurrency = min(rollout_concurrency, EXPECTED_ENDPOINTS)
    if (
        isinstance(provider_concurrency, bool)
        or not isinstance(provider_concurrency, int)
        or not 1 <= provider_concurrency <= rollout_concurrency <= MAX_DIRECT_CONCURRENCY
    ):
        raise DirectWorkerError("direct_worker_provider_concurrency_invalid")
    max_concurrent_requests = provider_concurrency
    if schema_version not in {AFFINITY_MANIFEST_SCHEMA_VERSION, ROUTER_MANIFEST_SCHEMA_VERSION}:
        raise DirectWorkerError("direct_worker_manifest_schema_invalid")
    manifest = {
        "schema_version": schema_version,
        "deployment_root": str(deployment_root.resolve()),
        "model": EXPECTED_MODEL,
        "spec_sha256": spec_sha256,
        "endpoint_bundle_sha256": bundle_sha256,
        "approved_task_allowlist_sha256": approved_task_allowlist_sha256,
        "workers": [asdict(worker) for worker in workers],
        "router": {
            "host": "127.0.0.1",
            "port": router_port,
            "metrics_host": "127.0.0.1",
            "metrics_port": metrics_port,
            "policy": ROUTER_POLICY,
            "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
            "request_timeout_seconds": 7_500,
            "max_concurrent_requests": max_concurrent_requests,
            "queue_size": rollout_concurrency - max_concurrent_requests,
            "queue_timeout_seconds": ROUTER_QUEUE_TIMEOUT_SECONDS,
            "retries": 0,
        },
    }
    if schema_version == ROUTER_MANIFEST_SCHEMA_VERSION:
        manifest["admission"] = {
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "rollout_concurrency": rollout_concurrency,
            "client_max_connections": provider_concurrency,
            "client_max_keepalive_connections": provider_concurrency,
            "router_max_concurrent_requests": provider_concurrency,
            "router_queue_size": rollout_concurrency - provider_concurrency,
        }
    return manifest


def validate_saved_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_json_object(path, max_bytes=1 << 20)
    schema_version = manifest.get("schema_version")
    if not _is_plain_int(schema_version) or schema_version not in {
        AFFINITY_MANIFEST_SCHEMA_VERSION,
        ROUTER_MANIFEST_SCHEMA_VERSION,
    }:
        raise DirectWorkerError("direct_worker_manifest_schema_mismatch")
    expected_keys = EXPECTED_MANIFEST_KEYS | (
        {"admission"} if schema_version == ROUTER_MANIFEST_SCHEMA_VERSION else set()
    )
    if set(manifest) != expected_keys:
        raise DirectWorkerError("direct_worker_manifest_structure_invalid")
    if manifest.get("model") != EXPECTED_MODEL:
        raise DirectWorkerError("direct_worker_manifest_model_mismatch")
    if manifest.get("spec_sha256") != EXPECTED_SPEC_SHA256:
        raise DirectWorkerError("direct_worker_manifest_spec_mismatch")
    if manifest.get("endpoint_bundle_sha256") != EXPECTED_ENDPOINT_BUNDLE_SHA256:
        raise DirectWorkerError("direct_worker_manifest_bundle_mismatch")
    approved_task_allowlist_sha256 = manifest.get("approved_task_allowlist_sha256")
    if (
        not isinstance(approved_task_allowlist_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", approved_task_allowlist_sha256) is None
    ):
        raise DirectWorkerError("direct_worker_manifest_task_allowlist_invalid")

    raw_workers = manifest.get("workers")
    if not isinstance(raw_workers, list) or len(raw_workers) != EXPECTED_ENDPOINTS:
        raise DirectWorkerError("direct_worker_manifest_worker_count_invalid")
    names: set[str] = set()
    addresses: set[tuple[str, int]] = set()
    bundle = hashlib.sha256()
    for raw_worker in raw_workers:
        if not isinstance(raw_worker, dict) or set(raw_worker) != EXPECTED_WORKER_KEYS:
            raise DirectWorkerError("direct_worker_manifest_worker_invalid")
        name = raw_worker["metadata_file"]
        metadata_sha256 = raw_worker["metadata_sha256"]
        host = raw_worker["host"]
        port = raw_worker["port"]
        started_at = raw_worker["started_at"]
        if not isinstance(name, str) or ENDPOINT_FILE_RE.fullmatch(name) is None or name in names:
            raise DirectWorkerError("direct_worker_manifest_worker_name_invalid")
        if not isinstance(metadata_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", metadata_sha256) is None:
            raise DirectWorkerError("direct_worker_manifest_worker_hash_invalid")
        if not isinstance(host, str) or HOST_RE.fullmatch(host) is None:
            raise DirectWorkerError("direct_worker_manifest_worker_host_invalid")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise DirectWorkerError("direct_worker_manifest_worker_port_invalid")
        if not isinstance(started_at, str) or not started_at.strip():
            raise DirectWorkerError("direct_worker_manifest_worker_started_at_invalid")
        if (host, port) in addresses:
            raise DirectWorkerError("direct_worker_manifest_worker_duplicate")
        names.add(name)
        addresses.add((host, port))
        bundle.update(f"{metadata_sha256}  {name}\n".encode())
    if bundle.hexdigest() != EXPECTED_ENDPOINT_BUNDLE_SHA256:
        raise DirectWorkerError("direct_worker_manifest_worker_bundle_invalid")

    router = manifest.get("router")
    expected_router = {
        "host": "127.0.0.1",
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "request_timeout_seconds": 7_500,
        "queue_timeout_seconds": ROUTER_QUEUE_TIMEOUT_SECONDS,
        "retries": 0,
    }
    if (
        not isinstance(router, dict)
        or not _is_plain_int(router.get("retries"))
        or any(router.get(key) != value for key, value in expected_router.items())
    ):
        raise DirectWorkerError("direct_worker_manifest_router_invalid")
    if set(router) != {
        *expected_router,
        "max_concurrent_requests",
        "queue_size",
        "port",
        "metrics_host",
        "metrics_port",
    }:
        raise DirectWorkerError("direct_worker_manifest_router_structure_invalid")
    max_concurrent_requests = router.get("max_concurrent_requests")
    if (
        isinstance(max_concurrent_requests, bool)
        or not isinstance(max_concurrent_requests, int)
        or not 1
        <= max_concurrent_requests
        <= (EXPECTED_ENDPOINTS if schema_version == AFFINITY_MANIFEST_SCHEMA_VERSION else MAX_DIRECT_CONCURRENCY)
    ):
        raise DirectWorkerError("direct_worker_manifest_router_concurrency_invalid")
    queue_size = router.get("queue_size")
    if isinstance(queue_size, bool) or not isinstance(queue_size, int) or not 0 <= queue_size < MAX_DIRECT_CONCURRENCY:
        raise DirectWorkerError("direct_worker_manifest_router_queue_invalid")
    if max_concurrent_requests + queue_size > MAX_DIRECT_CONCURRENCY:
        raise DirectWorkerError("direct_worker_manifest_router_admission_exceeds_rollout_limit")
    if router.get("metrics_host") != "127.0.0.1":
        raise DirectWorkerError("direct_worker_manifest_metrics_host_invalid")
    ports = (router.get("port"), router.get("metrics_port"))
    if not all(isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 for port in ports):
        raise DirectWorkerError("direct_worker_manifest_ports_invalid")
    if schema_version == ROUTER_MANIFEST_SCHEMA_VERSION:
        admission = manifest.get("admission")
        admission_integer_fields = (
            "schema_version",
            "rollout_concurrency",
            "client_max_connections",
            "client_max_keepalive_connections",
            "router_max_concurrent_requests",
            "router_queue_size",
        )
        if (
            not isinstance(admission, dict)
            or not all(_is_plain_int(admission.get(field)) for field in admission_integer_fields)
            or admission
            != {
                "schema_version": ADMISSION_SCHEMA_VERSION,
                "rollout_concurrency": max_concurrent_requests + queue_size,
                "client_max_connections": max_concurrent_requests,
                "client_max_keepalive_connections": max_concurrent_requests,
                "router_max_concurrent_requests": max_concurrent_requests,
                "router_queue_size": queue_size,
            }
        ):
            raise DirectWorkerError("direct_worker_manifest_admission_invalid")
        if admission["rollout_concurrency"] == MAX_DIRECT_CONCURRENCY and (
            max_concurrent_requests != PRODUCTION_PROVIDER_CONCURRENCY
            or queue_size != MAX_DIRECT_CONCURRENCY - PRODUCTION_PROVIDER_CONCURRENCY
        ):
            raise DirectWorkerError("direct_worker_manifest_production_admission_invalid")
    return manifest


def _read_provenance(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise DirectWorkerError("direct_worker_provenance_unreadable") from error
    lowered = "\n".join(lines).casefold()
    if any(fragment in lowered for fragment in ("api_key", "authorization", "bearer ")):
        raise DirectWorkerError("direct_worker_provenance_contains_credential")
    values: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise DirectWorkerError("direct_worker_provenance_malformed")
        if key in values and not key.startswith("resume_"):
            raise DirectWorkerError("direct_worker_provenance_duplicate_key")
        values[key] = value
    return values


def validate_router_provenance(
    path: Path,
    manifest_sha256: str,
    provider_concurrency_value: int | None = None,
) -> dict[str, str]:
    provenance = _read_provenance(path)
    expected = {
        "direct_qwen_manifest_sha256": manifest_sha256,
        "direct_qwen_router_policy": ROUTER_POLICY,
        "direct_qwen_request_id_headers": ",".join(ROUTER_REQUEST_ID_HEADERS),
    }
    if provider_concurrency_value is not None:
        expected["direct_qwen_provider_concurrency"] = str(provider_concurrency_value)
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise DirectWorkerError("direct_worker_provenance_router_mismatch")
    try:
        entries = [line.partition("=") for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError) as error:
        raise DirectWorkerError("direct_worker_provenance_unreadable") from error
    transition_positions = [
        index
        for index, (key, separator, _value) in enumerate(entries)
        if separator and key in {"qwen_router_transition_sha256", "qwen_router_admission_transition_sha256"}
    ]
    transition_by_key = {
        key: index
        for index, (key, separator, _value) in enumerate(entries)
        if separator and key in {"qwen_router_transition_sha256", "qwen_router_admission_transition_sha256"}
    }
    if (
        "qwen_router_transition_sha256" in transition_by_key
        and "qwen_router_admission_transition_sha256" in transition_by_key
        and transition_by_key["qwen_router_transition_sha256"]
        >= transition_by_key["qwen_router_admission_transition_sha256"]
    ):
        raise DirectWorkerError("direct_worker_resume_provenance_boundary_invalid")
    resume_floor = transition_positions[-1] if transition_positions else -1
    resume_blocks: list[tuple[int, list[tuple[str, str]]]] = []
    current_start: int | None = None
    current_entries: list[tuple[str, str]] = []
    allowed_resume_boundaries = {
        "qwen_router_transition_sha256",
        "direct_qwen_provider_concurrency",
        "qwen_router_admission_transition_sha256",
    }
    for index, (key, separator, value) in enumerate(entries):
        if not separator:
            raise DirectWorkerError("direct_worker_provenance_malformed")
        if key == "resume_slurm_job_id":
            if current_start is not None:
                resume_blocks.append((current_start, current_entries))
            current_start = index
            current_entries = [(key, value)]
        elif key.startswith("resume_"):
            if current_start is None:
                raise DirectWorkerError("direct_worker_resume_provenance_boundary_invalid")
            current_entries.append((key, value))
        elif current_start is not None:
            if key not in allowed_resume_boundaries:
                raise DirectWorkerError("direct_worker_resume_provenance_boundary_invalid")
            resume_blocks.append((current_start, current_entries))
            current_start = None
            current_entries = []
    if current_start is not None:
        resume_blocks.append((current_start, current_entries))

    expected_resume = {f"resume_{key}": value for key, value in expected.items()}
    expected_resume_keys = set(expected_resume)
    resume_job_ids: set[str] = set()
    for position, block_entries in resume_blocks:
        keys = [key for key, _value in block_entries]
        if len(keys) != len(set(keys)):
            raise DirectWorkerError("direct_worker_resume_provenance_duplicate_key")
        block = dict(block_entries)
        resume_job_id = block.get("resume_slurm_job_id", "")
        if re.fullmatch(r"[1-9][0-9]*", resume_job_id) is None or resume_job_id in resume_job_ids:
            raise DirectWorkerError("direct_worker_resume_provenance_boundary_invalid")
        resume_job_ids.add(resume_job_id)
        if position <= resume_floor:
            continue
        observed_router_keys = {key for key in keys if key.startswith("resume_direct_qwen_")}
        if observed_router_keys != expected_resume_keys or any(
            block.get(key) != value for key, value in expected_resume.items()
        ):
            raise DirectWorkerError("direct_worker_resume_provenance_router_mismatch")
    return provenance


def upgrade_legacy_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the only supported schema-1 -> schema-2 routing-policy upgrade."""
    if set(manifest) != EXPECTED_MANIFEST_KEYS or manifest.get("schema_version") != 1:
        raise DirectWorkerError("legacy_direct_worker_manifest_structure_invalid")
    router = manifest.get("router")
    if not isinstance(router, dict):
        raise DirectWorkerError("legacy_direct_worker_manifest_router_invalid")
    expected_router_keys = {
        "host",
        "port",
        "metrics_host",
        "metrics_port",
        "policy",
        "request_timeout_seconds",
        "max_concurrent_requests",
        "queue_size",
        "queue_timeout_seconds",
        "retries",
    }
    if set(router) != expected_router_keys or router.get("policy") != "round_robin" or "request_id_headers" in router:
        raise DirectWorkerError("legacy_direct_worker_manifest_router_invalid")
    upgraded = copy.deepcopy(manifest)
    upgraded["schema_version"] = AFFINITY_MANIFEST_SCHEMA_VERSION
    upgraded["router"]["policy"] = ROUTER_POLICY
    upgraded["router"]["request_id_headers"] = list(ROUTER_REQUEST_ID_HEADERS)
    return upgraded


def _read_row_hashes(path: Path, label: str) -> list[str]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise DirectWorkerError(f"routing_transition_{label}_rows_unreadable") from error
    if any(re.fullmatch(r"[0-9a-f]{64}", line) is None for line in lines):
        raise DirectWorkerError(f"routing_transition_{label}_rows_invalid")
    if len(lines) != len(set(lines)):
        raise DirectWorkerError(f"routing_transition_{label}_rows_duplicate")
    return lines


def _read_epoch1_row_hashes(path: Path) -> list[str]:
    return _read_row_hashes(path, "epoch1")


def _read_epoch2_lineage(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            for raw in handle:
                if not raw.endswith(b"\n"):
                    raise DirectWorkerError("routing_transition_epoch2_lineage_incomplete")
                value = json.loads(raw)
                if (
                    not isinstance(value, dict)
                    or set(value) != {"row_sha256", "routing_epoch"}
                    or not isinstance(value.get("row_sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", value["row_sha256"]) is None
                    or not _is_plain_int(value.get("routing_epoch"))
                    or value.get("routing_epoch") not in {1, 2}
                ):
                    raise DirectWorkerError("routing_transition_epoch2_lineage_invalid")
                records.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectWorkerError("routing_transition_epoch2_lineage_unreadable") from error
    digests = [record["row_sha256"] for record in records]
    if len(digests) != len(set(digests)):
        raise DirectWorkerError("routing_transition_epoch2_lineage_duplicate")
    return records


def _validate_policy_transition(
    run_dir: Path,
    manifest: dict[str, Any],
    provenance: dict[str, str],
    *,
    transition_path: Path,
    manifest_path: Path,
    child_config_path: Path,
    child_source_config_path: Path,
    child_inputs_manifest_path: Path,
    provenance_path: Path,
    results_path: Path,
    expected_child_path: str,
    enforce_boundary: bool,
) -> dict[str, Any]:
    """Validate the immutable round-robin to affinity edge and row membership."""
    epoch1_manifest_path = run_dir / ROUTING_EPOCH1_MANIFEST_FILENAME
    epoch1_rows_path = run_dir / ROUTING_EPOCH1_ROWS_FILENAME
    epoch1_source_config_path = run_dir / "inputs" / ROUTING_EPOCH1_SOURCE_CONFIG_FILENAME
    if not all(
        path.is_file() and not path.is_symlink()
        for path in (
            transition_path,
            epoch1_manifest_path,
            epoch1_rows_path,
            epoch1_source_config_path,
        )
    ):
        raise DirectWorkerError("routing_transition_artifacts_incomplete")

    transition_sha256 = _sha256(transition_path)
    if provenance.get("qwen_router_transition_sha256") != transition_sha256:
        raise DirectWorkerError("routing_transition_provenance_hash_mismatch")
    if provenance.get("qwen_router_epoch") != "2":
        raise DirectWorkerError("routing_transition_provenance_epoch_mismatch")
    transition = _read_json_object(transition_path, max_bytes=1 << 20)
    if (
        set(transition)
        != {
            "schema_version",
            "kind",
            "source",
            "resume_plan",
            "from_router",
            "to_router",
            "child",
        }
        or not _is_plain_int(transition.get("schema_version"))
        or transition.get("schema_version") != 1
        or transition.get("kind") != ROUTING_TRANSITION_KIND
    ):
        raise DirectWorkerError("routing_transition_structure_invalid")

    source = transition.get("source")
    if not isinstance(source, dict) or set(source) != {
        "canonical_path",
        "slurm_job_id",
        "prime_rl",
        "verifiers",
        "renderers",
        "config_sha256",
        "source_config_sha256",
        "inputs_manifest_sha256",
        "provenance_sha256",
        "results_sha256",
        "results_size_bytes",
        "direct_workers_sha256",
    }:
        raise DirectWorkerError("routing_transition_source_invalid")
    hashes = {
        source.get("config_sha256"),
        source.get("source_config_sha256"),
        source.get("inputs_manifest_sha256"),
        source.get("provenance_sha256"),
        source.get("results_sha256"),
        source.get("direct_workers_sha256"),
    }
    revisions = {source.get("prime_rl"), source.get("verifiers"), source.get("renderers")}
    if (
        any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes)
        or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None for value in revisions)
        or not isinstance(source.get("canonical_path"), str)
        or not Path(source["canonical_path"]).is_absolute()
        or not isinstance(source.get("slurm_job_id"), str)
        or re.fullmatch(r"[1-9][0-9]*", source["slurm_job_id"]) is None
        or isinstance(source.get("results_size_bytes"), bool)
        or not isinstance(source.get("results_size_bytes"), int)
        or source["results_size_bytes"] < 0
    ):
        raise DirectWorkerError("routing_transition_source_invalid")

    resume_plan = transition.get("resume_plan")
    if not isinstance(resume_plan, dict) or set(resume_plan) != {
        "retained_results_sha256",
        "retained_results_size_bytes",
        "retained_row_count",
        "owed_rollout_count",
        "epoch1_row_hashes_sha256",
    }:
        raise DirectWorkerError("routing_transition_resume_plan_invalid")
    for key in ("retained_results_sha256", "epoch1_row_hashes_sha256"):
        value = resume_plan.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise DirectWorkerError("routing_transition_resume_plan_invalid")
    for key in ("retained_results_size_bytes", "retained_row_count", "owed_rollout_count"):
        value = resume_plan.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DirectWorkerError("routing_transition_resume_plan_invalid")
    if resume_plan["owed_rollout_count"] < 1:
        raise DirectWorkerError("routing_transition_nothing_owed")

    from_router = transition.get("from_router")
    if (
        not isinstance(from_router, dict)
        or not _is_plain_int(from_router.get("manifest_schema_version"))
        or from_router
        != {
            "manifest_schema_version": 1,
            "policy": "round_robin",
            "request_id_headers": [],
        }
    ):
        raise DirectWorkerError("routing_transition_source_router_invalid")
    to_router = transition.get("to_router")
    if not isinstance(to_router, dict) or set(to_router) != {
        "manifest_schema_version",
        "policy",
        "request_id_headers",
        "spec_sha256",
        "endpoint_bundle_sha256",
        "direct_workers_sha256",
    }:
        raise DirectWorkerError("routing_transition_target_router_invalid")
    if to_router != {
        "manifest_schema_version": AFFINITY_MANIFEST_SCHEMA_VERSION,
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "spec_sha256": manifest["spec_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "direct_workers_sha256": _sha256(manifest_path),
    }:
        raise DirectWorkerError("routing_transition_target_router_invalid")

    child = transition.get("child")
    if not isinstance(child, dict) or set(child) != {
        "canonical_path",
        "routing_epoch",
        "config_sha256",
        "source_config_sha256",
        "inputs_manifest_sha256",
    }:
        raise DirectWorkerError("routing_transition_child_invalid")
    if (
        child.get("canonical_path") != expected_child_path
        or child.get("canonical_path") == source["canonical_path"]
        or child.get("routing_epoch") != 2
        or child.get("config_sha256") != _sha256(child_config_path)
        or child.get("source_config_sha256") != _sha256(child_source_config_path)
        or child.get("inputs_manifest_sha256") != _sha256(child_inputs_manifest_path)
    ):
        raise DirectWorkerError("routing_transition_child_invalid")

    if _sha256(epoch1_manifest_path) != source["direct_workers_sha256"]:
        raise DirectWorkerError("routing_transition_epoch1_manifest_hash_mismatch")
    if _sha256(epoch1_source_config_path) != source["source_config_sha256"]:
        raise DirectWorkerError("routing_transition_epoch1_source_config_hash_mismatch")
    try:
        legacy_manifest = json.loads(epoch1_manifest_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectWorkerError("routing_transition_epoch1_manifest_invalid") from error
    if not isinstance(legacy_manifest, dict):
        raise DirectWorkerError("routing_transition_epoch1_manifest_invalid")
    upgraded_legacy = upgrade_legacy_manifest(legacy_manifest)
    if upgraded_legacy != manifest:
        raise DirectWorkerError("routing_transition_manifest_lineage_mismatch")

    if _sha256(epoch1_rows_path) != resume_plan["epoch1_row_hashes_sha256"]:
        raise DirectWorkerError("routing_transition_epoch1_rows_hash_mismatch")
    epoch1_row_hashes = _read_epoch1_row_hashes(epoch1_rows_path)
    if len(epoch1_row_hashes) != resume_plan["retained_row_count"]:
        raise DirectWorkerError("routing_transition_epoch1_rows_count_mismatch")

    if not results_path.is_file() or results_path.is_symlink():
        raise DirectWorkerError("routing_transition_results_missing")
    provenance_entries = provenance_path.read_text(encoding="utf-8").splitlines()
    transition_positions = [
        index for index, line in enumerate(provenance_entries) if line.startswith("qwen_router_transition_sha256=")
    ]
    if len(transition_positions) != 1:
        raise DirectWorkerError("routing_transition_provenance_marker_invalid")
    post_transition_resumes = sum(
        line.startswith("resume_slurm_job_id=") for line in provenance_entries[transition_positions[0] + 1 :]
    )
    if enforce_boundary and post_transition_resumes <= 1:
        with results_path.open("rb") as results:
            retained_prefix = results.read(resume_plan["retained_results_size_bytes"])
        if hashlib.sha256(retained_prefix).hexdigest() != resume_plan["retained_results_sha256"]:
            raise DirectWorkerError("routing_transition_epoch1_boundary_mismatch")
    observed: dict[str, int] = {}
    observed_order: list[str] = []
    with results_path.open("rb") as results:
        while raw := results.readline():
            if not raw.endswith(b"\n"):
                break
            digest = hashlib.sha256(raw).hexdigest()
            observed_order.append(digest)
            observed[digest] = observed.get(digest, 0) + 1
    if (
        enforce_boundary
        and post_transition_resumes <= 1
        and observed_order[: len(epoch1_row_hashes)] != epoch1_row_hashes
    ):
        raise DirectWorkerError("routing_transition_epoch1_boundary_mismatch")
    if any(observed.get(digest) != 1 for digest in epoch1_row_hashes):
        raise DirectWorkerError("routing_transition_epoch1_row_membership_mismatch")
    return transition


def _validate_admission_transition(
    run_dir: Path,
    manifest: dict[str, Any],
    provenance: dict[str, str],
) -> dict[str, Any]:
    """Validate the affinity cap-16 to cap-32 edge and its complete parent chain."""
    admission_path = run_dir / ADMISSION_TRANSITION_FILENAME
    policy_transition_path = run_dir / ROUTING_TRANSITION_FILENAME
    epoch2_manifest_path = run_dir / ROUTING_EPOCH2_MANIFEST_FILENAME
    epoch2_config_path = run_dir / ROUTING_EPOCH2_CONFIG_FILENAME
    epoch2_source_config_path = run_dir / "inputs" / ROUTING_EPOCH2_SOURCE_CONFIG_FILENAME
    epoch2_inputs_manifest_path = run_dir / "inputs" / ROUTING_EPOCH2_INPUTS_MANIFEST_FILENAME
    epoch2_provenance_path = run_dir / ROUTING_EPOCH2_PROVENANCE_FILENAME
    epoch2_rows_path = run_dir / ROUTING_EPOCH2_ROWS_FILENAME
    required = (
        admission_path,
        policy_transition_path,
        epoch2_manifest_path,
        epoch2_config_path,
        epoch2_source_config_path,
        epoch2_inputs_manifest_path,
        epoch2_provenance_path,
        epoch2_rows_path,
    )
    if not all(path.is_file() and not path.is_symlink() for path in required):
        raise DirectWorkerError("admission_transition_artifacts_incomplete")
    if provenance.get("qwen_router_epoch") != "3":
        raise DirectWorkerError("admission_transition_provenance_epoch_mismatch")
    admission_sha256 = _sha256(admission_path)
    if provenance.get("qwen_router_admission_transition_sha256") != admission_sha256:
        raise DirectWorkerError("admission_transition_provenance_hash_mismatch")

    transition = _read_json_object(admission_path, max_bytes=1 << 20)
    if (
        set(transition) != {"schema_version", "kind", "source", "resume_plan", "from_router", "to_router", "child"}
        or not _is_plain_int(transition.get("schema_version"))
        or transition.get("schema_version") != 1
        or transition.get("kind") != ADMISSION_TRANSITION_KIND
    ):
        raise DirectWorkerError("admission_transition_structure_invalid")

    source = transition.get("source")
    source_keys = {
        "canonical_path",
        "slurm_job_id",
        "prime_rl",
        "verifiers",
        "renderers",
        "config_sha256",
        "source_config_sha256",
        "inputs_manifest_sha256",
        "provenance_sha256",
        "results_sha256",
        "results_size_bytes",
        "direct_workers_sha256",
        "routing_transition_sha256",
    }
    if not isinstance(source, dict) or set(source) != source_keys:
        raise DirectWorkerError("admission_transition_source_invalid")
    hash_keys = {
        "config_sha256",
        "source_config_sha256",
        "inputs_manifest_sha256",
        "provenance_sha256",
        "results_sha256",
        "direct_workers_sha256",
        "routing_transition_sha256",
    }
    if any(
        not isinstance(source.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", source[key]) is None for key in hash_keys
    ):
        raise DirectWorkerError("admission_transition_source_invalid")
    if any(
        not isinstance(source.get(key), str) or re.fullmatch(r"[0-9a-f]{40}", source[key]) is None
        for key in ("prime_rl", "verifiers", "renderers")
    ):
        raise DirectWorkerError("admission_transition_source_invalid")
    if (
        not isinstance(source.get("canonical_path"), str)
        or not Path(source["canonical_path"]).is_absolute()
        or not isinstance(source.get("slurm_job_id"), str)
        or re.fullmatch(r"[1-9][0-9]*", source["slurm_job_id"]) is None
        or isinstance(source.get("results_size_bytes"), bool)
        or not isinstance(source.get("results_size_bytes"), int)
        or source["results_size_bytes"] < 0
    ):
        raise DirectWorkerError("admission_transition_source_invalid")

    archived = {
        "config_sha256": epoch2_config_path,
        "source_config_sha256": epoch2_source_config_path,
        "inputs_manifest_sha256": epoch2_inputs_manifest_path,
        "provenance_sha256": epoch2_provenance_path,
        "direct_workers_sha256": epoch2_manifest_path,
        "routing_transition_sha256": policy_transition_path,
    }
    if any(_sha256(path) != source[key] for key, path in archived.items()):
        raise DirectWorkerError("admission_transition_source_archive_mismatch")

    epoch2_manifest = validate_saved_manifest(epoch2_manifest_path)
    try:
        epoch2_config = tomllib.loads(epoch2_config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DirectWorkerError("admission_transition_epoch2_config_invalid") from error
    if (
        epoch2_config.get("max_concurrent") != MAX_DIRECT_CONCURRENCY
        or provider_concurrency(epoch2_config) != LEGACY_PRODUCTION_PROVIDER_CONCURRENCY
        or epoch2_manifest["router"].get("max_concurrent_requests") != LEGACY_PRODUCTION_PROVIDER_CONCURRENCY
        or epoch2_manifest["router"].get("queue_size")
        != MAX_DIRECT_CONCURRENCY - LEGACY_PRODUCTION_PROVIDER_CONCURRENCY
    ):
        raise DirectWorkerError("admission_transition_epoch2_admission_invalid")
    epoch2_provenance = validate_router_provenance(
        epoch2_provenance_path,
        source["direct_workers_sha256"],
    )
    epoch2_expected_url = f"http://127.0.0.1:{epoch2_manifest['router']['port']}/v1"
    if str(epoch2_config.get("client", {}).get("base_url", "")).rstrip("/") != epoch2_expected_url:
        raise DirectWorkerError("admission_transition_epoch2_config_url_mismatch")
    if str(epoch2_provenance.get("inference_base_url", "")).rstrip("/") != epoch2_expected_url:
        raise DirectWorkerError("admission_transition_epoch2_provenance_url_mismatch")
    if epoch2_provenance.get("inference_deployment_id"):
        raise DirectWorkerError("admission_transition_epoch2_deployment_id_present")
    if (
        epoch2_provenance.get("prime_rl") != source["prime_rl"]
        or epoch2_provenance.get("verifiers") != source["verifiers"]
        or epoch2_provenance.get("renderers") != source["renderers"]
    ):
        raise DirectWorkerError("admission_transition_source_revision_mismatch")
    _validate_policy_transition(
        run_dir,
        epoch2_manifest,
        epoch2_provenance,
        transition_path=policy_transition_path,
        manifest_path=epoch2_manifest_path,
        child_config_path=epoch2_config_path,
        child_source_config_path=epoch2_source_config_path,
        child_inputs_manifest_path=epoch2_inputs_manifest_path,
        provenance_path=epoch2_provenance_path,
        results_path=run_dir / "results.jsonl",
        expected_child_path=source["canonical_path"],
        enforce_boundary=False,
    )

    resume_plan = transition.get("resume_plan")
    if not isinstance(resume_plan, dict) or set(resume_plan) != {
        "retained_results_sha256",
        "retained_results_size_bytes",
        "retained_row_count",
        "owed_rollout_count",
        "epoch2_lineage_sha256",
        "selected_idxs_sha256",
        "planner_verifiers_revision",
        "planner_module_sha256",
        "num_rollouts",
        "group",
        "require_exact_tokens",
        "require_logprobs",
        "shuffle",
    }:
        raise DirectWorkerError("admission_transition_resume_plan_invalid")
    for key in ("retained_results_sha256", "epoch2_lineage_sha256", "selected_idxs_sha256"):
        if not isinstance(resume_plan.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", resume_plan[key]) is None:
            raise DirectWorkerError("admission_transition_resume_plan_invalid")
    for key in ("retained_results_size_bytes", "retained_row_count", "owed_rollout_count"):
        value = resume_plan.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DirectWorkerError("admission_transition_resume_plan_invalid")
    if resume_plan["owed_rollout_count"] < 1:
        raise DirectWorkerError("admission_transition_nothing_owed")
    if (
        resume_plan.get("planner_verifiers_revision") != source["verifiers"]
        or source["verifiers"] != ADMISSION_VERIFIERS_REVISION
        or resume_plan.get("planner_module_sha256") != ADMISSION_RESUME_MODULE_SHA256
        or not _is_plain_int(resume_plan.get("num_rollouts"))
        or resume_plan.get("num_rollouts") != 1
        or resume_plan.get("group") is not False
        or resume_plan.get("require_exact_tokens") is not False
        or resume_plan.get("require_logprobs") is not False
        or resume_plan.get("shuffle") is not False
    ):
        raise DirectWorkerError("admission_transition_resume_planner_invalid")
    try:
        active_config = tomllib.loads((run_dir / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DirectWorkerError("admission_transition_child_config_invalid") from error
    num_tasks = active_config.get("num_tasks")
    if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
        raise DirectWorkerError("admission_transition_child_config_invalid")
    if resume_plan["retained_row_count"] + resume_plan["owed_rollout_count"] != num_tasks:
        raise DirectWorkerError("admission_transition_resume_plan_cardinality_mismatch")
    selected_payload = "".join(f"{index}\n" for index in range(num_tasks)).encode()
    if hashlib.sha256(selected_payload).hexdigest() != resume_plan["selected_idxs_sha256"]:
        raise DirectWorkerError("admission_transition_selected_idxs_mismatch")
    if _sha256(epoch2_rows_path) != resume_plan["epoch2_lineage_sha256"]:
        raise DirectWorkerError("admission_transition_epoch2_lineage_hash_mismatch")
    retained_lineage = _read_epoch2_lineage(epoch2_rows_path)
    retained_hashes = [record["row_sha256"] for record in retained_lineage]
    if len(retained_hashes) != resume_plan["retained_row_count"]:
        raise DirectWorkerError("admission_transition_epoch2_lineage_count_mismatch")
    epoch1_hashes = set(_read_epoch1_row_hashes(run_dir / ROUTING_EPOCH1_ROWS_FILENAME))
    lineage_epoch1 = {record["row_sha256"] for record in retained_lineage if record["routing_epoch"] == 1}
    if lineage_epoch1 != epoch1_hashes:
        raise DirectWorkerError("admission_transition_parent_rows_missing")

    from_router = transition.get("from_router")
    expected_from = {
        "manifest_schema_version": AFFINITY_MANIFEST_SCHEMA_VERSION,
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "max_concurrent_requests": LEGACY_PRODUCTION_PROVIDER_CONCURRENCY,
        "queue_size": MAX_DIRECT_CONCURRENCY - LEGACY_PRODUCTION_PROVIDER_CONCURRENCY,
        "spec_sha256": epoch2_manifest["spec_sha256"],
        "endpoint_bundle_sha256": epoch2_manifest["endpoint_bundle_sha256"],
        "direct_workers_sha256": _sha256(epoch2_manifest_path),
    }
    if from_router != expected_from:
        raise DirectWorkerError("admission_transition_source_router_invalid")
    to_router = transition.get("to_router")
    expected_to = {
        "manifest_schema_version": ROUTER_MANIFEST_SCHEMA_VERSION,
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "max_concurrent_requests": PRODUCTION_PROVIDER_CONCURRENCY,
        "queue_size": MAX_DIRECT_CONCURRENCY - PRODUCTION_PROVIDER_CONCURRENCY,
        "spec_sha256": manifest["spec_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "direct_workers_sha256": _sha256(run_dir / "direct_workers.json"),
    }
    if to_router != expected_to:
        raise DirectWorkerError("admission_transition_target_router_invalid")
    if (
        manifest["router"].get("max_concurrent_requests") != PRODUCTION_PROVIDER_CONCURRENCY
        or manifest["router"].get("queue_size") != MAX_DIRECT_CONCURRENCY - PRODUCTION_PROVIDER_CONCURRENCY
    ):
        raise DirectWorkerError("admission_transition_target_admission_invalid")

    child = transition.get("child")
    if not isinstance(child, dict) or set(child) != {
        "canonical_path",
        "routing_epoch",
        "migration_prime_rl",
        "config_sha256",
        "source_config_sha256",
        "inputs_manifest_sha256",
    }:
        raise DirectWorkerError("admission_transition_child_invalid")
    if (
        child.get("canonical_path") != str(run_dir.resolve())
        or child.get("canonical_path") == source["canonical_path"]
        or child.get("routing_epoch") != 3
        or not isinstance(child.get("migration_prime_rl"), str)
        or re.fullmatch(r"[0-9a-f]{40}", child["migration_prime_rl"]) is None
        or child.get("config_sha256") != _sha256(run_dir / "config.toml")
        or child.get("source_config_sha256") != _sha256(run_dir / "inputs" / "source_config.toml")
        or child.get("inputs_manifest_sha256") != _sha256(run_dir / "inputs" / "manifest.json")
    ):
        raise DirectWorkerError("admission_transition_child_invalid")

    results_path = run_dir / "results.jsonl"
    if not results_path.is_file() or results_path.is_symlink():
        raise DirectWorkerError("admission_transition_results_missing")
    provenance_entries = (run_dir / "provenance.txt").read_text(encoding="utf-8").splitlines()
    markers = [
        index
        for index, line in enumerate(provenance_entries)
        if line.startswith("qwen_router_admission_transition_sha256=")
    ]
    if len(markers) != 1:
        raise DirectWorkerError("admission_transition_provenance_marker_invalid")
    post_transition_resumes = sum(
        line.startswith("resume_slurm_job_id=") for line in provenance_entries[markers[0] + 1 :]
    )
    if post_transition_resumes <= 1:
        with results_path.open("rb") as results:
            retained_prefix = results.read(resume_plan["retained_results_size_bytes"])
        if hashlib.sha256(retained_prefix).hexdigest() != resume_plan["retained_results_sha256"]:
            raise DirectWorkerError("admission_transition_epoch2_boundary_mismatch")
    observed: dict[str, int] = {}
    observed_order: list[str] = []
    with results_path.open("rb") as results:
        while raw := results.readline():
            if not raw.endswith(b"\n"):
                break
            digest = hashlib.sha256(raw).hexdigest()
            observed_order.append(digest)
            observed[digest] = observed.get(digest, 0) + 1
    if post_transition_resumes <= 1 and observed_order[: len(retained_hashes)] != retained_hashes:
        raise DirectWorkerError("admission_transition_epoch2_boundary_mismatch")
    if any(observed.get(digest) != 1 for digest in retained_hashes):
        raise DirectWorkerError("admission_transition_epoch2_row_membership_mismatch")
    return transition


def validate_routing_transition(
    run_dir: Path,
    manifest: dict[str, Any],
    provenance: dict[str, str],
    *,
    allow_incomplete: bool = False,
) -> dict[str, Any] | None:
    """Validate optional COW routing/admission lineage without decoding trace bodies."""
    if not allow_incomplete:
        reject_incomplete_migration(run_dir)
    policy_path = run_dir / ROUTING_TRANSITION_FILENAME
    admission_path = run_dir / ADMISSION_TRANSITION_FILENAME
    lineage_present = any(
        (
            policy_path.exists(),
            admission_path.exists(),
            (run_dir / ROUTING_EPOCH1_MANIFEST_FILENAME).exists(),
            (run_dir / ROUTING_EPOCH1_ROWS_FILENAME).exists(),
            (run_dir / "inputs" / ROUTING_EPOCH1_SOURCE_CONFIG_FILENAME).exists(),
            "qwen_router_transition_sha256" in provenance,
            "qwen_router_admission_transition_sha256" in provenance,
            "qwen_router_epoch" in provenance,
        )
    )
    if not lineage_present:
        return None
    epoch = provenance.get("qwen_router_epoch")
    if epoch == "2":
        if admission_path.exists() or "qwen_router_admission_transition_sha256" in provenance:
            raise DirectWorkerError("admission_transition_unexpected_for_epoch2")
        return _validate_policy_transition(
            run_dir,
            manifest,
            provenance,
            transition_path=policy_path,
            manifest_path=run_dir / "direct_workers.json",
            child_config_path=run_dir / "config.toml",
            child_source_config_path=run_dir / "inputs" / "source_config.toml",
            child_inputs_manifest_path=run_dir / "inputs" / "manifest.json",
            provenance_path=run_dir / "provenance.txt",
            results_path=run_dir / "results.jsonl",
            expected_child_path=str(run_dir.resolve()),
            enforce_boundary=True,
        )
    if epoch == "3":
        return _validate_admission_transition(run_dir, manifest, provenance)
    raise DirectWorkerError("routing_transition_provenance_epoch_mismatch")


def audit_run_directory(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    reject_incomplete_migration(run_dir)
    manifest_path = run_dir / "direct_workers.json"
    manifest = validate_saved_manifest(manifest_path)
    manifest_sha256 = _sha256(manifest_path)
    config_path = run_dir / "config.toml"
    task_allowlist_sha256 = validate_eval_config(config_path)
    if task_allowlist_sha256 != manifest["approved_task_allowlist_sha256"]:
        raise DirectWorkerError("direct_worker_saved_task_allowlist_mismatch")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    expected_router_concurrency = provider_concurrency(config)
    expected_queue_size = config["max_concurrent"] - expected_router_concurrency
    if manifest["router"]["max_concurrent_requests"] != expected_router_concurrency:
        raise DirectWorkerError("direct_worker_saved_router_concurrency_mismatch")
    if manifest["router"]["queue_size"] != expected_queue_size:
        raise DirectWorkerError("direct_worker_saved_router_queue_mismatch")
    expected_base_url = f"http://127.0.0.1:{manifest['router']['port']}/v1"
    if str(config["client"].get("base_url", "")).rstrip("/") != expected_base_url:
        raise DirectWorkerError("direct_worker_saved_config_url_mismatch")

    provenance = validate_router_provenance(
        run_dir / "provenance.txt",
        manifest_sha256,
        manifest["router"]["max_concurrent_requests"]
        if manifest["schema_version"] == ROUTER_MANIFEST_SCHEMA_VERSION
        else None,
    )
    if str(provenance.get("inference_base_url", "")).rstrip("/") != expected_base_url:
        raise DirectWorkerError("direct_worker_provenance_url_mismatch")
    if provenance.get("inference_deployment_id"):
        raise DirectWorkerError("direct_worker_provenance_deployment_id_present")
    transition = validate_routing_transition(run_dir, manifest, provenance)

    inputs_manifest = _read_json_object(run_dir / "inputs" / "manifest.json", max_bytes=1 << 20)
    config_record = inputs_manifest.get("config")
    task_file_record = inputs_manifest.get("task_file")
    source_config = run_dir / "inputs" / "source_config.toml"
    task_file_snapshot = run_dir / "inputs" / "task_file.txt"
    if not isinstance(config_record, dict):
        raise DirectWorkerError("direct_worker_input_config_record_missing")
    if Path(str(config_record.get("snapshot", ""))).resolve() != source_config.resolve():
        raise DirectWorkerError("direct_worker_input_config_snapshot_mismatch")
    if config_record.get("sha256") != _sha256(source_config):
        raise DirectWorkerError("direct_worker_input_config_hash_mismatch")
    if not isinstance(task_file_record, dict):
        raise DirectWorkerError("direct_worker_input_task_file_record_missing")
    if Path(str(task_file_record.get("snapshot", ""))).resolve() != task_file_snapshot.resolve():
        raise DirectWorkerError("direct_worker_input_task_file_snapshot_mismatch")
    if task_file_record.get("sha256") != manifest["approved_task_allowlist_sha256"]:
        raise DirectWorkerError("direct_worker_input_task_file_hash_mismatch")
    if _sha256(task_file_snapshot) != manifest["approved_task_allowlist_sha256"]:
        raise DirectWorkerError("direct_worker_task_file_snapshot_hash_mismatch")
    source_task_allowlist_sha256 = validate_eval_config(source_config)
    if source_task_allowlist_sha256 != manifest["approved_task_allowlist_sha256"]:
        raise DirectWorkerError("direct_worker_source_task_allowlist_mismatch")
    try:
        source_config_data = tomllib.loads(source_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DirectWorkerError("direct_worker_source_config_unreadable") from error
    active_taskset = config.get("taskset")
    source_taskset = source_config_data.get("taskset")
    if not isinstance(active_taskset, dict) or not isinstance(source_taskset, dict):
        raise DirectWorkerError("direct_worker_input_taskset_invalid")
    image_record = inputs_manifest.get("image_manifest")
    image_values = (
        active_taskset.get("image_manifest"),
        active_taskset.get("image_manifest_sha256"),
        source_taskset.get("image_manifest"),
        source_taskset.get("image_manifest_sha256"),
        image_record,
    )
    if any(value is not None for value in image_values):
        image_snapshot = run_dir / "inputs" / "image_manifest.json"
        if (
            not isinstance(image_record, dict)
            or set(image_record) != {"source", "snapshot", "sha256"}
            or not image_snapshot.is_file()
            or image_snapshot.is_symlink()
            or Path(str(active_taskset.get("image_manifest", ""))).resolve() != image_snapshot.resolve()
            or Path(str(image_record.get("snapshot", ""))).resolve() != image_snapshot.resolve()
            or not isinstance(image_record.get("source"), str)
            or not image_record["source"]
            or not isinstance(image_record.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", image_record["sha256"]) is None
            or active_taskset.get("image_manifest_sha256") != image_record["sha256"]
            or source_taskset.get("image_manifest_sha256") != image_record["sha256"]
            or _sha256(image_snapshot) != image_record["sha256"]
        ):
            raise DirectWorkerError("direct_worker_image_manifest_snapshot_mismatch")
    return {
        "ok": True,
        "model": manifest["model"],
        "endpoints": len(manifest["workers"]),
        "spec_sha256": manifest["spec_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "manifest_sha256": manifest_sha256,
        "manifest_schema_version": manifest["schema_version"],
        "provider_concurrency": manifest["router"]["max_concurrent_requests"],
        "queue_size": manifest["router"]["queue_size"],
        "router_policy": manifest["router"]["policy"],
        "request_id_headers": manifest["router"]["request_id_headers"],
        "routing_epoch": int(provenance["qwen_router_epoch"]) if transition is not None else 1,
    }


def prepare(
    deployment_root: Path,
    eval_config: Path,
    manifest_path: Path,
    urls_output: Path,
    ports_output: Path,
    approved_task_file: Path,
    approved_task_file_sha256: str,
    *,
    resume: bool,
    probe_timeout: float,
) -> dict[str, Any]:
    reject_incomplete_migration(manifest_path.parent)
    task_allowlist_sha256 = validate_eval_config(
        eval_config,
        approved_task_file=approved_task_file,
        approved_task_file_sha256=approved_task_file_sha256,
    )
    config = tomllib.loads(eval_config.read_text(encoding="utf-8"))
    rollout_concurrency = config["max_concurrent"]
    max_concurrent_requests = provider_concurrency(config)
    if rollout_concurrency == MAX_DIRECT_CONCURRENCY and max_concurrent_requests != PRODUCTION_PROVIDER_CONCURRENCY:
        raise DirectWorkerError("direct_worker_admission_epoch_migration_required")
    if resume:
        if not manifest_path.is_file():
            raise DirectWorkerError("direct_worker_manifest_missing")
        saved = validate_saved_manifest(manifest_path)
        provenance = validate_router_provenance(
            manifest_path.parent / "provenance.txt",
            _sha256(manifest_path),
            saved["router"]["max_concurrent_requests"]
            if saved["schema_version"] == ROUTER_MANIFEST_SCHEMA_VERSION
            else None,
        )
        validate_routing_transition(manifest_path.parent, saved, provenance)
        router = saved.get("router")
        if not isinstance(router, dict):
            raise DirectWorkerError("direct_worker_manifest_router_invalid")
        router_port = router.get("port")
        metrics_port = router.get("metrics_port")
        if not all(
            isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
            for port in (router_port, metrics_port)
        ):
            raise DirectWorkerError("direct_worker_manifest_ports_invalid")
        saved_config = tomllib.loads(eval_config.read_text(encoding="utf-8"))
        expected_base_url = f"http://127.0.0.1:{router_port}/v1"
        if str(saved_config["client"].get("base_url", "")).rstrip("/") != expected_base_url:
            raise DirectWorkerError("resume_router_url_mismatch")
        workers, spec_sha256, bundle_sha256 = load_workers(deployment_root)
        probe_workers(workers, timeout=probe_timeout)
        expected = _manifest(
            deployment_root,
            workers,
            spec_sha256,
            bundle_sha256,
            task_allowlist_sha256,
            router_port,
            metrics_port,
            rollout_concurrency,
            max_concurrent_requests,
            saved["schema_version"],
        )
        if saved != expected:
            raise DirectWorkerError("direct_worker_manifest_mismatch")
        manifest = saved
    else:
        workers, spec_sha256, bundle_sha256 = load_workers(deployment_root)
        probe_workers(workers, timeout=probe_timeout)
        router_port, metrics_port = derive_ports(manifest_path.parent)
        manifest = _manifest(
            deployment_root,
            workers,
            spec_sha256,
            bundle_sha256,
            task_allowlist_sha256,
            router_port,
            metrics_port,
            rollout_concurrency,
            max_concurrent_requests,
        )
        _atomic_write(
            manifest_path,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            exclusive=True,
        )

    _atomic_write(urls_output, "".join(f"{worker.url}\n" for worker in workers).encode())
    _atomic_write(
        ports_output,
        (
            f"{manifest['router']['port']}\n"
            f"{manifest['router']['metrics_port']}\n"
            f"{manifest['router']['max_concurrent_requests']}\n"
            f"{manifest['router']['queue_size']}\n"
            f"{manifest['router']['queue_timeout_seconds']}\n"
            f"{manifest['router']['policy']}\n"
            f"{manifest['router']['request_id_headers'][0]}\n"
        ).encode(),
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-root", type=Path)
    parser.add_argument("--eval-config", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--urls-output", type=Path)
    parser.add_argument("--ports-output", type=Path)
    parser.add_argument("--approved-task-file", type=Path)
    parser.add_argument("--approved-task-file-sha256")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--probe-timeout", type=float, default=30)
    parser.add_argument("--audit-run-dir", type=Path)
    args = parser.parse_args()
    if args.probe_timeout <= 0:
        parser.error("--probe-timeout must be positive")
    try:
        if args.audit_run_dir is not None:
            if (
                any(
                    value is not None
                    for value in (
                        args.deployment_root,
                        args.eval_config,
                        args.manifest,
                        args.urls_output,
                        args.ports_output,
                        args.approved_task_file,
                        args.approved_task_file_sha256,
                    )
                )
                or args.resume
            ):
                parser.error("--audit-run-dir cannot be combined with launch preparation arguments")
            summary = audit_run_directory(args.audit_run_dir)
        else:
            required = {
                "--deployment-root": args.deployment_root,
                "--eval-config": args.eval_config,
                "--manifest": args.manifest,
                "--urls-output": args.urls_output,
                "--ports-output": args.ports_output,
                "--approved-task-file": args.approved_task_file,
                "--approved-task-file-sha256": args.approved_task_file_sha256,
            }
            if missing := [name for name, value in required.items() if value is None]:
                parser.error(f"missing required arguments: {', '.join(missing)}")
            manifest = prepare(
                args.deployment_root,
                args.eval_config,
                args.manifest,
                args.urls_output,
                args.ports_output,
                args.approved_task_file,
                args.approved_task_file_sha256,
                resume=args.resume,
                probe_timeout=args.probe_timeout,
            )
            summary = {
                "ok": True,
                "model": manifest["model"],
                "endpoints": len(manifest["workers"]),
                "spec_sha256": manifest["spec_sha256"],
                "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
                "router_policy": manifest["router"]["policy"],
                "request_id_headers": manifest["router"]["request_id_headers"],
            }
    except (OSError, DirectWorkerError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
