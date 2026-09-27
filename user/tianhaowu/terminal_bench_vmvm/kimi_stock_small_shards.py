#!/usr/bin/env python3
"""Plan and certify resumable Kimi 2,499-task stock/small shards.

Task membership is intentionally confined to mode-0600 artifacts.  Commands
print only counts, digests, shard indexes, and stable status codes.
"""

from __future__ import annotations

import argparse
import copy
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
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import audit_traces
import kimi_sandoq_production as legacy
import kimi_stock_small_task_image_soak as task_image_soak
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as tb4_small

SCHEMA_VERSION = 1
PLAN_KIND = "kimi-k3-stock-small-sharded-production-plan"
COMPLETION_KIND = "kimi-k3-stock-small-shard-completion"
FINAL_KIND = "kimi-k3-stock-small-sharded-production-completion"
LAUNCH_KIND = "kimi-k3-stock-small-shard-launch"
DEPLOYMENT_NAMESPACE = "kimi-stock-small-20260927"
MODEL = "Kimi-K3"
TOTAL_TASKS = 2_499
SHARD_COUNT = 40
CONCURRENCY = 64
MAX_SHARD_TASKS = 63
MAX_SEQUENCE_TOKENS = 262_144
SAMPLE_TOKENS = 32_768
REQUEST_TIMEOUT_SECONDS = 144_000
ROLLOUT_TIMEOUT_SECONDS = 129_600
SESSION_TIMEOUT_SECONDS = 144_000
MINIMUM_TB4_PASSES = 7
CPU_CAP = 1
MEMORY_MB_CAP = 2_048
STORAGE_MB_CAP = 10_240
PROVISIONING_RETRIES = 8
CAPACITY_PROFILE = "sandoq-stock-single-c64-v1"
ENDPOINT_IDENTIFIER = "tianhaowu-kimi-k3-stock-eval-20260927"
ENDPOINT_BUNDLE_SHA256 = "7ee38ee5d10c9cc7b04c2ddf9ff5b7813df148b2f7d425c1a4ff192f8fc4d581"
SOURCE_SPEC_SHA256 = "3b9d7b9e72767b9f65894ea024a08713ed10330c7d55c70cd99b2717056a9b39"
SOURCE_PROXY_SHA256 = "7894cd7205d0197620fa77edc747377e15c4e311769a0060be760659f5b29595"
STOCK_CAPACITY_SHA256 = "244dc901a555b4b73649c6185692c8a9d497319e0f8bcdcdb7373f6604c6f946"
STOCK_CAPACITY = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/"
    "kimi-stock-capacity-probes-20260927-v1/c64-fcedd7c6b.json"
)
SANDOQ_CAPACITY_SHA256 = "400d2c6cc39db2ab83c9dcec38a0e2870b76ced29e3bfb48bcd2478e8ba3b762"
SANDOQ_CAPACITY = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/"
    "sandoq-firecracker-small-c64-soak-20260927/run-1596293/receipt.json"
)
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
BASE_CONFIG_SHA256 = "d99aea0875e87849fc9c2fe2c561c52204bf5b71c91c94beb344239178c44779"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESULTS_ROW_BYTES = 128 * 1024 * 1024


class StockSmallError(ValueError):
    """A stock/small production artifact failed closed."""


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _base_config_path() -> Path:
    return (
        _workflow_dir()
        / "configs/eval/servers/cpu-132-021_8103/"
        "mobius_kimi_k3_stock_small_shard.base.toml"
    )


def _provider_profile_path() -> Path:
    return (
        _workflow_dir()
        / "configs/provider_context/use2/cpu-132-021_8103/"
        "kimi_sandoq_firecracker_small_host.json"
    )


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _plain_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


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
        raise StockSmallError(code) from error


def _json(body: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StockSmallError(code) from error
    if not isinstance(value, dict) or body != _canonical(value):
        raise StockSmallError(code)
    return value


def _json_line(body: bytes, *, code: str) -> dict[str, Any]:
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
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise StockSmallError(code) from error
    if not isinstance(value, dict):
        raise StockSmallError(code)
    return value


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StockSmallError("source_identity_invalid") from error
    if completed.stderr:
        raise StockSmallError("source_identity_invalid")
    return completed.stdout.strip()


def _validate_source(project_root: Path, expected_revision: str) -> Path:
    if REVISION_RE.fullmatch(expected_revision) is None:
        raise StockSmallError("source_identity_invalid")
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("source_identity_invalid") from error
    if root != project_root or not root.is_dir():
        raise StockSmallError("source_identity_invalid")
    repositories = (root, root / "deps/verifiers", root / "deps/renderers")
    if _git(root, "rev-parse", "HEAD") != expected_revision or any(
        _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
        for repository in repositories
    ):
        raise StockSmallError("source_identity_invalid")
    return root


def _load_base(held: split._HeldArtifactSet | None = None) -> tuple[dict[str, Any], bytes, Path]:
    path = _base_config_path().resolve(strict=True)
    body = _read(path, code="base_config_invalid", held=held)
    if _sha256(body) != BASE_CONFIG_SHA256:
        raise StockSmallError("base_config_invalid")
    try:
        value = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise StockSmallError("base_config_invalid") from error
    client = value.get("client")
    sampling = value.get("sampling")
    taskset = value.get("taskset")
    harness = value.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    if (
        value.get("model") != MODEL
        or value.get("num_tasks") != 1
        or value.get("num_rollouts") != 1
        or value.get("max_concurrent") != CONCURRENCY
        or value.get("multiplex") != CONCURRENCY
        or value.get("max_turns") != 200
        or any(value.get(key) != MAX_SEQUENCE_TOKENS for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
        or value.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or client.get("timeout") != REQUEST_TIMEOUT_SECONDS
        or client.get("max_connections") != CONCURRENCY
        or client.get("max_keepalive_connections") != CONCURRENCY
        or client.get("max_retries") != 0
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != SAMPLE_TOKENS
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, dict)
        or taskset.get("dataset_revision") != legacy.CANONICAL_DATASET_REVISION
        or taskset.get("enable_compose") is not False
        or taskset.get("resource_multiplier") != 1.0
        or taskset.get("resource_cpu_cap") != CPU_CAP
        or taskset.get("resource_memory_mb_cap") != MEMORY_MB_CAP
        or taskset.get("resource_storage_mb_cap") != STORAGE_MB_CAP
        or taskset.get("verifier_runtime_retries") != 2
        or taskset.get("retry_shared_verifier_scoring") is not True
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != "2.4.6"
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
            "session_timeout": SESSION_TIMEOUT_SECONDS,
            "network_access": True,
            "host_tunnel": "sandoq",
            "buffered_chat_completions": True,
            "guest_tunnel_url": "http://127.0.0.1:8485",
            "tunnel_pool_size": 4,
            "tunnel_ready_timeout": 30,
            "provisioning_retries": PROVISIONING_RETRIES,
            "expected_environment": "oci-runner-firecracker-small",
            "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
        }
        or value.get("timeout")
        != {"setup": 3_600, "rollout": ROLLOUT_TIMEOUT_SECONDS, "finalize": 3_600, "scoring": 21_600}
        or value.get("retries", {}).get("rollout", {}).get("max_retries") != 0
    ):
        raise StockSmallError("base_config_contract_invalid")
    return value, body, path


def _validate_provider_profile(held: split._HeldArtifactSet | None = None) -> tuple[Path, bytes]:
    path = _provider_profile_path().resolve(strict=True)
    body = _read(path, code="provider_profile_invalid", held=held)
    if _sha256(body) != PROVIDER_PROFILE_SHA256:
        raise StockSmallError("provider_profile_invalid")
    value = _json(body, code="provider_profile_invalid")
    if (
        value.get("environment") != "oci-runner-firecracker-small"
        or value.get("task_network") != "host"
        or value.get("effective_task_network") != "public"
        or value.get("transport_mode") != "auto"
    ):
        raise StockSmallError("provider_profile_invalid")
    return path, body


def _validate_stock_capacity(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes]:
    try:
        body, canonical = tb4_small._capacity_receipt(path, expected_sha256, held)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("stock_capacity_receipt_invalid") from error
    return canonical, body


def _validate_sandoq_capacity(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes]:
    try:
        canonical = path.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("sandoq_capacity_receipt_invalid") from error
    body = _read(canonical, code="sandoq_capacity_receipt_invalid", private=True, held=held)
    if expected_sha256 != SANDOQ_CAPACITY_SHA256 or _sha256(body) != expected_sha256:
        raise StockSmallError("sandoq_capacity_receipt_invalid")
    value = _json(body, code="sandoq_capacity_receipt_invalid")
    count = CONCURRENCY
    failures = value.get("create_failure_counts")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "sandoq-firecracker-small-c64-soak"
        or value.get("state") != "passed"
        or value.get("environment") != "oci-runner-firecracker-small"
        or value.get("profile_sha256") != PROVIDER_PROFILE_SHA256
        or any(value.get(key) != count for key in (
            "requested_concurrency",
            "create_attempts",
            "sessions_returned",
            "simultaneous_ready_verified",
            "delete_attempts",
            "typed_404_verified",
        ))
        or value.get("cleanup_failures") != 0
        or value.get("client_close_verified") is not True
        or value.get("mtls_available") is not True
        or value.get("transport_mode") != "proxy"
        or not isinstance(failures, dict)
        or any(item != 0 for item in failures.values())
    ):
        raise StockSmallError("sandoq_capacity_receipt_invalid")
    return canonical, body


def _validate_tb4_gate(
    path: Path,
    expected_sha256: str,
    expected_revision: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise StockSmallError("tb4_gate_invalid")
    try:
        canonical = path.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("tb4_gate_invalid") from error
    body = _read(canonical, code="tb4_gate_invalid", private=True, held=held)
    if _sha256(body) != expected_sha256:
        raise StockSmallError("tb4_gate_invalid")
    value = _json(body, code="tb4_gate_invalid")
    counts = value.get("counts")
    scores = value.get("scores")
    policy = value.get("policy")
    provider = value.get("provider_context")
    artifacts = value.get("artifacts")
    count_values = ()
    if isinstance(counts, dict):
        count_values = tuple(
            counts.get(key) for key in ("denominator", "executed", "compose_unsupported", "gpu_unsupported", "passes", "failures")
        )
    counts_are_integers = len(count_values) == 6 and all(map(_plain_nonnegative_integer, count_values))
    rate = scores.get("all_task_pass_rate") if isinstance(scores, dict) else None
    rate_is_number = isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(float(rate))
    identity_path: Path | None = None
    if isinstance(artifacts, dict):
        executed = artifacts.get("executed_results")
        if isinstance(executed, dict) and isinstance(executed.get("path"), str):
            identity_path = Path(executed["path"]).parent / "eval_run_identity.json"
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic"
        or value.get("state") != "passed"
        or value.get("source_revision") != expected_revision
        or value.get("result_label") != "resource-clamped-firecracker-small-diagnostic"
        or not isinstance(counts, dict)
        or not counts_are_integers
        or counts.get("denominator") != 66
        or counts.get("executed") != 52
        or counts["compose_unsupported"] < 0
        or counts["gpu_unsupported"] < 0
        or counts.get("compose_unsupported") + counts.get("gpu_unsupported") != 14
        or not 0 <= counts["passes"] <= counts["executed"]
        or counts["passes"] < MINIMUM_TB4_PASSES
        or counts.get("failures") != 66 - counts["passes"]
        or not isinstance(scores, dict)
        or not rate_is_number
        or not math.isclose(float(rate), counts["passes"] / 66)
        or not isinstance(policy, dict)
        or policy.get("model_io_response_kind") != "exact_provider_json"
        or policy.get("reasoning_required") is not True
        or policy.get("reasoning_message_parity_required") is not True
        or policy.get("request_graph_match_required") is not True
        or policy.get("model_retries") != 0
        or policy.get("verifier_runtime_retries") != 2
        or policy.get("retry_shared_verifier_scoring") is not True
        or policy.get("provisioning_retries") != PROVISIONING_RETRIES
        or policy.get("timeouts", {}).get("request_seconds") != REQUEST_TIMEOUT_SECONDS
        or policy.get("timeouts", {}).get("rollout_seconds") != ROLLOUT_TIMEOUT_SECONDS
        or not isinstance(provider, dict)
        or provider.get("provider_environment") != "oci-runner-firecracker-small"
        or provider.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or identity_path is None
    ):
        raise StockSmallError("tb4_gate_invalid")
    identity_body = _read(identity_path, code="tb4_gate_identity_invalid", private=True, held=held)
    if _sha256(identity_body) != value.get("eval_run_identity_sha256"):
        raise StockSmallError("tb4_gate_identity_invalid")
    try:
        from eval_run_identity import load_eval_run_identity_bytes

        identity_envelope = load_eval_run_identity_bytes(
            identity_body,
            run_dir=identity_path.parent,
            verify_references=True,
            verify_saved_provenance=True,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_identity_invalid") from error
    identity = identity_envelope.get("identity")
    router = identity.get("deployment", {}).get("router") if isinstance(identity, dict) else None
    if (
        not isinstance(identity, dict)
        or identity.get("role") != "kimi-direct-tb4-small-diagnostic"
        or identity.get("source", {}).get("prime_rl_commit") != expected_revision
        or not isinstance(router, dict)
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier") != ENDPOINT_IDENTIFIER
        or router.get("worker_count") != 1
        or router.get("provider_concurrency") != CONCURRENCY
        or identity.get("deployment", {}).get("spec_sha256") != SOURCE_SPEC_SHA256
        or identity.get("deployment", {}).get("endpoint_bundle_sha256") != ENDPOINT_BUNDLE_SHA256
    ):
        raise StockSmallError("tb4_gate_identity_invalid")
    task_record = identity.get("inputs", {}).get("task_file")
    executed_record = artifacts.get("executed_results") if isinstance(artifacts, dict) else None
    if (
        not isinstance(task_record, dict)
        or set(task_record) != {"path", "sha256", "count"}
        or task_record.get("count") != 52
        or not isinstance(executed_record, dict)
        or set(executed_record) != {"path", "bytes", "sha256"}
    ):
        raise StockSmallError("tb4_gate_trace_invalid")
    selector_path = Path(str(task_record["path"]))
    selector_body = _read(selector_path, code="tb4_gate_selector_invalid", private=True, held=held)
    if task_record.get("sha256") != _sha256(selector_body):
        raise StockSmallError("tb4_gate_selector_invalid")
    try:
        members = tuple(selector_body.decode().splitlines())
    except UnicodeDecodeError as error:
        raise StockSmallError("tb4_gate_selector_invalid") from error
    if len(members) != 52 or len(set(members)) != 52 or selector_body != legacy._task_payload(members):
        raise StockSmallError("tb4_gate_selector_invalid")
    try:
        trace_audit, rows, result_artifact = split._audit_cpu_results(
            Path(str(executed_record["path"])),
            members,
            {member: "separate" for member in members},
            held,
            require_exact_provider_json=True,
            required_response_kind="exact_provider_json",
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_trace_invalid") from error
    if (
        result_artifact != executed_record
        or trace_audit != value.get("trace_audit")
        or trace_audit.get("passes") != counts["passes"]
        or trace_audit.get("trace_failures") != 0
        or any(audit_traces._clean_stop_problem(row) is not None for row in rows.values())
    ):
        raise StockSmallError("tb4_gate_trace_invalid")
    return canonical, body


def _split_members(members: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    if len(members) != TOTAL_TASKS or len(set(members)) != TOTAL_TASKS:
        raise StockSmallError("selector_invalid")
    shards = tuple(tuple(members[index::SHARD_COUNT]) for index in range(SHARD_COUNT))
    flattened = tuple(member for offset in range(SHARD_COUNT) for member in shards[offset])
    if (
        len(flattened) != TOTAL_TASKS
        or set(flattened) != set(members)
        or any(not 1 <= len(shard) <= MAX_SHARD_TASKS for shard in shards)
    ):
        raise StockSmallError("shard_partition_invalid")
    return shards


def _render_config(
    base: Mapping[str, Any],
    *,
    count: int,
    selector: Path,
    selector_sha256: str,
    dataset: Path,
    image_manifest: Path,
) -> bytes:
    value = copy.deepcopy(dict(base))
    value["num_tasks"] = count
    taskset = value["taskset"]
    taskset["dataset_dir"] = str(dataset)
    taskset["task_file"] = str(selector)
    taskset["task_file_sha256"] = selector_sha256
    taskset["image_manifest"] = str(image_manifest)
    return union._render_toml(value)


def _contracts() -> dict[str, Any]:
    return {
        "model": MODEL,
        "harness": {"id": "mini-swe-agent", "version": "2.4.6"},
        "total_tasks": TOTAL_TASKS,
        "shards": SHARD_COUNT,
        "shard_algorithm": "canonical-order-round-robin-v1",
        "max_tasks_per_shard": MAX_SHARD_TASKS,
        "rollout_concurrency": CONCURRENCY,
        "context_tokens": MAX_SEQUENCE_TOKENS,
        "sample_tokens": SAMPLE_TOKENS,
        "reasoning_effort": "max",
        "reasoning_required": True,
        "reasoning_message_parity_required": True,
        "model_io_response_kind": "exact_provider_json",
        "request_graph_match_required": True,
        "model_attempts": 1,
        "model_retries": 0,
        "zero_model_resume_attempts": 0,
        "verifier_recovery": {
            "mode": "same-post-agent-runtime-scoring-only",
            "retries": 2,
            "maximum_attempts": 3,
            "model_calls": 0,
            "infrastructure_errors_remain_errors": True,
        },
        "timeouts": {
            "request_seconds": REQUEST_TIMEOUT_SECONDS,
            "session_seconds": SESSION_TIMEOUT_SECONDS,
            "rollout_seconds": ROLLOUT_TIMEOUT_SECONDS,
            "setup_seconds": 3_600,
            "finalize_seconds": 3_600,
            "scoring_seconds": 21_600,
        },
        "sandbox": {
            "provider": "sandoq",
            "environment": "oci-runner-firecracker-small",
            "task_network": "host",
            "effective_network": "public",
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
            "capacity": CONCURRENCY,
            "provisioning_retries": PROVISIONING_RETRIES,
            "provisioning_retry_scope": "pre-model-only",
        },
        "router": {
            "profile": CAPACITY_PROFILE,
            "endpoint_identifier": ENDPOINT_IDENTIFIER,
            "worker_count": 1,
            "per_worker_capacity": CONCURRENCY,
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "retries": 0,
        },
        "prelaunch_gates": {
            "tb4": {
                "minimum_passes": MINIMUM_TB4_PASSES,
                "denominator": 66,
                "response_kind": "exact_provider_json",
            },
            "real_task_image_c64_soak": {
                "kind": task_image_soak.RECEIPT_KIND,
                "task_count": task_image_soak.SELECTED_TASKS,
                "concurrency": task_image_soak.CONCURRENCY,
                "minimum_endpoint_remaining_seconds": (
                    task_image_soak.MINIMUM_ENDPOINT_REMAINING_SECONDS
                ),
                "model_calls": 0,
                "harness_invocations": 0,
            },
        },
        "resume": {
            "unit": "completed-shard-receipt",
            "partial_attempt_reuse": False,
            "model_bearing_retry": False,
            "zero_model_rows": "uncertifiable-manual-recovery",
            "cross_job": True,
            "endpoint_epoch_bound": True,
            "rollover_policy": "new-plan-required",
        },
        "security_task_handling": "opaque-execution-aggregate-only",
        "membership_disclosed": False,
    }


def materialize(
    *,
    project_root: Path,
    expected_revision: str,
    source: Path,
    dataset: Path,
    image_manifest: Path,
    tb4_certificate: Path,
    tb4_certificate_sha256: str,
    task_image_soak_receipt: Path,
    task_image_soak_receipt_sha256: str,
    output: Path,
    run_root: Path,
    stock_capacity: Path = STOCK_CAPACITY,
    stock_capacity_sha256: str = STOCK_CAPACITY_SHA256,
    sandoq_capacity: Path = SANDOQ_CAPACITY,
    sandoq_capacity_sha256: str = SANDOQ_CAPACITY_SHA256,
) -> dict[str, Any]:
    root = _validate_source(project_root, expected_revision)
    if not output.is_absolute() or not run_root.is_absolute():
        raise StockSmallError("output_namespace_invalid")
    if output.exists() or output.is_symlink() or run_root.exists() or run_root.is_symlink():
        raise StockSmallError("output_namespace_not_fresh")
    try:
        run_root_parent = legacy._private_root(run_root.parent)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("run_root_parent_invalid") from error
    if run_root != run_root_parent / run_root.name or run_root.name in {"", ".", ".."}:
        raise StockSmallError("run_root_parent_invalid")
    base, base_body, base_path = _load_base()
    provider_path, provider_body = _validate_provider_profile()
    stock_path, stock_body = _validate_stock_capacity(stock_capacity, stock_capacity_sha256)
    sandoq_path, sandoq_body = _validate_sandoq_capacity(sandoq_capacity, sandoq_capacity_sha256)
    tb4_path, tb4_body = _validate_tb4_gate(
        tb4_certificate,
        tb4_certificate_sha256,
        expected_revision,
    )
    try:
        task_soak_path, task_soak_body = task_image_soak.validate_task_image_soak_receipt(
            task_image_soak_receipt,
            task_image_soak_receipt_sha256,
            expected_revision=expected_revision,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("task_image_soak_receipt_invalid") from error
    source_path = source.resolve(strict=True)
    source_body = _read(source_path, code="approved_source_invalid")
    if source_path != legacy._canonical_source_path() or _sha256(source_body) != legacy.CANONICAL_SOURCE_SHA256:
        raise StockSmallError("approved_source_invalid")
    try:
        dataset_path = legacy.verify_canonical_dataset(dataset)
        partition = legacy.derive_partition(source_body, dataset_path)
    except Exception as error:
        raise StockSmallError("opaque_selection_invalid") from error
    if (
        partition.no_network_count != legacy.EXPECTED_SOURCE_COUNT
        or len(partition.sandoq) != TOTAL_TASKS
        or len(partition.vmvm) != legacy.EXPECTED_EXCLUDED_COUNT
    ):
        raise StockSmallError("opaque_selection_invalid")
    image_path = image_manifest.resolve(strict=True)
    image_body = _read(image_path, code="image_manifest_invalid", maximum_bytes=128 * 1024 * 1024)
    if _sha256(image_body) != IMAGE_MANIFEST_SHA256:
        raise StockSmallError("image_manifest_invalid")

    master_body = legacy._task_payload(partition.sandoq)
    master_receipt = legacy._selector_receipt(
        master_body,
        legacy._resource_coverage(dataset_path, partition.sandoq),
    )
    shards = _split_members(partition.sandoq)
    plan_files: dict[str, bytes] = {
        "selector.tasks.txt": master_body,
        "selector.receipt.json": legacy.canonical_json(master_receipt),
    }
    shard_records: list[dict[str, Any]] = []
    for index, members in enumerate(shards):
        selector_name = f"shard-{index:02d}.tasks.txt"
        config_name = f"shard-{index:02d}.toml"
        selector_path = output / selector_name
        config_path = output / config_name
        selector_body = legacy._task_payload(members)
        config_body = _render_config(
            base,
            count=len(members),
            selector=selector_path,
            selector_sha256=_sha256(selector_body),
            dataset=dataset_path,
            image_manifest=image_path,
        )
        plan_files[selector_name] = selector_body
        plan_files[config_name] = config_body
        shard_records.append(
            {
                "index": index,
                "count": len(members),
                "selector": _artifact(selector_path, selector_body),
                "config": _artifact(config_path, config_body),
                "run_root": str(run_root / f"shard-{index:02d}"),
            }
        )
    plan = {
        "schema_version": SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "state": "authorized",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "source_revision": expected_revision,
        "contracts": _contracts(),
        "source": {
            "project_root": str(root),
            "approved_selector_source": _artifact(source_path, source_body),
            "dataset": {"path": str(dataset_path), "revision": legacy.CANONICAL_DATASET_REVISION},
            "image_manifest": _artifact(image_path, image_body),
            "base_config": _artifact(base_path, base_body),
            "provider_profile": _artifact(provider_path, provider_body),
            "tb4_gate": _artifact(tb4_path, tb4_body),
            "task_image_c64_soak": _artifact(task_soak_path, task_soak_body),
            "stock_model_c64": _artifact(stock_path, stock_body),
            "sandoq_small_c64": _artifact(sandoq_path, sandoq_body),
        },
        "selection": {
            "approved_count": legacy.EXPECTED_SOURCE_COUNT,
            "selected_count": TOTAL_TASKS,
            "excluded_count": legacy.EXPECTED_EXCLUDED_COUNT,
            "selector": _artifact(output / "selector.tasks.txt", master_body),
            "receipt": _artifact(output / "selector.receipt.json", legacy.canonical_json(master_receipt)),
        },
        "run_root": str(run_root),
        "shards": shard_records,
    }
    plan["plan_sha256"] = _sha256(_canonical(plan))
    plan_files["plan.json"] = _canonical(plan)
    try:
        split._publish_private_bundle(output, plan_files)
        os.mkdir(run_root, 0o700)
    except Exception as error:
        raise StockSmallError("publication_failed") from error
    return {
        "state": "authorized",
        "selected_tasks": TOTAL_TASKS,
        "shards": SHARD_COUNT,
        "maximum_shard_tasks": max(map(len, shards)),
        "plan": str(output / "plan.json"),
        "plan_sha256": _sha256(plan_files["plan.json"]),
    }


def _record_body(
    record: object,
    *,
    code: str,
    private: bool,
    held: split._HeldArtifactSet,
) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise StockSmallError(code)
    path = Path(str(record.get("path", "")))
    body = _read(path, code=code, private=private, held=held, maximum_bytes=512 * 1024 * 1024)
    if record != _artifact(path, body):
        raise StockSmallError(code)
    return path, body


def _verify_with_held(
    plan_path: Path,
    plan_sha256: str,
    held: split._HeldArtifactSet,
) -> dict[str, Any]:
    body = _read(plan_path, code="plan_invalid", private=True, held=held)
    if _sha256(body) != plan_sha256:
        raise StockSmallError("plan_invalid")
    plan = _json(body, code="plan_invalid")
    unsigned = dict(plan)
    claimed = unsigned.pop("plan_sha256", None)
    if (
        plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("kind") != PLAN_KIND
        or plan.get("state") != "authorized"
        or plan.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or claimed != _sha256(_canonical(unsigned))
        or plan.get("contracts") != _contracts()
        or not isinstance(plan.get("source"), dict)
        or not isinstance(plan.get("selection"), dict)
        or not isinstance(plan.get("shards"), list)
        or len(plan["shards"]) != SHARD_COUNT
        or REVISION_RE.fullmatch(str(plan.get("source_revision", ""))) is None
    ):
        raise StockSmallError("plan_invalid")
    source = plan["source"]
    if set(source) != {
        "project_root",
        "approved_selector_source",
        "dataset",
        "image_manifest",
        "base_config",
        "provider_profile",
        "tb4_gate",
        "task_image_c64_soak",
        "stock_model_c64",
        "sandoq_small_c64",
    } or set(plan["selection"]) != {
        "approved_count",
        "selected_count",
        "excluded_count",
        "selector",
        "receipt",
    }:
        raise StockSmallError("plan_invalid")
    project_root = Path(str(source.get("project_root", "")))
    _validate_source(project_root, str(plan["source_revision"]))
    records: dict[str, tuple[Path, bytes]] = {}
    for key, private in (
        ("approved_selector_source", False),
        ("image_manifest", False),
        ("base_config", False),
        ("provider_profile", False),
        ("tb4_gate", True),
        ("task_image_c64_soak", True),
        ("stock_model_c64", True),
        ("sandoq_small_c64", True),
    ):
        records[key] = _record_body(source.get(key), code=f"{key}_invalid", private=private, held=held)
    dataset = source.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) != {"path", "revision"}:
        raise StockSmallError("dataset_invalid")
    dataset_path = Path(str(dataset["path"])).resolve(strict=True)
    if dataset.get("revision") != legacy.CANONICAL_DATASET_REVISION:
        raise StockSmallError("dataset_invalid")
    if (
        records["approved_selector_source"][0] != legacy._canonical_source_path()
        or _sha256(records["approved_selector_source"][1]) != legacy.CANONICAL_SOURCE_SHA256
        or _sha256(records["image_manifest"][1]) != IMAGE_MANIFEST_SHA256
        or _sha256(records["base_config"][1]) != BASE_CONFIG_SHA256
        or _sha256(records["provider_profile"][1]) != PROVIDER_PROFILE_SHA256
    ):
        raise StockSmallError("plan_source_invalid")
    _validate_stock_capacity(records["stock_model_c64"][0], STOCK_CAPACITY_SHA256, held)
    _validate_sandoq_capacity(records["sandoq_small_c64"][0], SANDOQ_CAPACITY_SHA256, held)
    _validate_tb4_gate(
        records["tb4_gate"][0],
        _sha256(records["tb4_gate"][1]),
        str(plan["source_revision"]),
        held,
    )
    try:
        task_image_soak.validate_task_image_soak_receipt(
            records["task_image_c64_soak"][0],
            _sha256(records["task_image_c64_soak"][1]),
            expected_revision=str(plan["source_revision"]),
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("task_image_soak_receipt_invalid") from error
    try:
        partition = legacy.derive_partition(
            records["approved_selector_source"][1],
            legacy.verify_canonical_dataset(dataset_path),
        )
    except Exception as error:
        raise StockSmallError("opaque_selection_invalid") from error
    members = tuple(partition.sandoq)
    shards = _split_members(members)
    master_path, master_body = _record_body(
        plan["selection"].get("selector"), code="selector_invalid", private=True, held=held
    )
    receipt_path, receipt_body = _record_body(
        plan["selection"].get("receipt"), code="selector_receipt_invalid", private=True, held=held
    )
    expected_master = legacy._task_payload(members)
    expected_receipt = legacy._selector_receipt(
        expected_master,
        legacy._resource_coverage(dataset_path, members),
    )
    if (
        master_body != expected_master
        or receipt_body != legacy.canonical_json(expected_receipt)
        or plan["selection"].get("approved_count") != legacy.EXPECTED_SOURCE_COUNT
        or plan["selection"].get("selected_count") != TOTAL_TASKS
        or plan["selection"].get("excluded_count") != legacy.EXPECTED_EXCLUDED_COUNT
    ):
        raise StockSmallError("selector_invalid")
    base, _base_body, _base_path = _load_base(held)
    image_path = records["image_manifest"][0]
    run_root = Path(str(plan.get("run_root", "")))
    if not run_root.is_absolute() or run_root.resolve(strict=True) != run_root:
        raise StockSmallError("run_root_invalid")
    observed_records: list[dict[str, Any]] = []
    for index, (record, expected_members) in enumerate(zip(plan["shards"], shards, strict=True)):
        if not isinstance(record, dict) or record.get("index") != index or record.get("count") != len(expected_members):
            raise StockSmallError("shard_invalid")
        selector_path, selector_body = _record_body(
            record.get("selector"), code="shard_selector_invalid", private=True, held=held
        )
        config_path, config_body = _record_body(
            record.get("config"), code="shard_config_invalid", private=True, held=held
        )
        expected_selector = legacy._task_payload(expected_members)
        expected_config = _render_config(
            base,
            count=len(expected_members),
            selector=selector_path,
            selector_sha256=_sha256(expected_selector),
            dataset=dataset_path,
            image_manifest=image_path,
        )
        if (
            selector_body != expected_selector
            or config_body != expected_config
            or record.get("run_root") != str(run_root / f"shard-{index:02d}")
        ):
            raise StockSmallError("shard_invalid")
        observed_records.append(record)
    del master_path, receipt_path, observed_records
    held.revalidate()
    return plan


def verify(plan_path: Path, plan_sha256: str) -> dict[str, Any]:
    held = split._HeldArtifactSet.create()
    try:
        return _verify_with_held(plan_path.resolve(strict=True), plan_sha256, held)
    finally:
        held.close()


def shard_binding(plan_path: Path, plan_sha256: str, index: int) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    if not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_index_invalid")
    shard = plan["shards"][index]
    return {
        "plan": str(plan_path.resolve(strict=True)),
        "plan_sha256": plan_sha256,
        "source_revision": plan["source_revision"],
        "index": index,
        "count": shard["count"],
        "selector": shard["selector"]["path"],
        "selector_sha256": shard["selector"]["sha256"],
        "config": shard["config"]["path"],
        "config_sha256": shard["config"]["sha256"],
        "run_root": shard["run_root"],
    }


def _validated_worker_manifest(path: Path, expected_sha256: str) -> tuple[Path, bytes, dict[str, Any]]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise StockSmallError("worker_manifest_invalid")
    try:
        canonical = path.resolve(strict=True)
        body = _read(canonical, code="worker_manifest_invalid", private=True)
        from direct_kimi_workers import validate_saved_manifest

        manifest = validate_saved_manifest(canonical, body=body)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("worker_manifest_invalid") from error
    router = manifest.get("router")
    workers = manifest.get("workers")
    if (
        canonical != path
        or _sha256(body) != expected_sha256
        or manifest.get("source_spec_sha256") != SOURCE_SPEC_SHA256
        or manifest.get("source_proxy_config_sha256") != SOURCE_PROXY_SHA256
        or manifest.get("endpoint_bundle_sha256") != ENDPOINT_BUNDLE_SHA256
        or not isinstance(router, dict)
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier") != ENDPOINT_IDENTIFIER
        or router.get("max_concurrent_requests") != CONCURRENCY
        or router.get("per_worker_capacity") != CONCURRENCY
        or router.get("request_timeout_seconds") != REQUEST_TIMEOUT_SECONDS
        or router.get("retries") != 0
        or not isinstance(workers, list)
        or len(workers) != 1
    ):
        raise StockSmallError("worker_manifest_invalid")
    return canonical, body, manifest


def _capacity_endpoint_jobs_sha256(plan: Mapping[str, Any]) -> str:
    record = plan.get("source", {}).get("stock_model_c64")
    if not isinstance(record, dict):
        raise StockSmallError("stock_capacity_receipt_invalid")
    body = _read(
        Path(str(record.get("path", ""))),
        code="stock_capacity_receipt_invalid",
        private=True,
    )
    if record != _artifact(Path(str(record.get("path", ""))), body):
        raise StockSmallError("stock_capacity_receipt_invalid")
    value = _json(body, code="stock_capacity_receipt_invalid")
    endpoint_job_id = value.get("deployment", {}).get("endpoint_job_id")
    if not isinstance(endpoint_job_id, str) or re.fullmatch(r"[1-9][0-9]*", endpoint_job_id) is None:
        raise StockSmallError("stock_capacity_receipt_invalid")
    return _sha256(f"{endpoint_job_id}\n".encode())


def create_launch(
    *,
    plan_path: Path,
    plan_sha256: str,
    index: int,
    worker_manifest: Path,
    worker_manifest_sha256: str,
    run_dir: Path,
    output: Path,
) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    if not 0 <= index < SHARD_COUNT or SHA256_RE.fullmatch(worker_manifest_sha256) is None:
        raise StockSmallError("shard_launch_invalid")
    shard = plan["shards"][index]
    manifest_path, manifest_body, manifest = _validated_worker_manifest(worker_manifest, worker_manifest_sha256)
    router = manifest.get("router")
    if (
        not isinstance(router, dict)
        or SHA256_RE.fullmatch(str(router.get("implementation_sha256", ""))) is None
    ):
        raise StockSmallError("worker_manifest_invalid")
    shard_root = Path(shard["run_root"])
    if (
        not run_dir.is_absolute()
        or run_dir.parent != shard_root
        or not re.fullmatch(r"attempt-[1-9][0-9]*", run_dir.name)
        or run_dir.exists()
        or run_dir.is_symlink()
    ):
        raise StockSmallError("run_directory_invalid")
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": LAUNCH_KIND,
        "state": "authorized",
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "source_revision": plan["source_revision"],
        "shard": {
            "index": index,
            "count": shard["count"],
            "selector": shard["selector"],
            "config": shard["config"],
        },
        "run_dir": str(run_dir),
        "worker_manifest": _artifact(manifest_path, manifest_body),
        "deployment": {
            "capacity_profile": CAPACITY_PROFILE,
            "endpoint_identifier": ENDPOINT_IDENTIFIER,
            "endpoint_bundle_sha256": ENDPOINT_BUNDLE_SHA256,
            "source_spec_sha256": SOURCE_SPEC_SHA256,
            "router_implementation_sha256": router.get("implementation_sha256"),
            "endpoint_jobs_sha256": _capacity_endpoint_jobs_sha256(plan),
            "worker_count": 1,
            "per_worker_capacity": CONCURRENCY,
        },
        "execution": {
            "requested_concurrency": CONCURRENCY,
            "pool_size": CONCURRENCY,
            "sandbox_environment": "oci-runner-firecracker-small",
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "provisioning_retries": PROVISIONING_RETRIES,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "session_timeout_seconds": SESSION_TIMEOUT_SECONDS,
            "rollout_timeout_seconds": ROLLOUT_TIMEOUT_SECONDS,
            "model_retries": 0,
            "zero_model_resume_attempts": 0,
            "verifier_runtime_retries": 2,
            "verifier_retry_mode": "same-post-agent-runtime-scoring-only",
        },
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning": True,
            "request_graph": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        },
    }
    value["launch_sha256"] = _sha256(_canonical(value))
    try:
        legacy._publish_bundle(output.parent, {output: _canonical(value)})
    except Exception as error:
        raise StockSmallError("shard_launch_publication_failed") from error
    return {
        "state": "authorized",
        "shard": index,
        "count": shard["count"],
        "launch": str(output),
        "launch_sha256": _sha256(_canonical(value)),
    }


def validate_launch(
    launch_path: Path,
    launch_sha256: str,
    *,
    config_sha256: str | None = None,
    selector_sha256: str | None = None,
    worker_manifest_sha256: str | None = None,
    source_spec_sha256: str | None = None,
    endpoint_bundle_sha256: str | None = None,
    router_implementation_sha256: str | None = None,
    concurrency: int | None = None,
) -> dict[str, Any]:
    body = _read(launch_path, code="shard_launch_invalid", private=True)
    if _sha256(body) != launch_sha256:
        raise StockSmallError("shard_launch_invalid")
    value = _json(body, code="shard_launch_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("launch_sha256", None)
    plan_record = value.get("plan")
    shard_record = value.get("shard")
    deployment = value.get("deployment")
    execution = value.get("execution")
    manifest_record = value.get("worker_manifest")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != LAUNCH_KIND
        or value.get("state") != "authorized"
        or claimed != _sha256(_canonical(unsigned))
        or not isinstance(plan_record, dict)
        or set(plan_record) != {"path", "sha256"}
        or SHA256_RE.fullmatch(str(plan_record.get("sha256", ""))) is None
        or not isinstance(shard_record, dict)
        or not isinstance(deployment, dict)
        or not isinstance(execution, dict)
        or not isinstance(manifest_record, dict)
        or set(manifest_record) != {"path", "bytes", "sha256"}
        or value.get("capture")
        != {
            "response_kind": "exact_provider_json",
            "reasoning": True,
            "request_graph": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        }
    ):
        raise StockSmallError("shard_launch_invalid")
    plan = verify(Path(str(plan_record["path"])), str(plan_record["sha256"]))
    index = shard_record.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_launch_invalid")
    expected_shard = plan["shards"][index]
    run_dir = Path(str(value.get("run_dir", "")))
    if (
        value.get("source_revision") != plan["source_revision"]
        or shard_record
        != {
            "index": index,
            "count": expected_shard["count"],
            "selector": expected_shard["selector"],
            "config": expected_shard["config"],
        }
        or deployment
        != {
            "capacity_profile": CAPACITY_PROFILE,
            "endpoint_identifier": ENDPOINT_IDENTIFIER,
            "endpoint_bundle_sha256": ENDPOINT_BUNDLE_SHA256,
            "source_spec_sha256": SOURCE_SPEC_SHA256,
            "router_implementation_sha256": deployment.get("router_implementation_sha256"),
            "endpoint_jobs_sha256": _capacity_endpoint_jobs_sha256(plan),
            "worker_count": 1,
            "per_worker_capacity": CONCURRENCY,
        }
        or SHA256_RE.fullmatch(str(deployment.get("router_implementation_sha256", ""))) is None
        or execution
        != {
            "requested_concurrency": CONCURRENCY,
            "pool_size": CONCURRENCY,
            "sandbox_environment": "oci-runner-firecracker-small",
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "provisioning_retries": PROVISIONING_RETRIES,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "session_timeout_seconds": SESSION_TIMEOUT_SECONDS,
            "rollout_timeout_seconds": ROLLOUT_TIMEOUT_SECONDS,
            "model_retries": 0,
            "zero_model_resume_attempts": 0,
            "verifier_runtime_retries": 2,
            "verifier_retry_mode": "same-post-agent-runtime-scoring-only",
        }
        or not run_dir.is_absolute()
        or Path(os.path.normpath(run_dir)) != run_dir
        or run_dir.parent != Path(expected_shard["run_root"])
        or re.fullmatch(r"attempt-[1-9][0-9]*", run_dir.name) is None
    ):
        raise StockSmallError("shard_launch_invalid")
    assert isinstance(manifest_record, dict)
    manifest_path, manifest_body, manifest = _validated_worker_manifest(
        Path(str(manifest_record["path"])),
        str(manifest_record["sha256"]),
    )
    if manifest_record != _artifact(manifest_path, manifest_body):
        raise StockSmallError("shard_launch_invalid")
    manifest_router = manifest.get("router")
    if (
        not isinstance(manifest_router, dict)
        or manifest_router.get("implementation_sha256") != deployment.get("router_implementation_sha256")
    ):
        raise StockSmallError("shard_launch_invalid")
    checks = {
        "config": (config_sha256, expected_shard["config"]["sha256"]),
        "selector": (selector_sha256, expected_shard["selector"]["sha256"]),
        "worker_manifest": (worker_manifest_sha256, manifest_record.get("sha256")),
        "source_spec": (source_spec_sha256, SOURCE_SPEC_SHA256),
        "endpoint_bundle": (endpoint_bundle_sha256, ENDPOINT_BUNDLE_SHA256),
        "router_implementation": (router_implementation_sha256, deployment.get("router_implementation_sha256")),
    }
    if any(observed is not None and observed != expected for observed, expected in checks.values()):
        raise StockSmallError("shard_launch_binding_invalid")
    if concurrency is not None and concurrency != CONCURRENCY:
        raise StockSmallError("shard_launch_binding_invalid")
    return value


def _task_slug(trace: Mapping[str, Any]) -> str:
    try:
        return audit_traces._task_slug(trace)
    except Exception as error:
        raise StockSmallError("trace_identity_invalid") from error


def audit_results(results: Path, selector: Path) -> dict[str, Any]:
    selector_body = _read(selector, code="selector_invalid", private=True, maximum_bytes=4 * 1024 * 1024)
    try:
        members = tuple(selector_body.decode("utf-8").splitlines())
    except UnicodeDecodeError as error:
        raise StockSmallError("selector_invalid") from error
    if not members or len(members) > MAX_SHARD_TASKS or len(members) != len(set(members)):
        raise StockSmallError("selector_invalid")
    expected = frozenset(members)
    if (
        not results.is_absolute()
        or Path(os.path.normpath(results)) != results
        or results.resolve(strict=True) != results
    ):
        raise StockSmallError("results_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(results, flags)
    except OSError as error:
        raise StockSmallError("results_invalid") from error
    digest = hashlib.sha256()
    size = 0
    seen_tasks: set[str] = set()
    seen_ids: set[str] = set()
    counts: Counter[str] = Counter()

    def audit_model_bearing_trace(row: dict[str, Any], *, clean_stop: bool) -> tuple[int, int]:
        audited = row
        if row.get("errors"):
            audited = dict(row)
            audited["errors"] = []
        problems = audit_traces._audit_trace(
            audited,
            require_reasoning=True,
            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
            require_model_io=True,
            model_io_contract=audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            require_exact_provider_json=True,
            require_clean_stop=clean_stop,
        )
        if problems:
            raise StockSmallError("model_bearing_trace_invalid")
        turns = 0
        sampled_tokens = 0
        for node in row.get("nodes", []):
            if not isinstance(node, dict) or node.get("sampled") is not True:
                continue
            model_io = node.get("model_io")
            response = model_io.get("response") if isinstance(model_io, dict) else None
            if not isinstance(response, dict) or response.get("kind") != "exact_provider_json":
                raise StockSmallError("model_bearing_trace_response_kind_invalid")
            turns += 1
            usage = audit_traces._usage_tokens(node)
            if usage is not None:
                sampled_tokens += usage[1]
        if turns < 1 or sampled_tokens < 1:
            raise StockSmallError("model_bearing_trace_invalid")
        return turns, sampled_tokens

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600:
            raise StockSmallError("results_invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            while raw := stream.readline(MAX_RESULTS_ROW_BYTES + 1):
                if len(raw) > MAX_RESULTS_ROW_BYTES or not raw.endswith(b"\n") or not raw.strip():
                    raise StockSmallError("results_invalid")
                digest.update(raw)
                size += len(raw)
                row = _json_line(raw, code="results_invalid")
                task = _task_slug(row)
                trace_id = row.get("id")
                if task not in expected or task in seen_tasks or not isinstance(trace_id, str) or not trace_id or trace_id in seen_ids:
                    raise StockSmallError("trace_identity_invalid")
                seen_tasks.add(task)
                seen_ids.add(trace_id)
                errors = row.get("errors")
                if not isinstance(errors, list):
                    raise StockSmallError("trace_errors_invalid")
                counts["traces"] += 1
                if errors:
                    counts["error_traces"] += 1
                    nodes = row.get("nodes")
                    if nodes == []:
                        counts["zero_model_error_traces"] += 1
                        continue
                    turns, sampled_tokens = audit_model_bearing_trace(row, clean_stop=False)
                    counts["model_bearing_error_traces"] += 1
                    counts["audited_model_io_turns"] += turns
                    counts["audited_sampled_tokens"] += sampled_tokens
                    continue
                rewards = row.get("rewards")
                if not isinstance(rewards, dict) or set(rewards) != {"solved"}:
                    raise StockSmallError("trace_reward_invalid")
                reward = rewards["solved"]
                if isinstance(reward, bool) or not isinstance(reward, (int, float)) or reward not in {0, 1}:
                    raise StockSmallError("trace_reward_invalid")
                turns, sampled_tokens = audit_model_bearing_trace(
                    row,
                    clean_stop=True,
                )
                counts["clean_model_io_turns"] += turns
                counts["clean_sampled_tokens"] += sampled_tokens
                counts["audited_model_io_turns"] += turns
                counts["audited_sampled_tokens"] += sampled_tokens
                counts["positive_traces" if float(reward) == 1.0 else "zero_reward_traces"] += 1
        after = os.fstat(descriptor)
        visible = results.lstat()
    finally:
        os.close(descriptor)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    visible_identity = (
        visible.st_dev,
        visible.st_ino,
        visible.st_mode,
        visible.st_uid,
        visible.st_nlink,
        visible.st_size,
        visible.st_mtime_ns,
        visible.st_ctime_ns,
    )
    if (
        before_identity != after_identity
        or after_identity != visible_identity
        or size != before.st_size
        or seen_tasks != expected
        or counts["traces"] != len(expected)
        or counts["error_traces"] + counts["zero_reward_traces"] + counts["positive_traces"] != len(expected)
        or counts["zero_model_error_traces"] + counts["model_bearing_error_traces"]
        != counts["error_traces"]
    ):
        raise StockSmallError("trace_coverage_invalid")
    return {
        "artifact": {"path": str(results.resolve()), "bytes": size, "sha256": digest.hexdigest()},
        **{key: counts[key] for key in (
            "traces",
            "error_traces",
            "zero_model_error_traces",
            "model_bearing_error_traces",
            "zero_reward_traces",
            "positive_traces",
            "clean_model_io_turns",
            "clean_sampled_tokens",
            "audited_model_io_turns",
            "audited_sampled_tokens",
        )},
    }


def _validate_run_evidence(
    *,
    plan: Mapping[str, Any],
    shard: Mapping[str, Any],
    launch: Mapping[str, Any],
    launch_path: Path,
    launch_sha256: str,
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    shard_root = Path(str(shard["run_root"]))
    try:
        canonical_run = run_dir.resolve(strict=True)
        canonical_shard_root = shard_root.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("run_directory_invalid") from error
    if (
        canonical_run.parent != canonical_shard_root
        or re.fullmatch(r"attempt-[1-9][0-9]*", canonical_run.name) is None
        or launch.get("run_dir") != str(canonical_run)
    ):
        raise StockSmallError("run_directory_invalid")

    try:
        evidence = split._open_held_run_evidence(canonical_run)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("run_evidence_invalid") from error
    held = split._HeldArtifactSet.create()
    try:
        with ExitStack() as stack:
            stack.callback(evidence.close)
            stack.callback(held.close)
            writer_lock = stack.enter_context(
                split._open_private_writer_lock_at(evidence.directory, ".writer.lock")
            )
            try:
                fcntl.flock(writer_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StockSmallError("writer_active") from error

            trace = audit_results(canonical_run / "results.jsonl", Path(str(shard["selector"]["path"])))
            if trace["zero_model_error_traces"] != 0:
                raise StockSmallError("incomplete_trace_set")

            try:
                from eval_run_identity import load_eval_run_identity_bytes

                identity_envelope = load_eval_run_identity_bytes(
                    evidence.files["eval_run_identity.json"].body,
                    run_dir=canonical_run,
                    verify_references=True,
                    verify_saved_provenance=False,
                )
                identity = identity_envelope["identity"]
                identity_sha256 = identity_envelope["eval_run_identity_sha256"]
                invocation_sha256, slurm_job_id = split._run_invocation_binding(
                    evidence.files["eval_invocations.jsonl"].body,
                    evidence.files["provenance.txt"].body,
                    identity_sha256,
                    expected_role="kimi-direct-mobius",
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise StockSmallError("identity_invalid") from error

            identity_deployment = identity.get("deployment")
            router = identity_deployment.get("router") if isinstance(identity_deployment, dict) else None
            environment = identity.get("execution", {}).get("sandoq_environment")
            inputs = identity.get("inputs")
            promotion = identity_deployment.get("promotion_certificate") if isinstance(identity_deployment, dict) else None
            if (
                identity.get("role") != "kimi-direct-mobius"
                or identity.get("source", {}).get("prime_rl_commit") != plan["source_revision"]
                or not isinstance(inputs, dict)
                or inputs.get("task_file", {}).get("sha256") != shard["selector"]["sha256"]
                or inputs.get("task_file", {}).get("count") != shard["count"]
                or identity.get("config", {}).get("source", {}).get("sha256") != shard["config"]["sha256"]
                or not isinstance(router, dict)
                or router.get("capacity_profile") != CAPACITY_PROFILE
                or router.get("endpoint_identifier") != ENDPOINT_IDENTIFIER
                or router.get("worker_count") != 1
                or router.get("provider_concurrency") != CONCURRENCY
                or router.get("retries") != 0
                or identity_deployment.get("spec_sha256") != SOURCE_SPEC_SHA256
                or identity_deployment.get("endpoint_bundle_sha256") != ENDPOINT_BUNDLE_SHA256
                or not isinstance(environment, dict)
                or environment.get("environment") != "oci-runner-firecracker-small"
                or environment.get("pool_size") != CONCURRENCY
                or not isinstance(promotion, dict)
                or promotion
                != {
                    "path": str(launch_path.resolve(strict=True)),
                    "sha256": launch_sha256,
                }
            ):
                raise StockSmallError("identity_invalid")

            capacity_record = plan.get("source", {}).get("stock_model_c64")
            walltime_record = identity_deployment.get("endpoint_walltime_gate")
            if not isinstance(capacity_record, dict) or not isinstance(walltime_record, dict):
                raise StockSmallError("endpoint_epoch_invalid")
            capacity_body = _read(
                Path(str(capacity_record.get("path", ""))),
                code="endpoint_epoch_invalid",
                private=True,
                held=held,
            )
            walltime_body = _read(
                Path(str(walltime_record.get("path", ""))),
                code="endpoint_epoch_invalid",
                private=True,
                held=held,
            )
            if (
                capacity_record != _artifact(Path(str(capacity_record.get("path", ""))), capacity_body)
                or walltime_record != _artifact(Path(str(walltime_record.get("path", ""))), walltime_body)
            ):
                raise StockSmallError("endpoint_epoch_invalid")
            capacity_value = _json(capacity_body, code="endpoint_epoch_invalid")
            walltime_value = _json(walltime_body, code="endpoint_epoch_invalid")
            endpoint_job_id = capacity_value.get("deployment", {}).get("endpoint_job_id")
            if (
                not isinstance(endpoint_job_id, str)
                or re.fullmatch(r"[1-9][0-9]*", endpoint_job_id) is None
                or walltime_value.get("endpoint_jobs_sha256")
                != _sha256(f"{endpoint_job_id}\n".encode())
            ):
                raise StockSmallError("endpoint_epoch_invalid")

            try:
                cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
                    canonical_run / "sandoq_cleanup_audit.json",
                    canonical_run,
                    identity,
                    identity_sha256,
                    invocation_sha256,
                    slurm_job_id,
                    int(shard["count"]),
                    int(shard["count"]),
                    held,
                    expected_pool_size=CONCURRENCY,
                )
                router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
                    canonical_run / "direct_kimi_router_final.json",
                    identity,
                    minimum_chat_requests=trace["audited_model_io_turns"],
                    identity_sha256=identity_sha256,
                    invocation_identity_sha256=invocation_sha256,
                    held=held,
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise StockSmallError("run_evidence_invalid") from error
            router_receipt = _json(router_body, code="router_receipt_invalid")
            if (
                cleanup.get("assignment_measured_high_water") != int(shard["count"])
                or router_receipt.get("chat_requests") != trace["audited_model_io_turns"]
                or router_receipt.get("worker_queue_timeouts") != 0
                or router_receipt.get("upstream_http_429") != 0
                or router_receipt.get("upstream_http_5xx") != 0
            ):
                raise StockSmallError("run_evidence_invalid")

            artifacts = {
                "results": trace.pop("artifact"),
                "eval_run_identity": evidence.artifact("eval_run_identity.json"),
                "eval_invocations": evidence.artifact("eval_invocations.jsonl"),
                "provenance": evidence.artifact("provenance.txt"),
                "endpoint_walltime_gate": _artifact(
                    Path(str(walltime_record["path"])),
                    walltime_body,
                ),
                "router_receipt": router_artifact,
                "router_receipt_commit": router_marker,
                **cleanup_artifacts,
            }
            evidence.revalidate()
            held.revalidate()
            return trace, artifacts
    except StockSmallError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("run_evidence_invalid") from error


def _validate_completion_value(
    value: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    plan_sha256: str,
    shard: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != COMPLETION_KIND
        or value.get("state") != "passed"
        or value.get("plan") != {"path": str(plan_path), "sha256": plan_sha256}
        or not isinstance(value.get("launch"), dict)
        or set(value["launch"]) != {"path", "sha256"}
        or SHA256_RE.fullmatch(str(value["launch"].get("sha256", ""))) is None
        or value.get("shard")
        != {"index": shard["index"], "count": shard["count"], "selector_sha256": shard["selector"]["sha256"]}
        or value.get("capture")
        != {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        }
        or value.get("deployment", {}).get("capacity_profile") != CAPACITY_PROFILE
        or value.get("deployment", {}).get("endpoint_identifier") != ENDPOINT_IDENTIFIER
        or value.get("deployment", {}).get("endpoint_bundle_sha256") != ENDPOINT_BUNDLE_SHA256
        or value.get("sandbox", {}).get("environment") != "oci-runner-firecracker-small"
        or value.get("sandbox", {}).get("capacity") != CONCURRENCY
    ):
        raise StockSmallError("completion_invalid")
    launch_record = value["launch"]
    launch = validate_launch(Path(launch_record["path"]), launch_record["sha256"])
    if (
        launch.get("plan") != {"path": str(plan_path), "sha256": plan_sha256}
        or launch.get("shard", {}).get("index") != shard["index"]
    ):
        raise StockSmallError("completion_invalid")
    trace = value.get("trace")
    outcome_counts = ()
    if isinstance(trace, dict):
        outcome_counts = tuple(
            trace.get(key)
            for key in (
                "error_traces",
                "zero_model_error_traces",
                "model_bearing_error_traces",
                "zero_reward_traces",
                "positive_traces",
            )
        )
    if (
        not isinstance(trace, dict)
        or trace.get("traces") != shard["count"]
        or not all(map(_plain_nonnegative_integer, outcome_counts))
        or trace.get("zero_model_error_traces") != 0
        or trace.get("error_traces") != trace.get("model_bearing_error_traces")
        or trace.get("error_traces", -1) + trace.get("zero_reward_traces", -1) + trace.get("positive_traces", -1)
        != shard["count"]
        or value.get("training")
        != {
            "trainable_traces": trace.get("zero_reward_traces", -1)
            + trace.get("positive_traces", -1),
            "non_trainable_traces": trace.get("model_bearing_error_traces", -1),
            "model_bearing_errors_retained": True,
        }
    ):
        raise StockSmallError("completion_invalid")
    observed_trace, observed_artifacts = _validate_run_evidence(
        plan=plan,
        shard=shard,
        launch=launch,
        launch_path=Path(str(launch_record["path"])),
        launch_sha256=str(launch_record["sha256"]),
        run_dir=Path(str(launch["run_dir"])),
    )
    if observed_trace != trace or value.get("artifacts") != observed_artifacts:
        raise StockSmallError("completion_trace_invalid")
    return dict(value)


def _load_completion_for_plan(
    plan: Mapping[str, Any],
    plan_path: Path,
    plan_sha256: str,
    index: int,
) -> dict[str, Any]:
    if not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_index_invalid")
    shard = plan["shards"][index]
    path = Path(shard["run_root"]) / "complete.json"
    body = _read(path, code="completion_invalid", private=True)
    return _validate_completion_value(
        _json(body, code="completion_invalid"),
        plan=plan,
        plan_path=plan_path.resolve(strict=True),
        plan_sha256=plan_sha256,
        shard=shard,
    )


def load_completion(plan_path: Path, plan_sha256: str, index: int) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    return _load_completion_for_plan(plan, plan_path, plan_sha256, index)


def certify_shard(
    *,
    plan_path: Path,
    plan_sha256: str,
    launch_path: Path,
    launch_sha256: str,
    index: int,
    run_dir: Path,
) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    if not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_index_invalid")
    shard = plan["shards"][index]
    launch = validate_launch(launch_path, launch_sha256)
    if (
        launch.get("plan") != {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256}
        or launch.get("shard", {}).get("index") != index
        or launch.get("run_dir") != str(run_dir)
    ):
        raise StockSmallError("shard_launch_binding_invalid")
    trace, artifacts = _validate_run_evidence(
        plan=plan,
        shard=shard,
        launch=launch,
        launch_path=launch_path,
        launch_sha256=launch_sha256,
        run_dir=run_dir,
    )
    shard_root = Path(shard["run_root"])
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": COMPLETION_KIND,
        "state": "passed",
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "launch": {"path": str(launch_path.resolve(strict=True)), "sha256": launch_sha256},
        "shard": {"index": index, "count": shard["count"], "selector_sha256": shard["selector"]["sha256"]},
        "trace": trace,
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        },
        "deployment": {
            "capacity_profile": CAPACITY_PROFILE,
            "endpoint_identifier": ENDPOINT_IDENTIFIER,
            "endpoint_bundle_sha256": ENDPOINT_BUNDLE_SHA256,
        },
        "sandbox": {"environment": "oci-runner-firecracker-small", "capacity": CONCURRENCY},
        "training": {
            "trainable_traces": trace["zero_reward_traces"] + trace["positive_traces"],
            "non_trainable_traces": trace["model_bearing_error_traces"],
            "model_bearing_errors_retained": True,
        },
        "artifacts": artifacts,
    }
    completion = shard_root / "complete.json"
    try:
        legacy._publish_bundle(shard_root, {completion: _canonical(value)})
    except Exception as error:
        raise StockSmallError("completion_publication_failed") from error
    return {"state": "passed", "shard": index, **trace}


def status(plan_path: Path, plan_sha256: str) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    complete: list[int] = []
    pending: list[int] = []
    counts: Counter[str] = Counter()
    for shard in plan["shards"]:
        index = shard["index"]
        completion = Path(shard["run_root"]) / "complete.json"
        if not completion.exists():
            pending.append(index)
            continue
        value = _load_completion_for_plan(plan, plan_path, plan_sha256, index)
        complete.append(index)
        counts["completed_tasks"] += shard["count"]
        for key in (
            "positive_traces",
            "zero_reward_traces",
            "error_traces",
            "zero_model_error_traces",
            "model_bearing_error_traces",
        ):
            counts[key] += value["trace"][key]
    return {
        "state": "complete" if not pending else "incomplete",
        "completed_shards": len(complete),
        "pending_shards": len(pending),
        "completed_tasks": counts["completed_tasks"],
        "positive_traces": counts["positive_traces"],
        "zero_reward_traces": counts["zero_reward_traces"],
        "error_traces": counts["error_traces"],
        "zero_model_error_traces": counts["zero_model_error_traces"],
        "model_bearing_error_traces": counts["model_bearing_error_traces"],
        "pending_indexes": pending,
    }


def finalize(plan_path: Path, plan_sha256: str, output: Path) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    completions = []
    counts: Counter[str] = Counter()
    for shard in plan["shards"]:
        path = Path(shard["run_root"]) / "complete.json"
        body = _read(path, code="completion_invalid", private=True)
        completion = _validate_completion_value(
            _json(body, code="completion_invalid"),
            plan=plan,
            plan_path=plan_path.resolve(strict=True),
            plan_sha256=plan_sha256,
            shard=shard,
        )
        counts["completed_tasks"] += shard["count"]
        for key in (
            "positive_traces",
            "zero_reward_traces",
            "error_traces",
            "zero_model_error_traces",
            "model_bearing_error_traces",
        ):
            counts[key] += completion["trace"][key]
        completions.append(_artifact(path, body))
    if (
        counts["completed_tasks"] != TOTAL_TASKS
        or counts["zero_model_error_traces"] != 0
        or counts["error_traces"] != counts["model_bearing_error_traces"]
    ):
        raise StockSmallError("production_incomplete")
    summary = {
        "state": "complete",
        "completed_shards": SHARD_COUNT,
        "pending_shards": 0,
        "completed_tasks": counts["completed_tasks"],
        "positive_traces": counts["positive_traces"],
        "zero_reward_traces": counts["zero_reward_traces"],
        "error_traces": counts["error_traces"],
        "zero_model_error_traces": counts["zero_model_error_traces"],
        "model_bearing_error_traces": counts["model_bearing_error_traces"],
        "pending_indexes": [],
    }
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": FINAL_KIND,
        "state": "passed",
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "coverage": {
            "expected_tasks": TOTAL_TASKS,
            "observed_tasks": summary["completed_tasks"],
            "shards": SHARD_COUNT,
            "disjoint": True,
            "exhaustive": True,
        },
        "outcomes": {
            key: summary[key]
            for key in (
                "positive_traces",
                "zero_reward_traces",
                "error_traces",
                "zero_model_error_traces",
                "model_bearing_error_traces",
            )
        },
        "training": {
            "trainable_traces": summary["positive_traces"] + summary["zero_reward_traces"],
            "non_trainable_traces": summary["model_bearing_error_traces"],
            "model_bearing_errors_retained": True,
        },
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        },
        "completion_receipts": completions,
    }
    value["certificate_sha256"] = _sha256(_canonical(value))
    split._publish_private_bundle(output, {"certificate.json": _canonical(value)})
    return {"state": "passed", **summary, "certificate_sha256": value["certificate_sha256"]}


class StableParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise StockSmallError("arguments_invalid")


def _parser() -> StableParser:
    parser = StableParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("materialize")
    make.add_argument("--project-root", type=Path, required=True)
    make.add_argument("--expected-revision", required=True)
    make.add_argument("--source", type=Path, required=True)
    make.add_argument("--dataset", type=Path, required=True)
    make.add_argument("--image-manifest", type=Path, required=True)
    make.add_argument("--tb4-certificate", type=Path, required=True)
    make.add_argument("--tb4-certificate-sha256", required=True)
    make.add_argument("--task-image-soak-receipt", type=Path, required=True)
    make.add_argument("--task-image-soak-receipt-sha256", required=True)
    make.add_argument("--stock-capacity", type=Path, default=STOCK_CAPACITY)
    make.add_argument("--stock-capacity-sha256", default=STOCK_CAPACITY_SHA256)
    make.add_argument("--sandoq-capacity", type=Path, default=SANDOQ_CAPACITY)
    make.add_argument("--sandoq-capacity-sha256", default=SANDOQ_CAPACITY_SHA256)
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--run-root", type=Path, required=True)
    for name in ("verify", "shard", "status", "finalize"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--plan-sha256", required=True)
        if name in {"shard"}:
            command.add_argument("--index", type=int, required=True)
            command.add_argument("--format", choices=("json", "tsv"), default="json")
        if name == "finalize":
            command.add_argument("--output", type=Path, required=True)
    certify = commands.add_parser("certify-shard")
    certify.add_argument("--plan", type=Path, required=True)
    certify.add_argument("--plan-sha256", required=True)
    certify.add_argument("--index", type=int, required=True)
    certify.add_argument("--run-dir", type=Path, required=True)
    certify.add_argument("--launch", type=Path, required=True)
    certify.add_argument("--launch-sha256", required=True)
    launch = commands.add_parser("create-launch")
    launch.add_argument("--plan", type=Path, required=True)
    launch.add_argument("--plan-sha256", required=True)
    launch.add_argument("--index", type=int, required=True)
    launch.add_argument("--worker-manifest", type=Path, required=True)
    launch.add_argument("--worker-manifest-sha256", required=True)
    launch.add_argument("--run-dir", type=Path, required=True)
    launch.add_argument("--output", type=Path, required=True)
    validate_launch_parser = commands.add_parser("validate-launch")
    validate_launch_parser.add_argument("--launch", type=Path, required=True)
    validate_launch_parser.add_argument("--launch-sha256", required=True)
    validate_completion_parser = commands.add_parser("validate-completion")
    validate_completion_parser.add_argument("--plan", type=Path, required=True)
    validate_completion_parser.add_argument("--plan-sha256", required=True)
    validate_completion_parser.add_argument("--index", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "materialize":
            result = materialize(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                source=args.source,
                dataset=args.dataset,
                image_manifest=args.image_manifest,
                tb4_certificate=args.tb4_certificate,
                tb4_certificate_sha256=args.tb4_certificate_sha256,
                task_image_soak_receipt=args.task_image_soak_receipt,
                task_image_soak_receipt_sha256=args.task_image_soak_receipt_sha256,
                output=args.output,
                run_root=args.run_root,
                stock_capacity=args.stock_capacity,
                stock_capacity_sha256=args.stock_capacity_sha256,
                sandoq_capacity=args.sandoq_capacity,
                sandoq_capacity_sha256=args.sandoq_capacity_sha256,
            )
        elif args.command == "verify":
            plan = verify(args.plan, args.plan_sha256)
            result = {"state": "authorized", "selected_tasks": TOTAL_TASKS, "shards": len(plan["shards"])}
        elif args.command == "shard":
            result = shard_binding(args.plan, args.plan_sha256, args.index)
        elif args.command == "status":
            result = status(args.plan, args.plan_sha256)
        elif args.command == "certify-shard":
            result = certify_shard(
                plan_path=args.plan,
                plan_sha256=args.plan_sha256,
                launch_path=args.launch,
                launch_sha256=args.launch_sha256,
                index=args.index,
                run_dir=args.run_dir,
            )
        elif args.command == "create-launch":
            result = create_launch(
                plan_path=args.plan,
                plan_sha256=args.plan_sha256,
                index=args.index,
                worker_manifest=args.worker_manifest,
                worker_manifest_sha256=args.worker_manifest_sha256,
                run_dir=args.run_dir,
                output=args.output,
            )
        elif args.command == "validate-launch":
            value = validate_launch(args.launch, args.launch_sha256)
            result = {
                "state": "authorized",
                "shard": value["shard"]["index"],
                "count": value["shard"]["count"],
            }
        elif args.command == "validate-completion":
            value = load_completion(args.plan, args.plan_sha256, args.index)
            result = {"state": "passed", "shard": args.index, "count": value["shard"]["count"]}
        else:
            result = finalize(args.plan, args.plan_sha256, args.output)
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_stock_small_shards_failed","state":"blocked"}', file=sys.stderr)
        return 2
    if args.command == "shard" and args.format == "tsv":
        print(
            "\t".join(
                str(result[key])
                for key in (
                    "source_revision",
                    "index",
                    "count",
                    "selector",
                    "selector_sha256",
                    "config",
                    "config_sha256",
                    "run_root",
                )
            )
        )
    else:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
