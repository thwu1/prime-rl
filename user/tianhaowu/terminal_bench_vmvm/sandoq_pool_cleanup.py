#!/usr/bin/env python3
"""Delete and verify every Sandoq outer session recorded by one eval run.

Adapted from ``recipes/sandoq_swerebench_v2_oci/verify_pool_cleanup.py`` at
upstream commit f7313db42eea4b3be8bcbe16a8072f73cf6abed5 (source SHA-256
35a235bf44acebcdb44d943a615f95ea32c78cf2b7634445178b80f1e130c1ef).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

from sandoq_provider.gateway import get_gateway_adapter

DEFAULT_BASE_URL = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
AUDIT_FILENAME = "pool_cleanup_audit.json"


class CleanupError(RuntimeError):
    """Stable aggregate-only cleanup failure."""


def _jsonl_rows(
    path: Path,
    *,
    code: str,
    allow_incomplete_final: bool,
    incomplete_final: list[bool] | None = None,
) -> list[dict[str, Any]]:
    if not os.path.lexists(path):
        return []
    try:
        before = path.lstat()
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise CleanupError(code) from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) & 0o077
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise CleanupError(code)
    lines = raw.splitlines(keepends=True)
    rows: list[dict[str, Any]] = []
    for index, encoded in enumerate(lines):
        final_incomplete = index == len(lines) - 1 and not encoded.endswith(b"\n")
        if not encoded.strip():
            continue
        try:
            row = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            if allow_incomplete_final and final_incomplete:
                if incomplete_final is not None:
                    incomplete_final.append(True)
                continue
            raise CleanupError(code) from error
        if not isinstance(row, dict):
            raise CleanupError(code)
        rows.append(row)
    return rows


def _recorded_outer_session_ids(
    output_dir: Path,
    *,
    wal_path: Path | None = None,
    live_only: bool = False,
    incomplete_wal: list[bool] | None = None,
) -> list[str]:
    event_created: set[str] = set()
    event_live: set[str] = set()
    for row in _jsonl_rows(
        output_dir / "pool_events.jsonl",
        code="pool_event_log_invalid",
        allow_incomplete_final=True,
    ):
        session_id = row.get("outer_session_id")
        if not isinstance(session_id, str) or not session_id:
            continue
        if row.get("event") == "outer_created":
            event_created.add(session_id)
            event_live.add(session_id)
        elif row.get("event") == "outer_deleted":
            event_live.discard(session_id)

    wal_created: set[str] = set()
    wal_live: set[str] = set()
    wal_seen: set[str] = set()
    if wal_path is not None:
        for row in _jsonl_rows(
            wal_path,
            code="pool_wal_invalid",
            allow_incomplete_final=live_only,
            incomplete_final=incomplete_wal,
        ):
            session_id = row.get("outer_session_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            wal_seen.add(session_id)
            if row.get("event") == "outer_created":
                wal_created.add(session_id)
                wal_live.add(session_id)
            elif row.get("event") == "outer_deleted":
                wal_live.discard(session_id)
    if live_only:
        return sorted(wal_live | (event_live - wal_seen))
    return sorted(event_created | wal_created)


def _publish_private(path: Path, value: object) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.urandom(16).hex()}")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise CleanupError("cleanup_audit_publish_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


async def verify_pool_cleanup(
    output_dir: Path,
    *,
    base_url: str,
    owner: str,
    concurrency: int = 16,
    wal_path: Path | None = None,
    live_only: bool = False,
    adapter: Any | None = None,
) -> dict[str, Any]:
    if not 1 <= concurrency <= 64:
        raise CleanupError("cleanup_concurrency_invalid")
    try:
        metadata = output_dir.lstat()
    except OSError as error:
        raise CleanupError("cleanup_output_directory_invalid") from error
    if (
        output_dir.resolve(strict=True) != output_dir
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CleanupError("cleanup_output_directory_invalid")
    destination = output_dir / AUDIT_FILENAME
    if os.path.lexists(destination):
        raise CleanupError("cleanup_audit_not_fresh")

    incomplete_wal: list[bool] = []
    session_ids = _recorded_outer_session_ids(
        output_dir,
        wal_path=wal_path,
        live_only=live_only,
        incomplete_wal=incomplete_wal,
    )
    gateway = adapter or get_gateway_adapter(base_url, owner)
    semaphore = asyncio.Semaphore(concurrency)

    async def clean(session_id: str) -> dict[str, Any]:
        async with semaphore:
            started = time.monotonic()
            try:
                receipt = await gateway.delete_session_async(
                    session_id,
                    timeout=60,
                    poll_interval=0.5,
                    prime=True,
                    overall_timeout=330,
                )
                cleanup_seconds = float(receipt.cleanup_seconds)
                return {
                    "outer_session_id": session_id,
                    "verified_http_status": int(receipt.verified_http_status),
                    "already_absent": cleanup_seconds == 0.0,
                    "cleanup_seconds": cleanup_seconds,
                    "verification_seconds": float(receipt.verification_seconds),
                    "duration": time.monotonic() - started,
                }
            except Exception as error:  # noqa: BLE001 - private receipt, aggregate CLI
                return {
                    "outer_session_id": session_id,
                    "verified_http_status": None,
                    "already_absent": False,
                    "duration": time.monotonic() - started,
                    "error_type": type(error).__name__,
                }

    receipts = await asyncio.gather(*(clean(session_id) for session_id in session_ids))
    failures = [receipt for receipt in receipts if receipt["verified_http_status"] != 404]
    audit = {
        "schema_version": 1,
        "completed_at_unix": time.time(),
        "recorded_outer_sessions": len(session_ids),
        "already_absent": sum(bool(receipt["already_absent"]) for receipt in receipts),
        "deleted_and_verified": sum(
            receipt["verified_http_status"] == 404 and not receipt["already_absent"] for receipt in receipts
        ),
        "verified_http_404": sum(receipt["verified_http_status"] == 404 for receipt in receipts),
        "failures": failures,
        "receipts": receipts,
    }
    _publish_private(destination, audit)
    if incomplete_wal:
        raise CleanupError("pool_wal_incomplete")
    if failures:
        raise CleanupError("authoritative_cleanup_failed")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OCI_RUNNER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--owner",
        default=os.environ.get("SANDOQ_OWNER") or os.environ.get("OCI_RUNNER_OWNER") or os.environ.get("USER"),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("OCI_RUNNER_POOL_DRAIN_WORKERS", "16")),
    )
    parser.add_argument("--wal", type=Path, default=os.environ.get("OCI_RUNNER_POOL_WAL"))
    parser.add_argument("--live-only", action="store_true")
    try:
        arguments = parser.parse_args()
        if not arguments.owner:
            raise CleanupError("cleanup_owner_missing")
        audit = asyncio.run(
            verify_pool_cleanup(
                arguments.output_dir,
                base_url=arguments.base_url,
                owner=arguments.owner,
                concurrency=arguments.concurrency,
                wal_path=arguments.wal,
                live_only=arguments.live_only,
            )
        )
        print(
            f"Sandoq cleanup passed recorded={audit['recorded_outer_sessions']} verified={audit['verified_http_404']}",
            flush=True,
        )
        return 0
    except (CleanupError, OSError, ValueError):
        print("Sandoq cleanup failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
