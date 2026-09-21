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
CAPACITY_SCHEMA_VERSION = 1
CAPACITY_FILENAME = "direct_kimi_capacity_certificate.json"
PROBE_KIND = "direct-kimi-router-capacity-probe"
PROBE_SCHEMA_VERSION = 1
PROBE_FILENAME = "direct_kimi_capacity_probe.json"
PROBE_ROUNDS = 2
MAX_RESPONSE_BYTES = 1 << 20
MAX_SEQUENCE_TOKENS = 262_144
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMPOSE_FILENAMES = ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
TASK_FILE_PLACEHOLDER = "/REPLACE/WITH/PRIVATE/CAPACITY_SELECTOR.txt"
TASK_SHA256_PLACEHOLDER = "REPLACE_WITH_SHA256"
KIMI_CAPACITY_SMOKE_ROLE = "kimi-direct-capacity-smoke"


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
    if (
        not isinstance(identity, dict)
        or identity.get("role") != KIMI_CAPACITY_SMOKE_ROLE
        or identity.get("contract", {}).get("model") != EXPECTED_MODEL
        or not isinstance(source, dict)
        or source.get("sandbox_provider") != "sandoq"
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
        or runtime.get("network_access") is not False
        or runtime.get("host_tunnel") != "none"
        or not isinstance(environment, dict)
        or environment.get("environment") != "oci-runner"
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


def _network_policy(value: object, *, default: str, phase_override: bool = False) -> str:
    if not isinstance(value, dict):
        raise DirectKimiCapacityError("capacity_selector_policy_invalid")
    declared = value.get("network_mode")
    if declared is None:
        if phase_override and "allowed_hosts" in value:
            raise DirectKimiCapacityError("capacity_selector_policy_invalid")
        if not phase_override and "allow_internet" in value:
            allow = value["allow_internet"]
            if not isinstance(allow, bool):
                raise DirectKimiCapacityError("capacity_selector_policy_invalid")
            declared = "public" if allow else "no-network"
        else:
            declared = default
    if declared not in {"public", "no-network"} or value.get("allowed_hosts"):
        raise DirectKimiCapacityError("capacity_selector_policy_invalid")
    return str(declared)


def _network_modes(metadata: object) -> tuple[str, str]:
    if not isinstance(metadata, dict):
        raise DirectKimiCapacityError("capacity_selector_policy_invalid")
    environment = metadata.get("environment", {})
    agent = metadata.get("agent", {})
    verifier = metadata.get("verifier", {})
    if not isinstance(verifier, dict):
        raise DirectKimiCapacityError("capacity_selector_policy_invalid")
    mode = verifier.get("environment_mode")
    verifier_environment = verifier.get("environment")
    if mode is None:
        mode = "separate" if verifier_environment is not None else "shared"
    if mode not in {"shared", "separate"}:
        raise DirectKimiCapacityError("capacity_selector_policy_invalid")
    baseline = _network_policy(environment, default="public")
    agent_mode = _network_policy(agent, default=baseline, phase_override=True)
    verifier_baseline = (
        _network_policy(verifier_environment, default="public")
        if mode == "separate" and verifier_environment is not None
        else baseline
    )
    verifier_mode = _network_policy(verifier, default=verifier_baseline, phase_override=True)
    if (baseline == "no-network" and agent_mode == "public") or (
        verifier_baseline == "no-network" and verifier_mode == "public"
    ):
        raise DirectKimiCapacityError("capacity_selector_policy_invalid")
    return agent_mode, verifier_mode


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


def _selector_policy(dataset: Path, task_file: Path) -> dict[str, Any]:
    expected = _expected_slugs(task_file)
    if len(expected) != CAPACITY:
        raise DirectKimiCapacityError("capacity_selector_invalid")
    no_network = 0
    compose = 0
    for name in expected:
        if not name or Path(name).name != name:
            raise DirectKimiCapacityError("capacity_selector_invalid")
        task_dir = dataset / name
        metadata_path = task_dir / "task.toml"
        try:
            if task_dir.is_symlink() or not task_dir.is_dir() or metadata_path.is_symlink():
                raise DirectKimiCapacityError("capacity_selector_invalid")
            metadata = tomllib.loads(_read_regular(metadata_path, maximum_bytes=1 << 20).decode())
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise DirectKimiCapacityError("capacity_selector_invalid") from error
        if _network_modes(metadata) != ("no-network", "no-network"):
            raise DirectKimiCapacityError("capacity_selector_network_invalid")
        no_network += 1
        environment = task_dir / "environment"
        compose += any((environment / filename).is_file() for filename in COMPOSE_FILENAMES)
    if compose:
        raise DirectKimiCapacityError("capacity_selector_compose_invalid")
    return {
        "task_count": len(expected),
        "agent_no_network_count": no_network,
        "verifier_no_network_count": no_network,
        "compose_task_count": compose,
        "selection_scope": "operator-approved-non-sensitive",
    }


def materialize_config(template: Path, task_file: Path, output: Path) -> dict[str, Any]:
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
    dataset = Path(str(taskset.get("dataset_dir", "")))
    policy = _selector_policy(dataset, task_file)
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
    _atomic_write(output, rendered.encode(), exclusive=True)
    return {
        "config_sha256": _sha256_bytes(rendered.encode()),
        "task_file_sha256": task_sha256,
        **policy,
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
        selector_policy = _selector_policy(Path(identity["dataset"]["path"]), expected_task_file)

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
        if failed or summary.get("model_io_turns", 0) < CAPACITY or summary.get("sampled_tokens", 0) < CAPACITY:
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
                "router_implementation_sha256": manifest["router"]["implementation_sha256"],
                "sandoq_provider_commit": source["sandoq_provider_commit"],
                "sandoq_provider_tree": source["sandoq_provider_tree"],
            },
            "config": {
                "source_sha256": config["source"]["sha256"],
                "resolved_sha256": config["resolved"]["sha256"],
            },
            "selection": {
                "task_file_sha256": expected_task_file_sha256,
                **selector_policy,
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
        or not isinstance(router, dict)
        or not isinstance(probe, dict)
        or not isinstance(sandoq, dict)
        or not isinstance(traces, dict)
        or not isinstance(artifacts, dict)
    ):
        raise DirectKimiCapacityError("capacity_certificate_invalid")
    integer_fields = (
        (
            selection,
            (
                "task_count",
                "agent_no_network_count",
                "verifier_no_network_count",
                "compose_task_count",
            ),
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
            "router_implementation_sha256",
            "sandoq_provider_commit",
            "sandoq_provider_tree",
        }
        or re.fullmatch(r"[0-9a-f]{40}", str(source.get("prime_rl_commit", ""))) is None
        or SHA256_RE.fullmatch(str(source.get("prime_rl_tree_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(source.get("router_implementation_sha256", ""))) is None
        or re.fullmatch(r"[0-9a-f]{40}", str(source.get("sandoq_provider_commit", ""))) is None
        or re.fullmatch(r"[0-9a-f]{40}", str(source.get("sandoq_provider_tree", ""))) is None
        or set(config) != {"source_sha256", "resolved_sha256"}
        or any(SHA256_RE.fullmatch(str(config.get(key, ""))) is None for key in config)
        or set(selection)
        != {
            "task_file_sha256",
            "task_count",
            "agent_no_network_count",
            "verifier_no_network_count",
            "compose_task_count",
            "selection_scope",
        }
        or SHA256_RE.fullmatch(str(selection.get("task_file_sha256", ""))) is None
        or selection.get("selection_scope") != "operator-approved-non-sensitive"
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
        or selection.get("agent_no_network_count") != CAPACITY
        or selection.get("verifier_no_network_count") != CAPACITY
        or selection.get("compose_task_count") != 0
        or traces.get("count") != CAPACITY
        or traces["model_io_turns"] < CAPACITY
        or traces["sampled_tokens"] < CAPACITY
        or traces.get("trace_failures") != 0
        or traces.get("global_problem_count") != 0
    ):
        raise DirectKimiCapacityError("capacity_certificate_not_qualified")
    cross_bindings = {
        "results": traces["results_sha256"],
        "config_source": config["source_sha256"],
        "config_resolved": config["resolved_sha256"],
        "task_file": selection["task_file_sha256"],
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
    return {**value, "capacity_certificate_payload_sha256": payload_sha256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize = commands.add_parser("materialize-config")
    materialize.add_argument("--template", type=Path, required=True)
    materialize.add_argument("--task-file", type=Path, required=True)
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
            result = materialize_config(args.template, args.task_file, args.output)
            summary = {
                "agent_no_network_count": result["agent_no_network_count"],
                "config_sha256": result["config_sha256"],
                "state": "prepared",
                "task_count": result["task_count"],
                "verifier_no_network_count": result["verifier_no_network_count"],
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
