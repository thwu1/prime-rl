#!/usr/bin/env python3
"""Build and verify a write-once, aggregate-only Mobius launch certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from audit_traces import KIMI_K3_MAX_MODEL_IO_CONTRACT, TraceJSONLError, _iter_traces
from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)
from deployment_proxy_policy import (
    KIMI_REQUEST_TIMEOUT,
    DeploymentProxyPolicyError,
    revalidate_deployment_proxy_policy,
    validate_proxy_policy_binding,
)
from eval_run_identity import (
    EvalIdentityError,
    load_eval_run_identity,
    validate_kimi_retry_contract,
    validate_kimi_steady_state_concurrency_contract,
    validate_kimi_timeout_contract,
)
from guard_success_receipt import (
    GuardReceiptError,
    load_guard_success_receipt,
    validate_eval_invocations,
    validate_guard_success_linkage,
)
from inference_route_generation import (
    RouteGenerationError,
    validate_readiness_route_generation,
    validate_route_generation,
)
from tb4_shard_workflow import (
    ShardWorkflowError,
    validate_multigen_sharded_checkpoint,
    validate_sharded_checkpoint,
)
from trace_concurrency import TraceConcurrencyError, measure_peak_active_rollouts
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    ConcurrencyTelemetryError,
    load_concurrency_telemetry_artifact,
)

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "terminal_bench_vmvm_mobius_launch_certificate"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
DEPLOYMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
MAX_METADATA_BYTES = 16 * 1024 * 1024
EXPECTED_TASKS = 2_500
EXPECTED_ORACLE_TASKS = 2_538
EXPECTED_MODEL = "Kimi-K3"
EXPECTED_CONTEXT_TOKENS = 262_144
EXPECTED_TB4_TASKS = 66
EXPECTED_TB4_SUPPORTED_TASKS = 63
EXPECTED_TB4_UNSUPPORTED_TASKS = 3
EXPECTED_TB4_MIN_PASS_RATE = 0.04
EXPECTED_TB4_MAX_PASS_RATE = 0.22
EXPECTED_TB4_ROLLOUT_CONCURRENCY = 4
EXPECTED_TB4_LEASE_START_CONCURRENCY = 2
EXPECTED_MOBIUS_LEASE_START_CONCURRENCY = 4
EXPECTED_DENYLIST = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": KIMI_K3_MAX_MODEL_IO_CONTRACT.provider_route,
    "request_model": KIMI_K3_MAX_MODEL_IO_CONTRACT.request_model,
    "response_model": KIMI_K3_MAX_MODEL_IO_CONTRACT.response_model,
    "request_reasoning_effort": KIMI_K3_MAX_MODEL_IO_CONTRACT.reasoning_effort,
    "request_chat_template_kwargs": dict(KIMI_K3_MAX_MODEL_IO_CONTRACT.chat_template_kwargs),
}
ORACLE_REASONS = frozenset({"error", "infrastructure_error", "invalid", "timeout", "unsupported", "valid"})
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
ORACLE_INVOCATION_KEYS = {
    "host",
    "invoked_at",
    "rerun_invalid",
    "resume",
    "reuse_completed_rows",
    "run_identity_sha256",
    "schema_version",
    "slurm_job_id",
    "source",
}
SOURCE_WHEEL_ORACLE_INVOCATION_KEYS = ORACLE_INVOCATION_KEYS | {
    "expected_source_wheel_attestation_sha256",
    "source_wheel_policy_sha256",
}


class LaunchCertificateError(ValueError):
    """A prerequisite cannot authorize a Mobius production launch."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_file(value: object) -> bytes:
    return (json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise LaunchCertificateError(f"{label}_sha256_invalid")
    return value


def _require_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or REVISION_RE.fullmatch(value) is None:
        raise LaunchCertificateError(f"{label}_revision_invalid")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LaunchCertificateError(f"{label}_invalid")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LaunchCertificateError(f"{label}_invalid")
    return value


def _require_rate(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise LaunchCertificateError(f"{label}_invalid")
    return float(value)


def _stable_read(path: Path, *, label: str, limit: int = MAX_METADATA_BYTES) -> tuple[Path, bytes]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            raise LaunchCertificateError(f"{label}_unreadable")
        with resolved.open("rb") as handle:
            value = handle.read(limit + 1)
        after = resolved.stat()
    except (OSError, RuntimeError) as cause:
        raise LaunchCertificateError(f"{label}_unreadable") from cause
    if len(value) > limit:
        raise LaunchCertificateError(f"{label}_too_large")
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise LaunchCertificateError(f"{label}_changed")
    return resolved, value


def _pinned_bytes(path: Path, expected_sha256: str, *, label: str) -> tuple[dict[str, str], bytes]:
    expected = _require_sha256(expected_sha256, label)
    resolved, value = _stable_read(path, label=label)
    if _sha256_bytes(value) != expected:
        raise LaunchCertificateError(f"{label}_sha256_mismatch")
    return {"path": str(resolved), "sha256": expected}, value


def _pinned_json(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    record, raw = _pinned_bytes(path, expected_sha256, label=label)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError) as cause:
        raise LaunchCertificateError(f"{label}_invalid") from cause
    if not isinstance(value, dict):
        raise LaunchCertificateError(f"{label}_invalid")
    return record, value


def _file_record(path: Path, *, label: str) -> tuple[dict[str, str], bytes]:
    resolved, raw = _stable_read(path, label=label)
    return {"path": str(resolved), "sha256": _sha256_bytes(raw)}, raw


def _stable_file_sha256(path: Path, *, label: str) -> tuple[Path, str]:
    digest = hashlib.sha256()
    try:
        resolved = path.expanduser().resolve(strict=True)
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            raise LaunchCertificateError(f"{label}_unreadable")
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = resolved.stat()
    except (OSError, RuntimeError) as cause:
        raise LaunchCertificateError(f"{label}_unreadable") from cause
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise LaunchCertificateError(f"{label}_changed")
    return resolved, digest.hexdigest()


def _record(value: object, *, label: str, keys: set[str] | None = None) -> dict[str, Any]:
    expected_keys = {"path", "sha256"} if keys is None else keys
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise LaunchCertificateError(f"{label}_record_invalid")
    path = value.get("path")
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        raise LaunchCertificateError(f"{label}_record_invalid")
    _require_sha256(value.get("sha256"), label)
    return value


def _rehash_record(value: object, *, label: str) -> tuple[dict[str, Any], Path]:
    record = _record(value, label=label)
    resolved, observed = _stable_file_sha256(Path(record["path"]), label=label)
    if observed != record["sha256"]:
        raise LaunchCertificateError(f"{label}_sha256_mismatch")
    return record, resolved


def _identity_record(identity: dict[str, Any], section: str, name: str, *, label: str) -> dict[str, Any]:
    parent = identity.get(section)
    record = parent.get(name) if isinstance(parent, dict) else None
    if not isinstance(record, dict) or not {"path", "sha256"}.issubset(record):
        raise LaunchCertificateError(f"{label}_invalid")
    return {"path": record["path"], "sha256": record["sha256"]}


def _records_match(left: dict[str, Any], right: dict[str, Any], *, label: str) -> None:
    try:
        left_path = Path(str(left.get("path"))).resolve(strict=True)
        right_path = Path(str(right.get("path"))).resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise LaunchCertificateError(f"{label}_unreadable") from cause
    if left_path != right_path or left.get("sha256") != right.get("sha256"):
        raise LaunchCertificateError(f"{label}_mismatch")


def _endpoint_binding(value: object, *, label: str) -> dict[str, Any]:
    try:
        return validate_endpoint_binding(value)
    except EndpointBindingError as cause:
        raise LaunchCertificateError(f"{label}_invalid") from cause


def _load_current_endpoint(
    proxy_info: Path,
    proxy_info_sha256: str,
    *,
    deployment_id: str,
    deployment_spec: Path,
) -> Any:
    try:
        return load_deployment_endpoint(
            proxy_info,
            deployment_id=deployment_id,
            expected_model=EXPECTED_MODEL,
            deployment_spec=deployment_spec,
            expected_proxy_info_sha256=proxy_info_sha256,
        )
    except EndpointBindingError as cause:
        raise LaunchCertificateError("deployment_endpoint_invalid") from cause


def _validate_oracle_invocations(
    raw: bytes,
    *,
    expected_run_identity_sha256: str,
    expected_source: dict[str, str],
    expected_count: int,
    expected_rerun_invalid_count: int,
    source_wheel_policy_sha256: str | None = None,
) -> None:
    if not raw or not raw.endswith(b"\n"):
        raise LaunchCertificateError("oracle_invocations_invalid")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise LaunchCertificateError("oracle_invocations_invalid") from cause
    if not lines or any(not line for line in lines):
        raise LaunchCertificateError("oracle_invocations_invalid")

    rerun_invalid_count = 0
    seen_job_ids: set[str] = set()
    previous_invoked_at: int | float | None = None
    for index, line in enumerate(lines):
        try:
            record = json.loads(
                line,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (ValueError, RecursionError) as cause:
            raise LaunchCertificateError("oracle_invocations_invalid") from cause
        expected_keys = (
            ORACLE_INVOCATION_KEYS if source_wheel_policy_sha256 is None else SOURCE_WHEEL_ORACLE_INVOCATION_KEYS
        )
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise LaunchCertificateError("oracle_invocations_invalid")
        invoked_at = record.get("invoked_at")
        host = record.get("host")
        job_id = record.get("slurm_job_id")
        resume = record.get("resume")
        rerun_invalid = record.get("rerun_invalid")
        if (
            type(record.get("schema_version")) is not int
            or record["schema_version"] != 1
            or record.get("run_identity_sha256") != expected_run_identity_sha256
            or record.get("source") != expected_source
            or (
                source_wheel_policy_sha256 is not None
                and (
                    record.get("source_wheel_policy_sha256") != source_wheel_policy_sha256
                    or (index == 0 and record.get("expected_source_wheel_attestation_sha256") is not None)
                    or (index > 0 and not isinstance(record.get("expected_source_wheel_attestation_sha256"), str))
                    or (index > 0 and SHA256_RE.fullmatch(record["expected_source_wheel_attestation_sha256"]) is None)
                )
            )
            or isinstance(invoked_at, bool)
            or not isinstance(invoked_at, (int, float))
            or not math.isfinite(invoked_at)
            or invoked_at <= 0
            or (previous_invoked_at is not None and invoked_at <= previous_invoked_at)
            or not isinstance(host, str)
            or not host
            or host.strip() != host
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in host)
            or not isinstance(job_id, str)
            or re.fullmatch(r"[1-9][0-9]*", job_id) is None
            or job_id in seen_job_ids
            or not isinstance(resume, bool)
            or resume is not (index > 0)
            or record.get("reuse_completed_rows") is not True
            or not isinstance(rerun_invalid, bool)
            or (index == 0 and rerun_invalid)
        ):
            raise LaunchCertificateError("oracle_invocations_invalid")
        previous_invoked_at = invoked_at
        seen_job_ids.add(job_id)
        rerun_invalid_count += int(rerun_invalid)

    if len(lines) != expected_count or rerun_invalid_count != expected_rerun_invalid_count or rerun_invalid_count > 1:
        raise LaunchCertificateError("oracle_invocations_count_mismatch")


def _verify_flat_self_hash(value: dict[str, Any], field: str, *, label: str) -> str:
    digest = _require_sha256(value.get(field), label)
    unsigned = dict(value)
    del unsigned[field]
    if _sha256_bytes(_canonical_json(unsigned)) != digest:
        raise LaunchCertificateError(f"{label}_self_hash_mismatch")
    return digest


def _validate_source_wheel_receipt_artifacts(
    value: object,
    *,
    oracle_dir: Path,
) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "policy",
        "attestation",
        "wheelhouses",
    }:
        raise LaunchCertificateError("oracle_source_wheel_artifacts_invalid")
    policy = value.get("policy")
    attestation = value.get("attestation")
    wheelhouses = value.get("wheelhouses")
    if (
        not isinstance(policy, dict)
        or set(policy) != {"path", "sha256"}
        or not isinstance(policy.get("path"), str)
        or not Path(policy["path"]).is_absolute()
        or not isinstance(attestation, dict)
        or set(attestation) != {"path", "sha256"}
        or attestation.get("path") != "source_wheel_attestations.json"
        or not isinstance(wheelhouses, list)
    ):
        raise LaunchCertificateError("oracle_source_wheel_artifacts_invalid")
    policy_sha256 = _require_sha256(policy.get("sha256"), "oracle_source_wheel_policy")
    attestation_sha256 = _require_sha256(
        attestation.get("sha256"),
        "oracle_source_wheel_attestation",
    )
    resolved_policy, observed_policy_sha256 = _stable_file_sha256(
        Path(policy["path"]),
        label="oracle_source_wheel_policy",
    )
    if str(resolved_policy) != policy["path"] or observed_policy_sha256 != policy_sha256:
        raise LaunchCertificateError("oracle_source_wheel_policy_mismatch")
    attestation_path = oracle_dir / attestation["path"]
    resolved_attestation, observed_attestation_sha256 = _stable_file_sha256(
        attestation_path,
        label="oracle_source_wheel_attestation",
    )
    if resolved_attestation.parent != oracle_dir or observed_attestation_sha256 != attestation_sha256:
        raise LaunchCertificateError("oracle_source_wheel_attestation_mismatch")
    observed_records: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for record in wheelhouses:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256", "size"}
            or not isinstance(record.get("path"), str)
            or re.fullmatch(r"source_wheel_cache/[0-9a-f]{64}\.tar", record["path"]) is None
            or record["path"] in seen_paths
            or isinstance(record.get("size"), bool)
            or not isinstance(record.get("size"), int)
            or record["size"] < 1
        ):
            raise LaunchCertificateError("oracle_source_wheel_artifacts_invalid")
        expected_sha256 = _require_sha256(
            record.get("sha256"),
            "oracle_source_wheel_archive",
        )
        archive_path = oracle_dir / record["path"]
        resolved_archive, observed_sha256 = _stable_file_sha256(
            archive_path,
            label="oracle_source_wheel_archive",
        )
        try:
            archive_size = resolved_archive.stat().st_size
        except OSError as cause:
            raise LaunchCertificateError("oracle_source_wheel_archive_unreadable") from cause
        if (
            resolved_archive.parent != oracle_dir / "source_wheel_cache"
            or observed_sha256 != expected_sha256
            or archive_size != record["size"]
        ):
            raise LaunchCertificateError("oracle_source_wheel_archive_mismatch")
        seen_paths.add(record["path"])
        observed_records.append(record)
    if observed_records != sorted(observed_records, key=lambda record: str(record["path"])):
        raise LaunchCertificateError("oracle_source_wheel_artifacts_invalid")
    return policy_sha256, attestation_sha256


def _project_root(path: Path) -> Path:
    for candidate in (path.parent, *path.parents):
        if (candidate / ".git").exists():
            return candidate.resolve(strict=True)
    raise LaunchCertificateError("production_config_project_root_unreadable")


def _git_output(project_root: Path, *args: str, label: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(project_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as cause:
        raise LaunchCertificateError(f"{label}_unverifiable") from cause


def _git_is_ancestor(project_root: Path, ancestor: str, descendant: str, *, label: str) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as cause:
        raise LaunchCertificateError(f"{label}_unverifiable") from cause
    if result.returncode != 0:
        raise LaunchCertificateError(f"{label}_mismatch")


def _vmvm_source_sha256(project_root: Path) -> str:
    source_root = project_root / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    try:
        paths = sorted(source_root.glob("*.py"))
    except OSError as cause:
        raise LaunchCertificateError("vmvm_source_unreadable") from cause
    if not paths:
        raise LaunchCertificateError("vmvm_source_unreadable")
    digest = hashlib.sha256()
    for path in paths:
        record, _ = _file_record(path, label="vmvm_source")
        relative = Path(record["path"]).relative_to(project_root).as_posix()
        digest.update(f"{record['sha256']}  {relative}\n".encode())
    return digest.hexdigest()


def _validate_source(project_root: Path, source: dict[str, Any]) -> dict[str, str]:
    prime_rl_commit = source["prime_rl_commit"]
    if source["prime_rl_tree_sha256"] != CLEAN_TREE_SHA256:
        raise LaunchCertificateError("oracle_source_tree_invalid")
    production_commit = _git_output(
        project_root,
        "rev-parse",
        "--verify",
        "HEAD",
        label="production_prime_rl_commit",
    ).strip()
    _require_revision(production_commit, "production_prime_rl")
    if _git_output(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        label="prime_rl_worktree",
    ).strip():
        raise LaunchCertificateError("oracle_source_worktree_not_clean")
    _git_is_ancestor(
        project_root,
        source["minimum_prime_rl_ancestor"],
        source["required_prime_rl_ancestor"],
        label="oracle_minimum_ancestor",
    )
    _git_is_ancestor(
        project_root,
        source["required_prime_rl_ancestor"],
        prime_rl_commit,
        label="oracle_required_ancestor",
    )
    _git_is_ancestor(
        project_root,
        prime_rl_commit,
        production_commit,
        label="production_oracle_ancestor",
    )
    expected_gitlink = f"160000 commit {source['verifiers_commit']}\tdeps/verifiers"
    for commit, label in (
        (prime_rl_commit, "oracle_verifiers_gitlink"),
        (production_commit, "production_verifiers_gitlink"),
    ):
        gitlink = _git_output(
            project_root,
            "ls-tree",
            commit,
            "deps/verifiers",
            label=label,
        ).strip()
        if gitlink != expected_gitlink:
            raise LaunchCertificateError(f"{label}_mismatch")
    verifiers_root = project_root / "deps/verifiers"
    if (
        _git_output(
            verifiers_root,
            "rev-parse",
            "--verify",
            "HEAD",
            label="production_verifiers_commit",
        ).strip()
        != source["verifiers_commit"]
    ):
        raise LaunchCertificateError("production_verifiers_commit_mismatch")
    if _git_output(
        verifiers_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        label="production_verifiers_worktree",
    ).strip():
        raise LaunchCertificateError("production_verifiers_worktree_not_clean")
    if _vmvm_source_sha256(project_root) != source["vmvm_tb_v2_sha256"]:
        raise LaunchCertificateError("oracle_vmvm_source_mismatch")
    return {
        "prime_rl_commit": production_commit,
        "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
        "verifiers_commit": source["verifiers_commit"],
        "vmvm_tb_v2_sha256": source["vmvm_tb_v2_sha256"],
    }


def _project_relative(path: Path, project_root: Path, *, label: str) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(project_root)
    except (OSError, RuntimeError, ValueError) as cause:
        raise LaunchCertificateError(f"{label}_outside_project") from cause
    if relative == Path("."):
        raise LaunchCertificateError(f"{label}_outside_project")
    return relative.as_posix()


def _stable_relative_record(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise LaunchCertificateError(f"{label}_record_invalid")
    path = value.get("path")
    if not isinstance(path, str) or not path:
        raise LaunchCertificateError(f"{label}_record_invalid")
    pure = PurePosixPath(path)
    if pure.is_absolute() or path != pure.as_posix() or any(part in {"", ".", ".."} for part in pure.parts):
        raise LaunchCertificateError(f"{label}_record_invalid")
    return {"path": path, "sha256": _require_sha256(value.get("sha256"), label)}


def _resolve_config_path(value: object, project_root: Path, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise LaunchCertificateError(f"{label}_invalid")
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise LaunchCertificateError(f"{label}_unreadable") from cause


def _spec_num_endpoints(raw: bytes) -> int:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as cause:
        raise LaunchCertificateError("deployment_spec_invalid") from cause
    matches = re.findall(
        r"^[ \t]*num_endpoints:[ \t]*([0-9]+)[ \t]*(?:#.*)?$",
        text,
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        raise LaunchCertificateError("deployment_spec_invalid")
    return _require_positive_int(int(matches[0]), "deployment_spec_num_endpoints")


def _validate_tb4_checkpoint(
    value: dict[str, Any],
    deployment_id: str,
    endpoint: dict[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LaunchCertificateError("tb4_checkpoint_schema_invalid")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise LaunchCertificateError("tb4_checkpoint_schema_invalid")
    if schema_version == 2 or schema_version == 3:
        try:
            validator = validate_multigen_sharded_checkpoint if schema_version == 3 else validate_sharded_checkpoint
            validated = validator(
                value,
                deployment_id=deployment_id,
                artifact_root=artifact_root,
            )
        except (OSError, ShardWorkflowError) as cause:
            raise LaunchCertificateError("tb4_sharded_checkpoint_invalid") from cause
        expected_routes = validated.get("expected_routes")
        if type(expected_routes) is not int or (
            (schema_version == 2 and expected_routes != 1)
            or (schema_version == 3 and expected_routes != 1 and expected_routes != 2)
        ):
            raise LaunchCertificateError("tb4_route_count_invalid")
        return validated
    expected_keys = {
        "artifacts",
        "audit_policy",
        "counts",
        "deployment",
        "endpoint",
        "serving_route_generation",
        "proxy_policy",
        "eval_run_identity_sha256",
        "ok",
        "schema_version",
        "scores",
        "state",
        "tb4_certificate_sha256",
    }
    if set(value) != expected_keys:
        raise LaunchCertificateError("tb4_checkpoint_schema_invalid")
    certificate_sha256 = _verify_flat_self_hash(
        value,
        "tb4_certificate_sha256",
        label="tb4_checkpoint",
    )
    deployment = value.get("deployment")
    checkpoint_endpoint = _endpoint_binding(value.get("endpoint"), label="tb4_endpoint")
    try:
        checkpoint_generation = validate_route_generation(value.get("serving_route_generation"))
        checkpoint_proxy_policy = validate_proxy_policy_binding(
            value.get("proxy_policy"),
            expected_request_timeout=KIMI_REQUEST_TIMEOUT,
        )
    except (RouteGenerationError, DeploymentProxyPolicyError) as cause:
        raise LaunchCertificateError("tb4_checkpoint_schema_invalid") from cause
    if len(checkpoint_generation["routes"]) != 1:
        raise LaunchCertificateError("tb4_route_count_invalid")
    if (
        value.get("schema_version") != 1
        or value.get("state") != "passed"
        or value.get("ok") is not True
        or not isinstance(deployment, dict)
        or set(deployment) != {"id", "spec_sha256"}
        or deployment.get("id") != deployment_id
        or checkpoint_endpoint != endpoint
    ):
        raise LaunchCertificateError("tb4_checkpoint_not_passed")
    _require_sha256(deployment.get("spec_sha256"), "tb4_deployment_spec")
    _require_sha256(value.get("eval_run_identity_sha256"), "tb4_eval_run_identity")

    expected_policy = {
        "binary_solved_reward": True,
        "expected_cpu_unsupported_tasks": EXPECTED_TB4_UNSUPPORTED_TASKS,
        "expected_supported_tasks": EXPECTED_TB4_SUPPORTED_TASKS,
        "expected_tasks": EXPECTED_TB4_TASKS,
        "lease_start_concurrency": EXPECTED_TB4_LEASE_START_CONCURRENCY,
        "max_sequence_tokens": EXPECTED_CONTEXT_TOKENS,
        "max_supported_pass_rate": EXPECTED_TB4_MAX_PASS_RATE,
        "min_supported_pass_rate": EXPECTED_TB4_MIN_PASS_RATE,
        "model": EXPECTED_MODEL,
        "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
        "reasoning_effort": "max",
        "require_logprobs": False,
        "require_model_io": True,
        "require_reasoning": True,
        "require_request_graph_match": True,
        "require_response": True,
        "require_token_data": False,
        "require_tool_call_lineage": True,
        "require_tool_schemas": True,
        "rollout_concurrency": EXPECTED_TB4_ROLLOUT_CONCURRENCY,
        "rollouts_per_task": 1,
    }
    if _canonical_json(value.get("audit_policy")) != _canonical_json(expected_policy):
        raise LaunchCertificateError("tb4_policy_invalid")

    counts = value.get("counts")
    expected_count_keys = {
        "cpu_unsupported_tasks",
        "cpu_unsupported_trace_failures",
        "global_problems",
        "observed_traces",
        "supported_passes",
        "supported_tasks",
        "supported_trace_failures",
        "trace_failures",
    }
    if not isinstance(counts, dict) or set(counts) != expected_count_keys:
        raise LaunchCertificateError("tb4_counts_invalid")
    for key in expected_count_keys:
        _require_nonnegative_int(counts.get(key), f"tb4_{key}")
    supported_passes = counts["supported_passes"]
    if (
        counts["observed_traces"] != EXPECTED_TB4_TASKS
        or counts["supported_tasks"] != EXPECTED_TB4_SUPPORTED_TASKS
        or counts["cpu_unsupported_tasks"] != EXPECTED_TB4_UNSUPPORTED_TASKS
        or counts["trace_failures"] != 0
        or counts["supported_trace_failures"] != 0
        or counts["cpu_unsupported_trace_failures"] != 0
        or counts["global_problems"] != 0
        or supported_passes > EXPECTED_TB4_SUPPORTED_TASKS
    ):
        raise LaunchCertificateError("tb4_counts_invalid")

    scores = value.get("scores")
    if not isinstance(scores, dict) or set(scores) != {"all_task_pass_rate", "supported_pass_rate"}:
        raise LaunchCertificateError("tb4_scores_invalid")
    supported_rate = _require_rate(scores.get("supported_pass_rate"), "tb4_supported_pass_rate")
    all_rate = _require_rate(scores.get("all_task_pass_rate"), "tb4_all_task_pass_rate")
    if (
        not math.isclose(
            supported_rate,
            supported_passes / EXPECTED_TB4_SUPPORTED_TASKS,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        or not math.isclose(
            all_rate,
            supported_passes / EXPECTED_TB4_TASKS,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        or not EXPECTED_TB4_MIN_PASS_RATE <= supported_rate <= EXPECTED_TB4_MAX_PASS_RATE
    ):
        raise LaunchCertificateError("tb4_scores_invalid")

    artifacts = value.get("artifacts")
    expected_artifacts = {
        "config",
        "eval_run_identity",
        "eval_invocations",
        "inputs_manifest",
        "provenance",
        "readiness_checkpoint",
        "results",
        "route_guard_success",
        "smoke_checkpoint",
        "proxy_info",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise LaunchCertificateError("tb4_artifacts_invalid")
    artifact_records: dict[str, dict[str, Any]] = {}
    artifact_paths: dict[str, Path] = {}
    for name, record in artifacts.items():
        artifact_records[name], artifact_paths[name] = _rehash_record(
            record,
            label=f"tb4_{name}",
        )
    try:
        identity_envelope = load_eval_run_identity(
            artifact_paths["eval_run_identity"],
            verify_references=False,
        )
    except (EvalIdentityError, OSError, ValueError) as cause:
        raise LaunchCertificateError("tb4_eval_run_identity_invalid") from cause
    identity = identity_envelope.get("identity")
    if (
        not isinstance(identity, dict)
        or identity_envelope.get("eval_run_identity_sha256") != value["eval_run_identity_sha256"]
        or identity.get("role") != "tb4"
    ):
        raise LaunchCertificateError("tb4_eval_run_identity_invalid")
    identity_deployment = identity.get("deployment")
    identity_inputs = identity.get("inputs")
    identity_config = identity.get("config")
    if (
        not isinstance(identity_deployment, dict)
        or identity_deployment.get("id") != deployment_id
        or identity_deployment.get("endpoint") != endpoint
        or identity_deployment.get("serving_route_generation") != checkpoint_generation
        or identity_deployment.get("proxy_policy") != checkpoint_proxy_policy
        or not isinstance(identity_deployment.get("spec"), dict)
        or identity_deployment["spec"].get("sha256") != deployment["spec_sha256"]
        or not isinstance(identity_inputs, dict)
        or not isinstance(identity_inputs.get("task_file"), dict)
        or identity_inputs["task_file"].get("count") != EXPECTED_TB4_TASKS
        or not isinstance(identity_config, dict)
    ):
        raise LaunchCertificateError("tb4_eval_run_identity_invalid")
    for identity_record, artifact_name in (
        (_identity_record(identity, "config", "resolved", label="tb4_identity_config"), "config"),
        (_identity_record(identity, "inputs", "manifest", label="tb4_identity_manifest"), "inputs_manifest"),
        (
            _identity_record(
                identity,
                "deployment",
                "readiness_checkpoint",
                label="tb4_identity_readiness",
            ),
            "readiness_checkpoint",
        ),
        (
            _identity_record(
                identity,
                "deployment",
                "smoke_checkpoint",
                label="tb4_identity_smoke",
            ),
            "smoke_checkpoint",
        ),
        (
            endpoint["proxy_info"],
            "proxy_info",
        ),
    ):
        _records_match(identity_record, artifact_records[artifact_name], label=f"tb4_{artifact_name}_link")
    try:
        guard_receipt = load_guard_success_receipt(
            artifact_paths["route_guard_success"],
        )
        guard_artifacts = validate_guard_success_linkage(
            guard_receipt,
            run_dir=artifact_paths["eval_run_identity"].parent,
            eval_run_identity_sha256=value["eval_run_identity_sha256"],
            eval_run_role="tb4",
            eval_run_identity_file_sha256=artifact_records["eval_run_identity"]["sha256"],
            results_sha256=artifact_records["results"]["sha256"],
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment["spec_sha256"],
            readiness_checkpoint=artifact_records["readiness_checkpoint"],
            endpoint=endpoint,
            serving_route_generation=checkpoint_generation,
            proxy_policy=checkpoint_proxy_policy,
        )
    except (OSError, GuardReceiptError) as cause:
        raise LaunchCertificateError("tb4_guard_success_receipt_invalid") from cause
    if guard_artifacts["eval_invocations"] != artifact_records["eval_invocations"]:
        raise LaunchCertificateError("tb4_guard_success_receipt_invalid")
    return {
        "certificate_sha256": certificate_sha256,
        "deployment_spec_sha256": deployment["spec_sha256"],
        "expected_routes": len(checkpoint_generation["routes"]),
        "serving_route_generation": checkpoint_generation,
        "proxy_policy": checkpoint_proxy_policy,
        "supported_pass_rate": supported_rate,
        "supported_passes": supported_passes,
    }


def _validate_oracle_receipt(
    envelope: dict[str, Any],
    *,
    project_root: Path,
    production_config: Path,
    production_config_sha256: str,
    approved_manifest: Path,
    approved_manifest_sha256: str,
) -> dict[str, Any]:
    if set(envelope) != {"receipt", "receipt_sha256", "schema_version"}:
        raise LaunchCertificateError("oracle_receipt_envelope_invalid")
    receipt = envelope.get("receipt")
    receipt_sha256 = _require_sha256(envelope.get("receipt_sha256"), "oracle_receipt")
    if (
        envelope.get("schema_version") != 1
        or not isinstance(receipt, dict)
        or _sha256_bytes(_canonical_json(receipt)) != receipt_sha256
    ):
        raise LaunchCertificateError("oracle_receipt_self_hash_mismatch")

    expected_receipt_keys = {
        "acceptance",
        "applied_manifest",
        "artifact_type",
        "counts",
        "dataset",
        "image_manifest",
        "oracle_artifacts",
        "promotion_summary",
        "schema_version",
        "source",
        "updated_configs",
    }
    if (
        set(receipt) != expected_receipt_keys
        or receipt.get("schema_version") != 1
        or receipt.get("artifact_type") != "terminal_bench_vmvm_oracle_promotion_receipt"
    ):
        raise LaunchCertificateError("oracle_receipt_schema_invalid")

    dataset = receipt.get("dataset")
    image_manifest = receipt.get("image_manifest")
    if not isinstance(dataset, dict) or set(dataset) != {"revision"}:
        raise LaunchCertificateError("oracle_receipt_dataset_invalid")
    dataset_revision = _require_revision(dataset.get("revision"), "oracle_dataset")
    if not isinstance(image_manifest, dict) or set(image_manifest) != {"sha256"}:
        raise LaunchCertificateError("oracle_receipt_image_manifest_invalid")
    image_manifest_sha256 = _require_sha256(
        image_manifest.get("sha256"),
        "oracle_image_manifest",
    )

    source = receipt.get("source")
    expected_source_keys = {
        "minimum_prime_rl_ancestor",
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "required_prime_rl_ancestor",
        "verifiers_commit",
        "vmvm_tb_v2_sha256",
    }
    if not isinstance(source, dict) or set(source) != expected_source_keys:
        raise LaunchCertificateError("oracle_receipt_source_invalid")
    for key in ("minimum_prime_rl_ancestor", "prime_rl_commit", "required_prime_rl_ancestor", "verifiers_commit"):
        _require_revision(source.get(key), f"oracle_{key}")
    for key in ("prime_rl_tree_sha256", "vmvm_tb_v2_sha256"):
        _require_sha256(source.get(key), f"oracle_{key}")
    production_source = _validate_source(project_root, source)

    oracle_artifacts = receipt.get("oracle_artifacts")
    base_oracle_artifact_keys = {
        "invocations",
        "provenance",
        "results",
        "run_identity",
        "summary",
    }
    if not isinstance(oracle_artifacts, dict) or frozenset(oracle_artifacts) not in {
        frozenset(base_oracle_artifact_keys),
        frozenset(base_oracle_artifact_keys | {"source_wheel_recovery"}),
    }:
        raise LaunchCertificateError("oracle_receipt_artifacts_invalid")
    artifact_hashes: dict[str, str] = {}
    for name, expected_name in (
        ("provenance", "provenance.txt"),
        ("results", "results.jsonl"),
        ("summary", "summary.json"),
    ):
        record = oracle_artifacts.get(name)
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise LaunchCertificateError("oracle_receipt_artifacts_invalid")
        if record.get("path") != expected_name:
            raise LaunchCertificateError("oracle_receipt_artifacts_invalid")
        artifact_hashes[name] = _require_sha256(record.get("sha256"), f"oracle_{name}")
    run_identity = oracle_artifacts.get("run_identity")
    if (
        not isinstance(run_identity, dict)
        or set(run_identity) != {"identity_sha256", "path", "sha256"}
        or run_identity.get("path") != "run_identity.json"
    ):
        raise LaunchCertificateError("oracle_receipt_artifacts_invalid")
    artifact_hashes["run_identity"] = _require_sha256(
        run_identity.get("sha256"),
        "oracle_run_identity_file",
    )
    run_identity_sha256 = _require_sha256(
        run_identity.get("identity_sha256"),
        "oracle_run_identity",
    )
    invocation_artifact = oracle_artifacts.get("invocations")
    if not isinstance(invocation_artifact, dict) or set(invocation_artifact) != {
        "path",
        "sha256",
    }:
        raise LaunchCertificateError("oracle_receipt_artifacts_invalid")
    invocation_path = invocation_artifact.get("path")
    if not isinstance(invocation_path, str) or not Path(invocation_path).is_absolute():
        raise LaunchCertificateError("oracle_receipt_artifacts_invalid")
    resolved_invocations, invocation_raw = _stable_read(
        Path(invocation_path),
        label="oracle_invocations",
    )
    invocation_sha256 = _require_sha256(
        invocation_artifact.get("sha256"),
        "oracle_invocations",
    )
    if str(resolved_invocations) != invocation_path or _sha256_bytes(invocation_raw) != invocation_sha256:
        raise LaunchCertificateError("oracle_invocations_sha256_mismatch")
    artifact_hashes["invocations"] = invocation_sha256
    source_wheel_policy_sha256: str | None = None
    source_wheel_attestation_sha256: str | None = None
    if "source_wheel_recovery" in oracle_artifacts:
        source_wheel_policy_sha256, source_wheel_attestation_sha256 = _validate_source_wheel_receipt_artifacts(
            oracle_artifacts["source_wheel_recovery"],
            oracle_dir=resolved_invocations.parent,
        )

    counts = receipt.get("counts")
    expected_count_keys = {
        "completed",
        "configured_files",
        "expected_total",
        "invocation_count",
        "oracle_reasons",
        "passed",
        "removed_invalid",
        "rerun_invalid_invocation_count",
        "selected",
    }
    if not isinstance(counts, dict) or set(counts) != expected_count_keys:
        raise LaunchCertificateError("oracle_receipt_counts_invalid")
    for key in expected_count_keys - {"oracle_reasons"}:
        _require_nonnegative_int(counts.get(key), f"oracle_{key}")
    reasons = counts.get("oracle_reasons")
    if (
        not isinstance(reasons, dict)
        or not reasons
        or not set(reasons).issubset(ORACLE_REASONS)
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in reasons.values())
    ):
        raise LaunchCertificateError("oracle_receipt_counts_invalid")
    if (
        counts["expected_total"] != EXPECTED_ORACLE_TASKS
        or counts["completed"] != EXPECTED_ORACLE_TASKS
        or counts["selected"] != EXPECTED_TASKS
        or counts["passed"] < EXPECTED_TASKS
        or counts["configured_files"] < 1
        or counts["invocation_count"] < 1
        or counts["rerun_invalid_invocation_count"] > 1
        or counts["removed_invalid"] > EXPECTED_TASKS
        or sum(reasons.values()) != EXPECTED_ORACLE_TASKS
        or reasons.get("valid") != counts["passed"]
    ):
        raise LaunchCertificateError("oracle_receipt_counts_invalid")
    _validate_oracle_invocations(
        invocation_raw,
        expected_run_identity_sha256=run_identity_sha256,
        expected_source={
            "prime_rl_commit": source["prime_rl_commit"],
            "prime_rl_tree_sha256": source["prime_rl_tree_sha256"],
            "verifiers_commit": source["verifiers_commit"],
            "vmvm_tb_v2_sha256": source["vmvm_tb_v2_sha256"],
        },
        expected_count=counts["invocation_count"],
        expected_rerun_invalid_count=counts["rerun_invalid_invocation_count"],
        source_wheel_policy_sha256=source_wheel_policy_sha256,
    )

    acceptance = receipt.get("acceptance")
    expected_acceptance_keys = {
        "minimum_pass_rate",
        "minimum_valid",
        "observed_pass_rate",
        "oracle_network_semantics",
        "selected_subset_valid",
    }
    if not isinstance(acceptance, dict) or set(acceptance) != expected_acceptance_keys:
        raise LaunchCertificateError("oracle_receipt_acceptance_invalid")
    observed_rate = _require_rate(acceptance.get("observed_pass_rate"), "oracle_pass_rate")
    expected_semantics = {
        "schema_version": 1,
        "trusted_reference_solution": "public",
        "verifier": "declared",
    }
    if (
        acceptance.get("minimum_pass_rate") != 0.9
        or acceptance.get("minimum_valid") != EXPECTED_TASKS
        or acceptance.get("selected_subset_valid") is not True
        or acceptance.get("oracle_network_semantics") != expected_semantics
        or observed_rate < 0.9
        or not math.isclose(
            observed_rate,
            counts["passed"] / EXPECTED_ORACLE_TASKS,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
    ):
        raise LaunchCertificateError("oracle_receipt_acceptance_invalid")

    manifest_record = _stable_relative_record(
        receipt.get("applied_manifest"),
        label="oracle_applied_manifest",
    )
    manifest_relative = _project_relative(
        approved_manifest,
        project_root,
        label="approved_manifest",
    )
    if manifest_record != {
        "path": manifest_relative,
        "sha256": approved_manifest_sha256,
    }:
        raise LaunchCertificateError("oracle_receipt_manifest_mismatch")

    updated_configs = receipt.get("updated_configs")
    if not isinstance(updated_configs, list):
        raise LaunchCertificateError("oracle_receipt_configs_invalid")
    config_records = [_stable_relative_record(record, label="oracle_updated_config") for record in updated_configs]
    if (
        len(config_records) != counts["configured_files"]
        or config_records != sorted(config_records, key=lambda record: record["path"])
        or len({record["path"] for record in config_records}) != len(config_records)
    ):
        raise LaunchCertificateError("oracle_receipt_configs_invalid")
    for record in config_records:
        config_path = _resolve_config_path(
            record["path"],
            project_root,
            label="oracle_updated_config",
        )
        if (
            config_path.suffix != ".toml"
            or _project_relative(config_path, project_root, label="oracle_updated_config") != record["path"]
        ):
            raise LaunchCertificateError("oracle_receipt_configs_invalid")
        observed, _ = _file_record(config_path, label="oracle_updated_config")
        if observed["sha256"] != record["sha256"]:
            raise LaunchCertificateError("oracle_receipt_config_hash_mismatch")
    config_relative = _project_relative(
        production_config,
        project_root,
        label="production_config",
    )
    matching_configs = [record for record in config_records if record["path"] == config_relative]
    if matching_configs != [{"path": config_relative, "sha256": production_config_sha256}]:
        raise LaunchCertificateError("oracle_receipt_config_mismatch")

    summary = receipt.get("promotion_summary")
    expected_summary_keys = {
        "applied",
        "completed",
        "configured_files",
        "current_manifest_sha256",
        "dataset_revision",
        "invocation_count",
        "minimum_pass_rate",
        "minimum_valid",
        "oracle_image_manifest_sha256",
        "oracle_invocations_sha256",
        "oracle_pass_rate",
        "oracle_prime_rl_commit",
        "oracle_provenance_sha256",
        "oracle_reasons",
        "oracle_results_sha256",
        "oracle_run_identity_file_sha256",
        "oracle_run_identity_sha256",
        "oracle_summary_sha256",
        "oracle_verifiers_commit",
        "oracle_vmvm_tb_v2_sha256",
        "passed",
        "removed_invalid",
        "rerun_invalid_invocation_count",
        "selected",
        "selected_manifest_sha256",
        "selected_subset_valid",
        "trusted_reference_solution",
    }
    if source_wheel_policy_sha256 is not None:
        expected_summary_keys |= {
            "source_wheel_attestation_sha256",
            "source_wheel_policy_sha256",
        }
    expected_summary = {
        "applied": True,
        "completed": counts["completed"],
        "configured_files": counts["configured_files"],
        "dataset_revision": dataset_revision,
        "invocation_count": counts["invocation_count"],
        "minimum_pass_rate": acceptance["minimum_pass_rate"],
        "minimum_valid": acceptance["minimum_valid"],
        "oracle_image_manifest_sha256": image_manifest_sha256,
        "oracle_invocations_sha256": artifact_hashes["invocations"],
        "oracle_pass_rate": observed_rate,
        "oracle_prime_rl_commit": source["prime_rl_commit"],
        "oracle_provenance_sha256": artifact_hashes["provenance"],
        "oracle_reasons": reasons,
        "oracle_results_sha256": artifact_hashes["results"],
        "oracle_run_identity_file_sha256": artifact_hashes["run_identity"],
        "oracle_run_identity_sha256": run_identity_sha256,
        "oracle_summary_sha256": artifact_hashes["summary"],
        "oracle_verifiers_commit": source["verifiers_commit"],
        "oracle_vmvm_tb_v2_sha256": source["vmvm_tb_v2_sha256"],
        "passed": counts["passed"],
        "removed_invalid": counts["removed_invalid"],
        "rerun_invalid_invocation_count": counts["rerun_invalid_invocation_count"],
        "selected": counts["selected"],
        "selected_manifest_sha256": approved_manifest_sha256,
        "selected_subset_valid": True,
        "trusted_reference_solution": "public",
    }
    if source_wheel_policy_sha256 is not None:
        expected_summary["source_wheel_attestation_sha256"] = source_wheel_attestation_sha256
        expected_summary["source_wheel_policy_sha256"] = source_wheel_policy_sha256
    if not isinstance(summary, dict) or set(summary) != expected_summary_keys:
        raise LaunchCertificateError("oracle_receipt_summary_invalid")
    _require_sha256(summary.get("current_manifest_sha256"), "oracle_current_manifest")
    if any(summary.get(key) != expected for key, expected in expected_summary.items()):
        raise LaunchCertificateError("oracle_receipt_summary_invalid")
    validated = {
        "dataset_revision": dataset_revision,
        "image_manifest_sha256": image_manifest_sha256,
        "passed": counts["passed"],
        "pass_rate": observed_rate,
        "receipt_sha256": receipt_sha256,
        "invocations": {
            "path": invocation_path,
            "sha256": invocation_sha256,
        },
        "invocation_count": counts["invocation_count"],
        "rerun_invalid_invocation_count": counts["rerun_invalid_invocation_count"],
        "oracle_source": dict(source),
        "production_source": production_source,
    }
    if source_wheel_policy_sha256 is not None:
        validated["source_wheel_recovery"] = {
            "policy_sha256": source_wheel_policy_sha256,
            "attestation_sha256": source_wheel_attestation_sha256,
        }
    return validated


def _validate_readiness_checkpoint(
    value: dict[str, Any],
    *,
    deployment_id: str,
    deployment_spec_sha256: str,
    endpoint: dict[str, Any],
) -> dict[str, Any]:
    required_keys = {
        "consecutive_ready_polls",
        "consecutive_status_unavailable",
        "deployment",
        "endpoint",
        "expected_routes",
        "last_status",
        "max_consecutive_status_unavailable",
        "observed_spec_sha256",
        "polls",
        "probe",
        "proxy_policy",
        "proxy_info_readable",
        "required_consecutive_polls",
        "schema_version",
        "state",
        "status_unavailable_reason",
        "serving_route_generation",
        "updated_at",
    }
    if set(value) != required_keys:
        raise LaunchCertificateError("readiness_checkpoint_schema_invalid")
    expected_routes = _require_positive_int(value.get("expected_routes"), "readiness_expected_routes")
    required_polls = _require_positive_int(
        value.get("required_consecutive_polls"),
        "readiness_required_consecutive_polls",
    )
    consecutive_ready = _require_nonnegative_int(
        value.get("consecutive_ready_polls"),
        "readiness_consecutive_ready_polls",
    )
    polls = _require_positive_int(value.get("polls"), "readiness_polls")
    _require_nonnegative_int(
        value.get("max_consecutive_status_unavailable"),
        "readiness_max_status_unavailable",
    )
    consecutive_unavailable = _require_nonnegative_int(
        value.get("consecutive_status_unavailable"),
        "readiness_consecutive_status_unavailable",
    )
    probe = value.get("probe")
    checkpoint_endpoint = _endpoint_binding(value.get("endpoint"), label="readiness_endpoint")
    if value.get("schema_version") != 1 or value.get("state") != "passed":
        raise LaunchCertificateError("readiness_checkpoint_not_passed")
    try:
        serving_route_generation = validate_readiness_route_generation(
            value,
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec_sha256,
        )
        proxy_policy = validate_proxy_policy_binding(
            value.get("proxy_policy"),
            expected_request_timeout=KIMI_REQUEST_TIMEOUT,
        )
    except (RouteGenerationError, DeploymentProxyPolicyError) as cause:
        raise LaunchCertificateError("readiness_checkpoint_schema_invalid") from cause
    last_status = value.get("last_status")
    expected_status_keys = {
        "coordinator_incarnation",
        "coord_ticks_completed",
        "deployment_id",
        "desired",
        "pending",
        "phase",
        "ready",
        "running_not_ready",
        "schema_version",
        "serving_route_generation",
    }
    if (
        value.get("schema_version") != 1
        or value.get("state") != "passed"
        or value.get("deployment") != deployment_id
        or value.get("observed_spec_sha256") != deployment_spec_sha256
        or checkpoint_endpoint != endpoint
        or value.get("proxy_info_readable") is not True
        or value.get("status_unavailable_reason") is not None
        or consecutive_unavailable != 0
        or consecutive_ready < required_polls
        or polls < consecutive_ready
        or not isinstance(probe, dict)
        or probe.get("ok") is not True
        or not isinstance(last_status, dict)
        or set(last_status) != expected_status_keys
        or last_status.get("deployment_id") != deployment_id
        or last_status.get("phase") != "serving"
        or last_status.get("desired") != expected_routes
        or last_status.get("ready") != expected_routes
        or last_status.get("running_not_ready") != 0
        or last_status.get("pending") != 0
    ):
        raise LaunchCertificateError("readiness_checkpoint_not_passed")
    _require_nonnegative_int(last_status.get("schema_version"), "readiness_status_schema_version")
    ticks = last_status.get("coord_ticks_completed")
    if ticks is not None:
        _require_nonnegative_int(ticks, "readiness_coord_ticks_completed")
    return {
        "endpoint": checkpoint_endpoint,
        "expected_routes": expected_routes,
        "polls": polls,
        "serving_route_generation": serving_route_generation,
        "proxy_policy": proxy_policy,
    }


def _validate_capacity_smoke(
    value: dict[str, Any],
    *,
    deployment_id: str,
    deployment_spec_sha256: str,
    endpoint: dict[str, Any],
    readiness_path: Path,
    readiness_sha256: str,
    production_contract: dict[str, Any],
    dataset_revision: str,
    image_manifest_sha256: str,
) -> dict[str, Any]:
    expected_keys = {
        "artifacts",
        "audit_policy",
        "counts",
        "deployment",
        "deployment_id",
        "deployment_spec_sha256",
        "endpoint",
        "serving_route_generation",
        "proxy_policy",
        "eval_run_identity_sha256",
        "ok",
        "observed_concurrency",
        "qualified_execution",
        "readiness_checkpoint_sha256",
        "schema_version",
        "smoke_checkpoint_sha256",
        "state",
    }
    if set(value) != expected_keys:
        raise LaunchCertificateError("capacity_smoke_schema_invalid")
    checkpoint_sha256 = _verify_flat_self_hash(
        value,
        "smoke_checkpoint_sha256",
        label="capacity_smoke",
    )
    deployment = value.get("deployment")
    checkpoint_endpoint = _endpoint_binding(value.get("endpoint"), label="capacity_endpoint")
    try:
        checkpoint_generation = validate_route_generation(value.get("serving_route_generation"))
        checkpoint_proxy_policy = validate_proxy_policy_binding(
            value.get("proxy_policy"),
            expected_request_timeout=KIMI_REQUEST_TIMEOUT,
        )
    except (RouteGenerationError, DeploymentProxyPolicyError) as cause:
        raise LaunchCertificateError("capacity_smoke_schema_invalid") from cause
    if (
        value.get("schema_version") != 1
        or value.get("state") != "passed"
        or value.get("ok") is not True
        or value.get("deployment_id") != deployment_id
        or value.get("deployment_spec_sha256") != deployment_spec_sha256
        or value.get("readiness_checkpoint_sha256") != readiness_sha256
        or checkpoint_endpoint != endpoint
        or not isinstance(deployment, dict)
        or deployment
        != {
            "id": deployment_id,
            "spec_sha256": deployment_spec_sha256,
        }
    ):
        raise LaunchCertificateError("capacity_smoke_not_passed")
    _require_sha256(value.get("eval_run_identity_sha256"), "capacity_eval_run_identity")

    execution = value.get("qualified_execution")
    expected_execution_keys = {
        "http_max_connections",
        "http_max_keepalive_connections",
        "lease_start_concurrency",
        "multiplex",
        "rollout_concurrency",
    }
    if not isinstance(execution, dict) or set(execution) != expected_execution_keys:
        raise LaunchCertificateError("capacity_smoke_execution_invalid")
    qualified_execution = {
        key: _require_positive_int(execution.get(key), f"capacity_{key}") for key in sorted(expected_execution_keys)
    }
    observed = value.get("observed_concurrency")
    expected_observed_keys = {
        "active_rollout_signal",
        "lease_start_signal",
        "peak_active_rollouts_lower_bound",
        "peak_concurrent_lease_startups",
        "required_peak_active_rollouts_lower_bound",
        "required_peak_concurrent_lease_startups",
    }
    if (
        not isinstance(observed, dict)
        or set(observed) != expected_observed_keys
        or observed.get("active_rollout_signal") != "completed_trace_lifecycle_timing_overlap"
        or observed.get("lease_start_signal") != "vacli_lease_start_semaphore_holders"
    ):
        raise LaunchCertificateError("capacity_smoke_observed_concurrency_invalid")
    observed_concurrency = {
        "active_rollout_signal": observed["active_rollout_signal"],
        "lease_start_signal": observed["lease_start_signal"],
        "peak_active_rollouts_lower_bound": _require_positive_int(
            observed.get("peak_active_rollouts_lower_bound"),
            "capacity_peak_active_rollouts_lower_bound",
        ),
        "peak_concurrent_lease_startups": _require_positive_int(
            observed.get("peak_concurrent_lease_startups"),
            "capacity_peak_concurrent_lease_startups",
        ),
        "required_peak_active_rollouts_lower_bound": _require_positive_int(
            observed.get("required_peak_active_rollouts_lower_bound"),
            "capacity_required_peak_active_rollouts_lower_bound",
        ),
        "required_peak_concurrent_lease_startups": _require_positive_int(
            observed.get("required_peak_concurrent_lease_startups"),
            "capacity_required_peak_concurrent_lease_startups",
        ),
    }
    policy = value.get("audit_policy")
    expected_policy_keys = {
        "expected_traces",
        "max_sequence_tokens",
        "require_logprobs",
        "require_model_io",
        "model_io_contract",
        "require_request_graph_match",
        "require_reasoning",
        "require_token_data",
        "rollouts_per_task",
    }
    if not isinstance(policy, dict) or set(policy) != expected_policy_keys:
        raise LaunchCertificateError("capacity_smoke_policy_invalid")
    expected_traces = _require_positive_int(
        policy.get("expected_traces"),
        "capacity_expected_traces",
    )
    expected_policy = {
        "expected_traces": expected_traces,
        "max_sequence_tokens": EXPECTED_CONTEXT_TOKENS,
        "require_logprobs": False,
        "require_model_io": True,
        "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
        "require_request_graph_match": True,
        "require_reasoning": True,
        "require_token_data": False,
        "rollouts_per_task": 1,
    }
    if _canonical_json(policy) != _canonical_json(expected_policy):
        raise LaunchCertificateError("capacity_smoke_policy_invalid")

    counts = value.get("counts")
    expected_count_keys = {
        "global_problems",
        "model_io_turns",
        "sampled_tokens",
        "tasks",
        "trace_failures",
        "traces",
    }
    if not isinstance(counts, dict) or set(counts) != expected_count_keys:
        raise LaunchCertificateError("capacity_smoke_counts_invalid")
    for key in expected_count_keys:
        _require_nonnegative_int(counts.get(key), f"capacity_{key}")
    if (
        counts["traces"] != expected_traces
        or counts["tasks"] != expected_traces
        or counts["trace_failures"] != 0
        or counts["global_problems"] != 0
        or counts["sampled_tokens"] < 1
        or counts["model_io_turns"] < expected_traces
    ):
        raise LaunchCertificateError("capacity_smoke_counts_invalid")

    artifacts = value.get("artifacts")
    expected_artifacts = {
        "config",
        "concurrency_telemetry",
        "eval_run_identity",
        "eval_invocations",
        "inputs_manifest",
        "provenance",
        "readiness_checkpoint",
        "results",
        "route_guard_success",
        "proxy_info",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise LaunchCertificateError("capacity_smoke_artifacts_invalid")
    artifact_records: dict[str, dict[str, Any]] = {}
    artifact_paths: dict[str, Path] = {}
    for name, record in artifacts.items():
        artifact_records[name], artifact_paths[name] = _rehash_record(
            record,
            label=f"capacity_{name}",
        )
    readiness_record = artifact_records["readiness_checkpoint"]
    linked_readiness = artifact_paths["readiness_checkpoint"]
    if linked_readiness != readiness_path or readiness_record["sha256"] != readiness_sha256:
        raise LaunchCertificateError("capacity_smoke_readiness_mismatch")
    try:
        identity_envelope = load_eval_run_identity(
            artifact_paths["eval_run_identity"],
            verify_references=True,
        )
    except (EvalIdentityError, OSError, ValueError) as cause:
        raise LaunchCertificateError("capacity_eval_run_identity_invalid") from cause
    identity = identity_envelope.get("identity")
    if (
        not isinstance(identity, dict)
        or identity_envelope.get("eval_run_identity_sha256") != value["eval_run_identity_sha256"]
        or identity.get("role") != "smoke"
    ):
        raise LaunchCertificateError("capacity_eval_run_identity_invalid")
    identity_deployment = identity.get("deployment")
    identity_inputs = identity.get("inputs")
    identity_execution = identity.get("execution")
    identity_contract = identity.get("contract")
    identity_dataset = identity.get("dataset")
    vmvm_environment = identity_execution.get("vmvm_environment") if isinstance(identity_execution, dict) else None
    expected_contract_keys = {
        "capture_model_io",
        "context_tokens",
        "model",
        "num_rollouts",
        "outbound_body_denylist",
        "pass_at_1",
        "reasoning_effort",
        "retain_traces",
        "sampling_max_tokens",
        "thinking",
    }
    expected_contract = {key: production_contract.get(key) for key in expected_contract_keys}
    image_manifest = identity_inputs.get("image_manifest") if isinstance(identity_inputs, dict) else None
    if (
        not isinstance(identity_deployment, dict)
        or identity_deployment.get("id") != deployment_id
        or identity_deployment.get("endpoint") != endpoint
        or identity_deployment.get("serving_route_generation") != checkpoint_generation
        or identity_deployment.get("proxy_policy") != checkpoint_proxy_policy
        or not isinstance(identity_deployment.get("spec"), dict)
        or identity_deployment["spec"].get("sha256") != deployment_spec_sha256
        or not isinstance(identity_inputs, dict)
        or not isinstance(identity_inputs.get("task_file"), dict)
        or identity_inputs["task_file"].get("count") != expected_traces
        or not isinstance(image_manifest, dict)
        or image_manifest.get("sha256") != image_manifest_sha256
        or _canonical_json(identity_contract) != _canonical_json(expected_contract)
        or not isinstance(identity_dataset, dict)
        or identity_dataset.get("kind") != "git_revision"
        or identity_dataset.get("revision") != dataset_revision
        or not isinstance(identity_execution, dict)
        or not isinstance(vmvm_environment, dict)
        or any(
            identity_execution.get(key) != qualified_execution[key]
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or vmvm_environment.get("lease_start_concurrency") != qualified_execution["lease_start_concurrency"]
    ):
        raise LaunchCertificateError("capacity_eval_run_identity_invalid")
    _records_match(
        endpoint["proxy_info"],
        artifact_records["proxy_info"],
        label="capacity_proxy_info_link",
    )
    for identity_record, artifact_name in (
        (
            _identity_record(identity, "config", "resolved", label="capacity_identity_config"),
            "config",
        ),
        (
            _identity_record(identity, "inputs", "manifest", label="capacity_identity_manifest"),
            "inputs_manifest",
        ),
        (
            _identity_record(
                identity,
                "deployment",
                "readiness_checkpoint",
                label="capacity_identity_readiness",
            ),
            "readiness_checkpoint",
        ),
    ):
        _records_match(
            identity_record,
            artifact_records[artifact_name],
            label=f"capacity_{artifact_name}_link",
        )
    try:
        guard_receipt = load_guard_success_receipt(
            artifact_paths["route_guard_success"],
        )
        guard_artifacts = validate_guard_success_linkage(
            guard_receipt,
            run_dir=artifact_paths["eval_run_identity"].parent,
            eval_run_identity_sha256=value["eval_run_identity_sha256"],
            eval_run_role="smoke",
            eval_run_identity_file_sha256=artifact_records["eval_run_identity"]["sha256"],
            results_sha256=artifact_records["results"]["sha256"],
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec_sha256,
            readiness_checkpoint=readiness_record,
            endpoint=endpoint,
            serving_route_generation=checkpoint_generation,
            proxy_policy=checkpoint_proxy_policy,
            require_concurrency_telemetry=True,
        )
    except (OSError, GuardReceiptError) as cause:
        raise LaunchCertificateError("capacity_guard_success_receipt_invalid") from cause
    if guard_artifacts["eval_invocations"] != artifact_records["eval_invocations"]:
        raise LaunchCertificateError("capacity_guard_success_receipt_invalid")
    try:
        invocation, invocation_artifact = validate_eval_invocations(
            artifact_paths["eval_invocations"],
            eval_run_identity_sha256=value["eval_run_identity_sha256"],
            eval_run_role="smoke",
        )
        if invocation_artifact != artifact_records["eval_invocations"]:
            raise GuardReceiptError("eval_invocations_changed")
        telemetry, telemetry_artifact = load_concurrency_telemetry_artifact(
            artifact_paths["concurrency_telemetry"],
            eval_run_identity_sha256=value["eval_run_identity_sha256"],
            eval_run_role="smoke",
            slurm_job_id=invocation["slurm_job_id"],
        )
        if telemetry_artifact != artifact_records["concurrency_telemetry"]:
            raise GuardReceiptError("concurrency_telemetry_changed")
    except (OSError, GuardReceiptError, ConcurrencyTelemetryError) as cause:
        raise LaunchCertificateError("capacity_concurrency_telemetry_invalid") from cause
    observations = telemetry["observations"]
    try:
        rollout_observation = measure_peak_active_rollouts(_iter_traces(artifact_paths["results"]))
        _, results_sha256 = _stable_file_sha256(
            artifact_paths["results"],
            label="capacity_results",
        )
    except (OSError, TraceJSONLError, TraceConcurrencyError) as cause:
        raise LaunchCertificateError("capacity_trace_concurrency_invalid") from cause
    if (
        rollout_observation["observed_rollouts"] != expected_traces
        or rollout_observation["peak_active_rollouts_lower_bound"]
        != observed_concurrency["peak_active_rollouts_lower_bound"]
        or results_sha256 != artifact_records["results"]["sha256"]
    ):
        raise LaunchCertificateError("capacity_trace_concurrency_invalid")
    if (
        observations["peak_concurrent_lease_startups"] != observed_concurrency["peak_concurrent_lease_startups"]
        or observations["vmvm_runtime_ready"] < expected_traces
    ):
        raise LaunchCertificateError("capacity_concurrency_telemetry_invalid")
    return {
        "checkpoint_sha256": checkpoint_sha256,
        "expected_traces": expected_traces,
        "qualified_execution": qualified_execution,
        "observed_concurrency": observed_concurrency,
        "serving_route_generation": checkpoint_generation,
        "proxy_policy": checkpoint_proxy_policy,
    }


def _validate_production_config(
    raw: bytes,
    *,
    project_root: Path,
    approved_manifest: Path,
    approved_manifest_sha256: str,
    dataset_revision: str,
    expected_image_manifest_sha256: str,
) -> dict[str, Any]:
    try:
        config = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as cause:
        raise LaunchCertificateError("production_config_invalid") from cause
    client = config.get("client")
    sampling = config.get("sampling")
    taskset = config.get("taskset")
    harness = config.get("harness")
    if not all(isinstance(value, dict) for value in (client, sampling, taskset, harness)):
        raise LaunchCertificateError("production_config_invalid")
    assert isinstance(client, dict)
    assert isinstance(sampling, dict)
    assert isinstance(taskset, dict)
    assert isinstance(harness, dict)
    runtime = harness.get("runtime")
    if not isinstance(runtime, dict):
        raise LaunchCertificateError("production_vmvm_contract_invalid")
    try:
        timeout_contract = validate_kimi_timeout_contract(config, required_profile="full")
    except EvalIdentityError as cause:
        raise LaunchCertificateError("production_timeout_contract_invalid") from cause
    try:
        validate_kimi_retry_contract(config)
    except EvalIdentityError as cause:
        raise LaunchCertificateError("production_retry_contract_invalid") from cause
    try:
        execution = validate_kimi_steady_state_concurrency_contract(config)
    except EvalIdentityError as cause:
        raise LaunchCertificateError("production_concurrency_contract_invalid") from cause

    context = {
        "max_input_tokens": config.get("max_input_tokens"),
        "max_output_tokens": config.get("max_output_tokens"),
        "max_total_tokens": config.get("max_total_tokens"),
    }
    thinking = sampling.get("chat_template_kwargs")
    denylist = client.get("outbound_body_denylist")
    sampling_max_tokens = _require_positive_int(
        sampling.get("max_tokens"),
        "production_sampling_max_tokens",
    )
    if (
        config.get("model") != EXPECTED_MODEL
        or config.get("num_tasks") != EXPECTED_TASKS
        or config.get("num_rollouts") != 1
        or config.get("retain_traces") is not False
        or config.get("rich") is not False
        or any(value != EXPECTED_CONTEXT_TOKENS for value in context.values())
        or sampling.get("reasoning_effort") != "max"
        or _canonical_json(thinking) != _canonical_json({"enable_thinking": True, "preserve_thinking": True})
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or not isinstance(denylist, list)
        or len(denylist) != len(EXPECTED_DENYLIST)
        or set(denylist) != EXPECTED_DENYLIST
        or sampling_max_tokens > EXPECTED_CONTEXT_TOKENS
    ):
        raise LaunchCertificateError("production_model_contract_invalid")
    if (
        taskset.get("id") != "terminal-bench-vmvm"
        or runtime.get("type") != "vmvm"
        or taskset.get("dataset_revision") != dataset_revision
        or taskset.get("task_file_sha256") != approved_manifest_sha256
        or taskset.get("image_manifest_sha256") != expected_image_manifest_sha256
    ):
        raise LaunchCertificateError("production_vmvm_contract_invalid")

    configured_manifest = _resolve_config_path(
        taskset.get("task_file"),
        project_root,
        label="production_task_file",
    )
    if configured_manifest != approved_manifest:
        raise LaunchCertificateError("production_task_file_mismatch")
    dataset_dir = _resolve_config_path(
        taskset.get("dataset_dir"),
        project_root,
        label="production_dataset",
    )
    if not dataset_dir.is_dir():
        raise LaunchCertificateError("production_dataset_unreadable")
    if (
        _git_output(dataset_dir, "rev-parse", "--verify", "HEAD", label="production_dataset").strip()
        != dataset_revision
    ):
        raise LaunchCertificateError("production_dataset_revision_mismatch")
    if _git_output(
        dataset_dir,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        label="production_dataset",
    ).strip():
        raise LaunchCertificateError("production_dataset_not_clean")
    image_manifest = _resolve_config_path(
        taskset.get("image_manifest"),
        project_root,
        label="production_image_manifest",
    )
    image_record, _ = _file_record(image_manifest, label="production_image_manifest")
    if image_record["sha256"] != expected_image_manifest_sha256:
        raise LaunchCertificateError("production_image_manifest_sha256_mismatch")

    return {
        "capture_model_io": True,
        "context_tokens": context,
        "dataset": {
            "path": str(dataset_dir),
            "revision": dataset_revision,
        },
        "execution": execution,
        "image_manifest": image_record,
        "model": EXPECTED_MODEL,
        "num_rollouts": 1,
        "num_tasks": EXPECTED_TASKS,
        "outbound_body_denylist": sorted(EXPECTED_DENYLIST),
        "pass_at_1": True,
        "reasoning_effort": "max",
        "retain_traces": False,
        "sampling_max_tokens": sampling_max_tokens,
        "task_file_sha256": approved_manifest_sha256,
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "timeouts": timeout_contract,
        "vmvm": True,
    }


def _validate_capacity(
    qualified: dict[str, int],
    observed: dict[str, Any],
    required: dict[str, int],
    requested_lease_start_concurrency: int,
    expected_traces: int,
) -> None:
    steady_state_keys = (
        "http_max_connections",
        "http_max_keepalive_connections",
        "multiplex",
        "rollout_concurrency",
    )
    if len({qualified[key] for key in steady_state_keys}) != 1:
        raise LaunchCertificateError("capacity_smoke_concurrency_contract_invalid")
    if len({required[key] for key in steady_state_keys}) != 1:
        raise LaunchCertificateError("production_concurrency_contract_invalid")
    comparisons = {
        "http_max_connections": required["http_max_connections"],
        "http_max_keepalive_connections": required["http_max_keepalive_connections"],
        "multiplex": required["multiplex"],
        "rollout_concurrency": required["rollout_concurrency"],
        "lease_start_concurrency": requested_lease_start_concurrency,
    }
    if any(qualified[key] < minimum for key, minimum in comparisons.items()):
        raise LaunchCertificateError("capacity_smoke_below_production_concurrency")
    if (
        observed["required_peak_active_rollouts_lower_bound"] != qualified["rollout_concurrency"]
        or observed["required_peak_concurrent_lease_startups"] != qualified["lease_start_concurrency"]
        or observed["peak_active_rollouts_lower_bound"] != qualified["rollout_concurrency"]
        or observed["peak_concurrent_lease_startups"] != qualified["lease_start_concurrency"]
    ):
        raise LaunchCertificateError("capacity_smoke_observed_concurrency_invalid")
    if (
        observed["peak_active_rollouts_lower_bound"] < required["rollout_concurrency"]
        or observed["peak_concurrent_lease_startups"] < requested_lease_start_concurrency
    ):
        raise LaunchCertificateError("capacity_smoke_observed_below_production_concurrency")
    if expected_traces < max(comparisons.values()):
        raise LaunchCertificateError("capacity_smoke_task_count_too_small")


def _tb4_gate_record(
    artifact: dict[str, str],
    validated: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "artifact": artifact,
        "certificate_sha256": validated["certificate_sha256"],
        "deployment_spec_sha256": validated["deployment_spec_sha256"],
        "expected_routes": validated["expected_routes"],
        "supported_pass_rate": validated["supported_pass_rate"],
        "supported_passes": validated["supported_passes"],
    }
    if validated.get("sharded") is True:
        sharded = {
            **record,
            "sharded": True,
            "shard_count": validated["shard_count"],
            "route_generation_sha256s": validated["route_generation_sha256s"],
            "endpoint_binding_sha256s": validated["endpoint_binding_sha256s"],
        }
        if "proxy_policy_sha256" in validated:
            return {**sharded, "proxy_policy_sha256": validated["proxy_policy_sha256"]}
        return {
            **sharded,
            "proxy_policy_semantics_sha256": validated["proxy_policy_semantics_sha256"],
            "proxy_policy_sha256s": validated["proxy_policy_sha256s"],
        }
    return {
        **record,
        "serving_route_generation": validated["serving_route_generation"],
        "proxy_policy": validated["proxy_policy"],
    }


def _build_unsigned(
    *,
    tb4_checkpoint: Path,
    tb4_checkpoint_sha256: str,
    oracle_receipt: Path,
    oracle_receipt_sha256: str,
    readiness_checkpoint: Path,
    readiness_checkpoint_sha256: str,
    capacity_smoke_checkpoint: Path,
    capacity_smoke_checkpoint_sha256: str,
    deployment_id: str,
    deployment_spec: Path,
    deployment_spec_sha256: str,
    deployment_proxy_info: Path,
    deployment_proxy_info_sha256: str,
    production_config: Path,
    approved_manifest: Path,
    approved_manifest_sha256: str,
    requested_lease_start_concurrency: int,
) -> dict[str, Any]:
    if not isinstance(deployment_id, str) or DEPLOYMENT_RE.fullmatch(deployment_id) is None:
        raise LaunchCertificateError("deployment_id_invalid")
    requested_leases = _require_positive_int(
        requested_lease_start_concurrency,
        "requested_lease_start_concurrency",
    )
    if requested_leases != EXPECTED_MOBIUS_LEASE_START_CONCURRENCY:
        raise LaunchCertificateError("production_lease_start_concurrency_invalid")
    spec_record, spec_raw = _pinned_bytes(
        deployment_spec,
        deployment_spec_sha256,
        label="deployment_spec",
    )
    spec_num_endpoints = _spec_num_endpoints(spec_raw)
    endpoint_info = _load_current_endpoint(
        deployment_proxy_info,
        deployment_proxy_info_sha256,
        deployment_id=deployment_id,
        deployment_spec=Path(spec_record["path"]),
    )
    endpoint = endpoint_info.binding
    manifest_record, manifest_raw = _pinned_bytes(
        approved_manifest,
        approved_manifest_sha256,
        label="approved_manifest",
    )
    if (
        not manifest_raw.endswith(b"\n")
        or manifest_raw.count(b"\n") != EXPECTED_TASKS
        or manifest_raw.startswith(b"\n")
        or b"\n\n" in manifest_raw
        or b"\r" in manifest_raw
        or b"\t" in manifest_raw
    ):
        raise LaunchCertificateError("approved_manifest_count_invalid")

    config_record, config_raw = _file_record(production_config, label="production_config")
    config_path = Path(config_record["path"])
    project_root = _project_root(config_path)
    tb4_record, tb4_value = _pinned_json(
        tb4_checkpoint,
        tb4_checkpoint_sha256,
        label="tb4_checkpoint",
    )
    oracle_record, oracle_value = _pinned_json(
        oracle_receipt,
        oracle_receipt_sha256,
        label="oracle_receipt",
    )
    readiness_record, readiness_value = _pinned_json(
        readiness_checkpoint,
        readiness_checkpoint_sha256,
        label="readiness_checkpoint",
    )
    capacity_record, capacity_value = _pinned_json(
        capacity_smoke_checkpoint,
        capacity_smoke_checkpoint_sha256,
        label="capacity_smoke_checkpoint",
    )

    tb4 = _validate_tb4_checkpoint(
        tb4_value,
        deployment_id,
        endpoint,
        Path(tb4_record["path"]).parent,
    )
    oracle = _validate_oracle_receipt(
        oracle_value,
        project_root=project_root,
        production_config=config_path,
        production_config_sha256=config_record["sha256"],
        approved_manifest=Path(manifest_record["path"]),
        approved_manifest_sha256=manifest_record["sha256"],
    )
    production_contract = _validate_production_config(
        config_raw,
        project_root=project_root,
        approved_manifest=Path(manifest_record["path"]),
        approved_manifest_sha256=manifest_record["sha256"],
        dataset_revision=oracle["dataset_revision"],
        expected_image_manifest_sha256=oracle["image_manifest_sha256"],
    )
    readiness = _validate_readiness_checkpoint(
        readiness_value,
        deployment_id=deployment_id,
        deployment_spec_sha256=spec_record["sha256"],
        endpoint=endpoint,
    )
    if readiness["expected_routes"] != spec_num_endpoints:
        raise LaunchCertificateError("readiness_route_count_spec_mismatch")
    if readiness["expected_routes"] < 2:
        raise LaunchCertificateError("post_tb4_route_count_too_small")
    if readiness["expected_routes"] <= tb4["expected_routes"]:
        raise LaunchCertificateError("post_tb4_route_count_not_increased")
    if tb4["deployment_spec_sha256"] == spec_record["sha256"]:
        raise LaunchCertificateError("post_tb4_deployment_spec_not_changed")
    if readiness["expected_routes"] < production_contract["execution"]["rollout_concurrency"]:
        raise LaunchCertificateError("post_tb4_route_count_below_production_concurrency")
    try:
        revalidate_deployment_proxy_policy(
            Path(spec_record["path"]),
            expected_spec_sha256=spec_record["sha256"],
            expected_binding=readiness["proxy_policy"],
            expected_request_timeout=KIMI_REQUEST_TIMEOUT,
        )
    except DeploymentProxyPolicyError as cause:
        raise LaunchCertificateError("deployment_proxy_policy_changed") from cause
    capacity = _validate_capacity_smoke(
        capacity_value,
        deployment_id=deployment_id,
        deployment_spec_sha256=spec_record["sha256"],
        endpoint=endpoint,
        readiness_path=Path(readiness_record["path"]),
        readiness_sha256=readiness_record["sha256"],
        production_contract=production_contract,
        dataset_revision=oracle["dataset_revision"],
        image_manifest_sha256=oracle["image_manifest_sha256"],
    )
    _validate_capacity(
        capacity["qualified_execution"],
        capacity["observed_concurrency"],
        production_contract["execution"],
        requested_leases,
        capacity["expected_traces"],
    )
    if (
        capacity["serving_route_generation"] != readiness["serving_route_generation"]
        or capacity["proxy_policy"] != readiness["proxy_policy"]
    ):
        raise LaunchCertificateError("capacity_smoke_route_generation_mismatch")

    unsigned = {
        "artifact_type": ARTIFACT_TYPE,
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": readiness["serving_route_generation"],
            "proxy_policy": readiness["proxy_policy"],
            "spec": spec_record,
        },
        "gates": {
            "capacity_smoke": {
                "artifact": capacity_record,
                "checkpoint_sha256": capacity["checkpoint_sha256"],
                "expected_traces": capacity["expected_traces"],
                "observed_concurrency": capacity["observed_concurrency"],
                "qualified_execution": capacity["qualified_execution"],
                "readiness_checkpoint_sha256": readiness_record["sha256"],
                "serving_route_generation": capacity["serving_route_generation"],
                "proxy_policy": capacity["proxy_policy"],
            },
            "oracle_promotion": {
                "artifact": oracle_record,
                "dataset_revision": oracle["dataset_revision"],
                "image_manifest_sha256": oracle["image_manifest_sha256"],
                "invocation_count": oracle["invocation_count"],
                "invocations_sha256": oracle["invocations"]["sha256"],
                "pass_rate": oracle["pass_rate"],
                "passed": oracle["passed"],
                "receipt_sha256": oracle["receipt_sha256"],
                "rerun_invalid_invocation_count": oracle["rerun_invalid_invocation_count"],
            },
            "readiness": {
                "artifact": readiness_record,
                "expected_routes": readiness["expected_routes"],
                "polls": readiness["polls"],
                "serving_route_generation": readiness["serving_route_generation"],
                "proxy_policy": readiness["proxy_policy"],
            },
            "tb4": _tb4_gate_record(tb4_record, tb4),
        },
        "ok": True,
        "production": {
            "approved_manifest": {**manifest_record, "count": EXPECTED_TASKS},
            "config": config_record,
            "contract": production_contract,
            "requested_lease_start_concurrency": requested_leases,
        },
        "schema_version": SCHEMA_VERSION,
        "source": {
            "oracle": oracle["oracle_source"],
            "production": oracle["production_source"],
        },
        "state": "passed",
    }
    if "source_wheel_recovery" in oracle:
        unsigned["gates"]["oracle_promotion"]["source_wheel_recovery"] = oracle["source_wheel_recovery"]
    final_endpoint = _load_current_endpoint(
        deployment_proxy_info,
        deployment_proxy_info_sha256,
        deployment_id=deployment_id,
        deployment_spec=Path(spec_record["path"]),
    ).binding
    if final_endpoint != endpoint:
        raise LaunchCertificateError("deployment_endpoint_changed")
    try:
        revalidate_deployment_proxy_policy(
            Path(spec_record["path"]),
            expected_spec_sha256=spec_record["sha256"],
            expected_binding=readiness["proxy_policy"],
            expected_request_timeout=KIMI_REQUEST_TIMEOUT,
        )
    except DeploymentProxyPolicyError as cause:
        raise LaunchCertificateError("deployment_proxy_policy_changed") from cause
    final_invocations, _ = _rehash_record(
        oracle["invocations"],
        label="oracle_invocations",
    )
    if final_invocations != oracle["invocations"]:
        raise LaunchCertificateError("oracle_invocations_changed")
    return unsigned


def _output_destination(path: Path) -> Path:
    configured = path.expanduser().absolute()
    if not configured.name:
        raise LaunchCertificateError("output_path_invalid")
    try:
        parent = configured.parent.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise LaunchCertificateError("output_parent_unreadable") from cause
    if not parent.is_dir():
        raise LaunchCertificateError("output_parent_unreadable")
    destination = parent / configured.name
    try:
        destination.lstat()
    except FileNotFoundError:
        return destination
    except OSError as cause:
        raise LaunchCertificateError("output_unreadable") from cause
    raise LaunchCertificateError("output_already_exists")


def _publish_write_once(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical_file(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fchmod(handle.fileno(), 0o444)
                os.fsync(handle.fileno())
        except OSError as cause:
            raise LaunchCertificateError("output_staging_failed") from cause
        try:
            os.link(temporary, path)
        except FileExistsError as cause:
            raise LaunchCertificateError("output_already_exists") from cause
        except OSError as cause:
            raise LaunchCertificateError("output_publish_failed") from cause
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as cause:
            raise LaunchCertificateError("output_publish_failed") from cause
    finally:
        temporary.unlink(missing_ok=True)
    _, observed = _stable_read(path, label="launch_certificate")
    if observed != encoded:
        raise LaunchCertificateError("output_verification_failed")


def create_launch_certificate(
    *,
    tb4_checkpoint: Path,
    tb4_checkpoint_sha256: str,
    oracle_receipt: Path,
    oracle_receipt_sha256: str,
    readiness_checkpoint: Path,
    readiness_checkpoint_sha256: str,
    capacity_smoke_checkpoint: Path,
    capacity_smoke_checkpoint_sha256: str,
    deployment_id: str,
    deployment_spec: Path,
    deployment_spec_sha256: str,
    deployment_proxy_info: Path,
    deployment_proxy_info_sha256: str,
    production_config: Path,
    approved_manifest: Path,
    approved_manifest_sha256: str,
    requested_lease_start_concurrency: int,
    output: Path,
) -> dict[str, Any]:
    """Validate all gates and publish one immutable launch certificate."""

    destination = _output_destination(output)
    unsigned = _build_unsigned(
        tb4_checkpoint=tb4_checkpoint,
        tb4_checkpoint_sha256=tb4_checkpoint_sha256,
        oracle_receipt=oracle_receipt,
        oracle_receipt_sha256=oracle_receipt_sha256,
        readiness_checkpoint=readiness_checkpoint,
        readiness_checkpoint_sha256=readiness_checkpoint_sha256,
        capacity_smoke_checkpoint=capacity_smoke_checkpoint,
        capacity_smoke_checkpoint_sha256=capacity_smoke_checkpoint_sha256,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        deployment_spec_sha256=deployment_spec_sha256,
        deployment_proxy_info=deployment_proxy_info,
        deployment_proxy_info_sha256=deployment_proxy_info_sha256,
        production_config=production_config,
        approved_manifest=approved_manifest,
        approved_manifest_sha256=approved_manifest_sha256,
        requested_lease_start_concurrency=requested_lease_start_concurrency,
    )
    certificate = {
        **unsigned,
        "launch_certificate_sha256": _sha256_bytes(_canonical_json(unsigned)),
    }
    if _output_destination(destination) != destination:
        raise LaunchCertificateError("output_path_changed")
    _publish_write_once(destination, certificate)
    return certificate


def _certificate_build_inputs(unsigned: dict[str, Any]) -> dict[str, Any]:
    deployment = unsigned.get("deployment")
    production = unsigned.get("production")
    gates = unsigned.get("gates")
    if not isinstance(deployment, dict) or not isinstance(production, dict) or not isinstance(gates, dict):
        raise LaunchCertificateError("launch_certificate_schema_invalid")
    spec = deployment.get("spec")
    endpoint = _endpoint_binding(deployment.get("endpoint"), label="launch_endpoint")
    config = production.get("config")
    manifest = production.get("approved_manifest")
    if not isinstance(spec, dict) or not isinstance(config, dict) or not isinstance(manifest, dict):
        raise LaunchCertificateError("launch_certificate_schema_invalid")

    gate_records: dict[str, dict[str, Any]] = {}
    for name in ("tb4", "oracle_promotion", "readiness", "capacity_smoke"):
        gate = gates.get(name)
        artifact = gate.get("artifact") if isinstance(gate, dict) else None
        if not isinstance(artifact, dict):
            raise LaunchCertificateError("launch_certificate_schema_invalid")
        gate_records[name] = artifact
    return {
        "approved_manifest": Path(str(manifest.get("path"))),
        "approved_manifest_sha256": manifest.get("sha256"),
        "capacity_smoke_checkpoint": Path(str(gate_records["capacity_smoke"].get("path"))),
        "capacity_smoke_checkpoint_sha256": gate_records["capacity_smoke"].get("sha256"),
        "deployment_id": deployment.get("id"),
        "deployment_spec": Path(str(spec.get("path"))),
        "deployment_spec_sha256": spec.get("sha256"),
        "deployment_proxy_info": Path(endpoint["proxy_info"]["path"]),
        "deployment_proxy_info_sha256": endpoint["proxy_info"]["sha256"],
        "oracle_receipt": Path(str(gate_records["oracle_promotion"].get("path"))),
        "oracle_receipt_sha256": gate_records["oracle_promotion"].get("sha256"),
        "production_config": Path(str(config.get("path"))),
        "readiness_checkpoint": Path(str(gate_records["readiness"].get("path"))),
        "readiness_checkpoint_sha256": gate_records["readiness"].get("sha256"),
        "requested_lease_start_concurrency": production.get("requested_lease_start_concurrency"),
        "tb4_checkpoint": Path(str(gate_records["tb4"].get("path"))),
        "tb4_checkpoint_sha256": gate_records["tb4"].get("sha256"),
    }


def _validate_launch_certificate(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Validate an externally pinned certificate and every aggregate prerequisite."""

    _, value = _pinned_json(path, expected_sha256, label="launch_certificate")
    expected_keys = {
        "artifact_type",
        "deployment",
        "gates",
        "launch_certificate_sha256",
        "ok",
        "production",
        "schema_version",
        "source",
        "state",
    }
    if set(value) != expected_keys:
        raise LaunchCertificateError("launch_certificate_schema_invalid")
    self_hash = _verify_flat_self_hash(
        value,
        "launch_certificate_sha256",
        label="launch_certificate",
    )
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_type") != ARTIFACT_TYPE
        or value.get("state") != "passed"
        or value.get("ok") is not True
    ):
        raise LaunchCertificateError("launch_certificate_not_passed")
    unsigned = dict(value)
    del unsigned["launch_certificate_sha256"]
    rebuilt = _build_unsigned(**_certificate_build_inputs(unsigned))
    if rebuilt != unsigned:
        raise LaunchCertificateError("launch_certificate_reconstruction_mismatch")
    if _sha256_bytes(_canonical_json(rebuilt)) != self_hash:
        raise LaunchCertificateError("launch_certificate_self_hash_mismatch")
    return value


def validate_launch_certificate_for_run(
    path: Path,
    expected_sha256: str,
    *,
    production_config: Path,
    approved_manifest: Path,
    approved_manifest_sha256: str,
    deployment_id: str,
    deployment_spec: Path,
    deployment_spec_sha256: str,
    deployment_proxy_info: Path,
    deployment_proxy_info_sha256: str,
    readiness_checkpoint: Path,
    readiness_checkpoint_sha256: str,
    capacity_smoke_checkpoint: Path,
    capacity_smoke_checkpoint_sha256: str,
    requested_lease_start_concurrency: int,
) -> dict[str, Any]:
    """Validate a certificate and bind it to the caller's exact live launch inputs."""

    certificate = _validate_launch_certificate(path, expected_sha256)
    config_record, _ = _file_record(production_config, label="expected_production_config")
    manifest_record, _ = _pinned_bytes(
        approved_manifest,
        approved_manifest_sha256,
        label="expected_approved_manifest",
    )
    spec_record, _ = _pinned_bytes(
        deployment_spec,
        deployment_spec_sha256,
        label="expected_deployment_spec",
    )
    endpoint = _load_current_endpoint(
        deployment_proxy_info,
        deployment_proxy_info_sha256,
        deployment_id=deployment_id,
        deployment_spec=Path(spec_record["path"]),
    ).binding
    readiness_record, _ = _pinned_bytes(
        readiness_checkpoint,
        readiness_checkpoint_sha256,
        label="expected_readiness_checkpoint",
    )
    capacity_record, _ = _pinned_bytes(
        capacity_smoke_checkpoint,
        capacity_smoke_checkpoint_sha256,
        label="expected_capacity_smoke_checkpoint",
    )
    requested_leases = _require_positive_int(
        requested_lease_start_concurrency,
        "expected_lease_start_concurrency",
    )
    production = certificate.get("production")
    deployment = certificate.get("deployment")
    gates = certificate.get("gates")
    readiness_gate = gates.get("readiness") if isinstance(gates, dict) else None
    capacity_gate = gates.get("capacity_smoke") if isinstance(gates, dict) else None
    if (
        not isinstance(production, dict)
        or not isinstance(deployment, dict)
        or not isinstance(readiness_gate, dict)
        or not isinstance(capacity_gate, dict)
        or production.get("config") != config_record
        or production.get("approved_manifest") != {**manifest_record, "count": EXPECTED_TASKS}
        or production.get("requested_lease_start_concurrency") != requested_leases
        or deployment.get("id") != deployment_id
        or deployment.get("endpoint") != endpoint
        or deployment.get("spec") != spec_record
        or readiness_gate.get("artifact") != readiness_record
        or capacity_gate.get("artifact") != capacity_record
    ):
        raise LaunchCertificateError("launch_inputs_mismatch")
    return certificate


def _positive_cli_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as cause:
        raise argparse.ArgumentTypeError("must be an integer") from cause
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _add_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tb4-checkpoint", type=Path, required=True)
    parser.add_argument("--tb4-checkpoint-sha256", required=True)
    parser.add_argument("--oracle-receipt", type=Path, required=True)
    parser.add_argument("--oracle-receipt-sha256", required=True)
    parser.add_argument("--readiness-checkpoint", type=Path, required=True)
    parser.add_argument("--readiness-checkpoint-sha256", required=True)
    parser.add_argument("--capacity-smoke-checkpoint", type=Path, required=True)
    parser.add_argument("--capacity-smoke-checkpoint-sha256", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--deployment-spec", type=Path, required=True)
    parser.add_argument("--deployment-spec-sha256", required=True)
    parser.add_argument("--deployment-proxy-info", type=Path, required=True)
    parser.add_argument("--deployment-proxy-info-sha256", required=True)
    parser.add_argument("--production-config", type=Path, required=True)
    parser.add_argument("--approved-manifest", type=Path, required=True)
    parser.add_argument("--approved-manifest-sha256", required=True)
    parser.add_argument(
        "--requested-lease-start-concurrency",
        type=_positive_cli_int,
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    _add_create_arguments(create_parser)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("certificate", type=Path)
    verify_parser.add_argument("--certificate-sha256", required=True)
    verify_parser.add_argument("--production-config", type=Path, required=True)
    verify_parser.add_argument("--approved-manifest", type=Path, required=True)
    verify_parser.add_argument("--approved-manifest-sha256", required=True)
    verify_parser.add_argument("--deployment-id", required=True)
    verify_parser.add_argument("--deployment-spec", type=Path, required=True)
    verify_parser.add_argument("--deployment-spec-sha256", required=True)
    verify_parser.add_argument("--deployment-proxy-info", type=Path, required=True)
    verify_parser.add_argument("--deployment-proxy-info-sha256", required=True)
    verify_parser.add_argument("--readiness-checkpoint", type=Path, required=True)
    verify_parser.add_argument("--readiness-checkpoint-sha256", required=True)
    verify_parser.add_argument("--capacity-smoke-checkpoint", type=Path, required=True)
    verify_parser.add_argument("--capacity-smoke-checkpoint-sha256", required=True)
    verify_parser.add_argument(
        "--requested-lease-start-concurrency",
        type=_positive_cli_int,
        required=True,
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            certificate = create_launch_certificate(
                tb4_checkpoint=args.tb4_checkpoint,
                tb4_checkpoint_sha256=args.tb4_checkpoint_sha256,
                oracle_receipt=args.oracle_receipt,
                oracle_receipt_sha256=args.oracle_receipt_sha256,
                readiness_checkpoint=args.readiness_checkpoint,
                readiness_checkpoint_sha256=args.readiness_checkpoint_sha256,
                capacity_smoke_checkpoint=args.capacity_smoke_checkpoint,
                capacity_smoke_checkpoint_sha256=args.capacity_smoke_checkpoint_sha256,
                deployment_id=args.deployment_id,
                deployment_spec=args.deployment_spec,
                deployment_spec_sha256=args.deployment_spec_sha256,
                deployment_proxy_info=args.deployment_proxy_info,
                deployment_proxy_info_sha256=args.deployment_proxy_info_sha256,
                production_config=args.production_config,
                approved_manifest=args.approved_manifest,
                approved_manifest_sha256=args.approved_manifest_sha256,
                requested_lease_start_concurrency=args.requested_lease_start_concurrency,
                output=args.output,
            )
            output = args.output.resolve(strict=True)
            _, file_sha256 = _stable_file_sha256(output, label="launch_certificate")
        else:
            certificate = validate_launch_certificate_for_run(
                args.certificate,
                args.certificate_sha256,
                production_config=args.production_config,
                approved_manifest=args.approved_manifest,
                approved_manifest_sha256=args.approved_manifest_sha256,
                deployment_id=args.deployment_id,
                deployment_spec=args.deployment_spec,
                deployment_spec_sha256=args.deployment_spec_sha256,
                deployment_proxy_info=args.deployment_proxy_info,
                deployment_proxy_info_sha256=args.deployment_proxy_info_sha256,
                readiness_checkpoint=args.readiness_checkpoint,
                readiness_checkpoint_sha256=args.readiness_checkpoint_sha256,
                capacity_smoke_checkpoint=args.capacity_smoke_checkpoint,
                capacity_smoke_checkpoint_sha256=args.capacity_smoke_checkpoint_sha256,
                requested_lease_start_concurrency=args.requested_lease_start_concurrency,
            )
            output = args.certificate.resolve(strict=True)
            file_sha256 = args.certificate_sha256
    except (LaunchCertificateError, OSError) as error:
        print(f"mobius_launch_certificate_error:{error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "certificate": str(output),
                "certificate_file_sha256": file_sha256,
                "launch_certificate_sha256": certificate["launch_certificate_sha256"],
                "ok": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
