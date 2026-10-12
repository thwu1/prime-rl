#!/usr/bin/env python3
"""Task-free, cleanup-verified Sandoq Firecracker create availability probe."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
ENVIRONMENT = "oci-runner-firecracker"
LEASE_DURATION = "5m"
CREATE_DEADLINE_SECONDS = 120.0
DELETE_DEADLINE_SECONDS = 300.0
VERIFY_DEADLINE_SECONDS = 60.0
CLOSE_DEADLINE_SECONDS = 90.0
HARD_WALL_SECONDS = 660
VERIFY_POLL_SECONDS = 0.5

PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "SANDOQ_TUNNEL_HTTPS_PROXY",
)
FORBIDDEN_CREDENTIAL_ENVIRONMENT_NAMES = ("SANDOQ_AUTH_TOKEN", "FIRECRACKER_KEY")
RESULT_KEYS = frozenset(
    {
        "sdk_version",
        "transport_mode",
        "mtls_available",
        "create_state",
        "response_received",
        "session_returned",
        "cleanup_verified",
        "elapsed_seconds",
    }
)


class ProbeEnvironmentError(RuntimeError):
    """The probe was not launched in its narrow, credential-free context."""


@dataclass(frozen=True)
class SdkBindings:
    client_factory: Callable[[str], Any]
    not_found_exception: type[BaseException]
    connection_exception: type[BaseException]
    session_exception: type[BaseException]
    version: str


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

    def create_client(owner: str) -> Any:
        return client_type(BASE_URL, owner=owner, telemetry=NullSink())

    return SdkBindings(
        client_factory=create_client,
        not_found_exception=SandoqSessionNotFoundException,
        connection_exception=SandoqConnectionException,
        session_exception=SandoqSessionException,
        version=installed_version(),
    )


def _validate_environment(environment: Mapping[str, str]) -> str:
    job_id = environment.get("SLURM_JOB_ID", "")
    owner = environment.get("USER", "")
    if (
        re.fullmatch(r"[1-9][0-9]*", job_id) is None
        or re.fullmatch(r"[A-Za-z0-9._-]+", owner) is None
        or any(environment.get(name) for name in PROXY_ENVIRONMENT_NAMES)
        or any(environment.get(name) for name in FORBIDDEN_CREDENTIAL_ENVIRONMENT_NAMES)
    ):
        raise ProbeEnvironmentError("probe_environment_invalid")
    return f"{owner}-firecracker-create-availability"


def _empty_result(create_state: str, elapsed_seconds: float) -> dict[str, object]:
    return {
        "sdk_version": "unavailable",
        "transport_mode": "unknown",
        "mtls_available": False,
        "create_state": create_state,
        "response_received": False,
        "session_returned": False,
        "cleanup_verified": False,
        "elapsed_seconds": round(max(elapsed_seconds, 0.0), 3),
    }


async def _create_session(client: Any, request_id: str) -> Any:
    arguments: dict[str, object] = {
        "environment_name": ENVIRONMENT,
        "lease_duration": LEASE_DURATION,
        "request_id": request_id,
    }
    if "ready_timeout_seconds" in inspect.signature(client.create_session).parameters:
        arguments["ready_timeout_seconds"] = CREATE_DEADLINE_SECONDS
    async with asyncio.timeout(CREATE_DEADLINE_SECONDS):
        return await client.create_session(**arguments)


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

    deadline = asyncio.get_running_loop().time() + VERIFY_DEADLINE_SECONDS
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


async def run_probe(
    *,
    environment: Mapping[str, str] | None = None,
    bindings: SdkBindings | None = None,
    request_id_factory: Callable[[], object] = uuid.uuid4,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, object], bool]:
    started = monotonic()
    owner = _validate_environment(os.environ if environment is None else environment)
    sdk = bindings or _load_sdk()
    client = sdk.client_factory(owner)
    session: Any | None = None
    create_state = "unexpected_failure"
    response_received = False
    cleanup_verified = False
    close_verified = False

    try:
        http = client.http
        transport_mode = "proxy" if http.proxy_url else "direct"
        mtls_available = http.ssl_context is not None
        try:
            session = await _create_session(client, str(request_id_factory()))
        except TimeoutError:
            create_state = "timed_out"
        except sdk.connection_exception as error:
            create_state = "connection_failure"
            response_received = getattr(error, "response_received", None) is True
        except sdk.session_exception as error:
            create_state = "session_failure"
            response_received = getattr(error, "response_received", None) is True
        except asyncio.CancelledError:
            raise
        except BaseException:
            create_state = "unexpected_failure"
        else:
            create_state = "created"
            response_received = True
    finally:
        try:
            if session is not None:
                session_id = getattr(session, "session_id", None)
                if isinstance(session_id, str) and session_id:
                    cleanup_verified = await _delete_and_verify(
                        client,
                        session_id,
                        sdk.not_found_exception,
                    )
        finally:
            close_verified = await _close_client(client)

    result = {
        "sdk_version": sdk.version,
        "transport_mode": transport_mode,
        "mtls_available": mtls_available,
        "create_state": create_state,
        "response_received": response_received,
        "session_returned": session is not None,
        "cleanup_verified": cleanup_verified,
        "elapsed_seconds": round(max(monotonic() - started, 0.0), 3),
    }
    if set(result) != RESULT_KEYS:
        raise AssertionError("probe result schema changed")
    passed = create_state == "created" and cleanup_verified and close_verified
    return result, passed


def main() -> int:
    logging.disable(logging.CRITICAL)
    started = time.monotonic()

    async def bounded_probe() -> tuple[dict[str, object], bool]:
        async with asyncio.timeout(HARD_WALL_SECONDS):
            return await run_probe()

    try:
        result, passed = asyncio.run(bounded_probe())
    except ProbeEnvironmentError:
        result = _empty_result("environment_invalid", time.monotonic() - started)
        passed = False
    except TimeoutError:
        result = _empty_result("wall_deadline", time.monotonic() - started)
        passed = False
    except BaseException:
        result = _empty_result("probe_failure", time.monotonic() - started)
        passed = False
    print(json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
