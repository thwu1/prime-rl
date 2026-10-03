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
ADAPTER = "kimi-tb4-miniswe246-sandoq-small-diagnostic-v2"
SUPPORTED_TASKS = 52
COMPOSE_UNSUPPORTED_TASKS = 11
GPU_UNSUPPORTED_TASKS = 3
CONCURRENCY = 24
CPU_CAP = 1
MEMORY_MB_CAP = 2_048
STORAGE_MB_CAP = 10_240
VERIFIER_RUNTIME_RETRIES = 2
SANDOQ_PROVISIONING_RETRIES = 8
SHELL_COMMAND_TIMEOUT_SECONDS = 3_600
BASE_CONFIG_SHA256 = "c9511e966308de60580d2a8f0cb985e628c57c817d5191d16f2a283f06a11f3d"
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
VERIFIERS_COMMIT = "36b0dff6c18affb3d40b7c46d5836381d568050b"
SMOKE_RECEIPT_SHA256 = "cfa6b1cf195b1c49ac3f2884223b183b7a726eca32a7218cdcc243d58e590ee7"
DEFAULT_SMOKE_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/"
    "kimi-tb4-miniswe246-sandoq-firecracker-small-stock-single-diagnostic/"
    "run-1605262/receipt.json"
)
SMOKE_FORMAT_ATTESTATION_SHA256 = "bba7aacbd24c308ff691242bcd83bd842f11eea42cf007d0a584665111815cd5"
DEFAULT_SMOKE_FORMAT_ATTESTATION = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/"
    "kimi-tb4-small-smoke-format-1605262-v1/attestation.json"
)
SMOKE_RAW_TRACE_SHA256 = "c30a3b59a836443fab04cd169d301abdfefb5126806f87281a26dfd30c240636"
SMOKE_REQUEST_DIGEST_SET_SHA256 = "49b3c5d0bcaf1e25839ff0ad90933f78a11660c8967200dc6645998440ea52ba"
SMOKE_RESPONSE_DIGEST_SET_SHA256 = "5fc398f8a24279f50644bac1953b24c12bc745a826219c696ce25aa1193ba047"
CAPACITY_RECEIPT_SHA256 = "244dc901a555b4b73649c6185692c8a9d497319e0f8bcdcdb7373f6604c6f946"
DEFAULT_CAPACITY_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/"
    "kimi-stock-capacity-probes-20260927-v1/c64-fcedd7c6b.json"
)
SANDOQ_SOAK_RECEIPT_SHA256 = "54e882d378c92d0dfa811d41954f94a789d7333076695dcff9862aa248b9f1c8"
DEFAULT_SANDOQ_SOAK_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/"
    "sandoq-firecracker-small-c24-soak-20260927/run-1596000/receipt.json"
)
STOCK_ENDPOINT_IDENTIFIER = "tianhaowu-kimi-k3-stock-eval-20260927"
STOCK_SMOKE_SOURCE_REVISION = "96a469f0b924dcd5dd89b226294f025576f887a8"
STOCK_FORMAT_SOURCE_REVISION = STOCK_SMOKE_SOURCE_REVISION
STOCK_SOURCE_SPEC_SHA256 = "3b9d7b9e72767b9f65894ea024a08713ed10330c7d55c70cd99b2717056a9b39"
STOCK_SOURCE_PROXY_SHA256 = "7894cd7205d0197620fa77edc747377e15c4e311769a0060be760659f5b29595"
STOCK_ENDPOINT_BUNDLE_SHA256 = "7ee38ee5d10c9cc7b04c2ddf9ff5b7813df148b2f7d425c1a4ff192f8fc4d581"
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


def _read(
    path: Path,
    *,
    code: str,
    private: bool = False,
    held: split._HeldArtifactSet | None = None,
) -> bytes:
    try:
        return split.read_regular(path, code=code, private=private, held=held)
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


def _load_base(
    held: split._HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], bytes, Path]:
    path = _base_config_path().resolve(strict=True)
    body = _read(path, code="base_config_invalid", held=held)
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
        or taskset.get("verifier_runtime_retries") != VERIFIER_RUNTIME_RETRIES
        or taskset.get("retry_shared_verifier_scoring") is not True
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != union.MINISWE_VERSION
        or harness.get("config_file") != "mini"
        or harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
        or harness.get("config_overrides")
        != [
            "agent.step_limit=200",
            "environment.environment_class=local",
            f"environment.timeout={SHELL_COMMAND_TIMEOUT_SECONDS}",
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
            "provisioning_retries": SANDOQ_PROVISIONING_RETRIES,
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


def _provider_profile(held: split._HeldArtifactSet | None = None) -> tuple[bytes, Path]:
    path = _provider_profile_path().resolve(strict=True)
    body = _read(path, code="provider_profile_invalid", held=held)
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


def _smoke_receipt(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[bytes, Path]:
    canonical = path.resolve(strict=True)
    body = _read(canonical, code="smoke_receipt_invalid", private=True, held=held)
    if expected_sha256 != SMOKE_RECEIPT_SHA256 or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("smoke_receipt_invalid")
    value = _json(body, code="smoke_receipt_invalid")
    deployment = value.get("deployment")
    router = deployment.get("router") if isinstance(deployment, dict) else None
    transport = value.get("transport")
    summary = transport.get("summary") if isinstance(transport, dict) else None
    totals = summary.get("integer_totals") if isinstance(summary, dict) else None
    record = transport.get("summary_record") if isinstance(transport, dict) else None
    if (
        value.get("schema_version") != 3
        or value.get("kind") != "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic"
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
        or value.get("router_w2_profile_configured") is not True
        or not isinstance(deployment, dict)
        or deployment.get("kind") != "direct-kimi-smoke-binding"
        or deployment.get("source_revision") != STOCK_SMOKE_SOURCE_REVISION
        or deployment.get("slurm_job_id") != "1605262"
        or deployment.get("source_spec_sha256") != STOCK_SOURCE_SPEC_SHA256
        or deployment.get("source_proxy_config_sha256") != STOCK_SOURCE_PROXY_SHA256
        or deployment.get("endpoint_bundle_sha256") != STOCK_ENDPOINT_BUNDLE_SHA256
        or not isinstance(deployment.get("worker_manifest_sha256"), str)
        or SHA256_RE.fullmatch(deployment["worker_manifest_sha256"]) is None
        or router
        != {
            "capacity_profile": "sandoq-stock-single-c64-v1",
            "endpoint_identifier": STOCK_ENDPOINT_IDENTIFIER,
            "per_worker_capacity": 64,
            "worker_count": 1,
        }
        or not isinstance(transport, dict)
        or set(transport) != {"schema_version", "kind", "summary_record", "summary"}
        or transport.get("schema_version") != 1
        or transport.get("kind") != "sandoq-buffered-chat-logical-exact-once"
        or not isinstance(record, dict)
        or set(record) != {"bytes", "sha256"}
        or not isinstance(record.get("bytes"), int)
        or isinstance(record.get("bytes"), bool)
        or record["bytes"] < 1
        or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
        or not isinstance(summary, dict)
        or summary.get("source_schema") != "logical-exact-once-v1"
        or summary.get("summary_records") != 1
        or summary.get("exact_once_counters_required") is not True
        or not isinstance(totals, dict)
        or any(totals.get(key) != 3 for key in (
            "requests",
            "upstream_attempts",
            "logical_requests",
            "logical_upstream_attempts",
            "streamed_requests",
        ))
        or any(totals.get(key) != 0 for key in (
            "anonymous_upstream_attempts",
            "coalesced_requests",
            "replayed_requests",
            "expired_logical_retries",
            "downstream_disconnects",
            "conflicting_requests",
            "inflight",
            "error_count",
            "unknown_path_requests",
        ))
    ):
        raise SmallDiagnosticError("smoke_receipt_invalid")
    return body, canonical


def _capacity_receipt(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[bytes, Path]:
    canonical = path.resolve(strict=True)
    body = _read(canonical, code="capacity_receipt_invalid", private=True, held=held)
    if expected_sha256 != CAPACITY_RECEIPT_SHA256 or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("capacity_receipt_invalid")
    value = _json(body, code="capacity_receipt_invalid")
    deployment = value.get("deployment")
    concurrency = value.get("concurrency")
    completions = value.get("completions")
    model_identity = value.get("model_identity")
    artifacts = value.get("artifacts")
    spec = artifacts.get("spec") if isinstance(artifacts, dict) else None
    proxy = artifacts.get("proxy_config") if isinstance(artifacts, dict) else None
    endpoint = artifacts.get("endpoint_file") if isinstance(artifacts, dict) else None
    metrics = value.get("metrics")
    in_flight = metrics.get("in_flight") if isinstance(metrics, dict) else None
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "kimi-stock-capacity-probe"
        or value.get("state") != "passed"
        or value.get("endpoint_unchanged") is not True
        or deployment
        != {
            "endpoint_authority_sha256": "510d02d82e3d16f34d69241845275af0b21a48875bc6a0e8ea92129ee88aeb43",
            "endpoint_job_id": "1593665",
            "id": STOCK_ENDPOINT_IDENTIFIER,
            "model": "Kimi-K3",
        }
        or concurrency != {"client_peak_in_flight": 64, "configured": 64}
        or not isinstance(completions, dict)
        or any(completions.get(key) != 64 for key in (
            "attempted",
            "http_200",
            "model_matches",
            "raw_reasoning_present",
            "reasoning_present",
            "requested",
            "successful",
            "tool_call_responses",
            "tool_calls_total",
        ))
        or completions.get("reasoning_content_present") != 0
        or completions.get("response_errors") != 0
        or completions.get("transport_errors") != 0
        or not isinstance(completions.get("response_digests_sha256"), str)
        or SHA256_RE.fullmatch(completions["response_digests_sha256"]) is None
        or model_identity
        != {
            "backend_model": "openai/Kimi-K3",
            "confirmed": True,
            "response_errors": 0,
            "served_model": "Kimi-K3",
            "transport_errors": 0,
        }
        or not isinstance(spec, dict)
        or spec.get("sha256") != STOCK_SOURCE_SPEC_SHA256
        or not isinstance(proxy, dict)
        or proxy.get("sha256") != STOCK_SOURCE_PROXY_SHA256
        or not isinstance(endpoint, dict)
        or endpoint.get("sha256") != "3daa2941e88bee4d0435d50687c6f0f95104df119cff1c361263d2053e2a61ae"
        or not isinstance(in_flight, dict)
        or in_flight.get("maximum_running", 0) < 64
        or in_flight.get("maximum_waiting") != 0
        or in_flight.get("response_errors") != 0
        or in_flight.get("transport_errors") != 0
    ):
        raise SmallDiagnosticError("capacity_receipt_invalid")
    return body, canonical


def _smoke_format_attestation(
    path: Path,
    expected_sha256: str,
    *,
    smoke_path: Path,
    smoke_body: bytes,
    held: split._HeldArtifactSet | None = None,
) -> tuple[bytes, Path]:
    canonical = path.resolve(strict=True)
    body = _read(canonical, code="smoke_format_attestation_invalid", private=True, held=held)
    if expected_sha256 != SMOKE_FORMAT_ATTESTATION_SHA256 or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("smoke_format_attestation_invalid")
    value = _json(body, code="smoke_format_attestation_invalid")
    source = value.get("source")
    capture = value.get("capture")
    receipt = source.get("receipt") if isinstance(source, dict) else None
    raw_trace = source.get("raw_trace") if isinstance(source, dict) else None
    if (
        value.get("schema_version") != 3
        or value.get("kind") != "kimi-tb4-miniswe246-sandoq-firecracker-small-smoke-format"
        or value.get("state") != "passed"
        or not isinstance(source, dict)
        or source.get("slurm_job_id") != "1605262"
        or source.get("source_revision") != STOCK_FORMAT_SOURCE_REVISION
        or receipt != _artifact(smoke_path, smoke_body)
        or not isinstance(raw_trace, dict)
        or set(raw_trace) != {"path", "bytes", "sha256"}
        or not isinstance(raw_trace.get("path"), str)
        or not isinstance(raw_trace.get("bytes"), int)
        or raw_trace["bytes"] < 1
        or raw_trace.get("sha256") != SMOKE_RAW_TRACE_SHA256
        or not isinstance(capture, dict)
        or capture.get("response_kind") != "exact_provider_json"
        or capture.get("model_calls") != 3
        or capture.get("nonstream_provider_requests") != 3
        or capture.get("reasoning_nonblank") != 3
        or capture.get("reasoning_exact_parity") != 3
        or capture.get("tool_call_turns") != 3
        or capture.get("tool_calls_total") != 3
        or capture.get("tool_call_exact_semantic_parity") != 3
        or capture.get("raw_provider_field") != "reasoning"
        or capture.get("canonical_trajectory_field") != "reasoning_content"
        or capture.get("request_digest_set_sha256") != SMOKE_REQUEST_DIGEST_SET_SHA256
        or capture.get("response_digest_set_sha256") != SMOKE_RESPONSE_DIGEST_SET_SHA256
    ):
        raise SmallDiagnosticError("smoke_format_attestation_invalid")
    return body, canonical


def _sandoq_soak_receipt(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[bytes, Path]:
    canonical = path.resolve(strict=True)
    body = _read(canonical, code="sandoq_soak_receipt_invalid", private=True, held=held)
    if expected_sha256 != SANDOQ_SOAK_RECEIPT_SHA256 or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("sandoq_soak_receipt_invalid")
    value = _json(body, code="sandoq_soak_receipt_invalid")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "sandoq-firecracker-small-c24-soak"
        or value.get("state") != "passed"
        or value.get("environment") != "oci-runner-firecracker-small"
        or value.get("profile_sha256") != PROVIDER_PROFILE_SHA256
        or value.get("requested_concurrency") != CONCURRENCY
        or value.get("create_attempts") != CONCURRENCY
        or value.get("sessions_returned") != CONCURRENCY
        or value.get("simultaneous_ready_verified") != CONCURRENCY
        or value.get("delete_attempts") != CONCURRENCY
        or value.get("typed_404_verified") != CONCURRENCY
        or value.get("cleanup_failures") != 0
        or value.get("client_close_verified") is not True
        or value.get("mtls_available") is not True
        or value.get("transport_mode") != "proxy"
    ):
        raise SmallDiagnosticError("sandoq_soak_receipt_invalid")
    failure_counts = value.get("create_failure_counts")
    if not isinstance(failure_counts, dict) or any(item != 0 for item in failure_counts.values()):
        raise SmallDiagnosticError("sandoq_soak_receipt_invalid")
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


def _contracts() -> dict[str, Any]:
    return {
        "model": "Kimi-K3",
        "harness": {"id": "mini-swe-agent", "version": union.MINISWE_VERSION},
        "verifiers_commit": VERIFIERS_COMMIT,
        "context_tokens": split.MAX_SEQUENCE_TOKENS,
        "generation_tokens": split.SAMPLING_MAX_TOKENS,
        "max_turns": 200,
        "reasoning_required": True,
        "model_io_response_kind": "exact_provider_json",
        "reasoning_message_parity_required": True,
        "request_graph_match_required": True,
        "model_retries": 0,
        "guest_transport_retry_attempts": 10,
        "logical_request_upstream_attempts": 1,
        "buffered_proxy_summary_schema": "logical-exact-once-v1",
        "buffered_proxy_summary_records": SUPPORTED_TASKS,
        "audit_error_model_io": True,
        "router_terminal_status_binding_required": True,
        "terminal_proxy_exceptions_allowed": False,
        "shell_command_timeout_seconds": SHELL_COMMAND_TIMEOUT_SECONDS,
        "zero_model_resume_attempts": 0,
        "verifier_runtime_retries": VERIFIER_RUNTIME_RETRIES,
        "retry_shared_verifier_scoring": True,
        "provisioning_retries": SANDOQ_PROVISIONING_RETRIES,
        "timeouts": dict(union.TIMEOUT_CONTRACT),
        "resource_caps": {
            "cpu": CPU_CAP,
            "memory_mb": MEMORY_MB_CAP,
            "storage_mb": STORAGE_MB_CAP,
        },
        "measured_router_capacity": 64,
        "evaluation_concurrency": CONCURRENCY,
    }


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
    smoke_format_path: Path,
    smoke_format_body: bytes,
    capacity_path: Path,
    capacity_body: bytes,
    soak_path: Path,
    soak_body: bytes,
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
        "contracts": _contracts(),
        "source": {
            "manifest": _artifact(manifest, manifest_body),
            "image_manifest": _artifact(image_manifest, image_body),
            "base_config": _artifact(base_path, base_body),
            "provider_profile": _artifact(profile_path, profile_body),
            "smoke_receipt": _artifact(smoke_path, smoke_body),
            "smoke_format_attestation": _artifact(smoke_format_path, smoke_format_body),
            "capacity_receipt": _artifact(capacity_path, capacity_body),
            "sandoq_c24_soak_receipt": _artifact(soak_path, soak_body),
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
    smoke_format_body, smoke_format_path = _smoke_format_attestation(
        args.smoke_format_attestation,
        args.smoke_format_attestation_sha256,
        smoke_path=smoke_path,
        smoke_body=smoke_body,
    )
    capacity_body, capacity_path = _capacity_receipt(
        args.capacity_receipt,
        args.capacity_receipt_sha256,
    )
    soak_body, soak_path = _sandoq_soak_receipt(
        args.sandoq_soak_receipt,
        args.sandoq_soak_receipt_sha256,
    )
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
        smoke_format_path=smoke_format_path,
        smoke_format_body=smoke_format_body,
        capacity_path=capacity_path,
        capacity_body=capacity_body,
        soak_path=soak_path,
        soak_body=soak_body,
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


def _verify_with_contracts(
    path: Path,
    expected_sha256: str,
    *,
    expected_contracts: dict[str, Any],
    base_loader: Any | None = None,
    provider_profile_loader: Any | None = None,
    require_smoke_format_attestation: bool = True,
    held: split._HeldArtifactSet | None = None,
    body: bytes | None = None,
) -> dict[str, Any]:
    captured = _read(path, code="plan_invalid", private=True, held=held)
    if body is not None and body != captured:
        raise SmallDiagnosticError("plan_invalid")
    body = captured
    if path.name != PLAN or SHA256_RE.fullmatch(expected_sha256 or "") is None or _sha256(body) != expected_sha256:
        raise SmallDiagnosticError("plan_invalid")
    plan = _json(body, code="plan_invalid")
    if (
        plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("kind") != KIND
        or plan.get("state") != "materialized"
        or plan.get("required_adapter") != ADAPTER
        or plan.get("contracts") != expected_contracts
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
    smoke_names = (
        ("smoke_receipt", "smoke_format_attestation")
        if require_smoke_format_attestation
        else ("smoke_receipt",)
    )
    for section, names, private in (
        (
            source,
            ("manifest", *smoke_names, "capacity_receipt", "sandoq_c24_soak_receipt"),
            True,
        ),
        (source, ("image_manifest", "base_config", "provider_profile"), False),
        (lane, ("selector", "config"), True),
        (unsupported, ("compose", "gpu"), True),
    ):
        for name in names:
            record = section.get(name)
            if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
                raise SmallDiagnosticError("plan_invalid")
            artifact_path = Path(str(record["path"]))
            artifact_body = _read(
                artifact_path,
                code="plan_artifact_invalid",
                private=private,
                held=held,
            )
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
    load_base = _load_base if base_loader is None else base_loader
    load_profile = _provider_profile if provider_profile_loader is None else provider_profile_loader
    base, base_body, base_path = load_base(held)
    profile_body, profile_path = load_profile(held)
    smoke_body, smoke_path = _smoke_receipt(
        records["smoke_receipt"][0],
        SMOKE_RECEIPT_SHA256,
        held,
    )
    smoke_format = None
    if require_smoke_format_attestation:
        smoke_format_body, smoke_format_path = _smoke_format_attestation(
            records["smoke_format_attestation"][0],
            SMOKE_FORMAT_ATTESTATION_SHA256,
            smoke_path=smoke_path,
            smoke_body=smoke_body,
            held=held,
        )
        smoke_format = (smoke_format_path, smoke_format_body)
    capacity_body, capacity_path = _capacity_receipt(
        records["capacity_receipt"][0],
        CAPACITY_RECEIPT_SHA256,
        held,
    )
    soak_body, soak_path = _sandoq_soak_receipt(
        records["sandoq_c24_soak_receipt"][0],
        SANDOQ_SOAK_RECEIPT_SHA256,
        held,
    )
    image_path, image_body = records["image_manifest"]
    if (
        records["base_config"] != (base_path, base_body)
        or records["provider_profile"] != (profile_path, profile_body)
        or records["smoke_receipt"] != (smoke_path, smoke_body)
        or (
            require_smoke_format_attestation
            and records["smoke_format_attestation"] != smoke_format
        )
        or records["capacity_receipt"] != (capacity_path, capacity_body)
        or records["sandoq_c24_soak_receipt"] != (soak_path, soak_body)
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


def verify(
    path: Path,
    expected_sha256: str,
    *,
    held: split._HeldArtifactSet | None = None,
    body: bytes | None = None,
) -> dict[str, Any]:
    return _verify_with_contracts(
        path,
        expected_sha256,
        expected_contracts=_contracts(),
        held=held,
        body=body,
    )


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
    make.add_argument(
        "--smoke-format-attestation",
        type=Path,
        default=DEFAULT_SMOKE_FORMAT_ATTESTATION,
    )
    make.add_argument(
        "--smoke-format-attestation-sha256",
        default=SMOKE_FORMAT_ATTESTATION_SHA256,
    )
    make.add_argument("--capacity-receipt", type=Path, default=DEFAULT_CAPACITY_RECEIPT)
    make.add_argument("--capacity-receipt-sha256", default=CAPACITY_RECEIPT_SHA256)
    make.add_argument("--sandoq-soak-receipt", type=Path, default=DEFAULT_SANDOQ_SOAK_RECEIPT)
    make.add_argument("--sandoq-soak-receipt-sha256", default=SANDOQ_SOAK_RECEIPT_SHA256)
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
