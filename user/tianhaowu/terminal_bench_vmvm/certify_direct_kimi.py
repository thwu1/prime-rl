#!/usr/bin/env python3
"""Publish aggregate-only certificates for direct-Kimi Sandoq TB4 runs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from audit_tb4_results import (
    EXPECTED_SUPPORTED_TASK_COUNT,
    EXPECTED_TASK_COUNT,
    audit_results,
)
from audit_traces import (
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    _iter_traces,
    _read_expected_slugs,
    _summarize_traces,
)
from direct_kimi_workers import (
    EXPECTED_ENDPOINTS,
    EXPECTED_MODEL,
    ROUTER_POLICY,
    ROUTER_PROVIDER_CONCURRENCY,
    ROUTER_REQUEST_ID_HEADERS,
    ROUTER_REQUEST_TIMEOUT_SECONDS,
    ROUTER_RETRIES,
    validate_saved_manifest,
)
from eval_run_identity import canonical_json, load_eval_run_identity

SHA256_RE = re.compile(r"[0-9a-f]{64}")
SMOKE_TASK_COUNT = 2
TB4_MIN_SUPPORTED_PASS_RATE = 0.04
TB4_MAX_SUPPORTED_PASS_RATE = 0.22
MAX_SEQUENCE_TOKENS = 262_144


class DirectKimiCertificateError(ValueError):
    """A direct-Kimi run does not satisfy the immutable certificate contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as error:
        raise DirectKimiCertificateError("artifact_unreadable") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise DirectKimiCertificateError("artifact_changed")
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": _sha256(resolved)}


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.resolve(strict=True).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiCertificateError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise DirectKimiCertificateError(f"{label}_invalid")
    return value


def _validate_identity(run_dir: Path, *, role: str, expected_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
    except (OSError, ValueError) as error:
        raise DirectKimiCertificateError("eval_identity_invalid") from error
    identity = envelope["identity"]
    source = identity.get("source")
    execution = identity.get("execution")
    deployment = identity.get("deployment")
    task = identity.get("inputs", {}).get("task_file")
    if (
        identity.get("role") != role
        or identity.get("contract", {}).get("model") != EXPECTED_MODEL
        or not isinstance(source, dict)
        or source.get("sandbox_provider") != "sandoq"
        or not isinstance(execution, dict)
        or execution.get("cleanup_must_succeed") is not True
        or execution.get("runtime", {}).get("type") != "sandoq"
        or not isinstance(deployment, dict)
        or deployment.get("kind") != "direct_kimi"
        or not isinstance(task, dict)
        or task.get("count") != expected_count
    ):
        raise DirectKimiCertificateError("eval_identity_invalid")
    expected_concurrency = 2 if role == "kimi-direct-smoke" else 24
    environment = execution.get("sandoq_environment")
    if (
        any(
            execution.get(key) != expected_concurrency
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or not isinstance(environment, dict)
        or environment.get("environment") != "oci-runner"
        or environment.get("task_network") != "public"
        or environment.get("pool_size") != expected_concurrency
        or environment.get("pool_min_size") != 0
    ):
        raise DirectKimiCertificateError("execution_contract_invalid")
    manifest_record = deployment.get("worker_manifest")
    if not isinstance(manifest_record, dict) or set(manifest_record) != {"path", "sha256"}:
        raise DirectKimiCertificateError("worker_manifest_invalid")
    manifest_path = Path(str(manifest_record["path"]))
    if _sha256(manifest_path) != manifest_record["sha256"]:
        raise DirectKimiCertificateError("worker_manifest_invalid")
    try:
        manifest = validate_saved_manifest(manifest_path)
    except (OSError, ValueError) as error:
        raise DirectKimiCertificateError("worker_manifest_invalid") from error
    if (
        deployment.get("spec_sha256") != manifest["source_spec_sha256"]
        or deployment.get("endpoint_bundle_sha256") != manifest["endpoint_bundle_sha256"]
        or deployment.get("router")
        != {
            "policy": ROUTER_POLICY,
            "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
            "provider_concurrency": ROUTER_PROVIDER_CONCURRENCY,
            "request_timeout_seconds": ROUTER_REQUEST_TIMEOUT_SECONDS,
            "retries": ROUTER_RETRIES,
            "worker_count": EXPECTED_ENDPOINTS,
        }
    ):
        raise DirectKimiCertificateError("worker_generation_invalid")
    return envelope, manifest


def _validate_task_selection(identity: dict[str, Any], expected_task_file: Path, expected_sha256: str) -> list[str]:
    if SHA256_RE.fullmatch(expected_sha256) is None or _sha256(expected_task_file) != expected_sha256:
        raise DirectKimiCertificateError("task_selection_invalid")
    expected_slugs = _read_expected_slugs(expected_task_file)
    record = identity.get("inputs", {}).get("task_file", {})
    if record.get("sha256") != expected_sha256 or record.get("count") != len(expected_slugs):
        raise DirectKimiCertificateError("task_selection_invalid")
    return expected_slugs


def _validate_router_receipt(path: Path, manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    receipt = _read_json(path, label="router_receipt")
    if receipt != {
        "schema_version": 1,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        "worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": EXPECTED_ENDPOINTS,
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "request_timeout_seconds": ROUTER_REQUEST_TIMEOUT_SECONDS,
        "retries": ROUTER_RETRIES,
        "source_generation_revalidated": True,
    }:
        raise DirectKimiCertificateError("router_receipt_invalid")
    return receipt


def _validate_cleanup(path: Path, *, expected_count: int, expected_concurrency: int) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.resolve(strict=True).read_bytes()
        cleanup = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiCertificateError("pool_cleanup_invalid") from error
    count_keys = {
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
    expected_keys = {"schema_version", "kind", "state", *count_keys, *digest_keys}
    if (
        not isinstance(cleanup, dict)
        or set(cleanup) != expected_keys
        or cleanup.get("schema_version") != 1
        or cleanup.get("kind") != "sandoq-pool-cleanup"
        or cleanup.get("state") != "passed"
        or cleanup.get("failures") != 0
        or any(
            not isinstance(cleanup.get(key), int) or isinstance(cleanup.get(key), bool) or cleanup[key] < 0
            for key in count_keys
        )
        or any(SHA256_RE.fullmatch(str(cleanup.get(key, ""))) is None for key in digest_keys)
        or cleanup["recorded_outer_sessions"] != cleanup["verified_http_404"]
        or cleanup["recorded_outer_sessions"] != cleanup["outer_sessions_created"]
        or cleanup["recorded_outer_sessions"] != cleanup["outer_sessions_deleted"]
        or cleanup["recorded_outer_sessions"] < 1
        or cleanup["outer_session_high_water"] < expected_concurrency
        or cleanup["assignment_measured_high_water"] != expected_concurrency
        or cleanup["assignments_acquired"] < expected_count
        or cleanup["assignments_cleanup_verified"] != cleanup["assignments_acquired"]
        or cleanup["assignment_release_rows"] + cleanup["assignment_cancellation_rows"]
        != cleanup["assignments_acquired"]
    ):
        raise DirectKimiCertificateError("pool_cleanup_invalid")
    return cleanup, raw


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fchmod(handle.fileno(), 0o444)
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise DirectKimiCertificateError("certificate_already_exists") from error
    finally:
        temporary.unlink(missing_ok=True)


def _common_artifacts(run_dir: Path) -> dict[str, dict[str, str]]:
    return {
        name: _artifact(run_dir / relative)
        for name, relative in {
            "results": "results.jsonl",
            "eval_run_identity": "eval_run_identity.json",
            "eval_invocations": "eval_invocations.jsonl",
            "config": "config.toml",
            "inputs_manifest": "inputs/manifest.json",
            "provenance": "provenance.txt",
            "router_receipt": "direct_kimi_router_final.json",
            "cleanup_audit": "sandoq_cleanup_audit.json",
        }.items()
    }


def certify_smoke(
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    output: Path,
) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    with (run_dir / ".writer.lock").open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DirectKimiCertificateError("writer_active") from error
        envelope, manifest = _validate_identity(
            run_dir,
            role="kimi-direct-smoke",
            expected_count=SMOKE_TASK_COUNT,
        )
        identity = envelope["identity"]
        expected_slugs = _validate_task_selection(identity, expected_task_file, expected_task_file_sha256)
        if len(expected_slugs) != SMOKE_TASK_COUNT:
            raise DirectKimiCertificateError("task_selection_invalid")
        results = run_dir / "results.jsonl"
        before = _sha256(results)
        summary, failed = _summarize_traces(
            _iter_traces(results),
            expected_slugs=expected_slugs,
            expected_count=SMOKE_TASK_COUNT,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            aggregate_only=True,
            model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            require_exact_provider_json=True,
            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
        )
        if failed or summary.get("model_io_turns", 0) < SMOKE_TASK_COUNT or summary.get("sampled_tokens", 0) < 1:
            raise DirectKimiCertificateError("trace_audit_failed")
        if _sha256(results) != before:
            raise DirectKimiCertificateError("results_changed")
        manifest_record = identity["deployment"]["worker_manifest"]
        _validate_router_receipt(
            run_dir / "direct_kimi_router_final.json",
            manifest,
            manifest_record["sha256"],
        )
        cleanup, cleanup_raw = _validate_cleanup(
            run_dir / "sandoq_cleanup_audit.json",
            expected_count=SMOKE_TASK_COUNT,
            expected_concurrency=SMOKE_TASK_COUNT,
        )
        artifacts = _common_artifacts(run_dir)
        certificate = {
            "schema_version": 1,
            "kind": "direct-kimi-sandoq-smoke",
            "state": "passed",
            "model": EXPECTED_MODEL,
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": before,
            "task_file_sha256": expected_task_file_sha256,
            "worker_manifest_sha256": manifest_record["sha256"],
            "source_spec_sha256": manifest["source_spec_sha256"],
            "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
            "worker_count": EXPECTED_ENDPOINTS,
            "trace_count": summary["traces"],
            "model_io_turns": summary["model_io_turns"],
            "sampled_tokens": summary["sampled_tokens"],
            "pool_cleanup": {
                "audit_sha256": hashlib.sha256(cleanup_raw).hexdigest(),
                "assignment_measured_high_water": cleanup["assignment_measured_high_water"],
                "outer_session_high_water": cleanup["outer_session_high_water"],
                "failures": 0,
            },
            "artifacts": artifacts,
        }
        _write_once(output, certificate)
        return certificate


def certify_tb4(
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    smoke_checkpoint: Path,
    smoke_checkpoint_sha256: str,
    output: Path,
) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    with (run_dir / ".writer.lock").open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DirectKimiCertificateError("writer_active") from error
        envelope, manifest = _validate_identity(
            run_dir,
            role="kimi-direct-tb4",
            expected_count=EXPECTED_TASK_COUNT,
        )
        identity = envelope["identity"]
        expected_slugs = _validate_task_selection(identity, expected_task_file, expected_task_file_sha256)
        if len(expected_slugs) != EXPECTED_TASK_COUNT:
            raise DirectKimiCertificateError("task_selection_invalid")
        smoke_raw = smoke_checkpoint.resolve(strict=True).read_bytes()
        try:
            smoke = json.loads(smoke_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DirectKimiCertificateError("smoke_checkpoint_invalid") from error
        manifest_record = identity["deployment"]["worker_manifest"]
        if (
            SHA256_RE.fullmatch(smoke_checkpoint_sha256) is None
            or hashlib.sha256(smoke_raw).hexdigest() != smoke_checkpoint_sha256
            or identity["deployment"]["smoke_checkpoint"]
            != {"path": str(smoke_checkpoint.resolve()), "sha256": smoke_checkpoint_sha256}
            or not isinstance(smoke, dict)
            or smoke.get("schema_version") != 1
            or smoke.get("kind") != "direct-kimi-sandoq-smoke"
            or smoke.get("state") != "passed"
            or smoke.get("model") != EXPECTED_MODEL
            or SHA256_RE.fullmatch(str(smoke.get("worker_manifest_sha256", ""))) is None
            or smoke.get("source_spec_sha256") != manifest["source_spec_sha256"]
            or smoke.get("endpoint_bundle_sha256") != manifest["endpoint_bundle_sha256"]
        ):
            raise DirectKimiCertificateError("smoke_checkpoint_invalid")
        results = run_dir / "results.jsonl"
        before = _sha256(results)
        try:
            summary, failed = audit_results(
                results,
                dataset_dir=Path(identity["dataset"]["path"]),
                task_file=expected_task_file,
                min_supported_pass_rate=TB4_MIN_SUPPORTED_PASS_RATE,
                max_supported_pass_rate=TB4_MAX_SUPPORTED_PASS_RATE,
                max_sequence_tokens=MAX_SEQUENCE_TOKENS,
            )
        except Exception as error:
            raise DirectKimiCertificateError("tb4_trace_audit_failed") from error
        if failed:
            raise DirectKimiCertificateError("tb4_trace_audit_failed")
        if _sha256(results) != before:
            raise DirectKimiCertificateError("results_changed")
        _validate_router_receipt(
            run_dir / "direct_kimi_router_final.json",
            manifest,
            manifest_record["sha256"],
        )
        cleanup, cleanup_raw = _validate_cleanup(
            run_dir / "sandoq_cleanup_audit.json",
            expected_count=EXPECTED_TASK_COUNT,
            expected_concurrency=24,
        )
        artifacts = _common_artifacts(run_dir)
        artifacts["smoke_checkpoint"] = _artifact(smoke_checkpoint)
        unsigned = {
            "schema_version": 1,
            "kind": "direct-kimi-sandoq-tb4",
            "state": "passed",
            "model": EXPECTED_MODEL,
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": before,
            "task_file_sha256": expected_task_file_sha256,
            "worker_manifest_sha256": manifest_record["sha256"],
            "source_spec_sha256": manifest["source_spec_sha256"],
            "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
            "worker_count": EXPECTED_ENDPOINTS,
            "counts": {
                "observed_traces": summary["observed_traces"],
                "supported_tasks": summary["supported_tasks"],
                "cpu_unsupported_tasks": len(summary["observed_unsupported_tasks"]),
                "supported_passes": summary["supported_passes"],
                "trace_failures": summary["trace_failures"],
                "global_problems": len(summary["global_problems"]),
            },
            "scores": {
                "supported_pass_rate": summary["supported_pass_rate"],
                "all_task_pass_rate": summary["all_task_pass_rate"],
            },
            "policy": {
                "expected_tasks": EXPECTED_TASK_COUNT,
                "expected_supported_tasks": EXPECTED_SUPPORTED_TASK_COUNT,
                "rollouts_per_task": 1,
                "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
                "min_supported_pass_rate": TB4_MIN_SUPPORTED_PASS_RATE,
                "max_supported_pass_rate": TB4_MAX_SUPPORTED_PASS_RATE,
                "router_policy": ROUTER_POLICY,
                "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
                "request_timeout_seconds": ROUTER_REQUEST_TIMEOUT_SECONDS,
                "retries": ROUTER_RETRIES,
            },
            "pool_cleanup": {
                "audit_sha256": hashlib.sha256(cleanup_raw).hexdigest(),
                "assignment_measured_high_water": cleanup["assignment_measured_high_water"],
                "outer_session_high_water": cleanup["outer_session_high_water"],
                "failures": 0,
            },
            "artifacts": artifacts,
        }
        certificate = {
            **unsigned,
            "tb4_certificate_sha256": hashlib.sha256(canonical_json(unsigned)).hexdigest(),
        }
        _write_once(output, certificate)
        return certificate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("smoke", "tb4"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--smoke-checkpoint", type=Path)
    parser.add_argument("--smoke-checkpoint-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "smoke":
            if args.smoke_checkpoint is not None or args.smoke_checkpoint_sha256 is not None:
                raise DirectKimiCertificateError("unexpected_smoke_checkpoint")
            certificate = certify_smoke(
                args.run_dir,
                args.expected_task_file,
                args.expected_task_file_sha256,
                args.output,
            )
        else:
            if args.smoke_checkpoint is None or args.smoke_checkpoint_sha256 is None:
                raise DirectKimiCertificateError("smoke_checkpoint_required")
            certificate = certify_tb4(
                args.run_dir,
                args.expected_task_file,
                args.expected_task_file_sha256,
                args.smoke_checkpoint,
                args.smoke_checkpoint_sha256,
                args.output,
            )
    except (OSError, ValueError):
        print("direct_kimi_certificate_failed", file=__import__("sys").stderr)
        raise SystemExit(2) from None
    print(
        json.dumps(
            {
                "certificate_sha256": _sha256(args.output),
                "kind": certificate["kind"],
                "state": "passed",
                "scores": certificate.get("scores"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
