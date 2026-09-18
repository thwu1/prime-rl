#!/usr/bin/env python3
"""Audit an oracle-repair canary without emitting task or result content."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import build_oracle_repair_canary as builder
from export_oracle_tasks import (
    RUN_IDENTITY_KEYS,
    PromotionError,
    _canonical_json_file,
    _canonical_json_sha256,
    _manifest_tasks,
    _sha256,
)

DEFAULT_EXPECTED_TOTAL = 2_538
DEFAULT_CONTROL_COUNT = 20
DEFAULT_MINIMUM_RECOVERED = 12
DEFAULT_SEED = builder.DEFAULT_SEED
CERTIFICATE_SCHEMA_VERSION = 1
CERTIFICATE_ARTIFACT_TYPE = "terminal_bench_vmvm_oracle_repair_canary_audit"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
EXECUTION_KEYS = {
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


class CanaryAuditError(ValueError):
    """An audit input failed without exposing row data."""


@dataclass(frozen=True)
class OracleSnapshot:
    identity: dict[str, Any]
    identity_sha256: str
    identity_file_sha256: str
    identity_path: Path
    identity_raw: bytes
    results: list[dict[str, Any]]
    reasons: Counter[str]
    results_sha256: str
    results_path: Path
    results_raw: bytes
    summary_sha256: str
    summary_path: Path
    summary_raw: bytes
    status_count: int


def _is_revision(value: object) -> bool:
    return isinstance(value, str) and REVISION_RE.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _is_absolute_path(value: object) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).is_absolute()


def _positive_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _validate_identity_contract(identity: dict[str, Any], *, error: str) -> None:
    dataset = identity.get("dataset")
    images = identity.get("images")
    network = identity.get("network_semantics")
    execution = identity.get("execution")
    acceptance = identity.get("acceptance")
    source = identity.get("source")
    if (
        not isinstance(dataset, dict)
        or set(dataset) != {"archive", "content_sha256", "path", "revision"}
        or not _is_absolute_path(dataset.get("path"))
        or not isinstance(images, dict)
        or set(images) != {"enable_compose", "manifest", "prefix", "tag", "use_declared_images"}
        or not isinstance(network, dict)
        or set(network) != {"schema_version", "trusted_reference_solution", "verifier"}
        or type(network.get("schema_version")) is not int
        or network["schema_version"] != 1
        or network.get("trusted_reference_solution") not in {"declared", "public"}
        or network.get("verifier") != "declared"
        or not isinstance(execution, dict)
        or set(execution) != EXECUTION_KEYS
        or not isinstance(acceptance, dict)
        or set(acceptance) != {"minimum_pass_rate", "minimum_valid"}
        or not isinstance(source, dict)
        or set(source) != {"prime_rl_commit", "prime_rl_tree_sha256", "verifiers_commit", "vmvm_tb_v2_sha256"}
        or not _is_revision(source.get("prime_rl_commit"))
        or source.get("prime_rl_tree_sha256") != CLEAN_TREE_SHA256
        or not _is_revision(source.get("verifiers_commit"))
        or not _is_sha256(source.get("vmvm_tb_v2_sha256"))
    ):
        raise CanaryAuditError(error)

    archive = dataset.get("archive")
    if not isinstance(archive, dict) or set(archive) != {"path", "sha256"}:
        raise CanaryAuditError(error)
    revision_dataset = (
        _is_revision(dataset.get("revision"))
        and archive == {"path": None, "sha256": None}
        and dataset.get("content_sha256") is None
    )
    archive_dataset = (
        dataset.get("revision") is None
        and _is_absolute_path(archive.get("path"))
        and _is_sha256(archive.get("sha256"))
        and _is_sha256(dataset.get("content_sha256"))
    )
    manifest = images.get("manifest")
    if (
        not (revision_dataset or archive_dataset)
        or not isinstance(manifest, dict)
        or set(manifest) != {"path", "sha256"}
        or not (
            manifest == {"path": None, "sha256": None}
            or (_is_absolute_path(manifest.get("path")) and _is_sha256(manifest.get("sha256")))
        )
        or not isinstance(images.get("prefix"), str)
        or not images["prefix"]
        or not isinstance(images.get("tag"), str)
        or not images["tag"]
        or images["tag"] == "latest"
        or not isinstance(images.get("use_declared_images"), bool)
        or not isinstance(images.get("enable_compose"), bool)
        or (archive_dataset and images.get("use_declared_images") is not True)
    ):
        raise CanaryAuditError(error)

    positive_ints = {
        "max_concurrent",
        "max_session_buffer_size",
        "vacli_image_pull_timeout_seconds",
        "vacli_max_concurrent_leases",
    }
    nonnegative_ints = {
        "infra_retries",
        "vacli_lease_retries",
        "vacli_max_pull_retries",
        "verifier_runtime_retries",
    }
    positive_numbers = {
        "resource_multiplier",
        "session_timeout_sec",
        "setup_timeout_sec",
        "timeout_multiplier",
        "validate_timeout_sec",
    }
    minimum_pass_rate = acceptance.get("minimum_pass_rate")
    minimum_valid = acceptance.get("minimum_valid")
    if (
        any(type(execution.get(key)) is not int or execution[key] < 1 for key in positive_ints)
        or any(type(execution.get(key)) is not int or execution[key] < 0 for key in nonnegative_ints)
        or any(not _positive_number(execution.get(key)) for key in positive_numbers)
        or not isinstance(execution.get("tenant_id"), str)
        or not execution["tenant_id"]
        or not isinstance(execution.get("lease_ttl"), str)
        or not execution["lease_ttl"]
        or execution.get("runtime_image") != "python:3.12-slim"
        or execution.get("runtime_workdir") != "/app"
        or not isinstance(execution.get("vacli_container_privileged"), bool)
        or isinstance(minimum_pass_rate, bool)
        or not isinstance(minimum_pass_rate, (int, float))
        or not math.isfinite(minimum_pass_rate)
        or not 0 <= minimum_pass_rate <= 1
        or type(minimum_valid) is not int
        or minimum_valid < 0
    ):
        raise CanaryAuditError(error)


def _load_full_source(
    oracle_dir: Path,
    expected_total: int,
    *,
    expected_prime_rl_commit: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
) -> OracleSnapshot:
    try:
        identity, identity_sha256, identity_file_sha256, identity_path, identity_raw = builder._run_identity(
            oracle_dir,
            expected_total,
        )
        _validate_identity_contract(identity, error="source_run_identity_invalid")
        expected_source = {
            "prime_rl_commit": expected_prime_rl_commit,
            "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
            "verifiers_commit": expected_verifiers_commit,
            "vmvm_tb_v2_sha256": expected_vmvm_tb_v2_sha256,
        }
        if identity["source"] != expected_source:
            raise CanaryAuditError("source_provenance_mismatch")
        selection = identity["selection"]
        results, reasons, results_sha256, results_path, results_raw = builder._results(
            oracle_dir,
            expected_total=expected_total,
            identity_sha256=identity_sha256,
            network_semantics=identity["network_semantics"],
            ordered_slugs_sha256=selection["ordered_task_slugs_sha256"],
        )
        passed = sum(row["valid"] for row in results)
        summary_sha256, summary_path, summary_raw = builder._summary(
            oracle_dir,
            expected_total=expected_total,
            identity_sha256=identity_sha256,
            network_semantics=identity["network_semantics"],
            reasons=reasons,
            passed=passed,
        )
        status_count = builder._statuses(oracle_dir, results)
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("source_oracle_invalid") from cause
    return OracleSnapshot(
        identity=identity,
        identity_sha256=identity_sha256,
        identity_file_sha256=identity_file_sha256,
        identity_path=identity_path,
        identity_raw=identity_raw,
        results=results,
        reasons=reasons,
        results_sha256=results_sha256,
        results_path=results_path,
        results_raw=results_raw,
        summary_sha256=summary_sha256,
        summary_path=summary_path,
        summary_raw=summary_raw,
        status_count=status_count,
    )


def _private_file(path: Path, *, error: str) -> tuple[Path, bytes]:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise CanaryAuditError(error) from cause
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise CanaryAuditError(error)
    try:
        raw = builder._read_limited(resolved, error=error)
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError(error) from cause
    return resolved, raw


def _task_file(path: Path) -> tuple[Path, bytes, list[str], str]:
    path, raw = _private_file(path, error="builder_task_file_invalid")
    try:
        tasks = _manifest_tasks(raw, error="builder_task_file_invalid")
    except PromotionError as cause:
        raise CanaryAuditError("builder_task_file_invalid") from cause
    return path, raw, tasks, _sha256(raw)


def _builder_receipt(
    path: Path,
    *,
    source: OracleSnapshot,
    task_bytes: bytes,
    task_sha256: str,
    control_count: int,
    seed: str,
) -> tuple[Path, bytes, str]:
    path, raw = _private_file(path, error="builder_receipt_invalid")
    try:
        envelope = builder._strict_json(raw, error="builder_receipt_invalid")
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("builder_receipt_invalid") from cause
    if set(envelope) != {"receipt", "receipt_sha256", "schema_version"}:
        raise CanaryAuditError("builder_receipt_invalid")
    payload = envelope.get("receipt")
    receipt_sha256 = envelope.get("receipt_sha256")
    if (
        type(envelope.get("schema_version")) is not int
        or envelope["schema_version"] != builder.RECEIPT_SCHEMA_VERSION
        or not isinstance(payload, dict)
        or not isinstance(receipt_sha256, str)
        or SHA256_RE.fullmatch(receipt_sha256) is None
        or _canonical_json_sha256(payload) != receipt_sha256
    ):
        raise CanaryAuditError("builder_receipt_invalid")
    try:
        expected_task_bytes, nonvalid_count = builder._selection(
            source.results,
            control_count,
            seed,
            source.identity_sha256,
        )
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("builder_receipt_mismatch") from cause
    if expected_task_bytes != task_bytes:
        raise CanaryAuditError("builder_task_file_mismatch")
    source_valid = sum(row["valid"] for row in source.results)
    selected_count = nonvalid_count + control_count
    expected_payload = {
        "artifact_type": builder.RECEIPT_ARTIFACT_TYPE,
        "counts": {
            "controls": control_count,
            "nonvalid": nonvalid_count,
            "oracle_reasons": dict(source.reasons),
            "selected": selected_count,
            "source_statuses": source.status_count,
            "source_total": len(source.results),
            "source_valid": source_valid,
        },
        "selection": {
            "algorithm": "sha256-seed-run-identity-slug-v1/source-order-output",
            "seed_sha256": _sha256(seed.encode("utf-8")),
            "task_file": {
                "count": selected_count,
                "mode": "0600",
                "sha256": task_sha256,
            },
        },
        "source_oracle": {
            "results": {"path": "results.jsonl", "sha256": source.results_sha256},
            "run_identity": {
                "identity_sha256": source.identity_sha256,
                "path": "run_identity.json",
                "sha256": source.identity_file_sha256,
            },
            "summary": {"path": "summary.json", "sha256": source.summary_sha256},
        },
        "schema_version": builder.RECEIPT_SCHEMA_VERSION,
    }
    if payload != expected_payload:
        raise CanaryAuditError("builder_receipt_mismatch")
    return path, raw, receipt_sha256


def _load_canary_identity(
    canary_dir: Path,
    *,
    task_file: Path,
    task_sha256: str,
    tasks: list[str],
    source: OracleSnapshot,
    expected_prime_rl_commit: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
) -> tuple[dict[str, Any], str, str, Path, bytes]:
    try:
        path, raw = builder._source_artifact(
            canary_dir,
            "run_identity.json",
            error="canary_run_identity_invalid",
        )
        wrapper = builder._strict_json(raw, error="canary_run_identity_invalid")
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("canary_run_identity_invalid") from cause
    if set(wrapper) != {"identity", "run_identity_sha256", "schema_version"}:
        raise CanaryAuditError("canary_run_identity_invalid")
    identity = wrapper.get("identity")
    identity_sha256 = wrapper.get("run_identity_sha256")
    if (
        type(wrapper.get("schema_version")) is not int
        or wrapper["schema_version"] != 1
        or not isinstance(identity, dict)
        or set(identity) != RUN_IDENTITY_KEYS
        or type(identity.get("schema_version")) is not int
        or identity["schema_version"] != 1
        or not isinstance(identity_sha256, str)
        or SHA256_RE.fullmatch(identity_sha256) is None
        or _canonical_json_sha256(identity) != identity_sha256
    ):
        raise CanaryAuditError("canary_run_identity_invalid")
    _validate_identity_contract(identity, error="canary_run_identity_invalid")
    selection = identity.get("selection")
    if not isinstance(selection, dict) or set(selection) != {
        "count",
        "limit",
        "offset",
        "ordered_task_slugs_sha256",
        "task_file",
    }:
        raise CanaryAuditError("canary_selection_identity_invalid")
    task_record = selection.get("task_file")
    if (
        type(selection.get("count")) is not int
        or selection["count"] != len(tasks)
        or type(selection.get("offset")) is not int
        or selection["offset"] != 0
        or selection.get("limit") is not None
        or selection.get("ordered_task_slugs_sha256") != builder._ordered_tasks_sha256(tasks)
        or task_record != {"path": str(task_file), "sha256": task_sha256}
    ):
        raise CanaryAuditError("canary_selection_identity_invalid")
    source_contract = source.identity.get("source")
    canary_source = identity.get("source")
    if not isinstance(source_contract, dict) or not isinstance(canary_source, dict):
        raise CanaryAuditError("canary_source_contract_invalid")
    source_keys = {"prime_rl_commit", "prime_rl_tree_sha256", "verifiers_commit", "vmvm_tb_v2_sha256"}
    # The completed source keeps its original provenance, while a compatibility
    # canary may intentionally exercise reviewed verifier or VMVM changes. Bind
    # every component of that execution source explicitly instead of mixing the
    # old source pins with unreviewed canary revisions.
    expected_canary_source = {
        "prime_rl_commit": expected_prime_rl_commit,
        "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
        "verifiers_commit": expected_verifiers_commit,
        "vmvm_tb_v2_sha256": expected_vmvm_tb_v2_sha256,
    }
    if (
        set(source_contract) != source_keys
        or set(canary_source) != source_keys
        or not _is_revision(source_contract.get("prime_rl_commit"))
        or source_contract.get("prime_rl_tree_sha256") != CLEAN_TREE_SHA256
        or not _is_revision(source_contract.get("verifiers_commit"))
        or not _is_sha256(source_contract.get("vmvm_tb_v2_sha256"))
        or canary_source != expected_canary_source
        or canary_source.get("prime_rl_commit") == source_contract.get("prime_rl_commit")
    ):
        raise CanaryAuditError("canary_source_contract_invalid")
    if (
        identity.get("dataset") != source.identity.get("dataset")
        or identity.get("images") != source.identity.get("images")
        or identity.get("network_semantics") != source.identity.get("network_semantics")
        or identity.get("execution") != source.identity.get("execution")
    ):
        raise CanaryAuditError("canary_benchmark_contract_invalid")
    return identity, identity_sha256, _sha256(raw), path, raw


def _load_canary(
    canary_dir: Path,
    *,
    task_file: Path,
    task_sha256: str,
    tasks: list[str],
    source: OracleSnapshot,
    expected_prime_rl_commit: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
) -> OracleSnapshot:
    identity, identity_sha256, identity_file_sha256, identity_path, identity_raw = _load_canary_identity(
        canary_dir,
        task_file=task_file,
        task_sha256=task_sha256,
        tasks=tasks,
        source=source,
        expected_prime_rl_commit=expected_prime_rl_commit,
        expected_verifiers_commit=expected_verifiers_commit,
        expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
    )
    try:
        results, reasons, results_sha256, results_path, results_raw = builder._results(
            canary_dir,
            expected_total=len(tasks),
            identity_sha256=identity_sha256,
            network_semantics=identity["network_semantics"],
            ordered_slugs_sha256=identity["selection"]["ordered_task_slugs_sha256"],
        )
        if [row["slug"] for row in results] != tasks:
            raise CanaryAuditError("canary_result_universe_mismatch")
        passed = sum(row["valid"] for row in results)
        summary_sha256, summary_path, summary_raw = builder._summary(
            canary_dir,
            expected_total=len(tasks),
            identity_sha256=identity_sha256,
            network_semantics=identity["network_semantics"],
            reasons=reasons,
            passed=passed,
        )
        status_count = builder._statuses(canary_dir, results)
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("canary_output_invalid") from cause
    return OracleSnapshot(
        identity=identity,
        identity_sha256=identity_sha256,
        identity_file_sha256=identity_file_sha256,
        identity_path=identity_path,
        identity_raw=identity_raw,
        results=results,
        reasons=reasons,
        results_sha256=results_sha256,
        results_path=results_path,
        results_raw=results_raw,
        summary_sha256=summary_sha256,
        summary_path=summary_path,
        summary_raw=summary_raw,
        status_count=status_count,
    )


def _unchanged(snapshot: OracleSnapshot) -> bool:
    try:
        return (
            builder._read_limited(snapshot.identity_path, error="source_changed") == snapshot.identity_raw
            and builder._read_limited(snapshot.results_path, error="source_changed") == snapshot.results_raw
            and builder._read_limited(snapshot.summary_path, error="source_changed") == snapshot.summary_raw
        )
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("source_changed") from cause


def _publish_certificate(path: Path, data: bytes) -> bool:
    try:
        existing = builder._existing_output(path)
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("audit_certificate_invalid") from cause
    if existing is not None:
        if existing == data:
            return False
        raise CanaryAuditError("audit_certificate_already_exists")
    try:
        temporary = builder._stage_file(path, data)
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("audit_certificate_publication_failed") from cause
    linked = False
    try:
        try:
            os.link(temporary, path)
            linked = True
            builder._fsync_directory(path.parent)
        except OSError as cause:
            if linked and builder._same_inode(temporary, path):
                path.unlink(missing_ok=True)
            raise CanaryAuditError("audit_certificate_publication_failed") from cause
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _transition_counts(
    source: OracleSnapshot,
    canary: OracleSnapshot,
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    source_by_slug = {row["slug"]: row for row in source.results}
    transitions: Counter[str] = Counter()
    selected_source_reasons: Counter[str] = Counter()
    unrecovered_reasons: Counter[str] = Counter()
    control_regression_reasons: Counter[str] = Counter()
    for row in canary.results:
        before = source_by_slug.get(row["slug"])
        if before is None:
            raise CanaryAuditError("canary_result_universe_mismatch")
        source_class = "valid" if before["valid"] else "nonvalid"
        canary_class = "valid" if row["valid"] else "nonvalid"
        transitions[f"source_{source_class}_to_{canary_class}"] += 1
        selected_source_reasons[before["reason"]] += 1
        if source_class == "nonvalid" and canary_class == "nonvalid":
            unrecovered_reasons[row["reason"]] += 1
        if source_class == "valid" and canary_class == "nonvalid":
            control_regression_reasons[row["reason"]] += 1
    reason_counts = {
        "canary": dict(canary.reasons),
        "control_regressions": dict(control_regression_reasons),
        "selected_source": dict(selected_source_reasons),
        "unrecovered": dict(unrecovered_reasons),
    }
    required_transition_keys = {
        "source_nonvalid_to_nonvalid",
        "source_nonvalid_to_valid",
        "source_valid_to_nonvalid",
        "source_valid_to_valid",
    }
    return {key: transitions.get(key, 0) for key in sorted(required_transition_keys)}, reason_counts


def audit_canary(
    source_oracle_dir: Path,
    builder_receipt: Path,
    task_file: Path,
    canary_dir: Path,
    certificate: Path,
    *,
    expected_source_prime_rl_commit: str,
    expected_source_verifiers_commit: str,
    expected_source_vmvm_tb_v2_sha256: str,
    expected_prime_rl_commit: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    expected_total: int = DEFAULT_EXPECTED_TOTAL,
    control_count: int = DEFAULT_CONTROL_COUNT,
    minimum_recovered: int = DEFAULT_MINIMUM_RECOVERED,
    seed: str = DEFAULT_SEED,
) -> dict[str, Any]:
    if not _is_revision(expected_source_prime_rl_commit):
        raise CanaryAuditError("expected_source_prime_rl_commit_invalid")
    if not _is_revision(expected_source_verifiers_commit):
        raise CanaryAuditError("expected_source_verifiers_commit_invalid")
    if not _is_sha256(expected_source_vmvm_tb_v2_sha256):
        raise CanaryAuditError("expected_source_vmvm_tb_v2_sha256_invalid")
    if not _is_revision(expected_prime_rl_commit):
        raise CanaryAuditError("expected_prime_rl_commit_invalid")
    if not _is_revision(expected_verifiers_commit):
        raise CanaryAuditError("expected_verifiers_commit_invalid")
    if not _is_sha256(expected_vmvm_tb_v2_sha256):
        raise CanaryAuditError("expected_vmvm_tb_v2_sha256_invalid")
    if type(expected_total) is not int or expected_total < 1:
        raise CanaryAuditError("expected_total_invalid")
    if type(control_count) is not int or control_count < 0:
        raise CanaryAuditError("control_count_invalid")
    if type(minimum_recovered) is not int or minimum_recovered < 0:
        raise CanaryAuditError("minimum_recovered_invalid")
    if (
        not isinstance(seed, str)
        or not seed
        or len(seed.encode("utf-8")) > 256
        or seed.strip() != seed
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in seed)
    ):
        raise CanaryAuditError("seed_invalid")
    try:
        source_oracle_dir = source_oracle_dir.resolve(strict=True)
        canary_dir = canary_dir.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise CanaryAuditError("oracle_directory_invalid") from cause
    if (
        not source_oracle_dir.is_dir()
        or not canary_dir.is_dir()
        or source_oracle_dir == canary_dir
        or source_oracle_dir.is_relative_to(canary_dir)
        or canary_dir.is_relative_to(source_oracle_dir)
    ):
        raise CanaryAuditError("oracle_directory_invalid")
    try:
        certificate = builder._target_path(certificate)
    except builder.CanaryManifestError as cause:
        raise CanaryAuditError("audit_certificate_path_invalid") from cause
    if certificate.is_relative_to(source_oracle_dir) or certificate.is_relative_to(canary_dir):
        raise CanaryAuditError("audit_certificate_path_invalid")

    lock_dirs = sorted(
        ((source_oracle_dir, "source_oracle"), (canary_dir, "canary")),
        key=lambda item: str(item[0]),
    )
    with ExitStack() as locks:
        for directory, label in lock_dirs:
            try:
                locks.enter_context(builder._hold_oracle_lock(directory))
            except builder.CanaryManifestError as cause:
                if str(cause) == "oracle_writer_active":
                    raise CanaryAuditError(f"{label}_writer_active") from cause
                raise CanaryAuditError(f"{label}_writer_lock_invalid") from cause
        source = _load_full_source(
            source_oracle_dir,
            expected_total,
            expected_prime_rl_commit=expected_source_prime_rl_commit,
            expected_verifiers_commit=expected_source_verifiers_commit,
            expected_vmvm_tb_v2_sha256=expected_source_vmvm_tb_v2_sha256,
        )
        task_file, task_raw, tasks, task_sha256 = _task_file(task_file)
        receipt_path, receipt_raw, builder_receipt_sha256 = _builder_receipt(
            builder_receipt,
            source=source,
            task_bytes=task_raw,
            task_sha256=task_sha256,
            control_count=control_count,
            seed=seed,
        )
        if (
            task_file == receipt_path
            or task_file.is_relative_to(source_oracle_dir)
            or task_file.is_relative_to(canary_dir)
            or receipt_path.is_relative_to(source_oracle_dir)
            or receipt_path.is_relative_to(canary_dir)
        ):
            raise CanaryAuditError("builder_artifact_path_invalid")
        if certificate in {task_file, receipt_path}:
            raise CanaryAuditError("audit_certificate_path_invalid")
        canary = _load_canary(
            canary_dir,
            task_file=task_file,
            task_sha256=task_sha256,
            tasks=tasks,
            source=source,
            expected_prime_rl_commit=expected_prime_rl_commit,
            expected_verifiers_commit=expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        )
        transitions, reason_counts = _transition_counts(source, canary)
        control_regressions = transitions["source_valid_to_nonvalid"]
        recovered = transitions["source_nonvalid_to_valid"]
        repair_candidates = recovered + transitions["source_nonvalid_to_nonvalid"]
        controls = transitions["source_valid_to_valid"] + control_regressions
        if controls != control_count or repair_candidates + controls != len(tasks):
            raise CanaryAuditError("canary_transition_counts_invalid")
        ok = control_regressions == 0 and recovered >= minimum_recovered
        state = "passed" if ok else "failed"
        source_contract = source.identity["source"]
        canary_contract = canary.identity["source"]
        payload = {
            "artifact_type": CERTIFICATE_ARTIFACT_TYPE,
            "artifacts": {
                "builder_receipt": {
                    "file_sha256": _sha256(receipt_raw),
                    "receipt_sha256": builder_receipt_sha256,
                },
                "canary": {
                    "results_sha256": canary.results_sha256,
                    "run_identity_file_sha256": canary.identity_file_sha256,
                    "run_identity_sha256": canary.identity_sha256,
                    "summary_sha256": canary.summary_sha256,
                },
                "source_oracle": {
                    "results_sha256": source.results_sha256,
                    "run_identity_file_sha256": source.identity_file_sha256,
                    "run_identity_sha256": source.identity_sha256,
                    "summary_sha256": source.summary_sha256,
                },
                "task_file": {
                    "count": len(tasks),
                    "mode": "0600",
                    "sha256": task_sha256,
                },
            },
            "contracts": {
                "canary_source": canary_contract,
                "dataset_sha256": _canonical_json_sha256(canary.identity["dataset"]),
                "execution_sha256": _canonical_json_sha256(canary.identity["execution"]),
                "images_sha256": _canonical_json_sha256(canary.identity["images"]),
                "network_semantics_sha256": _canonical_json_sha256(canary.identity["network_semantics"]),
                "source_oracle_source": source_contract,
            },
            "counts": {
                "canary_nonvalid": len(canary.results) - sum(row["valid"] for row in canary.results),
                "canary_valid": sum(row["valid"] for row in canary.results),
                "control_regressions": control_regressions,
                "controls": controls,
                "recovered": recovered,
                "repair_candidates": repair_candidates,
                "selected": len(tasks),
                "unrecovered": repair_candidates - recovered,
            },
            "gates": {
                "minimum_recovered": minimum_recovered,
                "required_control_regressions": 0,
            },
            "ok": ok,
            "reason_counts": reason_counts,
            "schema_version": CERTIFICATE_SCHEMA_VERSION,
            "selection": {
                "algorithm": "sha256-seed-run-identity-slug-v1/source-order-output",
                "seed_sha256": _sha256(seed.encode("utf-8")),
            },
            "state": state,
            "transitions": transitions,
        }
        certificate_sha256 = _canonical_json_sha256(payload)
        envelope = {
            "audit": payload,
            "audit_sha256": certificate_sha256,
            "schema_version": CERTIFICATE_SCHEMA_VERSION,
        }
        certificate_bytes = _canonical_json_file(envelope)
        try:
            current_task_path, current_task_raw = _private_file(
                task_file,
                error="source_changed",
            )
            current_receipt_path, current_receipt_raw = _private_file(
                receipt_path,
                error="source_changed",
            )
            unchanged_inputs = (
                _unchanged(source)
                and _unchanged(canary)
                and current_task_path == task_file
                and current_task_raw == task_raw
                and current_receipt_path == receipt_path
                and current_receipt_raw == receipt_raw
            )
        except (builder.CanaryManifestError, CanaryAuditError) as cause:
            raise CanaryAuditError("source_changed") from cause
        if not unchanged_inputs:
            raise CanaryAuditError("source_changed")
        published = _publish_certificate(certificate, certificate_bytes)

    return {
        "audit_sha256": certificate_sha256,
        "control_regressions": control_regressions,
        "controls": controls,
        "minimum_recovered": minimum_recovered,
        "ok": ok,
        "published": published,
        "reason_counts": reason_counts,
        "recovered": recovered,
        "repair_candidates": repair_candidates,
        "state": state,
        "transitions": transitions,
        "unrecovered": repair_candidates - recovered,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_oracle_dir", type=Path)
    parser.add_argument("builder_receipt", type=Path)
    parser.add_argument("task_file", type=Path)
    parser.add_argument("canary_dir", type=Path)
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--expected-source-prime-rl-commit", required=True)
    parser.add_argument("--expected-source-verifiers-commit", required=True)
    parser.add_argument("--expected-source-vmvm-tb-v2-sha256", required=True)
    parser.add_argument("--expected-prime-rl-commit", required=True)
    parser.add_argument("--expected-verifiers-commit", required=True)
    parser.add_argument("--expected-vmvm-tb-v2-sha256", required=True)
    parser.add_argument("--expected-total", type=int, default=DEFAULT_EXPECTED_TOTAL)
    parser.add_argument("--controls", type=int, default=DEFAULT_CONTROL_COUNT)
    parser.add_argument("--minimum-recovered", type=int, default=DEFAULT_MINIMUM_RECOVERED)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    try:
        summary = audit_canary(
            args.source_oracle_dir,
            args.builder_receipt,
            args.task_file,
            args.canary_dir,
            args.certificate,
            expected_source_prime_rl_commit=args.expected_source_prime_rl_commit,
            expected_source_verifiers_commit=args.expected_source_verifiers_commit,
            expected_source_vmvm_tb_v2_sha256=args.expected_source_vmvm_tb_v2_sha256,
            expected_prime_rl_commit=args.expected_prime_rl_commit,
            expected_verifiers_commit=args.expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=args.expected_vmvm_tb_v2_sha256,
            expected_total=args.expected_total,
            control_count=args.controls,
            minimum_recovered=args.minimum_recovered,
            seed=args.seed,
        )
    except CanaryAuditError as error:
        print(f"oracle_repair_canary_audit_error:{error}", file=sys.stderr)
        return 2
    except Exception:
        print("oracle_repair_canary_audit_error:internal_failure", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
