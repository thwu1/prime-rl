from __future__ import annotations

import hashlib
import json
from pathlib import Path

import direct_kimi_workers
import pytest
from certify_direct_kimi import (
    CAPACITY_LIMITED_SMOKE_SCOPE,
    DirectKimiCertificateError,
    _capacity_limited_smoke_scope,
    _expected_sandoq_pool_size,
    _native_miniswe_smoke_execution,
    _native_smoke_scoring,
    _native_tool_execution,
    _validate_cleanup,
    _validate_router_receipt,
)
from eval_run_identity import (
    KIMI_FIRECRACKER_RESOURCE_RECEIPT_SHA256,
    KIMI_FIRECRACKER_TUNNEL_PROFILE_SHA256,
    KIMI_FIRECRACKER_TUNNEL_RECEIPT_SHA256,
    KIMI_MINISWE_COMPATIBILITY_SHA256,
    KIMI_NATIVE_MINISWE_SMOKE_SELECTOR_SHA256,
    _valid_w2_smoke_checkpoint,
)


def _identity(config: Path) -> dict:
    return {
        "config": {
            "resolved": {
                "path": str(config),
                "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            }
        }
    }


def test_capacity_limited_smoke_scope_requires_declared_resources(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[taskset]\nresource_multiplier = 1.0\n")

    assert _capacity_limited_smoke_scope(_identity(config)) == CAPACITY_LIMITED_SMOKE_SCOPE


def test_capacity_limited_smoke_scope_rejects_scaled_resources(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[taskset]\nresource_multiplier = 3.0\n")

    with pytest.raises(DirectKimiCertificateError, match="^smoke_capacity_scope_invalid$"):
        _capacity_limited_smoke_scope(_identity(config))


def test_capacity_limited_smoke_scope_accepts_proven_mobius_multiplier(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[taskset]\nresource_multiplier = 2.0\n")

    scope = _capacity_limited_smoke_scope(_identity(config))

    assert scope["resource_multiplier"] == 2.0


def test_native_miniswe_smoke_execution_binds_full_tunnel_evidence() -> None:
    identity = {
        "contract": {"harness": {"id": "mini-swe-agent", "version": "2.4.6", "step_limit": 3}},
        "execution": {
            "runtime": {
                "expected_environment": "oci-runner-firecracker",
                "host_tunnel": "sandoq",
                "buffered_chat_completions": True,
            },
            "sandoq_environment": {
                "environment": "oci-runner-firecracker",
                "provider_task_network": "host",
                "provider_profile_sha256": KIMI_FIRECRACKER_TUNNEL_PROFILE_SHA256,
                "runtime_tunnel_receipt_sha256": KIMI_FIRECRACKER_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": KIMI_FIRECRACKER_RESOURCE_RECEIPT_SHA256,
                "miniswe_compatibility_receipt_sha256": KIMI_MINISWE_COMPATIBILITY_SHA256,
            },
        },
    }

    observed = _native_miniswe_smoke_execution(identity)

    assert observed is not None
    assert observed["harness"] == {"id": "mini-swe-agent", "version": "2.4.6", "step_limit": 3}
    assert observed["provider_profile_sha256"] == KIMI_FIRECRACKER_TUNNEL_PROFILE_SHA256


def _w2_smoke_payload() -> tuple[dict, dict]:
    manifest = {"source_spec_sha256": "1" * 64, "endpoint_bundle_sha256": "2" * 64}
    payload = {
        "full_tb4_ready": False,
        "source": {"prime_rl_commit": "4" * 40, "prime_rl_tree_sha256": "5" * 64},
        "model_retry_stop_after_attempt": 1,
        "qualification_scope": "capacity-limited-smoke-only",
        "task_file_sha256": KIMI_NATIVE_MINISWE_SMOKE_SELECTOR_SHA256,
        "source_spec_sha256": manifest["source_spec_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "worker_count": 24,
        "trace_count": 1,
        "model_io_turns": 3,
        "sampled_tokens": 128,
        "capacity_scope": {
            "kind": "full-firecracker-minimum-resource-qualified",
            "reasoning_effort": "max",
            "resource_multiplier": 1.0,
            "minimum_cpu_cores": 2,
            "minimum_memory_gib": 4,
            "minimum_disk_gib": 10,
            "full_tb4_ready": False,
        },
        "execution": {
            "harness": {"id": "mini-swe-agent", "version": "2.4.6", "step_limit": 3},
            "provider_environment": "oci-runner-firecracker",
            "provider_task_network": "host",
            "host_tunnel": "sandoq",
            "provider_profile_sha256": KIMI_FIRECRACKER_TUNNEL_PROFILE_SHA256,
            "runtime_tunnel_receipt_sha256": KIMI_FIRECRACKER_TUNNEL_RECEIPT_SHA256,
            "runtime_resource_receipt_sha256": KIMI_FIRECRACKER_RESOURCE_RECEIPT_SHA256,
            "miniswe_compatibility_receipt_sha256": KIMI_MINISWE_COMPATIBILITY_SHA256,
        },
        "scoring": {"quality_gate": False, "reward_key": "solved", "score": 0.0, "scored": True},
        "tool_execution": {
            "tool_observations": 2,
            "successful_tool_exits": 2,
            "nonzero_tool_exits": 0,
            "missing_tool_exits": 0,
            "traces_with_tool_exit_evidence": 1,
        },
        "pool_cleanup": {
            "audit_sha256": "3" * 64,
            "assignment_measured_high_water": 1,
            "outer_session_high_water": 1,
            "failures": 0,
        },
    }
    return payload, manifest


def test_w2_smoke_composition_accepts_full_firecracker_three_step_smoke() -> None:
    payload, manifest = _w2_smoke_payload()

    assert _valid_w2_smoke_checkpoint(
        payload,
        manifest,
        expected_revision="4" * 40,
        expected_tree_sha256="5" * 64,
    )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    (
        (None, "full_tb4_ready", True),
        (None, "worker_count", 23),
        (None, "model_retry_stop_after_attempt", 10),
        ("source", "prime_rl_commit", "6" * 40),
        ("execution", "provider_environment", "oci-runner-firecracker-small"),
        ("tool_execution", "successful_tool_exits", 0),
    ),
)
def test_w2_smoke_composition_rejects_weakened_evidence(
    section: str | None,
    key: str,
    value: object,
) -> None:
    payload, manifest = _w2_smoke_payload()
    target = payload if section is None else payload[section]
    target[key] = value

    assert not _valid_w2_smoke_checkpoint(
        payload,
        manifest,
        expected_revision="4" * 40,
        expected_tree_sha256="5" * 64,
    )


@pytest.mark.parametrize(("rollout_concurrency", "pool_size"), [(1, 2), (23, 46), (24, 48), (64, 64)])
def test_sandoq_pool_reserves_separate_verifier_capacity(rollout_concurrency: int, pool_size: int) -> None:
    assert _expected_sandoq_pool_size(rollout_concurrency) == pool_size


@pytest.mark.parametrize("rollout_concurrency", [True, 0, 65, 1.5])
def test_sandoq_pool_rejects_invalid_rollout_concurrency(rollout_concurrency: object) -> None:
    with pytest.raises(DirectKimiCertificateError, match="^execution_contract_invalid$"):
        _expected_sandoq_pool_size(rollout_concurrency)  # type: ignore[arg-type]


def test_native_miniswe_smoke_requires_numeric_tool_exit_evidence() -> None:
    trace = {
        "nodes": [
            {"message": {"role": "tool", "content": json.dumps({"returncode": 1})}},
            {"message": {"role": "tool", "content": json.dumps({"returncode": 0})}},
        ]
    }

    assert _native_tool_execution([trace]) == {
        "tool_observations": 2,
        "successful_tool_exits": 1,
        "nonzero_tool_exits": 1,
        "missing_tool_exits": 0,
        "traces_with_tool_exit_evidence": 1,
    }
    with pytest.raises(DirectKimiCertificateError, match="native_smoke_tool_exit_invalid"):
        _native_tool_execution([{"nodes": [{"message": {"role": "tool", "content": "plain text"}}]}])


@pytest.mark.parametrize("score", [0, 1, 0.0, 1.0])
def test_native_smoke_scoring_accepts_completed_binary_score_without_quality_gate(score: float) -> None:
    assert _native_smoke_scoring([{"rewards": {"solved": score}}]) == {
        "reward_key": "solved",
        "score": float(score),
        "scored": True,
        "quality_gate": False,
    }


@pytest.mark.parametrize(
    "trace",
    [
        {},
        {"rewards": {}},
        {"rewards": {"solved": True}},
        {"rewards": {"solved": 0.5}},
        {"rewards": {"solved": 0, "other": 0}},
    ],
)
def test_native_smoke_scoring_rejects_missing_or_nonbinary_score(trace: dict) -> None:
    with pytest.raises(DirectKimiCertificateError, match="^native_smoke_scoring_missing$"):
        _native_smoke_scoring([trace])


def _cleanup() -> dict:
    counts = {
        "recorded_outer_sessions": 2,
        "verified_http_404": 2,
        "already_absent": 2,
        "deleted_and_verified": 0,
        "assignments_acquired": 2,
        "assignment_release_rows": 2,
        "assignment_cancellation_rows": 0,
        "cleanup_gateway_retry_count": 0,
        "assignments_cleanup_verified": 2,
        "assignment_event_order_high_water": 1,
        "assignment_measured_high_water": 1,
        "outer_sessions_created": 2,
        "outer_sessions_deleted": 2,
        "outer_session_high_water": 1,
        "pool_drain_deleted": 2,
        "gateway_close_warnings": 0,
        "recovered_poisoned_assignments": 0,
        "failures": 0,
    }
    return {
        "schema_version": 1,
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        **counts,
        "raw_audit_sha256": "1" * 64,
        "pool_event_log_sha256": "2" * 64,
        "pool_wal_sha256": "3" * 64,
        "pool_drain_sha256": "4" * 64,
    }


def test_capacity_limited_smoke_accepts_truthful_partial_overlap(tmp_path: Path) -> None:
    cleanup = tmp_path / "cleanup.json"
    cleanup.write_text(__import__("json").dumps(_cleanup()))

    observed, _ = _validate_cleanup(
        cleanup,
        expected_count=2,
        expected_concurrency=2,
        require_saturation=False,
    )

    assert observed["assignment_measured_high_water"] == 1


def test_full_run_still_requires_concurrency_saturation(tmp_path: Path) -> None:
    cleanup = tmp_path / "cleanup.json"
    cleanup.write_text(__import__("json").dumps(_cleanup()))

    with pytest.raises(DirectKimiCertificateError, match="^pool_cleanup_invalid$"):
        _validate_cleanup(cleanup, expected_count=2, expected_concurrency=2)


@pytest.mark.parametrize(
    "implementation",
    ("direct-kimi-transparent-v1", "direct-kimi-transparent-v2"),
)
def test_certifier_accepts_marker_bound_schema_two_router_receipt(
    tmp_path: Path,
    implementation: str,
) -> None:
    output = tmp_path / "private" / "direct_kimi_router_final.json"
    binding = {
        "eval_run_identity_sha256": "1" * 64,
        "invocation_identity_sha256": "2" * 64,
    }
    manifest = {
        "endpoint_bundle_sha256": "3" * 64,
        "router": {
            "implementation": implementation,
            "implementation_sha256": "4" * 64,
        },
    }
    receipt = {
        "schema_version": 2,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        **binding,
        "worker_manifest_sha256": "5" * 64,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": 24,
        "implementation": implementation,
        "implementation_sha256": manifest["router"]["implementation_sha256"],
        "policy": "consistent_hash",
        "request_id_headers": ["x-session-id"],
        "request_timeout_seconds": 43_200,
        "retries": 0,
        "max_active_requests": 1,
        "total_requests": 2,
        "chat_requests": 2,
        "worker_request_counts_sha256": "6" * 64,
        "source_generation_revalidated": True,
    }
    direct_kimi_workers._atomic_write(
        output,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        exclusive=True,
    )

    assert (
        _validate_router_receipt(
            output,
            manifest,
            "5" * 64,
            minimum_chat_requests=1,
            binding=binding,
        )
        == receipt
    )


def test_certifier_accepts_c23_profiled_router_receipt(tmp_path: Path) -> None:
    output = tmp_path / "private" / "direct_kimi_router_final.json"
    binding = {
        "eval_run_identity_sha256": "1" * 64,
        "invocation_identity_sha256": "2" * 64,
    }
    manifest = {
        "endpoint_bundle_sha256": "3" * 64,
        "workers": [{} for _ in range(23)],
        "router": {
            "implementation": "direct-kimi-transparent-v2",
            "implementation_sha256": "4" * 64,
            "capacity_profile": "sandoq-c23-v1",
            "endpoint_identifier": "cpu-132-021_8103",
            "max_concurrent_requests": 23,
            "request_timeout_seconds": 144_000,
        },
    }
    receipt = {
        "schema_version": 4,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        **binding,
        "worker_manifest_sha256": "5" * 64,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": 23,
        "implementation": manifest["router"]["implementation"],
        "implementation_sha256": manifest["router"]["implementation_sha256"],
        "policy": "consistent_hash",
        "request_id_headers": ["x-session-id"],
        "request_timeout_seconds": 144_000,
        "retries": 0,
        "max_active_requests": 2,
        "total_requests": 3,
        "chat_requests": 3,
        "worker_request_counts_sha256": "6" * 64,
        "source_generation_revalidated": True,
        "capacity_profile": "sandoq-c23-v1",
        "endpoint_identifier": "cpu-132-021_8103",
        "configured_capacity": 23,
        "configured_per_worker_capacity": 1,
        "active_forwarded_requests": 0,
        "worker_active_request_counts_sha256": hashlib.sha256(
            (json.dumps([0] * 23, separators=(",", ":")) + "\n").encode()
        ).hexdigest(),
        "worker_session_counts_sha256": "7" * 64,
        "active_worker_waiters": 0,
        "worker_waiting_request_counts_sha256": hashlib.sha256(
            (json.dumps([0] * 23, separators=(",", ":")) + "\n").encode()
        ).hexdigest(),
        "max_active_chat_requests": 2,
        "capacity_rejections": 0,
        "queue_overflow_rejections": 0,
        "route_tracking_overflows": 0,
        "cross_route_anomalies": 0,
        "tracked_sessions": 3,
    }
    direct_kimi_workers._atomic_write(
        output,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        exclusive=True,
    )

    assert (
        _validate_router_receipt(
            output,
            manifest,
            "5" * 64,
            minimum_chat_requests=1,
            binding=binding,
        )
        == receipt
    )


def test_certifier_accepts_unsaturated_w2_receipt_within_capacity_proof_envelope(tmp_path: Path) -> None:
    output = tmp_path / "private" / "direct_kimi_router_final.json"
    binding = {
        "eval_run_identity_sha256": "1" * 64,
        "invocation_identity_sha256": "2" * 64,
    }
    manifest = {
        "endpoint_bundle_sha256": "3" * 64,
        "workers": [{} for _ in range(24)],
        "router": {
            "implementation": "direct-kimi-transparent-v2",
            "implementation_sha256": "4" * 64,
            "capacity_profile": "sandoq-c64-w2-v1",
            "endpoint_identifier": "cpu-132-021_8103",
            "max_concurrent_requests": 64,
            "request_timeout_seconds": 144_000,
        },
    }
    zero_counts = hashlib.sha256((json.dumps([0] * 24, separators=(",", ":")) + "\n").encode()).hexdigest()
    receipt = {
        "schema_version": 5,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        **binding,
        "worker_manifest_sha256": "5" * 64,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": 24,
        "implementation": manifest["router"]["implementation"],
        "implementation_sha256": manifest["router"]["implementation_sha256"],
        "policy": "consistent_hash",
        "request_id_headers": ["x-session-id"],
        "request_timeout_seconds": 144_000,
        "retries": 0,
        "max_active_requests": 32,
        "total_requests": 66,
        "chat_requests": 66,
        "worker_request_counts_sha256": "6" * 64,
        "source_generation_revalidated": True,
        "capacity_profile": "sandoq-c64-w2-v1",
        "endpoint_identifier": "cpu-132-021_8103",
        "configured_capacity": 64,
        "configured_per_worker_capacity": 2,
        "active_forwarded_requests": 0,
        "worker_active_request_counts_sha256": zero_counts,
        "worker_session_counts_sha256": "7" * 64,
        "active_worker_waiters": 0,
        "worker_waiting_request_counts_sha256": zero_counts,
        "max_active_chat_requests": 32,
        "capacity_rejections": 0,
        "queue_overflow_rejections": 0,
        "route_tracking_overflows": 0,
        "cross_route_anomalies": 0,
        "tracked_sessions": 66,
        "max_active_forwarded_requests": 32,
        "worker_max_active_request_counts_sha256": "8" * 64,
        "worker_queue_timeouts": 0,
        "upstream_http_429": 0,
        "upstream_http_5xx": 0,
    }
    direct_kimi_workers._atomic_write(
        output,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        exclusive=True,
    )

    assert (
        _validate_router_receipt(
            output,
            manifest,
            "5" * 64,
            minimum_chat_requests=66,
            binding=binding,
        )
        == receipt
    )

    invalid = dict(receipt, max_active_forwarded_requests=49)
    invalid_output = tmp_path / "invalid" / "direct_kimi_router_final.json"
    direct_kimi_workers._atomic_write(
        invalid_output,
        (json.dumps(invalid, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        exclusive=True,
    )
    with pytest.raises(DirectKimiCertificateError, match="^router_receipt_invalid$"):
        _validate_router_receipt(
            invalid_output,
            manifest,
            "5" * 64,
            minimum_chat_requests=66,
            binding=binding,
        )
