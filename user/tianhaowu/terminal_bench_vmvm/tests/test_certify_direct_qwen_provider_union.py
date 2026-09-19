from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path

import certify_direct_qwen_provider_union as union_certificate
import certify_direct_qwen_sandoq_partition as sandoq_certificate
import pytest
from direct_qwen_union_contract import canonical_json, sha256_bytes
from materialize_qwen_provider_union import receipt_value


def _write(path: Path, value: object) -> str:
    body = canonical_json(value)
    path.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def _shared() -> dict:
    return {
        "contract": {
            "model": "Qwen3.8-2.4T-A95B",
            "pass_at_1": True,
            "num_rollouts": 1,
            "reasoning_effort": "max",
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
            "context_tokens": {
                "max_input_tokens": 262_144,
                "max_output_tokens": 262_144,
                "max_total_tokens": 262_144,
            },
            "sampling_max_tokens": 32_768,
            "capture_model_io": True,
            "outbound_body_denylist": ["logprobs"],
            "retain_traces": False,
        },
        "dataset": {"kind": "git_revision", "revision": "a" * 40},
        "deployment": {
            "base_url_sha256": "1" * 64,
            "endpoint_bundle_sha256": "2" * 64,
            "router": {
                "policy": "consistent_hash",
                "provider_concurrency": 32,
                "request_id_headers": ["x-session-id"],
            },
            "spec_sha256": "3" * 64,
            "worker_count": 24,
            "worker_manifest_sha256": "4" * 64,
        },
        "source": {
            "prime_rl_commit": "5" * 40,
            "prime_rl_tree_sha256": "6" * 64,
            "verifiers_commit": "7" * 40,
            "verifiers_tree_sha256": "8" * 64,
            "renderers_commit": "9" * 40,
            "renderers_tree_sha256": "a" * 64,
        },
    }


def _materialization() -> dict:
    receipt = receipt_value()
    return {
        "sha256": "b" * 64,
        "source": receipt["source"],
        "dataset": receipt["dataset"],
        "templates": receipt["templates"],
        "partition": receipt["partition"],
        "derivation_sha256": receipt["derivation_sha256"],
    }


def _trace(count: int) -> dict:
    return {
        "traces": count,
        "tasks": count,
        "sampled_tokens": count,
        "model_io_turns": count,
        "provider_reported_zero_reasoning_tool_turns": 0,
        "provider_explicit_empty_reasoning_tool_turns": 0,
    }


def _certificates() -> tuple[dict, dict]:
    shared = _shared()
    shared_sha = sha256_bytes(canonical_json(shared))
    materialization = _materialization()
    common_source = shared["source"]
    sandoq = {
        "schema_version": 1,
        "kind": "direct-qwen-sandoq-partition",
        "state": "passed",
        "sandbox_provider": "sandoq",
        "task_count": 2499,
        "selection": "canonical-non-compose",
        "eval_run_identity_sha256": "c" * 64,
        "results_sha256": "d" * 64,
        "worker_manifest_sha256": "4" * 64,
        "worker_count": 24,
        "trace_audit": _trace(2499),
        "pool_cleanup": {
            "audit_sha256": "e" * 64,
            "assignment_attempts": 2501,
            "assignment_cancellations": 2,
            "assignment_measured_high_water": 64,
            "extra_assignment_attempts": 2,
            "gateway_close_warnings": 0,
            "outer_session_high_water": 64,
            "recorded_outer_sessions": 64,
            "recovered_poisoned_assignments": 1,
            "typed_http_404": 64,
            "zero_drop": True,
            "failures": 0,
        },
        "sanitized_cleanup_source_hashes": {
            "pool_drain_sha256": "1" * 64,
            "pool_event_log_sha256": "2" * 64,
            "pool_wal_sha256": "3" * 64,
            "raw_audit_sha256": "4" * 64,
        },
        "auth_rotation": {
            "audit_sha256": "5" * 64,
            "atomic_same_path": True,
            "batch_heartbeats": 100,
            "fail_closed_before_expiry_seconds": 1800,
            "maximum_observed_refresh_gap_seconds": 14_000,
            "maximum_refresh_interval_seconds": 14_400,
            "minimum_observed_expiry_margin_seconds": 3600,
            "run_duration_seconds": 190_800,
            "successful_replacements": 13,
        },
        "materialization": materialization,
        "predecessor": {"sha256": "6" * 64, "stage_count": 24},
        "shared_contract": copy.deepcopy(shared),
        "shared_contract_sha256": shared_sha,
        "provider_source": {
            "prime_rl_commit": common_source["prime_rl_commit"],
            "verifiers_commit": common_source["verifiers_commit"],
            "renderers_commit": common_source["renderers_commit"],
            "sandoq_provider_commit": "a" * 40,
            "sandoq_provider_tree": "b" * 40,
            "sandoq_client_version": "pinned",
            "sandoq_site_sha256": "7" * 64,
            "derived_image_manifest_sha256": "8" * 64,
            "direct_spec_sha256": "3" * 64,
            "direct_endpoint_bundle_sha256": "2" * 64,
        },
    }
    vmvm = {
        "schema_version": 1,
        "kind": "direct-qwen-vmvm-compose-partition",
        "state": "passed",
        "sandbox_provider": "vmvm",
        "task_count": 1,
        "selection": "canonical-compose",
        "eval_run_identity_sha256": "f" * 64,
        "results_sha256": "0" * 64,
        "worker_manifest_sha256": "4" * 64,
        "worker_count": 24,
        "trace_audit": _trace(1),
        "compose_proof": {
            "compose_count": 1,
            "network_policy": "both-phases-no-network",
            "runtime": "vmvm",
            "vmvm_tb_v2_sha256": "9" * 64,
        },
        "runtime_cleanup": {"error_traces": 0, "finalized_traces": 1, "state": "passed"},
        "materialization": materialization,
        "shared_contract": shared,
        "shared_contract_sha256": shared_sha,
        "provider_source": {
            "prime_rl_commit": common_source["prime_rl_commit"],
            "verifiers_commit": common_source["verifiers_commit"],
            "renderers_commit": common_source["renderers_commit"],
            "vmvm_tb_v2_sha256": "9" * 64,
            "direct_spec_sha256": "3" * 64,
            "direct_endpoint_bundle_sha256": "2" * 64,
        },
    }
    return sandoq, vmvm


def _certify(tmp_path: Path, sandoq: dict, vmvm: dict) -> dict:
    sandoq_path = tmp_path / "sandoq.json"
    vmvm_path = tmp_path / "vmvm.json"
    sandoq_sha = _write(sandoq_path, sandoq)
    vmvm_sha = _write(vmvm_path, vmvm)
    return union_certificate.certify_union(
        sandoq_certificate=sandoq_path,
        sandoq_certificate_sha256=sandoq_sha,
        vmvm_certificate=vmvm_path,
        vmvm_certificate_sha256=vmvm_sha,
    )


def test_union_binds_exact_private_partition_and_cleanup(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()

    result = _certify(tmp_path, sandoq, vmvm)

    assert result["task_count"] == 2500
    assert result["partition"] == {
        "sandoq": 2499,
        "vmvm": 1,
        "total": 2500,
        "compose_count": 1,
        "disjoint": True,
        "exhaustive": True,
        "member_commitments_public": False,
    }
    assert result["trace_audit"]["max_sequence_tokens"] == 262_144
    assert result["sanitized_cleanup"]["auth_rotation_audit_sha256"] == "5" * 64


def test_union_rejects_cross_provider_contract_drift(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()
    vmvm["shared_contract"]["deployment"]["spec_sha256"] = "f" * 64
    vmvm["shared_contract_sha256"] = sha256_bytes(canonical_json(vmvm["shared_contract"]))
    vmvm["provider_source"]["direct_spec_sha256"] = "f" * 64

    with pytest.raises(union_certificate.ProviderUnionCertificateError, match="^provider_union_mismatch$"):
        _certify(tmp_path, sandoq, vmvm)


def test_union_rejects_boolean_count(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()
    sandoq["trace_audit"]["tasks"] = True

    with pytest.raises(union_certificate.ProviderUnionCertificateError, match="^provider_trace_audit_invalid$"):
        _certify(tmp_path, sandoq, vmvm)


def test_union_rejects_missing_auth_rotation(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()
    sandoq["auth_rotation"]["maximum_observed_refresh_gap_seconds"] = 14_401

    with pytest.raises(union_certificate.ProviderUnionCertificateError, match="^auth_rotation_proof_invalid$"):
        _certify(tmp_path, sandoq, vmvm)


def test_union_rejects_compose_partition_count_tamper(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()
    vmvm["materialization"] = dict(vmvm["materialization"])
    vmvm["materialization"]["partition"] = dict(vmvm["materialization"]["partition"])
    vmvm["materialization"]["partition"]["vmvm_count"] = 2

    with pytest.raises(union_certificate.ProviderUnionCertificateError, match="^materialization_proof_invalid$"):
        _certify(tmp_path, sandoq, vmvm)


def test_sandoq_cleanup_requires_typed_404_and_zero_drop(tmp_path: Path) -> None:
    cleanup = {
        "schema_version": 1,
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        "recorded_outer_sessions": 64,
        "verified_http_404": 63,
        "already_absent": 64,
        "deleted_and_verified": 0,
        "assignments_acquired": 2499,
        "assignment_release_rows": 2499,
        "assignment_cancellation_rows": 0,
        "cleanup_gateway_retry_count": 0,
        "assignments_cleanup_verified": 2499,
        "assignment_event_order_high_water": 64,
        "assignment_measured_high_water": 64,
        "outer_sessions_created": 64,
        "outer_sessions_deleted": 64,
        "outer_session_high_water": 64,
        "pool_drain_deleted": 64,
        "gateway_close_warnings": 0,
        "recovered_poisoned_assignments": 0,
        "failures": 0,
        "raw_audit_sha256": "1" * 64,
        "pool_event_log_sha256": "2" * 64,
        "pool_wal_sha256": "3" * 64,
        "pool_drain_sha256": "4" * 64,
    }
    path = tmp_path / "cleanup.json"
    path.write_text(json.dumps(cleanup))

    with pytest.raises(sandoq_certificate.SandoqPartitionCertificateError, match="^sandoq_cleanup_invalid$"):
        sandoq_certificate.validate_cleanup(path)


def test_auth_rotation_rejects_underprovisioned_long_run(tmp_path: Path) -> None:
    audit = {
        "schema_version": 1,
        "kind": "sandoq-auth-rotation",
        "state": "passed",
        "refresh_source": "login-side-service",
        "token_path_policy": "private-mode-0600-atomic-replace",
        "atomic_same_path": True,
        "monitor_started_before_rollout": True,
        "monitor_stopped_after_rollout": True,
        "maximum_refresh_interval_seconds": 14_400,
        "fail_closed_before_expiry_seconds": 1800,
        "run_duration_seconds": 190_800,
        "successful_replacements": 12,
        "maximum_observed_refresh_gap_seconds": 14_000,
        "minimum_observed_expiry_margin_seconds": 3600,
        "batch_heartbeats": 100,
        "liveness_failures": 0,
        "expired_observations": 0,
        "credential_payload_records": 0,
        "raw_rotator_log_sha256": "1" * 64,
        "raw_batch_guard_log_sha256": "2" * 64,
    }
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(audit))

    with pytest.raises(
        sandoq_certificate.SandoqPartitionCertificateError,
        match="^auth_rotation_audit_invalid$",
    ):
        sandoq_certificate.validate_auth_rotation(path)
