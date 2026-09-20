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


def _recorded_outer_session_ids(output_dir: Path) -> list[str]:
    event_log = output_dir / "pool_events.jsonl"
    if not event_log.exists():
        return []
    session_ids: set[str] = set()
    with event_log.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise CleanupError("pool_event_log_invalid") from error
            session_id = row.get("outer_session_id")
            if isinstance(session_id, str) and session_id:
                session_ids.add(session_id)
    return sorted(session_ids)


def _publish_private(path: Path, value: object) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.urandom(16).hex()}")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
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

    session_ids = _recorded_outer_session_ids(output_dir)
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
            receipt["verified_http_status"] == 404 and not receipt["already_absent"]
            for receipt in receipts
        ),
        "verified_http_404": sum(
            receipt["verified_http_status"] == 404 for receipt in receipts
        ),
        "failures": failures,
        "receipts": receipts,
    }
    _publish_private(destination, audit)
    if failures:
        raise CleanupError("authoritative_cleanup_failed")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OCI_RUNNER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--owner",
        default=os.environ.get("SANDOQ_OWNER")
        or os.environ.get("OCI_RUNNER_OWNER")
        or os.environ.get("USER"),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("OCI_RUNNER_POOL_DRAIN_WORKERS", "16")),
    )
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
            )
        )
        print(
            "Sandoq cleanup passed "
            f"recorded={audit['recorded_outer_sessions']} "
            f"verified={audit['verified_http_404']}",
            flush=True,
        )
        return 0
    except (CleanupError, OSError, ValueError):
        print("Sandoq cleanup failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
