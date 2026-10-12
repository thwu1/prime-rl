#!/usr/bin/env python3
"""Create private provider certificates for the sealed Qwen repair union."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import certify_direct_qwen_sandoq as sandoq_ramp
import certify_direct_qwen_sandoq_partition as sandoq_evidence
import certify_direct_qwen_vmvm_compose as vmvm_evidence
import materialize_qwen_repair_provider_union as repair_materializer
import migrate_qwen_serving_generation as serving_generation
from audit_traces import qwen_repair_trace_contracts_value
from direct_qwen_union_contract import (
    HOST_HARNESS_CONTRACT,
    SHA256_RE,
    UnionContractError,
    audit_results,
    canonical_json,
    sha256_bytes,
    validate_shared_identity,
    write_exclusive,
)
from materialize_qwen_provider_union import SANDOQ_COUNT as CANONICAL_SANDOQ_COUNT

EXPECTED_REPAIR_COUNT = 1_233
EXPECTED_VMVM_COUNT = 0
SANDOQ_CONCURRENCY = 64
SANDOQ_HTTP_CONCURRENCY = 32
VMVM_CONCURRENCY = 96
VMVM_HTTP_CONCURRENCY = 48
MAX_PRIVATE_ARTIFACT_BYTES = 64 * 1024 * 1024


class RepairProviderCertificateError(ValueError):
    """A stable, aggregate-only repair provider certification failure."""


@dataclass(frozen=True, slots=True)
class RepairMaterializationInputs:
    source: Path
    dataset: Path
    sandoq_template: Path
    vmvm_template: Path
    repair_selection_manifest: Path
    repair_selection_manifest_sha256: str
    historical_source_dir: Path
    sandoq_tasks: Path
    vmvm_tasks: Path
    sandoq_config: Path
    vmvm_config: Path
    receipt: Path
    receipt_sha256: str
    private_output_root: Path

    def validate(self) -> dict[str, Any]:
        try:
            value = repair_materializer.validate_materialization(
                source=self.source,
                dataset=self.dataset,
                sandoq_template=self.sandoq_template,
                vmvm_template=self.vmvm_template,
                repair_selection_manifest=self.repair_selection_manifest,
                repair_selection_manifest_sha256=self.repair_selection_manifest_sha256,
                historical_source_dir=self.historical_source_dir,
                sandoq_tasks=self.sandoq_tasks,
                vmvm_tasks=self.vmvm_tasks,
                sandoq_config=self.sandoq_config,
                vmvm_config=self.vmvm_config,
                receipt=self.receipt,
                receipt_sha256=self.receipt_sha256,
                private_output_root=self.private_output_root,
            )
        except (OSError, repair_materializer.RepairProviderMaterializationError) as error:
            raise RepairProviderCertificateError("repair_materialization_invalid") from error
        return _validate_materialization_value(value)


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _sealed_repair_count() -> int:
    try:
        count = serving_generation._load_contract()["repair"]["repair_union_count"]
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        serving_generation.GenerationMigrationError,
    ) as error:
        raise RepairProviderCertificateError("repair_contract_invalid") from error
    if count != EXPECTED_REPAIR_COUNT:
        raise RepairProviderCertificateError("repair_contract_invalid")
    return count


def _validate_materialization_value(value: object) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "deployment_namespace",
        "canonical_source",
        "repair_selection",
        "partition",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise RepairProviderCertificateError("repair_materialization_invalid")
    selection = value.get("repair_selection")
    partition = value.get("partition")
    digest_fields = {"manifest_sha256", "task_file_sha256", "union_indices_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("kind") != repair_materializer.KIND
        or value.get("state") != "materialized"
        or value.get("deployment_namespace") != repair_materializer.DEPLOYMENT_NAMESPACE
        or value.get("canonical_source")
        != {
            "count": repair_materializer.CANONICAL_SOURCE_COUNT,
            "sha256": repair_materializer.CANONICAL_SOURCE_SHA256,
        }
        or not isinstance(selection, dict)
        or set(selection) != {"count", "source_partition", "trace_contracts", *digest_fields}
        or selection.get("count") != _sealed_repair_count()
        or selection.get("trace_contracts") != qwen_repair_trace_contracts_value()
        or selection.get("source_partition")
        != {
            "error_traces": 43,
            "exhaustive": True,
            "invalid_positive_traces": 82,
            "positive_reward_traces": 831,
            "repair_tasks": EXPECTED_REPAIR_COUNT,
            "retained_original_tasks": 1_267,
            "retained_valid_positive_traces": 749,
            "reward_zero_traces": 518,
            "seen_traces": 1_392,
            "source_task_count": 2_500,
            "superseded_legacy_empty_reasoning_traces": 1,
            "unseen_tasks": 1_108,
        }
        or any(SHA256_RE.fullmatch(str(selection.get(key, ""))) is None for key in digest_fields)
        or not isinstance(partition, dict)
        or set(partition)
        != {"disjoint", "exhaustive", "sandoq_count", "vmvm_count", "total_count"}
        or partition.get("disjoint") is not True
        or partition.get("exhaustive") is not True
        or not _integer(partition.get("sandoq_count"), minimum=1)
        or partition.get("vmvm_count") != EXPECTED_VMVM_COUNT
        or partition.get("total_count") != EXPECTED_REPAIR_COUNT
        or partition["sandoq_count"] + partition["vmvm_count"] != EXPECTED_REPAIR_COUNT
        or partition["sandoq_count"] != EXPECTED_REPAIR_COUNT
    ):
        raise RepairProviderCertificateError("repair_materialization_invalid")
    return value


def _private_file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _private_directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid


def _read_private_artifact(
    path: Path,
    private_output_root: Path,
    code: str,
) -> bytes:
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    file_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    if (
        not private_output_root.is_absolute()
        or private_output_root != Path(os.path.normpath(private_output_root))
        or not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or path.parent != private_output_root
        or path.name in {"", ".", ".."}
    ):
        raise RepairProviderCertificateError(code)
    directory = -1
    descriptor = -1
    observed_directory = -1
    try:
        if private_output_root.resolve(strict=True) != private_output_root:
            raise RepairProviderCertificateError(code)
        directory = os.open(private_output_root, directory_flags)
        root_before = os.fstat(directory)
        if (
            not stat.S_ISDIR(root_before.st_mode)
            or root_before.st_uid != os.getuid()
            or stat.S_IMODE(root_before.st_mode) != 0o700
        ):
            raise RepairProviderCertificateError(code)
        descriptor = os.open(path.name, file_flags, dir_fd=directory)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > MAX_PRIVATE_ARTIFACT_BYTES
        ):
            raise RepairProviderCertificateError(code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > MAX_PRIVATE_ARTIFACT_BYTES:
                raise RepairProviderCertificateError(code)
        after = os.fstat(descriptor)
        listed_after = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        root_after = os.fstat(directory)
        observed_directory = os.open(private_output_root, directory_flags)
        root_observed = os.fstat(observed_directory)
    except OSError as error:
        raise RepairProviderCertificateError(code) from error
    finally:
        if observed_directory >= 0:
            os.close(observed_directory)
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)
    if (
        _private_file_identity(before) != _private_file_identity(after)
        or _private_file_identity(after) != _private_file_identity(listed_after)
        or _private_directory_identity(root_before) != _private_directory_identity(root_after)
        or _private_directory_identity(root_after) != _private_directory_identity(root_observed)
    ):
        raise RepairProviderCertificateError(code)
    return bytes(body)


def _private_artifact_sha256(
    path: Path,
    private_output_root: Path,
    code: str,
) -> str:
    return sha256_bytes(_read_private_artifact(path, private_output_root, code))


def _validate_artifact(
    path: Path,
    expected_sha256: str,
    private_output_root: Path,
    code: str,
) -> None:
    observed = _private_artifact_sha256(path, private_output_root, code)
    if SHA256_RE.fullmatch(expected_sha256 or "") is None or observed != expected_sha256:
        raise RepairProviderCertificateError(code)


@contextmanager
def _locked_run(run_dir: Path) -> Iterator[None]:
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    file_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    if not run_dir.is_absolute() or run_dir != Path(os.path.normpath(run_dir)):
        raise RepairProviderCertificateError("run_directory_invalid")
    try:
        resolved = run_dir.resolve(strict=True)
        directory = os.open(run_dir, directory_flags)
    except OSError as error:
        raise RepairProviderCertificateError("run_directory_invalid") from error
    with ExitStack() as stack:
        stack.callback(os.close, directory)
        root_before = os.fstat(directory)
        if (
            run_dir != resolved
            or not stat.S_ISDIR(root_before.st_mode)
            or root_before.st_uid != os.getuid()
            or stat.S_IMODE(root_before.st_mode) != 0o700
        ):
            raise RepairProviderCertificateError("run_directory_invalid")
        locks: list[tuple[str, os.stat_result, Any]] = []
        for name in (".writer.lock", ".direct_router.lock"):
            try:
                descriptor = os.open(name, file_flags, dir_fd=directory)
            except OSError as error:
                raise RepairProviderCertificateError("run_lock_missing") from error
            lock = stack.enter_context(os.fdopen(descriptor, "rb"))
            lock_metadata = os.fstat(lock.fileno())
            if (
                not stat.S_ISREG(lock_metadata.st_mode)
                or lock_metadata.st_uid != os.getuid()
                or lock_metadata.st_nlink != 1
                or stat.S_IMODE(lock_metadata.st_mode) & 0o077
            ):
                raise RepairProviderCertificateError("run_lock_invalid")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RepairProviderCertificateError("run_active") from error
            locks.append((name, lock_metadata, lock))
        yield
        try:
            root_after = os.fstat(directory)
            observed_directory = os.open(run_dir, directory_flags)
        except OSError as error:
            raise RepairProviderCertificateError("run_directory_changed") from error
        try:
            root_observed = os.fstat(observed_directory)
        finally:
            os.close(observed_directory)
        if (
            _private_directory_identity(root_before)
            != _private_directory_identity(root_after)
            or _private_directory_identity(root_after)
            != _private_directory_identity(root_observed)
        ):
            raise RepairProviderCertificateError("run_directory_changed")
        for name, lock_before, lock in locks:
            try:
                lock_after = os.fstat(lock.fileno())
                lock_listed = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except OSError as error:
                raise RepairProviderCertificateError("run_lock_changed") from error
            if (
                _private_file_identity(lock_before) != _private_file_identity(lock_after)
                or _private_file_identity(lock_after) != _private_file_identity(lock_listed)
            ):
                raise RepairProviderCertificateError("run_lock_changed")


def _load_identity(
    *,
    run_dir: Path,
    provider: str,
    task_file: Path,
    task_file_sha256: str,
    task_count: int,
    config: Path,
    config_sha256: str,
    dataset: Path,
    private_output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _validate_artifact(
        task_file,
        task_file_sha256,
        private_output_root,
        "task_file_hash_mismatch",
    )
    _validate_artifact(
        config,
        config_sha256,
        private_output_root,
        "config_hash_mismatch",
    )
    try:
        from eval_run_identity import load_eval_run_identity

        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
        shared, execution = validate_shared_identity(
            envelope["identity"],
            expected_provider=provider,
            expected_task_file=task_file,
            expected_task_sha256=task_file_sha256,
            expected_count=task_count,
            expected_config=config,
            expected_dataset=dataset,
        )
        source_config = envelope["identity"]["config"]["source"]
    except (KeyError, OSError, TypeError, ValueError, UnionContractError) as error:
        raise RepairProviderCertificateError(f"{provider}_identity_invalid") from error
    if (
        source_config.get("sha256") != config_sha256
        or shared.get("contract", {}).get("harness") != HOST_HARNESS_CONTRACT
        or shared.get("deployment", {}).get("worker_count") != 24
    ):
        raise RepairProviderCertificateError(f"{provider}_identity_invalid")
    return envelope, shared, execution


def _validate_sandoq_execution(execution: object) -> None:
    if not isinstance(execution, Mapping):
        raise RepairProviderCertificateError("sandoq_execution_invalid")
    environment = execution.get("sandoq_environment")
    runtime = execution.get("runtime")
    if (
        execution.get("cleanup_must_succeed") is not True
        or execution.get("rollout_concurrency") != SANDOQ_CONCURRENCY
        or execution.get("multiplex") != SANDOQ_CONCURRENCY
        or execution.get("http_max_connections") != SANDOQ_HTTP_CONCURRENCY
        or execution.get("http_max_keepalive_connections") != SANDOQ_HTTP_CONCURRENCY
        or not isinstance(environment, Mapping)
        or environment.get("environment") != "oci-runner-firecracker"
        or environment.get("task_network") != "none"
        or environment.get("pool_size") != SANDOQ_CONCURRENCY
        or environment.get("pool_min_size") != 0
        or not isinstance(runtime, Mapping)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("network_access") is not False
        or runtime.get("host_tunnel") != "none"
        or runtime.get("expected_environment") != "oci-runner-firecracker"
    ):
        raise RepairProviderCertificateError("sandoq_execution_invalid")


def _validate_vmvm_execution(execution: object) -> None:
    if not isinstance(execution, Mapping):
        raise RepairProviderCertificateError("vmvm_execution_invalid")
    runtime = execution.get("runtime")
    if (
        execution.get("cleanup_must_succeed") is not True
        or execution.get("rollout_concurrency") != VMVM_CONCURRENCY
        or execution.get("multiplex") != VMVM_CONCURRENCY
        or execution.get("http_max_connections") != VMVM_HTTP_CONCURRENCY
        or execution.get("http_max_keepalive_connections") != VMVM_HTTP_CONCURRENCY
        or execution.get("cleanup_receipt_contract")
        != {
            "kind": "vacli-release-on-exit-v1",
            "receipt": "private-aggregate-jsonl",
            "release_on_exit_completed": True,
            "remote_deletion_verified": False,
        }
        or not isinstance(runtime, Mapping)
        or runtime.get("type") != "vmvm"
    ):
        raise RepairProviderCertificateError("vmvm_execution_invalid")


def _sandoq_execution_proof() -> dict[str, Any]:
    return {
        "harness_placement": "host",
        "runtime": "sandoq",
        "environment": "oci-runner-firecracker",
        "task_network": "none",
        "rollout_concurrency": SANDOQ_CONCURRENCY,
        "multiplex": SANDOQ_CONCURRENCY,
        "http_max_connections": SANDOQ_HTTP_CONCURRENCY,
        "http_max_keepalive_connections": SANDOQ_HTTP_CONCURRENCY,
        "pool_size": SANDOQ_CONCURRENCY,
        "pool_min_size": 0,
    }


def _vmvm_execution_proof() -> dict[str, Any]:
    return {
        "harness_placement": "host",
        "runtime": "vmvm",
        "network_policy": "both-phases-no-network",
        "rollout_concurrency": VMVM_CONCURRENCY,
        "multiplex": VMVM_CONCURRENCY,
        "http_max_connections": VMVM_HTTP_CONCURRENCY,
        "http_max_keepalive_connections": VMVM_HTTP_CONCURRENCY,
    }


def _lane_binding(
    *,
    task_file_sha256: str,
    config_sha256: str,
    eval_run_identity_sha256: str,
    results_sha256: str,
    worker_manifest_sha256: str,
) -> dict[str, str]:
    values = {
        "task_file_sha256": task_file_sha256,
        "config_sha256": config_sha256,
        "eval_run_identity_sha256": eval_run_identity_sha256,
        "results_sha256": results_sha256,
        "worker_manifest_sha256": worker_manifest_sha256,
    }
    if any(SHA256_RE.fullmatch(value) is None for value in values.values()):
        raise RepairProviderCertificateError("lane_binding_invalid")
    return values


def certify_sandoq(
    *,
    run_dir: Path,
    task_file_sha256: str,
    config_sha256: str,
    cleanup_audit: Path,
    auth_rotation_audit: Path,
    predecessor: Path,
    predecessor_sha256: str,
    materialization_inputs: RepairMaterializationInputs,
) -> dict[str, Any]:
    materialization = _validate_materialization_value(materialization_inputs.validate())
    task_count = materialization["partition"]["sandoq_count"]
    with _locked_run(run_dir):
        envelope, shared, execution = _load_identity(
            run_dir=run_dir,
            provider="sandoq",
            task_file=materialization_inputs.sandoq_tasks,
            task_file_sha256=task_file_sha256,
            task_count=task_count,
            config=materialization_inputs.sandoq_config,
            config_sha256=config_sha256,
            dataset=materialization_inputs.dataset,
            private_output_root=materialization_inputs.private_output_root,
        )
        _validate_sandoq_execution(execution)
        try:
            provider_source = sandoq_evidence._provider_source(envelope["identity"])
            predecessor_record = sandoq_ramp.validate_predecessor(
                CANONICAL_SANDOQ_COUNT,
                predecessor,
                predecessor_sha256,
                expected_source=provider_source,
            )
        except Exception as error:
            raise RepairProviderCertificateError("sandoq_predecessor_invalid") from error
        if predecessor_record is None or predecessor_record.get("stage_count") != 64:
            raise RepairProviderCertificateError("sandoq_predecessor_invalid")
        try:
            results_sha256, traces = audit_results(
                run_dir / "results.jsonl",
                materialization_inputs.sandoq_tasks,
                task_count,
            )
            cleanup, cleanup_source_hashes = sandoq_evidence.validate_cleanup(
                cleanup_audit,
                expected_task_count=task_count,
                expected_concurrency=SANDOQ_CONCURRENCY,
            )
            auth_rotation = sandoq_evidence.validate_auth_rotation(
                auth_rotation_audit,
                expected_eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
                expected_results_sha256=results_sha256,
            )
        except (OSError, ValueError, UnionContractError) as error:
            raise RepairProviderCertificateError("sandoq_evidence_invalid") from error
    shared_sha256 = sha256_bytes(canonical_json(shared))
    return {
        "schema_version": 1,
        "kind": "direct-qwen-repair-sandoq-partition",
        "state": "passed",
        "sandbox_provider": "sandoq",
        "task_count": task_count,
        "selection": "sealed-repair-intersection",
        "lane_binding": _lane_binding(
            task_file_sha256=task_file_sha256,
            config_sha256=config_sha256,
            eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            results_sha256=results_sha256,
            worker_manifest_sha256=envelope["identity"]["deployment"]["worker_manifest"]["sha256"],
        ),
        "worker_count": 24,
        "execution_proof": _sandoq_execution_proof(),
        "trace_audit": traces,
        "pool_cleanup": cleanup,
        "sanitized_cleanup_source_hashes": cleanup_source_hashes,
        "auth_rotation": auth_rotation,
        "predecessor": {
            "sha256": predecessor_record["sha256"],
            "stage_count": 64,
        },
        "materialization": materialization,
        "shared_contract": shared,
        "shared_contract_sha256": shared_sha256,
        "provider_source": provider_source,
    }


def certify_vmvm(
    *,
    run_dir: Path,
    task_file_sha256: str,
    config_sha256: str,
    cleanup_receipt: Path,
    lifecycle_receipt: Path,
    materialization_inputs: RepairMaterializationInputs,
) -> dict[str, Any]:
    materialization = _validate_materialization_value(materialization_inputs.validate())
    if materialization["partition"]["vmvm_count"] != 1:
        raise RepairProviderCertificateError("vmvm_lane_not_selected")
    with _locked_run(run_dir):
        envelope, shared, execution = _load_identity(
            run_dir=run_dir,
            provider="vmvm",
            task_file=materialization_inputs.vmvm_tasks,
            task_file_sha256=task_file_sha256,
            task_count=1,
            config=materialization_inputs.vmvm_config,
            config_sha256=config_sha256,
            dataset=materialization_inputs.dataset,
            private_output_root=materialization_inputs.private_output_root,
        )
        _validate_vmvm_execution(execution)
        try:
            results_sha256, traces = audit_results(
                run_dir / "results.jsonl",
                materialization_inputs.vmvm_tasks,
                1,
            )
            verifier_mode = vmvm_evidence._verifier_mode_from_results(run_dir / "results.jsonl")
            runtime_nonces = vmvm_evidence._read_private_lifecycle_receipts(
                lifecycle_receipt,
                run_dir=run_dir,
                expected_identity_sha256=envelope["eval_run_identity_sha256"],
            )
            cleanup = vmvm_evidence._read_private_cleanup_receipts(
                cleanup_receipt,
                run_dir=run_dir,
                expected_identity_sha256=envelope["eval_run_identity_sha256"],
                expected_runtime_nonces=runtime_nonces,
                verifier_mode=verifier_mode,
            )
            provider_source = vmvm_evidence._provider_source(envelope["identity"])
        except (OSError, ValueError, UnionContractError) as error:
            raise RepairProviderCertificateError("vmvm_evidence_invalid") from error
    shared_sha256 = sha256_bytes(canonical_json(shared))
    return {
        "schema_version": 1,
        "kind": "direct-qwen-repair-vmvm-partition",
        "state": "passed",
        "sandbox_provider": "vmvm",
        "task_count": 1,
        "selection": "sealed-repair-intersection",
        "lane_binding": _lane_binding(
            task_file_sha256=task_file_sha256,
            config_sha256=config_sha256,
            eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            results_sha256=results_sha256,
            worker_manifest_sha256=envelope["identity"]["deployment"]["worker_manifest"]["sha256"],
        ),
        "worker_count": 24,
        "execution_proof": _vmvm_execution_proof(),
        "trace_audit": traces,
        "compose_proof": {
            "compose_count": 1,
            "network_policy": "both-phases-no-network",
            "runtime": "vmvm",
            "vmvm_tb_v2_sha256": envelope["identity"]["source"]["vmvm_tb_v2_sha256"],
        },
        "runtime_cleanup": cleanup,
        "materialization": materialization,
        "shared_contract": shared,
        "shared_contract_sha256": shared_sha256,
        "provider_source": provider_source,
    }


def certify_vmvm_absence(
    *,
    task_file_sha256: str,
    config_sha256: str,
    materialization_inputs: RepairMaterializationInputs,
) -> dict[str, Any]:
    materialization = _validate_materialization_value(materialization_inputs.validate())
    if materialization["partition"]["vmvm_count"] != 0:
        raise RepairProviderCertificateError("vmvm_lane_selected")
    _validate_artifact(
        materialization_inputs.vmvm_tasks,
        task_file_sha256,
        materialization_inputs.private_output_root,
        "task_file_hash_mismatch",
    )
    _validate_artifact(
        materialization_inputs.vmvm_config,
        config_sha256,
        materialization_inputs.private_output_root,
        "config_hash_mismatch",
    )
    task_body = _read_private_artifact(
        materialization_inputs.vmvm_tasks,
        materialization_inputs.private_output_root,
        "vmvm_absence_invalid",
    )
    if task_body:
        raise RepairProviderCertificateError("vmvm_absence_invalid")
    return {
        "schema_version": 1,
        "kind": "direct-qwen-repair-vmvm-absence",
        "state": "absent",
        "sandbox_provider": "vmvm",
        "task_count": 0,
        "selection": "sealed-repair-intersection",
        "lane_binding": {
            "task_file_sha256": task_file_sha256,
            "config_sha256": config_sha256,
        },
        "launch_evidence_present": False,
        "materialization": materialization,
    }


def _write_private(path: Path, value: Mapping[str, Any]) -> str:
    try:
        parent = path.parent.resolve(strict=True)
        metadata = path.parent.lstat()
    except OSError as error:
        raise RepairProviderCertificateError("private_certificate_parent_invalid") from error
    if (
        path.parent != parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise RepairProviderCertificateError("private_certificate_parent_invalid")
    digest = write_exclusive(path, value)
    output = path.lstat()
    if (
        not stat.S_ISREG(output.st_mode)
        or output.st_uid != os.getuid()
        or stat.S_IMODE(output.st_mode) != 0o600
        or output.st_nlink != 1
    ):
        raise RepairProviderCertificateError("private_certificate_invalid")
    return digest


def _add_materialization_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sandoq-template", type=Path, required=True)
    parser.add_argument("--vmvm-template", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest-sha256", required=True)
    parser.add_argument("--historical-source-dir", type=Path, required=True)
    parser.add_argument("--sandoq-tasks", type=Path, required=True)
    parser.add_argument("--vmvm-tasks", type=Path, required=True)
    parser.add_argument("--sandoq-config", type=Path, required=True)
    parser.add_argument("--vmvm-config", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--materialization-receipt-sha256", required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--task-file-sha256", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)


def _materialization_inputs(args: argparse.Namespace) -> RepairMaterializationInputs:
    return RepairMaterializationInputs(
        source=args.source,
        dataset=args.dataset,
        sandoq_template=args.sandoq_template,
        vmvm_template=args.vmvm_template,
        repair_selection_manifest=args.repair_selection_manifest,
        repair_selection_manifest_sha256=args.repair_selection_manifest_sha256,
        historical_source_dir=args.historical_source_dir,
        sandoq_tasks=args.sandoq_tasks,
        vmvm_tasks=args.vmvm_tasks,
        sandoq_config=args.sandoq_config,
        vmvm_config=args.vmvm_config,
        receipt=args.materialization_receipt,
        receipt_sha256=args.materialization_receipt_sha256,
        private_output_root=args.private_output_root,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="provider", required=True)
    sandoq = subparsers.add_parser("sandoq")
    _add_materialization_arguments(sandoq)
    sandoq.add_argument("--run-dir", type=Path, required=True)
    sandoq.add_argument("--cleanup-audit", type=Path, required=True)
    sandoq.add_argument("--auth-rotation-audit", type=Path, required=True)
    sandoq.add_argument("--predecessor", type=Path, required=True)
    sandoq.add_argument("--predecessor-sha256", required=True)
    vmvm = subparsers.add_parser("vmvm")
    _add_materialization_arguments(vmvm)
    vmvm.add_argument("--run-dir", type=Path, required=True)
    vmvm.add_argument("--cleanup-receipt", type=Path, required=True)
    vmvm.add_argument("--lifecycle-receipt", type=Path, required=True)
    absence = subparsers.add_parser("vmvm-absence")
    _add_materialization_arguments(absence)
    args = parser.parse_args()
    common = {
        "task_file_sha256": args.task_file_sha256,
        "config_sha256": args.config_sha256,
        "materialization_inputs": _materialization_inputs(args),
    }
    try:
        if args.provider == "sandoq":
            value = certify_sandoq(
                run_dir=args.run_dir,
                cleanup_audit=args.cleanup_audit,
                auth_rotation_audit=args.auth_rotation_audit,
                predecessor=args.predecessor,
                predecessor_sha256=args.predecessor_sha256,
                **common,
            )
        elif args.provider == "vmvm":
            value = certify_vmvm(
                run_dir=args.run_dir,
                cleanup_receipt=args.cleanup_receipt,
                lifecycle_receipt=args.lifecycle_receipt,
                **common,
            )
        else:
            value = certify_vmvm_absence(**common)
        _write_private(args.output, value)
    except (OSError, RepairProviderCertificateError) as error:
        code = str(error) if isinstance(error, RepairProviderCertificateError) else "certification_failed"
        raise SystemExit(code) from None
    print(
        json.dumps(
            {
                "provider": value["sandbox_provider"],
                "state": value["state"],
                "task_count": value["task_count"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
