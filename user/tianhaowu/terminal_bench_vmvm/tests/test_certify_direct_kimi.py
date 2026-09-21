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
    _validate_cleanup,
    _validate_router_receipt,
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


def test_certifier_accepts_marker_bound_schema_two_router_receipt(tmp_path: Path) -> None:
    output = tmp_path / "private" / "direct_kimi_router_final.json"
    binding = {
        "eval_run_identity_sha256": "1" * 64,
        "invocation_identity_sha256": "2" * 64,
    }
    manifest = {
        "endpoint_bundle_sha256": "3" * 64,
        "router": {"implementation_sha256": "4" * 64},
    }
    receipt = {
        "schema_version": 2,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        **binding,
        "worker_manifest_sha256": "5" * 64,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": 24,
        "implementation": "direct-kimi-transparent-v1",
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
