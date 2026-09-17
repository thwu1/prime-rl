#!/usr/bin/env python3
"""Fail-closed checkpoint for a 66-task CPU-only Terminal-Bench 4 eval."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from audit_traces import (
    DEFAULT_MAX_SEQUENCE_TOKENS,
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    TraceJSONLError,
    _audit_trace,
    _iter_traces,
    _task_slug,
)
from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    revalidate_deployment_proxy_policy,
    validate_proxy_policy_binding,
)
from eval_run_identity import EvalIdentityError, canonical_json, load_eval_run_identity
from guard_success_receipt import (
    GuardReceiptError,
    load_guard_success_receipt,
    validate_guard_success_linkage,
)
from inference_route_generation import (
    RouteGenerationError,
    validate_readiness_route_generation,
    validate_route_generation,
)
from smoke_qualification import (
    SmokeQualificationError,
    validate_smoke_qualification,
)

EXPECTED_TASK_COUNT = 66
EXPECTED_SUPPORTED_TASK_COUNT = 63
EXPECTED_MODEL = "Kimi-K3"
EXPECTED_TB4_ROLLOUT_CONCURRENCY = 4
EXPECTED_TB4_LEASE_START_CONCURRENCY = 2
SUPPORTED_TB4_ROLLOUT_CONCURRENCIES = frozenset({4, 24})
EXPECTED_ROUTES_BY_ROLLOUT_CONCURRENCY = {4: 1, 24: 24}
EXPECTED_MIN_SUPPORTED_PASS_RATE = 0.04
EXPECTED_MAX_SUPPORTED_PASS_RATE = 0.22
EXPECTED_OUTBOUND_BODY_DENYLIST = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": KIMI_K3_MAX_MODEL_IO_CONTRACT.provider_route,
    "request_model": KIMI_K3_MAX_MODEL_IO_CONTRACT.request_model,
    "response_model": KIMI_K3_MAX_MODEL_IO_CONTRACT.response_model,
    "request_reasoning_effort": KIMI_K3_MAX_MODEL_IO_CONTRACT.reasoning_effort,
    "request_chat_template_kwargs": dict(KIMI_K3_MAX_MODEL_IO_CONTRACT.chat_template_kwargs),
}
EXPECTED_UNSUPPORTED_TASKS = frozenset(
    {
        "fp8-rmsnorm-gemm",
        "jax-speedrun-gpu",
        "math-eval-grader",
    }
)


class TB4AuditError(ValueError):
    """The expected TB4 input set could not be established safely."""


def _sha256_file(path: Path, *, label: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise TB4AuditError(f"{label}_unreadable") from error
    return digest.hexdigest()


def _resolved_file(path: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise TB4AuditError(f"{label}_unreadable") from error
    if not resolved.is_file():
        raise TB4AuditError(f"{label}_unreadable")
    return resolved


def _identity_artifact(record: object, *, label: str) -> tuple[Path, str]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise TB4AuditError(f"{label}_identity_invalid")
    path = _resolved_file(Path(str(record["path"])), label=label)
    digest = record["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise TB4AuditError(f"{label}_identity_invalid")
    if _sha256_file(path, label=label) != digest:
        raise TB4AuditError(f"{label}_sha256_mismatch")
    return path, digest


def _require_run_local(path: Path, expected: Path, *, label: str) -> None:
    if path != _resolved_file(expected, label=label):
        raise TB4AuditError(f"{label}_path_mismatch")


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TB4AuditError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise TB4AuditError(f"{label}_invalid")
    return value


@contextmanager
def _hold_writer_lock(run_dir: Path) -> Iterator[None]:
    lock_path = run_dir / ".writer.lock"
    if lock_path.is_symlink():
        raise TB4AuditError("writer_lock_invalid")
    try:
        handle = lock_path.open("rb")
    except OSError as error:
        raise TB4AuditError("writer_lock_unreadable") from error
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TB4AuditError("writer_lock_busy") from error
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read_task_file(path: Path) -> list[str]:
    slugs = [
        line.strip().split("\t", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(slugs) != len(set(slugs)):
        raise TB4AuditError(f"{path}: duplicate task slugs")
    return slugs


def _expected_slugs(dataset_dir: Path, task_file: Path | None = None) -> set[str]:
    if not dataset_dir.is_dir():
        raise TB4AuditError(f"{dataset_dir}: dataset directory does not exist")
    dataset_slugs = {
        path.name
        for path in dataset_dir.iterdir()
        if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
    }
    if task_file is None:
        expected = dataset_slugs
    else:
        requested = set(_read_task_file(task_file))
        if missing := sorted(requested - dataset_slugs):
            raise TB4AuditError(f"{task_file}: tasks missing from dataset: {missing[:20]!r} count={len(missing)}")
        expected = requested
    if len(expected) != EXPECTED_TASK_COUNT:
        raise TB4AuditError(f"expected exactly {EXPECTED_TASK_COUNT} TB4 tasks, found {len(expected)}")
    if missing := sorted(EXPECTED_UNSUPPORTED_TASKS - expected):
        raise TB4AuditError(f"expected GPU-unsupported tasks are absent: {missing!r}")
    return expected


def _unsupported_trace_problems(trace: dict, slug: str) -> list[str]:
    problems: list[str] = []
    task = trace.get("task")
    expected_name = f"terminal-bench/{slug}"
    if not isinstance(task, dict) or task.get("name") != expected_name:
        problems.append("unsupported_task_name_invalid")
    resources = task.get("resources") if isinstance(task, dict) else None
    if not isinstance(resources, dict) or resources.get("gpu") != "1":
        problems.append("unsupported_task_gpu_resource_missing")
    if trace.get("is_completed") is not True:
        problems.append("unsupported_trace_not_completed")
    if trace.get("stop_condition") != "error":
        problems.append("unsupported_trace_stop_condition_invalid")
    if trace.get("nodes") != []:
        problems.append("unsupported_trace_nodes_not_empty")
    if trace.get("rewards") != {}:
        problems.append("unsupported_trace_rewards_not_empty")
    if trace.get("metrics") != {}:
        problems.append("unsupported_trace_metrics_not_empty")

    errors = trace.get("errors")
    expected_message = (
        f"taskset setup: UnsupportedTaskError: {expected_name}: "
        "requests GPU resources, but the current VMVM tenant is CPU-only"
    )
    if not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict):
        problems.append("unsupported_trace_error_shape_invalid")
        return problems
    error = errors[0]
    if set(error) != {"type", "message", "traceback"}:
        problems.append("unsupported_trace_error_shape_invalid")
    if error.get("type") != "TasksetError":
        problems.append("unsupported_trace_error_type_invalid")
    if error.get("message") != expected_message:
        problems.append("unsupported_trace_error_message_invalid")
    traceback = error.get("traceback")
    if not isinstance(traceback, str) or expected_message not in traceback:
        problems.append("unsupported_trace_traceback_invalid")
    return problems


def _score_problem(trace: dict) -> tuple[float | None, str | None]:
    rewards = trace.get("rewards")
    if not isinstance(rewards, dict) or set(rewards) != {"solved"}:
        return None, "rewards_solved_missing_or_extra"
    score = rewards["solved"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or score not in {0, 1}
    ):
        return None, "rewards_solved_not_binary"
    return float(score), None


def audit_results(
    results: Path,
    *,
    dataset_dir: Path,
    task_file: Path | None = None,
    min_supported_pass_rate: float | None = None,
    max_supported_pass_rate: float | None = None,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
) -> tuple[dict, bool]:
    expected = _expected_slugs(dataset_dir, task_file)
    supported = expected - EXPECTED_UNSUPPORTED_TASKS
    rows = list(_iter_traces(results))
    per_task = Counter(_task_slug(row) for row in rows)
    trace_ids = [row.get("id") for row in rows]
    global_problems: list[str] = []
    failure_examples: list[dict] = []

    if len(rows) != EXPECTED_TASK_COUNT:
        global_problems.append(f"trace_count={len(rows)} expected={EXPECTED_TASK_COUNT}")
    invalid_ids = sum(not isinstance(trace_id, str) or not trace_id for trace_id in trace_ids)
    if invalid_ids:
        global_problems.append(f"invalid_trace_ids={invalid_ids}")
    valid_ids = [trace_id for trace_id in trace_ids if isinstance(trace_id, str) and trace_id]
    if len(valid_ids) != len(set(valid_ids)):
        global_problems.append("duplicate_trace_ids")
    if missing := sorted(expected - set(per_task)):
        global_problems.append(f"missing_tasks={missing[:20]!r} count={len(missing)}")
    if extra := sorted(set(per_task) - expected):
        global_problems.append(f"unexpected_tasks={extra[:20]!r} count={len(extra)}")
    if wrong := {slug: per_task.get(slug, 0) for slug in expected if per_task.get(slug, 0) != 1}:
        global_problems.append(f"wrong_rollout_multiplicity={dict(sorted(wrong.items()))!r}")

    supported_scores: list[float] = []
    unsupported_seen: set[str] = set()
    supported_failures = 0
    unsupported_failures = 0
    for row in rows:
        slug = _task_slug(row)
        problems: list[str]
        if slug in EXPECTED_UNSUPPORTED_TASKS:
            unsupported_seen.add(slug)
            problems = _unsupported_trace_problems(row, slug)
            if problems:
                unsupported_failures += 1
        else:
            problems = _audit_trace(
                row,
                require_reasoning=True,
                max_sequence_tokens=max_sequence_tokens,
                require_token_data=False,
                require_logprobs=False,
                require_model_io=True,
                model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
            )
            if row.get("is_completed") is not True:
                problems.append("supported_trace_not_completed")
            stop_condition = row.get("stop_condition")
            if not isinstance(stop_condition, str) or not stop_condition.strip() or stop_condition == "error":
                problems.append("supported_trace_stop_condition_invalid")
            score, score_problem = _score_problem(row)
            if score_problem is not None:
                problems.append(score_problem)
            elif slug in supported:
                supported_scores.append(score)
            if problems:
                supported_failures += 1
        if problems and len(failure_examples) < 50:
            failure_examples.append({"id": row.get("id"), "task": slug, "problems": problems})

    supported_passes = int(sum(supported_scores))
    supported_pass_rate = supported_passes / len(supported) if supported else 0.0
    all_task_pass_rate = supported_passes / EXPECTED_TASK_COUNT
    if len(supported_scores) != len(supported):
        global_problems.append(f"scored_supported_tasks={len(supported_scores)} expected={len(supported)}")
    if unsupported_seen != EXPECTED_UNSUPPORTED_TASKS:
        missing = sorted(EXPECTED_UNSUPPORTED_TASKS - unsupported_seen)
        global_problems.append(f"missing_expected_unsupported_tasks={missing!r}")
    if min_supported_pass_rate is not None and supported_pass_rate < min_supported_pass_rate:
        global_problems.append(
            f"supported_pass_rate={supported_pass_rate:.12g} below_min={min_supported_pass_rate:.12g}"
        )
    if max_supported_pass_rate is not None and supported_pass_rate > max_supported_pass_rate:
        global_problems.append(
            f"supported_pass_rate={supported_pass_rate:.12g} above_max={max_supported_pass_rate:.12g}"
        )

    summary = {
        "schema_version": 1,
        "ok": not (global_problems or failure_examples),
        "expected_tasks": EXPECTED_TASK_COUNT,
        "observed_traces": len(rows),
        "supported_tasks": len(supported),
        "expected_unsupported_tasks": sorted(EXPECTED_UNSUPPORTED_TASKS),
        "observed_unsupported_tasks": sorted(unsupported_seen),
        "trace_failures": supported_failures + unsupported_failures,
        "supported_trace_failures": supported_failures,
        "unsupported_trace_failures": unsupported_failures,
        "supported_passes": supported_passes,
        "supported_pass_rate": supported_pass_rate,
        "all_task_pass_rate": all_task_pass_rate,
        "score_bounds": {
            "min_supported_pass_rate": min_supported_pass_rate,
            "max_supported_pass_rate": max_supported_pass_rate,
        },
        "global_problems": global_problems,
        "failure_examples": failure_examples,
    }
    return summary, not summary["ok"]


def _validate_tb4_identity(
    envelope: dict[str, Any],
    *,
    expected_rollout_concurrency: int,
    expected_lease_start_concurrency: int,
) -> dict[str, Any]:
    identity = envelope.get("identity")
    if not isinstance(identity, dict) or identity.get("role") != "tb4":
        raise TB4AuditError("tb4_eval_identity_required")
    digest = envelope.get("eval_run_identity_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise TB4AuditError("eval_run_identity_digest_invalid")

    inputs = identity.get("inputs")
    contract = identity.get("contract")
    execution = identity.get("execution")
    if not all(isinstance(value, dict) for value in (inputs, contract, execution)):
        raise TB4AuditError("eval_run_identity_contract_invalid")
    assert isinstance(inputs, dict) and isinstance(contract, dict) and isinstance(execution, dict)
    task_file = inputs.get("task_file")
    if not isinstance(task_file, dict) or task_file.get("count") != EXPECTED_TASK_COUNT:
        raise TB4AuditError("tb4_approved_task_count_invalid")
    thinking = contract.get("thinking")
    context = contract.get("context_tokens")
    denylist = contract.get("outbound_body_denylist")
    sampling_max_tokens = contract.get("sampling_max_tokens")
    if (
        contract.get("model") != EXPECTED_MODEL
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "max"
        or canonical_json(thinking) != canonical_json({"enable_thinking": True, "preserve_thinking": True})
        or not isinstance(context, dict)
        or set(context) != {"max_input_tokens", "max_output_tokens", "max_total_tokens"}
        or any(value != DEFAULT_MAX_SEQUENCE_TOKENS for value in context.values())
        or contract.get("capture_model_io") is not True
        or contract.get("retain_traces") is not False
        or not isinstance(denylist, list)
        or len(denylist) != len(EXPECTED_OUTBOUND_BODY_DENYLIST)
        or set(denylist) != EXPECTED_OUTBOUND_BODY_DENYLIST
        or not isinstance(sampling_max_tokens, int)
        or isinstance(sampling_max_tokens, bool)
        or not 0 < sampling_max_tokens <= DEFAULT_MAX_SEQUENCE_TOKENS
    ):
        raise TB4AuditError("eval_run_identity_contract_invalid")
    vmvm_environment = execution.get("vmvm_environment")
    if (
        execution.get("rollout_concurrency") != expected_rollout_concurrency
        or execution.get("multiplex") != expected_rollout_concurrency
        or execution.get("http_max_connections") != expected_rollout_concurrency
        or execution.get("http_max_keepalive_connections") != expected_rollout_concurrency
        or not isinstance(vmvm_environment, dict)
        or vmvm_environment.get("lease_start_concurrency") != expected_lease_start_concurrency
    ):
        raise TB4AuditError("tb4_concurrency_contract_invalid")
    return identity


def _validated_endpoint(identity: dict[str, Any]) -> dict[str, Any]:
    deployment = identity.get("deployment")
    contract = identity.get("contract")
    if not isinstance(deployment, dict) or not isinstance(contract, dict):
        raise TB4AuditError("eval_run_identity_endpoint_invalid")
    try:
        endpoint = validate_endpoint_binding(deployment.get("endpoint"))
        observed = load_deployment_endpoint(
            Path(endpoint["proxy_info"]["path"]),
            deployment_id=deployment["id"],
            expected_model=contract["model"],
            deployment_spec=Path(deployment["spec"]["path"]),
            expected_proxy_info_sha256=endpoint["proxy_info"]["sha256"],
        )
    except (EndpointBindingError, KeyError, TypeError) as error:
        raise TB4AuditError("eval_run_identity_endpoint_invalid") from error
    if observed.binding != endpoint:
        raise TB4AuditError("eval_run_identity_endpoint_mismatch")
    return endpoint


def _validate_provenance(
    path: Path,
    *,
    identity: dict[str, Any],
    identity_sha256: str,
) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TB4AuditError("provenance_unreadable") from error
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in records:
            raise TB4AuditError("provenance_invalid")
        records[key] = value

    source = identity.get("source")
    deployment = identity.get("deployment")
    inputs = identity.get("inputs")
    if not all(isinstance(value, dict) for value in (source, deployment, inputs)):
        raise TB4AuditError("eval_run_identity_schema_invalid")
    assert isinstance(source, dict) and isinstance(deployment, dict) and isinstance(inputs, dict)
    task_file = inputs.get("task_file")
    if not isinstance(task_file, dict):
        raise TB4AuditError("eval_run_identity_schema_invalid")
    stable = {
        "prime_rl": source.get("prime_rl_commit"),
        "prime_rl_tree": source.get("prime_rl_tree_sha256"),
        "verifiers": source.get("verifiers_commit"),
        "verifiers_tree": source.get("verifiers_tree_sha256"),
        "renderers": source.get("renderers_commit"),
        "renderers_tree": source.get("renderers_tree_sha256"),
        "vmvm_tb_v2": source.get("vmvm_tb_v2_sha256"),
        "deployment_id": deployment.get("id"),
        "deployment_endpoint_authority_sha256": deployment.get("endpoint", {}).get("authority_sha256"),
        "deployment_proxy_info_sha256": deployment.get("endpoint", {}).get("proxy_info", {}).get("sha256"),
        "eval_run_role": "tb4",
        "eval_run_identity_sha256": identity_sha256,
        "approval_task_file_sha256": task_file.get("sha256"),
        "approval_task_count": str(EXPECTED_TASK_COUNT),
    }
    expected_keys = {*stable, "host", "slurm_job_id"}
    if (
        set(records) != expected_keys
        or any(not isinstance(value, str) or records.get(key) != value for key, value in stable.items())
        or not records.get("host", "").strip()
        or not records.get("slurm_job_id", "").isdigit()
    ):
        raise TB4AuditError("provenance_mismatch")


def _validate_smoke_concurrency(
    smoke_payload: dict[str, Any],
    *,
    expected_rollout_concurrency: int,
    expected_lease_start_concurrency: int,
) -> None:
    expected_concurrency = (
        expected_rollout_concurrency,
        expected_lease_start_concurrency,
    )
    if expected_concurrency == (
        EXPECTED_TB4_ROLLOUT_CONCURRENCY,
        EXPECTED_TB4_LEASE_START_CONCURRENCY,
    ):
        return
    if expected_concurrency != (24, EXPECTED_TB4_LEASE_START_CONCURRENCY):
        raise TB4AuditError("smoke_checkpoint_concurrency_invalid")

    expected_execution = {
        "rollout_concurrency": expected_rollout_concurrency,
        "multiplex": expected_rollout_concurrency,
        "http_max_connections": expected_rollout_concurrency,
        "http_max_keepalive_connections": expected_rollout_concurrency,
        "lease_start_concurrency": expected_lease_start_concurrency,
    }
    qualified_execution = smoke_payload.get("qualified_execution")
    if (
        not isinstance(qualified_execution, dict)
        or set(qualified_execution) != set(expected_execution)
        or any(type(value) is not int for value in qualified_execution.values())
        or qualified_execution != expected_execution
    ):
        raise TB4AuditError("smoke_checkpoint_qualified_execution_invalid")

    expected_observation = {
        "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
        "lease_start_signal": "vacli_lease_start_semaphore_holders",
        "peak_active_rollouts_lower_bound": expected_rollout_concurrency,
        "peak_concurrent_lease_startups": expected_lease_start_concurrency,
        "required_peak_active_rollouts_lower_bound": expected_rollout_concurrency,
        "required_peak_concurrent_lease_startups": expected_lease_start_concurrency,
    }
    observed_concurrency = smoke_payload.get("observed_concurrency")
    observed_counts = (
        "peak_active_rollouts_lower_bound",
        "peak_concurrent_lease_startups",
        "required_peak_active_rollouts_lower_bound",
        "required_peak_concurrent_lease_startups",
    )
    policy = smoke_payload.get("audit_policy")
    counts = smoke_payload.get("counts")
    if (
        not isinstance(observed_concurrency, dict)
        or set(observed_concurrency) != set(expected_observation)
        or any(type(observed_concurrency.get(key)) is not int for key in observed_counts)
        or observed_concurrency != expected_observation
        or not isinstance(policy, dict)
        or not isinstance(counts, dict)
        or not isinstance(policy.get("expected_traces"), int)
        or isinstance(policy.get("expected_traces"), bool)
        or policy["expected_traces"] < expected_rollout_concurrency
        or counts.get("traces") != policy["expected_traces"]
        or counts.get("tasks") != policy["expected_traces"]
    ):
        raise TB4AuditError("smoke_checkpoint_observed_concurrency_invalid")


def _validate_deployment_checkpoints_legacy(
    identity: dict[str, Any],
    endpoint: dict[str, Any],
    *,
    expected_routes: int,
    expected_rollout_concurrency: int,
    expected_lease_start_concurrency: int,
) -> tuple[tuple[Path, str], tuple[Path, str]]:
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict):
        raise TB4AuditError("deployment_identity_invalid")
    spec = deployment.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("sha256"), str):
        raise TB4AuditError("deployment_identity_invalid")
    readiness = _identity_artifact(deployment.get("readiness_checkpoint"), label="readiness_checkpoint")
    smoke = _identity_artifact(deployment.get("smoke_checkpoint"), label="smoke_checkpoint")
    readiness_payload = _read_json_object(readiness[0], label="readiness_checkpoint")
    probe = readiness_payload.get("probe")
    if (
        readiness_payload.get("schema_version") != 1
        or readiness_payload.get("state") != "passed"
        or readiness_payload.get("deployment") != deployment.get("id")
        or readiness_payload.get("observed_spec_sha256") != spec["sha256"]
        or not isinstance(probe, dict)
        or probe.get("ok") is not True
    ):
        raise TB4AuditError("readiness_checkpoint_not_passed")
    try:
        readiness_endpoint = validate_endpoint_binding(readiness_payload.get("endpoint"))
        identity_generation = validate_route_generation(deployment.get("serving_route_generation"))
        readiness_generation = validate_readiness_route_generation(
            readiness_payload,
            deployment_id=deployment.get("id"),
            deployment_spec_sha256=spec["sha256"],
        )
        identity_proxy_policy = validate_proxy_policy_binding(deployment.get("proxy_policy"))
        readiness_proxy_policy = validate_proxy_policy_binding(readiness_payload.get("proxy_policy"))
        revalidate_deployment_proxy_policy(
            Path(spec["path"]),
            expected_spec_sha256=spec["sha256"],
            expected_binding=identity_proxy_policy,
        )
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise TB4AuditError("readiness_checkpoint_endpoint_invalid") from error
    if (
        readiness_endpoint != endpoint
        or readiness_generation != identity_generation
        or readiness_proxy_policy != identity_proxy_policy
        or len(readiness_generation["routes"]) != expected_routes
    ):
        raise TB4AuditError("readiness_checkpoint_endpoint_mismatch")
    smoke_payload = _read_json_object(smoke[0], label="smoke_checkpoint")
    self_digest = smoke_payload.get("smoke_checkpoint_sha256")
    smoke_body = {key: value for key, value in smoke_payload.items() if key != "smoke_checkpoint_sha256"}
    smoke_deployment = smoke_payload.get("deployment")
    smoke_artifacts = smoke_payload.get("artifacts")
    smoke_readiness = smoke_artifacts.get("readiness_checkpoint") if isinstance(smoke_artifacts, dict) else None
    policy = smoke_payload.get("audit_policy")
    counts = smoke_payload.get("counts")
    if (
        smoke_payload.get("schema_version") != 1
        or smoke_payload.get("state") != "passed"
        or smoke_payload.get("ok") is not True
        or not isinstance(self_digest, str)
        or self_digest != hashlib.sha256(canonical_json(smoke_body)).hexdigest()
        or not isinstance(smoke_deployment, dict)
        or smoke_deployment.get("id") != deployment.get("id")
        or smoke_deployment.get("spec_sha256") != spec["sha256"]
        or not isinstance(smoke_readiness, dict)
        or smoke_readiness != {"path": str(readiness[0]), "sha256": readiness[1]}
        or not isinstance(policy, dict)
        or policy.get("rollouts_per_task") != 1
        or policy.get("require_reasoning") is not True
        or policy.get("require_model_io") is not True
        or canonical_json(policy.get("model_io_contract")) != canonical_json(EXPECTED_MODEL_IO_CONTRACT)
        or policy.get("require_token_data") is not False
        or policy.get("require_logprobs") is not False
        or policy.get("max_sequence_tokens") != DEFAULT_MAX_SEQUENCE_TOKENS
        or not isinstance(counts, dict)
        or counts.get("trace_failures") != 0
        or counts.get("global_problems") != 0
    ):
        raise TB4AuditError("smoke_checkpoint_not_passed")
    _validate_smoke_concurrency(
        smoke_payload,
        expected_rollout_concurrency=expected_rollout_concurrency,
        expected_lease_start_concurrency=expected_lease_start_concurrency,
    )
    try:
        smoke_endpoint = validate_endpoint_binding(smoke_payload.get("endpoint"))
        smoke_generation = validate_route_generation(smoke_payload.get("serving_route_generation"))
        smoke_proxy_policy = validate_proxy_policy_binding(smoke_payload.get("proxy_policy"))
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise TB4AuditError("smoke_checkpoint_endpoint_invalid") from error
    smoke_proxy = smoke_artifacts.get("proxy_info") if isinstance(smoke_artifacts, dict) else None
    if (
        smoke_endpoint != endpoint
        or smoke_proxy != endpoint["proxy_info"]
        or smoke_generation != identity_generation
        or smoke_proxy_policy != identity_proxy_policy
    ):
        raise TB4AuditError("smoke_checkpoint_endpoint_mismatch")
    expected_traces = policy.get("expected_traces")
    positive_counts = (counts.get("traces"), counts.get("tasks"), counts.get("model_io_turns"))
    if (
        not isinstance(expected_traces, int)
        or isinstance(expected_traces, bool)
        or expected_traces < 1
        or counts.get("traces") != expected_traces
        or counts.get("tasks") != expected_traces
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in positive_counts)
    ):
        raise TB4AuditError("smoke_checkpoint_counts_invalid")
    return readiness, smoke


def _validate_deployment_checkpoints(
    identity: dict[str, Any],
    endpoint: dict[str, Any],
    *,
    expected_routes: int = EXPECTED_ROUTES_BY_ROLLOUT_CONCURRENCY[
        EXPECTED_TB4_ROLLOUT_CONCURRENCY
    ],
    expected_rollout_concurrency: int = EXPECTED_TB4_ROLLOUT_CONCURRENCY,
    expected_lease_start_concurrency: int = EXPECTED_TB4_LEASE_START_CONCURRENCY,
) -> tuple[tuple[Path, str], tuple[Path, str]]:
    """Revalidate readiness and smoke through the shared qualification gate."""

    if (
        expected_lease_start_concurrency != EXPECTED_TB4_LEASE_START_CONCURRENCY
        or EXPECTED_ROUTES_BY_ROLLOUT_CONCURRENCY.get(expected_rollout_concurrency)
        != expected_routes
    ):
        raise TB4AuditError("tb4_concurrency_policy_invalid")
    deployment = identity.get("deployment")
    contract = identity.get("contract")
    if not isinstance(deployment, dict) or not isinstance(contract, dict):
        raise TB4AuditError("deployment_identity_invalid")
    spec = _identity_artifact(deployment.get("spec"), label="deployment_spec")
    readiness = _identity_artifact(
        deployment.get("readiness_checkpoint"),
        label="readiness_checkpoint",
    )
    smoke = _identity_artifact(
        deployment.get("smoke_checkpoint"),
        label="smoke_checkpoint",
    )
    smoke_payload = _read_json_object(smoke[0], label="smoke_checkpoint")
    if smoke_payload.get("schema_version") == 1:
        return _validate_deployment_checkpoints_legacy(
            identity,
            endpoint,
            expected_routes=expected_routes,
            expected_rollout_concurrency=expected_rollout_concurrency,
            expected_lease_start_concurrency=expected_lease_start_concurrency,
        )
    proxy_info = endpoint.get("proxy_info")
    if not isinstance(proxy_info, dict):
        raise TB4AuditError("deployment_identity_invalid")
    try:
        evidence = validate_smoke_qualification(
            smoke[0],
            smoke[1],
            deployment_id=deployment["id"],
            deployment_spec_path=spec[0],
            deployment_spec_sha256=spec[1],
            readiness_path=readiness[0],
            readiness_sha256=readiness[1],
            proxy_info_path=Path(proxy_info["path"]),
            proxy_info_sha256=proxy_info["sha256"],
            model=contract["model"],
            identity_loader=load_eval_run_identity,
        )
    except (KeyError, TypeError, SmokeQualificationError) as error:
        raise TB4AuditError("smoke_checkpoint_not_passed") from error
    if (
        expected_rollout_concurrency,
        expected_lease_start_concurrency,
    ) != (
        EXPECTED_TB4_ROLLOUT_CONCURRENCY,
        EXPECTED_TB4_LEASE_START_CONCURRENCY,
    ):
        source_smoke_payload = _read_json_object(
            evidence.source_smoke.path,
            label="source_smoke_checkpoint",
        )
        _validate_smoke_concurrency(
            source_smoke_payload,
            expected_rollout_concurrency=expected_rollout_concurrency,
            expected_lease_start_concurrency=expected_lease_start_concurrency,
        )
        if (
            _sha256_file(evidence.source_smoke.path, label="source_smoke_checkpoint")
            != evidence.source_smoke.sha256
        ):
            raise TB4AuditError("smoke_checkpoint_endpoint_mismatch")
    if (
        evidence.target_generation != deployment.get("serving_route_generation")
        or len(evidence.target_generation["routes"]) != expected_routes
    ):
        raise TB4AuditError("smoke_checkpoint_endpoint_mismatch")
    return readiness, smoke


def _certificate_bytes(certificate: dict[str, Any]) -> bytes:
    return (json.dumps(certificate, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _publish_write_once(path: Path, certificate: dict[str, Any]) -> None:
    payload = _certificate_bytes(certificate)
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise TB4AuditError("tb4_certificate_invalid")
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise TB4AuditError("tb4_certificate_unreadable") from error
        if existing != payload:
            raise TB4AuditError("tb4_certificate_already_exists_different")
        return

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                raise TB4AuditError("tb4_certificate_already_exists_different")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise TB4AuditError("tb4_certificate_write_failed") from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def certify_tb4_results(
    results: Path,
    *,
    certificate_path: Path,
    min_supported_pass_rate: float,
    max_supported_pass_rate: float,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
    expected_rollout_concurrency: int = EXPECTED_TB4_ROLLOUT_CONCURRENCY,
    expected_lease_start_concurrency: int = EXPECTED_TB4_LEASE_START_CONCURRENCY,
) -> dict[str, Any]:
    """Validate and atomically bind a completed TB4 run without exporting example data."""

    try:
        run_dir = results.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise TB4AuditError("results_directory_unreadable") from error
    if not run_dir.is_dir():
        raise TB4AuditError("results_directory_unreadable")
    results = _resolved_file(results, label="results")
    _require_run_local(results, run_dir / "results.jsonl", label="results")
    try:
        certificate_parent = certificate_path.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise TB4AuditError("tb4_certificate_parent_unreadable") from error
    if certificate_parent != run_dir or certificate_path.name != "checkpoint.json":
        raise TB4AuditError("tb4_certificate_path_mismatch")
    certificate_path = certificate_parent / certificate_path.name
    if (
        not math.isfinite(min_supported_pass_rate)
        or not math.isfinite(max_supported_pass_rate)
        or min_supported_pass_rate != EXPECTED_MIN_SUPPORTED_PASS_RATE
        or max_supported_pass_rate != EXPECTED_MAX_SUPPORTED_PASS_RATE
    ):
        raise TB4AuditError("tb4_score_bounds_mismatch")
    if (
        expected_rollout_concurrency not in SUPPORTED_TB4_ROLLOUT_CONCURRENCIES
        or expected_lease_start_concurrency != EXPECTED_TB4_LEASE_START_CONCURRENCY
        or expected_lease_start_concurrency > expected_rollout_concurrency
    ):
        raise TB4AuditError("tb4_concurrency_policy_invalid")

    with _hold_writer_lock(run_dir):
        identity_path = _resolved_file(run_dir / "eval_run_identity.json", label="eval_run_identity")
        identity_file_sha256 = _sha256_file(identity_path, label="eval_run_identity")
        try:
            envelope = load_eval_run_identity(identity_path)
        except EvalIdentityError as error:
            raise TB4AuditError("eval_run_identity_invalid") from error
        if _sha256_file(identity_path, label="eval_run_identity") != identity_file_sha256:
            raise TB4AuditError("eval_run_identity_changed")
        identity = _validate_tb4_identity(
            envelope,
            expected_rollout_concurrency=expected_rollout_concurrency,
            expected_lease_start_concurrency=expected_lease_start_concurrency,
        )
        identity_sha256 = envelope["eval_run_identity_sha256"]
        endpoint = _validated_endpoint(identity)

        config_section = identity.get("config")
        inputs_section = identity.get("inputs")
        dataset_section = identity.get("dataset")
        if not all(isinstance(value, dict) for value in (config_section, inputs_section, dataset_section)):
            raise TB4AuditError("eval_run_identity_schema_invalid")
        assert isinstance(config_section, dict)
        assert isinstance(inputs_section, dict)
        assert isinstance(dataset_section, dict)
        config = _identity_artifact(config_section.get("resolved"), label="config")
        manifest = _identity_artifact(inputs_section.get("manifest"), label="inputs_manifest")
        task_record = inputs_section.get("task_file")
        if not isinstance(task_record, dict) or not {"path", "sha256", "count"}.issubset(task_record):
            raise TB4AuditError("task_file_identity_invalid")
        task_file = _resolved_file(Path(str(task_record["path"])), label="task_file")
        if _sha256_file(task_file, label="task_file") != task_record["sha256"]:
            raise TB4AuditError("task_file_sha256_mismatch")
        _require_run_local(config[0], run_dir / "config.toml", label="config")
        _require_run_local(manifest[0], run_dir / "inputs/manifest.json", label="inputs_manifest")
        _require_run_local(task_file, run_dir / "inputs/task_file.txt", label="task_file")
        provenance = _resolved_file(run_dir / "provenance.txt", label="provenance")
        _validate_provenance(provenance, identity=identity, identity_sha256=identity_sha256)
        readiness, smoke = _validate_deployment_checkpoints(
            identity,
            endpoint,
            expected_routes=EXPECTED_ROUTES_BY_ROLLOUT_CONCURRENCY[
                expected_rollout_concurrency
            ],
            expected_rollout_concurrency=expected_rollout_concurrency,
            expected_lease_start_concurrency=expected_lease_start_concurrency,
        )
        deployment = identity["deployment"]
        guard_receipt_path = run_dir / "route_guard_success.json"
        guarded_results_sha256 = _sha256_file(results, label="results")
        try:
            if guard_receipt_path.resolve(strict=True) != guard_receipt_path:
                raise GuardReceiptError("guard_receipt_path_mismatch")
            guard_receipt = load_guard_success_receipt(guard_receipt_path)
            guard_artifacts = validate_guard_success_linkage(
                guard_receipt,
                run_dir=run_dir,
                eval_run_identity_sha256=identity_sha256,
                eval_run_role="tb4",
                eval_run_identity_file_sha256=identity_file_sha256,
                results_sha256=guarded_results_sha256,
                deployment_id=deployment["id"],
                deployment_spec_sha256=deployment["spec"]["sha256"],
                readiness_checkpoint={"path": str(readiness[0]), "sha256": readiness[1]},
                endpoint=endpoint,
                serving_route_generation=deployment["serving_route_generation"],
                proxy_policy=deployment["proxy_policy"],
            )
        except (OSError, GuardReceiptError) as error:
            raise TB4AuditError("guard_success_receipt_invalid") from error

        dataset_path = dataset_section.get("path")
        if not isinstance(dataset_path, str):
            raise TB4AuditError("dataset_identity_invalid")
        if max_sequence_tokens != DEFAULT_MAX_SEQUENCE_TOKENS:
            raise TB4AuditError("tb4_max_sequence_tokens_mismatch")

        artifact_paths = {
            "results": results,
            "eval_run_identity": identity_path,
            "eval_invocations": Path(guard_artifacts["eval_invocations"]["path"]),
            "route_guard_success": guard_receipt_path,
            "config": config[0],
            "inputs_manifest": manifest[0],
            "provenance": provenance,
            "readiness_checkpoint": readiness[0],
            "smoke_checkpoint": smoke[0],
            "proxy_info": Path(endpoint["proxy_info"]["path"]),
        }
        before = {name: _sha256_file(path, label=name) for name, path in artifact_paths.items()}
        if before["eval_run_identity"] != identity_file_sha256:
            raise TB4AuditError("eval_run_identity_changed")
        try:
            summary, failed = audit_results(
                results,
                dataset_dir=Path(dataset_path),
                task_file=task_file,
                min_supported_pass_rate=min_supported_pass_rate,
                max_supported_pass_rate=max_supported_pass_rate,
                max_sequence_tokens=max_sequence_tokens,
            )
        except (TraceJSONLError, TB4AuditError) as error:
            raise TB4AuditError("tb4_results_audit_failed") from error
        if failed:
            raise TB4AuditError("tb4_results_audit_failed")
        after = {name: _sha256_file(path, label=name) for name, path in artifact_paths.items()}
        if before != after:
            raise TB4AuditError("tb4_audit_artifact_changed")
        if (
            before["results"] != guard_artifacts["results"]["sha256"]
            or before["eval_run_identity"] != guard_artifacts["eval_run_identity"]["sha256"]
            or before["eval_invocations"] != guard_artifacts["eval_invocations"]["sha256"]
            or before["config"] != config[1]
            or before["inputs_manifest"] != manifest[1]
            or before["readiness_checkpoint"] != readiness[1]
            or before["smoke_checkpoint"] != smoke[1]
            or before["proxy_info"] != endpoint["proxy_info"]["sha256"]
        ):
            raise TB4AuditError("identity_artifact_sha256_mismatch")

        unsigned = {
            "schema_version": 1,
            "state": "passed",
            "ok": True,
            "eval_run_identity_sha256": identity_sha256,
            "deployment": {
                "id": deployment["id"],
                "spec_sha256": deployment["spec"]["sha256"],
            },
            "endpoint": endpoint,
            "serving_route_generation": deployment["serving_route_generation"],
            "proxy_policy": deployment["proxy_policy"],
            "audit_policy": {
                "expected_tasks": EXPECTED_TASK_COUNT,
                "expected_supported_tasks": EXPECTED_SUPPORTED_TASK_COUNT,
                "expected_cpu_unsupported_tasks": len(EXPECTED_UNSUPPORTED_TASKS),
                "rollouts_per_task": 1,
                "model": EXPECTED_MODEL,
                "reasoning_effort": "max",
                "max_sequence_tokens": max_sequence_tokens,
                "rollout_concurrency": expected_rollout_concurrency,
                "lease_start_concurrency": expected_lease_start_concurrency,
                "require_reasoning": True,
                "require_response": True,
                "require_model_io": True,
                "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
                "require_tool_schemas": True,
                "require_tool_call_lineage": True,
                "require_token_data": False,
                "require_logprobs": False,
                "binary_solved_reward": True,
                "min_supported_pass_rate": min_supported_pass_rate,
                "max_supported_pass_rate": max_supported_pass_rate,
            },
            "counts": {
                "observed_traces": summary["observed_traces"],
                "supported_tasks": summary["supported_tasks"],
                "cpu_unsupported_tasks": len(summary["observed_unsupported_tasks"]),
                "supported_passes": summary["supported_passes"],
                "trace_failures": summary["trace_failures"],
                "supported_trace_failures": summary["supported_trace_failures"],
                "cpu_unsupported_trace_failures": summary["unsupported_trace_failures"],
                "global_problems": len(summary["global_problems"]),
            },
            "scores": {
                "supported_pass_rate": summary["supported_pass_rate"],
                "all_task_pass_rate": summary["all_task_pass_rate"],
            },
            "artifacts": {name: {"path": str(artifact_paths[name]), "sha256": before[name]} for name in artifact_paths},
        }
        certificate = {
            **unsigned,
            "tb4_certificate_sha256": hashlib.sha256(canonical_json(unsigned)).hexdigest(),
        }
        _publish_write_once(certificate_path, certificate)
        return certificate


def _rate(value: str) -> float:
    rate = float(value)
    if not math.isfinite(rate) or not 0 <= rate <= 1:
        raise argparse.ArgumentTypeError("must be a finite number between 0 and 1")
    return rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        help="pinned TB4 tasks directory used to establish the expected slug set",
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        help="optional exact 66-slug subset within --dataset-dir",
    )
    parser.add_argument(
        "--min-supported-pass-rate",
        type=_rate,
        help="optional inclusive lower bound for rewards.solved across the 63 CPU-supported tasks",
    )
    parser.add_argument(
        "--max-supported-pass-rate",
        type=_rate,
        help="optional inclusive upper bound for rewards.solved across the 63 CPU-supported tasks",
    )
    parser.add_argument(
        "--max-sequence-tokens",
        type=int,
        default=DEFAULT_MAX_SEQUENCE_TOKENS,
    )
    parser.add_argument(
        "--certificate",
        type=Path,
        help="publish an aggregate-only, write-once TB4 certificate using run identity inputs",
    )
    parser.add_argument(
        "--expected-rollout-concurrency",
        type=int,
        default=EXPECTED_TB4_ROLLOUT_CONCURRENCY,
    )
    parser.add_argument(
        "--expected-lease-start-concurrency",
        type=int,
        default=EXPECTED_TB4_LEASE_START_CONCURRENCY,
    )
    args = parser.parse_args()
    if args.max_sequence_tokens < 1:
        parser.error("--max-sequence-tokens must be positive")
    if (
        args.min_supported_pass_rate is not None
        and args.max_supported_pass_rate is not None
        and args.min_supported_pass_rate > args.max_supported_pass_rate
    ):
        parser.error("--min-supported-pass-rate cannot exceed --max-supported-pass-rate")
    try:
        if args.certificate is not None:
            if args.dataset_dir is not None or args.task_file is not None:
                parser.error("--dataset-dir/--task-file cannot be used with --certificate")
            if args.min_supported_pass_rate is None or args.max_supported_pass_rate is None:
                parser.error("certificate mode requires both supported pass-rate bounds")
            summary = certify_tb4_results(
                args.results,
                certificate_path=args.certificate,
                min_supported_pass_rate=args.min_supported_pass_rate,
                max_supported_pass_rate=args.max_supported_pass_rate,
                max_sequence_tokens=args.max_sequence_tokens,
                expected_rollout_concurrency=args.expected_rollout_concurrency,
                expected_lease_start_concurrency=args.expected_lease_start_concurrency,
            )
            failed = False
        else:
            if args.dataset_dir is None:
                parser.error("--dataset-dir is required unless --certificate is used")
            summary, failed = audit_results(
                args.results,
                dataset_dir=args.dataset_dir,
                task_file=args.task_file,
                min_supported_pass_rate=args.min_supported_pass_rate,
                max_supported_pass_rate=args.max_supported_pass_rate,
                max_sequence_tokens=args.max_sequence_tokens,
            )
    except (OSError, TraceJSONLError, TB4AuditError, EvalIdentityError) as error:
        parser.error(str(error))
    if args.certificate is None:
        output = summary
    else:
        checkpoint_path = args.certificate.resolve(strict=True)
        output = {
            "ok": True,
            "checkpoint": str(checkpoint_path),
            "checkpoint_file_sha256": _sha256_file(checkpoint_path, label="tb4_certificate"),
            "tb4_certificate_sha256": summary["tb4_certificate_sha256"],
        }
    print(json.dumps(output, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
