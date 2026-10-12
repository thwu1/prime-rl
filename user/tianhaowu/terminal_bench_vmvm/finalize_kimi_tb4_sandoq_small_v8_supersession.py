#!/usr/bin/env python3
"""Finalize the immutable Kimi TB4 v8 run with verifier-failure zeroes."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import eval_run_identity as identity_module
import finalize_kimi_tb4_sandoq_small_full as ordinary
import finalize_kimi_tb4_sandoq_small_v4_recovery as recovery
import finalize_kimi_tb4_sandoq_small_v6_supersession as transport
import finalize_kimi_tb4_sandoq_small_v7 as v7
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module
from terminal_bench_vmvm import taskset as taskset_module

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
IMAGE_DIGEST_RE = re.compile(r"[^\s@]+@sha256:([0-9a-f]{64})\Z")
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
    allow_post_agent_artifact_write_transport_errors: bool = False
    plan_verifier: str = "legacy-small-full"
    execution_project_root: str | None = None
    supported_tasks: int = plan_module.SUPPORTED_TASKS
    compose_unsupported_tasks: int = plan_module.COMPOSE_UNSUPPORTED_TASKS
    gpu_unsupported_tasks: int = plan_module.GPU_UNSUPPORTED_TASKS
    concurrency: int = plan_module.CONCURRENCY
    stock_endpoint_identifier: str | None = None
    stock_source_spec_sha256: str | None = None
    stock_endpoint_bundle_sha256: str | None = None
    completion_marker_name: str | None = None
    require_persisted_verifier_artifacts: bool = False
    allow_pre_ready_managed_shell_provisioning_failures: bool = False


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
        or type(contract.allow_post_agent_artifact_write_transport_errors) is not bool
        or contract.plan_verifier not in {"legacy-small-full", "capacity-bound-v10"}
        or type(contract.supported_tasks) is not int
        or type(contract.compose_unsupported_tasks) is not int
        or type(contract.gpu_unsupported_tasks) is not int
        or type(contract.concurrency) is not int
        or contract.supported_tasks < 1
        or contract.compose_unsupported_tasks < 0
        or contract.gpu_unsupported_tasks < 0
        or contract.supported_tasks + contract.compose_unsupported_tasks + contract.gpu_unsupported_tasks
        != split.TOTAL_TASKS
        or not 1 <= contract.concurrency <= contract.supported_tasks
        or type(contract.require_persisted_verifier_artifacts) is not bool
        or type(contract.allow_pre_ready_managed_shell_provisioning_failures) is not bool
        or any(
            not isinstance(path, str)
            or not path.startswith("user/tianhaowu/terminal_bench_vmvm/")
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            for path in contract.supersession_source_files
        )
    ):
        _fail("execution_contract_invalid")
    dynamic_values = (
        contract.stock_endpoint_identifier,
        contract.stock_source_spec_sha256,
        contract.stock_endpoint_bundle_sha256,
        contract.completion_marker_name,
    )
    if contract.plan_verifier == "legacy-small-full":
        if (
            contract.execution_project_root is not None
            or any(value is not None for value in dynamic_values)
            or contract.require_persisted_verifier_artifacts
            or (
                contract.supported_tasks,
                contract.compose_unsupported_tasks,
                contract.gpu_unsupported_tasks,
                contract.concurrency,
            )
            != (
                plan_module.SUPPORTED_TASKS,
                plan_module.COMPOSE_UNSUPPORTED_TASKS,
                plan_module.GPU_UNSUPPORTED_TASKS,
                plan_module.CONCURRENCY,
            )
        ):
            _fail("execution_contract_invalid")
    else:
        project_root = (
            Path(contract.execution_project_root) if isinstance(contract.execution_project_root, str) else None
        )
        if (
            project_root is None
            or not project_root.is_absolute()
            or Path(os.path.normpath(project_root)) != project_root
            or not isinstance(contract.stock_endpoint_identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", contract.stock_endpoint_identifier)
            or not isinstance(contract.stock_source_spec_sha256, str)
            or plan_module.SHA256_RE.fullmatch(contract.stock_source_spec_sha256) is None
            or not isinstance(contract.stock_endpoint_bundle_sha256, str)
            or plan_module.SHA256_RE.fullmatch(contract.stock_endpoint_bundle_sha256) is None
            or contract.completion_marker_name != "v10_execution_completion.json"
            or not contract.require_persisted_verifier_artifacts
        ):
            _fail("execution_contract_invalid")
    if contract.allow_post_agent_artifact_write_transport_errors and (
        contract.plan_verifier != "capacity-bound-v10"
        or not contract.require_persisted_verifier_artifacts
        or contract.execution_project_root is None
    ):
        _fail("execution_contract_invalid")
    if contract.allow_pre_ready_managed_shell_provisioning_failures and (
        contract.plan_verifier != "capacity-bound-v10"
        or not contract.require_persisted_verifier_artifacts
        or contract.execution_project_root is None
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


def _verified_execution_plan(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet,
    execution: ExecutionContract,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if execution.plan_verifier == "legacy-small-full":
        return v7._verified_plan(path, expected_sha256, held)
    body = split.read_regular(path, code="plan_invalid", private=True, held=held)
    if recovery._sha256(body) != expected_sha256:
        _fail("plan_invalid")
    project = Path(str(execution.execution_project_root))
    workflow = project / "user/tianhaowu/terminal_bench_vmvm"
    verifier = workflow / "prepare_kimi_tb4_sandoq_small_v10_run.py"
    try:
        revision = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(project), "status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        execution_paths = (
            workflow,
            project / "environments/vmvm_tb_v2",
            project / "deps/verifiers",
            project / "deps/renderers",
            project / "deps/pydantic-config/src",
        )
        inherited = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = ":".join(
            [*(str(item) for item in execution_paths), *([inherited] if inherited else [])]
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(verifier),
                "verify",
                "--plan",
                str(path),
                "--plan-sha256",
                expected_sha256,
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=300,
        )
        value = json.loads(body)
        verified = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("plan_invalid", error)
    if (
        revision != execution.source_revision
        or status
        or not verifier.is_file()
        or completed.returncode != 0
        or completed.stderr
        or len(completed.stdout.encode()) > 64 * 1024
        or not isinstance(value, dict)
        or not isinstance(verified, dict)
        or verified.get("source_revision") != execution.source_revision
        or verified.get("count") != execution.supported_tasks
        or verified.get("concurrency") != execution.concurrency
    ):
        _fail("plan_invalid")
    return value, verified, ordinary._artifact_bytes(path, body)


def _validate_execution_stock_identity(
    identity: Mapping[str, Any],
    execution: ExecutionContract,
) -> None:
    if execution.stock_endpoint_identifier is None:
        v7._validate_stock_identity(identity)
        return
    deployment = identity.get("deployment")
    router = deployment.get("router") if isinstance(deployment, Mapping) else None
    if (
        not isinstance(deployment, Mapping)
        or not isinstance(router, Mapping)
        or deployment.get("spec_sha256") != execution.stock_source_spec_sha256
        or deployment.get("endpoint_bundle_sha256") != execution.stock_endpoint_bundle_sha256
        or router.get("policy") != "consistent_hash"
        or router.get("capacity_profile") != "sandoq-stock-single-c64-v1"
        or router.get("endpoint_identifier") != execution.stock_endpoint_identifier
        or router.get("worker_count") != 1
        or router.get("provider_concurrency") != 64
        or router.get("per_worker_capacity") != 64
    ):
        _fail("stock_identity_invalid")


def _execution_identity_contract(
    *,
    run_dir: Path,
    evidence: split._HeldRunEvidence,
    plan: Mapping[str, Any],
    execution: ExecutionContract,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], str, str, str]:
    if execution.plan_verifier == "legacy-small-full":
        return ordinary._identity_contract(
            run_dir=run_dir,
            evidence=evidence,
            plan=plan,
            expected_revision=execution.source_revision,
            expected_verifiers_commit=execution.verifiers_commit,
            held=held,
        )
    try:
        envelope = identity_module.load_eval_run_identity_bytes(
            evidence.files["eval_run_identity.json"].body,
            run_dir=run_dir,
            verify_references=True,
            verify_saved_provenance=False,
        )
        identity = envelope["identity"]
        identity_sha256 = envelope["eval_run_identity_sha256"]
        invocation_sha256, slurm_job_id = split._run_invocation_binding(
            evidence.files["eval_invocations.jsonl"].body,
            evidence.files["provenance.txt"].body,
            identity_sha256,
            expected_role="kimi-direct-tb4-small-diagnostic",
        )
    except Exception as error:
        _fail("run_identity_invalid", error)
    source = identity.get("source")
    config = identity.get("config")
    inputs = identity.get("inputs")
    runtime_execution = identity.get("execution")
    runtime = runtime_execution.get("runtime") if isinstance(runtime_execution, dict) else None
    environment = runtime_execution.get("sandoq_environment") if isinstance(runtime_execution, dict) else None
    deployment = identity.get("deployment")
    router = deployment.get("router") if isinstance(deployment, dict) else None
    contract = identity.get("contract")
    harness = contract.get("harness") if isinstance(contract, dict) else None
    lane = plan.get("lane")
    if (
        identity.get("role") != identity_module.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE
        or not isinstance(source, dict)
        or source.get("sandbox_provider") != "sandoq"
        or source.get("prime_rl_commit") != execution.source_revision
        or source.get("verifiers_commit") != execution.verifiers_commit
        or not isinstance(config, dict)
        or not isinstance(lane, dict)
        or config.get("source", {}).get("sha256") != lane.get("config", {}).get("sha256")
        or not isinstance(inputs, dict)
        or inputs.get("task_file", {}).get("sha256") != lane.get("selector", {}).get("sha256")
        or inputs.get("task_file", {}).get("count") != execution.supported_tasks
        or not isinstance(runtime_execution, dict)
        or any(
            runtime_execution.get(key) != execution.concurrency
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or runtime_execution.get("cleanup_must_succeed") is not True
        or not isinstance(runtime, dict)
        or runtime.get("type") != "sandoq"
        or runtime.get("expected_environment") != identity_module.KIMI_SMALL_FIRECRACKER_ENVIRONMENT
        or runtime.get("session_timeout") != identity_module.KIMI_TB4_EXTENDED_SESSION_TIMEOUT_SECONDS
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("buffered_chat_completions") is not True
        or not isinstance(environment, dict)
        or environment.get("environment") != identity_module.KIMI_SMALL_FIRECRACKER_ENVIRONMENT
        or environment.get("provider_profile_sha256") != plan_module.PROVIDER_PROFILE_SHA256
        or environment.get("task_network") != "public"
        or environment.get("provider_task_network") != "host"
        or environment.get("pool_size") != execution.concurrency
        or not isinstance(deployment, dict)
        or not isinstance(router, dict)
        or router.get("retries") != 0
        or not isinstance(contract, dict)
        or contract.get("model") != "Kimi-K3"
        or harness
        != {
            "id": "mini-swe-agent",
            "version": "2.4.6",
            "placement": "sandbox",
            "step_limit": 200,
            "request_timeout_seconds": 144_000,
            "request_max_retries": 0,
            "guest_transport_retry_attempts": 10,
            "logical_request_upstream_attempts": 1,
        }
    ):
        _fail("run_identity_invalid")
    _validate_execution_stock_identity(identity, execution)
    return identity, identity_sha256, invocation_sha256, slurm_job_id


def _execution_completion_audit(
    run_dir: Path,
    execution: ExecutionContract,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if execution.completion_marker_name is None:
        return None
    body, artifact = split._read_regular_evidence(
        run_dir / execution.completion_marker_name,
        code="execution_completion_invalid",
        maximum_bytes=64 * 1024,
        private=True,
        held=held,
    )
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("execution_completion_invalid", error)
    expected = {
        "execution_revision": execution.source_revision,
        "job_id": execution.slurm_job_id,
        "plan_sha256": execution.plan_sha256,
        "stage": "tb4-miniswe246-sandoq-small-v10-c16",
        "state": "completed-awaiting-v11-certification",
    }
    if value != expected or body != split.canonical_json(expected):
        _fail("execution_completion_invalid")
    return expected, artifact


def _persisted_verifier_artifact_audit(
    results_body: bytes,
    run_dir: Path,
) -> dict[str, Any]:
    try:
        rows = [json.loads(line) for line in results_body.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("persisted_verifier_artifacts_invalid", error)
    trace_hashes: list[str] = []
    aggregate_hashes: list[str] = []
    payload_count = 0
    total_bytes = 0
    required_rows = 0
    persisted_rows = 0
    for row in rows:
        trace_id = row.get("id") if isinstance(row, dict) else None
        info = row.get("info") if isinstance(row, dict) else None
        metadata = info.get("terminal_bench_artifacts") if isinstance(info, dict) else None
        rewards = row.get("rewards") if isinstance(row, dict) else None
        required = (
            (
                isinstance(rewards, dict)
                and "solved" in rewards
                or row.get("stop_condition") in {"agent_completed", "max_total_tokens"}
            )
            if isinstance(row, dict)
            else False
        )
        required_rows += int(required)
        if metadata is None:
            if required:
                _fail("persisted_verifier_artifacts_missing")
            continue
        if not isinstance(trace_id, str) or not trace_id or not isinstance(metadata, dict):
            _fail("persisted_verifier_artifacts_invalid")
        try:
            payloads, manifest = taskset_module.load_persisted_verifier_artifacts_from_metadata(
                run_dir,
                trace_id,
                metadata,
            )
        except (OSError, RuntimeError, ValueError) as error:
            _fail("persisted_verifier_artifacts_invalid", error)
        aggregate = manifest.get("aggregate") if isinstance(manifest, dict) else None
        if not payloads or not isinstance(aggregate, dict):
            _fail("persisted_verifier_artifacts_invalid")
        persisted_rows += 1
        payload_count += len(payloads)
        total_bytes += sum(len(payload) for payload in payloads.values())
        trace_hashes.append(recovery._sha256(trace_id.encode()))
        aggregate_hashes.append(str(aggregate.get("sha256", "")))
    if persisted_rows < required_rows:
        _fail("persisted_verifier_artifacts_missing")
    return {
        "schema_version": 1,
        "state": "reopened-and-verified",
        "rows": persisted_rows,
        "required_rows": required_rows,
        "payloads": payload_count,
        "bytes": total_bytes,
        "trace_set_sha256": recovery._sha256("".join(f"{value}\n" for value in sorted(trace_hashes)).encode()),
        "aggregate_set_sha256": recovery._sha256("".join(f"{value}\n" for value in sorted(aggregate_hashes)).encode()),
    }


def _immutable_image_digest(value: object) -> str:
    match = IMAGE_DIGEST_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        _fail("assignment_lifecycle_image_binding_invalid")
    return match.group(1)


def _validated_task_images(
    plan: Mapping[str, Any],
    held: split._HeldArtifactSet,
) -> dict[str, dict[str, str]]:
    source = plan.get("source")
    record = source.get("image_manifest") if isinstance(source, Mapping) else None
    if not isinstance(record, Mapping) or set(record) != {"path", "bytes", "sha256"}:
        _fail("assignment_lifecycle_image_binding_invalid")
    path = Path(str(record.get("path", "")))
    body = split.read_regular(
        path,
        code="assignment_lifecycle_image_binding_invalid",
        private=False,
        held=held,
    )
    if ordinary._artifact_bytes(path, body) != record:
        _fail("assignment_lifecycle_image_binding_invalid")
    try:
        raw = union._json(body, code="assignment_lifecycle_image_binding_invalid")
        images = raw.get("images", raw)
        if not isinstance(images, dict):
            raise ValueError("image_manifest_invalid")
        normalized: dict[str, dict[str, str]] = {}
        for task_id, entry in images.items():
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("image_manifest_invalid")
            if isinstance(entry, str):
                normalized[task_id] = {"agent": entry}
            elif (
                isinstance(entry, dict)
                and entry
                and all(
                    isinstance(role, str) and bool(role) and isinstance(reference, str) and bool(reference)
                    for role, reference in entry.items()
                )
            ):
                normalized[task_id] = dict(entry)
            else:
                raise ValueError("image_manifest_invalid")
        return normalized
    except (RuntimeError, ValueError) as error:
        _fail("assignment_lifecycle_image_binding_invalid", error)


def _pre_model_provisioning_image_requirements(
    rows: Mapping[str, Mapping[str, Any]],
    task_images: Mapping[str, Mapping[str, str]],
    expected_rows: int,
) -> tuple[Counter[str], frozenset[str]]:
    pre_model_rows_by_agent_image: Counter[str] = Counter()
    selected_agent_images: Counter[str] = Counter()
    selected_verifier_images: Counter[str] = Counter()
    observed_rows = 0
    for task_id, row in rows.items():
        image_entry = task_images.get(task_id)
        if not isinstance(image_entry, Mapping) or set(image_entry) != {"agent", "verifier"}:
            _fail("assignment_lifecycle_image_binding_invalid")
        agent_digest = _immutable_image_digest(image_entry.get("agent"))
        verifier_digest = _immutable_image_digest(image_entry.get("verifier"))
        selected_agent_images[agent_digest] += 1
        selected_verifier_images[verifier_digest] += 1
        info = row.get("info")
        disposition = info.get("diagnostic_evaluation_disposition") if isinstance(info, Mapping) else None
        if (
            not isinstance(disposition, Mapping)
            or disposition.get("kind") != "pre-model-sandoq-provisioning-error-counted-as-zero"
        ):
            continue
        pre_model_rows_by_agent_image[agent_digest] += 1
        observed_rows += 1
    if observed_rows != expected_rows or any(
        selected_agent_images[digest] != rows_for_digest or selected_verifier_images[digest] != 0
        for digest, rows_for_digest in pre_model_rows_by_agent_image.items()
    ):
        _fail("assignment_lifecycle_image_binding_invalid")
    return (
        Counter(
            {
                digest: rows_for_digest * PROVISIONING_ATTEMPTS
                for digest, rows_for_digest in pre_model_rows_by_agent_image.items()
            }
        ),
        frozenset(selected_agent_images) | frozenset(selected_verifier_images),
    )


def _assignment_lifecycle_audit(
    body: bytes,
    *,
    expected_slurm_job_id: str,
    trace_audit: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    verifier_modes: Mapping[str, str],
    allow_pre_ready_managed_shell_provisioning_failures: bool = False,
    task_images: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    if (
        not body
        or not body.endswith(b"\n")
        or b"\r" in body
        or type(allow_pre_ready_managed_shell_provisioning_failures) is not bool
        or (allow_pre_ready_managed_shell_provisioning_failures and not isinstance(task_images, Mapping))
        or (not allow_pre_ready_managed_shell_provisioning_failures and task_images is not None)
    ):
        _fail("assignment_lifecycle_invalid")
    acquired: dict[str, dict[str, Any]] = {}
    ready: set[str] = set()
    terminal: set[str] = set()
    abandoned: set[str] = set()
    recovery_failed: set[str] = set()
    pre_ready_recovery_failed: set[str] = set()
    initialization_by_image: Counter[str] = Counter()
    pre_ready_loss_by_image: Counter[str] = Counter()
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
            acquired[assignment_id] = {
                "ready": False,
                "terminal": False,
                "requested_image": event.get("requested_image"),
            }
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
                or assignment_id not in acquired
                or assignment_id in terminal
                or assignment_id in recovery_failed
                or event.get("error_type") != "RuntimeError"
                or (assignment_id not in ready and not allow_pre_ready_managed_shell_provisioning_failures)
            ):
                _fail("assignment_lifecycle_invalid")
            recovery_failed.add(assignment_id)
            if assignment_id not in ready:
                pre_ready_recovery_failed.add(assignment_id)
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
                if allow_pre_ready_managed_shell_provisioning_failures:
                    initialization_by_image[
                        _immutable_image_digest(acquired[assignment_id].get("requested_image"))
                    ] += 1
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
                    assignment_id in (ready | pre_ready_recovery_failed)
                    and assignment_id in (abandoned | recovery_failed)
                    and event.get("status") == "poisoned"
                    and event.get("poisoned") is True
                    and event.get("nested_recycle_verified") is False
                    and event.get("outer_deletion_verified_http_status") == 404
                    and event.get("shell_failure_status") == expected_shell_status
                    and isinstance(event.get("error"), str)
                    and bool(event["error"])
                )
                if valid and assignment_id in pre_ready_recovery_failed:
                    pre_ready_loss_by_image[
                        _immutable_image_digest(acquired[assignment_id].get("requested_image"))
                    ] += 1
            elif reason == "gateway_command_outcome_unknown":
                valid = (
                    assignment_id in ready
                    and assignment_id not in (abandoned | recovery_failed)
                    and event.get("status") == "poisoned"
                    and event.get("poisoned") is True
                    and event.get("nested_recycle_verified") is False
                    and event.get("outer_deletion_verified_http_status") == 404
                    and event.get("shell_failure_status") == "transport_error"
                    and event.get("outer_retired") is False
                    and event.get("shell_deleted") is False
                    and event.get("managed_shell_recovery_count") == 0
                    and event.get("cleanup_gateway_retry_count") == 0
                    and event.get("cleanup_gateway_retry_exhausted_count") == 0
                    and event.get("retirement_reason") is None
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
        or recovery_failed != {assignment_id for assignment_id in terminal if assignment_id in recovery_failed}
        or pre_ready_recovery_failed
        != {assignment_id for assignment_id in terminal if assignment_id in pre_ready_recovery_failed}
        or not abandoned.isdisjoint(recovery_failed)
        or not pre_ready_recovery_failed <= recovery_failed
        or reasons["managed_shell_lost"] != len(abandoned) + len(recovery_failed)
        or len(acquired)
        != len(ready) + reasons["initialization_failure"] + len(pre_ready_recovery_failed) + cancellations
        or len(ready)
        != reasons["rollout_complete"]
        + reasons["managed_shell_lost"]
        - len(pre_ready_recovery_failed)
        + reasons["gateway_command_outcome_unknown"]
    ):
        _fail("assignment_lifecycle_invalid")

    zero_model_errors = trace_audit.get("zero_model_error_zeroes")
    post_agent_errors = trace_audit.get("post_agent_verifier_sandbox_error_zeroes")
    exec_transport_policy = (
        "post_agent_verifier_provisioning_error_zeroes" in trace_audit
        or "post_agent_verifier_exec_transport_error_zeroes" in trace_audit
        or "post_agent_verifier_artifact_write_transport_error_zeroes" in trace_audit
    )
    post_agent_provisioning_errors = trace_audit.get(
        "post_agent_verifier_provisioning_error_zeroes",
        post_agent_errors,
    )
    post_agent_exec_transport_errors = trace_audit.get(
        "post_agent_verifier_exec_transport_error_zeroes",
        0,
    )
    post_agent_artifact_write_transport_errors = trace_audit.get(
        "post_agent_verifier_artifact_write_transport_error_zeroes",
        0,
    )
    pre_model_provisioning_errors = trace_audit.get("pre_model_sandoq_provisioning_error_zeroes")
    if (
        not transport._nonnegative_integer(zero_model_errors)
        or not transport._nonnegative_integer(post_agent_errors)
        or not transport._nonnegative_integer(post_agent_provisioning_errors)
        or not transport._nonnegative_integer(post_agent_exec_transport_errors)
        or not transport._nonnegative_integer(post_agent_artifact_write_transport_errors)
        or int(post_agent_errors)
        != int(post_agent_provisioning_errors)
        + int(post_agent_exec_transport_errors)
        + int(post_agent_artifact_write_transport_errors)
        or not transport._nonnegative_integer(pre_model_provisioning_errors)
        or int(pre_model_provisioning_errors) > int(zero_model_errors)
        or (not exec_transport_policy and recovery_failed)
        or reasons["gateway_command_outcome_unknown"] != int(post_agent_artifact_write_transport_errors)
    ):
        _fail("assignment_lifecycle_invalid")
    required_pre_model_attempts = PROVISIONING_ATTEMPTS * int(pre_model_provisioning_errors)
    required_post_agent_initialization_failures = (
        PROVISIONING_ATTEMPTS * VERIFIER_ATTEMPTS * int(post_agent_provisioning_errors)
    )
    initialization_failures = reasons["initialization_failure"]
    attributed_pre_model_initialization_failures = required_pre_model_attempts
    pre_model_image_set_sha256: str | None = None
    if allow_pre_ready_managed_shell_provisioning_failures:
        assert task_images is not None
        required_by_image, selected_image_digests = _pre_model_provisioning_image_requirements(
            rows,
            task_images,
            int(pre_model_provisioning_errors),
        )
        if (
            not set(initialization_by_image) <= selected_image_digests
            or not set(pre_ready_loss_by_image) <= set(required_by_image)
            or any(
                initialization_by_image[digest] + pre_ready_loss_by_image[digest] != required
                for digest, required in required_by_image.items()
            )
        ):
            _fail("assignment_lifecycle_image_binding_invalid")
        attributed_pre_model_initialization_failures = sum(
            initialization_by_image[digest] for digest in required_by_image
        )
        pre_model_image_set_sha256 = recovery._sha256(
            split.canonical_json(
                [
                    {
                        "agent_image_sha256": digest,
                        "required_attempts": required,
                        "rows": required // PROVISIONING_ATTEMPTS,
                    }
                    for digest, required in sorted(required_by_image.items())
                ]
            )
        )
    elif pre_ready_recovery_failed:
        _fail("assignment_lifecycle_invalid")
    if (
        attributed_pre_model_initialization_failures + len(pre_ready_recovery_failed) != required_pre_model_attempts
        or initialization_failures - attributed_pre_model_initialization_failures
        < required_post_agent_initialization_failures
    ):
        _fail("assignment_lifecycle_invalid")
    required_initialization_failures = (
        attributed_pre_model_initialization_failures + required_post_agent_initialization_failures
    )
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
    required_exec_transport_ready_terminals = VERIFIER_ATTEMPTS * int(post_agent_exec_transport_errors)
    required_artifact_write_ready_terminals = VERIFIER_ATTEMPTS * int(post_agent_artifact_write_transport_errors)
    minimum_ready_terminal = (
        len(rows)
        - int(zero_model_errors)
        + scored_separate
        + required_exec_transport_ready_terminals
        + required_artifact_write_ready_terminals
    )
    maximum_ready_terminal = (
        len(rows) + scored_separate + separate_retry_attempts + int(post_agent_errors) * VERIFIER_ATTEMPTS
    )
    if (
        not minimum_ready_terminal <= len(ready) <= maximum_ready_terminal
        or len(abandoned) + len(recovery_failed) - len(pre_ready_recovery_failed)
        < required_exec_transport_ready_terminals
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
        "unattributed_initialization_failures": (
            initialization_failures
            - attributed_pre_model_initialization_failures
            - required_post_agent_initialization_failures
        ),
        "managed_shell_recoveries": recoveries,
        "managed_shell_abandonments": len(abandoned),
        "minimum_ready_terminal": minimum_ready_terminal,
        "maximum_ready_terminal": maximum_ready_terminal,
    }
    if exec_transport_policy:
        result["required_exec_transport_ready_terminals"] = required_exec_transport_ready_terminals
        result["managed_shell_recovery_failures"] = len(recovery_failed)
    if "post_agent_verifier_artifact_write_transport_error_zeroes" in trace_audit:
        result["required_artifact_write_ready_terminals"] = required_artifact_write_ready_terminals
        result["required_artifact_write_gateway_unknown_terminals"] = int(post_agent_artifact_write_transport_errors)
    if allow_pre_ready_managed_shell_provisioning_failures:
        assert pre_model_image_set_sha256 is not None
        result["pre_model_attempt_attribution"] = {
            "schema_version": 1,
            "state": "image-digest-bound",
            "rows": int(pre_model_provisioning_errors),
            "required_attempts": required_pre_model_attempts,
            "initialization_failures": attributed_pre_model_initialization_failures,
            "pre_ready_managed_shell_losses": len(pre_ready_recovery_failed),
            "pre_model_image_set_sha256": pre_model_image_set_sha256,
        }
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
        artifact_write_transport = trace_audit.get(
            "post_agent_verifier_artifact_write_transport_error_zeroes",
            0,
        )
        provisioning_rows = trace_audit.get("post_agent_verifier_provisioning_error_row_set_sha256")
        exec_transport_rows = trace_audit.get("post_agent_verifier_exec_transport_error_row_set_sha256")
        artifact_write_transport_rows = trace_audit.get(
            "post_agent_verifier_artifact_write_transport_error_row_set_sha256"
        )
        if (
            not transport._nonnegative_integer(provisioning)
            or not transport._nonnegative_integer(exec_transport)
            or not transport._nonnegative_integer(artifact_write_transport)
            or int(provisioning) + int(exec_transport) + int(artifact_write_transport) != int(count)
            or not isinstance(provisioning_rows, str)
            or plan_module.SHA256_RE.fullmatch(provisioning_rows) is None
            or not isinstance(exec_transport_rows, str)
            or plan_module.SHA256_RE.fullmatch(exec_transport_rows) is None
            or (
                "post_agent_verifier_artifact_write_transport_error_zeroes" in trace_audit
                and (
                    not isinstance(artifact_write_transport_rows, str)
                    or plan_module.SHA256_RE.fullmatch(artifact_write_transport_rows) is None
                )
            )
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
                "exec_transport_failure_messages": sorted(recovery.POST_AGENT_EXEC_TRANSPORT_FAILURES),
                "reward_present": False,
            }
        )
        if "post_agent_verifier_artifact_write_transport_error_zeroes" in trace_audit:
            result.update(
                {
                    "schema_version": 3,
                    "artifact_write_transport_exhaustion_zeroes": artifact_write_transport,
                    "artifact_write_transport_exhaustion_row_set_sha256": (artifact_write_transport_rows),
                    "artifact_write_attempts_per_row": VERIFIER_ATTEMPTS,
                    "artifact_write_path": recovery.POST_AGENT_ARTIFACT_WRITE_PATH,
                    "artifact_write_attempt_pattern": (
                        "http-500-e2big,server-disconnected-poisoned-no-replay,http-500-e2big"
                    ),
                    "requires_persisted_artifact_reopen": True,
                }
            )
    return result


def _pre_model_sandoq_provisioning_policy(
    trace_audit: Mapping[str, Any],
    *,
    allow_pre_ready_managed_shell_provisioning_failures: bool = False,
) -> dict[str, Any]:
    count = trace_audit.get("pre_model_sandoq_provisioning_error_zeroes")
    row_set = trace_audit.get("pre_model_sandoq_provisioning_error_row_set_sha256")
    if (
        type(allow_pre_ready_managed_shell_provisioning_failures) is not bool
        or not transport._nonnegative_integer(count)
        or not isinstance(row_set, str)
        or plan_module.SHA256_RE.fullmatch(row_set) is None
    ):
        _fail("pre_model_sandoq_provisioning_policy_invalid")
    result = {
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
    if allow_pre_ready_managed_shell_provisioning_failures:
        result.update(
            {
                "schema_version": 2,
                "accepted_attempt_release_classes": [
                    "initialization_failure",
                    "pre_ready_managed_shell_recovery_failed",
                ],
                "pre_ready_managed_shell_loss_requires_recovery_failed": True,
                "requires_agent_image_digest_binding": True,
                "requires_exact_attempt_count_per_row": True,
            }
        )
    return result


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
        or fields["exact_length_nontrainable_passing_rows"] > fields["exact_length_nontrainable_scored_rows"]
        or fields["exact_length_nontrainable_passing_rows"] != trace_audit.get("trace_invalid_passing_rows", -1)
        or fields["exact_length_nontrainable_scored_rows"] > trace_audit.get("trace_invalid_scored_rows", -1)
        or fields["exact_length_nontrainable_nodes"] < fields["exact_length_nontrainable_scored_rows"]
        or fields["exact_length_error_zero_rows"] > trace_audit.get("model_bearing_error_zeroes", -1)
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
        plan, verified, plan_artifact = _verified_execution_plan(
            plan_path,
            plan_sha256,
            held,
            execution,
        )
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
        task_images = (
            _validated_task_images(plan, held)
            if execution.allow_pre_ready_managed_shell_provisioning_failures
            else None
        )

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

            execution_completion = _execution_completion_audit(
                run_dir,
                execution,
                held,
            )

            supported = ordinary._selector_members(plan["lane"]["selector"], held)
            compose = ordinary._selector_members(plan["unsupported"]["compose"], held)
            gpu = ordinary._selector_members(plan["unsupported"]["gpu"], held)
            if (
                supported != partition.sandoq_firecracker
                or compose != partition.compose_required
                or gpu != partition.gpu_unsupported
            ):
                _fail("partition_invalid")
            identity, identity_sha256, invocation_sha256, slurm_job_id = _execution_identity_contract(
                run_dir=run_dir,
                evidence=evidence,
                plan=plan,
                execution=execution,
                held=held,
            )
            if slurm_job_id != execution.slurm_job_id:
                _fail("run_identity_invalid")
            _validate_execution_stock_identity(identity, execution)

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
                allow_exact_length_benchmark_rows=(execution.allow_exact_length_benchmark_passes),
                allow_post_agent_exec_transport_errors=(execution.allow_post_agent_exec_transport_errors),
                allow_post_agent_artifact_write_transport_errors=(
                    execution.allow_post_agent_artifact_write_transport_errors
                ),
                require_persisted_verifier_artifacts=(execution.require_persisted_verifier_artifacts),
                execution_project_root=execution.execution_project_root,
            )
            persisted_verifier_artifacts = (
                _persisted_verifier_artifact_audit(results_body, run_dir)
                if execution.require_persisted_verifier_artifacts
                else None
            )
            try:
                cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
                    run_dir / "sandoq_cleanup_audit.json",
                    run_dir,
                    identity,
                    identity_sha256,
                    invocation_sha256,
                    slurm_job_id,
                    execution.supported_tasks,
                    execution.concurrency,
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
                    allow_pre_ready_managed_shell_provisioning_failures=(
                        execution.allow_pre_ready_managed_shell_provisioning_failures
                    ),
                    task_images=task_images,
                )
                router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
                    run_dir / "direct_kimi_router_final.json",
                    identity,
                    minimum_chat_requests=execution.supported_tasks,
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
                expected_records=execution.supported_tasks,
                expected_schema="logical-exact-once-v1",
                held=held,
            )
            buffered_proxy_audit = transport._exact_proxy_trace_binding(
                proxy_audit,
                trace_audit,
                expected_summary_records=execution.supported_tasks,
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
                trace_audit["benchmark_valid_passes" if execution.allow_exact_length_benchmark_passes else "passes"]
            )
            gate_met = (
                _exact_length_gate_met(trace_audit)
                if execution.allow_exact_length_benchmark_passes
                else transport._gate_met(trace_audit)
            )
            post_agent_policy = _post_agent_verifier_policy(trace_audit)
            pre_model_provisioning_policy = _pre_model_sandoq_provisioning_policy(
                trace_audit,
                allow_pre_ready_managed_shell_provisioning_failures=(
                    execution.allow_pre_ready_managed_shell_provisioning_failures
                ),
            )
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
                    "executed": execution.supported_tasks,
                    "compose_unsupported": execution.compose_unsupported_tasks,
                    "gpu_unsupported": execution.gpu_unsupported_tasks,
                    "passes": passes,
                    "failures": split.TOTAL_TASKS - passes,
                    "execution_error_zeroes": trace_audit["execution_error_zeroes"],
                    "post_agent_verifier_sandbox_error_zeroes": post_agent_zeroes,
                    "pre_model_sandoq_provisioning_error_zeroes": pre_model_provisioning_zeroes,
                },
                "scores": {
                    "executed_pass_rate": passes / execution.supported_tasks,
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
                        execution.compose_unsupported_tasks + execution.gpu_unsupported_tasks
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
            if execution_completion is not None:
                completion_value, completion_artifact = execution_completion
                certificate["execution_completion"] = completion_value
                certificate["artifacts"]["execution_completion"] = completion_artifact
            if persisted_verifier_artifacts is not None:
                certificate["persisted_verifier_artifacts"] = persisted_verifier_artifacts
            if execution.allow_exact_length_benchmark_passes:
                certificate["counts"].update(
                    {
                        "provider_scored_passes": trace_audit["passes"],
                        "benchmark_scored_rows": trace_audit["scored_rows"],
                        "benchmark_scored_failures": trace_audit["scored_failures"],
                        "trainable_passes": trace_audit["trainable_passes"],
                        "benchmark_valid_nontrainable_passes": trace_audit["exact_length_nontrainable_passing_rows"],
                        "infrastructure_zeroes": trace_audit["execution_error_zeroes"],
                        "post_agent_verifier_exec_transport_zeroes": trace_audit[
                            "post_agent_verifier_exec_transport_error_zeroes"
                        ],
                    }
                )
                certificate["training_eligibility"]["eligible_clean_passes"] = trace_audit["trainable_passes"]
                certificate["exact_length_benchmark_policy"] = _exact_length_benchmark_policy(trace_audit)
            if execution.allow_post_agent_artifact_write_transport_errors:
                artifact_write_zeroes = trace_audit["post_agent_verifier_artifact_write_transport_error_zeroes"]
                certificate["counts"]["post_agent_verifier_artifact_write_transport_zeroes"] = artifact_write_zeroes
                certificate["training_eligibility"]["excluded_post_agent_verifier_artifact_write_transport_rows"] = (
                    artifact_write_zeroes
                )
                certificate["training_eligibility"][
                    "post_agent_verifier_artifact_write_transport_rows_are_trainable"
                ] = False
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
