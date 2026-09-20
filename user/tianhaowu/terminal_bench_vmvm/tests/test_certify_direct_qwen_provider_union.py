from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import certify_direct_qwen_provider_union as union_certificate
import certify_direct_qwen_sandoq_partition as sandoq_certificate
import pytest
import sft_run_identity
from direct_qwen_union_contract import HOST_HARNESS_CONTRACT, canonical_json, sha256_bytes
from materialize_qwen_provider_union import receipt_value


def _write(path: Path, value: object) -> str:
    body = canonical_json(value)
    path.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def _write_private(path: Path, value: object) -> str:
    digest = _write(path, value)
    path.chmod(0o600)
    return digest


def _shared() -> dict:
    return {
        "contract": {
            "model": "Qwen3.8-2.4T-A95B",
            "pass_at_1": True,
            "num_rollouts": 1,
            "reasoning_effort": "high",
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
            "harness": dict(HOST_HARNESS_CONTRACT),
        },
        "dataset": {"kind": "git_revision", "revision": "a" * 40},
        "deployment": {
            "endpoint_bundle_sha256": "2" * 64,
            "router": {
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "request_timeout_seconds": 7_500,
                "queue_timeout_seconds": 7_200,
                "retries": 0,
            },
            "spec_sha256": "3" * 64,
            "worker_count": 24,
            "worker_generation_sha256": "4" * 64,
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
        "deployment_namespace": receipt["deployment_namespace"],
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
            "pool_drain_sha256": "10" * 32,
            "pool_event_log_sha256": "20" * 32,
            "pool_wal_sha256": "30" * 32,
            "raw_audit_sha256": "40" * 32,
        },
        "auth_rotation": {
            "audit_sha256": "5" * 64,
            "atomic_same_path": True,
            "batch_heartbeats": 100,
            "fail_closed_before_expiry_seconds": 1800,
            "maximum_observed_refresh_gap_seconds": 14_000,
            "maximum_observed_heartbeat_gap_seconds": 60,
            "maximum_refresh_interval_seconds": 14_400,
            "minimum_observed_expiry_margin_seconds": 3600,
            "run_duration_seconds": 190_800,
            "successful_replacements": 13,
        },
        "materialization": materialization,
        "predecessor": {"sha256": "6" * 64, "stage_count": 64},
        "shared_contract": copy.deepcopy(shared),
        "shared_contract_sha256": shared_sha,
        "provider_source": {
            "prime_rl_commit": common_source["prime_rl_commit"],
            "verifiers_commit": common_source["verifiers_commit"],
            "renderers_commit": common_source["renderers_commit"],
            "sandoq_provider_commit": "a" * 40,
            "sandoq_provider_tree": "b" * 40,
            "sandoq_client_version": "pinned",
            "sandoq_host_harness_sha256": "c" * 64,
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
        "runtime_cleanup": {
            "state": "passed",
            "runtime_instances": 2,
            "cleanup_passes": 2,
            "agent_runtime_instances": 1,
            "verifier_runtime_instances": 1,
            "verifier_mode": "separate",
            "compose_runtime_instances": 1,
            "local_cleanup_failures": 0,
            "release_on_exit_completed": 2,
            "remote_deletion_verified": False,
        },
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
    assert result["cleanup"]["auth_rotation"]["successful_replacements"] == 13
    assert result["cleanup"]["vmvm"]["remote_deletion_verified"] is False
    assert "materialization" not in result
    assert result["execution_contract"] == {
        "contract": sandoq["shared_contract"]["contract"],
        "deployment": sandoq["shared_contract"]["deployment"],
    }
    assert "shared_contract" not in result
    assert "shared_contract_sha256" not in result


def test_public_union_recursively_excludes_private_member_commitments(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()
    result = _certify(tmp_path, sandoq, vmvm)
    encoded = json.dumps(result, sort_keys=True)
    private_values = {
        sha256_bytes(canonical_json(sandoq)),
        sha256_bytes(canonical_json(vmvm)),
        sandoq["eval_run_identity_sha256"],
        vmvm["eval_run_identity_sha256"],
        sandoq["results_sha256"],
        vmvm["results_sha256"],
        sandoq["materialization"]["sha256"],
        sandoq["shared_contract_sha256"],
        sandoq["materialization"]["source"]["sha256"],
        sandoq["materialization"]["dataset"]["revision"],
        sandoq["materialization"]["dataset"]["tree"],
        sandoq["pool_cleanup"]["audit_sha256"],
        sandoq["auth_rotation"]["audit_sha256"],
        *sandoq["sanitized_cleanup_source_hashes"].values(),
    }
    forbidden_keys = {
        "certificate",
        "config_sha256",
        "eval_run_identity_sha256",
        "predecessor",
        "provider_certificates",
        "provider_exports",
        "provider_partition_sha256",
        "results_sha256",
        "task_file_sha256",
        "worker_manifest_sha256",
        "materialization",
        "sanitized_cleanup_source_hashes",
        "sanitized_cleanup",
        "shared_contract",
        "shared_contract_sha256",
        "task_id",
        "task_ids",
        "train_task_sha256",
        "validation_task_sha256",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            assert "path" not in value
            assert all(not key.endswith("_path") or key == "atomic_same_path" for key in value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)
    assert all(private not in encoded for private in private_values)


def test_private_provider_union_flows_into_sft_identity(tmp_path: Path) -> None:
    sandoq, vmvm = _certificates()
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    cleanup = run_dir / sft_run_identity.SANDOQ_CLEANUP_AUDIT_FILENAME
    rotation = run_dir / sft_run_identity.SANDOQ_AUTH_ROTATION_AUDIT_FILENAME
    cleanup.write_bytes(b"{}\n")
    rotation.write_bytes(b"{}\n")
    cleanup.chmod(0o600)
    rotation.chmod(0o600)
    sandoq["pool_cleanup"]["audit_sha256"] = hashlib.sha256(cleanup.read_bytes()).hexdigest()
    sandoq["auth_rotation"]["audit_sha256"] = hashlib.sha256(rotation.read_bytes()).hexdigest()
    sandoq_path = run_dir / sft_run_identity.SANDOQ_PARTITION_CERTIFICATE_FILENAME
    vmvm_path = run_dir / sft_run_identity.VMVM_COMPOSE_CERTIFICATE_FILENAME
    sandoq_sha = _write_private(sandoq_path, sandoq)
    vmvm_sha = _write_private(vmvm_path, vmvm)
    union = union_certificate.certify_union(
        sandoq_certificate=sandoq_path,
        sandoq_certificate_sha256=sandoq_sha,
        vmvm_certificate=vmvm_path,
        vmvm_certificate_sha256=vmvm_sha,
    )
    _write_private(run_dir / sft_run_identity.PROVIDER_UNION_CERTIFICATE_FILENAME, union)

    provenance, artifacts, results_sha256 = sft_run_identity._mixed_provider_union(
        run_dir,
        provider="sandoq",
        eval_run_identity_sha256=sandoq["eval_run_identity_sha256"],
        task_count=2499,
    )

    assert provenance["sanitized_cleanup"]["vmvm_runtime_cleanup"] == vmvm["runtime_cleanup"]
    assert provenance["materialization"] == sandoq["materialization"]
    assert results_sha256 == sandoq["results_sha256"]
    assert set(artifacts) == set(sft_run_identity.MIXED_PROVIDER_EXPORT_ARTIFACT_FILENAMES)


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


def test_sandoq_cleanup_accepts_sessions_retired_before_final_drain(tmp_path: Path) -> None:
    cleanup = {
        "schema_version": 1,
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        "recorded_outer_sessions": 430,
        "verified_http_404": 430,
        "already_absent": 430,
        "deleted_and_verified": 0,
        "assignments_acquired": 2507,
        "assignment_release_rows": 2500,
        "assignment_cancellation_rows": 7,
        "cleanup_gateway_retry_count": 2,
        "assignments_cleanup_verified": 2507,
        "assignment_event_order_high_water": 65,
        "assignment_measured_high_water": 64,
        "outer_sessions_created": 430,
        "outer_sessions_deleted": 430,
        "outer_session_high_water": 64,
        "pool_drain_deleted": 61,
        "gateway_close_warnings": 0,
        "recovered_poisoned_assignments": 3,
        "failures": 0,
        "raw_audit_sha256": "1" * 64,
        "pool_event_log_sha256": "2" * 64,
        "pool_wal_sha256": "3" * 64,
        "pool_drain_sha256": "4" * 64,
    }
    path = tmp_path / "cleanup.json"
    path.write_text(json.dumps(cleanup))

    public, source_hashes = sandoq_certificate.validate_cleanup(path)

    assert public["recorded_outer_sessions"] == 430
    assert public["typed_http_404"] == 430
    assert public["zero_drop"] is True
    assert source_hashes["pool_drain_sha256"] == "4" * 64


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
        "maximum_observed_heartbeat_gap_seconds": 60,
        "minimum_observed_expiry_margin_seconds": 3600,
        "batch_heartbeats": 100,
        "liveness_failures": 0,
        "expired_observations": 0,
        "credential_payload_records": 0,
        "raw_rotator_log_sha256": "1" * 64,
        "raw_batch_guard_log_sha256": "2" * 64,
        "eval_run_identity_sha256": "a" * 64,
        "results_sha256": "b" * 64,
    }
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(audit))

    with pytest.raises(
        sandoq_certificate.SandoqPartitionCertificateError,
        match="^auth_rotation_audit_invalid$",
    ):
        sandoq_certificate.validate_auth_rotation(
            path,
            expected_eval_run_identity_sha256="a" * 64,
            expected_results_sha256="b" * 64,
        )
