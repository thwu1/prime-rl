#!/usr/bin/env python3
"""Validate and snapshot the fixed direct-worker Qwen deployment."""

from __future__ import annotations

import argparse
import concurrent.futures
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


class DirectWorkerError(ValueError):
    """The direct-worker deployment or evaluation config is not the pinned one."""


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
    if config.get("num_rollouts") != 1:
        raise DirectWorkerError("eval_num_rollouts_mismatch")
    num_tasks = config.get("num_tasks")
    if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
        raise DirectWorkerError("eval_num_tasks_invalid")
    max_concurrent = config.get("max_concurrent")
    if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int) or not 1 <= max_concurrent <= 8:
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
    for field in ("max_connections", "max_keepalive_connections"):
        value = client.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not max_concurrent <= value <= 8:
            raise DirectWorkerError(f"eval_client_{field}_invalid")

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
) -> dict[str, Any]:
    return {
        "schema_version": 1,
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
            "policy": "consistent_hash",
            "request_timeout_seconds": 7_500,
            "max_concurrent_requests": 8,
            "retries": 0,
        },
    }


def validate_saved_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_json_object(path, max_bytes=1 << 20)
    if set(manifest) != EXPECTED_MANIFEST_KEYS or manifest.get("schema_version") != 1:
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
        "policy": "consistent_hash",
        "request_timeout_seconds": 7_500,
        "max_concurrent_requests": 8,
        "retries": 0,
    }
    if not isinstance(router, dict) or any(router.get(key) != value for key, value in expected_router.items()):
        raise DirectWorkerError("direct_worker_manifest_router_invalid")
    if set(router) != {*expected_router, "port", "metrics_host", "metrics_port"}:
        raise DirectWorkerError("direct_worker_manifest_router_structure_invalid")
    if router.get("metrics_host") != "127.0.0.1":
        raise DirectWorkerError("direct_worker_manifest_metrics_host_invalid")
    ports = (router.get("port"), router.get("metrics_port"))
    if not all(isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 for port in ports):
        raise DirectWorkerError("direct_worker_manifest_ports_invalid")
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


def audit_run_directory(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    manifest = validate_saved_manifest(run_dir / "direct_workers.json")
    config_path = run_dir / "config.toml"
    task_allowlist_sha256 = validate_eval_config(config_path)
    if task_allowlist_sha256 != manifest["approved_task_allowlist_sha256"]:
        raise DirectWorkerError("direct_worker_saved_task_allowlist_mismatch")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    expected_base_url = f"http://127.0.0.1:{manifest['router']['port']}/v1"
    if str(config["client"].get("base_url", "")).rstrip("/") != expected_base_url:
        raise DirectWorkerError("direct_worker_saved_config_url_mismatch")

    provenance = _read_provenance(run_dir / "provenance.txt")
    if str(provenance.get("inference_base_url", "")).rstrip("/") != expected_base_url:
        raise DirectWorkerError("direct_worker_provenance_url_mismatch")
    if provenance.get("inference_deployment_id"):
        raise DirectWorkerError("direct_worker_provenance_deployment_id_present")

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
    return {
        "ok": True,
        "model": manifest["model"],
        "endpoints": len(manifest["workers"]),
        "spec_sha256": manifest["spec_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
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
    task_allowlist_sha256 = validate_eval_config(
        eval_config,
        approved_task_file=approved_task_file,
        approved_task_file_sha256=approved_task_file_sha256,
    )
    workers, spec_sha256, bundle_sha256 = load_workers(deployment_root)
    probe_workers(workers, timeout=probe_timeout)

    if resume:
        if not manifest_path.is_file():
            raise DirectWorkerError("direct_worker_manifest_missing")
        saved = validate_saved_manifest(manifest_path)
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
        expected = _manifest(
            deployment_root,
            workers,
            spec_sha256,
            bundle_sha256,
            task_allowlist_sha256,
            router_port,
            metrics_port,
        )
        if saved != expected:
            raise DirectWorkerError("direct_worker_manifest_mismatch")
        saved_config = tomllib.loads(eval_config.read_text(encoding="utf-8"))
        expected_base_url = f"http://127.0.0.1:{router_port}/v1"
        if str(saved_config["client"].get("base_url", "")).rstrip("/") != expected_base_url:
            raise DirectWorkerError("resume_router_url_mismatch")
        manifest = saved
    else:
        router_port, metrics_port = derive_ports(manifest_path.parent)
        manifest = _manifest(
            deployment_root,
            workers,
            spec_sha256,
            bundle_sha256,
            task_allowlist_sha256,
            router_port,
            metrics_port,
        )
        _atomic_write(
            manifest_path,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            exclusive=True,
        )

    _atomic_write(urls_output, "".join(f"{worker.url}\n" for worker in workers).encode())
    _atomic_write(ports_output, f"{manifest['router']['port']}\n{manifest['router']['metrics_port']}\n".encode())
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
            }
    except (OSError, DirectWorkerError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
