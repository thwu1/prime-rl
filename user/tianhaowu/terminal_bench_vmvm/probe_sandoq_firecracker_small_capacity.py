#!/usr/bin/env python3
"""Task-free, simultaneous Sandoq Firecracker-small lifecycle capacity soak."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import stat
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

ALLOWED_CONCURRENCIES = (24, 64)
ENVIRONMENT = "oci-runner-firecracker-small"
LEASE_DURATION = "10m"
CREATE_DEADLINE_SECONDS = 180.0
READY_VERIFY_DEADLINE_SECONDS = 30.0
DELETE_DEADLINE_SECONDS = 270.0
MISSING_VERIFY_DEADLINE_SECONDS = 60.0
CLOSE_DEADLINE_SECONDS = 90.0
HARD_WALL_SECONDS = 690
VERIFY_POLL_SECONDS = 0.5
MAX_PROFILE_BYTES = 4096
MAX_RECEIPT_BYTES = 16 * 1024

PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "SANDOQ_TUNNEL_HTTPS_PROXY",
)
FORBIDDEN_CREDENTIAL_ENVIRONMENT_NAMES = (
    "SANDOQ_AUTH_TOKEN",
    "FIRECRACKER_KEY",
    "OCI_RUNNER_TOKEN",
    "OCI_RUNNER_TOKEN_FILE",
)
EXPECTED_PROFILE = {
    "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
    "cluster_identifier": "use2",
    "effective_task_network": "public",
    "environment": ENVIRONMENT,
    "provider_token_file": "/home/tianhaowu/.config/oci-runner/firecracker-token",
    "schema_version": 3,
    "task_network": "host",
    "transport_mode": "auto",
}
RESULT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "state",
        "environment",
        "profile_sha256",
        "sdk_version",
        "transport_mode",
        "mtls_available",
        "requested_concurrency",
        "create_attempts",
        "sessions_returned",
        "simultaneous_ready_verified",
        "create_failure_counts",
        "delete_attempts",
        "typed_404_verified",
        "cleanup_failures",
        "client_close_verified",
        "elapsed_seconds",
        "slurm_job_id",
    }
)
CREATE_FAILURE_KEYS = (
    "connection_failure",
    "invalid_session",
    "session_failure",
    "timed_out",
    "unexpected_failure",
)

_T = TypeVar("_T")


class SoakError(RuntimeError):
    """The narrow soak contract or its launch environment is invalid."""


def _kind_for_concurrency(concurrency: int) -> str:
    if type(concurrency) is not int or concurrency not in ALLOWED_CONCURRENCIES:
        raise SoakError("concurrency_invalid")
    return f"sandoq-firecracker-small-c{concurrency}-soak"


@dataclass(frozen=True)
class ProviderProfile:
    base_url: str
    environment: str
    sha256: str


@dataclass(frozen=True)
class SdkBindings:
    client_factory: Callable[[str, str], Any]
    not_found_exception: type[BaseException]
    connection_exception: type[BaseException]
    session_exception: type[BaseException]
    version: str


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _load_profile(path: Path) -> ProviderProfile:
    if not path.is_absolute():
        raise SoakError("profile_invalid")
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as error:
        raise SoakError("profile_invalid") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or len(raw) > MAX_PROFILE_BYTES:
        raise SoakError("profile_invalid")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SoakError("profile_invalid") from error
    if value != EXPECTED_PROFILE:
        raise SoakError("profile_invalid")
    return ProviderProfile(
        base_url=value["base_url"],
        environment=value["environment"],
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _load_sdk() -> SdkBindings:
    from sandoq_client import (
        SandoqClient,
        SandoqConnectionException,
        SandoqSessionException,
        SandoqSessionNotFoundException,
    )
    from sandoq_client._version import installed_version
    from sandoq_client.telemetry import NullSink
    from sandoq_provider.gateway import _creation_retry_client_type

    client_type = _creation_retry_client_type(SandoqClient)

    def create_client(base_url: str, owner: str) -> Any:
        return client_type(base_url, owner=owner, telemetry=NullSink())

    return SdkBindings(
        client_factory=create_client,
        not_found_exception=SandoqSessionNotFoundException,
        connection_exception=SandoqConnectionException,
        session_exception=SandoqSessionException,
        version=installed_version(),
    )


def _validate_environment(environment: Mapping[str, str]) -> tuple[str, str]:
    job_id = environment.get("SLURM_JOB_ID", "")
    owner = environment.get("USER", "")
    if (
        re.fullmatch(r"[1-9][0-9]*", job_id) is None
        or re.fullmatch(r"[A-Za-z0-9._-]+", owner) is None
        or any(environment.get(name) for name in PROXY_ENVIRONMENT_NAMES)
        or any(environment.get(name) for name in FORBIDDEN_CREDENTIAL_ENVIRONMENT_NAMES)
    ):
        raise SoakError("probe_environment_invalid")
    return job_id, owner


def _session_id(session: Any) -> str | None:
    value = getattr(session, "session_id", None)
    return value if isinstance(value, str) and value else None


def _ready_status(session: Any) -> bool:
    status = getattr(session, "status", None)
    return status is None or getattr(status, "value", None) == "ready"


async def _create_session(client: Any, profile: ProviderProfile, request_id: str) -> Any:
    async with asyncio.timeout(CREATE_DEADLINE_SECONDS):
        return await client.create_session(
            environment_name=profile.environment,
            lease_duration=LEASE_DURATION,
            request_id=request_id,
            ready_timeout_seconds=CREATE_DEADLINE_SECONDS,
        )


async def _verify_ready(client: Any, session_id: str) -> bool:
    try:
        async with asyncio.timeout(READY_VERIFY_DEADLINE_SECONDS):
            observed = await client.get_session(session_id)
    except asyncio.CancelledError:
        raise
    except BaseException:
        return False
    return _session_id(observed) == session_id and _ready_status(observed)


async def _delete_and_verify(
    client: Any,
    session_id: str,
    not_found_exception: type[BaseException],
) -> bool:
    try:
        async with asyncio.timeout(DELETE_DEADLINE_SECONDS):
            await client.delete_session(session_id)
    except asyncio.CancelledError:
        raise
    except BaseException:
        return False

    deadline = asyncio.get_running_loop().time() + MISSING_VERIFY_DEADLINE_SECONDS
    while True:
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            async with asyncio.timeout(remaining):
                await client.get_session(session_id)
        except not_found_exception:
            return True
        except asyncio.CancelledError:
            raise
        except BaseException:
            pass
        await asyncio.sleep(min(VERIFY_POLL_SECONDS, max(deadline - asyncio.get_running_loop().time(), 0.0)))


async def _close_client(client: Any) -> bool:
    try:
        async with asyncio.timeout(CLOSE_DEADLINE_SECONDS):
            await client.close()
    except asyncio.CancelledError:
        raise
    except BaseException:
        return False
    return True


async def _finish_despite_cancellation(
    operation: Awaitable[_T],
) -> tuple[_T, asyncio.CancelledError | None]:
    future = asyncio.ensure_future(operation)
    interrupted: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.shield(future), interrupted
        except asyncio.CancelledError as error:
            if interrupted is None:
                interrupted = error
            if future.done():
                return future.result(), interrupted


def _collect_sessions(tasks: Sequence[asyncio.Task[Any]]) -> dict[str, Any]:
    sessions: dict[str, Any] = {}
    for task in tasks:
        if not task.done() or task.cancelled():
            continue
        try:
            session = task.result()
        except BaseException:
            continue
        session_id = _session_id(session)
        if session_id is not None:
            sessions.setdefault(session_id, session)
    return sessions


def _create_failure_counts(
    tasks: Sequence[asyncio.Task[Any]],
    bindings: SdkBindings,
) -> dict[str, int]:
    counts = dict.fromkeys(CREATE_FAILURE_KEYS, 0)
    for task in tasks:
        if task.cancelled():
            counts["unexpected_failure"] += 1
            continue
        try:
            session = task.result()
        except TimeoutError:
            counts["timed_out"] += 1
        except bindings.connection_exception:
            counts["connection_failure"] += 1
        except bindings.session_exception:
            counts["session_failure"] += 1
        except BaseException:
            counts["unexpected_failure"] += 1
        else:
            if _session_id(session) is None or not _ready_status(session):
                counts["invalid_session"] += 1
    return counts


async def run_soak(
    *,
    profile: ProviderProfile,
    concurrency: int,
    environment: Mapping[str, str] | None = None,
    bindings: SdkBindings | None = None,
    request_id_factory: Callable[[], object] = uuid.uuid4,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, object], bool]:
    started = monotonic()
    kind = _kind_for_concurrency(concurrency)
    job_id, user = _validate_environment(os.environ if environment is None else environment)
    owner = f"{user}-firecracker-small-c{concurrency}-soak"
    sdk = bindings or _load_sdk()
    client = sdk.client_factory(profile.base_url, owner)
    transport_mode = "proxy" if client.http.proxy_url else "direct"
    mtls_available = client.http.ssl_context is not None
    create_tasks: list[asyncio.Task[Any]] = []
    ready_tasks: list[asyncio.Task[bool]] = []
    ready_results: list[bool] = []
    cleanup_results: list[bool] = []
    close_verified = False
    interrupted: asyncio.CancelledError | None = None

    try:
        create_tasks = [
            asyncio.create_task(_create_session(client, profile, str(request_id_factory()))) for _ in range(concurrency)
        ]
        try:
            await asyncio.gather(*create_tasks, return_exceptions=True)
            sessions = _collect_sessions(create_tasks)
            ready_tasks = [asyncio.create_task(_verify_ready(client, session_id)) for session_id in sessions]
            ready_results = list(await asyncio.gather(*ready_tasks))
        except asyncio.CancelledError as error:
            interrupted = error
    finally:
        for task in (*create_tasks, *ready_tasks):
            if not task.done():
                task.cancel()
        if create_tasks or ready_tasks:
            _, settle_interruption = await _finish_despite_cancellation(
                asyncio.gather(*create_tasks, *ready_tasks, return_exceptions=True)
            )
            interrupted = interrupted or settle_interruption

        sessions = _collect_sessions(create_tasks)
        cleanup_results, cleanup_interruption = await _finish_despite_cancellation(
            asyncio.gather(
                *(_delete_and_verify(client, session_id, sdk.not_found_exception) for session_id in sessions)
            )
        )
        interrupted = interrupted or cleanup_interruption
        close_verified, close_interruption = await _finish_despite_cancellation(_close_client(client))
        interrupted = interrupted or close_interruption

    if interrupted is not None:
        raise interrupted

    sessions = _collect_sessions(create_tasks)
    failure_counts = _create_failure_counts(create_tasks, sdk)
    ready_count = sum(result is True for result in ready_results)
    cleanup_count = sum(result is True for result in cleanup_results)
    passed = (
        len(create_tasks) == concurrency
        and len(sessions) == concurrency
        and ready_count == concurrency
        and not any(failure_counts.values())
        and len(cleanup_results) == concurrency
        and cleanup_count == concurrency
        and close_verified
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "kind": kind,
        "state": "passed" if passed else "unavailable",
        "environment": profile.environment,
        "profile_sha256": profile.sha256,
        "sdk_version": sdk.version,
        "transport_mode": transport_mode,
        "mtls_available": mtls_available,
        "requested_concurrency": concurrency,
        "create_attempts": len(create_tasks),
        "sessions_returned": len(sessions),
        "simultaneous_ready_verified": ready_count,
        "create_failure_counts": failure_counts,
        "delete_attempts": len(cleanup_results),
        "typed_404_verified": cleanup_count,
        "cleanup_failures": len(cleanup_results) - cleanup_count,
        "client_close_verified": close_verified,
        "elapsed_seconds": round(max(monotonic() - started, 0.0), 3),
        "slurm_job_id": job_id,
    }
    if set(result) != RESULT_KEYS:
        raise AssertionError("soak result schema changed")
    return result, passed


def _publish_private(path: Path, value: Mapping[str, object]) -> None:
    body = _canonical_json(value)
    if len(body) > MAX_RECEIPT_BYTES or path.name != "receipt.json" or not path.is_absolute():
        raise SoakError("probe_output_invalid")
    try:
        parent = path.parent.resolve(strict=True)
        metadata = path.parent.lstat()
    except OSError as error:
        raise SoakError("probe_output_invalid") from error
    if (
        parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or os.path.lexists(path)
    ):
        raise SoakError("probe_output_invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, choices=ALLOWED_CONCURRENCIES, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.disable(logging.CRITICAL)
    args = _parser().parse_args(argv)
    kind = _kind_for_concurrency(args.concurrency)
    try:
        profile = _load_profile(args.profile)

        async def bounded_soak() -> tuple[dict[str, object], bool]:
            async with asyncio.timeout(HARD_WALL_SECONDS):
                return await run_soak(profile=profile, concurrency=args.concurrency)

        result, passed = asyncio.run(bounded_soak())
        _publish_private(args.output, result)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        print(f'{{"kind":"{kind}","state":"blocked"}}', file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "kind": kind,
                "receipt_sha256": hashlib.sha256(_canonical_json(result)).hexdigest(),
                "state": result["state"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
