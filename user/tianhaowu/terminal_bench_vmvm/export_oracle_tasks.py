#!/usr/bin/env python3
"""Promote a complete oracle run into an approved, deterministic task manifest.

The command is a dry-run unless ``--apply`` is supplied. Apply mode requires a
new ``--receipt`` target and publishes a canonical, self-hashed receipt only
after the manifest and configs are verified. Stdout contains counts and digests
only; task identifiers and oracle error details are never printed. Existing
manifest order is retained for tasks that remain valid and replacement tasks
are appended in the canonical dataset order.
"""

from __future__ import annotations

import argparse
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
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from terminal_bench_vmvm.source_wheels import (
    SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION,
    canonical_json,
    inspect_wheelhouse,
    load_source_wheel_policy,
    wheel_evidence_dicts,
)

SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SOURCE_WHEELHOUSE_BYTES = 1024 * 1024 * 1024
TASKSET_ID = "terminal-bench-vmvm"
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
MINIMUM_ORACLE_PRIME_RL_ANCESTOR = "f0e8d1fd55dadedc086feb8833071700ed034f63"
RECEIPT_SCHEMA_VERSION = 1
RECEIPT_ARTIFACT_TYPE = "terminal_bench_vmvm_oracle_promotion_receipt"
PROVENANCE_KEYS = {
    "host",
    "oracle_solution_network_mode",
    "prime_rl",
    "prime_rl_tree",
    "run_identity_sha256",
    "slurm_job_id",
    "verifiers",
    "vmvm_tb_v2",
}
RUN_IDENTITY_KEYS = {
    "acceptance",
    "dataset",
    "execution",
    "images",
    "network_semantics",
    "schema_version",
    "selection",
    "source",
}
SOURCE_WHEEL_RUN_IDENTITY_KEYS = RUN_IDENTITY_KEYS | {"source_wheel_recovery"}
ORACLE_REASONS = {
    "error",
    "infrastructure_error",
    "invalid",
    "timeout",
    "unsupported",
    "valid",
}
INVOCATION_KEYS = {
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
SOURCE_WHEEL_INVOCATION_KEYS = INVOCATION_KEYS | {
    "expected_source_wheel_attestation_sha256",
    "source_wheel_policy_sha256",
}


class PromotionError(ValueError):
    """An oracle run or approval input failed a promotion invariant."""


def _source_wheel_recovery(identity: dict[str, Any]) -> dict[str, Any] | None:
    keys = set(identity)
    if keys == RUN_IDENTITY_KEYS:
        return None
    if keys != SOURCE_WHEEL_RUN_IDENTITY_KEYS:
        raise PromotionError("oracle_run_identity_invalid")
    recovery = identity.get("source_wheel_recovery")
    if not isinstance(recovery, dict) or set(recovery) != {
        "schema_version",
        "policy",
        "attestation",
        "artifact_download_network",
        "builder_lease_limit",
        "build_network",
        "build_isolation",
        "target_install",
    }:
        raise PromotionError("oracle_source_wheel_identity_invalid")
    policy = recovery.get("policy")
    if (
        recovery.get("schema_version") != 1
        or not isinstance(policy, dict)
        or set(policy) != {"path", "sha256"}
        or not isinstance(policy.get("path"), str)
        or not Path(policy["path"]).is_absolute()
        or not isinstance(policy.get("sha256"), str)
        or SHA256_RE.fullmatch(policy["sha256"]) is None
        or recovery.get("attestation") != "source_wheel_attestations.json"
        or recovery.get("artifact_download_network") != "public-hash-pinned-https"
        or recovery.get("builder_lease_limit") != 1
        or recovery.get("build_network") != "no-network"
        or recovery.get("build_isolation") is not False
        or recovery.get("target_install") != "offline-no-index-no-deps"
    ):
        raise PromotionError("oracle_source_wheel_identity_invalid")
    return recovery


def _read_bytes(path: Path, *, limit: int, error: str) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as cause:
        raise PromotionError(error) from cause
    if len(data) > limit:
        raise PromotionError(error)
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(encoded)


def _canonical_json_file(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _json_file_with_sha256(path: Path, *, error: str) -> tuple[dict[str, Any], str]:
    raw = _read_bytes(path, limit=MAX_JSON_BYTES, error=error)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise PromotionError(error) from cause
    if not isinstance(value, dict):
        raise PromotionError(error)
    return value, _sha256(raw)


def _json_file(path: Path, *, error: str) -> dict[str, Any]:
    return _json_file_with_sha256(path, error=error)[0]


def _manifest_tasks(data: bytes, *, error: str) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as cause:
        raise PromotionError(error) from cause
    if not text.endswith("\n"):
        raise PromotionError(error)
    tasks = text.splitlines()
    if not tasks or any(not task or task.strip() != task or "\t" in task for task in tasks):
        raise PromotionError(error)
    if len(tasks) != len(set(tasks)):
        raise PromotionError(error)
    return tasks


def _ordered_tasks_sha256(tasks: list[str]) -> str:
    return _sha256("".join(f"{task}\n" for task in tasks).encode("utf-8"))


def _positive_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _audit_run_identity(
    oracle_dir: Path,
    dataset_dir: Path,
    dataset_revision: str,
    canonical_tasks: list[str],
    *,
    expected_prime_rl_commit: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    expected_image_manifest_sha256: str,
    expected_minimum_pass_rate: float,
    expected_minimum_valid: int,
    trusted_reference_solution: str,
) -> tuple[str, str, Path, dict[str, Any] | None]:
    wrapper, sidecar_sha256 = _json_file_with_sha256(
        oracle_dir / "run_identity.json",
        error="oracle_run_identity_invalid",
    )
    if set(wrapper) != {"schema_version", "run_identity_sha256", "identity"} or wrapper.get("schema_version") != 1:
        raise PromotionError("oracle_run_identity_invalid")
    identity = wrapper.get("identity")
    identity_sha256 = wrapper.get("run_identity_sha256")
    if not isinstance(identity, dict) or not isinstance(identity_sha256, str):
        raise PromotionError("oracle_run_identity_invalid")
    source_wheel_recovery = _source_wheel_recovery(identity)
    canonical_identity = json.dumps(
        identity,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if SHA256_RE.fullmatch(identity_sha256) is None or _sha256(canonical_identity) != identity_sha256:
        raise PromotionError("oracle_run_identity_hash_mismatch")

    dataset = identity.get("dataset")
    selection = identity.get("selection")
    images = identity.get("images")
    source = identity.get("source")
    network_semantics = identity.get("network_semantics")
    execution = identity.get("execution")
    acceptance = identity.get("acceptance")
    if (
        identity.get("schema_version") != 1
        or not isinstance(dataset, dict)
        or set(dataset) != {"archive", "content_sha256", "path", "revision"}
        or not isinstance(selection, dict)
        or set(selection) != {"count", "limit", "offset", "ordered_task_slugs_sha256", "task_file"}
        or not isinstance(images, dict)
        or set(images) != {"enable_compose", "manifest", "prefix", "tag", "use_declared_images"}
        or not isinstance(source, dict)
        or set(source) != {"prime_rl_commit", "prime_rl_tree_sha256", "verifiers_commit", "vmvm_tb_v2_sha256"}
        or not isinstance(execution, dict)
        or set(execution)
        != {
            "infra_retries",
            "lease_ttl",
            "max_concurrent",
            "max_session_buffer_size",
            "resource_multiplier",
            "runtime_image",
            "runtime_workdir",
            "session_timeout_sec",
            "setup_timeout_sec",
            "tenant_id",
            "timeout_multiplier",
            "vacli_container_privileged",
            "vacli_image_pull_timeout_seconds",
            "vacli_lease_retries",
            "vacli_max_concurrent_leases",
            "vacli_max_pull_retries",
            "validate_timeout_sec",
            "verifier_runtime_retries",
        }
        or not isinstance(acceptance, dict)
        or set(acceptance) != {"minimum_pass_rate", "minimum_valid"}
    ):
        raise PromotionError("oracle_run_identity_invalid")

    try:
        identity_dataset = Path(dataset["path"]).resolve(strict=True)
    except (KeyError, TypeError, OSError, RuntimeError) as cause:
        raise PromotionError("oracle_run_identity_invalid") from cause
    expected_semantics = _expected_semantics(trusted_reference_solution)
    if (
        identity_dataset != dataset_dir.resolve(strict=True)
        or dataset.get("revision") != dataset_revision
        or dataset.get("archive") != {"path": None, "sha256": None}
        or dataset.get("content_sha256") is not None
        or selection.get("count") != len(canonical_tasks)
        or selection.get("offset") != 0
        or selection.get("limit") is not None
        or selection.get("ordered_task_slugs_sha256") != _ordered_tasks_sha256(canonical_tasks)
        or selection.get("task_file") != {"path": None, "sha256": None}
        or source.get("prime_rl_commit") != expected_prime_rl_commit
        or source.get("prime_rl_tree_sha256") != CLEAN_TREE_SHA256
        or source.get("verifiers_commit") != expected_verifiers_commit
        or source.get("vmvm_tb_v2_sha256") != expected_vmvm_tb_v2_sha256
        or network_semantics != expected_semantics
    ):
        raise PromotionError("oracle_run_identity_mismatch")

    minimum_pass_rate = acceptance.get("minimum_pass_rate")
    minimum_valid = acceptance.get("minimum_valid")
    if (
        isinstance(minimum_pass_rate, bool)
        or not isinstance(minimum_pass_rate, (int, float))
        or not math.isfinite(minimum_pass_rate)
        or minimum_pass_rate != expected_minimum_pass_rate
        or isinstance(minimum_valid, bool)
        or not isinstance(minimum_valid, int)
        or minimum_valid != expected_minimum_valid
    ):
        raise PromotionError("oracle_run_identity_mismatch")

    manifest = images.get("manifest")
    if not isinstance(manifest, dict) or set(manifest) != {"path", "sha256"}:
        raise PromotionError("oracle_run_identity_invalid")
    manifest_path = manifest.get("path")
    if (
        not isinstance(manifest_path, str)
        or not manifest_path
        or manifest.get("sha256") != expected_image_manifest_sha256
        or not isinstance(images.get("prefix"), str)
        or not images["prefix"]
        or not isinstance(images.get("tag"), str)
        or not images["tag"]
        or images["tag"] == "latest"
        or images.get("use_declared_images") is not False
        or not isinstance(images.get("enable_compose"), bool)
    ):
        raise PromotionError("oracle_run_identity_mismatch")
    try:
        resolved_manifest = Path(manifest_path).resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("oracle_image_manifest_unreadable") from cause
    if str(resolved_manifest) != manifest_path:
        raise PromotionError("oracle_run_identity_mismatch")
    manifest_bytes = _read_bytes(
        resolved_manifest,
        limit=MAX_MANIFEST_BYTES,
        error="oracle_image_manifest_unreadable",
    )
    if _sha256(manifest_bytes) != expected_image_manifest_sha256:
        raise PromotionError("oracle_image_manifest_mismatch")

    positive_ints = (
        "max_concurrent",
        "max_session_buffer_size",
        "vacli_image_pull_timeout_seconds",
        "vacli_max_concurrent_leases",
    )
    nonnegative_ints = (
        "infra_retries",
        "vacli_lease_retries",
        "vacli_max_pull_retries",
        "verifier_runtime_retries",
    )
    positive_numbers = (
        "resource_multiplier",
        "session_timeout_sec",
        "setup_timeout_sec",
        "timeout_multiplier",
        "validate_timeout_sec",
    )
    if (
        any(
            isinstance(execution.get(key), bool) or not isinstance(execution.get(key), int) or execution[key] < 1
            for key in positive_ints
        )
        or any(
            isinstance(execution.get(key), bool) or not isinstance(execution.get(key), int) or execution[key] < 0
            for key in nonnegative_ints
        )
        or any(not _positive_number(execution.get(key)) for key in positive_numbers)
        or not isinstance(execution.get("tenant_id"), str)
        or not execution["tenant_id"]
        or not isinstance(execution.get("lease_ttl"), str)
        or not execution["lease_ttl"]
        or execution.get("runtime_image") != "python:3.12-slim"
        or execution.get("runtime_workdir") != "/app"
        or not isinstance(execution.get("vacli_container_privileged"), bool)
    ):
        raise PromotionError("oracle_run_identity_invalid")
    if source_wheel_recovery is not None:
        policy = source_wheel_recovery["policy"]
        try:
            policy_path = Path(policy["path"]).resolve(strict=True)
        except (OSError, RuntimeError) as cause:
            raise PromotionError("oracle_source_wheel_policy_unreadable") from cause
        if str(policy_path) != policy["path"]:
            raise PromotionError("oracle_source_wheel_identity_invalid")
        policy_bytes = _read_bytes(
            policy_path,
            limit=MAX_CONFIG_BYTES,
            error="oracle_source_wheel_policy_unreadable",
        )
        if _sha256(policy_bytes) != policy["sha256"]:
            raise PromotionError("oracle_source_wheel_policy_mismatch")
    return identity_sha256, sidecar_sha256, resolved_manifest, source_wheel_recovery


def _git_output(dataset_dir: Path, *args: str, error: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(dataset_dir), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as cause:
        raise PromotionError(error) from cause


def _audit_provenance(
    oracle_dir: Path,
    project_root: Path,
    *,
    expected_prime_rl_commit: str,
    required_prime_rl_ancestor: str,
    minimum_prime_rl_ancestor: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    expected_run_identity_sha256: str,
    trusted_reference_solution: str,
    source_wheel_policy_sha256: str | None = None,
) -> tuple[str, dict[str, str]]:
    if (
        REVISION_RE.fullmatch(expected_prime_rl_commit) is None
        or REVISION_RE.fullmatch(required_prime_rl_ancestor) is None
        or REVISION_RE.fullmatch(minimum_prime_rl_ancestor) is None
        or REVISION_RE.fullmatch(expected_verifiers_commit) is None
        or SHA256_RE.fullmatch(expected_vmvm_tb_v2_sha256) is None
        or SHA256_RE.fullmatch(expected_run_identity_sha256) is None
    ):
        raise PromotionError("provenance_expectation_invalid")
    raw = _read_bytes(
        oracle_dir / "provenance.txt",
        limit=MAX_CONFIG_BYTES,
        error="oracle_provenance_unreadable",
    )
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise PromotionError("oracle_provenance_invalid") from cause
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in records:
            raise PromotionError("oracle_provenance_invalid")
        records[key] = value
    expected_keys = (
        PROVENANCE_KEYS if source_wheel_policy_sha256 is None else PROVENANCE_KEYS | {"source_wheel_policy_sha256"}
    )
    if set(records) != expected_keys:
        raise PromotionError("oracle_provenance_invalid")
    if (
        records["prime_rl"] != expected_prime_rl_commit
        or records["prime_rl_tree"] != CLEAN_TREE_SHA256
        or records["verifiers"] != expected_verifiers_commit
        or records["vmvm_tb_v2"] != expected_vmvm_tb_v2_sha256
        or records["run_identity_sha256"] != expected_run_identity_sha256
        or records["oracle_solution_network_mode"] != trusted_reference_solution
        or (
            source_wheel_policy_sha256 is not None
            and records.get("source_wheel_policy_sha256") != source_wheel_policy_sha256
        )
        or not records["host"].strip()
        or not records["slurm_job_id"].isdigit()
    ):
        raise PromotionError("oracle_provenance_mismatch")

    try:
        root = project_root.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("project_root_unreadable") from cause
    for ancestor, descendant, mismatch_error in (
        (
            minimum_prime_rl_ancestor,
            required_prime_rl_ancestor,
            "required_oracle_ancestor_before_lifecycle_baseline",
        ),
        (
            required_prime_rl_ancestor,
            expected_prime_rl_commit,
            "oracle_commit_before_required_ancestor",
        ),
    ):
        try:
            ancestry = subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
                check=False,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as cause:
            raise PromotionError("oracle_commit_ancestry_unverifiable") from cause
        if ancestry.returncode == 1:
            raise PromotionError(mismatch_error)
        if ancestry.returncode != 0:
            raise PromotionError("oracle_commit_ancestry_unverifiable")
    gitlink = _git_output(
        root,
        "ls-tree",
        expected_prime_rl_commit,
        "deps/verifiers",
        error="oracle_verifier_gitlink_unverifiable",
    ).strip()
    expected_gitlink = f"160000 commit {expected_verifiers_commit}\tdeps/verifiers"
    if gitlink != expected_gitlink:
        raise PromotionError("oracle_verifier_gitlink_mismatch")
    return _sha256(raw), records


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _audit_source_wheel_artifacts(
    oracle_dir: Path,
    recovery: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, frozenset[str]]:
    if recovery is None:
        return None, frozenset()
    policy_record = recovery["policy"]
    policy_path = Path(policy_record["path"])
    try:
        policy = load_source_wheel_policy(policy_path, policy_record["sha256"])
    except (OSError, ValueError) as cause:
        raise PromotionError("oracle_source_wheel_policy_invalid") from cause

    attestation_path = oracle_dir / recovery["attestation"]
    try:
        metadata = attestation_path.lstat()
        resolved_attestation = attestation_path.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("oracle_source_wheel_attestation_unreadable") from cause
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
        or resolved_attestation.parent != oracle_dir.resolve(strict=True)
    ):
        raise PromotionError("oracle_source_wheel_attestation_invalid")
    raw = _read_bytes(
        resolved_attestation,
        limit=MAX_JSON_BYTES,
        error="oracle_source_wheel_attestation_unreadable",
    )
    try:
        manifest = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as cause:
        raise PromotionError("oracle_source_wheel_attestation_invalid") from cause
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "policy_sha256",
        "entries_sha256",
        "entries",
    }:
        raise PromotionError("oracle_source_wheel_attestation_invalid")
    entries = manifest.get("entries")
    if (
        manifest.get("schema_version") != SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION
        or manifest.get("policy_sha256") != policy.sha256
        or not isinstance(entries, list)
        or manifest.get("entries_sha256") != _sha256(canonical_json(entries))
    ):
        raise PromotionError("oracle_source_wheel_attestation_invalid")

    cache_directory = oracle_dir / "source_wheel_cache"
    expected_cache_files: set[str] = set()
    attestation_digests: set[str] = set()
    wheelhouse_records: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "schema_version",
            "cache_key_sha256",
            "policy_sha256",
            "requirements",
            "target",
            "build_contract",
            "sources",
            "binary_wheels",
            "resolution",
            "wheels",
            "wheelhouse",
            "attestation_sha256",
        }:
            raise PromotionError("oracle_source_wheel_attestation_invalid")
        attestation_sha256 = entry.get("attestation_sha256")
        unsigned = {key: value for key, value in entry.items() if key != "attestation_sha256"}
        requirements = entry.get("requirements")
        target = entry.get("target")
        wheelhouse = entry.get("wheelhouse")
        runtime = target.get("runtime") if isinstance(target, dict) else None
        expected_marker_keys = {
            "implementation_name",
            "implementation_version",
            "os_name",
            "platform_machine",
            "platform_python_implementation",
            "platform_release",
            "platform_system",
            "platform_version",
            "python_full_version",
            "python_version",
            "sys_platform",
        }
        if (
            entry.get("schema_version") != SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION
            or entry.get("policy_sha256") != policy.sha256
            or not isinstance(attestation_sha256, str)
            or SHA256_RE.fullmatch(attestation_sha256) is None
            or _sha256(canonical_json(unsigned)) != attestation_sha256
            or attestation_sha256 in attestation_digests
            or not isinstance(requirements, list)
            or not requirements
            or not all(isinstance(requirement, str) for requirement in requirements)
            or not isinstance(target, dict)
            or set(target)
            != {
                "image",
                "resolution_fingerprint",
                "compatibility_fingerprint",
                "toolchain_fingerprint",
                "runtime",
            }
            or not isinstance(target.get("image"), str)
            or not isinstance(runtime, dict)
            or set(runtime) != {"marker_environment", "pip_version", "wheel_compatibility", "build_tools"}
            or not isinstance(runtime.get("marker_environment"), dict)
            or set(runtime["marker_environment"]) != expected_marker_keys
            or not all(isinstance(value, str) for value in runtime["marker_environment"].values())
            or not isinstance(runtime.get("pip_version"), str)
            or not runtime["pip_version"]
            or not isinstance(runtime.get("wheel_compatibility"), list)
            or len(runtime["wheel_compatibility"]) != 5
            or not isinstance(runtime["wheel_compatibility"][0], str)
            or not runtime["wheel_compatibility"][0]
            or not isinstance(runtime["wheel_compatibility"][1], list)
            or len(runtime["wheel_compatibility"][1]) != 2
            or not all(
                not isinstance(value, bool) and isinstance(value, int) and value >= 0
                for value in runtime["wheel_compatibility"][1]
            )
            or not all(isinstance(value, str) and value for value in runtime["wheel_compatibility"][2:])
            or not isinstance(runtime.get("build_tools"), dict)
            or set(runtime["build_tools"]) != {"pip", "setuptools", "wheel"}
            or not all(isinstance(value, str) and value for value in runtime["build_tools"].values())
            or entry.get("build_contract")
            != {
                "artifact_download_network": "public-hash-pinned-https",
                "builder_lease_limit": 1,
                "build_network": "no-network",
                "build_isolation": False,
                "dependency_resolution": "explicit-policy-artifacts",
                "isolated_python": True,
                "staged_inputs": "policy-artifacts-only",
                "target_install": "offline-no-index-no-deps",
            }
            or not isinstance(wheelhouse, dict)
            or set(wheelhouse) != {"path", "size", "sha256"}
        ):
            raise PromotionError("oracle_source_wheel_attestation_invalid")
        try:
            build_tools = runtime["build_tools"]
            policy_entry = policy.entry_for(
                tuple(requirements),
                target["image"],
                tuple(sorted(build_tools.items())),
            )
        except (AttributeError, TypeError, RuntimeError) as cause:
            raise PromotionError("oracle_source_wheel_attestation_policy_mismatch") from cause
        expected_resolution_fingerprint = _sha256(
            canonical_json([runtime["marker_environment"], runtime["pip_version"]])
        )
        expected_compatibility_fingerprint = _sha256(
            canonical_json(
                [
                    target["image"],
                    runtime["marker_environment"],
                    runtime["pip_version"],
                    runtime["wheel_compatibility"],
                    runtime["build_tools"],
                ]
            )
        )
        expected_toolchain_fingerprint = _sha256(canonical_json([target["image"], runtime["build_tools"]]))
        if (
            target.get("resolution_fingerprint") != expected_resolution_fingerprint
            or target.get("compatibility_fingerprint") != expected_compatibility_fingerprint
            or target.get("toolchain_fingerprint") != expected_toolchain_fingerprint
        ):
            raise PromotionError("oracle_source_wheel_attestation_fingerprint_mismatch")
        cache_key = entry.get("cache_key_sha256")
        expected_cache_key = _sha256(
            canonical_json(
                {
                    "requirements": requirements,
                    "image": target["image"],
                    "resolution_fingerprint": target["resolution_fingerprint"],
                    "compatibility_fingerprint": target["compatibility_fingerprint"],
                    "toolchain_fingerprint": target["toolchain_fingerprint"],
                    "build_tools": build_tools,
                    "policy_sha256": policy.sha256,
                }
            )
        )
        expected_relative_path = f"source_wheel_cache/{cache_key}.tar"
        if (
            not isinstance(cache_key, str)
            or SHA256_RE.fullmatch(cache_key) is None
            or cache_key != expected_cache_key
            or wheelhouse.get("path") != expected_relative_path
            or isinstance(wheelhouse.get("size"), bool)
            or not isinstance(wheelhouse.get("size"), int)
            or not 0 < wheelhouse["size"] <= MAX_SOURCE_WHEELHOUSE_BYTES
            or not isinstance(wheelhouse.get("sha256"), str)
            or SHA256_RE.fullmatch(wheelhouse["sha256"]) is None
        ):
            raise PromotionError("oracle_source_wheel_attestation_invalid")
        archive_path = oracle_dir / expected_relative_path
        try:
            archive_metadata = archive_path.lstat()
            resolved_archive = archive_path.resolve(strict=True)
        except (OSError, RuntimeError) as cause:
            raise PromotionError("oracle_source_wheel_archive_unreadable") from cause
        if (
            not stat.S_ISREG(archive_metadata.st_mode)
            or stat.S_IMODE(archive_metadata.st_mode) not in {0o400, 0o600}
            or resolved_archive.parent != cache_directory.resolve(strict=True)
        ):
            raise PromotionError("oracle_source_wheel_archive_invalid")
        archive = _read_bytes(
            resolved_archive,
            limit=MAX_SOURCE_WHEELHOUSE_BYTES,
            error="oracle_source_wheel_archive_unreadable",
        )
        if len(archive) != wheelhouse["size"] or _sha256(archive) != wheelhouse["sha256"]:
            raise PromotionError("oracle_source_wheel_archive_mismatch")
        try:
            evidence = inspect_wheelhouse(archive)
        except RuntimeError as cause:
            raise PromotionError("oracle_source_wheel_archive_invalid") from cause
        expected_wheels = {
            filename: (distribution, version, size, digest)
            for distribution, version, filename, size, digest in policy_entry.expected_wheels
        }
        observed_wheels = {
            item.filename: (item.distribution, item.version, item.size, item.sha256) for item in evidence
        }
        expected_sources = []
        for source in policy_entry.sources:
            source_path = f"/tmp/terminal-bench-source-inputs/{source.filename}"
            source_requirement = f"{source.distribution} @ file://{source_path}#sha256={source.sha256}"
            build_argv = [
                "python3",
                "-I",
                "-m",
                "pip",
                "wheel",
                "--quiet",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                "/tmp/terminal-bench-source-wheels",
                source_requirement,
            ]
            expected_sources.append(
                {
                    "policy": {
                        "distribution": source.distribution,
                        "version": source.version,
                        "filename": source.filename,
                        "url": source.url,
                        "size": source.size,
                        "sha256": source.sha256,
                        "wheel_filename": source.wheel_filename,
                        "wheel_size": source.wheel_size,
                        "wheel_sha256": source.wheel_sha256,
                    },
                    "consumed_path": source_path,
                    "built_wheel": source.wheel_filename,
                    "build_argv_sha256": _sha256(canonical_json(build_argv)),
                }
            )
        expected_binary_wheels = [
            {
                "distribution": wheel.distribution,
                "version": wheel.version,
                "filename": wheel.filename,
                "url": wheel.url,
                "size": wheel.size,
                "sha256": wheel.sha256,
            }
            for wheel in policy_entry.binary_wheels
        ]
        expected_closure = [
            [distribution, version]
            for distribution, version in sorted(
                (distribution, version) for distribution, version, *_ in policy_entry.expected_wheels
            )
        ]
        expected_resolution = {
            "roots": requirements,
            "closure": expected_closure,
        }
        expected_resolution["sha256"] = _sha256(canonical_json(expected_resolution))
        if (
            wheel_evidence_dicts(evidence) != entry.get("wheels")
            or observed_wheels != expected_wheels
            or entry.get("sources") != expected_sources
            or entry.get("binary_wheels") != expected_binary_wheels
            or entry.get("resolution") != expected_resolution
        ):
            raise PromotionError("oracle_source_wheel_archive_policy_mismatch")
        expected_cache_files.add(f"{cache_key}.tar")
        attestation_digests.add(attestation_sha256)
        wheelhouse_records.append(
            {
                "path": expected_relative_path,
                "sha256": wheelhouse["sha256"],
                "size": wheelhouse["size"],
            }
        )
    if expected_cache_files:
        try:
            cache_metadata = cache_directory.lstat()
            observed_cache_files = {entry.name for entry in cache_directory.iterdir()}
        except OSError as cause:
            raise PromotionError("oracle_source_wheel_cache_invalid") from cause
        if (
            not stat.S_ISDIR(cache_metadata.st_mode)
            or stat.S_IMODE(cache_metadata.st_mode) != 0o700
            or observed_cache_files != expected_cache_files
        ):
            raise PromotionError("oracle_source_wheel_cache_invalid")
    else:
        try:
            cache_directory.lstat()
        except FileNotFoundError:
            pass
        except OSError as cause:
            raise PromotionError("oracle_source_wheel_cache_invalid") from cause
        else:
            raise PromotionError("oracle_source_wheel_cache_invalid")
    return (
        {
            "policy": {"path": str(policy.path), "sha256": policy.sha256},
            "attestation": {
                "path": recovery["attestation"],
                "sha256": _sha256(raw),
            },
            "wheelhouses": sorted(wheelhouse_records, key=lambda item: str(item["path"])),
        },
        frozenset(attestation_digests),
    )


def _audit_invocations(
    oracle_dir: Path,
    *,
    expected_run_identity_sha256: str,
    expected_source: dict[str, str],
    initial_provenance: dict[str, str],
    source_wheel_policy_sha256: str | None = None,
) -> tuple[dict[str, str], int, int]:
    path = oracle_dir / "invocations.jsonl"
    raw = _read_bytes(
        path,
        limit=MAX_JSON_BYTES,
        error="oracle_invocations_unreadable",
    )
    if not raw or not raw.endswith(b"\n"):
        raise PromotionError("oracle_invocations_invalid")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise PromotionError("oracle_invocations_invalid") from cause
    if not lines or any(not line for line in lines):
        raise PromotionError("oracle_invocations_invalid")

    rerun_invalid_count = 0
    seen_job_ids: set[str] = set()
    previous_invoked_at: int | float | None = None
    first_host: str | None = None
    first_job_id: str | None = None
    for index, line in enumerate(lines):
        try:
            record = json.loads(
                line,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (ValueError, RecursionError) as cause:
            raise PromotionError("oracle_invocations_invalid") from cause
        expected_keys = INVOCATION_KEYS if source_wheel_policy_sha256 is None else SOURCE_WHEEL_INVOCATION_KEYS
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise PromotionError("oracle_invocations_invalid")
        invoked_at = record.get("invoked_at")
        host = record.get("host")
        slurm_job_id = record.get("slurm_job_id")
        resume = record.get("resume")
        reuse_completed_rows = record.get("reuse_completed_rows")
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
                    or (
                        index > 0
                        and (
                            not isinstance(record.get("expected_source_wheel_attestation_sha256"), str)
                            or SHA256_RE.fullmatch(record["expected_source_wheel_attestation_sha256"]) is None
                        )
                    )
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
            or not isinstance(slurm_job_id, str)
            or re.fullmatch(r"[1-9][0-9]*", slurm_job_id) is None
            or slurm_job_id in seen_job_ids
            or not isinstance(resume, bool)
            or resume is not (index > 0)
            or reuse_completed_rows is not True
            or not isinstance(rerun_invalid, bool)
            or (index == 0 and rerun_invalid)
        ):
            raise PromotionError("oracle_invocations_invalid")
        if index == 0:
            first_host = host
            first_job_id = slurm_job_id
        previous_invoked_at = invoked_at
        seen_job_ids.add(slurm_job_id)
        rerun_invalid_count += int(rerun_invalid)

    if rerun_invalid_count > 1:
        raise PromotionError("oracle_rerun_invalid_limit_exceeded")
    if first_host != initial_provenance.get("host") or first_job_id != initial_provenance.get("slurm_job_id"):
        raise PromotionError("oracle_invocations_provenance_mismatch")
    return (
        {"path": str(path.resolve(strict=True)), "sha256": _sha256(raw)},
        len(lines),
        rerun_invalid_count,
    )


def _dataset_tasks(dataset_dir: Path, revision: str, expected_total: int) -> list[str]:
    try:
        root = dataset_dir.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("dataset_unreadable") from cause
    if not root.is_dir():
        raise PromotionError("dataset_unreadable")
    head = _git_output(root, "rev-parse", "HEAD", error="dataset_revision_unverifiable").strip()
    if head != revision:
        raise PromotionError("dataset_revision_mismatch")
    status = _git_output(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        error="dataset_cleanliness_unverifiable",
    )
    if status.strip():
        raise PromotionError("dataset_not_clean")
    try:
        tasks = [
            path.name
            for path in sorted(root.iterdir())
            if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
        ]
    except OSError as cause:
        raise PromotionError("dataset_unreadable") from cause
    if len(tasks) != expected_total or len(tasks) != len(set(tasks)):
        raise PromotionError("dataset_task_count_mismatch")
    if any(
        not task
        or task.strip() != task
        or task.startswith("#")
        or any(character in task for character in ("\r", "\n", "\t"))
        for task in tasks
    ):
        raise PromotionError("dataset_task_name_invalid")
    return tasks


def _results(oracle_dir: Path) -> tuple[list[dict[str, Any]], str]:
    raw = _read_bytes(
        oracle_dir / "results.jsonl",
        limit=MAX_JSON_BYTES,
        error="oracle_results_unreadable",
    )
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise PromotionError("oracle_results_invalid") from cause
    if not lines:
        raise PromotionError("oracle_results_empty")
    parsed: list[dict[str, Any]] = []
    for line in lines:
        try:
            result = json.loads(line)
        except json.JSONDecodeError as cause:
            raise PromotionError("oracle_results_invalid") from cause
        if not isinstance(result, dict):
            raise PromotionError("oracle_results_invalid")
        parsed.append(result)
    return parsed, _sha256(raw)


def _expected_semantics(trusted_reference_solution: str) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "trusted_reference_solution": trusted_reference_solution,
        "verifier": "declared",
    }


def _audit_oracle(
    oracle_dir: Path,
    dataset_dir: Path,
    dataset_revision: str,
    *,
    expected_total: int,
    minimum_pass_rate: float,
    minimum_valid: int,
    expected_run_identity_sha256: str,
    trusted_reference_solution: str,
    source_wheel_attestation_sha256: str | None = None,
    known_source_wheel_attestation_sha256s: frozenset[str] = frozenset(),
) -> tuple[list[str], set[str], int, float, dict[str, int], str, str]:
    canonical = _dataset_tasks(dataset_dir, dataset_revision, expected_total)
    canonical_set = set(canonical)
    results, results_sha256 = _results(oracle_dir)
    if len(results) != expected_total:
        raise PromotionError("oracle_result_count_mismatch")

    expected_semantics = _expected_semantics(trusted_reference_solution)
    slugs: list[str] = []
    valid: set[str] = set()
    referenced_source_attestations: set[str] = set()
    reasons: Counter[str] = Counter()
    for expected_index, result in enumerate(results):
        slug = result.get("slug")
        name = result.get("name")
        image = result.get("image")
        is_valid = result.get("valid")
        reason = result.get("reason")
        error = result.get("error")
        error_type = result.get("error_type")
        elapsed_sec = result.get("elapsed_sec")
        attempts = result.get("attempts")
        source_attestations = result.get("source_wheel_attestation_sha256s")
        if (
            isinstance(result.get("index"), bool)
            or not isinstance(result.get("index"), int)
            or result["index"] != expected_index
            or not isinstance(slug, str)
            or not slug
            or not isinstance(name, str)
            or not name
            or not isinstance(image, str)
            or not image
            or not isinstance(is_valid, bool)
            or not isinstance(reason, str)
            or reason not in ORACLE_REASONS
            or (is_valid and reason != "valid")
            or (not is_valid and reason == "valid")
            or not (error is None or isinstance(error, str))
            or not (error_type is None or isinstance(error_type, str))
            or isinstance(elapsed_sec, bool)
            or not isinstance(elapsed_sec, (int, float))
            or not math.isfinite(elapsed_sec)
            or elapsed_sec < 0
            or isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 1
            or not isinstance(result.get("infrastructure_failures"), list)
            or ("last_attempt" in result and not isinstance(result["last_attempt"], dict))
            or result.get("run_identity_sha256") != expected_run_identity_sha256
            or (source_wheel_attestation_sha256 is None and "source_wheel_attestation_sha256s" in result)
            or (
                source_wheel_attestation_sha256 is not None
                and (
                    not isinstance(source_attestations, list)
                    or source_attestations != sorted(set(source_attestations))
                    or not all(
                        isinstance(digest, str) and digest in known_source_wheel_attestation_sha256s
                        for digest in source_attestations
                    )
                )
            )
        ):
            raise PromotionError("oracle_result_schema_invalid")
        if result.get("oracle_network_semantics") != expected_semantics:
            raise PromotionError("oracle_result_semantics_mismatch")
        slugs.append(slug)
        if isinstance(source_attestations, list):
            referenced_source_attestations.update(source_attestations)
        reasons[reason] += 1
        if is_valid:
            valid.add(slug)
    if len(slugs) != len(set(slugs)):
        raise PromotionError("oracle_result_duplicates")
    if slugs != canonical:
        raise PromotionError("oracle_result_universe_or_order_mismatch")
    if source_wheel_attestation_sha256 is not None and (
        referenced_source_attestations != known_source_wheel_attestation_sha256s
    ):
        raise PromotionError("oracle_source_wheel_recovery_not_exercised")

    passed = len(valid)
    pass_rate = passed / expected_total
    if pass_rate < minimum_pass_rate:
        raise PromotionError("oracle_pass_rate_below_minimum")
    if passed < minimum_valid:
        raise PromotionError("oracle_valid_count_below_minimum")

    summary, summary_sha256 = _json_file_with_sha256(
        oracle_dir / "summary.json",
        error="oracle_summary_invalid",
    )
    finished_at = summary.get("finished_at")
    if (
        isinstance(finished_at, bool)
        or not isinstance(finished_at, (int, float))
        or not math.isfinite(float(finished_at))
    ):
        raise PromotionError("oracle_summary_not_final")
    if (
        summary.get("selected") != expected_total
        or summary.get("completed") != expected_total
        or summary.get("passed") != passed
        or summary.get("reasons") != dict(reasons)
        or summary.get("oracle_network_semantics") != expected_semantics
        or summary.get("run_identity_sha256") != expected_run_identity_sha256
        or (source_wheel_attestation_sha256 is None and "source_wheel_attestation_sha256" in summary)
        or (
            source_wheel_attestation_sha256 is not None
            and summary.get("source_wheel_attestation_sha256") != source_wheel_attestation_sha256
        )
    ):
        raise PromotionError("oracle_summary_mismatch")
    summary_rate = summary.get("pass_rate")
    if (
        isinstance(summary_rate, bool)
        or not isinstance(summary_rate, (int, float))
        or not math.isfinite(float(summary_rate))
        or not math.isclose(float(summary_rate), pass_rate, rel_tol=0.0, abs_tol=1e-15)
    ):
        raise PromotionError("oracle_summary_mismatch")

    run_config = _json_file(oracle_dir / "run_config.json", error="oracle_run_config_invalid")
    try:
        configured_dataset = Path(run_config["dataset_dir"]).resolve(strict=True)
    except (KeyError, TypeError, OSError, RuntimeError) as cause:
        raise PromotionError("oracle_run_config_invalid") from cause
    if (
        configured_dataset != dataset_dir.resolve(strict=True)
        or run_config.get("selected_tasks") != expected_total
        or run_config.get("oracle_solution_network_mode") != trusted_reference_solution
        or run_config.get("oracle_network_semantics") != expected_semantics
        or run_config.get("run_identity_sha256") != expected_run_identity_sha256
    ):
        raise PromotionError("oracle_run_config_mismatch")
    if (
        _json_file(
            oracle_dir / "oracle_network_semantics.json",
            error="oracle_semantics_invalid",
        )
        != expected_semantics
    ):
        raise PromotionError("oracle_semantics_mismatch")

    status_dir = oracle_dir / "tasks"
    try:
        status_paths = sorted(status_dir.glob("*.json"))
    except OSError as cause:
        raise PromotionError("oracle_statuses_unreadable") from cause
    if len(status_paths) != expected_total:
        raise PromotionError("oracle_status_count_mismatch")
    expected_by_slug = {result["slug"]: result for result in results}
    observed_statuses: set[str] = set()
    for path in status_paths:
        status = _json_file(path, error="oracle_status_invalid")
        slug = status.get("slug")
        if not isinstance(slug, str) or slug in observed_statuses or slug not in expected_by_slug:
            raise PromotionError("oracle_status_set_mismatch")
        observed_statuses.add(slug)
        expected = expected_by_slug[slug]
        if status != expected:
            raise PromotionError("oracle_status_mismatch")
    if observed_statuses != canonical_set:
        raise PromotionError("oracle_status_set_mismatch")
    return canonical, valid, passed, pass_rate, dict(reasons), results_sha256, summary_sha256


def _resolve_task_file(project_root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("config_task_file_invalid") from cause


def _updated_config(
    path: Path,
    *,
    project_root: Path,
    output: Path,
    dataset_dir: Path,
    dataset_revision: str,
    image_manifest: Path,
    image_manifest_sha256: str,
    current_sha256: str,
    new_sha256: str,
    selected_count: int,
) -> bytes:
    raw = _read_bytes(path, limit=MAX_CONFIG_BYTES, error="config_unreadable")
    try:
        text = raw.decode("utf-8")
        config = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as cause:
        raise PromotionError("config_invalid") from cause
    taskset = config.get("taskset")
    if not isinstance(taskset, dict) or taskset.get("id") != TASKSET_ID or "tasks" in taskset:
        raise PromotionError("config_taskset_invalid")
    if config.get("num_tasks") != selected_count:
        raise PromotionError("config_task_count_mismatch")
    dataset_value = taskset.get("dataset_dir")
    if not isinstance(dataset_value, str) or not dataset_value:
        raise PromotionError("config_dataset_invalid")
    configured_dataset = _resolve_task_file(project_root, dataset_value)
    if configured_dataset != dataset_dir.resolve(strict=True) or taskset.get("dataset_revision") != dataset_revision:
        raise PromotionError("config_dataset_mismatch")
    if taskset.get("image_manifest_sha256") != image_manifest_sha256:
        raise PromotionError("config_image_manifest_hash_mismatch")
    image_manifest_value = taskset.get("image_manifest")
    if not isinstance(image_manifest_value, str) or not image_manifest_value:
        raise PromotionError("config_image_manifest_invalid")
    configured_image_manifest = _resolve_task_file(project_root, image_manifest_value)
    if configured_image_manifest != image_manifest:
        raise PromotionError("config_image_manifest_mismatch")
    task_file = taskset.get("task_file")
    if not isinstance(task_file, str) or _resolve_task_file(project_root, task_file) != output.resolve():
        raise PromotionError("config_task_file_mismatch")
    if taskset.get("task_file_sha256") != current_sha256:
        raise PromotionError("config_current_hash_mismatch")

    lines = text.splitlines(keepends=True)
    section: str | None = None
    matches: list[int] = []
    pattern = re.compile(
        r'^(?P<prefix>[ \t]*task_file_sha256[ \t]*=[ \t]*")[0-9a-f]{64}'
        r'(?P<suffix>"[ \t]*(?:#.*)?(?:\r?\n)?$)'
    )
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
        if section == "taskset" and pattern.fullmatch(line):
            matches.append(index)
    if len(matches) != 1:
        raise PromotionError("config_task_hash_line_invalid")
    index = matches[0]
    lines[index] = pattern.sub(rf"\g<prefix>{new_sha256}\g<suffix>", lines[index])
    updated = "".join(lines).encode("utf-8")
    try:
        reparsed = tomllib.loads(updated.decode("utf-8"))
    except tomllib.TOMLDecodeError as cause:
        raise PromotionError("config_rewrite_invalid") from cause
    if reparsed["taskset"].get("task_file_sha256") != new_sha256:
        raise PromotionError("config_rewrite_invalid")
    return updated


def _stable_project_path(path: Path, project_root: Path) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(project_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as cause:
        raise PromotionError("promotion_path_outside_project") from cause
    if relative == Path("."):
        raise PromotionError("promotion_path_outside_project")
    return relative.as_posix()


def _receipt_destination(path: Path) -> Path:
    configured = path.expanduser().absolute()
    if not configured.name:
        raise PromotionError("receipt_path_invalid")
    try:
        parent = configured.parent.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("receipt_parent_unreadable") from cause
    if not parent.is_dir():
        raise PromotionError("receipt_parent_unreadable")
    destination = parent / configured.name
    try:
        destination.lstat()
    except FileNotFoundError:
        return destination
    except OSError as cause:
        raise PromotionError("receipt_target_unreadable") from cause
    raise PromotionError("receipt_already_exists")


def _write_receipt_once(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fchmod(handle.fileno(), 0o444)
                os.fsync(handle.fileno())
        except OSError as cause:
            raise PromotionError("receipt_staging_failed") from cause
        try:
            os.link(temporary, path)
        except FileExistsError as cause:
            raise PromotionError("receipt_already_exists") from cause
        except OSError as cause:
            raise PromotionError("receipt_publish_failed") from cause
    finally:
        temporary.unlink(missing_ok=True)


def _replace_files(updates: list[tuple[Path, bytes]]) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, data in updates:
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temporary, destination))
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def _promote_locked(
    oracle_dir: Path,
    output: Path,
    *,
    dataset_dir: Path,
    dataset_revision: str,
    expected_current_manifest_sha256: str,
    expected_prime_rl_commit: str,
    required_prime_rl_ancestor: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    expected_image_manifest_sha256: str,
    configs: list[Path],
    project_root: Path,
    expected_total: int = 2_538,
    limit: int = 2_500,
    minimum_pass_rate: float = 0.9,
    trusted_reference_solution: str = "public",
    expected_config_count: int = 2,
    minimum_prime_rl_ancestor: str | None = None,
    expected_source_wheel_policy_sha256: str | None = None,
    expected_source_wheel_attestations: int | None = None,
    apply: bool = False,
    receipt: Path | None = None,
) -> dict[str, Any]:
    if REVISION_RE.fullmatch(dataset_revision) is None:
        raise PromotionError("dataset_revision_invalid")
    if SHA256_RE.fullmatch(expected_current_manifest_sha256) is None:
        raise PromotionError("current_manifest_hash_invalid")
    if SHA256_RE.fullmatch(expected_image_manifest_sha256) is None:
        raise PromotionError("image_manifest_hash_invalid")
    if (expected_source_wheel_policy_sha256 is None) != (expected_source_wheel_attestations is None):
        raise PromotionError("source_wheel_contract_invalid")
    if expected_source_wheel_policy_sha256 is not None and (
        SHA256_RE.fullmatch(expected_source_wheel_policy_sha256) is None
        or type(expected_source_wheel_attestations) is not int
        or expected_source_wheel_attestations < 1
    ):
        raise PromotionError("source_wheel_contract_invalid")
    if expected_total < 1 or limit < 1 or limit > expected_total:
        raise PromotionError("task_counts_invalid")
    if not 0.0 <= minimum_pass_rate <= 1.0:
        raise PromotionError("minimum_pass_rate_invalid")
    if trusted_reference_solution not in {"declared", "public"}:
        raise PromotionError("trusted_reference_solution_invalid")
    if expected_config_count < 1 or len(configs) != expected_config_count:
        raise PromotionError("config_count_mismatch")
    if len(configs) != len({path.resolve() for path in configs}):
        raise PromotionError("configs_invalid")
    if apply and receipt is None:
        raise PromotionError("receipt_required_for_apply")
    receipt_path = _receipt_destination(receipt) if apply and receipt is not None else None

    output = output.resolve()
    current_bytes = _read_bytes(
        output,
        limit=MAX_MANIFEST_BYTES,
        error="current_manifest_unreadable",
    )
    current_sha256 = _sha256(current_bytes)
    if current_sha256 != expected_current_manifest_sha256:
        raise PromotionError("current_manifest_hash_mismatch")
    current_tasks = _manifest_tasks(current_bytes, error="current_manifest_invalid")
    if len(current_tasks) != limit:
        raise PromotionError("current_manifest_count_mismatch")

    canonical_at_promotion = _dataset_tasks(dataset_dir, dataset_revision, expected_total)
    (
        run_identity_sha256,
        run_identity_file_sha256,
        run_image_manifest,
        source_wheel_recovery,
    ) = _audit_run_identity(
        oracle_dir.resolve(),
        dataset_dir,
        dataset_revision,
        canonical_at_promotion,
        expected_prime_rl_commit=expected_prime_rl_commit,
        expected_verifiers_commit=expected_verifiers_commit,
        expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        expected_image_manifest_sha256=expected_image_manifest_sha256,
        expected_minimum_pass_rate=minimum_pass_rate,
        expected_minimum_valid=limit,
        trusted_reference_solution=trusted_reference_solution,
    )
    source_wheel_artifacts, source_wheel_entry_digests = _audit_source_wheel_artifacts(
        oracle_dir.resolve(),
        source_wheel_recovery,
    )
    source_wheel_policy_sha256 = (
        source_wheel_recovery["policy"]["sha256"] if source_wheel_recovery is not None else None
    )
    if source_wheel_recovery is None:
        if expected_source_wheel_policy_sha256 is not None:
            raise PromotionError("oracle_source_wheel_recovery_missing")
    elif (
        expected_source_wheel_policy_sha256 is None
        or source_wheel_policy_sha256 != expected_source_wheel_policy_sha256
        or len(source_wheel_entry_digests) != expected_source_wheel_attestations
        or source_wheel_artifacts is None
        or len(source_wheel_artifacts["wheelhouses"]) != expected_source_wheel_attestations
    ):
        raise PromotionError("oracle_source_wheel_policy_not_approved")
    source_wheel_attestation_sha256 = (
        source_wheel_artifacts["attestation"]["sha256"] if source_wheel_artifacts is not None else None
    )
    effective_minimum_prime_rl_ancestor = (
        MINIMUM_ORACLE_PRIME_RL_ANCESTOR if minimum_prime_rl_ancestor is None else minimum_prime_rl_ancestor
    )
    oracle_provenance_sha256, initial_provenance = _audit_provenance(
        oracle_dir.resolve(),
        project_root,
        expected_prime_rl_commit=expected_prime_rl_commit,
        required_prime_rl_ancestor=required_prime_rl_ancestor,
        minimum_prime_rl_ancestor=effective_minimum_prime_rl_ancestor,
        expected_verifiers_commit=expected_verifiers_commit,
        expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        expected_run_identity_sha256=run_identity_sha256,
        trusted_reference_solution=trusted_reference_solution,
        source_wheel_policy_sha256=source_wheel_policy_sha256,
    )
    invocation_source = {
        "prime_rl_commit": expected_prime_rl_commit,
        "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
        "verifiers_commit": expected_verifiers_commit,
        "vmvm_tb_v2_sha256": expected_vmvm_tb_v2_sha256,
    }
    invocation_record, invocation_count, rerun_invalid_invocation_count = _audit_invocations(
        oracle_dir.resolve(),
        expected_run_identity_sha256=run_identity_sha256,
        expected_source=invocation_source,
        initial_provenance=initial_provenance,
        source_wheel_policy_sha256=source_wheel_policy_sha256,
    )
    canonical, valid, passed, pass_rate, oracle_reasons, oracle_results_sha256, oracle_summary_sha256 = _audit_oracle(
        oracle_dir.resolve(),
        dataset_dir,
        dataset_revision,
        expected_total=expected_total,
        minimum_pass_rate=minimum_pass_rate,
        minimum_valid=limit,
        expected_run_identity_sha256=run_identity_sha256,
        trusted_reference_solution=trusted_reference_solution,
        source_wheel_attestation_sha256=source_wheel_attestation_sha256,
        known_source_wheel_attestation_sha256s=source_wheel_entry_digests,
    )
    canonical_set = set(canonical)
    if not set(current_tasks).issubset(canonical_set):
        raise PromotionError("current_manifest_not_in_dataset")

    preserved = [task for task in current_tasks if task in valid]
    replacements = [task for task in canonical if task in valid and task not in current_tasks]
    selected = (preserved + replacements)[:limit]
    if len(selected) != limit or len(selected) != len(set(selected)) or not set(selected).issubset(valid):
        raise PromotionError("selected_manifest_invariant_failed")
    selected_bytes = "".join(f"{task}\n" for task in selected).encode("utf-8")
    selected_sha256 = _sha256(selected_bytes)

    config_updates = [
        (
            path.resolve(),
            _updated_config(
                path.resolve(),
                project_root=project_root.resolve(),
                output=output,
                dataset_dir=dataset_dir,
                dataset_revision=dataset_revision,
                image_manifest=run_image_manifest,
                image_manifest_sha256=expected_image_manifest_sha256,
                current_sha256=current_sha256,
                new_sha256=selected_sha256,
                selected_count=limit,
            ),
        )
        for path in configs
    ]
    summary = {
        "applied": apply,
        "completed": expected_total,
        "configured_files": len(configs),
        "current_manifest_sha256": current_sha256,
        "dataset_revision": dataset_revision,
        "minimum_pass_rate": minimum_pass_rate,
        "minimum_valid": limit,
        "invocation_count": invocation_count,
        "oracle_image_manifest_sha256": expected_image_manifest_sha256,
        "oracle_invocations_sha256": invocation_record["sha256"],
        "oracle_pass_rate": pass_rate,
        "oracle_prime_rl_commit": expected_prime_rl_commit,
        "oracle_provenance_sha256": oracle_provenance_sha256,
        "oracle_reasons": oracle_reasons,
        "oracle_results_sha256": oracle_results_sha256,
        "oracle_run_identity_file_sha256": run_identity_file_sha256,
        "oracle_run_identity_sha256": run_identity_sha256,
        "oracle_summary_sha256": oracle_summary_sha256,
        "oracle_verifiers_commit": expected_verifiers_commit,
        "oracle_vmvm_tb_v2_sha256": expected_vmvm_tb_v2_sha256,
        "passed": passed,
        "removed_invalid": limit - len(preserved),
        "rerun_invalid_invocation_count": rerun_invalid_invocation_count,
        "selected": len(selected),
        "selected_manifest_sha256": selected_sha256,
        "selected_subset_valid": True,
        "trusted_reference_solution": trusted_reference_solution,
    }
    if source_wheel_artifacts is not None:
        summary["source_wheel_attestation_sha256"] = source_wheel_attestation_sha256
        summary["source_wheel_policy_sha256"] = source_wheel_policy_sha256
    final_invocation_audit = _audit_invocations(
        oracle_dir.resolve(),
        expected_run_identity_sha256=run_identity_sha256,
        expected_source=invocation_source,
        initial_provenance=initial_provenance,
        source_wheel_policy_sha256=source_wheel_policy_sha256,
    )
    if final_invocation_audit != (
        invocation_record,
        invocation_count,
        rerun_invalid_invocation_count,
    ):
        raise PromotionError("oracle_invocations_changed")
    if _audit_source_wheel_artifacts(
        oracle_dir.resolve(),
        source_wheel_recovery,
    ) != (source_wheel_artifacts, source_wheel_entry_digests):
        raise PromotionError("oracle_source_wheel_artifacts_changed")
    if apply:
        if receipt_path is None:
            raise PromotionError("receipt_required_for_apply")
        if _receipt_destination(receipt_path) != receipt_path:
            raise PromotionError("receipt_path_changed")
        manifest_record = {
            "path": _stable_project_path(output, project_root),
            "sha256": selected_sha256,
        }
        config_records = sorted(
            (
                {
                    "path": _stable_project_path(path, project_root),
                    "sha256": _sha256(updated),
                }
                for path, updated in config_updates
            ),
            key=lambda record: record["path"],
        )
        _replace_files([(output, selected_bytes), *config_updates])
        applied = _read_bytes(
            output,
            limit=MAX_MANIFEST_BYTES,
            error="applied_manifest_unreadable",
        )
        if _sha256(applied) != selected_sha256:
            raise PromotionError("applied_manifest_hash_mismatch")
        for path, expected in config_updates:
            observed = _read_bytes(path, limit=MAX_CONFIG_BYTES, error="applied_config_unreadable")
            if observed != expected:
                raise PromotionError("applied_config_mismatch")
        oracle_artifacts = {
            "invocations": invocation_record,
            "provenance": {"path": "provenance.txt", "sha256": oracle_provenance_sha256},
            "results": {"path": "results.jsonl", "sha256": oracle_results_sha256},
            "run_identity": {
                "identity_sha256": run_identity_sha256,
                "path": "run_identity.json",
                "sha256": run_identity_file_sha256,
            },
            "summary": {"path": "summary.json", "sha256": oracle_summary_sha256},
        }
        if source_wheel_artifacts is not None:
            oracle_artifacts["source_wheel_recovery"] = source_wheel_artifacts
        receipt_payload = {
            "acceptance": {
                "minimum_pass_rate": minimum_pass_rate,
                "minimum_valid": limit,
                "observed_pass_rate": pass_rate,
                "oracle_network_semantics": _expected_semantics(trusted_reference_solution),
                "selected_subset_valid": True,
            },
            "applied_manifest": manifest_record,
            "artifact_type": RECEIPT_ARTIFACT_TYPE,
            "counts": {
                "completed": expected_total,
                "configured_files": len(configs),
                "expected_total": expected_total,
                "invocation_count": invocation_count,
                "oracle_reasons": oracle_reasons,
                "passed": passed,
                "removed_invalid": limit - len(preserved),
                "rerun_invalid_invocation_count": rerun_invalid_invocation_count,
                "selected": len(selected),
            },
            "dataset": {"revision": dataset_revision},
            "image_manifest": {"sha256": expected_image_manifest_sha256},
            "oracle_artifacts": oracle_artifacts,
            "promotion_summary": dict(summary),
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "source": {
                "minimum_prime_rl_ancestor": effective_minimum_prime_rl_ancestor,
                "prime_rl_commit": expected_prime_rl_commit,
                "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
                "required_prime_rl_ancestor": required_prime_rl_ancestor,
                "verifiers_commit": expected_verifiers_commit,
                "vmvm_tb_v2_sha256": expected_vmvm_tb_v2_sha256,
            },
            "updated_configs": config_records,
        }
        receipt_sha256 = _canonical_json_sha256(receipt_payload)
        receipt_envelope = {
            "receipt": receipt_payload,
            "receipt_sha256": receipt_sha256,
            "schema_version": RECEIPT_SCHEMA_VERSION,
        }
        _write_receipt_once(receipt_path, _canonical_json_file(receipt_envelope))
        summary["receipt_sha256"] = receipt_sha256

    return summary


def promote(
    oracle_dir: Path,
    output: Path,
    *,
    dataset_dir: Path,
    dataset_revision: str,
    expected_current_manifest_sha256: str,
    expected_prime_rl_commit: str,
    required_prime_rl_ancestor: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    expected_image_manifest_sha256: str,
    configs: list[Path],
    project_root: Path,
    expected_total: int = 2_538,
    limit: int = 2_500,
    minimum_pass_rate: float = 0.9,
    trusted_reference_solution: str = "public",
    expected_config_count: int = 2,
    minimum_prime_rl_ancestor: str | None = None,
    expected_source_wheel_policy_sha256: str | None = None,
    expected_source_wheel_attestations: int | None = None,
    apply: bool = False,
    receipt: Path | None = None,
) -> dict[str, Any]:
    """Audit/promote one terminal oracle run while excluding active writers."""
    lock_path = oracle_dir.resolve() / ".writer.lock"
    try:
        lock = lock_path.open("rb")
    except OSError as cause:
        raise PromotionError("oracle_writer_lock_unreadable") from cause
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as cause:
            raise PromotionError("oracle_writer_active") from cause
        return _promote_locked(
            oracle_dir,
            output,
            dataset_dir=dataset_dir,
            dataset_revision=dataset_revision,
            expected_current_manifest_sha256=expected_current_manifest_sha256,
            expected_prime_rl_commit=expected_prime_rl_commit,
            required_prime_rl_ancestor=required_prime_rl_ancestor,
            expected_verifiers_commit=expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
            expected_image_manifest_sha256=expected_image_manifest_sha256,
            configs=configs,
            project_root=project_root,
            expected_total=expected_total,
            limit=limit,
            minimum_pass_rate=minimum_pass_rate,
            trusted_reference_solution=trusted_reference_solution,
            expected_config_count=expected_config_count,
            minimum_prime_rl_ancestor=minimum_prime_rl_ancestor,
            expected_source_wheel_policy_sha256=expected_source_wheel_policy_sha256,
            expected_source_wheel_attestations=expected_source_wheel_attestations,
            apply=apply,
            receipt=receipt,
        )
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--expected-current-manifest-sha256", required=True)
    parser.add_argument("--expected-prime-rl-commit", required=True)
    parser.add_argument("--required-prime-rl-ancestor", required=True)
    parser.add_argument("--expected-verifiers-commit", required=True)
    parser.add_argument("--expected-vmvm-tb-v2-sha256", required=True)
    parser.add_argument("--expected-image-manifest-sha256", required=True)
    parser.add_argument("--expected-source-wheel-policy-sha256")
    parser.add_argument("--expected-source-wheel-attestations", type=int)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--expected-config-count", type=int, default=2)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-total", type=int, default=2_538)
    parser.add_argument("--limit", type=int, default=2_500)
    parser.add_argument("--minimum-pass-rate", type=float, default=0.9)
    parser.add_argument(
        "--trusted-reference-solution",
        choices=("declared", "public"),
        default="public",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if args.apply and args.receipt is None:
        parser.error("--receipt is required with --apply")
    try:
        summary = promote(
            args.oracle_dir,
            args.output,
            dataset_dir=args.dataset_dir,
            dataset_revision=args.dataset_revision,
            expected_current_manifest_sha256=args.expected_current_manifest_sha256,
            expected_prime_rl_commit=args.expected_prime_rl_commit,
            required_prime_rl_ancestor=args.required_prime_rl_ancestor,
            expected_verifiers_commit=args.expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=args.expected_vmvm_tb_v2_sha256,
            expected_image_manifest_sha256=args.expected_image_manifest_sha256,
            configs=args.config,
            project_root=args.project_root,
            expected_total=args.expected_total,
            limit=args.limit,
            minimum_pass_rate=args.minimum_pass_rate,
            trusted_reference_solution=args.trusted_reference_solution,
            expected_config_count=args.expected_config_count,
            expected_source_wheel_policy_sha256=args.expected_source_wheel_policy_sha256,
            expected_source_wheel_attestations=args.expected_source_wheel_attestations,
            apply=args.apply,
            receipt=args.receipt,
        )
    except PromotionError as error:
        print(f"oracle_promotion_error:{error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
