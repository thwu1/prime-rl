#!/usr/bin/env python3
"""Certify the private 2,499-member Sandoq side of the Qwen union."""

from __future__ import annotations

import argparse
import fcntl
import json
import re
from pathlib import Path
from typing import Any, Mapping

from direct_qwen_union_contract import (
    SHA256_RE,
    UnionContractError,
    artifact,
    audit_results,
    canonical_json,
    sha256_bytes,
    validate_shared_identity,
    write_exclusive,
)
from materialize_qwen_provider_union import (
    CANONICAL_SANDOQ_TEMPLATE_SHA256,
    CANONICAL_SOURCE_SHA256,
    SANDOQ_COUNT,
    MixedMaterializationError,
    validate_materialization,
)


class SandoqPartitionCertificateError(ValueError):
    pass


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def validate_cleanup(
    path: Path,
    *,
    expected_task_count: int = SANDOQ_COUNT,
    expected_concurrency: int = 64,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        not _integer(expected_task_count, minimum=1)
        or not _integer(expected_concurrency, minimum=1)
        or expected_concurrency > expected_task_count
    ):
        raise SandoqPartitionCertificateError("sandoq_cleanup_expectation_invalid")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise SandoqPartitionCertificateError("sandoq_cleanup_invalid") from error
    count_keys = {
        "schema_version",
        "recorded_outer_sessions",
        "verified_http_404",
        "already_absent",
        "deleted_and_verified",
        "assignments_acquired",
        "assignment_release_rows",
        "assignment_cancellation_rows",
        "cleanup_gateway_retry_count",
        "assignments_cleanup_verified",
        "assignment_event_order_high_water",
        "assignment_measured_high_water",
        "outer_sessions_created",
        "outer_sessions_deleted",
        "outer_session_high_water",
        "pool_drain_deleted",
        "gateway_close_warnings",
        "recovered_poisoned_assignments",
        "failures",
    }
    digest_keys = {
        "raw_audit_sha256",
        "pool_event_log_sha256",
        "pool_wal_sha256",
        "pool_drain_sha256",
    }
    expected = count_keys | digest_keys | {"kind", "state"}
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-pool-cleanup"
        or value.get("state") != "passed"
        or any(not _integer(value.get(key)) for key in count_keys)
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in digest_keys)
        or value["failures"] != 0
        or value["recorded_outer_sessions"] < 1
        or value["recorded_outer_sessions"] != value["verified_http_404"]
        or value["recorded_outer_sessions"] != value["already_absent"]
        or value["deleted_and_verified"] != 0
        or value["outer_sessions_created"] != value["recorded_outer_sessions"]
        or value["outer_sessions_deleted"] != value["recorded_outer_sessions"]
        or value["pool_drain_deleted"] > value["recorded_outer_sessions"]
        or value["outer_session_high_water"] < expected_concurrency
        or value["assignment_measured_high_water"] != expected_concurrency
        or value["assignment_measured_high_water"] > value["outer_session_high_water"]
        or value["assignments_acquired"] < expected_task_count
        or value["assignments_cleanup_verified"] != value["assignments_acquired"]
        or value["assignment_release_rows"] + value["assignment_cancellation_rows"]
        != value["assignments_acquired"]
    ):
        raise SandoqPartitionCertificateError("sandoq_cleanup_invalid")
    public = {
        "audit_sha256": sha256_bytes(raw),
        "assignment_attempts": value["assignments_acquired"],
        "assignment_cancellations": value["assignment_cancellation_rows"],
        "assignment_measured_high_water": expected_concurrency,
        "extra_assignment_attempts": value["assignments_acquired"] - expected_task_count,
        "gateway_close_warnings": value["gateway_close_warnings"],
        "outer_session_high_water": value["outer_session_high_water"],
        "recorded_outer_sessions": value["recorded_outer_sessions"],
        "recovered_poisoned_assignments": value["recovered_poisoned_assignments"],
        "typed_http_404": value["verified_http_404"],
        "zero_drop": True,
        "failures": 0,
    }
    raw_hashes = {key: value[key] for key in sorted(digest_keys)}
    return public, raw_hashes


def validate_auth_rotation(
    path: Path,
    *,
    expected_eval_run_identity_sha256: str,
    expected_results_sha256: str,
) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise SandoqPartitionCertificateError("auth_rotation_audit_invalid") from error
    expected = {
        "schema_version",
        "kind",
        "state",
        "refresh_source",
        "token_path_policy",
        "atomic_same_path",
        "monitor_started_before_rollout",
        "monitor_stopped_after_rollout",
        "maximum_refresh_interval_seconds",
        "fail_closed_before_expiry_seconds",
        "run_duration_seconds",
        "successful_replacements",
        "maximum_observed_refresh_gap_seconds",
        "maximum_observed_heartbeat_gap_seconds",
        "minimum_observed_expiry_margin_seconds",
        "batch_heartbeats",
        "liveness_failures",
        "expired_observations",
        "credential_payload_records",
        "raw_rotator_log_sha256",
        "raw_batch_guard_log_sha256",
        "eval_run_identity_sha256",
        "results_sha256",
    }
    integer_keys = {
        "maximum_refresh_interval_seconds",
        "fail_closed_before_expiry_seconds",
        "run_duration_seconds",
        "successful_replacements",
        "maximum_observed_refresh_gap_seconds",
        "maximum_observed_heartbeat_gap_seconds",
        "minimum_observed_expiry_margin_seconds",
        "batch_heartbeats",
        "liveness_failures",
        "expired_observations",
        "credential_payload_records",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-auth-rotation"
        or value.get("state") != "passed"
        or value.get("refresh_source") != "login-side-service"
        or value.get("token_path_policy") != "private-mode-0600-atomic-replace"
        or value.get("atomic_same_path") is not True
        or value.get("monitor_started_before_rollout") is not True
        or value.get("monitor_stopped_after_rollout") is not True
        or any(not _integer(value.get(key)) for key in integer_keys)
        or value["maximum_refresh_interval_seconds"] != 14_400
        or value["fail_closed_before_expiry_seconds"] < 1_800
        or value["run_duration_seconds"] < 1
        or value["successful_replacements"] < value["run_duration_seconds"] // 14_400
        or value["maximum_observed_refresh_gap_seconds"] > 14_400
        or value["maximum_observed_heartbeat_gap_seconds"] > 300
        or value["minimum_observed_expiry_margin_seconds"] < value["fail_closed_before_expiry_seconds"]
        or value["batch_heartbeats"] < 2
        or value["liveness_failures"] != 0
        or value["expired_observations"] != 0
        or value["credential_payload_records"] != 0
        or SHA256_RE.fullmatch(str(value.get("raw_rotator_log_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("raw_batch_guard_log_sha256", ""))) is None
        or value.get("eval_run_identity_sha256") != expected_eval_run_identity_sha256
        or value.get("results_sha256") != expected_results_sha256
    ):
        raise SandoqPartitionCertificateError("auth_rotation_audit_invalid")
    return {
        "audit_sha256": sha256_bytes(raw),
        "atomic_same_path": True,
        "batch_heartbeats": value["batch_heartbeats"],
        "fail_closed_before_expiry_seconds": value["fail_closed_before_expiry_seconds"],
        "maximum_observed_refresh_gap_seconds": value["maximum_observed_refresh_gap_seconds"],
        "maximum_observed_heartbeat_gap_seconds": value["maximum_observed_heartbeat_gap_seconds"],
        "maximum_refresh_interval_seconds": 14_400,
        "minimum_observed_expiry_margin_seconds": value["minimum_observed_expiry_margin_seconds"],
        "run_duration_seconds": value["run_duration_seconds"],
        "successful_replacements": value["successful_replacements"],
    }


def _provider_source(identity: Mapping[str, Any]) -> dict[str, Any]:
    source = identity["source"]
    keys = (
        "prime_rl_commit",
        "verifiers_commit",
        "renderers_commit",
        "sandoq_provider_commit",
        "sandoq_provider_tree",
        "sandoq_client_version",
        "sandoq_host_harness_sha256",
        "sandoq_site_sha256",
        "derived_image_manifest_sha256",
    )
    value = {key: source.get(key) for key in keys}
    if (
        any(not isinstance(item, str) or not item for item in value.values())
        or any(
            re.fullmatch(r"[0-9a-f]{40,64}", value[key]) is None
            for key in (
                "prime_rl_commit",
                "verifiers_commit",
                "renderers_commit",
                "sandoq_provider_commit",
                "sandoq_provider_tree",
            )
        )
        or any(
            SHA256_RE.fullmatch(value[key]) is None
            for key in (
                "sandoq_site_sha256",
                "sandoq_host_harness_sha256",
                "derived_image_manifest_sha256",
            )
        )
    ):
        raise SandoqPartitionCertificateError("sandoq_source_closure_invalid")
    value.update(
        direct_spec_sha256=identity["deployment"].get("spec_sha256"),
        direct_endpoint_bundle_sha256=identity["deployment"].get("endpoint_bundle_sha256"),
    )
    return value


def certify(
    *,
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_config: Path,
    cleanup_audit: Path,
    auth_rotation_audit: Path,
    materialization_receipt: Path,
    materialization_receipt_sha256: str,
    canonical_task_source: Path,
    canonical_dataset: Path,
    canonical_sandoq_template: Path,
    canonical_vmvm_template: Path,
    vmvm_task_file: Path,
    vmvm_config: Path,
    private_output_root: Path,
    predecessor: Path,
    predecessor_sha256: str,
) -> dict[str, Any]:
    lock_path = run_dir / ".writer.lock"
    try:
        lock = lock_path.open("rb")
    except OSError as error:
        raise SandoqPartitionCertificateError("writer_lock_missing") from error
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SandoqPartitionCertificateError("writer_active") from error
        try:
            materialization = validate_materialization(
                source=canonical_task_source,
                dataset=canonical_dataset,
                sandoq_template=canonical_sandoq_template,
                vmvm_template=canonical_vmvm_template,
                sandoq_tasks=expected_task_file,
                vmvm_tasks=vmvm_task_file,
                sandoq_config=expected_config,
                vmvm_config=vmvm_config,
                receipt=materialization_receipt,
                receipt_sha256=materialization_receipt_sha256,
                private_output_root=private_output_root,
            )
        except MixedMaterializationError as error:
            raise SandoqPartitionCertificateError("mixed_materialization_invalid") from error
        if artifact(expected_task_file)["sha256"] != expected_task_file_sha256:
            raise SandoqPartitionCertificateError("task_file_hash_mismatch")
        try:
            from eval_run_identity import load_eval_run_identity

            envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
            shared, execution = validate_shared_identity(
                envelope["identity"],
                expected_provider="sandoq",
                expected_task_file=expected_task_file,
                expected_task_sha256=expected_task_file_sha256,
                expected_count=SANDOQ_COUNT,
                expected_config=expected_config,
                expected_dataset=canonical_dataset,
            )
        except (KeyError, OSError, UnionContractError) as error:
            raise SandoqPartitionCertificateError("sandoq_identity_invalid") from error
        environment = execution.get("sandoq_environment")
        runtime = execution.get("runtime")
        if (
            execution.get("cleanup_must_succeed") is not True
            or execution.get("rollout_concurrency") != 64
            or execution.get("multiplex") != 64
            or execution.get("http_max_connections") != 32
            or execution.get("http_max_keepalive_connections") != 32
            or not isinstance(environment, dict)
            or environment.get("pool_size") != 64
            or environment.get("pool_min_size") != 0
            or not isinstance(runtime, dict)
            or runtime.get("type") != "sandoq"
            or runtime.get("network_access") is not False
        ):
            raise SandoqPartitionCertificateError("sandoq_execution_invalid")
        provider_source = _provider_source(envelope["identity"])
        try:
            from certify_direct_qwen_sandoq import validate_predecessor

            predecessor_record = validate_predecessor(
                SANDOQ_COUNT,
                predecessor,
                predecessor_sha256,
                expected_source=provider_source,
                expected_ramp={
                    "canonical_source_sha256": CANONICAL_SOURCE_SHA256,
                    "provider_partition_sha256": expected_task_file_sha256,
                    "template_sha256": CANONICAL_SANDOQ_TEMPLATE_SHA256,
                },
                current_task_file=expected_task_file,
            )
        except Exception as error:
            raise SandoqPartitionCertificateError("ramp_predecessor_invalid") from error
        try:
            results_sha256, traces = audit_results(
                run_dir / "results.jsonl",
                expected_task_file,
                SANDOQ_COUNT,
            )
        except UnionContractError as error:
            raise SandoqPartitionCertificateError(str(error)) from error
        cleanup, cleanup_source_hashes = validate_cleanup(cleanup_audit)
        auth_rotation = validate_auth_rotation(
            auth_rotation_audit,
            expected_eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            expected_results_sha256=results_sha256,
        )
        shared_sha256 = sha256_bytes(canonical_json(shared))
        return {
            "schema_version": 1,
            "kind": "direct-qwen-sandoq-partition",
            "state": "passed",
            "sandbox_provider": "sandoq",
            "task_count": SANDOQ_COUNT,
            "selection": "canonical-non-compose",
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": results_sha256,
            "worker_manifest_sha256": envelope["identity"]["deployment"]["worker_manifest"]["sha256"],
            "worker_count": 24,
            "trace_audit": traces,
            "pool_cleanup": cleanup,
            "sanitized_cleanup_source_hashes": cleanup_source_hashes,
            "auth_rotation": auth_rotation,
            "materialization": materialization,
            "predecessor": {
                "sha256": predecessor_record["sha256"],
                "stage_count": predecessor_record["stage_count"],
            },
            "shared_contract": shared,
            "shared_contract_sha256": shared_sha256,
            "provider_source": provider_source,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--expected-config", type=Path, required=True)
    parser.add_argument("--cleanup-audit", type=Path, required=True)
    parser.add_argument("--auth-rotation-audit", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--materialization-receipt-sha256", required=True)
    parser.add_argument("--canonical-task-source", type=Path, required=True)
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--canonical-sandoq-template", type=Path, required=True)
    parser.add_argument("--canonical-vmvm-template", type=Path, required=True)
    parser.add_argument("--vmvm-task-file", type=Path, required=True)
    parser.add_argument("--vmvm-config", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--predecessor-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    try:
        value = certify(**args)
        digest = write_exclusive(output, value)
    except (OSError, SandoqPartitionCertificateError) as error:
        code = str(error) if isinstance(error, SandoqPartitionCertificateError) else "certification_failed"
        raise SystemExit(code) from None
    print(digest)


if __name__ == "__main__":
    main()
