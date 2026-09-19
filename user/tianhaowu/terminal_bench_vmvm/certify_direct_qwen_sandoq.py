#!/usr/bin/env python3
"""Certify a direct-Qwen Sandoq ramp stage using aggregate trace evidence."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from audit_traces import (
    QWEN3_A95B_MODEL_IO_CONTRACT,
    _iter_traces,
    _read_expected_slugs,
    _summarize_traces,
)
from direct_qwen_workers import validate_saved_manifest
from eval_run_identity import load_eval_run_identity
from materialize_sandoq_ramp import CANONICAL_TEMPLATE_SHA256, materialize_config


class DirectSandoqCertificateError(ValueError):
    pass


STAGE_EXECUTION = {
    2: (2, 2, 2, None),
    8: (8, 8, 8, 2),
    24: (24, 24, 24, 8),
    2500: (64, 32, 64, 24),
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
CANONICAL_TASK_SOURCE_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_predecessor(
    expected_count: int,
    predecessor: Path | None,
    predecessor_sha256: str | None,
    *,
    expected_source: dict | None = None,
    expected_ramp: dict | None = None,
    current_task_file: Path | None = None,
) -> dict | None:
    try:
        required_predecessor = STAGE_EXECUTION[expected_count][3]
    except KeyError as error:
        raise DirectSandoqCertificateError("stage_count_invalid") from error
    if required_predecessor is None:
        if predecessor is not None or predecessor_sha256 is not None:
            raise DirectSandoqCertificateError("unexpected_predecessor")
        return None
    if predecessor is None or predecessor_sha256 is None:
        raise DirectSandoqCertificateError("predecessor_required")
    raw_predecessor = predecessor.resolve(strict=True).read_bytes()
    if (
        SHA256_RE.fullmatch(predecessor_sha256 or "") is None
        or hashlib.sha256(raw_predecessor).hexdigest() != predecessor_sha256
    ):
        raise DirectSandoqCertificateError("predecessor_hash_mismatch")
    try:
        prior = json.loads(raw_predecessor)
    except json.JSONDecodeError as error:
        raise DirectSandoqCertificateError("predecessor_invalid") from error
    if (
        not isinstance(prior, dict)
        or set(prior)
        != {
            "schema_version",
            "kind",
            "state",
            "stage_count",
            "eval_run_identity_sha256",
            "results_sha256",
            "task_file_sha256",
            "sandbox_provider",
            "cleanup_must_succeed",
            "worker_manifest_sha256",
            "worker_count",
            "pool_cleanup",
            "predecessor",
            "ramp",
            "source",
        }
        or prior.get("schema_version") != 1
        or prior.get("kind") != "direct-qwen-sandoq-ramp"
        or prior.get("state") != "passed"
        or prior.get("stage_count") != required_predecessor
        or prior.get("sandbox_provider") != "sandoq"
        or prior.get("cleanup_must_succeed") is not True
        or prior.get("pool_cleanup", {}).get("failures") != 0
        or prior.get("worker_count") != 24
        or any(
            SHA256_RE.fullmatch(str(prior.get(key, ""))) is None
            for key in (
                "eval_run_identity_sha256",
                "results_sha256",
                "task_file_sha256",
                "worker_manifest_sha256",
            )
        )
        or (expected_source is not None and prior.get("source") != expected_source)
        or (
            expected_ramp is not None
            and (
                prior.get("ramp", {}).get("source_sha256") != expected_ramp.get("source_sha256")
                or prior.get("ramp", {}).get("template_sha256") != expected_ramp.get("template_sha256")
            )
        )
    ):
        raise DirectSandoqCertificateError("predecessor_invalid")
    if current_task_file is not None:
        prefix = b"".join(
            current_task_file.resolve(strict=True).read_bytes().splitlines(keepends=True)[:required_predecessor]
        )
        if hashlib.sha256(prefix).hexdigest() != prior["task_file_sha256"]:
            raise DirectSandoqCertificateError("predecessor_prefix_mismatch")
    return {
        "sha256": predecessor_sha256,
        "stage_count": required_predecessor,
        "task_file_sha256": prior["task_file_sha256"],
    }


def validate_ramp_receipt(
    expected_count: int,
    expected_task_file_sha256: str,
    selected_task_file: Path,
    canonical_source: Path,
    canonical_template: Path,
    eval_config: Path,
    receipt_path: Path,
    receipt_sha256: str,
) -> dict:
    source_raw = canonical_source.resolve(strict=True).read_bytes()
    if hashlib.sha256(source_raw).hexdigest() != CANONICAL_TASK_SOURCE_SHA256:
        raise DirectSandoqCertificateError("canonical_task_source_mismatch")
    source_lines = source_raw.decode("utf-8").splitlines()
    if len(source_lines) != 2500 or len(source_lines) != len(set(source_lines)):
        raise DirectSandoqCertificateError("canonical_task_source_mismatch")
    expected_selection = ("\n".join(source_lines[:expected_count]) + "\n").encode()
    if (
        selected_task_file.resolve(strict=True).read_bytes() != expected_selection
        or hashlib.sha256(expected_selection).hexdigest() != expected_task_file_sha256
    ):
        raise DirectSandoqCertificateError("ramp_selection_not_canonical_prefix")
    if hashlib.sha256(canonical_template.resolve(strict=True).read_bytes()).hexdigest() != CANONICAL_TEMPLATE_SHA256:
        raise DirectSandoqCertificateError("canonical_template_mismatch")
    expected_config = materialize_config(
        canonical_template,
        CANONICAL_TEMPLATE_SHA256,
        count=expected_count,
        task_file=selected_task_file.resolve(),
        task_file_sha256=expected_task_file_sha256,
    )
    if eval_config.resolve(strict=True).read_bytes() != expected_config:
        raise DirectSandoqCertificateError("ramp_config_not_canonical_derivation")
    raw = receipt_path.resolve(strict=True).read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise DirectSandoqCertificateError("ramp_receipt_hash_mismatch")
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DirectSandoqCertificateError("ramp_receipt_invalid") from error
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {
            "schema_version",
            "selection",
            "source_sha256",
            "source_count",
            "selected_count",
            "selected_sha256",
            "template_sha256",
            "config_sha256",
        }
        or receipt.get("schema_version") != 1
        or receipt.get("selection") != "ordered-prefix"
        or receipt.get("source_count") != 2500
        or receipt.get("source_sha256") != CANONICAL_TASK_SOURCE_SHA256
        or receipt.get("template_sha256") != CANONICAL_TEMPLATE_SHA256
        or receipt.get("selected_count") != expected_count
        or receipt.get("selected_sha256") != expected_task_file_sha256
        or receipt.get("config_sha256") != _sha256(eval_config)
        or any(
            not isinstance(receipt.get(key), str) or SHA256_RE.fullmatch(receipt[key]) is None
            for key in ("source_sha256", "selected_sha256", "template_sha256", "config_sha256")
        )
    ):
        raise DirectSandoqCertificateError("ramp_receipt_invalid")
    return {
        "sha256": receipt_sha256,
        "source_sha256": receipt["source_sha256"],
        "template_sha256": receipt["template_sha256"],
        "config_sha256": receipt["config_sha256"],
        "selection": "ordered-prefix",
    }


def certify(
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_count: int,
    cleanup_audit: Path,
    ramp_receipt: Path,
    ramp_receipt_sha256: str,
    canonical_task_source: Path,
    canonical_template: Path,
    predecessor: Path | None = None,
    predecessor_sha256: str | None = None,
) -> dict:
    lock_path = run_dir / ".writer.lock"
    with lock_path.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DirectSandoqCertificateError("writer_active") from error
        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
        identity = envelope["identity"]
        source = identity.get("source", {})
        execution = identity.get("execution", {})
        if (
            identity.get("role") != "qwen-direct"
            or source.get("sandbox_provider") != "sandoq"
            or execution.get("cleanup_must_succeed") is not True
            or execution.get("runtime", {}).get("type") != "sandoq"
        ):
            raise DirectSandoqCertificateError("sandoq_identity_required")
        rollout, client, pool, _ = STAGE_EXECUTION[expected_count]
        environment = execution.get("sandoq_environment", {})
        if (
            execution.get("rollout_concurrency") != rollout
            or execution.get("multiplex") != rollout
            or execution.get("http_max_connections") != client
            or execution.get("http_max_keepalive_connections") != client
            or environment.get("pool_size") != pool
            or environment.get("pool_min_size") != 0
        ):
            raise DirectSandoqCertificateError("stage_concurrency_mismatch")
        ramp_record = validate_ramp_receipt(
            expected_count,
            expected_task_file_sha256,
            expected_task_file,
            canonical_task_source,
            canonical_template,
            Path(identity["config"]["source"]["path"]),
            ramp_receipt,
            ramp_receipt_sha256,
        )
        source_record = {
            key: source.get(key)
            for key in (
                "prime_rl_commit",
                "verifiers_commit",
                "renderers_commit",
                "sandoq_provider_commit",
                "sandoq_provider_tree",
                "sandoq_client_version",
                "sandoq_site_sha256",
                "derived_image_manifest_sha256",
            )
        }
        if any(not isinstance(value, str) or not value for value in source_record.values()):
            raise DirectSandoqCertificateError("source_closure_invalid")
        source_record.update(
            direct_spec_sha256=identity["deployment"].get("spec_sha256"),
            direct_endpoint_bundle_sha256=identity["deployment"].get("endpoint_bundle_sha256"),
        )
        if any(
            re.fullmatch(r"[0-9a-f]{40,64}", source_record[key]) is None
            for key in (
                "prime_rl_commit",
                "verifiers_commit",
                "renderers_commit",
                "sandoq_provider_commit",
                "sandoq_provider_tree",
            )
        ) or any(
            SHA256_RE.fullmatch(str(source_record[key])) is None
            for key in (
                "sandoq_site_sha256",
                "derived_image_manifest_sha256",
                "direct_spec_sha256",
                "direct_endpoint_bundle_sha256",
            )
        ):
            raise DirectSandoqCertificateError("source_closure_invalid")
        worker_manifest = validate_saved_manifest(Path(identity["deployment"]["worker_manifest"]["path"]))
        if len(worker_manifest["workers"]) != 24:
            raise DirectSandoqCertificateError("worker_generation_invalid")
        predecessor_record = validate_predecessor(
            expected_count,
            predecessor,
            predecessor_sha256,
            expected_source=source_record,
            expected_ramp=ramp_record,
            current_task_file=expected_task_file,
        )
        task_bytes = expected_task_file.resolve(strict=True).read_bytes()
        if hashlib.sha256(task_bytes).hexdigest() != expected_task_file_sha256:
            raise DirectSandoqCertificateError("task_file_hash_mismatch")
        expected_slugs = _read_expected_slugs(expected_task_file)
        task_record = identity.get("inputs", {}).get("task_file", {})
        if (
            len(expected_slugs) != expected_count
            or task_record.get("sha256") != expected_task_file_sha256
            or task_record.get("count") != expected_count
        ):
            raise DirectSandoqCertificateError("task_selection_mismatch")
        results = run_dir / "results.jsonl"
        before = _sha256(results)
        summary, failed = _summarize_traces(
            _iter_traces(results),
            expected_slugs=expected_slugs,
            expected_count=expected_count,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            model_io_contract=QWEN3_A95B_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            max_sequence_tokens=262_144,
        )
        if failed or summary.get("model_io_turns", 0) < expected_count:
            raise DirectSandoqCertificateError("trace_audit_failed")
        if _sha256(results) != before:
            raise DirectSandoqCertificateError("results_changed_during_audit")
        try:
            cleanup_raw = cleanup_audit.read_bytes()
            cleanup = json.loads(cleanup_raw)
        except (OSError, json.JSONDecodeError) as error:
            raise DirectSandoqCertificateError("pool_cleanup_proof_invalid") from error
        cleanup_keys = {
            "schema_version",
            "kind",
            "state",
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
            "raw_audit_sha256",
            "pool_event_log_sha256",
            "pool_wal_sha256",
            "pool_drain_sha256",
        }
        count_keys = cleanup_keys - {
            "kind",
            "state",
            "raw_audit_sha256",
            "pool_event_log_sha256",
            "pool_wal_sha256",
            "pool_drain_sha256",
        }
        if (
            not isinstance(cleanup, dict)
            or set(cleanup) != cleanup_keys
            or cleanup.get("schema_version") != 1
            or cleanup.get("kind") != "sandoq-pool-cleanup"
            or cleanup.get("state") != "passed"
            or cleanup.get("failures") != 0
            or cleanup.get("recorded_outer_sessions") != cleanup.get("verified_http_404")
            or any(
                not isinstance(cleanup.get(key), int) or isinstance(cleanup.get(key), bool) or cleanup[key] < 0
                for key in count_keys
            )
            or cleanup["recorded_outer_sessions"] < 1
            or cleanup.get("outer_session_high_water", 0) < pool
            or cleanup.get("assignment_measured_high_water") != rollout
            or cleanup["assignment_measured_high_water"] > cleanup.get("outer_session_high_water", 0)
            or cleanup.get("assignments_acquired", 0) < expected_count
            or cleanup.get("assignments_cleanup_verified") != cleanup.get("assignments_acquired")
            or cleanup.get("assignment_release_rows", 0) + cleanup.get("assignment_cancellation_rows", 0)
            != cleanup.get("assignments_acquired")
            or cleanup.get("outer_sessions_created") != cleanup.get("recorded_outer_sessions")
            or cleanup.get("outer_sessions_deleted") != cleanup.get("recorded_outer_sessions")
            or any(
                SHA256_RE.fullmatch(str(cleanup.get(key, ""))) is None
                for key in (
                    "raw_audit_sha256",
                    "pool_event_log_sha256",
                    "pool_wal_sha256",
                    "pool_drain_sha256",
                )
            )
        ):
            raise DirectSandoqCertificateError("pool_cleanup_proof_invalid")
        return {
            "schema_version": 1,
            "kind": "direct-qwen-sandoq-ramp",
            "state": "passed",
            "stage_count": expected_count,
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": before,
            "task_file_sha256": expected_task_file_sha256,
            "sandbox_provider": "sandoq",
            "cleanup_must_succeed": True,
            "worker_manifest_sha256": identity["deployment"]["worker_manifest"]["sha256"],
            "worker_count": 24,
            "pool_cleanup": {
                "audit_sha256": hashlib.sha256(cleanup_raw).hexdigest(),
                "recorded_outer_sessions": cleanup["recorded_outer_sessions"],
                "verified_http_404": cleanup["verified_http_404"],
                "assignment_event_order_high_water": cleanup["assignment_event_order_high_water"],
                "assignment_measured_high_water": cleanup["assignment_measured_high_water"],
                "outer_session_high_water": cleanup["outer_session_high_water"],
                "assignment_attempts": cleanup["assignments_acquired"],
                "assignment_cancellations": cleanup["assignment_cancellation_rows"],
                "extra_assignment_attempts": cleanup["assignments_acquired"] - expected_count,
                "gateway_close_warnings": cleanup.get("gateway_close_warnings", 0),
                "recovered_poisoned_assignments": cleanup["recovered_poisoned_assignments"],
                "failures": 0,
            },
            "predecessor": predecessor_record,
            "ramp": ramp_record,
            "source": source_record,
        }


def _write_exclusive(path: Path, payload: dict) -> None:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--expected-count", type=int, choices=(2, 8, 24, 2500), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cleanup-audit", type=Path, required=True)
    parser.add_argument("--ramp-receipt", type=Path, required=True)
    parser.add_argument("--ramp-receipt-sha256", required=True)
    parser.add_argument("--canonical-task-source", type=Path, required=True)
    parser.add_argument("--canonical-template", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path)
    parser.add_argument("--predecessor-sha256")
    args = parser.parse_args()
    certificate = certify(
        args.run_dir,
        args.expected_task_file,
        args.expected_task_file_sha256,
        args.expected_count,
        args.cleanup_audit,
        args.ramp_receipt,
        args.ramp_receipt_sha256,
        args.canonical_task_source,
        args.canonical_template,
        args.predecessor,
        args.predecessor_sha256,
    )
    _write_exclusive(args.output, certificate)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
