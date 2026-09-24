import json
from pathlib import Path

import pytest
from sanitize_sandoq_cleanup_audit import CleanupAuditError, sanitize


def _managed_event(event: str, **values: object) -> dict[str, object]:
    return {
        "schema_version": 2,
        "event": event,
        "timestamp": 1.0,
        "slurm_job_id": "synthetic-job",
        "wandb_run_id": None,
        **values,
    }


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
    started = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": "pool_started",
    }
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
    event.write_text(
        json.dumps(started)
        + "\n"
        + json.dumps(acquired)
        + "\n"
        + json.dumps(released)
        + "\n"
        + json.dumps(drained)
        + "\n"
    )
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


def _append_complete_lifecycle(
    raw: Path,
    event: Path,
    wal: Path,
    drain: Path,
    *,
    suffix: str = "2",
    include_pool_drain: bool = True,
) -> None:
    outer_id = f"opaque-outer-{suffix}"
    assignment_id = f"opaque-assignment-{suffix}"

    audit = json.loads(raw.read_text())
    audit["recorded_outer_sessions"] += 1
    audit["already_absent"] += 1
    audit["verified_http_404"] += 1
    audit["receipts"].append({"outer_session_id": outer_id, "verified_http_status": 404})
    raw.write_text(json.dumps(audit))

    rows = [
        {"schema_version": 2, "record_type": "pool_event", "event": "pool_started"},
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "assignment_acquired",
            "assignment_id": assignment_id,
            "outer_session_id": outer_id,
            "active_assignment_count": 1,
        },
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "assignment_released",
            "assignment_id": assignment_id,
            "outer_session_id": outer_id,
            "status": "recycled",
            "nested_recycle_verified": True,
            "cleanup_gateway_retry_count": 0,
            "cleanup_gateway_retry_exhausted_count": 0,
        },
    ]
    if include_pool_drain:
        rows.append(
            {
                "schema_version": 2,
                "record_type": "pool_event",
                "event": "pool_drained",
                "reason": "final_client_departure",
                "failures": {},
                "event_records_dropped": 0,
            }
        )
    with event.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": 2,
                    "record_type": "pool_event",
                    "event": "gateway_close_failed",
                }
            )
            + "\n"
        )
        handle.write("".join(json.dumps(row) + "\n" for row in rows))

    with wal.open("a") as handle:
        handle.write(json.dumps({"schema_version": 2, "event": "outer_created", "outer_session_id": outer_id}) + "\n")
        handle.write(json.dumps({"schema_version": 2, "event": "outer_deleted", "outer_session_id": outer_id}) + "\n")

    marker = json.loads(drain.read_text())
    marker["deleted"].append({"outer_session_id": outer_id, "verified_http_status": 404})
    drain.write_text(json.dumps(marker))


def test_sanitizer_reconciles_all_cleanup_layers_without_publishing_ids(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    output = tmp_path / "sanitized.json"
    result = sanitize(raw, event, wal, drain, output)

    assert result["state"] == "passed"
    assert result["assignments_cleanup_verified"] == 1
    assert result["outer_sessions_deleted"] == 1
    assert "opaque" not in output.read_text()
    assert all(path.exists() for path in (raw, event, wal, drain))


def test_sanitizer_accepts_multiple_fully_drained_pool_lifecycles(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    _append_complete_lifecycle(raw, event, wal, drain)

    output = tmp_path / "sanitized.json"
    result = sanitize(raw, event, wal, drain, output)

    assert result["assignments_acquired"] == 2
    assert result["assignments_cleanup_verified"] == 2
    assert result["outer_sessions_created"] == 2
    assert result["outer_sessions_deleted"] == 2
    assert result["gateway_close_warnings"] == 1
    assert "opaque" not in output.read_text()


def test_sanitizer_rejects_an_unclosed_pool_lifecycle(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    _append_complete_lifecycle(raw, event, wal, drain, include_pool_drain=False)

    with pytest.raises(CleanupAuditError, match="assignment_cleanup_coverage_incomplete"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


@pytest.mark.parametrize(
    ("field", "value"),
    [("failures", {"cleanup": "failed"}), ("event_records_dropped", 1)],
)
def test_sanitizer_rejects_failure_in_any_pool_lifecycle(tmp_path: Path, field: str, value: object) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    _append_complete_lifecycle(raw, event, wal, drain)
    rows = [json.loads(line) for line in event.read_text().splitlines()]
    first_drain = next(row for row in rows if row["event"] == "pool_drained")
    first_drain[field] = value
    event.write_text("".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(CleanupAuditError, match="pool_drain_event_invalid"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


def test_sanitizer_rejects_assignment_outside_pool_lifecycle(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    rows = [json.loads(line) for line in event.read_text().splitlines()]
    event.write_text("".join(json.dumps(row) + "\n" for row in rows[1:]))

    with pytest.raises(CleanupAuditError, match="assignment_outside_pool_lifecycle"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


def test_sanitizer_rejects_pool_drain_with_an_active_assignment(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    rows = [json.loads(line) for line in event.read_text().splitlines()]
    rows[2], rows[3] = rows[3], rows[2]
    event.write_text("".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(CleanupAuditError, match="pool_drain_event_invalid"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


def test_sanitizer_accepts_strict_managed_shell_recovery_chain_without_publishing_ids(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    event_rows = [json.loads(line) for line in event.read_text().splitlines()]
    event_rows[1].update(slot_id=0, generation=1)
    event_rows.insert(
        2,
        _managed_event(
            "managed_shell_recovered",
            record_type="pool_event",
            assignment_id="opaque-assignment",
            outer_session_id="opaque-outer",
            slot_id=0,
            generation=1,
            shell_generation=1,
            recovery_count=1,
        ),
    )
    event.write_text("".join(json.dumps(row) + "\n" for row in event_rows))
    wal.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {"schema_version": 2, "event": "outer_created", "outer_session_id": "opaque-outer"},
                _managed_event(
                    "managed_shell_bound",
                    assignment_id="opaque-assignment",
                    outer_session_id="opaque-outer",
                    slot_id=0,
                    generation=1,
                    shell_id="opaque-shell-old",
                    shell_generation=0,
                ),
                _managed_event(
                    "managed_shell_recovered",
                    assignment_id="opaque-assignment",
                    outer_session_id="opaque-outer",
                    slot_id=0,
                    generation=1,
                    prior_shell_id="opaque-shell-old",
                    shell_id="opaque-shell-new",
                    shell_generation=1,
                ),
                {"schema_version": 2, "event": "outer_deleted", "outer_session_id": "opaque-outer"},
            )
        )
    )

    output = tmp_path / "sanitized.json"
    result = sanitize(raw, event, wal, drain, output)

    assert not {
        "managed_shell_bindings",
        "managed_shell_recoveries",
        "assignments_with_managed_shell_recovery",
        "managed_shell_recovery_failures",
        "abandoned_shell_operations",
    } & set(result)
    assert "opaque-assignment" not in output.read_text()
    assert "opaque-shell-old" not in output.read_text()
    assert "opaque-shell-new" not in output.read_text()


def test_sanitizer_preserves_standard_wal_without_shell_lifecycle_rows(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)

    result = sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")

    assert not {
        "managed_shell_bindings",
        "managed_shell_recoveries",
        "assignments_with_managed_shell_recovery",
        "managed_shell_recovery_failures",
        "abandoned_shell_operations",
    } & set(result)


def test_sanitizer_rejects_unlinked_managed_shell_recovery(tmp_path: Path) -> None:
    raw, event, wal, drain = _write_evidence(tmp_path)
    event_rows = [json.loads(line) for line in event.read_text().splitlines()]
    event_rows[1].update(slot_id=0, generation=1)
    event.write_text("".join(json.dumps(row) + "\n" for row in event_rows))
    rows = [json.loads(line) for line in wal.read_text().splitlines()]
    rows.insert(
        1,
        _managed_event(
            "managed_shell_recovered",
            assignment_id="opaque-assignment",
            outer_session_id="opaque-outer",
            slot_id=0,
            generation=1,
            prior_shell_id="opaque-shell-old",
            shell_id="opaque-shell-new",
            shell_generation=1,
        ),
    )
    wal.write_text("".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(CleanupAuditError, match="managed_shell_wal_order_invalid"):
        sanitize(raw, event, wal, drain, tmp_path / "sanitized.json")


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
    rows[2] = {
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
    rows[2] = {
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
        2,
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "assignment_acquired",
            "assignment_id": "opaque-assignment-2",
            "outer_session_id": second,
            "active_assignment_count": 2,
        },
    )
    rows[3]["outer_session_id"] = second
    rows.insert(
        4,
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
