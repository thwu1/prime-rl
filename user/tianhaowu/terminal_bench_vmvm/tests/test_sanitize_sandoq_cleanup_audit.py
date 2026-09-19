import json
from pathlib import Path

import pytest
from sanitize_sandoq_cleanup_audit import CleanupAuditError, sanitize


def _write_evidence(root: Path, *, release: dict | None = None) -> tuple[Path, Path, Path, Path]:
    raw = root / "pool_cleanup_audit.json"
    raw.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "recorded_outer_sessions": 1,
                "already_absent": 1,
                "deleted_and_verified": 0,
                "verified_http_404": 1,
                "failures": [],
                "receipts": [{"outer_session_id": "opaque-outer", "verified_http_status": 404}],
            }
        )
    )
    event = root / "pool_events.jsonl"
    acquired = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_acquired",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
    }
    released = release or {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_released",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        "nested_recycle_verified": True,
        "cleanup_gateway_retry_count": 1,
        "cleanup_gateway_retry_exhausted_count": 0,
    }
    drained = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "pool_drained",
        "reason": "final_client_departure",
        "failures": {},
    }
    event.write_text(json.dumps(acquired) + "\n" + json.dumps(released) + "\n" + json.dumps(drained) + "\n")
    wal = root / "pool.wal.jsonl"
    wal.write_text(
        json.dumps({"schema_version": 2, "event": "outer_created", "outer_session_id": "opaque-outer"})
        + "\n"
        + json.dumps({"schema_version": 2, "event": "outer_deleted", "outer_session_id": "opaque-outer"})
        + "\n"
    )
    drain = root / "pool.drained.json"
    drain.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "reason": "final_client_departure",
                "deleted": [{"outer_session_id": "opaque-outer", "verified_http_status": 404}],
                "failures": {},
            }
        )
    )
    return raw, event, wal, drain


def test_sanitizer_reconciles_all_cleanup_layers_without_publishing_ids(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    output = tmp_path / "sanitized.json"
    result = sanitize(raw, event, wal, drain, output)

    assert result["state"] == "passed"
    assert result["assignments_cleanup_verified"] == 1
    assert result["outer_sessions_deleted"] == 1
    assert "opaque" not in output.read_text()
    assert all(path.exists() for path in (raw, event, wal, drain))


def test_sanitizer_rejects_unverified_assignment_release(tmp_path: Path) -> None:
    release = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_released",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        "poisoned": False,
        "outer_deletion_verified_http_status": 404,
    }
    raw, event, wal, drain = _write_evidence(tmp_path, release=release)

    with pytest.raises(CleanupAuditError, match="assignment_cleanup_not_verified"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")
