#!/usr/bin/env python3
"""Promote cleanup-proven build receipts and quarantine all other receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _plan(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in path.read_text().splitlines():
        if not raw:
            continue
        fields = raw.split("\t")
        if len(fields) != 5 or re.fullmatch(r"[0-9a-f]{64}", fields[2]) is None:
            raise SystemExit("build plan contains an invalid row")
        rows.append(dict(zip(("task", "role", "context_sha256", "context", "image"), fields)))
    if not rows:
        raise SystemExit("build plan is empty")
    return rows


def _outcomes(
    log_root: Path,
    job_id: str,
    array_count: int,
    plan_rows: int,
    *,
    require_complete: bool,
) -> dict[int, str]:
    outcomes: dict[int, str] = {}
    logs = sorted(log_root.glob(f"sandoq_build_{job_id}_*.log"))
    if len(logs) != array_count:
        raise SystemExit("build log count does not match the expected array width")
    for path in logs:
        match = re.fullmatch(rf"sandoq_build_{re.escape(job_id)}_([0-9]+)\.log", path.name)
        if match is None:
            raise SystemExit("build log name is invalid")
        array_index = int(match.group(1))
        if not 0 <= array_index < array_count:
            raise SystemExit("build log array index is invalid")
        local: dict[int, str] = {}
        for line in path.read_text(errors="replace").splitlines():
            terminal = re.fullmatch(r"row=([0-9]+) state=(success|failed)(?: .*)?", line)
            if terminal is None:
                continue
            local_index = int(terminal.group(1))
            if local_index in local:
                raise SystemExit("build log contains duplicate terminal row outcomes")
            local[local_index] = terminal.group(2)
        for local_index, state in local.items():
            global_index = array_index + local_index * array_count
            if global_index >= plan_rows or global_index in outcomes:
                raise SystemExit("build log row mapping is invalid")
            outcomes[global_index] = state
    if require_complete and len(outcomes) != plan_rows:
        raise SystemExit("build logs do not contain one terminal outcome for every plan row")
    return outcomes


def _matching_receipt(path: Path, row: dict[str, str]) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit("build receipt is unreadable") from error
    if (
        not isinstance(value, dict)
        or value.get("task") != row["task"]
        or value.get("role") != row["role"]
        or value.get("context_sha256") != row["context_sha256"]
        or value.get("image") != row["image"]
    ):
        raise SystemExit("build receipt does not match its plan row")
    return value


def reconcile(
    plan_path: Path,
    log_root: Path,
    status_root: Path,
    quarantine_root: Path,
    job_id: str,
    array_count: int,
    *,
    require_complete: bool = True,
) -> dict[str, object]:
    rows = _plan(plan_path)
    outcomes = _outcomes(
        log_root,
        job_id,
        array_count,
        len(rows),
        require_complete=require_complete,
    )
    promoted = 0
    quarantined = 0
    failed_without_receipts = 0
    unobserved_without_receipts = 0
    quarantine_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for index, row in enumerate(rows):
        name = f"{row['context_sha256']}.{row['role']}.json"
        status = status_root / name
        outcome = outcomes.get(index)
        if outcome == "success":
            if not status.is_file():
                raise SystemExit("successful build row has no receipt")
            value = _matching_receipt(status, row)
            digest = value.get("digest")
            if value.get("state") != "success" or not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise SystemExit("successful build row has an invalid receipt")
            value["cleanup_verified"] = True
            _atomic_json(status, value)
            promoted += 1
            continue
        if not status.exists():
            if outcome == "failed":
                failed_without_receipts += 1
            else:
                unobserved_without_receipts += 1
            continue
        _matching_receipt(status, row)
        destination = quarantine_root / name
        if destination.exists():
            raise SystemExit("quarantine destination already exists")
        os.replace(status, destination)
        quarantined += 1

    return {
        "schema_version": 1,
        "job_id": job_id,
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "rows": len(rows),
        "terminal_outcomes": len(outcomes),
        "unobserved_rows": len(rows) - len(outcomes),
        "success_outcomes_promoted": promoted,
        "non_success_receipts_quarantined": quarantined,
        "failed_outcomes_without_receipts": failed_without_receipts,
        "unobserved_rows_without_receipts": unobserved_without_receipts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--log-root", type=Path, required=True)
    parser.add_argument("--status-root", type=Path, required=True)
    parser.add_argument("--quarantine-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--array-count", type=int, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.job_id.isdigit() or args.array_count < 1:
        parser.error("job ID and array count must be positive decimal integers")
    receipt = reconcile(
        args.plan,
        args.log_root,
        args.status_root,
        args.quarantine_root,
        args.job_id,
        args.array_count,
        require_complete=not args.allow_incomplete,
    )
    _atomic_json(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
