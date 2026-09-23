#!/usr/bin/env python3
"""Measure and certify the bounded Kimi direct-router/Sandoq c64 profile."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import http.client
import json
import os
import re
import stat
import threading
import time
import tomllib
import urllib.parse
from pathlib import Path
from typing import Any

from direct_kimi_router import C64_CAPACITY_PROFILE, POLICY, RETRIES, SESSION_HEADER
from direct_kimi_workers import (
    EXPECTED_ENDPOINT_IDENTIFIER,
    EXPECTED_ENDPOINTS,
    EXPECTED_MODEL,
    ROUTER_MAX_PROVIDER_CONCURRENCY,
    _atomic_write,
    load_saved_manifest,
    read_published_file,
)

CAPACITY = 64
CAPACITY_KIND = "direct-kimi-sandoq-capacity"
CAPACITY_SCHEMA_VERSION = 2
CAPACITY_FILENAME = "direct_kimi_capacity_certificate.json"
PROBE_KIND = "direct-kimi-router-capacity-probe"
PROBE_SCHEMA_VERSION = 1
PROBE_FILENAME = "direct_kimi_capacity_probe.json"
PROBE_ROUNDS = 2
MAX_RESPONSE_BYTES = 1 << 20
MAX_SEQUENCE_TOKENS = 262_144
MAX_GENERATION_TOKENS = 32_768
MINISWE_VERSION = "2.4.6"
MINISWE_MAX_STEPS = 3
PROVIDER_ENVIRONMENT = "oci-runner-firecracker"
PROVIDER_TASK_NETWORK = "host"
PROVIDER_PROFILE_SHA256 = "7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df"
RUNTIME_RESOURCE_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-full-resource-20260922/run-1537410/receipt.json"
)
RUNTIME_RESOURCE_RECEIPT_SHA256 = "ce3fc3ed2ead1aaf8c71fc35e5dae324f1be9d51b4e7fffff7bc99d1a47adbf6"
RUNTIME_TUNNEL_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-full-tunnel-20260922/run-1537377/receipt.json"
)
RUNTIME_TUNNEL_RECEIPT_SHA256 = "39108c28f052f4689e863fedaa81430b479915797a4e6836ed090344c5ee3276"
VERIFIERS_COMMIT = "f9dcefb73ac341de5f707600d54dba838ad1ce97"
MINISWE_LIVE_SMOKE_KIND = "qwen-miniswe246-sandoq-three-step-smoke"
MINISWE_LIVE_SMOKE_ENVIRONMENT = "oci-runner-firecracker-small"
MINISWE_LIVE_SMOKE_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/"
    "qwen-miniswe246-sandoq-3step-20260921/run-1537041/receipt.json"
)
MINISWE_LIVE_SMOKE_RECEIPT_SHA256 = "cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220"
CAPACITY_SELECTOR_KIND = "kimi-k3-max-sandoq-capacity-selector"
APPROVED_SOURCE_COUNT = 2_500
APPROVED_SOURCE_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
CAPACITY_CANDIDATE_COUNT = 2_499
DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
DATASET_TREE = "a6c036e1b9abfd7075902ca38ef757587079a59b"
PROVIDER_CONTEXT_FILENAME = "sandoq-provider-context.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TASK_FILE_PLACEHOLDER = "/REPLACE/WITH/PRIVATE/CAPACITY_SELECTOR.txt"
TASK_SHA256_PLACEHOLDER = "REPLACE_WITH_SHA256"
KIMI_CAPACITY_SMOKE_ROLE = "kimi-direct-capacity-smoke"
MINISWE_OVERRIDES = (
    "agent.step_limit=3",
    "environment.environment_class=local",
    "environment.timeout=1800",
    "model.model_kwargs.drop_params=true",
    "model.model_kwargs.timeout=1800",
    "model.model_kwargs.temperature=1.0",
    "model.model_kwargs.top_p=1.0",
    "model.model_kwargs.parallel_tool_calls=false",
)


def _provider_profile_path() -> Path:
    return (
        Path(__file__).resolve(strict=True).parent / "configs/provider_context/use2/kimi_sandoq_firecracker_host.json"
    )


class DirectKimiCapacityError(ValueError):
    """A capacity input or observation did not satisfy the sealed c64 contract."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _read_regular(path: Path, *, maximum_bytes: int = 16 * 1024 * 1024) -> bytes:
    try:
        resolved = path.resolve(strict=True)
        before = path.lstat()
        if resolved != path or path.is_symlink():
            raise DirectKimiCapacityError("artifact_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise DirectKimiCapacityError("artifact_invalid") from error
    try:
        opened = os.fstat(descriptor)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > maximum_bytes:
                raise DirectKimiCapacityError("artifact_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise DirectKimiCapacityError("artifact_invalid")
    return bytes(body)


def _sha256_regular(path: Path, *, maximum_bytes: int = 1 << 34) -> str:
    try:
        resolved = path.resolve(strict=True)
        before = path.lstat()
        if resolved != path or path.is_symlink():
            raise DirectKimiCapacityError("artifact_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise DirectKimiCapacityError("artifact_invalid") from error
    digest = hashlib.sha256()
    observed_bytes = 0
    try:
        opened = os.fstat(descriptor)
        while chunk := os.read(descriptor, 1 << 20):
            observed_bytes += len(chunk)
            if observed_bytes > maximum_bytes:
                raise DirectKimiCapacityError("artifact_invalid")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or observed_bytes != opened.st_size
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise DirectKimiCapacityError("artifact_invalid")
    return digest.hexdigest()


def _artifact(path: Path, *, published: bool = False) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    digest = _sha256_bytes(read_published_file(resolved)) if published else _sha256_regular(resolved)
    return {"path": str(resolved), "sha256": digest}


def _published_json(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    try:
        body = read_published_file(path)
        value = json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise DirectKimiCapacityError(code) from error
    if not isinstance(value, dict):
        raise DirectKimiCapacityError(code)
    return value, body


def _strict_json_regular(
    path: Path,
    code: str,
    *,
    expected_sha256: str | None = None,
    private: bool = False,
) -> tuple[dict[str, Any], bytes]:
    try:
        metadata = path.lstat()
        body = _read_regular(path)

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate_key")
                value[key] = item
            return value

        value = json.loads(
            body,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise DirectKimiCapacityError(code) from error
    if (
        not isinstance(value, dict)
        or (expected_sha256 is not None and _sha256_bytes(body) != expected_sha256)
        or (private and (metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600))
    ):
        raise DirectKimiCapacityError(code)
    return value, body


def _validate_capacity_selector_receipt(
    path: Path,
    expected_sha256: str,
    *,
    selector_sha256: str,
) -> tuple[dict[str, Any], bytes]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise DirectKimiCapacityError("capacity_selector_receipt_invalid")
    value, body = _strict_json_regular(
        path,
        "capacity_selector_receipt_invalid",
        expected_sha256=expected_sha256,
        private=True,
    )
    approved = value.get("approved_source")
    dataset = value.get("dataset")
    selection = value.get("selection")
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "deployment_namespace",
            "approved_source",
            "dataset",
            "selection",
            "selection_contract_sha256",
        }
        or value.get("schema_version") != 1
        or value.get("kind") != CAPACITY_SELECTOR_KIND
        or value.get("state") != "materialized"
        or value.get("deployment_namespace") != EXPECTED_ENDPOINT_IDENTIFIER
        or not isinstance(approved, dict)
        or set(approved) != {"count", "sha256"}
        or approved.get("count") != APPROVED_SOURCE_COUNT
        or approved.get("sha256") != APPROVED_SOURCE_SHA256
        or not isinstance(dataset, dict)
        or set(dataset) != {"revision", "tree"}
        or dataset.get("revision") != DATASET_REVISION
        or dataset.get("tree") != DATASET_TREE
        or not isinstance(selection, dict)
        or set(selection)
        != {
            "algorithm",
            "candidate_count",
            "membership_disclosed",
            "selected_count",
            "selected_sha256",
        }
        or selection.get("algorithm") != "sha256-canonical-index-v1"
        or selection.get("candidate_count") != CAPACITY_CANDIDATE_COUNT
        or selection.get("membership_disclosed") is not False
        or selection.get("selected_count") != CAPACITY
        or selection.get("selected_sha256") != selector_sha256
        or value.get("selection_contract_sha256") != _sha256_bytes(_canonical_json(selection))
    ):
        raise DirectKimiCapacityError("capacity_selector_receipt_invalid")
    return value, body


def _validate_provider_profile() -> tuple[Path, bytes]:
    path = _provider_profile_path().resolve(strict=True)
    value, body = _strict_json_regular(
        path,
        "capacity_provider_profile_invalid",
        expected_sha256=PROVIDER_PROFILE_SHA256,
    )
    if value != {
        "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "cluster_identifier": "use2",
        "effective_task_network": "public",
        "environment": PROVIDER_ENVIRONMENT,
        "provider_token_file": "/home/tianhaowu/.config/oci-runner/firecracker-token",
        "runtime_tunnel_receipt": str(RUNTIME_TUNNEL_RECEIPT),
        "runtime_tunnel_receipt_sha256": RUNTIME_TUNNEL_RECEIPT_SHA256,
        "runtime_resource_receipt": str(RUNTIME_RESOURCE_RECEIPT),
        "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
        "schema_version": 4,
        "task_network": PROVIDER_TASK_NETWORK,
        "transport_mode": "auto",
    }:
        raise DirectKimiCapacityError("capacity_provider_profile_invalid")
    return path, body


def _validate_miniswe_live_smoke() -> tuple[Path, bytes]:
    path = MINISWE_LIVE_SMOKE_RECEIPT.resolve(strict=True)
    value, body = _strict_json_regular(
        path,
        "capacity_miniswe_smoke_invalid",
        expected_sha256=MINISWE_LIVE_SMOKE_RECEIPT_SHA256,
        private=True,
    )
    trajectory = value.get("trajectory_audit")
    relay = value.get("relay_audit")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != MINISWE_LIVE_SMOKE_KIND
        or value.get("state") != "passed"
        or value.get("sandbox_environment") != MINISWE_LIVE_SMOKE_ENVIRONMENT
        or value.get("task_network") != PROVIDER_TASK_NETWORK
        or value.get("model_calls") != MINISWE_MAX_STEPS
        or value.get("prior_reasoning_forwarded_calls") != MINISWE_MAX_STEPS - 1
        or value.get("tool_result_forwarded_calls") != MINISWE_MAX_STEPS - 1
        or value.get("program_exit_code") != 0
        or value.get("cleanup_verified") is not True
        or not isinstance(relay, list)
        or len(relay) != MINISWE_MAX_STEPS
        or any(
            not isinstance(call, dict)
            or call.get("call") != index
            or call.get("status_code") != 200
            or call.get("response_reasoning_present") is not True
            or call.get("response_tool_calls") != 1
            for index, call in enumerate(relay, start=1)
        )
        or not isinstance(trajectory, dict)
        or trajectory.get("mini_version") != MINISWE_VERSION
        or trajectory.get("api_calls") != MINISWE_MAX_STEPS
        or trajectory.get("assistant_reasoning_messages") != MINISWE_MAX_STEPS
        or trajectory.get("native_submit_marker_actions") != 1
        or trajectory.get("exit_status") != "Submitted"
    ):
        raise DirectKimiCapacityError("capacity_miniswe_smoke_invalid")
    return path, body


def _validate_provider_context(path: Path) -> tuple[dict[str, Any], bytes]:
    value, body = _strict_json_regular(
        path,
        "capacity_provider_context_invalid",
        private=True,
    )
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
        or value.get("runtime_tunnel_receipt_sha256") != RUNTIME_TUNNEL_RECEIPT_SHA256
        or value.get("runtime_resource_receipt_sha256") != RUNTIME_RESOURCE_RECEIPT_SHA256
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in (
                "provider_token_file_path_sha256",
                "provider_context_contract_sha256",
            )
        )
    ):
        raise DirectKimiCapacityError("capacity_provider_context_invalid")
    return value, body


def _capacity_payload() -> bytes:
    return json.dumps(
        {
            "max_tokens": 1,
            "messages": [{"content": "Reply with OK.", "role": "user"}],
            "model": EXPECTED_MODEL,
            "stream": False,
            "temperature": 0,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _request(base_url: str, payload: bytes, session_id: str, timeout: float) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise DirectKimiCapacityError("capacity_probe_endpoint_invalid")
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=payload,
            headers={
                "Authorization": "Bearer EMPTY",
                "Content-Type": "application/json",
                SESSION_HEADER: session_id,
            },
        )
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if response.status != 200 or len(body) > MAX_RESPONSE_BYTES:
            raise DirectKimiCapacityError("capacity_probe_request_failed")
    except (OSError, http.client.HTTPException) as error:
        raise DirectKimiCapacityError("capacity_probe_request_failed") from error
    finally:
        connection.close()
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiCapacityError("capacity_probe_response_invalid") from error
    if not isinstance(value, dict) or not isinstance(value.get("choices"), list) or not value["choices"]:
        raise DirectKimiCapacityError("capacity_probe_response_invalid")
    return _sha256_bytes(body)


def _validate_capacity_config_value(config: object) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise DirectKimiCapacityError("capacity_config_invalid")
    client = config.get("client")
    sampling = config.get("sampling")
    taskset = config.get("taskset")
    harness = config.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    retries = config.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
    if (
        config.get("model") != EXPECTED_MODEL
        or config.get("num_tasks") != CAPACITY
        or config.get("num_rollouts") != 1
        or config.get("max_concurrent") != CAPACITY
        or config.get("max_turns") != MINISWE_MAX_STEPS
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or config.get("multiplex") != CAPACITY
        or config.get("rich") is not False
        or config.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("max_connections") != CAPACITY
        or client.get("max_keepalive_connections") != CAPACITY
        or client.get("max_retries") != 0
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != MAX_GENERATION_TOKENS
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, dict)
        or taskset.get("enable_compose") is not False
        or taskset.get("verifier_runtime_retries") != 0
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != MINISWE_VERSION
        or harness.get("config_file") != "mini"
        or harness.get("config_overrides") != list(MINISWE_OVERRIDES)
        or harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
        or not isinstance(runtime, dict)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("buffered_chat_completions") is not True
        or runtime.get("guest_tunnel_url") != "http://127.0.0.1:8485"
        or runtime.get("tunnel_pool_size") != 4
        or runtime.get("tunnel_ready_timeout") != 30
        or runtime.get("expected_environment") != PROVIDER_ENVIRONMENT
        or not isinstance(rollout_retries, dict)
        or rollout_retries.get("max_retries") != 0
    ):
        raise DirectKimiCapacityError("capacity_config_invalid")
    return config


def _capacity_identity(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    from eval_run_identity import load_eval_run_identity

    try:
        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
    except (OSError, ValueError) as error:
        raise DirectKimiCapacityError("capacity_identity_invalid") from error
    identity = envelope.get("identity")
    source = identity.get("source") if isinstance(identity, dict) else None
    execution = identity.get("execution") if isinstance(identity, dict) else None
    environment = execution.get("sandoq_environment") if isinstance(execution, dict) else None
    runtime = execution.get("runtime") if isinstance(execution, dict) else None
    deployment = identity.get("deployment") if isinstance(identity, dict) else None
    router = deployment.get("router") if isinstance(deployment, dict) else None
    config = identity.get("config") if isinstance(identity, dict) else None
    try:
        resolved_config = tomllib.loads(
            _read_regular(Path(str(config["resolved"]["path"])), maximum_bytes=1 << 20).decode()
        )
    except (KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DirectKimiCapacityError("capacity_identity_invalid") from error
    _validate_capacity_config_value(resolved_config)
    if (
        not isinstance(identity, dict)
        or identity.get("role") != KIMI_CAPACITY_SMOKE_ROLE
        or identity.get("contract", {}).get("model") != EXPECTED_MODEL
        or not isinstance(source, dict)
        or source.get("sandbox_provider") != "sandoq"
        or source.get("verifiers_commit") != VERIFIERS_COMMIT
        or not isinstance(execution, dict)
        or execution.get("cleanup_must_succeed") is not True
        or any(
            execution.get(key) != CAPACITY
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or not isinstance(runtime, dict)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("buffered_chat_completions") is not True
        or runtime.get("guest_tunnel_url") != "http://127.0.0.1:8485"
        or runtime.get("tunnel_pool_size") != 4
        or runtime.get("tunnel_ready_timeout") != 30
        or runtime.get("expected_environment") != PROVIDER_ENVIRONMENT
        or not isinstance(environment, dict)
        or environment.get("environment") != PROVIDER_ENVIRONMENT
        or environment.get("task_network") != "public"
        or environment.get("provider_task_network") != PROVIDER_TASK_NETWORK
        or environment.get("allow_dockerhub_fallback") is not False
        or environment.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or environment.get("miniswe_compatibility_receipt_sha256") != MINISWE_LIVE_SMOKE_RECEIPT_SHA256
        or environment.get("pool_size") != CAPACITY
        or environment.get("pool_min_size") != 0
        or not isinstance(deployment, dict)
        or not isinstance(router, dict)
        or router.get("capacity_profile") != C64_CAPACITY_PROFILE
        or router.get("endpoint_identifier") != EXPECTED_ENDPOINT_IDENTIFIER
        or router.get("provider_concurrency") != CAPACITY
        or router.get("policy") != POLICY
        or router.get("request_id_headers") != [SESSION_HEADER]
        or router.get("retries") != RETRIES
        or not isinstance(config, dict)
    ):
        raise DirectKimiCapacityError("capacity_identity_invalid")
    return envelope, identity


def run_probe(
    run_dir: Path,
    manifest_path: Path,
    manifest_sha256: str,
    base_url: str,
    output: Path,
    *,
    requester: Any = _request,
) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    envelope, identity = _capacity_identity(run_dir)
    try:
        manifest_body, manifest = load_saved_manifest(manifest_path)
    except (OSError, ValueError) as error:
        raise DirectKimiCapacityError("capacity_manifest_invalid") from error
    router = manifest["router"]
    if (
        SHA256_RE.fullmatch(manifest_sha256) is None
        or _sha256_bytes(manifest_body) != manifest_sha256
        or identity["deployment"]["worker_manifest"]
        != {"path": str(manifest_path.resolve()), "sha256": manifest_sha256}
        or router.get("capacity_profile") != C64_CAPACITY_PROFILE
        or router.get("endpoint_identifier") != EXPECTED_ENDPOINT_IDENTIFIER
        or router.get("max_concurrent_requests") != CAPACITY
        or base_url != f"http://127.0.0.1:{router['port']}/v1"
        or output.resolve() != (run_dir / "control" / PROBE_FILENAME).resolve()
    ):
        raise DirectKimiCapacityError("capacity_probe_binding_invalid")

    payload = _capacity_payload()
    session_ids = [
        hashlib.sha256(f"{envelope['eval_run_identity_sha256']}:{index}".encode()).hexdigest()
        for index in range(CAPACITY)
    ]
    response_digests: list[str] = []
    peak = 0
    active = 0
    counter_lock = threading.Lock()
    started = time.monotonic_ns()

    for _round in range(PROBE_ROUNDS):
        start = threading.Barrier(CAPACITY)
        in_flight = threading.Barrier(CAPACITY)

        def probe_one(session_id: str) -> str:
            nonlocal active, peak
            try:
                start.wait(timeout=30)
            except threading.BrokenBarrierError as error:
                raise DirectKimiCapacityError("capacity_probe_parallelism_failed") from error
            with counter_lock:
                active += 1
                peak = max(peak, active)
            try:
                in_flight.wait(timeout=30)
                return requester(base_url, payload, session_id, 900)
            except threading.BrokenBarrierError as error:
                raise DirectKimiCapacityError("capacity_probe_parallelism_failed") from error
            finally:
                with counter_lock:
                    active -= 1

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=CAPACITY) as executor:
                response_digests.extend(executor.map(probe_one, session_ids))
        except DirectKimiCapacityError:
            raise
        except Exception as error:
            raise DirectKimiCapacityError("capacity_probe_failed") from error

    if (
        peak != CAPACITY
        or len(response_digests) != CAPACITY * PROBE_ROUNDS
        or any(SHA256_RE.fullmatch(value) is None for value in response_digests)
    ):
        raise DirectKimiCapacityError("capacity_probe_failed")
    config = identity["config"]
    source = identity["source"]
    receipt = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "kind": PROBE_KIND,
        "state": "passed",
        "capacity_profile": C64_CAPACITY_PROFILE,
        "endpoint_identifier": EXPECTED_ENDPOINT_IDENTIFIER,
        "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
        "worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "prime_rl_commit": source["prime_rl_commit"],
        "prime_rl_tree_sha256": source["prime_rl_tree_sha256"],
        "source_config_sha256": config["source"]["sha256"],
        "resolved_config_sha256": config["resolved"]["sha256"],
        "policy": POLICY,
        "request_id_header": SESSION_HEADER,
        "retries": RETRIES,
        "client_parallelism": CAPACITY,
        "client_peak_in_flight": peak,
        "rounds": PROBE_ROUNDS,
        "successful_requests": len(response_digests),
        "request_payload_sha256": _sha256_bytes(payload),
        "response_digests_sha256": _sha256_bytes("".join(response_digests).encode()),
        "elapsed_milliseconds": max(1, (time.monotonic_ns() - started) // 1_000_000),
    }
    _atomic_write(output, _canonical_json(receipt) + b"\n", exclusive=True)
    return receipt


def _expected_slugs(task_file: Path) -> set[str]:
    try:
        body = _read_regular(task_file).decode()
    except UnicodeDecodeError as error:
        raise DirectKimiCapacityError("capacity_selector_invalid") from error
    if not body.endswith("\n") or "\r" in body:
        raise DirectKimiCapacityError("capacity_selector_invalid")
    rows = [
        line.strip().split("\t", 1)[0]
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(rows) != len(set(rows)):
        raise DirectKimiCapacityError("capacity_selector_invalid")
    return set(rows)


def _tool_exit_observations(traces: Any) -> tuple[int, int, int]:
    total = 0
    successful = 0
    for trace in traces:
        nodes = trace.get("nodes") if isinstance(trace, dict) else None
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            message = node.get("message") if isinstance(node, dict) else None
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            total += 1
            content = message.get("content")
            try:
                observation = json.loads(content) if isinstance(content, str) else None
            except json.JSONDecodeError:
                observation = None
            if (
                isinstance(observation, dict)
                and type(observation.get("returncode")) is int
                and observation["returncode"] == 0
                and not observation.get("exception_info")
            ):
                successful += 1
    return total, successful, total - successful


def materialize_config(
    template: Path,
    task_file: Path,
    capacity_selector_receipt: Path,
    capacity_selector_receipt_sha256: str,
    output: Path,
) -> dict[str, Any]:
    try:
        task_metadata = task_file.resolve(strict=True).lstat()
    except OSError as error:
        raise DirectKimiCapacityError("capacity_selector_invalid") from error
    if (
        task_file.resolve(strict=True) != task_file
        or task_file.is_symlink()
        or not stat.S_ISREG(task_metadata.st_mode)
        or task_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(task_metadata.st_mode) != 0o600
        or task_metadata.st_nlink != 1
    ):
        raise DirectKimiCapacityError("capacity_selector_invalid")
    task_body = _read_regular(task_file)
    task_sha256 = _sha256_bytes(task_body)
    if len(_expected_slugs(task_file)) != CAPACITY:
        raise DirectKimiCapacityError("capacity_selector_invalid")
    _selector_receipt, selector_receipt_body = _validate_capacity_selector_receipt(
        capacity_selector_receipt,
        capacity_selector_receipt_sha256,
        selector_sha256=task_sha256,
    )
    try:
        template_body = _read_regular(template, maximum_bytes=1 << 20)
        text = template_body.decode()
        template_value = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DirectKimiCapacityError("capacity_template_invalid") from error
    taskset = template_value.get("taskset")
    if (
        not isinstance(taskset, dict)
        or text.count(TASK_FILE_PLACEHOLDER) != 1
        or text.count(TASK_SHA256_PLACEHOLDER) != 1
        or output.exists()
        or output.is_symlink()
    ):
        raise DirectKimiCapacityError("capacity_template_invalid")
    escaped_task_file = json.dumps(str(task_file), ensure_ascii=False)[1:-1]
    rendered = text.replace(TASK_FILE_PLACEHOLDER, escaped_task_file).replace(
        TASK_SHA256_PLACEHOLDER,
        task_sha256,
    )
    try:
        rendered_value = tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise DirectKimiCapacityError("capacity_template_invalid") from error
    rendered_taskset = rendered_value.get("taskset")
    if (
        not isinstance(rendered_taskset, dict)
        or rendered_taskset.get("task_file") != str(task_file)
        or rendered_taskset.get("task_file_sha256") != task_sha256
        or rendered_value.get("num_tasks") != CAPACITY
    ):
        raise DirectKimiCapacityError("capacity_template_invalid")
    _validate_capacity_config_value(rendered_value)
    _atomic_write(output, rendered.encode(), exclusive=True)
    return {
        "config_sha256": _sha256_bytes(rendered.encode()),
        "task_file_sha256": task_sha256,
        "task_count": CAPACITY,
        "selector_receipt_sha256": _sha256_bytes(selector_receipt_body),
    }


def _validate_probe(
    path: Path,
    *,
    identity: dict[str, Any],
    identity_sha256: str,
    manifest_sha256: str,
) -> tuple[dict[str, Any], bytes]:
    value, body = _published_json(path, "capacity_probe_invalid")
    expected = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "kind": PROBE_KIND,
        "state": "passed",
        "capacity_profile": C64_CAPACITY_PROFILE,
        "endpoint_identifier": EXPECTED_ENDPOINT_IDENTIFIER,
        "eval_run_identity_sha256": identity_sha256,
        "worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": identity["deployment"]["endpoint_bundle_sha256"],
        "prime_rl_commit": identity["source"]["prime_rl_commit"],
        "prime_rl_tree_sha256": identity["source"]["prime_rl_tree_sha256"],
        "source_config_sha256": identity["config"]["source"]["sha256"],
        "resolved_config_sha256": identity["config"]["resolved"]["sha256"],
        "policy": POLICY,
        "request_id_header": SESSION_HEADER,
        "retries": RETRIES,
        "client_parallelism": CAPACITY,
        "client_peak_in_flight": CAPACITY,
        "rounds": PROBE_ROUNDS,
        "successful_requests": CAPACITY * PROBE_ROUNDS,
        "request_payload_sha256": _sha256_bytes(_capacity_payload()),
    }
    dynamic = {"response_digests_sha256", "elapsed_milliseconds"}
    if (
        set(value) != {*expected, *dynamic}
        or any(value.get(key) != expected_value for key, expected_value in expected.items())
        or SHA256_RE.fullmatch(str(value.get("response_digests_sha256", ""))) is None
        or type(value.get("elapsed_milliseconds")) is not int
        or value["elapsed_milliseconds"] < 1
    ):
        raise DirectKimiCapacityError("capacity_probe_invalid")
    return value, body


def _validate_router_receipt(
    path: Path,
    *,
    identity_sha256: str,
    manifest: dict[str, Any],
    manifest_sha256: str,
) -> tuple[dict[str, Any], bytes]:
    value, body = _published_json(path, "capacity_router_receipt_invalid")
    expected = {
        "schema_version": 3,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        "eval_run_identity_sha256": identity_sha256,
        "worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": EXPECTED_ENDPOINTS,
        "implementation": "direct-kimi-transparent-v1",
        "implementation_sha256": manifest["router"]["implementation_sha256"],
        "policy": POLICY,
        "request_id_headers": [SESSION_HEADER],
        "request_timeout_seconds": 43_200,
        "retries": RETRIES,
        "capacity_profile": C64_CAPACITY_PROFILE,
        "endpoint_identifier": EXPECTED_ENDPOINT_IDENTIFIER,
        "configured_capacity": CAPACITY,
        "capacity_rejections": 0,
        "queue_overflow_rejections": 0,
        "route_tracking_overflows": 0,
        "cross_route_anomalies": 0,
        "source_generation_revalidated": True,
    }
    dynamic = {
        "invocation_identity_sha256",
        "max_active_requests",
        "max_active_chat_requests",
        "total_requests",
        "chat_requests",
        "tracked_sessions",
        "worker_request_counts_sha256",
    }
    if (
        set(value) != {*expected, *dynamic}
        or any(value.get(key) != expected_value for key, expected_value in expected.items())
        or any(
            type(value.get(key)) is not int or value[key] < CAPACITY
            for key in ("max_active_requests", "max_active_chat_requests", "tracked_sessions")
        )
        or value["max_active_requests"] > CAPACITY
        or value["max_active_chat_requests"] > CAPACITY
        or value["tracked_sessions"] > value["chat_requests"]
        or value["chat_requests"] < CAPACITY * PROBE_ROUNDS
        or value["total_requests"] < value["chat_requests"]
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in ("invocation_identity_sha256", "worker_request_counts_sha256")
        )
    ):
        raise DirectKimiCapacityError("capacity_router_receipt_invalid")
    return value, body


def certify_capacity(
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    capacity_selector_receipt: Path,
    capacity_selector_receipt_sha256: str,
    capacity_probe: Path,
    output: Path,
) -> dict[str, Any]:
    from audit_traces import (
        KIMI_K3_MAX_MODEL_IO_CONTRACT,
        _iter_traces,
        _summarize_traces,
    )
    from certify_direct_kimi import _validate_cleanup

    run_dir = run_dir.resolve(strict=True)
    with (run_dir / ".writer.lock").open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DirectKimiCapacityError("writer_active") from error
        envelope, identity = _capacity_identity(run_dir)
        task_record = identity["inputs"]["task_file"]
        if (
            SHA256_RE.fullmatch(expected_task_file_sha256) is None
            or _sha256_bytes(_read_regular(expected_task_file)) != expected_task_file_sha256
            or task_record.get("sha256") != expected_task_file_sha256
            or task_record.get("count") != CAPACITY
        ):
            raise DirectKimiCapacityError("capacity_selector_invalid")
        _selector_receipt, selector_receipt_body = _validate_capacity_selector_receipt(
            capacity_selector_receipt,
            capacity_selector_receipt_sha256,
            selector_sha256=expected_task_file_sha256,
        )
        provider_profile_path, provider_profile_body = _validate_provider_profile()
        _runtime_tunnel_receipt, runtime_tunnel_body = _strict_json_regular(
            RUNTIME_TUNNEL_RECEIPT,
            "capacity_runtime_tunnel_receipt_invalid",
            expected_sha256=RUNTIME_TUNNEL_RECEIPT_SHA256,
            private=True,
        )
        _runtime_resource_receipt, runtime_resource_body = _strict_json_regular(
            RUNTIME_RESOURCE_RECEIPT,
            "capacity_runtime_resource_receipt_invalid",
            expected_sha256=RUNTIME_RESOURCE_RECEIPT_SHA256,
            private=True,
        )
        live_smoke_path, live_smoke_body = _validate_miniswe_live_smoke()
        _provider_context, provider_context_body = _validate_provider_context(run_dir / PROVIDER_CONTEXT_FILENAME)

        manifest_record = identity["deployment"]["worker_manifest"]
        try:
            manifest_body, manifest = load_saved_manifest(Path(manifest_record["path"]))
        except (OSError, ValueError) as error:
            raise DirectKimiCapacityError("capacity_manifest_invalid") from error
        manifest_sha256 = _sha256_bytes(manifest_body)
        if (
            manifest_sha256 != manifest_record["sha256"]
            or manifest["router"].get("capacity_profile") != C64_CAPACITY_PROFILE
            or manifest["router"].get("endpoint_identifier") != EXPECTED_ENDPOINT_IDENTIFIER
        ):
            raise DirectKimiCapacityError("capacity_manifest_invalid")

        probe, probe_body = _validate_probe(
            capacity_probe,
            identity=identity,
            identity_sha256=envelope["eval_run_identity_sha256"],
            manifest_sha256=manifest_sha256,
        )
        router, router_body = _validate_router_receipt(
            run_dir / "direct_kimi_router_final.json",
            identity_sha256=envelope["eval_run_identity_sha256"],
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
        results = run_dir / "results.jsonl"
        results_sha256 = _sha256_regular(results)
        expected_slugs = _expected_slugs(expected_task_file)
        summary, failed = _summarize_traces(
            _iter_traces(results),
            expected_slugs=expected_slugs,
            expected_count=CAPACITY,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            aggregate_only=True,
            model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            require_exact_provider_json=True,
            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
            require_clean_stop=False,
        )
        tool_observations, successful_tool_exits, nonzero_tool_exits = _tool_exit_observations(_iter_traces(results))
        if (
            failed
            or summary.get("model_io_turns", 0) < CAPACITY
            or summary.get("sampled_tokens", 0) < CAPACITY
            or tool_observations < CAPACITY
            or successful_tool_exits != tool_observations
            or nonzero_tool_exits != 0
        ):
            raise DirectKimiCapacityError("capacity_trace_audit_failed")

        cleanup, cleanup_body = _validate_cleanup(
            run_dir / "sandoq_cleanup_audit.json",
            expected_count=CAPACITY,
            expected_concurrency=CAPACITY,
        )
        if (
            cleanup["assignment_event_order_high_water"] < CAPACITY
            or cleanup["assignment_measured_high_water"] < CAPACITY
            or cleanup["outer_session_high_water"] < CAPACITY
            or cleanup["assignments_acquired"] != CAPACITY
            or cleanup["assignments_cleanup_verified"] != CAPACITY
            or cleanup["recorded_outer_sessions"] != CAPACITY
            or cleanup["cleanup_gateway_retry_count"] != 0
            or cleanup["gateway_close_warnings"] != 0
            or cleanup["recovered_poisoned_assignments"] != 0
        ):
            raise DirectKimiCapacityError("capacity_cleanup_not_saturated")

        source = identity["source"]
        config = identity["config"]
        artifacts = {
            "results": _artifact(results),
            "eval_run_identity": _artifact(run_dir / "eval_run_identity.json"),
            "config_source": _artifact(Path(config["source"]["path"])),
            "config_resolved": _artifact(Path(config["resolved"]["path"])),
            "task_file": _artifact(Path(task_record["path"])),
            "capacity_selector_receipt": _artifact(capacity_selector_receipt),
            "provider_profile": _artifact(provider_profile_path),
            "provider_context": _artifact(run_dir / PROVIDER_CONTEXT_FILENAME),
            "runtime_tunnel_receipt": _artifact(RUNTIME_TUNNEL_RECEIPT),
            "runtime_resource_receipt": _artifact(RUNTIME_RESOURCE_RECEIPT),
            "miniswe_live_smoke_receipt": _artifact(live_smoke_path),
            "worker_manifest": _artifact(Path(manifest_record["path"])),
            "capacity_probe": _artifact(capacity_probe, published=True),
            "router_receipt": _artifact(run_dir / "direct_kimi_router_final.json", published=True),
            "cleanup_audit": _artifact(run_dir / "sandoq_cleanup_audit.json"),
        }
        unsigned = {
            "schema_version": CAPACITY_SCHEMA_VERSION,
            "kind": CAPACITY_KIND,
            "state": "passed",
            "model": EXPECTED_MODEL,
            "capacity_profile": C64_CAPACITY_PROFILE,
            "qualified_concurrency": CAPACITY,
            "endpoint_identifier": EXPECTED_ENDPOINT_IDENTIFIER,
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "worker_manifest_sha256": manifest_sha256,
            "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
            "source": {
                "prime_rl_commit": source["prime_rl_commit"],
                "prime_rl_tree_sha256": source["prime_rl_tree_sha256"],
                "verifiers_commit": source["verifiers_commit"],
                "router_implementation_sha256": manifest["router"]["implementation_sha256"],
                "sandoq_provider_commit": source["sandoq_provider_commit"],
                "sandoq_provider_tree": source["sandoq_provider_tree"],
            },
            "config": {
                "source_sha256": config["source"]["sha256"],
                "resolved_sha256": config["resolved"]["sha256"],
            },
            "selection": {
                "task_count": CAPACITY,
                "selector_sha256": expected_task_file_sha256,
                "selector_receipt_sha256": _sha256_bytes(selector_receipt_body),
            },
            "runtime": {
                "harness": {
                    "id": "mini-swe-agent",
                    "version": MINISWE_VERSION,
                    "max_steps": MINISWE_MAX_STEPS,
                },
                "sandbox": {
                    "environment": PROVIDER_ENVIRONMENT,
                    "task_network": PROVIDER_TASK_NETWORK,
                    "effective_task_network": "public",
                    "network_access": True,
                    "host_tunnel": "sandoq",
                    "guest_tunnel_url": "http://127.0.0.1:8485",
                    "tunnel_pool_size": 4,
                    "provider_profile_sha256": _sha256_bytes(provider_profile_body),
                    "provider_context_sha256": _sha256_bytes(provider_context_body),
                    "runtime_tunnel_receipt_sha256": _sha256_bytes(runtime_tunnel_body),
                    "runtime_resource_receipt_sha256": _sha256_bytes(runtime_resource_body),
                },
                "compatibility": {
                    "kind": MINISWE_LIVE_SMOKE_KIND,
                    "receipt_sha256": _sha256_bytes(live_smoke_body),
                    "evidence_scope": "relay-reasoning-native-submission-only",
                },
            },
            "router": {
                "policy": POLICY,
                "request_id_headers": [SESSION_HEADER],
                "retries": RETRIES,
                "configured_capacity": CAPACITY,
                "max_active_requests": router["max_active_requests"],
                "max_active_chat_requests": router["max_active_chat_requests"],
                "capacity_rejections": 0,
                "queue_overflow_rejections": 0,
                "route_tracking_overflows": 0,
                "cross_route_anomalies": 0,
                "tracked_sessions": router["tracked_sessions"],
            },
            "probe": {
                "rounds": PROBE_ROUNDS,
                "client_parallelism": CAPACITY,
                "successful_requests": probe["successful_requests"],
                "receipt_sha256": _sha256_bytes(probe_body),
            },
            "sandoq": {
                "assignment_event_order_high_water": cleanup["assignment_event_order_high_water"],
                "assignment_measured_high_water": cleanup["assignment_measured_high_water"],
                "outer_session_high_water": cleanup["outer_session_high_water"],
                "assignments_acquired": cleanup["assignments_acquired"],
                "assignments_cleanup_verified": cleanup["assignments_cleanup_verified"],
                "outer_sessions_deleted": cleanup["outer_sessions_deleted"],
                "cleanup_gateway_retry_count": 0,
                "gateway_close_warnings": 0,
                "recovered_poisoned_assignments": 0,
                "failures": 0,
                "cleanup_audit_sha256": _sha256_bytes(cleanup_body),
            },
            "traces": {
                "count": summary["traces"],
                "model_io_turns": summary["model_io_turns"],
                "sampled_tokens": summary["sampled_tokens"],
                "trace_failures": summary["trace_failures"],
                "global_problem_count": len(summary["global_problems"]),
                "tool_observations": tool_observations,
                "successful_tool_exits": successful_tool_exits,
                "nonzero_tool_exits": nonzero_tool_exits,
                "results_sha256": results_sha256,
            },
            "artifacts": artifacts,
        }
        certificate = {
            **unsigned,
            "capacity_certificate_payload_sha256": _sha256_bytes(_canonical_json(unsigned)),
        }
        _atomic_write(output, _canonical_json(certificate) + b"\n", exclusive=True)
        return certificate


def validate_capacity_certificate(
    path: Path,
    *,
    expected_sha256: str | None = None,
    required_concurrency: int = CAPACITY,
    expected_endpoint_identifier: str = EXPECTED_ENDPOINT_IDENTIFIER,
    expected_worker_manifest_sha256: str | None = None,
    expected_config_sha256: str | None = None,
) -> dict[str, Any]:
    if (
        type(required_concurrency) is not int
        or not 1 <= required_concurrency <= ROUTER_MAX_PROVIDER_CONCURRENCY
        or expected_endpoint_identifier != EXPECTED_ENDPOINT_IDENTIFIER
    ):
        raise DirectKimiCapacityError("capacity_certificate_requirement_invalid")
    value, body = _published_json(path, "capacity_certificate_invalid")
    if expected_sha256 is not None and (
        SHA256_RE.fullmatch(expected_sha256) is None or _sha256_bytes(body) != expected_sha256
    ):
        raise DirectKimiCapacityError("capacity_certificate_digest_mismatch")
    expected_top_level_keys = {
        "schema_version",
        "kind",
        "state",
        "model",
        "capacity_profile",
        "qualified_concurrency",
        "endpoint_identifier",
        "eval_run_identity_sha256",
        "worker_manifest_sha256",
        "endpoint_bundle_sha256",
        "source",
        "config",
        "selection",
        "runtime",
        "router",
        "probe",
        "sandoq",
        "traces",
        "artifacts",
        "capacity_certificate_payload_sha256",
    }
    if set(value) != expected_top_level_keys:
        raise DirectKimiCapacityError("capacity_certificate_invalid")
    payload_sha256 = value.pop("capacity_certificate_payload_sha256", None)
    if payload_sha256 != _sha256_bytes(_canonical_json(value)):
        raise DirectKimiCapacityError("capacity_certificate_invalid")
    source = value.get("source")
    config = value.get("config")
    selection = value.get("selection")
    runtime = value.get("runtime")
    router = value.get("router")
    probe = value.get("probe")
    sandoq = value.get("sandoq")
    traces = value.get("traces")
    artifacts = value.get("artifacts")
    if (
        value.get("schema_version") != CAPACITY_SCHEMA_VERSION
        or value.get("kind") != CAPACITY_KIND
        or value.get("state") != "passed"
        or value.get("model") != EXPECTED_MODEL
        or value.get("capacity_profile") != C64_CAPACITY_PROFILE
        or value.get("qualified_concurrency") != CAPACITY
        or value.get("qualified_concurrency") < required_concurrency
        or value.get("endpoint_identifier") != expected_endpoint_identifier
        or SHA256_RE.fullmatch(str(value.get("eval_run_identity_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("worker_manifest_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("endpoint_bundle_sha256", ""))) is None
        or not isinstance(source, dict)
        or not isinstance(config, dict)
        or not isinstance(selection, dict)
        or not isinstance(runtime, dict)
        or not isinstance(router, dict)
        or not isinstance(probe, dict)
        or not isinstance(sandoq, dict)
        or not isinstance(traces, dict)
        or not isinstance(artifacts, dict)
    ):
        raise DirectKimiCapacityError("capacity_certificate_invalid")
    runtime_harness = runtime.get("harness")
    runtime_sandbox = runtime.get("sandbox")
    runtime_compatibility = runtime.get("compatibility")
    integer_fields = (
        (
            selection,
            ("task_count",),
        ),
        (
            router,
            (
                "retries",
                "configured_capacity",
                "max_active_requests",
                "max_active_chat_requests",
                "capacity_rejections",
                "queue_overflow_rejections",
                "route_tracking_overflows",
                "cross_route_anomalies",
                "tracked_sessions",
            ),
        ),
        (probe, ("rounds", "client_parallelism", "successful_requests")),
        (
            sandoq,
            (
                "assignment_event_order_high_water",
                "assignment_measured_high_water",
                "outer_session_high_water",
                "assignments_acquired",
                "assignments_cleanup_verified",
                "outer_sessions_deleted",
                "cleanup_gateway_retry_count",
                "gateway_close_warnings",
                "recovered_poisoned_assignments",
                "failures",
            ),
        ),
        (
            traces,
            (
                "count",
                "model_io_turns",
                "sampled_tokens",
                "trace_failures",
                "global_problem_count",
                "tool_observations",
                "successful_tool_exits",
                "nonzero_tool_exits",
            ),
        ),
    )
    if any(type(record.get(key)) is not int or record[key] < 0 for record, keys in integer_fields for key in keys):
        raise DirectKimiCapacityError("capacity_certificate_invalid")
    if (
        set(source)
        != {
            "prime_rl_commit",
            "prime_rl_tree_sha256",
            "verifiers_commit",
            "router_implementation_sha256",
            "sandoq_provider_commit",
            "sandoq_provider_tree",
        }
        or re.fullmatch(r"[0-9a-f]{40}", str(source.get("prime_rl_commit", ""))) is None
        or source.get("verifiers_commit") != VERIFIERS_COMMIT
        or SHA256_RE.fullmatch(str(source.get("prime_rl_tree_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(source.get("router_implementation_sha256", ""))) is None
        or re.fullmatch(r"[0-9a-f]{40}", str(source.get("sandoq_provider_commit", ""))) is None
        or re.fullmatch(r"[0-9a-f]{40}", str(source.get("sandoq_provider_tree", ""))) is None
        or set(config) != {"source_sha256", "resolved_sha256"}
        or any(SHA256_RE.fullmatch(str(config.get(key, ""))) is None for key in config)
        or set(selection)
        != {
            "task_count",
            "selector_sha256",
            "selector_receipt_sha256",
        }
        or any(
            SHA256_RE.fullmatch(str(selection.get(key, ""))) is None
            for key in ("selector_sha256", "selector_receipt_sha256")
        )
        or set(runtime) != {"harness", "sandbox", "compatibility"}
        or runtime_harness
        != {
            "id": "mini-swe-agent",
            "version": MINISWE_VERSION,
            "max_steps": MINISWE_MAX_STEPS,
        }
        or not isinstance(runtime_sandbox, dict)
        or runtime_sandbox
        != {
            "environment": PROVIDER_ENVIRONMENT,
            "task_network": PROVIDER_TASK_NETWORK,
            "effective_task_network": "public",
            "network_access": True,
            "host_tunnel": "sandoq",
            "guest_tunnel_url": "http://127.0.0.1:8485",
            "tunnel_pool_size": 4,
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "provider_context_sha256": runtime_sandbox.get("provider_context_sha256"),
            "runtime_tunnel_receipt_sha256": RUNTIME_TUNNEL_RECEIPT_SHA256,
            "runtime_resource_receipt_sha256": RUNTIME_RESOURCE_RECEIPT_SHA256,
        }
        or SHA256_RE.fullmatch(str(runtime_sandbox.get("provider_context_sha256", ""))) is None
        or runtime_compatibility
        != {
            "kind": MINISWE_LIVE_SMOKE_KIND,
            "receipt_sha256": MINISWE_LIVE_SMOKE_RECEIPT_SHA256,
            "evidence_scope": "relay-reasoning-native-submission-only",
        }
        or set(router)
        != {
            "policy",
            "request_id_headers",
            "retries",
            "configured_capacity",
            "max_active_requests",
            "max_active_chat_requests",
            "capacity_rejections",
            "queue_overflow_rejections",
            "route_tracking_overflows",
            "cross_route_anomalies",
            "tracked_sessions",
        }
        or set(probe) != {"rounds", "client_parallelism", "successful_requests", "receipt_sha256"}
        or SHA256_RE.fullmatch(str(probe.get("receipt_sha256", ""))) is None
        or set(sandoq)
        != {
            "assignment_event_order_high_water",
            "assignment_measured_high_water",
            "outer_session_high_water",
            "assignments_acquired",
            "assignments_cleanup_verified",
            "outer_sessions_deleted",
            "cleanup_gateway_retry_count",
            "gateway_close_warnings",
            "recovered_poisoned_assignments",
            "failures",
            "cleanup_audit_sha256",
        }
        or SHA256_RE.fullmatch(str(sandoq.get("cleanup_audit_sha256", ""))) is None
        or set(traces)
        != {
            "count",
            "model_io_turns",
            "sampled_tokens",
            "trace_failures",
            "global_problem_count",
            "tool_observations",
            "successful_tool_exits",
            "nonzero_tool_exits",
            "results_sha256",
        }
        or SHA256_RE.fullmatch(str(traces.get("results_sha256", ""))) is None
        or set(artifacts)
        != {
            "results",
            "eval_run_identity",
            "config_source",
            "config_resolved",
            "task_file",
            "capacity_selector_receipt",
            "provider_profile",
            "provider_context",
            "runtime_tunnel_receipt",
            "runtime_resource_receipt",
            "miniswe_live_smoke_receipt",
            "worker_manifest",
            "capacity_probe",
            "router_receipt",
            "cleanup_audit",
        }
    ):
        raise DirectKimiCapacityError("capacity_certificate_invalid")
    if (
        expected_worker_manifest_sha256 is not None
        and value["worker_manifest_sha256"] != expected_worker_manifest_sha256
    ):
        raise DirectKimiCapacityError("capacity_certificate_binding_mismatch")
    if expected_config_sha256 is not None and config.get("source_sha256") != expected_config_sha256:
        raise DirectKimiCapacityError("capacity_certificate_binding_mismatch")
    if (
        router.get("policy") != POLICY
        or router.get("request_id_headers") != [SESSION_HEADER]
        or router.get("retries") != RETRIES
        or router.get("configured_capacity") != CAPACITY
        or router["max_active_requests"] != CAPACITY
        or router["max_active_chat_requests"] != CAPACITY
        or router["tracked_sessions"] < CAPACITY
        or any(
            router.get(key) != 0
            for key in (
                "capacity_rejections",
                "queue_overflow_rejections",
                "route_tracking_overflows",
                "cross_route_anomalies",
            )
        )
        or probe.get("rounds") != PROBE_ROUNDS
        or probe.get("client_parallelism") != CAPACITY
        or probe.get("successful_requests") != CAPACITY * PROBE_ROUNDS
        or sandoq["assignment_event_order_high_water"] != CAPACITY
        or sandoq["assignment_measured_high_water"] != CAPACITY
        or sandoq["outer_session_high_water"] != CAPACITY
        or sandoq.get("assignments_acquired") != CAPACITY
        or sandoq.get("assignments_cleanup_verified") != CAPACITY
        or sandoq.get("outer_sessions_deleted") != CAPACITY
        or any(
            sandoq.get(key) != 0
            for key in (
                "cleanup_gateway_retry_count",
                "gateway_close_warnings",
                "recovered_poisoned_assignments",
                "failures",
            )
        )
        or selection.get("task_count") != CAPACITY
        or traces.get("count") != CAPACITY
        or traces["model_io_turns"] < CAPACITY
        or traces["sampled_tokens"] < CAPACITY
        or traces.get("trace_failures") != 0
        or traces.get("global_problem_count") != 0
        or traces.get("tool_observations", 0) < CAPACITY
        or traces.get("successful_tool_exits") != traces.get("tool_observations")
        or traces.get("nonzero_tool_exits") != 0
    ):
        raise DirectKimiCapacityError("capacity_certificate_not_qualified")
    cross_bindings = {
        "results": traces["results_sha256"],
        "config_source": config["source_sha256"],
        "config_resolved": config["resolved_sha256"],
        "task_file": selection["selector_sha256"],
        "capacity_selector_receipt": selection["selector_receipt_sha256"],
        "provider_profile": runtime_sandbox["provider_profile_sha256"],
        "provider_context": runtime_sandbox["provider_context_sha256"],
        "runtime_tunnel_receipt": runtime_sandbox["runtime_tunnel_receipt_sha256"],
        "runtime_resource_receipt": runtime_sandbox["runtime_resource_receipt_sha256"],
        "miniswe_live_smoke_receipt": runtime_compatibility["receipt_sha256"],
        "worker_manifest": value["worker_manifest_sha256"],
        "capacity_probe": probe["receipt_sha256"],
        "cleanup_audit": sandoq["cleanup_audit_sha256"],
    }
    for record in artifacts.values():
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
            or _sha256_regular(Path(str(record.get("path")))) != record["sha256"]
        ):
            raise DirectKimiCapacityError("capacity_certificate_artifact_changed")
    if any(artifacts[name]["sha256"] != digest for name, digest in cross_bindings.items()):
        raise DirectKimiCapacityError("capacity_certificate_binding_mismatch")
    _validate_capacity_selector_receipt(
        Path(artifacts["capacity_selector_receipt"]["path"]),
        artifacts["capacity_selector_receipt"]["sha256"],
        selector_sha256=selection["selector_sha256"],
    )
    provider_profile_path, _provider_profile_body = _validate_provider_profile()
    live_smoke_path, _live_smoke_body = _validate_miniswe_live_smoke()
    if (
        artifacts["provider_profile"]["path"] != str(provider_profile_path)
        or artifacts["runtime_tunnel_receipt"]["path"] != str(RUNTIME_TUNNEL_RECEIPT)
        or artifacts["runtime_resource_receipt"]["path"] != str(RUNTIME_RESOURCE_RECEIPT)
        or artifacts["miniswe_live_smoke_receipt"]["path"] != str(live_smoke_path)
    ):
        raise DirectKimiCapacityError("capacity_certificate_binding_mismatch")
    _validate_provider_context(Path(artifacts["provider_context"]["path"]))
    return {**value, "capacity_certificate_payload_sha256": payload_sha256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize = commands.add_parser("materialize-config")
    materialize.add_argument("--template", type=Path, required=True)
    materialize.add_argument("--task-file", type=Path, required=True)
    materialize.add_argument("--capacity-selector-receipt", type=Path, required=True)
    materialize.add_argument("--capacity-selector-receipt-sha256", required=True)
    materialize.add_argument("--output", type=Path, required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--run-dir", type=Path, required=True)
    probe.add_argument("--manifest", type=Path, required=True)
    probe.add_argument("--manifest-sha256", required=True)
    probe.add_argument("--base-url", required=True)
    probe.add_argument("--output", type=Path, required=True)
    certify = commands.add_parser("certify")
    certify.add_argument("--run-dir", type=Path, required=True)
    certify.add_argument("--expected-task-file", type=Path, required=True)
    certify.add_argument("--expected-task-file-sha256", required=True)
    certify.add_argument("--capacity-selector-receipt", type=Path, required=True)
    certify.add_argument("--capacity-selector-receipt-sha256", required=True)
    certify.add_argument("--capacity-probe", type=Path, required=True)
    certify.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--certificate", type=Path, required=True)
    verify.add_argument("--certificate-sha256")
    verify.add_argument("--required-concurrency", type=int, default=CAPACITY)
    verify.add_argument("--endpoint-identifier", default=EXPECTED_ENDPOINT_IDENTIFIER)
    verify.add_argument("--worker-manifest-sha256")
    verify.add_argument("--config-sha256")
    args = parser.parse_args()
    try:
        if args.command == "materialize-config":
            result = materialize_config(
                args.template,
                args.task_file,
                args.capacity_selector_receipt,
                args.capacity_selector_receipt_sha256,
                args.output,
            )
            summary = {
                "config_sha256": result["config_sha256"],
                "selector_receipt_sha256": result["selector_receipt_sha256"],
                "state": "prepared",
                "task_count": result["task_count"],
            }
        elif args.command == "probe":
            result = run_probe(
                args.run_dir,
                args.manifest,
                args.manifest_sha256,
                args.base_url,
                args.output,
            )
            summary = {
                "client_peak_in_flight": result["client_peak_in_flight"],
                "state": result["state"],
                "successful_requests": result["successful_requests"],
            }
        elif args.command == "certify":
            result = certify_capacity(
                args.run_dir,
                args.expected_task_file,
                args.expected_task_file_sha256,
                args.capacity_selector_receipt,
                args.capacity_selector_receipt_sha256,
                args.capacity_probe,
                args.output,
            )
            summary = {
                "certificate_sha256": _sha256_bytes(read_published_file(args.output)),
                "qualified_concurrency": result["qualified_concurrency"],
                "state": result["state"],
            }
        else:
            result = validate_capacity_certificate(
                args.certificate,
                expected_sha256=args.certificate_sha256,
                required_concurrency=args.required_concurrency,
                expected_endpoint_identifier=args.endpoint_identifier,
                expected_worker_manifest_sha256=args.worker_manifest_sha256,
                expected_config_sha256=args.config_sha256,
            )
            summary = {
                "qualified_concurrency": result["qualified_concurrency"],
                "state": result["state"],
            }
    except (OSError, RuntimeError, ValueError):
        print("direct_kimi_capacity_failed", file=__import__("sys").stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
