#!/usr/bin/env python3
"""Finalize the immutable Kimi TB4 v8 run with verifier-failure zeroes."""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import finalize_kimi_tb4_sandoq_small_full as ordinary
import finalize_kimi_tb4_sandoq_small_v4_recovery as recovery
import finalize_kimi_tb4_sandoq_small_v6_supersession as transport
import finalize_kimi_tb4_sandoq_small_v7 as v7
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module

SCHEMA_VERSION = 2
KIND = ordinary.KIND
RESULTS = ordinary.RESULTS
CERTIFICATE = ordinary.CERTIFICATE
OUTPUT_NAME = "full-denominator-supersession-v2"
SUPERSESSION_REASON = "fixed-denominator-exact-transport-v8-post-agent-verifier-zero"
TARGET_PASSES = 7
EXECUTION_SOURCE_REVISION = "02ced99650a33f6c548e47569d18587ae4a71a08"
EXECUTION_VERIFIERS_COMMIT = "36b0dff6c18affb3d40b7c46d5836381d568050b"
EXECUTION_SLURM_JOB_ID = "1607011"
EXECUTION_PLAN_SHA256 = "af936100b1cb06e021f98de9900d235a9175e716fd9e9432298889f9ea9d6150"
VERIFIER_ATTEMPTS = 3
PROVISIONING_ATTEMPTS = 9
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
KNOWN_POOL_EVENTS = frozenset(
    {
        "assignment_acquired",
        "assignment_cancelled",
        "assignment_ready",
        "assignment_release_failed",
        "assignment_released",
        "capacity_backpressure",
        "ecr_credential_vended",
        "gateway_close_failed",
        "managed_shell_ipc_response_delivery_failed",
        "managed_shell_operation_abandoned",
        "managed_shell_recovered",
        "managed_shell_recovery_failed",
        "outer_create_failed",
        "outer_created",
        "outer_delete_failed",
        "outer_deleted",
        "outer_renewal_failed",
        "outer_renewed",
        "pool_drain_incomplete",
        "pool_drained",
        "pool_recovery_completed",
        "pool_recovery_incomplete",
        "pool_recovery_retry",
        "pool_recovery_started",
        "pool_started",
    }
)
SUPERSESSION_SOURCE_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v8_supersession.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v7.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v6_supersession.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v4_recovery.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py",
    "user/tianhaowu/terminal_bench_vmvm/prepare_kimi_tb4_miniswe246_union.py",
    "user/tianhaowu/terminal_bench_vmvm/prepare_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/audit_traces.py",
)


@dataclass(frozen=True)
class ExecutionContract:
    """Immutable execution identity consumed by the shared v8 audit engine."""

    source_revision: str
    verifiers_commit: str
    slurm_job_id: str
    plan_sha256: str
    output_name: str
    supersession_reason: str
    supersession_source_files: tuple[str, ...]
    allow_exact_length_benchmark_passes: bool = False
    allow_post_agent_exec_transport_errors: bool = False


V8_EXECUTION_CONTRACT = ExecutionContract(
    source_revision=EXECUTION_SOURCE_REVISION,
    verifiers_commit=EXECUTION_VERIFIERS_COMMIT,
    slurm_job_id=EXECUTION_SLURM_JOB_ID,
    plan_sha256=EXECUTION_PLAN_SHA256,
    output_name=OUTPUT_NAME,
    supersession_reason=SUPERSESSION_REASON,
    supersession_source_files=SUPERSESSION_SOURCE_FILES,
)


class V8SupersessionError(ValueError):
    """The immutable v8 run cannot be represented by this supersession."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise V8SupersessionError(code)
    raise V8SupersessionError(code) from error


def _validated_execution_contract(contract: ExecutionContract) -> ExecutionContract:
    if (
        not isinstance(contract, ExecutionContract)
        or not isinstance(contract.source_revision, str)
        or REVISION_RE.fullmatch(contract.source_revision) is None
        or not isinstance(contract.verifiers_commit, str)
        or REVISION_RE.fullmatch(contract.verifiers_commit) is None
        or not isinstance(contract.slurm_job_id, str)
        or re.fullmatch(r"[1-9][0-9]*", contract.slurm_job_id) is None
        or not isinstance(contract.plan_sha256, str)
        or plan_module.SHA256_RE.fullmatch(contract.plan_sha256) is None
        or not isinstance(contract.output_name, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", contract.output_name) is None
        or not isinstance(contract.supersession_reason, str)
        or not contract.supersession_reason
        or not isinstance(contract.supersession_source_files, tuple)
        or not contract.supersession_source_files
        or len(contract.supersession_source_files) != len(set(contract.supersession_source_files))
        or type(contract.allow_exact_length_benchmark_passes) is not bool
        or type(contract.allow_post_agent_exec_transport_errors) is not bool
        or any(
            not isinstance(path, str)
            or not path.startswith("user/tianhaowu/terminal_bench_vmvm/")
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            for path in contract.supersession_source_files
        )
    ):
        _fail("execution_contract_invalid")
    return contract


def _supersession_source_binding(
    expected_revision: str,
    source_files: tuple[str, ...] = SUPERSESSION_SOURCE_FILES,
) -> dict[str, Any]:
    try:
        binding = recovery._repository_binding(expected_revision)
        project = Path(str(binding["project_root"]))
        status = subprocess.run(
            ["git", "-C", str(project), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if status:
            _fail("supersession_source_invalid")
        files = transport._git_file_hashes(project, expected_revision, source_files)
        for path, expected_sha256 in files.items():
            if recovery._sha256((project / path).read_bytes()) != expected_sha256:
                _fail("supersession_source_invalid")
    except V8SupersessionError:
        raise
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        _fail("supersession_source_invalid", error)
    return {
        **binding,
        "hash_kind": "raw-file-sha256",
        "files": files,
        "file_set_sha256": recovery._sha256(split.canonical_json(files)),
    }


def _assignment_lifecycle_audit(
    body: bytes,
    *,
    expected_slurm_job_id: str,
    trace_audit: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    verifier_modes: Mapping[str, str],
) -> dict[str, Any]:
    if not body or not body.endswith(b"\n") or b"\r" in body:
        _fail("assignment_lifecycle_invalid")
    acquired: dict[str, dict[str, bool]] = {}
    ready: set[str] = set()
    terminal: set[str] = set()
    abandoned: set[str] = set()
    recovery_failed: set[str] = set()
    reasons: Counter[str] = Counter()
    initialization_statuses: Counter[str] = Counter()
    recoveries = 0
    cancellations = 0
    event_counts: Counter[str] = Counter()
    for line in body.splitlines():
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            _fail("assignment_lifecycle_invalid", error)
        if (
            not isinstance(event, dict)
            or event.get("schema_version") != 2
            or event.get("record_type") != "pool_event"
            or event.get("slurm_job_id") != expected_slurm_job_id
        ):
            _fail("assignment_lifecycle_invalid")
        name = event.get("event")
        if not isinstance(name, str) or name not in KNOWN_POOL_EVENTS:
            _fail("assignment_lifecycle_invalid")
        event_counts[name] += 1
        assignment_id = event.get("assignment_id")
        if name == "assignment_acquired":
            if not isinstance(assignment_id, str) or not assignment_id or assignment_id in acquired:
                _fail("assignment_lifecycle_invalid")
            acquired[assignment_id] = {"ready": False, "terminal": False}
        elif name == "assignment_ready":
            if (
                not isinstance(assignment_id, str)
                or assignment_id not in acquired
                or assignment_id in ready
                or assignment_id in terminal
            ):
                _fail("assignment_lifecycle_invalid")
            acquired[assignment_id]["ready"] = True
            ready.add(assignment_id)
        elif name == "managed_shell_recovered":
            if not isinstance(assignment_id, str) or assignment_id not in ready or assignment_id in terminal:
                _fail("assignment_lifecycle_invalid")
            recoveries += 1
        elif name == "managed_shell_operation_abandoned":
            if (
                not isinstance(assignment_id, str)
                or assignment_id not in ready
                or assignment_id in terminal
                or assignment_id in abandoned
            ):
                _fail("assignment_lifecycle_invalid")
            abandoned.add(assignment_id)
        elif name == "managed_shell_recovery_failed":
            if (
                not isinstance(assignment_id, str)
                or assignment_id not in ready
                or assignment_id in terminal
                or assignment_id in recovery_failed
                or event.get("error_type") != "RuntimeError"
            ):
                _fail("assignment_lifecycle_invalid")
            recovery_failed.add(assignment_id)
        elif name in {"assignment_release_failed", "pool_drain_incomplete"}:
            _fail("assignment_lifecycle_invalid")
        elif name == "assignment_cancelled":
            if (
                not isinstance(assignment_id, str)
                or assignment_id not in acquired
                or assignment_id in ready
                or assignment_id in terminal
                or event.get("cancellation_verified") is not True
                or event.get("status") is not None
                or bool(event.get("error"))
            ):
                _fail("assignment_lifecycle_invalid")
            acquired[assignment_id]["terminal"] = True
            terminal.add(assignment_id)
            cancellations += 1
        elif name == "assignment_released":
            if not isinstance(assignment_id, str) or assignment_id not in acquired or assignment_id in terminal:
                _fail("assignment_lifecycle_invalid")
            reason = event.get("reason")
            if reason == "initialization_failure":
                valid = (
                    assignment_id not in ready
                    and event.get("status") == "poisoned"
                    and event.get("poisoned") is True
                    and event.get("nested_recycle_verified") is False
                    and event.get("outer_deletion_verified_http_status") == 404
                    and isinstance(event.get("error"), str)
                    and bool(event["error"])
                    and event.get("shell_failure_status") in {"http_500", "initialization_command_failed"}
                )
                initialization_statuses[str(event.get("shell_failure_status"))] += 1
            elif reason == "rollout_complete":
                valid = (
                    assignment_id in ready
                    and event.get("status") == "retired"
                    and event.get("poisoned") is False
                    and event.get("nested_recycle_verified") is True
                    and event.get("outer_deletion_verified_http_status") == 404
                    and not event.get("error")
                )
            elif reason == "managed_shell_lost":
                expected_shell_status = (
                    "managed_shell_command_outcome_unknown"
                    if assignment_id in abandoned
                    else "managed_shell_recovery_failed"
                )
                valid = (
                    assignment_id in ready
                    and assignment_id in (abandoned | recovery_failed)
                    and event.get("status") == "poisoned"
                    and event.get("poisoned") is True
                    and event.get("nested_recycle_verified") is False
                    and event.get("outer_deletion_verified_http_status") == 404
                    and event.get("shell_failure_status") == expected_shell_status
                    and isinstance(event.get("error"), str)
                    and bool(event["error"])
                )
            else:
                valid = False
            if not valid:
                _fail("assignment_lifecycle_invalid")
            acquired[assignment_id]["terminal"] = True
            terminal.add(assignment_id)
            reasons[str(reason)] += 1

    if (
        not acquired
        or event_counts["pool_started"] != 1
        or event_counts["pool_recovery_completed"] != 1
        or event_counts["pool_drained"] != 1
        or set(acquired) != terminal
        or any(not state["terminal"] for state in acquired.values())
        or ready != {assignment_id for assignment_id in terminal if assignment_id in ready}
        or abandoned != {assignment_id for assignment_id in terminal if assignment_id in abandoned}
        or recovery_failed
        != {assignment_id for assignment_id in terminal if assignment_id in recovery_failed}
        or not abandoned.isdisjoint(recovery_failed)
        or reasons["managed_shell_lost"] != len(abandoned) + len(recovery_failed)
        or len(acquired) != len(ready) + reasons["initialization_failure"] + cancellations
        or len(ready) != reasons["rollout_complete"] + reasons["managed_shell_lost"]
    ):
        _fail("assignment_lifecycle_invalid")

    zero_model_errors = trace_audit.get("zero_model_error_zeroes")
    post_agent_errors = trace_audit.get("post_agent_verifier_sandbox_error_zeroes")
    exec_transport_policy = (
        "post_agent_verifier_provisioning_error_zeroes" in trace_audit
        or "post_agent_verifier_exec_transport_error_zeroes" in trace_audit
    )
    post_agent_provisioning_errors = trace_audit.get(
        "post_agent_verifier_provisioning_error_zeroes",
        post_agent_errors,
    )
    post_agent_exec_transport_errors = trace_audit.get(
        "post_agent_verifier_exec_transport_error_zeroes",
        0,
    )
    pre_model_provisioning_errors = trace_audit.get("pre_model_sandoq_provisioning_error_zeroes")
    if (
        not transport._nonnegative_integer(zero_model_errors)
        or not transport._nonnegative_integer(post_agent_errors)
        or not transport._nonnegative_integer(post_agent_provisioning_errors)
        or not transport._nonnegative_integer(post_agent_exec_transport_errors)
        or int(post_agent_errors)
        != int(post_agent_provisioning_errors) + int(post_agent_exec_transport_errors)
        or not transport._nonnegative_integer(pre_model_provisioning_errors)
        or int(pre_model_provisioning_errors) > int(zero_model_errors)
        or (not exec_transport_policy and recovery_failed)
    ):
        _fail("assignment_lifecycle_invalid")
    required_initialization_failures = PROVISIONING_ATTEMPTS * (
        int(pre_model_provisioning_errors)
        + VERIFIER_ATTEMPTS * int(post_agent_provisioning_errors)
    )
    initialization_failures = reasons["initialization_failure"]
    if initialization_failures < required_initialization_failures:
        _fail("assignment_lifecycle_invalid")
    scored_separate = 0
    separate_retry_attempts = 0
    for task_id, row in rows.items():
        if row.get("errors") != [] or verifier_modes.get(task_id) != "separate":
            continue
        verifier = row.get("info", {}).get("terminal_bench_verifier")
        attempts = verifier.get("attempts") if isinstance(verifier, Mapping) else None
        failures = verifier.get("infrastructure_failures") if isinstance(verifier, Mapping) else None
        if (
            not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or not 1 <= attempts <= VERIFIER_ATTEMPTS
            or not isinstance(failures, list)
            or len(failures) != attempts - 1
        ):
            _fail("assignment_lifecycle_invalid")
        scored_separate += 1
        separate_retry_attempts += attempts - 1
    required_exec_transport_ready_terminals = (
        VERIFIER_ATTEMPTS * int(post_agent_exec_transport_errors)
    )
    minimum_ready_terminal = (
        len(rows)
        - int(zero_model_errors)
        + scored_separate
        + required_exec_transport_ready_terminals
    )
    maximum_ready_terminal = (
        len(rows) + scored_separate + separate_retry_attempts + int(post_agent_errors) * VERIFIER_ATTEMPTS
    )
    if (
        not minimum_ready_terminal <= len(ready) <= maximum_ready_terminal
        or len(abandoned) + len(recovery_failed) < required_exec_transport_ready_terminals
    ):
        _fail("assignment_lifecycle_invalid")
    result = {
        "schema_version": 1,
        "state": "passed",
        "event_log_sha256": recovery._sha256(body),
        "assignments_acquired": len(acquired),
        "assignments_ready": len(ready),
        "assignment_releases": sum(reasons.values()),
        "assignment_cancellations": cancellations,
        "release_reason_counts": dict(sorted(reasons.items())),
        "initialization_failure_status_counts": dict(sorted(initialization_statuses.items())),
        "required_error_source_initialization_failures": required_initialization_failures,
        "unattributed_initialization_failures": initialization_failures - required_initialization_failures,
        "managed_shell_recoveries": recoveries,
        "managed_shell_abandonments": len(abandoned),
        "minimum_ready_terminal": minimum_ready_terminal,
        "maximum_ready_terminal": maximum_ready_terminal,
    }
    if exec_transport_policy:
        result["required_exec_transport_ready_terminals"] = (
            required_exec_transport_ready_terminals
        )
        result["managed_shell_recovery_failures"] = len(recovery_failed)
    return result


def _post_agent_verifier_policy(trace_audit: Mapping[str, Any]) -> dict[str, Any]:
    count = trace_audit.get("post_agent_verifier_sandbox_error_zeroes")
    turns = trace_audit.get("post_agent_verifier_sandbox_error_model_io_turns")
    row_set = trace_audit.get("post_agent_verifier_sandbox_error_row_set_sha256")
    if (
        not transport._nonnegative_integer(count)
        or not transport._nonnegative_integer(turns)
        or not isinstance(row_set, str)
        or plan_module.SHA256_RE.fullmatch(row_set) is None
    ):
        _fail("post_agent_verifier_policy_invalid")
    result = {
        "schema_version": 1,
        "state": "enforced",
        "error_type": "SandboxError",
        "stop_condition": "agent_completed",
        "verifier_mode": "separate",
        "verifier_attempts": VERIFIER_ATTEMPTS,
        "provisioning_attempts_per_verifier": PROVISIONING_ATTEMPTS,
        "requires_artifact_manifest": True,
        "requires_exact_model_io_audit": True,
        "requires_assignment_lifecycle_proof": True,
        "counted_as_zero": True,
        "trainable": False,
        "rows": count,
        "model_io_turns": turns,
        "row_set_sha256": row_set,
    }
    if "post_agent_verifier_exec_transport_error_zeroes" in trace_audit:
        provisioning = trace_audit.get("post_agent_verifier_provisioning_error_zeroes")
        exec_transport = trace_audit.get("post_agent_verifier_exec_transport_error_zeroes")
        provisioning_rows = trace_audit.get(
            "post_agent_verifier_provisioning_error_row_set_sha256"
        )
        exec_transport_rows = trace_audit.get(
            "post_agent_verifier_exec_transport_error_row_set_sha256"
        )
        if (
            not transport._nonnegative_integer(provisioning)
            or not transport._nonnegative_integer(exec_transport)
            or int(provisioning) + int(exec_transport) != int(count)
            or not isinstance(provisioning_rows, str)
            or plan_module.SHA256_RE.fullmatch(provisioning_rows) is None
            or not isinstance(exec_transport_rows, str)
            or plan_module.SHA256_RE.fullmatch(exec_transport_rows) is None
        ):
            _fail("post_agent_verifier_policy_invalid")
        result.update(
            {
                "schema_version": 2,
                "stop_condition": "agent_completed-or-max_total_tokens",
                "infrastructure_zeroes": count,
                "provisioning_exhaustion_zeroes": provisioning,
                "provisioning_exhaustion_row_set_sha256": provisioning_rows,
                "exec_transport_exhaustion_zeroes": exec_transport,
                "exec_transport_exhaustion_row_set_sha256": exec_transport_rows,
                "exec_transport_attempts_per_row": VERIFIER_ATTEMPTS,
                "exec_transport_failure_messages": sorted(
                    recovery.POST_AGENT_EXEC_TRANSPORT_FAILURES
                ),
                "reward_present": False,
            }
        )
    return result


def _pre_model_sandoq_provisioning_policy(trace_audit: Mapping[str, Any]) -> dict[str, Any]:
    count = trace_audit.get("pre_model_sandoq_provisioning_error_zeroes")
    row_set = trace_audit.get("pre_model_sandoq_provisioning_error_row_set_sha256")
    if (
        not transport._nonnegative_integer(count)
        or not isinstance(row_set, str)
        or plan_module.SHA256_RE.fullmatch(row_set) is None
    ):
        _fail("pre_model_sandoq_provisioning_policy_invalid")
    return {
        "schema_version": 1,
        "state": "enforced",
        "error_type": "SandboxError",
        "stop_condition": "error",
        "phase": "agent-runtime-provisioning",
        "provisioning_attempts": PROVISIONING_ATTEMPTS,
        "requires_empty_model_trace": True,
        "requires_assignment_lifecycle_proof": True,
        "counted_as_zero": True,
        "trainable": False,
        "rows": count,
        "row_set_sha256": row_set,
    }


def _exact_length_benchmark_policy(trace_audit: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        key: trace_audit.get(key)
        for key in (
            "passes",
            "benchmark_valid_passes",
            "trainable_passes",
            "benchmark_invalid_passing_rows",
            "exact_length_nontrainable_scored_rows",
            "exact_length_nontrainable_passing_rows",
            "exact_length_nontrainable_nodes",
            "exact_length_error_zero_rows",
            "exact_length_error_zero_nodes",
        )
    }
    row_set = trace_audit.get("exact_length_nontrainable_row_set_sha256")
    error_row_set = trace_audit.get("exact_length_error_zero_row_set_sha256")
    if (
        any(not transport._nonnegative_integer(value) for value in fields.values())
        or not isinstance(row_set, str)
        or plan_module.SHA256_RE.fullmatch(row_set) is None
        or not isinstance(error_row_set, str)
        or plan_module.SHA256_RE.fullmatch(error_row_set) is None
        or fields["benchmark_invalid_passing_rows"] != 0
        or fields["benchmark_valid_passes"] != fields["passes"]
        or fields["benchmark_valid_passes"]
        != fields["trainable_passes"] + fields["exact_length_nontrainable_passing_rows"]
        or fields["exact_length_nontrainable_passing_rows"]
        > fields["exact_length_nontrainable_scored_rows"]
        or fields["exact_length_nontrainable_passing_rows"]
        != trace_audit.get("trace_invalid_passing_rows", -1)
        or fields["exact_length_nontrainable_scored_rows"]
        > trace_audit.get("trace_invalid_scored_rows", -1)
        or fields["exact_length_nontrainable_nodes"]
        < fields["exact_length_nontrainable_scored_rows"]
        or fields["exact_length_error_zero_rows"]
        > trace_audit.get("model_bearing_error_zeroes", -1)
        or fields["exact_length_error_zero_nodes"] < fields["exact_length_error_zero_rows"]
    ):
        _fail("exact_length_benchmark_policy_invalid")
    return {
        "schema_version": 1,
        "state": "enforced",
        "benchmark_finish_reason": "length",
        "requires_matching_node_and_exact_provider_finish_reason": True,
        "requires_exact_provider_json": True,
        "requires_complete_response_semantic_match": True,
        "requires_reasoning": True,
        "requires_null_tool_calls": True,
        "counted_for_benchmark_pass_at_1": True,
        "trainable": False,
        "benchmark_valid_passes": fields["benchmark_valid_passes"],
        "trainable_passes": fields["trainable_passes"],
        "nontrainable_scored_rows": fields["exact_length_nontrainable_scored_rows"],
        "nontrainable_passing_rows": fields["exact_length_nontrainable_passing_rows"],
        "nontrainable_nodes": fields["exact_length_nontrainable_nodes"],
        "nontrainable_row_set_sha256": row_set,
        "error_zero_rows_with_validated_length_stops": fields["exact_length_error_zero_rows"],
        "error_zero_nodes_with_validated_length_stops": fields["exact_length_error_zero_nodes"],
        "error_zero_row_set_sha256": error_row_set,
    }


def _exact_length_gate_met(trace_audit: Mapping[str, Any]) -> bool:
    policy = _exact_length_benchmark_policy(trace_audit)
    return int(policy["benchmark_valid_passes"]) >= TARGET_PASSES


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    supersession_source_revision: str,
    execution_contract: ExecutionContract = V8_EXECUTION_CONTRACT,
) -> dict[str, Any]:
    execution = _validated_execution_contract(execution_contract)
    if plan_sha256 != execution.plan_sha256:
        _fail("execution_plan_invalid")
    source_binding = _supersession_source_binding(
        supersession_source_revision,
        execution.supersession_source_files,
    )
    execution_semantics = transport._execution_semantics_manifest(
        execution.source_revision,
        execution.verifiers_commit,
    )
    held = split._HeldArtifactSet.create()
    try:
        plan, verified, plan_artifact = v7._verified_plan(plan_path, plan_sha256, held)
        run_dir = split._absolute_path(run_dir)
        output = run_dir / execution.output_name
        if (
            str(run_dir) != verified["output_dir"]
            or plan.get("full_output_dir") != str(run_dir / v7.OUTPUT_NAME)
            or output.exists()
            or output.is_symlink()
        ):
            _fail("output_or_run_directory_invalid")
        manifest_record = plan["source"]["manifest"]
        manifest_path = Path(str(manifest_record["path"]))
        manifest_body = split.read_regular(
            manifest_path,
            code="manifest_invalid",
            private=True,
            held=held,
        )
        if ordinary._artifact_bytes(manifest_path, manifest_body) != manifest_record:
            _fail("manifest_invalid")
        try:
            _manifest, entries = split.parse_manifest(
                manifest_body,
                str(manifest_record["sha256"]),
            )
            partition = union.derive_union_partition(entries)
        except Exception as error:
            _fail("manifest_invalid", error)
        verifier_modes = {entry.task_id: entry.verifier_mode for entry in entries}

        with ExitStack() as stack:
            evidence = split._open_held_run_evidence(run_dir)
            stack.callback(evidence.close)
            writer_lock = stack.enter_context(split._open_private_writer_lock_at(evidence.directory, ".writer.lock"))
            router_lock = stack.enter_context(
                split._open_private_writer_lock(split._router_lock_path(evidence.files["eval_run_identity.json"].body))
            )
            for lock in (writer_lock, router_lock):
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    _fail("run_active", error)

            supported = ordinary._selector_members(plan["lane"]["selector"], held)
            compose = ordinary._selector_members(plan["unsupported"]["compose"], held)
            gpu = ordinary._selector_members(plan["unsupported"]["gpu"], held)
            if (
                supported != partition.sandoq_firecracker
                or compose != partition.compose_required
                or gpu != partition.gpu_unsupported
            ):
                _fail("partition_invalid")
            identity, identity_sha256, invocation_sha256, slurm_job_id = ordinary._identity_contract(
                run_dir=run_dir,
                evidence=evidence,
                plan=plan,
                expected_revision=execution.source_revision,
                expected_verifiers_commit=execution.verifiers_commit,
                held=held,
            )
            if slurm_job_id != execution.slurm_job_id:
                _fail("run_identity_invalid")
            v7._validate_stock_identity(identity)

            results_body, results_artifact = split._read_regular_evidence(
                run_dir / RESULTS,
                code="provider_results_invalid",
                maximum_bytes=512 * 1024 * 1024,
                private=True,
                held=held,
            )
            trace_audit, rows = recovery._audit_supported_rows(
                results_body,
                supported,
                verifier_modes,
                allow_nontrainable_scored_rows=True,
                audit_error_model_io=True,
                allow_post_agent_verifier_sandbox_errors=True,
                post_agent_verifier_attempts=VERIFIER_ATTEMPTS,
                audit_pre_model_sandoq_provisioning_errors=True,
                sandoq_provisioning_attempts=PROVISIONING_ATTEMPTS,
                allow_exact_length_benchmark_rows=(
                    execution.allow_exact_length_benchmark_passes
                ),
                allow_post_agent_exec_transport_errors=(
                    execution.allow_post_agent_exec_transport_errors
                ),
            )
            try:
                cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
                    run_dir / "sandoq_cleanup_audit.json",
                    run_dir,
                    identity,
                    identity_sha256,
                    invocation_sha256,
                    slurm_job_id,
                    plan_module.SUPPORTED_TASKS,
                    plan_module.CONCURRENCY,
                    held,
                )
                event_body, _event_artifact = split._read_regular_evidence(
                    run_dir / "pool_events.jsonl",
                    code="assignment_lifecycle_invalid",
                    maximum_bytes=128 * 1024 * 1024,
                    private=True,
                    held=held,
                )
                assignment_lifecycle = _assignment_lifecycle_audit(
                    event_body,
                    expected_slurm_job_id=slurm_job_id,
                    trace_audit=trace_audit,
                    rows=rows,
                    verifier_modes=verifier_modes,
                )
                router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
                    run_dir / "direct_kimi_router_final.json",
                    identity,
                    minimum_chat_requests=plan_module.SUPPORTED_TASKS,
                    identity_sha256=identity_sha256,
                    invocation_identity_sha256=invocation_sha256,
                    held=held,
                    allow_terminal_upstream_statuses=True,
                )
            except Exception as error:
                _fail("run_audit_failed", error)
            provider_context = transport._provider_context(
                run_dir / "sandoq-provider-context.json",
                held,
            )
            proxy_audit, proxy_artifacts = transport._buffered_proxy_directory_audit(
                run_dir / "control/buffered-proxy-stats",
                expected_records=plan_module.SUPPORTED_TASKS,
                expected_schema="logical-exact-once-v1",
                held=held,
            )
            buffered_proxy_audit = transport._exact_proxy_trace_binding(
                proxy_audit,
                trace_audit,
                expected_summary_records=plan_module.SUPPORTED_TASKS,
            )
            router_transport_binding = transport._exact_router_proxy_binding(
                router_body,
                buffered_proxy_audit,
                trace_audit,
            )
            results_output = transport._merge_rows(
                entries,
                rows,
                compose,
                gpu,
                str(manifest_record["sha256"]),
            )
            passes = int(
                trace_audit[
                    "benchmark_valid_passes"
                    if execution.allow_exact_length_benchmark_passes
                    else "passes"
                ]
            )
            gate_met = (
                _exact_length_gate_met(trace_audit)
                if execution.allow_exact_length_benchmark_passes
                else transport._gate_met(trace_audit)
            )
            post_agent_policy = _post_agent_verifier_policy(trace_audit)
            pre_model_provisioning_policy = _pre_model_sandoq_provisioning_policy(trace_audit)
            post_agent_zeroes = int(trace_audit["post_agent_verifier_sandbox_error_zeroes"])
            pre_model_provisioning_zeroes = int(trace_audit["pre_model_sandoq_provisioning_error_zeroes"])
            certificate = {
                "schema_version": SCHEMA_VERSION,
                "kind": KIND,
                "state": "finalized-with-explicit-error-zeroes",
                "certification_eligible": False,
                "official_comparable": False,
                "result_label": "resource-clamped-firecracker-small-diagnostic",
                "source_revision": execution.source_revision,
                "launch_plan_sha256": plan_sha256,
                "manifest_sha256": manifest_record["sha256"],
                "eval_run_identity_sha256": identity_sha256,
                "invocation_identity_sha256": invocation_sha256,
                "source_run": {
                    "slurm_job_id": slurm_job_id,
                    "source_revision": execution.source_revision,
                    "launch_plan": plan_artifact,
                    "results": results_artifact,
                    "results_mutated": False,
                },
                "supersession": {
                    "source": source_binding,
                    "reason": execution.supersession_reason,
                    "original_full_output": plan["full_output_dir"],
                    "model_attempts_preserved": True,
                },
                "counts": {
                    "denominator": split.TOTAL_TASKS,
                    "executed": plan_module.SUPPORTED_TASKS,
                    "compose_unsupported": plan_module.COMPOSE_UNSUPPORTED_TASKS,
                    "gpu_unsupported": plan_module.GPU_UNSUPPORTED_TASKS,
                    "passes": passes,
                    "failures": split.TOTAL_TASKS - passes,
                    "execution_error_zeroes": trace_audit["execution_error_zeroes"],
                    "post_agent_verifier_sandbox_error_zeroes": post_agent_zeroes,
                    "pre_model_sandoq_provisioning_error_zeroes": pre_model_provisioning_zeroes,
                },
                "scores": {
                    "executed_pass_rate": passes / plan_module.SUPPORTED_TASKS,
                    "all_task_pass_rate": passes / split.TOTAL_TASKS,
                },
                "gate": {"target_passes": TARGET_PASSES, "met": gate_met},
                "policy": plan["contracts"],
                "execution_semantics": execution_semantics,
                "post_agent_verifier_error_policy": post_agent_policy,
                "pre_model_sandoq_provisioning_error_policy": pre_model_provisioning_policy,
                "sandoq_assignment_lifecycle": assignment_lifecycle,
                "buffered_proxy_audit": buffered_proxy_audit,
                "router_transport_binding": router_transport_binding,
                "trace_audit": trace_audit,
                "training_eligibility": {
                    "eligible_clean_scored_rows": trace_audit["clean_scored_rows"],
                    "excluded_error_rows": trace_audit["execution_error_zeroes"],
                    "excluded_post_agent_verifier_sandbox_error_rows": post_agent_zeroes,
                    "excluded_pre_model_sandoq_provisioning_error_rows": pre_model_provisioning_zeroes,
                    "excluded_trace_invalid_scored_rows": trace_audit["trace_invalid_scored_rows"],
                    "excluded_unsupported_rows": (
                        plan_module.COMPOSE_UNSUPPORTED_TASKS + plan_module.GPU_UNSUPPORTED_TASKS
                    ),
                    "error_rows_are_trainable": False,
                    "post_agent_verifier_sandbox_error_rows_are_trainable": False,
                    "pre_model_sandoq_provisioning_error_rows_are_trainable": False,
                    "trace_invalid_scored_rows_are_trainable": False,
                },
                "zero_model_recovery": {
                    "state": "not_attempted",
                    "eligible_rows": trace_audit["zero_model_error_zeroes"],
                    "recovered_rows": 0,
                    "source_row_set_sha256": trace_audit["zero_model_row_set_sha256"],
                    "model_attempts_preserved": True,
                    "requires_new_versioned_supersession_for_recovered_rows": True,
                },
                "cleanup": cleanup,
                "provider_context": provider_context,
                "router_receipt_sha256": recovery._sha256(router_body),
                "artifacts": {
                    "executed_results": results_artifact,
                    "buffered_proxy_summary_records": proxy_artifacts,
                    "router_receipt": router_artifact,
                    "router_receipt_commit": router_marker,
                    **cleanup_artifacts,
                },
                "results_sha256": recovery._sha256(results_output),
            }
            if execution.allow_exact_length_benchmark_passes:
                certificate["counts"].update(
                    {
                        "provider_scored_passes": trace_audit["passes"],
                        "benchmark_scored_rows": trace_audit["scored_rows"],
                        "benchmark_scored_failures": trace_audit["scored_failures"],
                        "trainable_passes": trace_audit["trainable_passes"],
                        "benchmark_valid_nontrainable_passes": trace_audit[
                            "exact_length_nontrainable_passing_rows"
                        ],
                        "infrastructure_zeroes": trace_audit["execution_error_zeroes"],
                        "post_agent_verifier_exec_transport_zeroes": trace_audit[
                            "post_agent_verifier_exec_transport_error_zeroes"
                        ],
                    }
                )
                certificate["training_eligibility"]["eligible_clean_passes"] = (
                    trace_audit["trainable_passes"]
                )
                certificate["exact_length_benchmark_policy"] = (
                    _exact_length_benchmark_policy(trace_audit)
                )
            evidence.revalidate()
            held.revalidate()
            split._publish_private_bundle(
                output,
                {RESULTS: results_output, CERTIFICATE: split.canonical_json(certificate)},
            )
            evidence.revalidate()
            held.revalidate()
    finally:
        held.close()
    return {
        "state": "finalized-with-explicit-error-zeroes",
        "denominator": split.TOTAL_TASKS,
        "passes": passes,
        "failures": split.TOTAL_TASKS - passes,
        "execution_error_zeroes": trace_audit["execution_error_zeroes"],
        "post_agent_verifier_sandbox_error_zeroes": post_agent_zeroes,
        "pre_model_sandoq_provisioning_error_zeroes": pre_model_provisioning_zeroes,
        "gate_met": gate_met,
        "all_task_pass_rate": passes / split.TOTAL_TASKS,
        "certification_eligible": False,
        "results_sha256": recovery._sha256(results_output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--supersession-source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            supersession_source_revision=args.supersession_source_revision,
        )
    except (OSError, RuntimeError, ValueError):
        print(
            '{"code":"kimi_tb4_sandoq_small_v8_supersession_failed","state":"blocked"}',
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
