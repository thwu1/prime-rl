from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from certify_direct_kimi import (
    CAPACITY_LIMITED_SMOKE_SCOPE,
    DirectKimiCertificateError,
    _capacity_limited_smoke_scope,
    _validate_cleanup,
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
    config.write_text("[taskset]\nresource_multiplier = 2.0\n")

    with pytest.raises(DirectKimiCertificateError, match="^smoke_capacity_scope_invalid$"):
        _capacity_limited_smoke_scope(_identity(config))


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
