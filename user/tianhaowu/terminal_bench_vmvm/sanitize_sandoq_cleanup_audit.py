#!/usr/bin/env python3
"""Validate authoritative Sandoq cleanup evidence and retain only aggregates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path


class CleanupAuditError(ValueError):
    pass


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def sanitize(
    raw_audit: Path,
    event_log: Path,
    wal: Path,
    drain_marker: Path,
    output: Path,
) -> dict[str, object]:
    try:
        audit_raw = raw_audit.resolve(strict=True).read_bytes()
        audit = json.loads(audit_raw)
        drain_raw = drain_marker.resolve(strict=True).read_bytes()
        drain = json.loads(drain_raw)
        event_raw = event_log.resolve(strict=True).read_bytes()
        wal_raw = wal.resolve(strict=True).read_bytes()
    except (OSError, json.JSONDecodeError) as error:
        raise CleanupAuditError("cleanup_audit_missing_or_invalid") from error
    if not event_log.is_file() or not wal.is_file():
        raise CleanupAuditError("durable_cleanup_logs_missing")
    if not isinstance(audit, dict):
        raise CleanupAuditError("authoritative_cleanup_not_verified")
    receipts = audit.get("receipts")
    recorded = audit.get("recorded_outer_sessions")
    already_absent = audit.get("already_absent")
    deleted_and_verified = audit.get("deleted_and_verified")
    if (
        audit.get("schema_version") != 1
        or not _is_int(recorded)
        or recorded < 1
        or not _is_int(already_absent)
        or not _is_int(deleted_and_verified)
        or min(already_absent, deleted_and_verified) < 0
        or already_absent + deleted_and_verified != recorded
        or already_absent != recorded
        or deleted_and_verified != 0
        or audit.get("verified_http_404") != recorded
        or audit.get("failures") != []
        or not isinstance(receipts, list)
        or len(receipts) != recorded
        or any(
            not isinstance(receipt, dict) or receipt.get("verified_http_status") != 404 or bool(receipt.get("error"))
            for receipt in receipts
        )
    ):
        raise CleanupAuditError("authoritative_cleanup_not_verified")
    receipt_outer_ids = [receipt.get("outer_session_id") for receipt in receipts]
    if any(not isinstance(value, str) or not value for value in receipt_outer_ids) or len(
        set(receipt_outer_ids)
    ) != len(receipt_outer_ids):
        raise CleanupAuditError("authoritative_cleanup_identity_invalid")
    if (
        not isinstance(drain, dict)
        or drain.get("schema_version") != 3
        or drain.get("reason") != "final_client_departure"
        or drain.get("failures") != {}
        or not _is_int(drain.get("event_records_dropped"))
        or drain.get("event_records_dropped") != 0
        or not isinstance(drain.get("deleted"), list)
        or any(
            not isinstance(entry, dict)
            or entry.get("verified_http_status") != 404
            or not isinstance(entry.get("outer_session_id"), str)
            for entry in drain.get("deleted", [])
        )
    ):
        raise CleanupAuditError("pool_drain_not_verified")
    acquired_counts: Counter[str] = Counter()
    assignment_outer: dict[str, str] = {}
    release_counts: Counter[str] = Counter()
    cancellation_counts: Counter[str] = Counter()
    active_assignments: set[str] = set()
    assignment_high_water = 0
    measured_assignment_high_water = 0
    release_rows = 0
    cleanup_gateway_retry_count = 0
    pool_drained = 0
    gateway_close_warnings = 0
    recovered_poisoned_assignments = 0
    event_outer_ids: set[str] = set()
    for line_number, line in enumerate(event_raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise CleanupAuditError(f"pool_event_invalid_at_{line_number}") from error
        if not isinstance(event, dict):
            raise CleanupAuditError(f"pool_event_invalid_at_{line_number}")
        if event.get("schema_version") != 2 or event.get("record_type") != "pool_event":
            raise CleanupAuditError(f"pool_event_schema_invalid_at_{line_number}")
        event_name = event.get("event")
        assignment_id = event.get("assignment_id")
        outer_id = event.get("outer_session_id")
        if outer_id is not None:
            if not isinstance(outer_id, str) or not outer_id:
                raise CleanupAuditError("pool_event_outer_identity_invalid")
            event_outer_ids.add(outer_id)
        if event_name == "assignment_acquired":
            if not isinstance(assignment_id, str) or not assignment_id:
                raise CleanupAuditError("pool_event_assignment_identity_invalid")
            if not isinstance(outer_id, str) or not outer_id:
                raise CleanupAuditError("pool_event_outer_identity_invalid")
            acquired_counts[assignment_id] += 1
            assignment_outer[assignment_id] = outer_id
            active_assignments.add(assignment_id)
            assignment_high_water = max(assignment_high_water, len(active_assignments))
            measured_active = event.get("active_assignment_count")
            if not _is_int(measured_active) or measured_active < 1:
                raise CleanupAuditError("active_assignment_count_invalid")
            measured_assignment_high_water = max(measured_assignment_high_water, measured_active)
        elif event_name == "assignment_release_failed":
            raise CleanupAuditError("assignment_release_failure_recorded")
        elif event_name == "assignment_cancelled":
            if (
                not isinstance(assignment_id, str)
                or not isinstance(outer_id, str)
                or assignment_outer.get(assignment_id) != outer_id
                or event.get("cancellation_verified") is not True
                or event.get("status") is not None
                or bool(event.get("error"))
            ):
                raise CleanupAuditError("assignment_cancellation_not_verified")
            cancellation_counts[assignment_id] += 1
            active_assignments.discard(assignment_id)
        elif event_name == "assignment_released":
            release_rows += 1
            status = event.get("status")
            verified = (
                (
                    status == "recycled"
                    and event.get("nested_recycle_verified") is True
                    and event.get("poisoned") is not True
                    and not event.get("error")
                )
                or (
                    status == "retired"
                    and event.get("nested_recycle_verified") is True
                    and event.get("poisoned") is not True
                    and event.get("outer_deletion_verified_http_status") == 404
                    and not event.get("error")
                )
                or (
                    status == "poisoned"
                    and event.get("poisoned") is True
                    and event.get("outer_deletion_verified_http_status") == 404
                )
            )
            if (
                not isinstance(assignment_id, str)
                or not isinstance(outer_id, str)
                or assignment_outer.get(assignment_id) != outer_id
                or not verified
                or not _is_int(event.get("cleanup_gateway_retry_count", 0))
                or event.get("cleanup_gateway_retry_count", 0) < 0
                or not _is_int(event.get("cleanup_gateway_retry_exhausted_count", 0))
                or event.get("cleanup_gateway_retry_exhausted_count", 0) != 0
            ):
                raise CleanupAuditError("assignment_cleanup_not_verified")
            release_counts[assignment_id] += 1
            cleanup_gateway_retry_count += event.get("cleanup_gateway_retry_count", 0)
            active_assignments.discard(assignment_id)
            if event.get("status") == "poisoned":
                recovered_poisoned_assignments += 1
        elif event_name == "pool_drain_incomplete":
            raise CleanupAuditError("pool_drain_incomplete")
        elif event_name == "pool_drained":
            if (
                event.get("reason") != "final_client_departure"
                or event.get("failures") != {}
                or not _is_int(event.get("event_records_dropped"))
                or event.get("event_records_dropped") != 0
            ):
                raise CleanupAuditError("pool_drain_event_invalid")
            pool_drained += 1
        elif event_name == "gateway_close_failed":
            gateway_close_warnings += 1
    if (
        not acquired_counts
        or acquired_counts != release_counts + cancellation_counts
        or any(count != 1 for count in acquired_counts.values())
        or any(count != 1 for count in (release_counts + cancellation_counts).values())
        or active_assignments
        or pool_drained != 1
    ):
        raise CleanupAuditError("assignment_cleanup_coverage_incomplete")
    outer_created_counts: Counter[str] = Counter()
    outer_deleted_counts: Counter[str] = Counter()
    active_outer: set[str] = set()
    outer_high_water = 0
    for line_number, line in enumerate(wal_raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise CleanupAuditError(f"pool_wal_invalid_at_{line_number}") from error
        if not isinstance(event, dict):
            raise CleanupAuditError(f"pool_wal_invalid_at_{line_number}")
        if event.get("schema_version") != 2:
            raise CleanupAuditError(f"pool_wal_schema_invalid_at_{line_number}")
        outer_id = event.get("outer_session_id")
        if event.get("event") not in {"outer_created", "outer_deleted"}:
            raise CleanupAuditError(f"pool_wal_event_invalid_at_{line_number}")
        if not isinstance(outer_id, str) or not outer_id:
            raise CleanupAuditError(f"pool_wal_identity_invalid_at_{line_number}")
        if event.get("event") == "outer_created":
            outer_created_counts[outer_id] += 1
            active_outer.add(outer_id)
            outer_high_water = max(outer_high_water, len(active_outer))
        else:
            outer_deleted_counts[outer_id] += 1
            active_outer.discard(outer_id)
    outer_created = set(outer_created_counts)
    outer_deleted = set(outer_deleted_counts)
    drain_outer_ids = [entry["outer_session_id"] for entry in drain["deleted"]]
    if (
        not outer_created
        or not outer_deleted.issubset(outer_created)
        or not outer_created.issubset(outer_deleted)
        or active_outer
        or any(count != 1 for count in outer_created_counts.values())
        or any(count != 1 for count in outer_deleted_counts.values())
        or set(receipt_outer_ids) != outer_created
        or event_outer_ids != outer_created
        or recorded != len(outer_created)
        or len(drain_outer_ids) != len(set(drain_outer_ids))
        or not set(drain_outer_ids).issubset(outer_created & outer_deleted)
    ):
        raise CleanupAuditError("pool_wal_cleanup_coverage_incomplete")
    sanitized = {
        "schema_version": 1,
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        "recorded_outer_sessions": recorded,
        "verified_http_404": recorded,
        "already_absent": already_absent,
        "deleted_and_verified": deleted_and_verified,
        "assignments_acquired": len(acquired_counts),
        "assignment_release_rows": release_rows,
        "assignment_cancellation_rows": sum(cancellation_counts.values()),
        "cleanup_gateway_retry_count": cleanup_gateway_retry_count,
        "assignments_cleanup_verified": len(release_counts) + len(cancellation_counts),
        "assignment_event_order_high_water": assignment_high_water,
        "assignment_measured_high_water": measured_assignment_high_water,
        "outer_sessions_created": len(outer_created),
        "outer_sessions_deleted": len(outer_created & outer_deleted),
        "outer_session_high_water": outer_high_water,
        "pool_drain_deleted": len(drain["deleted"]),
        "gateway_close_warnings": gateway_close_warnings,
        "recovered_poisoned_assignments": recovered_poisoned_assignments,
        "failures": 0,
        "raw_audit_sha256": hashlib.sha256(audit_raw).hexdigest(),
        "pool_event_log_sha256": hashlib.sha256(event_raw).hexdigest(),
        "pool_wal_sha256": hashlib.sha256(wal_raw).hexdigest(),
        "pool_drain_sha256": hashlib.sha256(drain_raw).hexdigest(),
    }
    raw = (json.dumps(sanitized, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(dir=output.parent, prefix=f".{output.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return sanitized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-audit", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--wal", type=Path, required=True)
    parser.add_argument("--drain-marker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = sanitize(args.raw_audit, args.event_log, args.wal, args.drain_marker, args.output)
    print(
        f"[sandoq-cleanup] recorded={result['recorded_outer_sessions']} "
        f"verified_http_404={result['verified_http_404']} failures=0"
    )


if __name__ == "__main__":
    main()
