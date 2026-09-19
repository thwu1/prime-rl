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
        "active_assignment_count": 1,
    }
    released = release or {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_released",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        "status": "recycled",
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
        "event_records_dropped": 0,
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
                "event_records_dropped": 0,
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


@pytest.mark.parametrize(
    "fields",
    [
        {"nested_recycle_verified": True},
        {"status": "retired", "nested_recycle_verified": True},
        {"status": "recycled", "nested_recycle_verified": True, "poisoned": True},
        {"status": "unknown", "verified_http_status": 404},
    ],
)
def test_sanitizer_rejects_unverified_assignment_release(tmp_path: Path, fields: dict) -> None:
    release = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_released",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        **fields,
    }
    raw, event, wal, drain = _write_evidence(tmp_path, release=release)

    with pytest.raises(CleanupAuditError, match="assignment_cleanup_not_verified"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


def test_sanitizer_accepts_verified_poison_recovery(tmp_path: Path) -> None:
    release = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_released",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        "status": "poisoned",
        "poisoned": True,
        "outer_deletion_verified_http_status": 404,
        "error": "nested cleanup failed before verified outer deletion",
        "cleanup_gateway_retry_count": 0,
        "cleanup_gateway_retry_exhausted_count": 0,
    }
    raw, event, wal, drain = _write_evidence(tmp_path, release=release)

    result = sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")
    assert result["recovered_poisoned_assignments"] == 1


def test_sanitizer_accepts_verified_assigned_cancellation(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    rows = [json.loads(line) for line in event.read_text().splitlines()]
    rows[1] = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_cancelled",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        "cancellation_verified": True,
    }
    event.write_text("".join(json.dumps(row) + "\n" for row in rows))

    result = sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")
    assert result["assignment_release_rows"] == 0
    assert result["assignment_cancellation_rows"] == 1
    assert result["assignments_cleanup_verified"] == 1


def test_sanitizer_rejects_unverified_assigned_cancellation(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    rows = [json.loads(line) for line in event.read_text().splitlines()]
    rows[1] = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "assignment_cancelled",
        "assignment_id": "opaque-assignment",
        "outer_session_id": "opaque-outer",
        "cancellation_verified": False,
    }
    event.write_text("".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(CleanupAuditError, match="assignment_cancellation_not_verified"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


def test_sanitizer_rejects_swapped_assignment_outer_identity(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    second = "opaque-outer-2"
    audit = json.loads(raw.read_text())
    audit.update(recorded_outer_sessions=2, already_absent=2, verified_http_404=2)
    audit["receipts"].append({"outer_session_id": second, "verified_http_status": 404})
    raw.write_text(json.dumps(audit))
    rows = [json.loads(line) for line in event.read_text().splitlines()]
    rows.insert(
        1,
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "assignment_acquired",
            "assignment_id": "opaque-assignment-2",
            "outer_session_id": second,
            "active_assignment_count": 2,
        },
    )
    rows[2]["outer_session_id"] = second
    rows.insert(
        3,
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "assignment_released",
            "assignment_id": "opaque-assignment-2",
            "outer_session_id": "opaque-outer",
            "status": "recycled",
            "nested_recycle_verified": True,
        },
    )
    event.write_text("".join(json.dumps(row) + "\n" for row in rows))
    wal.write_text(
        wal.read_text()
        + json.dumps({"schema_version": 2, "event": "outer_created", "outer_session_id": second})
        + "\n"
        + json.dumps({"schema_version": 2, "event": "outer_deleted", "outer_session_id": second})
        + "\n"
    )
    marker = json.loads(drain.read_text())
    marker["deleted"].append({"outer_session_id": second, "verified_http_status": 404})
    drain.write_text(json.dumps(marker))

    with pytest.raises(CleanupAuditError, match="assignment_cleanup_not_verified"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")
