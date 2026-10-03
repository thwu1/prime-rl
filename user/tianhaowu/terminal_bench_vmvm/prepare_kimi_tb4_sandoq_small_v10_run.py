#!/usr/bin/env python3
"""Materialize the capacity-bound c16 Kimi TB4 v10 contingency run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Sequence

import eval_run_identity as identity
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as legacy
from kimi_stock_endpoint_binding import StockEndpointBinding, load_capacity_binding

SCHEMA_VERSION = 1
KIND = "kimi-tb4-miniswe246-sandoq-firecracker-small-v10-plan"
STAGE = "tb4-miniswe246-sandoq-small-v10-c16"
ADAPTER = "kimi-tb4-miniswe246-sandoq-small-v10-c16-v1"
SUPPORTED_TASKS = 52
COMPOSE_UNSUPPORTED_TASKS = 11
GPU_UNSUPPORTED_TASKS = 3
CONCURRENCY = 16
CPU_CAP = 1
MEMORY_MB_CAP = 2_048
STORAGE_MB_CAP = 10_240
VERIFIER_RUNTIME_RETRIES = 2
SANDOQ_PROVISIONING_RETRIES = 8
SHELL_COMMAND_TIMEOUT_SECONDS = 3_600
BASE_CONFIG_SHA256 = "ad0f35cccc671ee5d828f7c29f777dd52133e53f2085bc8d7d02ec2f873bf23e"
SCORE_POLICY_BASELINE_REVISION = "97ba80d9c1f284b2ca787d297d756fef6ce03367"
READY_RECEIPT_KIND = "kimi-stock-fresh-deployment-ready"
READY_RECEIPT_MINIMUM_SECONDS = 6 * 24 * 60 * 60
ENDPOINT_MINIMUM_REMAINING_SECONDS = 162 * 60 * 60
CANONICAL_DATASET_ARCHIVE = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/"
    "terminal-bench-prebuilt-v4.0.0.tar.gz"
)
ROUTER_CAPACITY_PROFILE = "sandoq-stock-single-c64-v1"
ROUTER_POLICY = "consistent_hash"
EXCLUSIVE_LOCK = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/terminal-bench-sandoq-campaign.lock")
SUPPORTED_SELECTOR = "sandoq-small-supported.tasks.txt"
COMPOSE_SELECTOR = "compose-unsupported.tasks.txt"
GPU_SELECTOR = "gpu-unsupported.tasks.txt"
CONFIG = "sandoq-small-v10-c16.toml"
PLAN = "launch-plan.json"
RUN_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_READY_RECEIPT_BYTES = 256 * 1024
SCORE_POLICY_FILES = (
    "audit_traces.py",
    "finalize_kimi_tb4_sandoq_small_v4_recovery.py",
    "finalize_kimi_tb4_sandoq_small_v8_supersession.py",
    "finalize_kimi_tb4_sandoq_small_v10.py",
    "terminal_bench_vmvm/taskset.py",
)


class V10PlanError(ValueError):
    """A v10 launch input failed closed."""


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _project_root() -> Path:
    return _workflow_dir().parents[2]


def _base_config_path() -> Path:
    return (
        _workflow_dir() / "configs/eval/servers/cpu-132-021_8103/"
        "tb4_kimi_k3_miniswe246_sandoq_firecracker_small_v10_c16.base.toml"
    )


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _read(
    path: Path,
    *,
    code: str,
    private: bool = False,
    held: split._HeldArtifactSet | None = None,
    maximum_bytes: int = 64 * 1024 * 1024,
) -> bytes:
    try:
        return split.read_regular(
            path,
            code=code,
            private=private,
            held=held,
            maximum_bytes=maximum_bytes,
        )
    except (OSError, ValueError) as error:
        raise V10PlanError(code) from error


def _artifact(path: Path, body: bytes) -> dict[str, int | str]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _strict_json(body: bytes, *, code: str, canonical: bool = False) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise V10PlanError(code)
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(V10PlanError(code)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, V10PlanError) as error:
        raise V10PlanError(code) from error
    if not isinstance(value, dict) or (canonical and _canonical(value) != body):
        raise V10PlanError(code)
    return value


def _source_revision(expected_revision: str) -> str:
    if REVISION_RE.fullmatch(expected_revision or "") is None:
        raise V10PlanError("source_revision_invalid")
    root = _project_root()
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise V10PlanError("source_revision_invalid") from error
    if revision != expected_revision or dirty:
        raise V10PlanError("source_revision_invalid")
    return revision


def _validated_dataset(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        dataset = absolute.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise V10PlanError("dataset_content_invalid") from error
    if dataset != absolute or not dataset.is_dir():
        raise V10PlanError("dataset_content_invalid")

    archive = CANONICAL_DATASET_ARCHIVE
    try:
        if archive.is_symlink() or archive.resolve(strict=True) != archive:
            raise V10PlanError("dataset_archive_invalid")
        identity._verified_archive_content(
            archive,
            split.CANONICAL_DATASET_ARCHIVE_SHA256,
            split.CANONICAL_DATASET_CONTENT_SHA256,
        )
    except V10PlanError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise V10PlanError("dataset_archive_invalid") from error

    try:
        observed = identity._tree_digest(dataset)
    except (OSError, RuntimeError, ValueError) as error:
        raise V10PlanError("dataset_content_invalid") from error
    if observed != split.CANONICAL_DATASET_CONTENT_SHA256:
        raise V10PlanError("dataset_content_invalid")
    return dataset


def _load_base(
    held: split._HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], bytes, Path]:
    path = _base_config_path().resolve(strict=True)
    body = _read(path, code="base_config_invalid", held=held)
    if _sha256(body) != BASE_CONFIG_SHA256:
        raise V10PlanError("base_config_invalid")
    try:
        value = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise V10PlanError("base_config_invalid") from error
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
        or any(
            value.get(key) != split.MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or value.get("retain_traces") is not False
        or value.get("rich") is not False
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or client.get("max_retries") != 0
        or client.get("timeout") != union.REQUEST_TIMEOUT_SECONDS
        or client.get("max_connections") != CONCURRENCY
        or client.get("max_keepalive_connections") != CONCURRENCY
        or not isinstance(sampling, dict)
        or sampling.get("temperature") != 1.0
        or sampling.get("top_p") != 1.0
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
        or taskset.get("persist_verifier_artifacts") is not True
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
        or timeout != {"setup": 3_600, "rollout": 129_600, "finalize": 3_600, "scoring": 21_600}
        or not isinstance(rollout_retry, dict)
        or rollout_retry.get("max_retries") != 0
    ):
        raise V10PlanError("base_config_contract_invalid")
    return value, body, path


def _ready_receipt(
    path: Path,
    expected_sha256: str,
    *,
    binding: StockEndpointBinding,
    held: split._HeldArtifactSet | None = None,
) -> tuple[bytes, Path]:
    if SHA256_RE.fullmatch(expected_sha256 or "") is None:
        raise V10PlanError("ready_receipt_invalid")
    canonical = path.resolve(strict=True)
    body = _read(
        canonical,
        code="ready_receipt_invalid",
        private=True,
        held=held,
        maximum_bytes=MAX_READY_RECEIPT_BYTES,
    )
    if _sha256(body) != expected_sha256:
        raise V10PlanError("ready_receipt_changed")
    value = _strict_json(body, code="ready_receipt_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("receipt_sha256", None)
    deployment = value.get("deployment")
    artifacts = deployment.get("artifacts") if isinstance(deployment, dict) else None
    jobs = deployment.get("jobs") if isinstance(deployment, dict) else None
    health = value.get("health")
    lifetime = value.get("lifetime")
    routing = value.get("routing")
    endpoint_artifact = artifacts.get("endpoint_file") if isinstance(artifacts, dict) else None
    spec_artifact = artifacts.get("spec") if isinstance(artifacts, dict) else None
    proxy_artifact = artifacts.get("proxy_config") if isinstance(artifacts, dict) else None
    capacity_artifact = health.get("capacity_receipt") if isinstance(health, dict) else None
    if (
        value.get("schema_version") != 1
        or value.get("kind") != READY_RECEIPT_KIND
        or value.get("state") != "ready"
        or claimed != _sha256(_canonical(unsigned))
        or value.get("slurm_mutations_performed") is not False
        or value.get("task_content_retained") is not False
        or not isinstance(deployment, dict)
        or deployment.get("id") != binding.deployment_id
        or deployment.get("root") != str(binding.deployment_root)
        or deployment.get("model") != "Kimi-K3"
        or deployment.get("replicas") != 1
        or deployment.get("nodes_per_replica") != 4
        or deployment.get("gpus_per_replica") != 16
        or deployment.get("tensor_parallel") != 16
        or not isinstance(artifacts, dict)
        or artifacts.get("endpoint_authority_sha256") != binding.endpoint_authority_sha256
        or artifacts.get("endpoint_bundle_sha256") != binding.endpoint_bundle_sha256
        or artifacts.get("endpoint_jobs_sha256") != binding.endpoint_jobs_sha256
        or not isinstance(endpoint_artifact, dict)
        or endpoint_artifact.get("sha256") != binding.endpoint_file_sha256
        or not isinstance(spec_artifact, dict)
        or spec_artifact.get("sha256") != binding.source_spec_sha256
        or not isinstance(proxy_artifact, dict)
        or proxy_artifact.get("sha256") != binding.source_proxy_config_sha256
        or not isinstance(jobs, dict)
        or set(jobs) != {"coordinator", "endpoint", "proxy"}
        or jobs.get("endpoint", {}).get("job_id") != binding.endpoint_job_id
        or any(
            not isinstance(record, dict)
            or record.get("state") != "RUNNING"
            or record.get("restarts") != 0
            or record.get("time_limit_seconds") != 604_800
            or type(record.get("remaining_seconds_at_capture")) is not int
            or record["remaining_seconds_at_capture"] < READY_RECEIPT_MINIMUM_SECONDS
            for record in jobs.values()
        )
        or not isinstance(health, dict)
        or health.get("capacity_probe_state") != "passed"
        or health.get("served_model_confirmed") is not True
        or health.get("endpoint_http_status") != 200
        or not isinstance(capacity_artifact, dict)
        or capacity_artifact.get("path") != str(binding.capacity_receipt_path)
        or capacity_artifact.get("sha256") != binding.capacity_receipt_sha256
        or not isinstance(lifetime, dict)
        or lifetime.get("passes") is not True
        or type(lifetime.get("minimum_required_seconds")) is not int
        or lifetime.get("minimum_required_seconds") < READY_RECEIPT_MINIMUM_SECONDS
        or type(lifetime.get("observed_minimum_remaining_seconds")) is not int
        or lifetime.get("observed_minimum_remaining_seconds")
        < ENDPOINT_MINIMUM_REMAINING_SECONDS
        or routing
        != {
            "deployment_proxy_sticky_routing": binding.sticky_routing,
            "deployment_proxy_used_for_production": False,
            "production_path": "direct-worker-router",
            "production_router_policy": ROUTER_POLICY,
            "single_backend_stable": True,
            "worker_count": 1,
        }
    ):
        raise V10PlanError("ready_receipt_invalid")
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


def _score_policy_artifacts(
    held: split._HeldArtifactSet | None = None,
) -> dict[str, dict[str, int | str]]:
    records: dict[str, dict[str, int | str]] = {}
    for relative in SCORE_POLICY_FILES:
        path = (_workflow_dir() / relative).resolve(strict=True)
        body = _read(path, code="score_policy_source_invalid", held=held)
        records[relative] = _artifact(path, body)
    return records


def _contracts(binding: StockEndpointBinding) -> dict[str, Any]:
    return {
        "model": "Kimi-K3",
        "harness": {"id": "mini-swe-agent", "version": union.MINISWE_VERSION},
        "context_tokens": split.MAX_SEQUENCE_TOKENS,
        "generation_tokens": split.SAMPLING_MAX_TOKENS,
        "max_turns": 200,
        "reasoning_effort": "max",
        "sampling": {"temperature": 1.0, "top_p": 1.0},
        "model_retries": 0,
        "guest_transport_retry_attempts": 10,
        "logical_request_upstream_attempts": 1,
        "buffered_proxy_summary_schema": "logical-exact-once-v1",
        "buffered_proxy_summary_records": SUPPORTED_TASKS,
        "model_io_response_kind": "exact_provider_json",
        "reasoning_message_parity_required": True,
        "request_graph_match_required": True,
        "router_terminal_status_binding_required": True,
        "persistent_separate_verifier_artifacts": True,
        "exact_infrastructure_disposition_required": True,
        "score_validity_separate_from_sft_eligibility": True,
        "verifier_runtime_retries": VERIFIER_RUNTIME_RETRIES,
        "retry_shared_verifier_scoring": True,
        "provisioning_retries": SANDOQ_PROVISIONING_RETRIES,
        "shell_command_timeout_seconds": SHELL_COMMAND_TIMEOUT_SECONDS,
        "timeouts": dict(union.TIMEOUT_CONTRACT),
        "resource_caps": {
            "cpu": CPU_CAP,
            "memory_mb": MEMORY_MB_CAP,
            "storage_mb": STORAGE_MB_CAP,
        },
        "evaluation_concurrency": CONCURRENCY,
        "measured_router_capacity": 64,
        "routing": {
            "capacity_profile": ROUTER_CAPACITY_PROFILE,
            "deployment_id": binding.deployment_id,
            "direct_router_policy": ROUTER_POLICY,
            "deployment_proxy_used": False,
            "proxy_sticky_routing": binding.sticky_routing,
            "single_backend_stable": True,
            "worker_count": 1,
        },
        "sandbox_isolation": {
            "concurrent_sandoq_campaigns": 0,
            "explicit_operator_attestation_required": True,
            "exclusive_lock": str(EXCLUSIVE_LOCK),
            "active_slurm_campaign_scan_required": True,
        },
        "scheduler_job_limit_seconds": 561_600,
        "endpoint_minimum_remaining_seconds": ENDPOINT_MINIMUM_REMAINING_SECONDS,
    }


def _expected_plan(
    *,
    directory: Path,
    run_output: Path,
    full_output: Path,
    revision: str,
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
    soak_path: Path,
    soak_body: bytes,
    capacity_path: Path,
    capacity_body: bytes,
    ready_path: Path,
    ready_body: bytes,
    binding: StockEndpointBinding,
    supported_body: bytes,
    compose_body: bytes,
    gpu_body: bytes,
    config_body: bytes,
    score_policy: dict[str, dict[str, int | str]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "materialized",
        "execution_source_revision": revision,
        "score_policy_baseline_revision": SCORE_POLICY_BASELINE_REVISION,
        "evaluation": {
            "denominator": split.TOTAL_TASKS,
            "executed_tasks": SUPPORTED_TASKS,
            "compose_unsupported": COMPOSE_UNSUPPORTED_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "pass_at_1": True,
            "certification_eligible": False,
            "official_comparable": False,
            "result_label": "resource-clamped-firecracker-small-v10-c16",
        },
        "contracts": _contracts(binding),
        "source": {
            "manifest": _artifact(manifest, manifest_body),
            "image_manifest": _artifact(image_manifest, image_body),
            "base_config": _artifact(base_path, base_body),
            "provider_profile": _artifact(profile_path, profile_body),
            "historical_smoke_receipt": _artifact(smoke_path, smoke_body),
            "historical_smoke_format_attestation": _artifact(smoke_format_path, smoke_format_body),
            "historical_sandoq_c24_soak_receipt": _artifact(soak_path, soak_body),
            "fresh_capacity_receipt": _artifact(capacity_path, capacity_body),
            "fresh_ready_receipt": _artifact(ready_path, ready_body),
            "score_policy": score_policy,
        },
        "endpoint_epoch": {
            **binding.public_record,
            "endpoint_file_sha256": binding.endpoint_file_sha256,
        },
        "evidence_roles": {
            "historical_smoke": "capture-format-only-not-endpoint-authority",
            "historical_sandoq_soak": "provider-capacity-lower-bound",
            "fresh_capacity": "endpoint-and-routing-authority",
            "fresh_ready": "submission-health-and-lifetime-authority",
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
        "postprocessing": {
            "state": "awaiting-versioned-v11-after-execution",
            "legacy_v10_reuse_forbidden": True,
            "requirements": [
                "exact-execution-plan-sha256",
                "exact-execution-slurm-job-id",
                "exact-infrastructure-disposition",
                "score-validity-and-sft-eligibility-separated",
                "persisted-separate-verifier-artifacts-reopened",
            ],
        },
    }


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_LABEL_RE.fullmatch(args.run_label or "") is None:
        raise V10PlanError("run_label_invalid")
    revision = _source_revision(args.expected_revision)
    manifest = args.manifest.resolve(strict=True)
    manifest_body = _read(manifest, code="resource_manifest_invalid", private=True)
    if SHA256_RE.fullmatch(args.manifest_sha256 or "") is None or _sha256(manifest_body) != args.manifest_sha256:
        raise V10PlanError("resource_manifest_invalid")
    try:
        _manifest, entries = split.parse_manifest(manifest_body, args.manifest_sha256)
        partition = union.derive_union_partition(entries)
    except (OSError, ValueError) as error:
        raise V10PlanError("resource_manifest_invalid") from error
    image_manifest = args.image_manifest.resolve(strict=True)
    image_body = _read(image_manifest, code="image_manifest_invalid")
    if _sha256(image_body) != split.CANONICAL_IMAGE_MANIFEST_SHA256:
        raise V10PlanError("image_manifest_invalid")
    dataset_dir = _validated_dataset(args.dataset_dir)
    eval_root = args.eval_root.resolve(strict=True)
    if not eval_root.is_dir():
        raise V10PlanError("eval_root_invalid")
    base, base_body, base_path = _load_base()
    profile_body, profile_path = legacy._provider_profile()
    smoke_body, smoke_path = legacy._smoke_receipt(args.smoke_receipt, args.smoke_receipt_sha256)
    smoke_format_body, smoke_format_path = legacy._smoke_format_attestation(
        args.smoke_format_attestation,
        args.smoke_format_attestation_sha256,
        smoke_path=smoke_path,
        smoke_body=smoke_body,
    )
    soak_body, soak_path = legacy._sandoq_soak_receipt(args.sandoq_soak_receipt, args.sandoq_soak_receipt_sha256)
    try:
        binding, capacity_body = load_capacity_binding(args.capacity_receipt, args.capacity_receipt_sha256)
    except (OSError, ValueError) as error:
        raise V10PlanError("capacity_receipt_invalid") from error
    ready_body, ready_path = _ready_receipt(
        args.ready_receipt,
        args.ready_receipt_sha256,
        binding=binding,
    )
    directory = Path(os.path.abspath(args.output))
    run_output = eval_root / f"tb4-kimi-{args.run_label}-miniswe246-sandoq-firecracker-small"
    full_output = run_output / "full-denominator"
    if directory.exists() or directory.is_symlink() or run_output.exists() or full_output.exists():
        raise V10PlanError("output_not_fresh")
    supported_body = union._selector_payload(partition.sandoq_firecracker)
    compose_body = union._selector_payload(partition.compose_required)
    gpu_body = union._selector_payload(partition.gpu_unsupported)
    if (
        len(partition.sandoq_firecracker),
        len(partition.compose_required),
        len(partition.gpu_unsupported),
    ) != (SUPPORTED_TASKS, COMPOSE_UNSUPPORTED_TASKS, GPU_UNSUPPORTED_TASKS):
        raise V10PlanError("partition_invalid")
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
        revision=revision,
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
        soak_path=soak_path,
        soak_body=soak_body,
        capacity_path=binding.capacity_receipt_path,
        capacity_body=capacity_body,
        ready_path=ready_path,
        ready_body=ready_body,
        binding=binding,
        supported_body=supported_body,
        compose_body=compose_body,
        gpu_body=gpu_body,
        config_body=config_body,
        score_policy=_score_policy_artifacts(),
    )
    files = {
        SUPPORTED_SELECTOR: supported_body,
        COMPOSE_SELECTOR: compose_body,
        GPU_SELECTOR: gpu_body,
        CONFIG: config_body,
        PLAN: _canonical(plan),
    }
    try:
        split._publish_private_bundle(directory, files)
    except (OSError, ValueError) as error:
        raise V10PlanError("bundle_publish_failed") from error
    return {
        "state": "materialized",
        "executed_tasks": SUPPORTED_TASKS,
        "unsupported_tasks": COMPOSE_UNSUPPORTED_TASKS + GPU_UNSUPPORTED_TASKS,
        "denominator": split.TOTAL_TASKS,
        "concurrency": CONCURRENCY,
        "deployment_id": binding.deployment_id,
        "plan_sha256": _sha256(files[PLAN]),
    }


def verify(path: Path, expected_sha256: str) -> dict[str, Any]:
    held = split._HeldArtifactSet.create()
    try:
        body = _read(path, code="plan_invalid", private=True, held=held)
        if path.name != PLAN or SHA256_RE.fullmatch(expected_sha256 or "") is None or _sha256(body) != expected_sha256:
            raise V10PlanError("plan_invalid")
        plan = _strict_json(body, code="plan_invalid", canonical=True)
        revision = plan.get("execution_source_revision")
        if not isinstance(revision, str):
            raise V10PlanError("plan_invalid")
        _source_revision(revision)
        source = plan.get("source")
        lane = plan.get("lane")
        unsupported = plan.get("unsupported")
        if (
            plan.get("schema_version") != SCHEMA_VERSION
            or plan.get("kind") != KIND
            or plan.get("state") != "materialized"
            or plan.get("score_policy_baseline_revision") != SCORE_POLICY_BASELINE_REVISION
            or plan.get("required_adapter") != ADAPTER
            or not isinstance(source, dict)
            or not isinstance(lane, dict)
            or not isinstance(unsupported, dict)
        ):
            raise V10PlanError("plan_invalid")
        records: dict[str, tuple[Path, bytes]] = {}
        source_private = {
            "manifest",
            "historical_smoke_receipt",
            "historical_smoke_format_attestation",
            "historical_sandoq_c24_soak_receipt",
            "fresh_capacity_receipt",
            "fresh_ready_receipt",
        }
        for section, names in (
            (source, source_private | {"image_manifest", "base_config", "provider_profile"}),
            (lane, {"selector", "config"}),
            (unsupported, {"compose", "gpu"}),
        ):
            for name in names:
                record = section.get(name)
                if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
                    raise V10PlanError("plan_invalid")
                artifact_path = Path(str(record["path"]))
                artifact_body = _read(
                    artifact_path,
                    code="plan_artifact_invalid",
                    private=name in source_private or section is lane or section is unsupported,
                    held=held,
                )
                if _artifact(artifact_path, artifact_body) != record:
                    raise V10PlanError("plan_artifact_invalid")
                records[name] = (artifact_path, artifact_body)
        score_policy = source.get("score_policy")
        if not isinstance(score_policy, dict) or set(score_policy) != set(SCORE_POLICY_FILES):
            raise V10PlanError("score_policy_source_invalid")
        expected_score_policy = _score_policy_artifacts(held)
        if score_policy != expected_score_policy:
            raise V10PlanError("score_policy_source_invalid")
        try:
            binding, capacity_body = load_capacity_binding(
                records["fresh_capacity_receipt"][0],
                _sha256(records["fresh_capacity_receipt"][1]),
            )
        except (OSError, ValueError) as error:
            raise V10PlanError("capacity_receipt_invalid") from error
        ready_body, ready_path = _ready_receipt(
            records["fresh_ready_receipt"][0],
            _sha256(records["fresh_ready_receipt"][1]),
            binding=binding,
            held=held,
        )
        base, base_body, base_path = _load_base(held)
        profile_body, profile_path = legacy._provider_profile(held)
        smoke_body, smoke_path = legacy._smoke_receipt(
            records["historical_smoke_receipt"][0], legacy.SMOKE_RECEIPT_SHA256, held
        )
        smoke_format_body, smoke_format_path = legacy._smoke_format_attestation(
            records["historical_smoke_format_attestation"][0],
            legacy.SMOKE_FORMAT_ATTESTATION_SHA256,
            smoke_path=smoke_path,
            smoke_body=smoke_body,
            held=held,
        )
        soak_body, soak_path = legacy._sandoq_soak_receipt(
            records["historical_sandoq_c24_soak_receipt"][0],
            legacy.SANDOQ_SOAK_RECEIPT_SHA256,
            held,
        )
        manifest_path, manifest_body = records["manifest"]
        try:
            _manifest, entries = split.parse_manifest(manifest_body, _sha256(manifest_body))
            partition = union.derive_union_partition(entries)
        except (OSError, ValueError) as error:
            raise V10PlanError("resource_manifest_invalid") from error
        supported_body = union._selector_payload(partition.sandoq_firecracker)
        compose_body = union._selector_payload(partition.compose_required)
        gpu_body = union._selector_payload(partition.gpu_unsupported)
        if (
            records["selector"][1] != supported_body
            or records["compose"][1] != compose_body
            or records["gpu"][1] != gpu_body
        ):
            raise V10PlanError("partition_invalid")
        image_path, image_body = records["image_manifest"]
        config_path, config_body = records["config"]
        try:
            config = tomllib.loads(config_body.decode())
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise V10PlanError("config_invalid") from error
        dataset_dir = _validated_dataset(Path(str(config.get("taskset", {}).get("dataset_dir", ""))))
        run_output = Path(str(lane.get("output_dir", "")))
        full_output = Path(str(plan.get("full_output_dir", "")))
        if not run_output.is_absolute() or full_output != run_output / "full-denominator":
            raise V10PlanError("output_path_invalid")
        expected_config = _render_config(
            base,
            selector=records["selector"][0],
            selector_sha256=_sha256(supported_body),
            image_manifest=image_path,
            dataset_dir=dataset_dir,
        )
        expected = _expected_plan(
            directory=path.parent,
            run_output=run_output,
            full_output=full_output,
            revision=revision,
            manifest=manifest_path,
            manifest_body=manifest_body,
            image_manifest=image_path,
            image_body=image_body,
            base_path=base_path,
            base_body=base_body,
            profile_path=profile_path,
            profile_body=profile_body,
            smoke_path=smoke_path,
            smoke_body=smoke_body,
            smoke_format_path=smoke_format_path,
            smoke_format_body=smoke_format_body,
            soak_path=soak_path,
            soak_body=soak_body,
            capacity_path=binding.capacity_receipt_path,
            capacity_body=capacity_body,
            ready_path=ready_path,
            ready_body=ready_body,
            binding=binding,
            supported_body=supported_body,
            compose_body=compose_body,
            gpu_body=gpu_body,
            config_body=config_body,
            score_policy=expected_score_policy,
        )
        if plan != expected or config_body != expected_config:
            raise V10PlanError("plan_invalid")
        expected_files = {
            SUPPORTED_SELECTOR: supported_body,
            COMPOSE_SELECTOR: compose_body,
            GPU_SELECTOR: gpu_body,
            CONFIG: config_body,
            PLAN: body,
        }
        union._verify_bundle(path.parent, expected_files)
        held.revalidate()
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
            "full_output_dir": plan["full_output_dir"],
            "manifest": str(manifest_path),
            "manifest_sha256": _sha256(manifest_body),
            "adapter": ADAPTER,
            "deployment_root": str(binding.deployment_root),
            "deployment_id": binding.deployment_id,
            "capacity_receipt": str(binding.capacity_receipt_path),
            "capacity_receipt_sha256": binding.capacity_receipt_sha256,
            "ready_receipt": str(ready_path),
            "ready_receipt_sha256": _sha256(ready_body),
            "source_spec_sha256": binding.source_spec_sha256,
            "source_proxy_config_sha256": binding.source_proxy_config_sha256,
            "endpoint_bundle_sha256": binding.endpoint_bundle_sha256,
            "endpoint_authority_sha256": binding.endpoint_authority_sha256,
            "endpoint_jobs_sha256": binding.endpoint_jobs_sha256,
            "endpoint_file_sha256": binding.endpoint_file_sha256,
            "source_revision": revision,
        }
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, V10PlanError):
            raise
        raise V10PlanError("plan_invalid") from error
    finally:
        held.close()


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
    make.add_argument("--expected-revision", required=True)
    make.add_argument("--capacity-receipt", type=Path, required=True)
    make.add_argument("--capacity-receipt-sha256", required=True)
    make.add_argument("--ready-receipt", type=Path, required=True)
    make.add_argument("--ready-receipt-sha256", required=True)
    make.add_argument("--smoke-receipt", type=Path, default=legacy.DEFAULT_SMOKE_RECEIPT)
    make.add_argument("--smoke-receipt-sha256", default=legacy.SMOKE_RECEIPT_SHA256)
    make.add_argument(
        "--smoke-format-attestation",
        type=Path,
        default=legacy.DEFAULT_SMOKE_FORMAT_ATTESTATION,
    )
    make.add_argument(
        "--smoke-format-attestation-sha256",
        default=legacy.SMOKE_FORMAT_ATTESTATION_SHA256,
    )
    make.add_argument("--sandoq-soak-receipt", type=Path, default=legacy.DEFAULT_SANDOQ_SOAK_RECEIPT)
    make.add_argument("--sandoq-soak-receipt-sha256", default=legacy.SANDOQ_SOAK_RECEIPT_SHA256)
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
        print("kimi_tb4_sandoq_small_v10_plan_failed", file=sys.stderr)
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
            "deployment_root",
            "deployment_id",
            "capacity_receipt",
            "capacity_receipt_sha256",
            "ready_receipt",
            "ready_receipt_sha256",
            "source_spec_sha256",
            "source_proxy_config_sha256",
            "endpoint_bundle_sha256",
            "endpoint_authority_sha256",
            "endpoint_jobs_sha256",
            "endpoint_file_sha256",
            "source_revision",
        )
        values = tuple(str(result[field]) for field in fields)
        if any("\t" in value or "\n" in value for value in values):
            print("kimi_tb4_sandoq_small_v10_plan_failed", file=sys.stderr)
            return 2
        print("\t".join(values))
    else:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
