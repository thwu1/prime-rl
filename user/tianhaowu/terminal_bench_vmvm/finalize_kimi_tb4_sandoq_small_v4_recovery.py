#!/usr/bin/env python3
"""Truthfully supersede the immutable v4 TB4 result after its capture-contract correction."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import audit_traces
import finalize_kimi_tb4_sandoq_small_full as ordinary
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module

SCHEMA_VERSION = 1
KIND = "kimi-tb4-sandoq-small-v4-contract-recovery"
ORIGINAL_PLAN_SHA256 = "2ad797917023cca027b41d4a6d138abaefd52b38597793d11dc51981aed81ce0"
ORIGINAL_SOURCE_REVISION = "daaa4427b4a4b23359c6c4176953dff9188b07c7"
ORIGINAL_VERIFIERS_COMMIT = "d5e8b77ce20ce79b0b9ae0e5b416fffb74969b08"
ORIGINAL_SLURM_JOB_ID = "1597890"
ORIGINAL_RESPONSE_KIND = "normalized_stream_response"
CORRECTED_RESPONSE_KIND = "exact_provider_json"
ORIGINAL_BASE_CONFIG_SHA256 = "aa5737800031e79d560127cc025f5b379396767f46e81eaa0eb4f1dde02a7b08"
RESULTS = "results.jsonl"
CERTIFICATE = "certificate.json"
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
ALLOWED_ERROR_TYPES = frozenset(
    {
        "HarnessError",
        "InterceptionError",
        "ProviderError",
        "SandboxError",
        "TasksetError",
        "ToolsetError",
        "TunnelError",
        "UserError",
    }
)
POST_AGENT_VERIFIER_ARTIFACT_KEYS = frozenset({"bytes", "captured", "collect", "missing", "sha256"})
POST_AGENT_VERIFIER_PERSISTED_ARTIFACT_KEYS = POST_AGENT_VERIFIER_ARTIFACT_KEYS | {"persistence"}


class V4RecoveryError(ValueError):
    """The immutable source run cannot be represented by the recovery contract."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise V4RecoveryError(code)
    raise V4RecoveryError(code) from error


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _legacy_contracts() -> dict[str, Any]:
    contracts = copy.deepcopy(plan_module._contracts())
    contracts["model_io_response_kind"] = ORIGINAL_RESPONSE_KIND
    contracts["verifiers_commit"] = ORIGINAL_VERIFIERS_COMMIT
    contracts.pop("verifier_runtime_retries", None)
    contracts.pop("retry_shared_verifier_scoring", None)
    contracts.pop("provisioning_retries", None)
    return contracts


def _repository_binding(expected_revision: str) -> dict[str, str]:
    if REVISION_RE.fullmatch(expected_revision or "") is None:
        _fail("recovery_source_revision_invalid")
    project = Path(__file__).resolve(strict=True).parents[3]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        _fail("recovery_source_revision_invalid", error)
    if head != expected_revision or status:
        _fail("recovery_source_revision_invalid")
    return {"project_root": str(project), "revision": head}


def _verified_legacy_plan(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if expected_sha256 != ORIGINAL_PLAN_SHA256:
        _fail("original_plan_invalid")
    body = split.read_regular(path, code="original_plan_invalid", private=True, held=held)
    if _sha256(body) != expected_sha256:
        _fail("original_plan_invalid")
    try:
        plan = json.loads(body)
        source = plan.get("source") if isinstance(plan, dict) else None
        base_record = source.get("base_config") if isinstance(source, dict) else None
        profile_record = source.get("provider_profile") if isinstance(source, dict) else None
        if not isinstance(base_record, dict) or not isinstance(profile_record, dict):
            _fail("original_plan_invalid")

        def legacy_base(loader_held: split._HeldArtifactSet | None):
            base_path = Path(str(base_record.get("path"))).resolve(strict=True)
            base_body = plan_module._read(
                base_path,
                code="base_config_invalid",
                held=loader_held,
            )
            if _sha256(base_body) != ORIGINAL_BASE_CONFIG_SHA256:
                _fail("original_plan_invalid")
            try:
                base = tomllib.loads(base_body.decode())
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
                _fail("original_plan_invalid", error)
            return base, base_body, base_path

        def legacy_profile(loader_held: split._HeldArtifactSet | None):
            profile_path = Path(str(profile_record.get("path"))).resolve(strict=True)
            profile_body = plan_module._read(
                profile_path,
                code="provider_profile_invalid",
                held=loader_held,
            )
            if _sha256(profile_body) != plan_module.PROVIDER_PROFILE_SHA256:
                _fail("original_plan_invalid")
            return profile_body, profile_path

        verified = plan_module._verify_with_contracts(
            path,
            expected_sha256,
            expected_contracts=_legacy_contracts(),
            base_loader=legacy_base,
            provider_profile_loader=legacy_profile,
            require_smoke_format_attestation=False,
            held=held,
            body=body,
        )
    except Exception as error:
        _fail("original_plan_invalid", error)
    if not isinstance(plan, dict):
        _fail("original_plan_invalid")
    return plan, verified, {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _valid_error_objects(errors: object) -> tuple[str, ...]:
    if not isinstance(errors, list) or not errors:
        _fail("error_row_invalid")
    types: list[str] = []
    for error in errors:
        error_type = error.get("type") if isinstance(error, dict) else None
        if (
            not isinstance(error, dict)
            or error_type not in ALLOWED_ERROR_TYPES
            or not isinstance(error.get("message"), str)
            or not error["message"]
            or (error_type == "ProviderError" and set(error) != {"message", "type"})
            or (
                error_type != "ProviderError"
                and (set(error) != {"message", "traceback", "type"} or not isinstance(error.get("traceback"), str))
            )
        ):
            _fail("error_row_invalid")
        types.append(error_type)
    return tuple(types)


def _model_turns(row: Mapping[str, Any]) -> int:
    nodes = row.get("nodes")
    if not isinstance(nodes, list):
        _fail("provider_trace_audit_failed")
    return sum(node.get("sampled") is True for node in nodes if isinstance(node, dict))


def _derived_error_zero(row: Mapping[str, Any], *, zero_model: bool) -> dict[str, Any]:
    derived = copy.deepcopy(dict(row))
    source_sha256 = _sha256(split.canonical_json(row))
    info = derived.get("info")
    if not isinstance(info, dict):
        _fail("error_row_invalid")
    derived["rewards"] = {"solved": 0}
    derived["info"] = {
        **info,
        "diagnostic_evaluation_disposition": {
            "kind": "execution-error-counted-as-zero",
            "source_row_sha256": source_sha256,
            "trainable": False,
            "zero_model": zero_model,
        },
    }
    return derived


def _post_agent_verifier_sandbox_error(
    row: Mapping[str, Any],
    *,
    verifier_mode: str,
    verifier_attempts: int,
    provisioning_attempts: int,
    require_persisted_artifacts: bool = False,
) -> bool:
    """Recognize the source-bound error emitted after a separate verifier exhausts."""

    task = row.get("task")
    task_name = task.get("name") if isinstance(task, Mapping) else None
    errors = row.get("errors")
    info = row.get("info")
    artifacts = info.get("terminal_bench_artifacts") if isinstance(info, Mapping) else None
    if (
        verifier_mode != "separate"
        or not isinstance(verifier_attempts, int)
        or isinstance(verifier_attempts, bool)
        or verifier_attempts < 1
        or not isinstance(provisioning_attempts, int)
        or isinstance(provisioning_attempts, bool)
        or provisioning_attempts < 1
        or row.get("stop_condition") != "agent_completed"
        or row.get("rewards") != {}
        or row.get("metrics") != {}
        or not isinstance(task_name, str)
        or not task_name
        or not isinstance(errors, list)
        or len(errors) != 1
        or not isinstance(info, Mapping)
        or set(info) != {"terminal_bench_artifacts"}
        or not _valid_post_agent_artifacts(
            artifacts,
            require_persistence=require_persisted_artifacts,
        )
    ):
        return False
    error = errors[0]
    message = error.get("message") if isinstance(error, Mapping) else None
    traceback = error.get("traceback") if isinstance(error, Mapping) else None
    attempt_detail = "; ".join(
        f"attempt {attempt}: Sandoq provisioning failed after {provisioning_attempts} attempts"
        for attempt in range(1, verifier_attempts + 1)
    )
    expected_message = f"{task_name}: verifier VMVM failed after {verifier_attempts} attempts: {attempt_detail}"
    if (
        not isinstance(error, Mapping)
        or set(error) != {"message", "traceback", "type"}
        or error.get("type") != "SandboxError"
        or not isinstance(message, str)
        or message != expected_message
        or not isinstance(traceback, str)
        or not traceback
        or "in _score_separate" not in traceback
        or "in solved" not in traceback
        or "raise SandboxError" not in traceback
    ):
        return False
    return True


def _valid_post_agent_artifacts(
    artifacts: object,
    *,
    require_persistence: bool = False,
) -> bool:
    expected_keys = (
        POST_AGENT_VERIFIER_PERSISTED_ARTIFACT_KEYS if require_persistence else POST_AGENT_VERIFIER_ARTIFACT_KEYS
    )
    if not isinstance(artifacts, Mapping) or set(artifacts) != expected_keys:
        return False
    artifact_bytes = artifacts.get("bytes")
    artifact_sha256 = artifacts.get("sha256")
    captured = artifacts.get("captured")
    missing = artifacts.get("missing")
    collect = artifacts.get("collect")
    return (
        isinstance(artifact_bytes, int)
        and not isinstance(artifact_bytes, bool)
        and artifact_bytes > 0
        and isinstance(artifact_sha256, str)
        and SHA256_RE.fullmatch(artifact_sha256) is not None
        and isinstance(captured, Mapping)
        and all(
            isinstance(service, str)
            and service
            and isinstance(paths, list)
            and all(isinstance(path, str) and path.startswith("/") for path in paths)
            for service, paths in captured.items()
        )
        and isinstance(missing, list)
        and all(
            isinstance(entry, Mapping)
            and set(entry) == {"service", "source"}
            and isinstance(entry.get("service"), str)
            and bool(entry["service"])
            and isinstance(entry.get("source"), str)
            and bool(entry["source"])
            for entry in missing
        )
        and isinstance(collect, list)
        and all(
            isinstance(entry, Mapping)
            and set(entry) == {"attempts", "exit_code", "output_tail", "service"}
            and isinstance(entry.get("attempts"), int)
            and not isinstance(entry["attempts"], bool)
            and entry["attempts"] >= 1
            and isinstance(entry.get("exit_code"), int)
            and not isinstance(entry["exit_code"], bool)
            and isinstance(entry.get("output_tail"), str)
            and isinstance(entry.get("service"), str)
            and bool(entry["service"])
            for entry in collect
        )
    )


POST_AGENT_EXEC_TRANSPORT_FAILURES = frozenset(
    {
        (
            "OCI runner persistent shell exec had an uncertain transport failure: "
            "Sandoq HTTP transport failed during POST request (ServerDisconnectedError); "
            "assignment is poisoned and the command was not replayed"
        ),
        (
            "OCI runner persistent shell exec crossed the proxy deadline with HTTP 504 "
            "and an unknown outcome; assignment is poisoned and the command was not replayed"
        ),
    }
)


def _post_agent_verifier_exec_transport_error(
    row: Mapping[str, Any],
    *,
    verifier_mode: str,
    verifier_attempts: int,
    require_persisted_artifacts: bool = False,
) -> bool:
    """Recognize only the witnessed non-replay verifier exec exhaustion."""

    task = row.get("task")
    task_name = task.get("name") if isinstance(task, Mapping) else None
    errors = row.get("errors")
    info = row.get("info")
    artifacts = info.get("terminal_bench_artifacts") if isinstance(info, Mapping) else None
    if (
        verifier_mode != "separate"
        or verifier_attempts != 3
        or row.get("stop_condition") not in {"agent_completed", "max_total_tokens"}
        or row.get("rewards") != {}
        or row.get("metrics") != {}
        or not isinstance(task_name, str)
        or not task_name
        or not isinstance(errors, list)
        or len(errors) != 1
        or not isinstance(info, Mapping)
        or set(info) != {"terminal_bench_artifacts"}
        or not _valid_post_agent_artifacts(
            artifacts,
            require_persistence=require_persisted_artifacts,
        )
    ):
        return False
    error = errors[0]
    message = error.get("message") if isinstance(error, Mapping) else None
    traceback = error.get("traceback") if isinstance(error, Mapping) else None
    prefix = f"{task_name}: verifier VMVM failed after {verifier_attempts} attempts: "
    if (
        not isinstance(error, Mapping)
        or set(error) != {"message", "traceback", "type"}
        or error.get("type") != "SandboxError"
        or not isinstance(message, str)
        or not message.startswith(prefix)
        or not isinstance(traceback, str)
        or not traceback
        or "in _score_separate" not in traceback
        or "in solved" not in traceback
        or "in run" not in traceback
        or "Sandoq exec failed" not in traceback
        or "raise SandboxError" not in traceback
    ):
        return False
    remaining = message[len(prefix) :]
    for attempt in range(1, verifier_attempts + 1):
        attempt_prefix = f"attempt {attempt}: Sandoq exec failed: "
        if not remaining.startswith(attempt_prefix):
            return False
        remaining = remaining[len(attempt_prefix) :]
        matched = next(
            (
                detail
                for detail in POST_AGENT_EXEC_TRANSPORT_FAILURES
                if remaining == detail or remaining.startswith(f"{detail}; attempt {attempt + 1}: ")
            ),
            None,
        )
        if matched is None:
            return False
        remaining = remaining[len(matched) :]
        if attempt < verifier_attempts:
            separator = f"; attempt {attempt + 1}: "
            if not remaining.startswith(separator):
                return False
            remaining = f"attempt {attempt + 1}: {remaining[len(separator) :]}"
    return remaining == ""


POST_AGENT_ARTIFACT_WRITE_PATH = "/tmp/terminal-bench-artifacts-0.tgz"
POST_AGENT_ARTIFACT_WRITE_TRANSPORT_DETAIL = (
    "OCI runner blocking exec had an uncertain transport failure: "
    "Sandoq HTTP transport failed during POST request (ServerDisconnectedError); "
    "assignment is poisoned and the command was not replayed"
)
POST_AGENT_ARTIFACT_WRITE_HTTP_500_DETAIL = (
    "HTTP 500: {'error': 'Internal Server Error', "
    "'message': 'exec failed: failed to run command: fork/exec /usr/bin/bash: "
    "argument list too long', 'code': 500}"
)


def _post_agent_verifier_artifact_write_transport_error(
    row: Mapping[str, Any],
    *,
    verifier_mode: str,
    verifier_attempts: int,
    execution_project_root: str,
) -> bool:
    """Recognize only the witnessed persisted-artifact write exhaustion."""

    task = row.get("task")
    task_name = task.get("name") if isinstance(task, Mapping) else None
    errors = row.get("errors")
    info = row.get("info")
    artifacts = info.get("terminal_bench_artifacts") if isinstance(info, Mapping) else None
    if (
        verifier_mode != "separate"
        or verifier_attempts != 3
        or row.get("stop_condition") != "agent_completed"
        or row.get("rewards") != {}
        or row.get("metrics") != {}
        or not isinstance(task_name, str)
        or not task_name
        or not isinstance(errors, list)
        or len(errors) != 1
        or not isinstance(info, Mapping)
        or set(info) != {"terminal_bench_artifacts"}
        or not _valid_post_agent_artifacts(artifacts, require_persistence=True)
        or not isinstance(execution_project_root, str)
        or not execution_project_root.startswith("/")
        or execution_project_root.endswith("/")
    ):
        return False
    error = errors[0]
    message = error.get("message") if isinstance(error, Mapping) else None
    traceback = error.get("traceback") if isinstance(error, Mapping) else None
    write_prefix = f"write '{POST_AGENT_ARTIFACT_WRITE_PATH}': "
    prefix = f"{task_name}: verifier VMVM failed after 3 attempts: attempt 1: {write_prefix}"
    attempt_2 = f"; attempt 2: {write_prefix}{POST_AGENT_ARTIFACT_WRITE_TRANSPORT_DETAIL}; attempt 3: {write_prefix}"
    if (
        not isinstance(error, Mapping)
        or set(error) != {"message", "traceback", "type"}
        or error.get("type") != "SandboxError"
        or not isinstance(message, str)
        or not message.startswith(prefix)
        or message.count(attempt_2) != 1
        or not isinstance(traceback, str)
        or not traceback.endswith(f"verifiers.v1.errors.SandboxError: {message}\n")
    ):
        return False
    first, third = message[len(prefix) :].split(attempt_2)
    http_500 = re.compile(
        r"OCI runner /v1/exec failed on assignment-([0-9a-f]{32}): "
        + re.escape(POST_AGENT_ARTIFACT_WRITE_HTTP_500_DETAIL)
        + r"\Z"
    )
    first_match = http_500.fullmatch(first)
    third_match = http_500.fullmatch(third)
    expected_frames = (
        f'File "{execution_project_root}/deps/verifiers/verifiers/v1/rollout.py"',
        "in run\n",
        f'File "{execution_project_root}/deps/verifiers/verifiers/v1/taskset.py"',
        "in score\n",
        (f'File "{execution_project_root}/user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py"'),
        "in solved\n",
        "in _score_separate\n",
        "raise SandboxError(\n",
    )
    return (
        first_match is not None
        and third_match is not None
        and first_match.group(1) != third_match.group(1)
        and all(frame in traceback for frame in expected_frames)
    )


def _pre_model_sandoq_provisioning_error(
    row: Mapping[str, Any],
    *,
    provisioning_attempts: int,
) -> bool:
    """Recognize the exact fail-closed Sandoq start exhaustion before model I/O."""

    errors = row.get("errors")
    if (
        not isinstance(provisioning_attempts, int)
        or isinstance(provisioning_attempts, bool)
        or provisioning_attempts < 1
        or row.get("stop_condition") != "error"
        or row.get("nodes") != []
        or row.get("rewards") != {}
        or row.get("metrics") != {}
        or row.get("info") != {}
        or not isinstance(errors, list)
        or len(errors) != 1
    ):
        return False
    error = errors[0]
    traceback = error.get("traceback") if isinstance(error, Mapping) else None
    return (
        isinstance(error, Mapping)
        and set(error) == {"message", "traceback", "type"}
        and error.get("type") == "SandboxError"
        and error.get("message") == f"Sandoq provisioning failed after {provisioning_attempts} attempts"
        and isinstance(traceback, str)
        and bool(traceback)
        and "verifiers/v1/runtimes/sandoq.py" in traceback
        and "in start" in traceback
        and "raise SandboxError(" in traceback
    )


def _derived_post_agent_verifier_error_zero(
    row: Mapping[str, Any],
    *,
    infrastructure_class: str | None = None,
) -> dict[str, Any]:
    derived = _derived_error_zero(row, zero_model=False)
    disposition = derived["info"]["diagnostic_evaluation_disposition"]
    disposition.update(
        {
            "kind": "post-agent-verifier-error-counted-as-zero",
            "phase": "separate-verifier",
        }
    )
    if infrastructure_class is not None:
        disposition["infrastructure_class"] = infrastructure_class
    return derived


def _derived_pre_model_sandoq_provisioning_error_zero(row: Mapping[str, Any]) -> dict[str, Any]:
    derived = _derived_error_zero(row, zero_model=True)
    disposition = derived["info"]["diagnostic_evaluation_disposition"]
    disposition.update(
        {
            "kind": "pre-model-sandoq-provisioning-error-counted-as-zero",
            "phase": "agent-runtime-provisioning",
        }
    )
    return derived


def _derived_trace_invalid_score(
    row: Mapping[str, Any],
    *,
    problems: Sequence[str],
) -> dict[str, Any]:
    derived = copy.deepcopy(dict(row))
    source_sha256 = _sha256(split.canonical_json(row))
    info = derived.get("info")
    if not isinstance(info, dict) or not problems:
        _fail("provider_trace_audit_failed")
    derived["info"] = {
        **info,
        "diagnostic_evaluation_disposition": {
            "kind": "score-retained-trace-excluded",
            "source_row_sha256": source_sha256,
            "audit_problem_set_sha256": _sha256(split.canonical_json(sorted(set(problems)))),
            "trainable": False,
        },
    }
    return derived


def _audit_supported_rows(
    body: bytes,
    expected_members: Sequence[str],
    verifier_modes: Mapping[str, str],
    *,
    allow_nontrainable_scored_rows: bool = False,
    audit_error_model_io: bool = False,
    allow_post_agent_verifier_sandbox_errors: bool = False,
    post_agent_verifier_attempts: int | None = None,
    audit_pre_model_sandoq_provisioning_errors: bool = False,
    sandoq_provisioning_attempts: int | None = None,
    allow_exact_length_benchmark_rows: bool = False,
    allow_post_agent_exec_transport_errors: bool = False,
    allow_post_agent_artifact_write_transport_errors: bool = False,
    require_persisted_verifier_artifacts: bool = False,
    execution_project_root: str | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if allow_post_agent_exec_transport_errors and (
        not audit_error_model_io or not allow_post_agent_verifier_sandbox_errors or post_agent_verifier_attempts != 3
    ):
        _fail("post_agent_verifier_policy_invalid")
    if allow_post_agent_artifact_write_transport_errors and (
        not audit_error_model_io
        or not allow_post_agent_verifier_sandbox_errors
        or not require_persisted_verifier_artifacts
        or post_agent_verifier_attempts != 3
        or not isinstance(execution_project_root, str)
        or not execution_project_root.startswith("/")
    ):
        _fail("post_agent_verifier_policy_invalid")
    if allow_post_agent_verifier_sandbox_errors and (
        not isinstance(post_agent_verifier_attempts, int)
        or isinstance(post_agent_verifier_attempts, bool)
        or post_agent_verifier_attempts < 1
        or not isinstance(sandoq_provisioning_attempts, int)
        or isinstance(sandoq_provisioning_attempts, bool)
        or sandoq_provisioning_attempts < 1
    ):
        _fail("post_agent_verifier_policy_invalid")
    if audit_pre_model_sandoq_provisioning_errors and (
        not isinstance(sandoq_provisioning_attempts, int)
        or isinstance(sandoq_provisioning_attempts, bool)
        or sandoq_provisioning_attempts < 1
    ):
        _fail("pre_model_sandoq_provisioning_policy_invalid")
    try:
        rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("provider_results_invalid", error)
    expected = set(expected_members)
    if len(rows) != len(expected_members) or any(not isinstance(row, dict) for row in rows):
        _fail("provider_results_invalid")

    by_task: dict[str, dict[str, Any]] = {}
    trace_ids: set[str] = set()
    passes = 0
    clean_rows = 0
    trace_invalid_scored_rows = 0
    trace_invalid_passing_rows = 0
    exact_length_nontrainable_scored_rows = 0
    exact_length_nontrainable_passing_rows = 0
    exact_length_nontrainable_nodes = 0
    exact_length_error_zero_rows = 0
    exact_length_error_zero_nodes = 0
    clean_model_turns = 0
    source_model_io_turns = 0
    validated_error_model_io_turns = 0
    clean_sampled_tokens = 0
    zero_model_errors = 0
    model_bearing_errors = 0
    zero_model_provider_errors = 0
    model_bearing_provider_errors = 0
    post_agent_verifier_sandbox_errors = 0
    post_agent_verifier_provisioning_errors = 0
    post_agent_verifier_exec_transport_errors = 0
    post_agent_verifier_artifact_write_transport_errors = 0
    post_agent_verifier_sandbox_error_model_io_turns = 0
    pre_model_sandoq_provisioning_errors = 0
    error_types: Counter[str] = Counter()
    zero_model_row_hashes: list[str] = []
    error_row_hashes: list[str] = []
    post_agent_verifier_sandbox_error_hashes: list[str] = []
    post_agent_verifier_provisioning_error_hashes: list[str] = []
    post_agent_verifier_exec_transport_error_hashes: list[str] = []
    post_agent_verifier_artifact_write_transport_error_hashes: list[str] = []
    pre_model_sandoq_provisioning_error_hashes: list[str] = []
    trace_invalid_row_hashes: list[str] = []
    exact_length_nontrainable_row_hashes: list[str] = []
    exact_length_error_zero_row_hashes: list[str] = []
    trace_problem_counts: Counter[str] = Counter()
    observations: Counter[str] = Counter()

    for row in rows:
        try:
            task_id = split._task_slug(row)
        except Exception as error:
            _fail("provider_trace_audit_failed", error)
        trace_id = row.get("id")
        if (
            task_id not in expected
            or task_id in by_task
            or not isinstance(trace_id, str)
            or not trace_id
            or trace_id in trace_ids
            or row.get("is_completed") is not True
            or not isinstance(row.get("stop_condition"), str)
            or not row["stop_condition"].strip()
        ):
            _fail("provider_trace_audit_failed")
        trace_ids.add(trace_id)
        turns = _model_turns(row)
        source_model_io_turns += turns

        errors = row.get("errors")
        if errors:
            row_error_types = _valid_error_objects(errors)
            for error_type in row_error_types:
                error_types[error_type] += 1
            post_agent_verifier_provisioning_error = (
                audit_error_model_io
                and turns > 0
                and row_error_types == ("SandboxError",)
                and allow_post_agent_verifier_sandbox_errors
                and _post_agent_verifier_sandbox_error(
                    row,
                    verifier_mode=verifier_modes[task_id],
                    verifier_attempts=int(post_agent_verifier_attempts),
                    provisioning_attempts=int(sandoq_provisioning_attempts),
                    require_persisted_artifacts=require_persisted_verifier_artifacts,
                )
            )
            post_agent_verifier_exec_transport_error = (
                audit_error_model_io
                and turns > 0
                and row_error_types == ("SandboxError",)
                and allow_post_agent_exec_transport_errors
                and _post_agent_verifier_exec_transport_error(
                    row,
                    verifier_mode=verifier_modes[task_id],
                    verifier_attempts=int(post_agent_verifier_attempts),
                    require_persisted_artifacts=require_persisted_verifier_artifacts,
                )
            )
            post_agent_verifier_artifact_write_transport_error = (
                audit_error_model_io
                and turns > 0
                and row_error_types == ("SandboxError",)
                and allow_post_agent_artifact_write_transport_errors
                and _post_agent_verifier_artifact_write_transport_error(
                    row,
                    verifier_mode=verifier_modes[task_id],
                    verifier_attempts=int(post_agent_verifier_attempts),
                    execution_project_root=str(execution_project_root),
                )
            )
            post_agent_verifier_sandbox_error = (
                post_agent_verifier_provisioning_error
                or post_agent_verifier_exec_transport_error
                or post_agent_verifier_artifact_write_transport_error
            )
            if audit_error_model_io:
                if not post_agent_verifier_sandbox_error and (
                    row.get("stop_condition") != "error" or len(row_error_types) != 1
                ):
                    _fail("error_row_invalid")
                if (
                    turns > 0
                    and not post_agent_verifier_sandbox_error
                    and row_error_types
                    not in {
                        ("ProviderError",),
                        ("HarnessError",),
                    }
                ):
                    _fail("model_bearing_error_row_invalid")
            if row.get("rewards") != {} or row.get("metrics") != {}:
                _fail("error_row_invalid")
            zero_model = turns == 0
            if zero_model:
                if row.get("nodes") != [] or row.get("info") != {}:
                    _fail("zero_model_error_row_invalid")
                pre_model_sandoq_provisioning_error = row_error_types == ("SandboxError",) and (
                    audit_pre_model_sandoq_provisioning_errors
                    and _pre_model_sandoq_provisioning_error(
                        row,
                        provisioning_attempts=int(sandoq_provisioning_attempts),
                    )
                )
                if (
                    audit_pre_model_sandoq_provisioning_errors
                    and row_error_types == ("SandboxError",)
                    and not pre_model_sandoq_provisioning_error
                ):
                    _fail("pre_model_sandoq_provisioning_error_invalid")
                zero_model_errors += 1
                zero_model_provider_errors += int(row_error_types == ("ProviderError",))
                zero_model_row_hashes.append(_sha256(split.canonical_json(row)))
                if pre_model_sandoq_provisioning_error:
                    pre_model_sandoq_provisioning_errors += 1
                    pre_model_sandoq_provisioning_error_hashes.append(_sha256(split.canonical_json(row)))
            else:
                if audit_error_model_io:
                    error_problems = audit_traces._audit_trace(
                        row,
                        require_reasoning=True,
                        max_sequence_tokens=split.MAX_SEQUENCE_TOKENS,
                        require_token_data=False,
                        require_logprobs=False,
                        require_model_io=True,
                        model_io_contract=audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
                        require_request_graph_match=True,
                        observations=observations,
                        require_exact_provider_json=True,
                        require_clean_stop=False,
                    )
                    length_problems = [problem for problem in error_problems if problem != "trace_has_errors"]
                    length_nodes = (
                        audit_traces._exact_length_termination_nodes(
                            row,
                            length_problems,
                            audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
                        )
                        if allow_exact_length_benchmark_rows and length_problems
                        else None
                    )
                    if error_problems.count("trace_has_errors") != 1 or (length_problems and length_nodes is None):
                        _fail("error_row_model_io_audit_failed")
                    if length_nodes is not None:
                        exact_length_error_zero_rows += 1
                        exact_length_error_zero_nodes += len(length_nodes)
                        exact_length_error_zero_row_hashes.append(_sha256(split.canonical_json(row)))
                    validated_error_model_io_turns += turns
                model_bearing_errors += 1
                model_bearing_provider_errors += int(row_error_types == ("ProviderError",))
                if post_agent_verifier_sandbox_error:
                    post_agent_verifier_sandbox_errors += 1
                    post_agent_verifier_sandbox_error_model_io_turns += turns
                    post_agent_verifier_sandbox_error_hashes.append(_sha256(split.canonical_json(row)))
                    if post_agent_verifier_provisioning_error:
                        post_agent_verifier_provisioning_errors += 1
                        post_agent_verifier_provisioning_error_hashes.append(_sha256(split.canonical_json(row)))
                    if post_agent_verifier_exec_transport_error:
                        post_agent_verifier_exec_transport_errors += 1
                        post_agent_verifier_exec_transport_error_hashes.append(_sha256(split.canonical_json(row)))
                    if post_agent_verifier_artifact_write_transport_error:
                        post_agent_verifier_artifact_write_transport_errors += 1
                        post_agent_verifier_artifact_write_transport_error_hashes.append(
                            _sha256(split.canonical_json(row))
                        )
            error_row_hashes.append(_sha256(split.canonical_json(row)))
            if post_agent_verifier_sandbox_error:
                by_task[task_id] = _derived_post_agent_verifier_error_zero(
                    row,
                    infrastructure_class=(
                        "separate-verifier-artifact-write-transport-exhausted"
                        if post_agent_verifier_artifact_write_transport_error
                        else (
                            "separate-verifier-exec-transport-exhausted"
                            if post_agent_verifier_exec_transport_error
                            else (
                                "separate-verifier-provisioning-exhausted"
                                if allow_post_agent_exec_transport_errors
                                or allow_post_agent_artifact_write_transport_errors
                                else None
                            )
                        )
                    ),
                )
            elif zero_model and pre_model_sandoq_provisioning_error:
                by_task[task_id] = _derived_pre_model_sandoq_provisioning_error_zero(row)
            else:
                by_task[task_id] = _derived_error_zero(row, zero_model=zero_model)
            continue

        if errors != []:
            _fail("provider_trace_audit_failed")
        info = row.get("info")
        verifier = info.get("terminal_bench_verifier") if isinstance(info, dict) else None
        if not isinstance(verifier, dict) or verifier.get("mode") != verifier_modes[task_id]:
            _fail("provider_trace_audit_failed")
        problems = audit_traces._audit_trace(
            row,
            require_reasoning=True,
            max_sequence_tokens=split.MAX_SEQUENCE_TOKENS,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            model_io_contract=audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            observations=observations,
            require_exact_provider_json=True,
            require_clean_stop=True,
        )
        exact_length_nodes = (
            audit_traces._exact_length_termination_nodes(
                row,
                problems,
                audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
            )
            if allow_exact_length_benchmark_rows and problems
            else None
        )
        score = split._score(row)
        if problems:
            if allow_exact_length_benchmark_rows:
                if score == 1 and exact_length_nodes is None:
                    _fail("provider_trace_audit_failed")
                if score == 0 and exact_length_nodes is None and not allow_nontrainable_scored_rows:
                    _fail("provider_trace_audit_failed")
            elif not allow_nontrainable_scored_rows:
                _fail("provider_trace_audit_failed")
        passes += score
        if problems:
            trace_invalid_scored_rows += 1
            trace_invalid_passing_rows += score
            source_sha256 = _sha256(split.canonical_json(row))
            trace_invalid_row_hashes.append(source_sha256)
            trace_problem_counts.update(re.sub(r"^node_[0-9]+_", "node_*_", problem) for problem in problems)
            if exact_length_nodes is not None:
                exact_length_nontrainable_scored_rows += 1
                exact_length_nontrainable_passing_rows += score
                exact_length_nontrainable_nodes += len(exact_length_nodes)
                exact_length_nontrainable_row_hashes.append(source_sha256)
            by_task[task_id] = _derived_trace_invalid_score(row, problems=problems)
            continue
        clean_rows += 1
        nodes = row["nodes"]
        clean_model_turns += sum(
            node.get("sampled") is True and node.get("model_io") is not None for node in nodes if isinstance(node, dict)
        )
        for node in nodes:
            if not isinstance(node, dict) or node.get("sampled") is not True:
                continue
            response = node.get("model_io", {}).get("response")
            if not isinstance(response, dict) or response.get("kind") != CORRECTED_RESPONSE_KIND:
                _fail("provider_trace_audit_failed")
            usage = node.get("usage")
            completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
            if isinstance(completion, bool) or not isinstance(completion, int) or completion < 0:
                _fail("provider_trace_audit_failed")
            clean_sampled_tokens += completion
        by_task[task_id] = row

    if set(
        by_task
    ) != expected or clean_rows + trace_invalid_scored_rows + zero_model_errors + model_bearing_errors != len(rows):
        _fail("provider_results_invalid")
    summary = {
        "source_rows": len(rows),
        "clean_scored_rows": clean_rows,
        "passes": passes,
        "scored_rows": clean_rows + trace_invalid_scored_rows,
        "scored_failures": clean_rows + trace_invalid_scored_rows - passes,
        "trace_invalid_scored_rows": trace_invalid_scored_rows,
        "trace_invalid_passing_rows": trace_invalid_passing_rows,
        "trace_invalid_problem_counts": dict(sorted(trace_problem_counts.items())),
        "trace_invalid_row_set_sha256": _sha256(split.canonical_json(sorted(trace_invalid_row_hashes))),
        "execution_error_zeroes": zero_model_errors + model_bearing_errors,
        "zero_model_error_zeroes": zero_model_errors,
        "model_bearing_error_zeroes": model_bearing_errors,
        "provider_error_zeroes": zero_model_provider_errors + model_bearing_provider_errors,
        "zero_model_provider_error_zeroes": zero_model_provider_errors,
        "model_bearing_provider_error_zeroes": model_bearing_provider_errors,
        "clean_model_io_turns": clean_model_turns,
        "source_model_io_turns": source_model_io_turns,
        "validated_error_model_io_turns": validated_error_model_io_turns,
        "error_model_io_audit_required": audit_error_model_io,
        "clean_sampled_tokens": clean_sampled_tokens,
        "clean_trace_failures": 0,
        "exact_provider_json_required": True,
        "request_graph_match_required": True,
        "reasoning_required": True,
        "provider_explicit_empty_reasoning_tool_turns": observations["provider_explicit_empty_reasoning_tool_turns"],
        "provider_reported_zero_reasoning_tool_turns": observations["provider_reported_zero_reasoning_tool_turns"],
        "error_type_counts": dict(sorted(error_types.items())),
        "error_row_set_sha256": _sha256(split.canonical_json(sorted(error_row_hashes))),
        "zero_model_row_set_sha256": _sha256(split.canonical_json(sorted(zero_model_row_hashes))),
    }
    if allow_post_agent_verifier_sandbox_errors:
        summary.update(
            {
                "post_agent_verifier_sandbox_error_zeroes": post_agent_verifier_sandbox_errors,
                "post_agent_verifier_sandbox_error_model_io_turns": (post_agent_verifier_sandbox_error_model_io_turns),
                "post_agent_verifier_sandbox_error_row_set_sha256": _sha256(
                    split.canonical_json(sorted(post_agent_verifier_sandbox_error_hashes))
                ),
            }
        )
    if audit_pre_model_sandoq_provisioning_errors:
        summary.update(
            {
                "pre_model_sandoq_provisioning_error_zeroes": pre_model_sandoq_provisioning_errors,
                "pre_model_sandoq_provisioning_error_row_set_sha256": _sha256(
                    split.canonical_json(sorted(pre_model_sandoq_provisioning_error_hashes))
                ),
            }
        )
    if allow_exact_length_benchmark_rows:
        benchmark_invalid_passing_rows = trace_invalid_passing_rows - exact_length_nontrainable_passing_rows
        summary.update(
            {
                "benchmark_valid_passes": passes - benchmark_invalid_passing_rows,
                "trainable_passes": passes - trace_invalid_passing_rows,
                "benchmark_invalid_passing_rows": benchmark_invalid_passing_rows,
                "exact_length_nontrainable_scored_rows": exact_length_nontrainable_scored_rows,
                "exact_length_nontrainable_passing_rows": exact_length_nontrainable_passing_rows,
                "exact_length_nontrainable_nodes": exact_length_nontrainable_nodes,
                "exact_length_nontrainable_row_set_sha256": _sha256(
                    split.canonical_json(sorted(exact_length_nontrainable_row_hashes))
                ),
                "exact_length_error_zero_rows": exact_length_error_zero_rows,
                "exact_length_error_zero_nodes": exact_length_error_zero_nodes,
                "exact_length_error_zero_row_set_sha256": _sha256(
                    split.canonical_json(sorted(exact_length_error_zero_row_hashes))
                ),
            }
        )
    if allow_post_agent_exec_transport_errors or allow_post_agent_artifact_write_transport_errors:
        if (
            post_agent_verifier_sandbox_errors
            != post_agent_verifier_provisioning_errors
            + post_agent_verifier_exec_transport_errors
            + post_agent_verifier_artifact_write_transport_errors
        ):
            _fail("post_agent_verifier_policy_invalid")
        summary.update(
            {
                "post_agent_verifier_provisioning_error_zeroes": (post_agent_verifier_provisioning_errors),
                "post_agent_verifier_provisioning_error_row_set_sha256": _sha256(
                    split.canonical_json(sorted(post_agent_verifier_provisioning_error_hashes))
                ),
                "post_agent_verifier_exec_transport_error_zeroes": (post_agent_verifier_exec_transport_errors),
                "post_agent_verifier_exec_transport_error_row_set_sha256": _sha256(
                    split.canonical_json(sorted(post_agent_verifier_exec_transport_error_hashes))
                ),
            }
        )
        if allow_post_agent_artifact_write_transport_errors:
            summary.update(
                {
                    "post_agent_verifier_artifact_write_transport_error_zeroes": (
                        post_agent_verifier_artifact_write_transport_errors
                    ),
                    "post_agent_verifier_artifact_write_transport_error_row_set_sha256": _sha256(
                        split.canonical_json(sorted(post_agent_verifier_artifact_write_transport_error_hashes))
                    ),
                }
            )
    return summary, by_task


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    output: Path,
    recovery_source_revision: str,
) -> dict[str, Any]:
    source_binding = _repository_binding(recovery_source_revision)
    held = split._HeldArtifactSet.create()
    try:
        plan, verified, plan_artifact = _verified_legacy_plan(plan_path, plan_sha256, held)
        run_dir = split._absolute_path(run_dir)
        output = split._absolute_path(output)
        if str(run_dir) != verified["output_dir"] or output.exists() or output.is_symlink():
            _fail("output_or_run_directory_invalid")
        manifest_record = plan["source"]["manifest"]
        manifest_path = Path(manifest_record["path"])
        manifest_body = split.read_regular(
            manifest_path,
            code="manifest_invalid",
            private=True,
            held=held,
        )
        if ordinary._artifact_bytes(manifest_path, manifest_body) != manifest_record:
            _fail("manifest_invalid")
        try:
            _manifest, entries = split.parse_manifest(manifest_body, manifest_record["sha256"])
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
                expected_revision=ORIGINAL_SOURCE_REVISION,
                expected_verifiers_commit=ORIGINAL_VERIFIERS_COMMIT,
                held=held,
            )
            if slurm_job_id != ORIGINAL_SLURM_JOB_ID:
                _fail("run_identity_invalid")

            results_body, results_artifact = split._read_regular_evidence(
                run_dir / RESULTS,
                code="provider_results_invalid",
                maximum_bytes=512 * 1024 * 1024,
                private=True,
                held=held,
            )
            trace_audit, rows = _audit_supported_rows(results_body, supported, verifier_modes)
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
                router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
                    run_dir / "direct_kimi_router_final.json",
                    identity,
                    minimum_chat_requests=plan_module.SUPPORTED_TASKS,
                    identity_sha256=identity_sha256,
                    invocation_identity_sha256=invocation_sha256,
                    held=held,
                )
            except Exception as error:
                _fail("run_audit_failed", error)
            provider_context = ordinary._provider_context(run_dir / "sandoq-provider-context.json", held)

            merged: list[dict[str, Any]] = []
            trace_ids: set[str] = set()
            compose_set = set(compose)
            gpu_set = set(gpu)
            for entry in entries:
                if entry.task_id in rows:
                    row = rows[entry.task_id]
                elif entry.task_id in compose_set:
                    row = ordinary._unsupported_row(entry.task_id, manifest_record["sha256"], "compose")
                elif entry.task_id in gpu_set:
                    row = ordinary._unsupported_row(entry.task_id, manifest_record["sha256"], "gpu")
                else:
                    _fail("coverage_invalid")
                trace_id = row.get("id")
                if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
                    _fail("trace_identity_invalid")
                trace_ids.add(trace_id)
                merged.append(row)
            if len(merged) != split.TOTAL_TASKS:
                _fail("coverage_invalid")

            results_output = b"".join(split.canonical_json(row) for row in merged)
            passes = int(trace_audit["passes"])
            certificate = {
                "schema_version": SCHEMA_VERSION,
                "kind": KIND,
                "state": "finalized-with-explicit-error-zeroes",
                "certification_eligible": False,
                "official_comparable": False,
                "result_label": "resource-clamped-firecracker-small-diagnostic",
                "source_run": {
                    "slurm_job_id": ORIGINAL_SLURM_JOB_ID,
                    "source_revision": ORIGINAL_SOURCE_REVISION,
                    "launch_plan": plan_artifact,
                    "results": results_artifact,
                    "eval_run_identity_sha256": identity_sha256,
                    "invocation_identity_sha256": invocation_sha256,
                },
                "contract_supersession": {
                    "recovery_source": source_binding,
                    "original_declared_response_kind": ORIGINAL_RESPONSE_KIND,
                    "observed_and_required_response_kind": CORRECTED_RESPONSE_KIND,
                    "reason": "buffered-sandoq-nonstream-provider-boundary",
                    "source_results_mutated": False,
                },
                "counts": {
                    "denominator": split.TOTAL_TASKS,
                    "executed": plan_module.SUPPORTED_TASKS,
                    "compose_unsupported": plan_module.COMPOSE_UNSUPPORTED_TASKS,
                    "gpu_unsupported": plan_module.GPU_UNSUPPORTED_TASKS,
                    "passes": passes,
                    "failures": split.TOTAL_TASKS - passes,
                    "execution_error_zeroes": trace_audit["execution_error_zeroes"],
                },
                "scores": {
                    "executed_pass_rate": passes / plan_module.SUPPORTED_TASKS,
                    "all_task_pass_rate": passes / split.TOTAL_TASKS,
                },
                "trace_audit": trace_audit,
                "training_eligibility": {
                    "eligible_clean_scored_rows": trace_audit["clean_scored_rows"],
                    "excluded_error_rows": trace_audit["execution_error_zeroes"],
                    "error_rows_are_trainable": False,
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
                "router_receipt_sha256": _sha256(router_body),
                "artifacts": {
                    "router_receipt": router_artifact,
                    "router_receipt_commit": router_marker,
                    **cleanup_artifacts,
                },
                "results_sha256": _sha256(results_output),
            }
            files = {RESULTS: results_output, CERTIFICATE: split.canonical_json(certificate)}
            evidence.revalidate()
            held.revalidate()
            split._publish_private_bundle(output, files)
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
        "all_task_pass_rate": passes / split.TOTAL_TASKS,
        "certification_eligible": False,
        "results_sha256": _sha256(results_output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recovery-source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            output=args.output,
            recovery_source_revision=args.recovery_source_revision,
        )
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_tb4_sandoq_small_v4_recovery_failed","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
