#!/usr/bin/env python3
"""Compose approved private policy and launch artifacts for Qwen repair.

The composer never executes a worker, creates a sandbox, reads a task file, or
opens a credential.  Its stdout is aggregate-only.  Membership commitments,
paths, runtime digests, commands, and environment values remain in private
mode-0600 artifacts below the deployment namespace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import prepare_qwen_sandoq_catalog_plan as plan_generator
from materialize_qwen_provider_union import (
    DEPLOYMENT_NAMESPACE,
    MixedMaterializationError,
    _canonical_json,
    _open_private_output_root,
    _read_private_artifact,
    _read_regular,
    publish_exclusive,
    sha256,
)
from terminal_bench_vmvm.offline_verifier_catalog import (
    CatalogIdentity,
    catalog_consumer_code_sha256,
)
from terminal_bench_vmvm.offline_verifier_catalog_materializer import (
    MAX_SHARED_POOL_BUILD_CONCURRENCY,
    MAX_SHARED_POOL_PROBE_CONCURRENCY,
    MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
    materializer_controller_code_sha256,
)
from terminal_bench_vmvm.source_wheels import (
    canonical_json as compact_json,
)
from terminal_bench_vmvm.source_wheels import strict_json_loads
from terminal_bench_vmvm.taskset import (
    TerminalBenchVMVMConfig,
    offline_requirements_extractor_sha256,
)

SCHEMA_VERSION = 1
RUNTIME_KIND = "qwen-sandoq-repair-runtime-approval"
BINDING_KIND = "qwen-sandoq-repair-task-free-binding"
AUTHORIZATION_KIND = "qwen-sandoq-repair-launch-authorization"
LAUNCH_KIND = "qwen-sandoq-repair-launch-contract"
RECEIPT_KIND = "qwen-sandoq-repair-launch-composition"
MODEL = "Qwen3.8-2.4T-A95B"
TASK_COUNT = 1_233
ROLLOUT_CONCURRENCY = 64
HTTP_CONCURRENCY = 32
RAMP_COUNTS = (2, 8, 24, 64)
PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
MAX_PRIVATE_JSON_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 4 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_RE = re.compile(r"[0-9a-f]{40}")
ENVIRONMENT_RE = re.compile(r"[a-z][a-z0-9_-]{0,127}")

RUNTIME_ARTIFACT_KEYS = {
    "catalog_consumer_sha256",
    "catalog_materializer_sha256",
    "composer_sha256",
    "curl_sha256",
    "ecr_amd64_manifest_sha256",
    "ecr_config_sha256",
    "ecr_index_sha256",
    "generator_sha256",
    "host_harness_sha256",
    "provider_environment_context_sha256",
    "direct_connect_proxy_sha256",
    "requirements_extractor_sha256",
    "sealed_launcher_path_identity_sha256",
}
PROVISION_APPROVAL_KEYS = {
    "schema_version",
    "wheel_provenance",
    "binary_wheels_only",
    "no_index_install",
    "require_hashes_install",
    "dynamic_loader_sha256",
    "host_elf_manifest_sha256",
    "provision_identity_sha256",
    "python_executable_sha256",
    "python_runtime_manifest_sha256",
    "site_manifest_sha256",
    "worker_contract_sha256",
    "worker_runtime_sha256",
    "provider_commit",
    "provider_tree",
    "provider_source_sha256",
    "sandoq_client_version",
    "worker_site_manifest_sha256",
    "uv_sha256",
    "requirements_sha256",
    "origin_requirements_sha256",
    "wheel_origin_manifest_sha256",
    "network_provenance_sha256",
    "origin_tree_receipt_sha256",
    "wheel_set_sha256",
    "sealed_launcher_sha256",
    "worker_launcher_sha256",
    "worker_module_sha256",
    "controller_python_sha256",
}
WORKER_CONTRACT_KEYS = {
    "schema_version",
    "worker_protocol_version",
    "provider_commit",
    "provider_tree",
    "provider_source_sha256",
    "sandoq_client_version",
    "worker_runtime_sha256",
    "python_runtime_manifest_sha256",
    "worker_provision_identity_sha256",
    "worker_site_manifest_sha256",
    "cleanup_receipt_verifier_sha256",
    "inventory_probe_code_sha256",
    "inventory_probe_environment_sha256",
    "required_environment_names",
    "runtime_invariants",
}
REQUIRED_PARAMETERIZED_ENVIRONMENT_NAMES = {
    "OCI_RUNNER_BASE_URL",
    "OCI_RUNNER_ENVIRONMENT",
    "OCI_RUNNER_TASK_NETWORK",
    "OCI_RUNNER_TOKEN_FILE",
    "SANDOQ_CATALOG_EXCLUSIVE_POOL",
    "VF_SANDBOX_PROVIDER",
}


class LaunchCompositionError(ValueError):
    """Stable, aggregate-only composition failure."""


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise LaunchCompositionError("arguments_invalid")


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise LaunchCompositionError(code)
    raise LaunchCompositionError(code) from error


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _exact(value: object, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _fail(code)
    return value


def _parse_canonical(body: bytes, *, newline: bool, code: str) -> dict[str, Any]:
    if not 1 <= len(body) <= MAX_PRIVATE_JSON_BYTES:
        _fail(code)
    try:
        raw = strict_json_loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _fail(code, error)
    if not isinstance(raw, dict):
        _fail(code)
    expected = _canonical_json(raw) if newline else compact_json(raw)
    if body != expected:
        _fail(code)
    return raw


def _path_identity(
    path: Path,
    *,
    executable: bool,
    code: str,
    required_modes: frozenset[int] | None = None,
) -> tuple[bytes, str]:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        _fail(code)
    try:
        resolved = path.resolve(strict=True)
        listed = path.lstat()
        body = _read_regular(path)
        after = path.lstat()
    except (OSError, MixedMaterializationError) as error:
        _fail(code, error)
    if (
        resolved != path
        or not stat.S_ISREG(listed.st_mode)
        or listed.st_uid != os.geteuid()
        or listed.st_nlink != 1
        or bool(listed.st_mode & 0o022)
        or bool(listed.st_mode & stat.S_IXUSR) is not executable
        or (
            required_modes is not None
            and stat.S_IMODE(listed.st_mode) not in required_modes
        )
        or (
            listed.st_dev,
            listed.st_ino,
            listed.st_mode,
            listed.st_uid,
            listed.st_nlink,
            listed.st_size,
            listed.st_mtime_ns,
            listed.st_ctime_ns,
        )
        != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    ):
        _fail(code)
    identity = compact_json(
        {
            "schema_version": 1,
            "path": str(path),
            "device": listed.st_dev,
            "inode": listed.st_ino,
            "mode": stat.S_IMODE(listed.st_mode),
            "owner": listed.st_uid,
            "links": listed.st_nlink,
            "size": listed.st_size,
            "modified_ns": listed.st_mtime_ns,
            "changed_ns": listed.st_ctime_ns,
            "content_sha256": sha256(body),
        }
    )
    return body, sha256(identity)


def _source_sha256(path: Path) -> str:
    return sha256(_read_regular(path.resolve(strict=True)))


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _fail("runtime_code_identity_invalid", error)
    if result.stderr:
        _fail("runtime_code_identity_invalid")
    return result.stdout.strip()


def _code_identity(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    if root != project_root or not root.is_dir():
        _fail("runtime_code_identity_invalid")
    repositories = (
        root,
        root / "deps/verifiers",
        root / "deps/renderers",
        root / "deps/sandoq-provider",
    )
    if any(_git(repository, "status", "--porcelain=v1", "--untracked-files=all") for repository in repositories):
        _fail("runtime_code_identity_invalid")
    return {
        "project_revision": _git(root, "rev-parse", "HEAD"),
        "project_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "verifiers_revision": _git(root / "deps/verifiers", "rev-parse", "HEAD"),
        "renderers_revision": _git(root / "deps/renderers", "rev-parse", "HEAD"),
        "sandoq_provider_revision": _git(root / "deps/sandoq-provider", "rev-parse", "HEAD"),
    }


def _validate_provider_access(execution: Mapping[str, Any]) -> None:
    environment = execution["environment"]
    token_file = execution["token_file_path"]
    ecr_token_file = execution["ecr_token_file_path"]
    ecr_metadata = execution["ecr_token_metadata_path"]
    base_url = execution["base_url"]
    context = _exact(
        execution["provider_context"],
        {
            "startup_timeout_seconds",
            "lease_duration",
            "session_reuse",
            "pool_max_reuse_count",
            "image_cache_max_entries",
            "podman_fuse_overlayfs",
            "fuse_overlayfs_path",
            "libfuse3_path",
            "pull_timeout",
            "pull_poll_max_errors",
            "proxy_required",
            "proxy_bind_host",
            "proxy_target_port",
            "proxy_target_suffix",
            "proxy_environment_names",
            "cleared_proxy_environment_names",
            "vf_sandbox_provider_removed",
            "starts_before_provider",
            "lives_through_final_cleanup",
        },
        "runtime_approval_invalid",
    )
    try:
        parsed = urllib.parse.urlsplit(base_url)
    except (TypeError, ValueError) as error:
        _fail("runtime_approval_invalid", error)
    if (
        not isinstance(environment, str)
        or not ENVIRONMENT_RE.fullmatch(environment)
        or not isinstance(base_url, str)
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or any(
            not isinstance(item, str)
            or not Path(item).is_absolute()
            or Path(item) != Path(os.path.normpath(item))
            for item in (token_file, ecr_token_file, ecr_metadata)
        )
        or len({token_file, ecr_token_file, ecr_metadata}) != 3
        or "FIRECRACKER_KEY" in execution
        or context
        != {
            "startup_timeout_seconds": 3_600,
            "lease_duration": "1h",
            "session_reuse": 1,
            "pool_max_reuse_count": 1,
            "image_cache_max_entries": 0,
            "podman_fuse_overlayfs": 1,
            "fuse_overlayfs_path": "/usr/bin/fuse-overlayfs",
            "libfuse3_path": "/lib/x86_64-linux-gnu/libfuse3.so.3",
            "pull_timeout": "3600s",
            "pull_poll_max_errors": 20,
            "proxy_required": True,
            "proxy_bind_host": "127.0.0.1",
            "proxy_target_port": 443,
            "proxy_target_suffix": ".metafb.cloud",
            "proxy_environment_names": ["HTTPS_PROXY", "https_proxy"],
            "cleared_proxy_environment_names": list(PROXY_ENVIRONMENT_NAMES),
            "vf_sandbox_provider_removed": True,
            "starts_before_provider": True,
            "lives_through_final_cleanup": True,
        }
    ):
        _fail("runtime_approval_invalid")


@dataclass(frozen=True)
class RuntimeApproval:
    body: bytes
    sha256: str
    value: dict[str, Any]


@dataclass(frozen=True)
class RepairBinding:
    body: bytes
    sha256: str
    value: dict[str, Any]


def _hash_list(value: object, code: str, *, allow_empty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or value != sorted(set(value))
        or (not allow_empty and not value)
        or not all(_is_sha256(item) for item in value)
    ):
        _fail(code)
    return value


def _load_runtime_approval(
    body: bytes,
    expected_sha256: str,
    *,
    project_root: Path,
) -> RuntimeApproval:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("runtime_approval_invalid")
    value = _exact(
        _parse_canonical(body, newline=True, code="runtime_approval_invalid"),
        {
            "schema_version",
            "kind",
            "state",
            "deployment_namespace",
            "model",
            "repair_binding_sha256",
            "expected_catalog_policy_sha256",
            "code",
            "provider",
            "runtime_artifacts",
            "provision_approval_sha256",
            "provision_approval",
            "catalog_policy",
            "serving",
            "execution",
            "ramps",
            "trust_boundary",
        },
        "runtime_approval_invalid",
    )
    code = _exact(
        value["code"],
        {
            "project_revision",
            "project_tree",
            "verifiers_revision",
            "renderers_revision",
            "sandoq_provider_revision",
        },
        "runtime_approval_invalid",
    )
    provider = _exact(
        value["provider"],
        {"commit", "tree", "source_sha256", "client_version"},
        "runtime_approval_invalid",
    )
    artifacts = _exact(
        value["runtime_artifacts"],
        RUNTIME_ARTIFACT_KEYS,
        "runtime_approval_invalid",
    )
    provision = _exact(
        value["provision_approval"],
        PROVISION_APPROVAL_KEYS,
        "runtime_approval_invalid",
    )
    policy = _exact(
        value["catalog_policy"],
        {
            "worker_environment_names",
            "worker_environment_sha256",
            "worker_runtime_invariants",
            "worker_recovery_scope_sha256",
            "cleanup_receipt_verifier_sha256",
            "ecr_rotator_sha256",
            "inventory_probe_approval_sha256",
            "source_policy_sha256",
            "source_policy_approval_sha256",
            "approved_binary_artifacts",
            "approved_source_attestations",
            "approved_toolchains",
            "timeouts_seconds",
            "concurrency",
        },
        "runtime_approval_invalid",
    )
    serving = _exact(
        value["serving"],
        {
            "deployment_id",
            "worker_count",
            "healthy_workers",
            "identity_matched_workers",
            "spec_sha256",
            "endpoint_bundle_sha256",
            "worker_manifest_sha256",
            "routing_policy",
            "request_id_header",
        },
        "runtime_approval_invalid",
    )
    execution = _exact(
        value["execution"],
        {
            "sandbox_provider",
            "environment",
            "base_url",
            "token_file_path",
            "ecr_token_file_path",
            "ecr_token_metadata_path",
            "provider_context",
            "task_network",
            "host_tunnel",
            "host_harness",
            "rollout_concurrency",
            "provider_pool_capacity",
            "lease_create_cap",
            "http_max_connections",
            "http_max_keepalive_connections",
            "max_turns",
            "client_timeout_seconds",
            "connect_timeout_seconds",
            "runtime_session_timeout_seconds",
            "max_sequence_tokens",
            "sampling_max_tokens",
            "phase_timeouts_seconds",
            "capture_model_io",
            "preserve_thinking",
            "reasoning_effort",
            "cleanup_must_succeed",
            "fresh_output_required",
            "resume_allowed",
        },
        "runtime_approval_invalid",
    )
    trust = _exact(
        value["trust_boundary"],
        {
            "x86_64_required",
            "exclusive_job_required",
            "exclusive_catalog_epoch_required",
            "credential_values_recorded",
            "production_task_inputs_accessed",
        },
        "runtime_approval_invalid",
    )
    ramps = value["ramps"]
    timeout_values = _exact(
        policy["timeouts_seconds"],
        {"recover", "probe", "build", "validate"},
        "runtime_approval_invalid",
    )
    concurrency = _exact(
        policy["concurrency"],
        {"probe", "build", "validate"},
        "runtime_approval_invalid",
    )
    phase_timeouts = _exact(
        execution["phase_timeouts_seconds"],
        {"setup", "rollout", "finalize", "scoring"},
        "runtime_approval_invalid",
    )
    runtime_invariants = policy["worker_runtime_invariants"]
    if (
        not isinstance(runtime_invariants, dict)
        or not runtime_invariants
        or not all(
            isinstance(key, str) and key and isinstance(item, str)
            for key, item in runtime_invariants.items()
        )
    ):
        _fail("runtime_approval_invalid")
    _validate_provider_access(execution)
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["kind"] != RUNTIME_KIND
        or value["state"] != "approved"
        or value["deployment_namespace"] != DEPLOYMENT_NAMESPACE
        or value["model"] != MODEL
        or not _is_sha256(value["repair_binding_sha256"])
        or not _is_sha256(value["expected_catalog_policy_sha256"])
        or code != _code_identity(project_root)
        or not all(isinstance(item, str) and GIT_RE.fullmatch(item) for item in code.values())
        or provider["commit"] != code["sandoq_provider_revision"]
        or not isinstance(provider["commit"], str)
        or GIT_RE.fullmatch(provider["commit"]) is None
        or not isinstance(provider["tree"], str)
        or GIT_RE.fullmatch(provider["tree"]) is None
        or not _is_sha256(provider["source_sha256"])
        or not isinstance(provider["client_version"], str)
        or not provider["client_version"]
        or not all(_is_sha256(item) for item in artifacts.values())
        or not _is_sha256(value["provision_approval_sha256"])
        or value["provision_approval_sha256"] != sha256(compact_json(provision))
        or provision["schema_version"] != 1
        or provision["wheel_provenance"]
        != "approved_tls_origin_with_independent_refetch"
        or provision["binary_wheels_only"] is not True
        or provision["no_index_install"] is not True
        or provision["require_hashes_install"] is not True
        or not all(
            _is_sha256(provision[key])
            for key in PROVISION_APPROVAL_KEYS
            - {
                "schema_version",
                "wheel_provenance",
                "binary_wheels_only",
                "no_index_install",
                "require_hashes_install",
                "provider_commit",
                "provider_tree",
                "sandoq_client_version",
            }
        )
        or provision["provider_commit"] != provider["commit"]
        or provision["provider_tree"] != provider["tree"]
        or provision["provider_source_sha256"] != provider["source_sha256"]
        or provision["sandoq_client_version"] != provider["client_version"]
        or artifacts["composer_sha256"] != _source_sha256(Path(__file__))
        or artifacts["generator_sha256"] != _source_sha256(Path(plan_generator.__file__))
        or artifacts["catalog_materializer_sha256"] != materializer_controller_code_sha256()
        or artifacts["catalog_consumer_sha256"] != catalog_consumer_code_sha256()
        or artifacts["requirements_extractor_sha256"]
        != offline_requirements_extractor_sha256()
        or artifacts["host_harness_sha256"]
        != _source_sha256(
            project_root
            / "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/sandoq_host_harness.py"
        )
        or not isinstance(policy["worker_environment_names"], list)
        or policy["worker_environment_names"]
        != sorted(set(policy["worker_environment_names"]))
        or not all(isinstance(item, str) and item for item in policy["worker_environment_names"])
        or not REQUIRED_PARAMETERIZED_ENVIRONMENT_NAMES.issubset(
            policy["worker_environment_names"]
        )
        or "FIRECRACKER_KEY" in policy["worker_environment_names"]
        or runtime_invariants != dict(sorted(runtime_invariants.items()))
        or runtime_invariants.get("OCI_RUNNER_ENVIRONMENT") != execution["environment"]
        or runtime_invariants.get("OCI_RUNNER_TASK_NETWORK") != "none"
        or runtime_invariants.get("SANDOQ_CATALOG_EXCLUSIVE_POOL") != "1"
        or runtime_invariants.get("VF_SANDBOX_PROVIDER") != "sandoq"
        or "FIRECRACKER_KEY" in runtime_invariants
        or not all(
            _is_sha256(policy[key])
            for key in (
                "worker_environment_sha256",
                "worker_recovery_scope_sha256",
                "cleanup_receipt_verifier_sha256",
                "ecr_rotator_sha256",
                "inventory_probe_approval_sha256",
                "source_policy_sha256",
                "source_policy_approval_sha256",
            )
        )
        or not all(type(item) is int and 1 <= item <= 86_400 for item in timeout_values.values())
        or concurrency
        != {
            "probe": MAX_SHARED_POOL_PROBE_CONCURRENCY,
            "build": MAX_SHARED_POOL_BUILD_CONCURRENCY,
            "validate": MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
        }
        or serving["deployment_id"] != DEPLOYMENT_NAMESPACE
        or serving["worker_count"] != 24
        or serving["healthy_workers"] != 24
        or serving["identity_matched_workers"] != 24
        or not all(
            _is_sha256(serving[key])
            for key in ("spec_sha256", "endpoint_bundle_sha256", "worker_manifest_sha256")
        )
        or serving["routing_policy"] != "consistent_hash"
        or serving["request_id_header"] != "x-session-id"
        or execution["sandbox_provider"] != "sandoq"
        or execution["task_network"] != "none"
        or execution["host_tunnel"] != "none"
        or execution["host_harness"] is not True
        or execution["rollout_concurrency"] != ROLLOUT_CONCURRENCY
        or type(execution["provider_pool_capacity"]) is not int
        or execution["provider_pool_capacity"] < ROLLOUT_CONCURRENCY
        or type(execution["lease_create_cap"]) is not int
        or not 1 <= execution["lease_create_cap"] <= execution["provider_pool_capacity"]
        or execution["http_max_connections"] != HTTP_CONCURRENCY
        or execution["http_max_keepalive_connections"] != HTTP_CONCURRENCY
        or execution["max_turns"] != 200
        or execution["client_timeout_seconds"] != 7_200
        or execution["connect_timeout_seconds"] != 30
        or execution["runtime_session_timeout_seconds"] != 43_200
        or execution["max_sequence_tokens"] != 262_144
        or execution["sampling_max_tokens"] != 32_768
        or phase_timeouts != plan_generator.EXPECTED_PHASE_TIMEOUTS
        or execution["capture_model_io"] is not True
        or execution["preserve_thinking"] is not True
        or execution["reasoning_effort"] != "max"
        or execution["cleanup_must_succeed"] is not True
        or execution["fresh_output_required"] is not True
        or execution["resume_allowed"] is not False
        or not isinstance(ramps, list)
        or len(ramps) != len(RAMP_COUNTS)
        or trust
        != {
            "x86_64_required": True,
            "exclusive_job_required": True,
            "exclusive_catalog_epoch_required": True,
            "credential_values_recorded": False,
            "production_task_inputs_accessed": False,
        }
    ):
        _fail("runtime_approval_invalid")
    for expected_count, item in zip(RAMP_COUNTS, ramps, strict=True):
        ramp = _exact(
            item,
            {"stage_count", "state", "measured", "certificate_sha256"},
            "runtime_approval_invalid",
        )
        if ramp != {
            "stage_count": expected_count,
            "state": "passed",
            "measured": True,
            "certificate_sha256": ramp["certificate_sha256"],
        } or not _is_sha256(ramp["certificate_sha256"]):
            _fail("runtime_approval_invalid")
    _hash_list(policy["approved_binary_artifacts"], "runtime_approval_invalid")
    _hash_list(policy["approved_source_attestations"], "runtime_approval_invalid")
    _hash_list(policy["approved_toolchains"], "runtime_approval_invalid", allow_empty=False)
    return RuntimeApproval(body=body, sha256=expected_sha256, value=value)


def _load_repair_binding(body: bytes, expected_sha256: str) -> RepairBinding:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("repair_binding_invalid")
    value = _exact(
        _parse_canonical(body, newline=True, code="repair_binding_invalid"),
        {
            "schema_version",
            "kind",
            "state",
            "deployment_namespace",
            "counts",
            "provider_materialization_receipt_sha256",
            "repair_selection_manifest_sha256",
            "repair_union_indices_sha256",
            "task_file_sha256",
            "task_file_path_sha256",
            "source_config_sha256",
            "source_config_path_sha256",
            "dataset_revision",
            "dataset_path_sha256",
            "image_manifest_sha256",
            "image_manifest_path_sha256",
        },
        "repair_binding_invalid",
    )
    counts = _exact(value["counts"], {"repair", "sandoq", "vmvm"}, "repair_binding_invalid")
    digest_keys = set(value) - {
        "schema_version",
        "kind",
        "state",
        "deployment_namespace",
        "counts",
        "dataset_revision",
    }
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["kind"] != BINDING_KIND
        or value["state"] != "sealed"
        or value["deployment_namespace"] != DEPLOYMENT_NAMESPACE
        or counts != {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0}
        or not isinstance(value["dataset_revision"], str)
        or GIT_RE.fullmatch(value["dataset_revision"]) is None
        or not all(_is_sha256(value[key]) for key in digest_keys)
    ):
        _fail("repair_binding_invalid")
    return RepairBinding(body=body, sha256=expected_sha256, value=value)


def _validate_worker_runtime(
    body: bytes,
    expected_sha256: str,
    *,
    runtime: RuntimeApproval,
    worker_executable: Path,
) -> tuple[dict[str, Any], bytes]:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("worker_runtime_contract_invalid")
    contract = _exact(
        _parse_canonical(
            body,
            newline=False,
            code="worker_runtime_contract_invalid",
        ),
        WORKER_CONTRACT_KEYS,
        "worker_runtime_contract_invalid",
    )
    approval = runtime.value["provision_approval"]
    artifacts = runtime.value["runtime_artifacts"]
    worker_body, path_identity_sha256 = _path_identity(
        worker_executable,
        executable=True,
        code="sealed_launcher_invalid",
        required_modes=frozenset({0o500}),
    )
    if (
        body != compact_json(contract)
        or expected_sha256 != approval["worker_contract_sha256"]
        or contract["schema_version"] != 1
        or contract["worker_protocol_version"] != 2
        or sha256(worker_body) != approval["sealed_launcher_sha256"]
        or path_identity_sha256 != artifacts["sealed_launcher_path_identity_sha256"]
        or contract["provider_commit"] != runtime.value["provider"]["commit"]
        or contract["provider_commit"] != approval["provider_commit"]
        or contract["provider_tree"] != approval["provider_tree"]
        or contract["provider_source_sha256"] != approval["provider_source_sha256"]
        or contract["sandoq_client_version"] != approval["sandoq_client_version"]
        or contract["worker_runtime_sha256"] != approval["worker_runtime_sha256"]
        or contract["python_runtime_manifest_sha256"]
        != approval["python_runtime_manifest_sha256"]
        or contract["worker_provision_identity_sha256"]
        != approval["provision_identity_sha256"]
        or contract["worker_site_manifest_sha256"]
        != approval["worker_site_manifest_sha256"]
        or contract["cleanup_receipt_verifier_sha256"]
        != runtime.value["catalog_policy"]["cleanup_receipt_verifier_sha256"]
        or contract["required_environment_names"]
        != runtime.value["catalog_policy"]["worker_environment_names"]
        or contract["runtime_invariants"]
        != runtime.value["catalog_policy"]["worker_runtime_invariants"]
    ):
        _fail("worker_runtime_contract_invalid")
    return contract, worker_body


def _catalog_policy_value(
    runtime: RuntimeApproval,
    binding: RepairBinding,
    worker_contract: Mapping[str, Any],
    worker_executable_sha256: str,
) -> dict[str, Any]:
    runtime_value = runtime.value
    policy = runtime_value["catalog_policy"]
    artifacts = runtime_value["runtime_artifacts"]
    value = {
        "schema_version": plan_generator.SCHEMA_VERSION,
        "kind": plan_generator.KIND,
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "expected_counts": {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0},
        "generator_sha256": artifacts["generator_sha256"],
        "provider_materialization_receipt_sha256": binding.value[
            "provider_materialization_receipt_sha256"
        ],
        "worker_contract_sha256": runtime_value["provision_approval"][
            "worker_contract_sha256"
        ],
        "worker": {
            "executable_sha256": worker_executable_sha256,
            "runtime_sha256": worker_contract["worker_runtime_sha256"],
            "materializer_code_sha256": artifacts["catalog_materializer_sha256"],
            "cleanup_receipt_verifier_sha256": worker_contract[
                "cleanup_receipt_verifier_sha256"
            ],
            "environment_sha256": policy["worker_environment_sha256"],
            "recovery_scope_sha256": policy["worker_recovery_scope_sha256"],
            "ecr_rotator_sha256": policy["ecr_rotator_sha256"],
            "environment_names": policy["worker_environment_names"],
            "timeouts_seconds": policy["timeouts_seconds"],
            "concurrency": policy["concurrency"],
        },
        "catalog_policy": {
            "inventory_probe_code_sha256": worker_contract["inventory_probe_code_sha256"],
            "inventory_probe_environment_sha256": worker_contract[
                "inventory_probe_environment_sha256"
            ],
            "inventory_probe_approval_sha256": policy[
                "inventory_probe_approval_sha256"
            ],
            "catalog_consumer_code_sha256": artifacts["catalog_consumer_sha256"],
            "requirements_extractor_sha256": artifacts[
                "requirements_extractor_sha256"
            ],
            "source_policy_sha256": policy["source_policy_sha256"],
            "source_policy_approval_sha256": policy["source_policy_approval_sha256"],
            "approved_binary_artifacts": policy["approved_binary_artifacts"],
            "approved_source_attestations": policy["approved_source_attestations"],
            "approved_toolchains": policy["approved_toolchains"],
        },
    }
    payload = _canonical_json(value)
    if sha256(payload) != runtime_value["expected_catalog_policy_sha256"]:
        _fail("catalog_policy_not_approved")
    return value


def compose_policy(
    *,
    project_root: Path,
    dataset_root: Path,
    private_output_root: Path,
    runtime_approval: Path,
    runtime_approval_sha256: str,
    repair_binding: Path,
    repair_binding_sha256: str,
    worker_contract: Path,
    worker_contract_sha256: str,
    worker_executable: Path,
    output: Path,
) -> dict[str, int]:
    private_paths = (runtime_approval, repair_binding, worker_contract, output)
    try:
        with _open_private_output_root(
            private_output_root,
            private_paths,
            forbidden_roots=(project_root, dataset_root),
            validate_existing=False,
        ) as opened:
            runtime_body = _read_private_artifact(opened, runtime_approval)
            binding_body = _read_private_artifact(opened, repair_binding)
            worker_contract_body = _read_private_artifact(opened, worker_contract)
            runtime = _load_runtime_approval(
                runtime_body,
                runtime_approval_sha256,
                project_root=project_root,
            )
            binding = _load_repair_binding(binding_body, repair_binding_sha256)
            if runtime.value["repair_binding_sha256"] != binding.sha256:
                _fail("repair_binding_not_approved")
            contract, worker_body = _validate_worker_runtime(
                worker_contract_body,
                worker_contract_sha256,
                runtime=runtime,
                worker_executable=worker_executable,
            )
            policy_value = _catalog_policy_value(
                runtime,
                binding,
                contract,
                sha256(worker_body),
            )
            if (
                _read_private_artifact(opened, runtime_approval) != runtime_body
                or _read_private_artifact(opened, repair_binding) != binding_body
                or _read_private_artifact(opened, worker_contract) != worker_contract_body
            ):
                _fail("composition_input_changed")
            publish_exclusive(opened, [(output, _canonical_json(policy_value))])
    except LaunchCompositionError:
        raise
    except (OSError, MixedMaterializationError, ValueError) as error:
        _fail("policy_composition_invalid", error)
    return {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0}


def _load_catalog_identity(body: bytes, expected_sha256: str) -> CatalogIdentity:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("catalog_identity_invalid")
    raw = _parse_canonical(body, newline=False, code="catalog_identity_invalid")
    try:
        identity = CatalogIdentity(**raw)
    except (TypeError, ValueError) as error:
        _fail("catalog_identity_invalid", error)
    if identity.expected_task_count != TASK_COUNT:
        _fail("catalog_identity_invalid")
    return identity


def _load_plan_receipt(
    body: bytes,
    expected_sha256: str,
    *,
    runtime: RuntimeApproval,
    binding: RepairBinding,
    identity: CatalogIdentity,
    plan_sha256: str,
) -> dict[str, Any]:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("plan_receipt_invalid")
    value = _exact(
        _parse_canonical(body, newline=True, code="plan_receipt_invalid"),
        {
            "schema_version",
            "kind",
            "state",
            "deployment_namespace",
            "counts",
            "bindings",
            "private_set_commitments",
            "runtime_contract",
        },
        "plan_receipt_invalid",
    )
    counts = _exact(
        value["counts"],
        {
            "tasks",
            "sandoq",
            "vmvm",
            "images",
            "probe_groups",
            "requirement_sets",
            "shared_agent",
            "separate_verifier",
        },
        "plan_receipt_invalid",
    )
    bindings = _exact(
        value["bindings"],
        {
            "plan_sha256",
            "identity_sha256",
            "policy_sha256",
            "generator_sha256",
            "provider_materialization_receipt_sha256",
            "sandoq_config_sha256",
            "worker_contract_sha256",
        },
        "plan_receipt_invalid",
    )
    commitments = _exact(
        value["private_set_commitments"],
        {"assignments", "probe_groups", "requirement_sets"},
        "plan_receipt_invalid",
    )
    for name, expected_count in (
        ("assignments", TASK_COUNT),
        ("probe_groups", counts["probe_groups"]),
        ("requirement_sets", counts["requirement_sets"]),
    ):
        item = _exact(commitments[name], {"unique_count", "set_sha256"}, "plan_receipt_invalid")
        if item["unique_count"] != expected_count or not _is_sha256(item["set_sha256"]):
            _fail("plan_receipt_invalid")
    runtime_contract = _exact(
        value["runtime_contract"],
        {
            "provider",
            "environment",
            "task_network",
            "host_harness",
            "rollout_retries",
            "verifier_runtime_retries",
            "catalog_epoch_exclusive",
            "probe_concurrency",
            "build_concurrency",
            "validate_concurrency",
        },
        "plan_receipt_invalid",
    )
    approval = runtime.value
    if (
        value["schema_version"] != plan_generator.SCHEMA_VERSION
        or value["kind"] != plan_generator.KIND
        or value["state"] != "sealed"
        or value["deployment_namespace"] != DEPLOYMENT_NAMESPACE
        or counts["tasks"] != TASK_COUNT
        or counts["sandoq"] != TASK_COUNT
        or counts["vmvm"] != 0
        or counts["shared_agent"] + counts["separate_verifier"] != TASK_COUNT
        or not all(type(counts[key]) is int and counts[key] >= 0 for key in counts)
        or bindings["plan_sha256"] != plan_sha256
        or bindings["identity_sha256"] != identity.sha256
        or bindings["policy_sha256"] != approval["expected_catalog_policy_sha256"]
        or bindings["generator_sha256"] != approval["runtime_artifacts"]["generator_sha256"]
        or bindings["provider_materialization_receipt_sha256"]
        != binding.value["provider_materialization_receipt_sha256"]
        or bindings["sandoq_config_sha256"] != binding.value["source_config_sha256"]
        or bindings["worker_contract_sha256"]
        != approval["provision_approval"]["worker_contract_sha256"]
        or runtime_contract
        != {
            "provider": "sandoq",
            "environment": approval["execution"]["environment"],
            "task_network": "none",
            "host_harness": True,
            "rollout_retries": 0,
            "verifier_runtime_retries": 0,
            "catalog_epoch_exclusive": True,
            "probe_concurrency": MAX_SHARED_POOL_PROBE_CONCURRENCY,
            "build_concurrency": MAX_SHARED_POOL_BUILD_CONCURRENCY,
            "validate_concurrency": MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
        }
    ):
        _fail("plan_receipt_invalid")
    return value


def _load_catalog_launch(body: bytes, expected_sha256: str) -> dict[str, Any]:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("catalog_launch_receipt_invalid")
    value = _exact(
        _parse_canonical(body, newline=False, code="catalog_launch_receipt_invalid"),
        {
            "schema_version",
            "catalog_file",
            "catalog_sha256",
            "identity_sha256",
            "expected_task_count",
            "provider_epoch",
            "provider_recovery",
        },
        "catalog_launch_receipt_invalid",
    )
    recovery = _exact(
        value["provider_recovery"],
        {
            "durable_provider_wal",
            "recovery_attempted",
            "remaining_sessions",
            "cleanup_receipts_verified",
            "recovery_scope_sha256",
            "phase",
            "wal_snapshot_sha256",
            "recovery_receipt_sha256",
            "receipt_verifier_sha256",
            "anchor_liveness",
        },
        "catalog_launch_receipt_invalid",
    )
    anchor = _exact(
        recovery["anchor_liveness"],
        {"active_client_registered", "heartbeat_checks", "stop_received"},
        "catalog_launch_receipt_invalid",
    )
    if (
        value["schema_version"] != 2
        or value["catalog_file"] != "catalog.json"
        or not _is_sha256(value["catalog_sha256"])
        or not _is_sha256(value["identity_sha256"])
        or value["expected_task_count"] != TASK_COUNT
        or value["provider_epoch"]
        != {"exclusive_socket_lock": True, "exclusive_wal_lock": True}
        or recovery["durable_provider_wal"] is not True
        or recovery["recovery_attempted"] is not True
        or recovery["remaining_sessions"] != 0
        or recovery["cleanup_receipts_verified"] is not True
        or recovery["phase"] != "final"
        or not all(
            _is_sha256(recovery[key])
            for key in (
                "recovery_scope_sha256",
                "wal_snapshot_sha256",
                "recovery_receipt_sha256",
                "receipt_verifier_sha256",
            )
        )
        or anchor["active_client_registered"] is not True
        or type(anchor["heartbeat_checks"]) is not int
        or anchor["heartbeat_checks"] < 0
        or anchor["stop_received"] is not True
    ):
        _fail("catalog_launch_receipt_invalid")
    return value


def _load_launch_authorization(body: bytes, expected_sha256: str) -> dict[str, Any]:
    if not _is_sha256(expected_sha256) or sha256(body) != expected_sha256:
        _fail("launch_authorization_invalid")
    value = _exact(
        _parse_canonical(body, newline=True, code="launch_authorization_invalid"),
        {
            "schema_version",
            "kind",
            "state",
            "runtime_approval_sha256",
            "repair_binding_sha256",
            "source_config_sha256",
            "plan_sha256",
            "plan_receipt_sha256",
            "catalog_identity_sha256",
            "catalog_launch_receipt_sha256",
            "catalog_sha256",
            "expected_eval_config_sha256",
            "expected_launch_contract_sha256",
        },
        "launch_authorization_invalid",
    )
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["kind"] != AUTHORIZATION_KIND
        or value["state"] != "approved"
        or not all(
            _is_sha256(value[key])
            for key in set(value) - {"schema_version", "kind", "state"}
        )
    ):
        _fail("launch_authorization_invalid")
    return value


def _path_sha256(path: Path) -> str:
    return sha256(str(path).encode("utf-8"))


def _validate_source_config(
    body: bytes,
    path: Path,
    binding: RepairBinding,
    runtime: RuntimeApproval,
) -> tuple[dict[str, Any], TerminalBenchVMVMConfig]:
    if (
        len(body) > MAX_CONFIG_BYTES
        or sha256(body) != binding.value["source_config_sha256"]
        or _path_sha256(path) != binding.value["source_config_path_sha256"]
    ):
        _fail("source_config_invalid")
    try:
        raw = tomllib.loads(body.decode("utf-8"))
        taskset_raw = raw["taskset"]
        config = TerminalBenchVMVMConfig.model_validate(taskset_raw)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        _fail("source_config_invalid", error)
    client = raw.get("client")
    sampling = raw.get("sampling")
    harness = raw.get("harness")
    harness_runtime = harness.get("runtime") if isinstance(harness, dict) else None
    retries = raw.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
    execution = runtime.value["execution"]
    task_file = config.task_file
    dataset = config.dataset_dir
    image_manifest = config.image_manifest
    if (
        raw.get("model") != MODEL
        or raw.get("num_tasks") != TASK_COUNT
        or raw.get("num_rollouts") != 1
        or raw.get("max_concurrent") != execution["rollout_concurrency"]
        or raw.get("multiplex") != execution["rollout_concurrency"]
        or raw.get("max_turns") != execution["max_turns"]
        or raw.get("max_input_tokens") != execution["max_sequence_tokens"]
        or raw.get("max_output_tokens") != execution["max_sequence_tokens"]
        or raw.get("max_total_tokens") != execution["max_sequence_tokens"]
        or raw.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not execution["capture_model_io"]
        or client.get("outbound_body_denylist") != plan_generator.EXPECTED_OUTBOUND_DENYLIST
        or client.get("base_url") != "http://127.0.0.1:8000/v1"
        or client.get("api_key_var") != "OPENAI_API_KEY"
        or client.get("timeout") != execution["client_timeout_seconds"]
        or client.get("connect_timeout") != execution["connect_timeout_seconds"]
        or client.get("max_connections") != execution["http_max_connections"]
        or client.get("max_keepalive_connections")
        != execution["http_max_keepalive_connections"]
        or not isinstance(sampling, dict)
        or sampling.get("reasoning_effort") != execution["reasoning_effort"]
        or sampling.get("temperature") != 0.7
        or sampling.get("top_p") != 0.95
        or sampling.get("top_k") != 20
        or sampling.get("max_tokens") != execution["sampling_max_tokens"]
        or sampling.get("chat_template_kwargs")
        != {"enable_thinking": True, "preserve_thinking": execution["preserve_thinking"]}
        or not isinstance(harness, dict)
        or harness.get("id") != "terminal-bench-sandoq-host"
        or harness.get("command_timeout_seconds") != 240
        or harness.get("command_kill_grace_seconds") != 10
        or harness.get("max_command_output_chars") != 100_000
        or harness.get("request_timeout_seconds") != 15_000
        or not isinstance(harness_runtime, dict)
        or harness_runtime.get("type") != execution["sandbox_provider"]
        or harness_runtime.get("mode") != "oci-runner"
        or harness_runtime.get("session_timeout")
        != execution["runtime_session_timeout_seconds"]
        or harness_runtime.get("network_access") is not False
        or harness_runtime.get("host_tunnel") != execution["host_tunnel"]
        or harness_runtime.get("expected_environment") != execution["environment"]
        or harness_runtime.get("ecr_token_file") != execution["ecr_token_file_path"]
        or raw.get("timeout") != execution["phase_timeouts_seconds"]
        or not isinstance(rollout_retries, dict)
        or rollout_retries.get("max_retries") != 0
        or config.verifier_runtime_retries != 0
        or config.enable_compose
        or config.tasks is not None
        or task_file is None
        or not task_file.is_absolute()
        or _path_sha256(task_file) != binding.value["task_file_path_sha256"]
        or config.task_file_sha256 != binding.value["task_file_sha256"]
        or not dataset.is_absolute()
        or _path_sha256(dataset) != binding.value["dataset_path_sha256"]
        or config.dataset_revision != binding.value["dataset_revision"]
        or image_manifest is None
        or not image_manifest.is_absolute()
        or _path_sha256(image_manifest) != binding.value["image_manifest_path_sha256"]
        or config.image_manifest_sha256 != binding.value["image_manifest_sha256"]
        or any(
            item is not None
            for item in (
                config.offline_verifier_catalog,
                config.offline_verifier_catalog_sha256,
                config.offline_verifier_catalog_identity,
                config.offline_verifier_catalog_task_file,
                config.offline_verifier_catalog_task_file_sha256,
                config.offline_verifier_project_root,
            )
        )
    ):
        _fail("source_config_invalid")
    return raw, config


def _render_eval_config(
    source: bytes,
    *,
    catalog_path: Path,
    catalog_sha256: str,
    project_root: Path,
    task_file: Path,
    task_file_sha256: str,
    identity: CatalogIdentity,
) -> bytes:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("eval_config_invalid", error)
    if (
        not text.endswith("\n")
        or "offline_verifier_catalog" in text
        or text.count("[taskset]\n") != 1
    ):
        _fail("eval_config_invalid")
    start = text.index("[taskset]\n") + len("[taskset]\n")
    section = re.search(r"(?m)^\[[^\n]+\]\s*$", text[start:])
    if section is None:
        _fail("eval_config_invalid")
    insertion = start + section.start()
    scalar_lines = (
        f"offline_verifier_catalog = {json.dumps(str(catalog_path))}\n"
        f"offline_verifier_catalog_sha256 = {json.dumps(catalog_sha256)}\n"
        f"offline_verifier_catalog_task_file = {json.dumps(str(task_file))}\n"
        f"offline_verifier_catalog_task_file_sha256 = {json.dumps(task_file_sha256)}\n"
        f"offline_verifier_project_root = {json.dumps(str(project_root))}\n"
    )
    record = identity.record()
    identity_lines = ["\n[taskset.offline_verifier_catalog_identity]\n"]
    for key, value in record.items():
        if type(value) is int:
            identity_lines.append(f"{key} = {value}\n")
        elif isinstance(value, str):
            identity_lines.append(f"{key} = {json.dumps(value)}\n")
        else:
            _fail("catalog_identity_invalid")
    payload = (text[:insertion] + scalar_lines + text[insertion:] + "".join(identity_lines)).encode()
    try:
        parsed = tomllib.loads(payload.decode("utf-8"))
        config = TerminalBenchVMVMConfig.model_validate(parsed["taskset"])
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        _fail("eval_config_invalid", error)
    if (
        config.offline_verifier_catalog != catalog_path
        or config.offline_verifier_catalog_sha256 != catalog_sha256
        or config.offline_verifier_catalog_task_file != task_file
        or config.offline_verifier_catalog_task_file_sha256 != task_file_sha256
        or config.offline_verifier_project_root != project_root
        or config.offline_verifier_catalog_identity is None
        or config.offline_verifier_catalog_identity.catalog_identity() != identity
    ):
        _fail("eval_config_invalid")
    return payload


def _fresh_output_binding(path: Path) -> dict[str, Any]:
    if (
        not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or path.parent == path
        or os.path.lexists(path)
    ):
        _fail("evaluation_output_not_fresh")
    try:
        parent = path.parent.resolve(strict=True)
        listed = path.parent.lstat()
    except OSError as error:
        _fail("evaluation_output_not_fresh", error)
    if (
        parent != path.parent
        or not stat.S_ISDIR(listed.st_mode)
        or listed.st_uid != os.geteuid()
        or stat.S_IMODE(listed.st_mode) != 0o700
    ):
        _fail("evaluation_output_not_fresh")
    identity = {
        "schema_version": 1,
        "path": str(path),
        "parent_device": listed.st_dev,
        "parent_inode": listed.st_ino,
        "parent_mode": stat.S_IMODE(listed.st_mode),
        "parent_owner": listed.st_uid,
    }
    return {"path": str(path), "path_identity_sha256": sha256(compact_json(identity))}


def _catalog_files(
    root: Path,
    *,
    expected_launch_sha256: str,
) -> tuple[bytes, bytes, dict[str, Any]]:
    if not root.is_absolute() or root != Path(os.path.normpath(root)):
        _fail("catalog_output_invalid")
    try:
        resolved = root.resolve(strict=True)
        before = root.lstat()
    except OSError as error:
        _fail("catalog_output_invalid", error)
    if (
        resolved != root
        or not stat.S_ISDIR(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o700
    ):
        _fail("catalog_output_invalid")
    launch_body, _ = _path_identity(
        root / "launch.json",
        executable=False,
        code="catalog_launch_receipt_invalid",
        required_modes=frozenset({0o400}),
    )
    launch = _load_catalog_launch(launch_body, expected_launch_sha256)
    catalog_body, _ = _path_identity(
        root / "catalog.json",
        executable=False,
        code="catalog_output_invalid",
        required_modes=frozenset({0o400}),
    )
    try:
        after = root.lstat()
    except OSError as error:
        _fail("catalog_output_invalid", error)
    if (
        sha256(catalog_body) != launch["catalog_sha256"]
        or (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    ):
        _fail("catalog_output_changed")
    return catalog_body, launch_body, launch


def _validate_catalog_policy_for_launch(
    body: bytes,
    runtime: RuntimeApproval,
    binding: RepairBinding,
) -> dict[str, Any]:
    expected_sha256 = runtime.value["expected_catalog_policy_sha256"]
    if sha256(body) != expected_sha256:
        _fail("catalog_policy_invalid")
    policy = _parse_canonical(body, newline=True, code="catalog_policy_invalid")
    worker = policy.get("worker") if isinstance(policy, dict) else None
    catalog = policy.get("catalog_policy") if isinstance(policy, dict) else None
    if (
        policy.get("kind") != plan_generator.KIND
        or policy.get("expected_counts")
        != {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0}
        or policy.get("provider_materialization_receipt_sha256")
        != binding.value["provider_materialization_receipt_sha256"]
        or policy.get("worker_contract_sha256")
        != runtime.value["provision_approval"]["worker_contract_sha256"]
        or not isinstance(worker, dict)
        or worker.get("executable_sha256")
        != runtime.value["provision_approval"]["sealed_launcher_sha256"]
        or worker.get("runtime_sha256")
        != runtime.value["provision_approval"]["worker_runtime_sha256"]
        or worker.get("environment_sha256")
        != runtime.value["catalog_policy"]["worker_environment_sha256"]
        or worker.get("recovery_scope_sha256")
        != runtime.value["catalog_policy"]["worker_recovery_scope_sha256"]
        or not isinstance(catalog, dict)
        or catalog.get("catalog_consumer_code_sha256")
        != runtime.value["runtime_artifacts"]["catalog_consumer_sha256"]
        or catalog.get("requirements_extractor_sha256")
        != runtime.value["runtime_artifacts"]["requirements_extractor_sha256"]
    ):
        _fail("catalog_policy_invalid")
    return policy


def _launch_contract_value(
    *,
    runtime: RuntimeApproval,
    binding: RepairBinding,
    plan_sha256: str,
    plan_receipt_sha256: str,
    catalog_identity_sha256: str,
    catalog_launch_sha256: str,
    catalog_sha256: str,
    eval_config: Path,
    eval_config_sha256: str,
    catalog_path: Path,
    output_binding: Mapping[str, Any],
) -> dict[str, Any]:
    execution = runtime.value["execution"]
    serving = runtime.value["serving"]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": LAUNCH_KIND,
        "state": "composed",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "model": MODEL,
        "counts": {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0},
        "bindings": {
            "runtime_approval_sha256": runtime.sha256,
            "repair_binding_sha256": binding.sha256,
            "catalog_policy_sha256": runtime.value["expected_catalog_policy_sha256"],
            "plan_sha256": plan_sha256,
            "plan_receipt_sha256": plan_receipt_sha256,
            "catalog_identity_sha256": catalog_identity_sha256,
            "catalog_launch_receipt_sha256": catalog_launch_sha256,
            "catalog_sha256": catalog_sha256,
            "source_config_sha256": binding.value["source_config_sha256"],
            "eval_config_sha256": eval_config_sha256,
        },
        "serving": serving,
        "execution": execution,
        "ramps": runtime.value["ramps"],
        "catalog": {
            "path": str(catalog_path),
            "expected_task_count": TASK_COUNT,
            "preflight_required_before_any_sandbox": True,
            "per_runtime_revalidation_required": True,
            "final_zero_live_wal_verified": True,
        },
        "evaluation": {
            "config": str(eval_config),
            "output": dict(output_binding),
            "mode": "fresh",
            "resume_allowed": False,
            "execution_performed": False,
        },
        "environment": {
            "DIRECT_QWEN_ROUTER_POLICY": "consistent_hash",
            "DIRECT_QWEN_REQUEST_ID_HEADERS": "x-session-id",
            "DIRECT_QWEN_PROVIDER_CONCURRENCY": str(HTTP_CONCURRENCY),
            "MODAL_DISABLE_API_PROXY": "1",
            "OCI_RUNNER_BASE_URL": execution["base_url"],
            "OCI_RUNNER_ENVIRONMENT": execution["environment"],
            "OCI_RUNNER_ECR_TOKEN_FILE": execution["ecr_token_file_path"],
            "OCI_RUNNER_ECR_TOKEN_METADATA_PATH": execution[
                "ecr_token_metadata_path"
            ],
            "OCI_RUNNER_TASK_NETWORK": "none",
            "OCI_RUNNER_TOKEN_FILE": execution["token_file_path"],
            "OCI_RUNNER_POOL_SIZE": str(execution["provider_pool_capacity"]),
            "OCI_RUNNER_POOL_MIN_SIZE": "0",
            "OCI_RUNNER_POOL_CREATE_WORKERS": str(execution["lease_create_cap"]),
            "OCI_RUNNER_OBSERVABILITY": "1",
            "OCI_RUNNER_SESSION_REUSE": "1",
            "OCI_RUNNER_POOL_MAX_REUSE_COUNT": "1",
            "OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES": "0",
            "OCI_RUNNER_PODMAN_FUSE_OVERLAYFS": "1",
            "OCI_RUNNER_FUSE_OVERLAYFS_PATH": "/usr/bin/fuse-overlayfs",
            "OCI_RUNNER_LIBFUSE3_PATH": "/lib/x86_64-linux-gnu/libfuse3.so.3",
            "OCI_RUNNER_LEASE_DURATION": "1h",
            "OCI_RUNNER_PULL_TIMEOUT": "3600s",
            "OCI_RUNNER_PULL_POLL_MAX_ERRORS": "20",
            "SANDOQ_CATALOG_EXCLUSIVE_POOL": "1",
        },
        "dynamic_environment": {
            "HTTPS_PROXY": "supervised_loopback_direct_connect_proxy_url",
            "https_proxy": "supervised_loopback_direct_connect_proxy_url",
        },
        "provider_context": {
            **execution["provider_context"],
            "implementation_sha256": runtime.value["runtime_artifacts"][
                "provider_environment_context_sha256"
            ],
            "proxy_implementation_sha256": runtime.value["runtime_artifacts"][
                "direct_connect_proxy_sha256"
            ],
        },
        "forbidden_environment": ["FIRECRACKER_KEY", "RESUME_DIR"],
        "trust_boundary": runtime.value["trust_boundary"],
    }


def _composition_receipt(
    launch: Mapping[str, Any],
    *,
    eval_config_sha256: str,
    launch_contract_sha256: str,
    launch_authorization_sha256: str,
) -> bytes:
    return _canonical_json(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": RECEIPT_KIND,
            "state": "composed",
            "counts": {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0},
            "execution_performed": False,
            "fresh_output_verified": True,
            "resume_allowed": False,
            "catalog_preflight_required": True,
            "bindings": {
                "eval_config_sha256": eval_config_sha256,
                "launch_contract_sha256": launch_contract_sha256,
                "launch_authorization_sha256": launch_authorization_sha256,
                **launch["bindings"],
            },
        }
    )


def compose_launch(
    *,
    project_root: Path,
    dataset_root: Path,
    private_output_root: Path,
    runtime_approval: Path,
    runtime_approval_sha256: str,
    repair_binding: Path,
    repair_binding_sha256: str,
    source_config: Path,
    catalog_policy: Path,
    plan: Path,
    plan_sha256: str,
    plan_receipt: Path,
    plan_receipt_sha256: str,
    catalog_identity: Path,
    catalog_identity_sha256: str,
    catalog_root: Path,
    catalog_launch_receipt_sha256: str,
    launch_authorization: Path,
    launch_authorization_sha256: str,
    evaluation_output: Path,
    eval_config_output: Path,
    launch_contract_output: Path,
    composition_receipt_output: Path,
) -> dict[str, int]:
    inputs = (
        runtime_approval,
        repair_binding,
        source_config,
        catalog_policy,
        plan,
        plan_receipt,
        catalog_identity,
        launch_authorization,
    )
    outputs = (eval_config_output, launch_contract_output, composition_receipt_output)
    if not _is_sha256(plan_sha256):
        _fail("plan_invalid")
    if (
        catalog_root.parent != private_output_root
        or catalog_root.name != "catalog"
        or evaluation_output.parent != private_output_root
    ):
        _fail("launch_path_invalid")
    try:
        with _open_private_output_root(
            private_output_root,
            (*inputs, *outputs),
            forbidden_roots=(project_root, dataset_root),
            validate_existing=False,
        ) as opened:
            bodies = {path: _read_private_artifact(opened, path) for path in inputs}
            runtime = _load_runtime_approval(
                bodies[runtime_approval],
                runtime_approval_sha256,
                project_root=project_root,
            )
            binding = _load_repair_binding(
                bodies[repair_binding],
                repair_binding_sha256,
            )
            if runtime.value["repair_binding_sha256"] != binding.sha256:
                _fail("repair_binding_not_approved")
            authorization = _load_launch_authorization(
                bodies[launch_authorization],
                launch_authorization_sha256,
            )
            if sha256(bodies[plan]) != plan_sha256:
                _fail("plan_invalid")
            identity = _load_catalog_identity(
                bodies[catalog_identity],
                catalog_identity_sha256,
            )
            policy = _validate_catalog_policy_for_launch(
                bodies[catalog_policy],
                runtime,
                binding,
            )
            _load_plan_receipt(
                bodies[plan_receipt],
                plan_receipt_sha256,
                runtime=runtime,
                binding=binding,
                identity=identity,
                plan_sha256=plan_sha256,
            )
            _, config = _validate_source_config(
                bodies[source_config],
                source_config,
                binding,
                runtime,
            )
            catalog_body, catalog_launch_body, catalog_launch = _catalog_files(
                catalog_root,
                expected_launch_sha256=catalog_launch_receipt_sha256,
            )
            catalog_sha256 = sha256(catalog_body)
            if (
                catalog_launch["catalog_sha256"] != catalog_sha256
                or catalog_launch["identity_sha256"] != identity.sha256
                or catalog_launch["provider_recovery"]["recovery_scope_sha256"]
                != runtime.value["catalog_policy"]["worker_recovery_scope_sha256"]
                or catalog_launch["provider_recovery"]["receipt_verifier_sha256"]
                != runtime.value["catalog_policy"]["cleanup_receipt_verifier_sha256"]
                or identity.dataset_revision != binding.value["dataset_revision"]
                or identity.task_selection_sha256 != binding.value["task_file_sha256"]
                or identity.image_manifest_sha256 != binding.value["image_manifest_sha256"]
                or identity.catalog_consumer_code_sha256
                != runtime.value["runtime_artifacts"]["catalog_consumer_sha256"]
                or identity.requirements_extractor_sha256
                != runtime.value["runtime_artifacts"]["requirements_extractor_sha256"]
                or identity.inventory_probe_code_sha256
                != policy["catalog_policy"]["inventory_probe_code_sha256"]
                or identity.inventory_probe_environment_sha256
                != policy["catalog_policy"]["inventory_probe_environment_sha256"]
                or identity.inventory_probe_approval_sha256
                != policy["catalog_policy"]["inventory_probe_approval_sha256"]
                or identity.source_policy_sha256
                != policy["catalog_policy"]["source_policy_sha256"]
                or identity.source_policy_approval_sha256
                != policy["catalog_policy"]["source_policy_approval_sha256"]
                or identity.approved_binary_artifacts_sha256
                != plan_generator._allowlist_sha256(
                    "binary-artifacts",
                    tuple(policy["catalog_policy"]["approved_binary_artifacts"]),
                )
                or identity.approved_source_attestations_sha256
                != plan_generator._allowlist_sha256(
                    "source-attestations",
                    tuple(policy["catalog_policy"]["approved_source_attestations"]),
                )
                or identity.approved_toolchains_sha256
                != plan_generator._allowlist_sha256(
                    "toolchains",
                    tuple(policy["catalog_policy"]["approved_toolchains"]),
                )
            ):
                _fail("catalog_binding_invalid")
            authorization_bindings = {
                "runtime_approval_sha256": runtime.sha256,
                "repair_binding_sha256": binding.sha256,
                "source_config_sha256": binding.value["source_config_sha256"],
                "plan_sha256": plan_sha256,
                "plan_receipt_sha256": plan_receipt_sha256,
                "catalog_identity_sha256": catalog_identity_sha256,
                "catalog_launch_receipt_sha256": catalog_launch_receipt_sha256,
                "catalog_sha256": catalog_sha256,
            }
            if any(authorization[key] != value for key, value in authorization_bindings.items()):
                _fail("launch_authorization_mismatch")
            task_file = config.task_file
            if task_file is None:
                _fail("source_config_invalid")
            catalog_path = catalog_root / "catalog.json"
            eval_config = _render_eval_config(
                bodies[source_config],
                catalog_path=catalog_path,
                catalog_sha256=catalog_sha256,
                project_root=project_root,
                task_file=task_file,
                task_file_sha256=binding.value["task_file_sha256"],
                identity=identity,
            )
            eval_config_sha256 = sha256(eval_config)
            if authorization["expected_eval_config_sha256"] != eval_config_sha256:
                _fail("eval_config_not_approved")
            output_binding = _fresh_output_binding(evaluation_output)
            launch_value = _launch_contract_value(
                runtime=runtime,
                binding=binding,
                plan_sha256=plan_sha256,
                plan_receipt_sha256=plan_receipt_sha256,
                catalog_identity_sha256=catalog_identity_sha256,
                catalog_launch_sha256=catalog_launch_receipt_sha256,
                catalog_sha256=catalog_sha256,
                eval_config=eval_config_output,
                eval_config_sha256=eval_config_sha256,
                catalog_path=catalog_path,
                output_binding=output_binding,
            )
            launch_payload = _canonical_json(launch_value)
            launch_contract_sha256 = sha256(launch_payload)
            if (
                authorization["expected_launch_contract_sha256"]
                != launch_contract_sha256
            ):
                _fail("launch_contract_not_approved")
            receipt_payload = _composition_receipt(
                launch_value,
                eval_config_sha256=eval_config_sha256,
                launch_contract_sha256=launch_contract_sha256,
                launch_authorization_sha256=launch_authorization_sha256,
            )
            for path, body in bodies.items():
                if _read_private_artifact(opened, path) != body:
                    _fail("composition_input_changed")
            catalog_body_after, catalog_launch_body_after, _ = _catalog_files(
                catalog_root,
                expected_launch_sha256=catalog_launch_receipt_sha256,
            )
            if catalog_body_after != catalog_body or catalog_launch_body_after != catalog_launch_body:
                _fail("catalog_output_changed")
            if _fresh_output_binding(evaluation_output) != output_binding:
                _fail("evaluation_output_changed")
            publish_exclusive(
                opened,
                [
                    (eval_config_output, eval_config),
                    (launch_contract_output, launch_payload),
                    (composition_receipt_output, receipt_payload),
                ],
            )
    except LaunchCompositionError:
        raise
    except (OSError, MixedMaterializationError, ValueError) as error:
        _fail("launch_composition_invalid", error)
    return {"repair": TASK_COUNT, "sandoq": TASK_COUNT, "vmvm": 0}


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--private-output-root", required=True, type=Path)
    parser.add_argument("--runtime-approval", required=True, type=Path)
    parser.add_argument("--runtime-approval-sha256", required=True)
    parser.add_argument("--repair-binding", required=True, type=Path)
    parser.add_argument("--repair-binding-sha256", required=True)


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser()
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=StableArgumentParser,
    )
    policy = commands.add_parser("policy")
    _common_arguments(policy)
    policy.add_argument("--worker-contract", required=True, type=Path)
    policy.add_argument("--worker-contract-sha256", required=True)
    policy.add_argument("--worker-executable", required=True, type=Path)
    policy.add_argument("--output", required=True, type=Path)

    launch = commands.add_parser("launch")
    _common_arguments(launch)
    launch.add_argument("--source-config", required=True, type=Path)
    launch.add_argument("--catalog-policy", required=True, type=Path)
    launch.add_argument("--plan", required=True, type=Path)
    launch.add_argument("--plan-sha256", required=True)
    launch.add_argument("--plan-receipt", required=True, type=Path)
    launch.add_argument("--plan-receipt-sha256", required=True)
    launch.add_argument("--catalog-identity", required=True, type=Path)
    launch.add_argument("--catalog-identity-sha256", required=True)
    launch.add_argument("--catalog-root", required=True, type=Path)
    launch.add_argument("--catalog-launch-receipt-sha256", required=True)
    launch.add_argument("--launch-authorization", required=True, type=Path)
    launch.add_argument("--launch-authorization-sha256", required=True)
    launch.add_argument("--evaluation-output", required=True, type=Path)
    launch.add_argument("--eval-config-output", required=True, type=Path)
    launch.add_argument("--launch-contract-output", required=True, type=Path)
    launch.add_argument("--composition-receipt-output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = vars(_parser().parse_args(argv))
        command = arguments.pop("command")
        if command == "policy":
            counts = compose_policy(**arguments)
        elif command == "launch":
            counts = compose_launch(**arguments)
        else:
            _fail("arguments_invalid")
        print(
            json.dumps(
                {"state": "composed", "phase": command, "counts": counts},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception:
        print(
            '{"error":"composition_invalid","state":"failed"}',
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
