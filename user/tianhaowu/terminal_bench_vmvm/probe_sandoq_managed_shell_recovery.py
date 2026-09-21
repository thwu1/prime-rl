"""Task-free live check for long-Kimi managed-shell recovery.

The probe creates a disposable, digest-pinned utility container.  It either
deletes the managed shell explicitly or leaves it idle beyond the documented
TTL, then verifies that one ordinary command transparently replaces the
missing shell while preserving nested-container state.  No benchmark task or
model endpoint is accessed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sandoq_provider import registry
from sandoq_provider.oci_client import OCIRunnerAsyncSandboxClient
from terminal_bench_vmvm.sandoq_provider_context import (
    CONTEXT_RECEIPT,
    FIRECRACKER_ENVIRONMENT,
    ProviderContextError,
    _load_receipt,
    provider_context_is_active,
)

SCHEMA_VERSION = 2
DEFAULT_IMAGE = "docker.io/library/python@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9"
EXPECTED_PROVIDER_TOKEN_FILE = Path("/home/tianhaowu/.config/oci-runner/firecracker-token")
EXPECTED_PROVIDER_PROFILE_SHA256 = "53e0311216e1b27988b960a782188c5794ed941b9380cba1fbd0f29a67149a93"
EXPECTED_RUNTIME_SMOKE_SHA256 = "1e5d92d346894a0b8e29a1029278de4a0d4257a529862de87e8715f03dd152bf"
_DIGEST_IMAGE_RE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")


class RecoveryProbeError(RuntimeError):
    """Stable task-free probe failure."""


def _publish_private(path: Path, value: dict[str, object]) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if not path.is_absolute() or path.name != "managed-shell-recovery.json":
        raise RecoveryProbeError("probe_output_path_invalid")
    parent = path.parent
    try:
        canonical_parent = parent.resolve(strict=True)
        parent_metadata = parent.lstat()
    except OSError as error:
        raise RecoveryProbeError("probe_output_parent_invalid") from error
    if (
        canonical_parent != parent
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        or parent.is_symlink()
    ):
        raise RecoveryProbeError("probe_output_parent_invalid")
    descriptor = os.open(
        parent / path.name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


async def run_probe(
    *,
    mode: str,
    image: str,
    idle_seconds: int,
    output: Path,
    client: Any | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, object]:
    if mode not in {"forced-delete", "idle-endurance"}:
        raise RecoveryProbeError("probe_mode_invalid")
    if _DIGEST_IMAGE_RE.fullmatch(image) is None:
        raise RecoveryProbeError("probe_image_invalid")
    if (mode == "forced-delete" and idle_seconds != 0) or (mode == "idle-endurance" and idle_seconds < 3_900):
        raise RecoveryProbeError("probe_idle_budget_invalid")
    provider_token_file = Path(os.environ.get("OCI_RUNNER_TOKEN_FILE", ""))
    if (
        not provider_context_is_active(os.environ)
        or os.environ.get("SANDOQ_PROVIDER_CONTEXT_ACTIVE") != "1"
        or os.environ.get("OCI_RUNNER_ENVIRONMENT") != FIRECRACKER_ENVIRONMENT
        or os.environ.get("SANDOQ_EFFECTIVE_TASK_NETWORK") != "none"
        or os.environ.get("OCI_RUNNER_TASK_NETWORK") != "none"
        or os.environ.get("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK") != "0"
        or provider_token_file != EXPECTED_PROVIDER_TOKEN_FILE
        or os.environ.get("SANDOQ_PROVIDER_PROFILE_SHA256")
        != EXPECTED_PROVIDER_PROFILE_SHA256
        or os.environ.get("SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256")
        != EXPECTED_RUNTIME_SMOKE_SHA256
        or os.environ.get("SANDOQ_LEASE_PROFILE") != "kimi-tb4-long"
        or os.environ.get("OCI_RUNNER_LEASE_DURATION") != "12h"
        or os.environ.get("OCI_RUNNER_POOL_RENEW_INTERVAL") != "5m"
        or os.environ.get("OCI_RUNNER_MANAGED_SHELL_RECOVERY") != "1"
        or os.environ.get("OCI_RUNNER_POOL_SIZE") != "1"
    ):
        raise RecoveryProbeError("probe_provider_context_invalid")
    try:
        context_receipt = _load_receipt(Path(os.environ[CONTEXT_RECEIPT]))
    except (KeyError, OSError, ProviderContextError, ValueError) as error:
        raise RecoveryProbeError("probe_provider_context_invalid") from error
    if re.fullmatch(
        r"[0-9a-f]{64}",
        str(context_receipt.get("contract_sha256", "")),
    ) is None:
        raise RecoveryProbeError("probe_provider_context_invalid")

    sandbox_client = client or OCIRunnerAsyncSandboxClient()
    sandbox_id: str | None = None
    cleanup: dict[str, object] | None = None
    drain: dict[str, object] | None = None
    started = time.monotonic()
    failure: BaseException | None = None
    observation: dict[str, object] = {}
    try:
        request = SimpleNamespace(
            name="task-free-managed-shell-recovery",
            docker_image=image,
            environment_vars={"OCI_EXPECTED_WORKDIR": "/tmp"},
            start_command=None,
            cpu_cores=1,
            memory_gb=2,
            disk_size_gb=10,
        )
        sandbox = await sandbox_client.create(request, deadline=time.monotonic() + 3_600)
        sandbox_id = str(sandbox.id)
        await sandbox_client.wait_for_creation(sandbox_id)
        initial = await sandbox_client.execute_command(
            sandbox_id,
            "printf '%s' managed-shell-recovery > .managed-shell-recovery-state",
            working_dir="/tmp",
            timeout=30,
        )
        if initial.exit_code != 0:
            raise RecoveryProbeError("probe_state_setup_failed")
        info = registry.get(sandbox_id)
        if info is None or not info.shell_id or re.fullmatch(r"[A-Za-z0-9._-]{1,256}", info.shell_id) is None:
            raise RecoveryProbeError("probe_initial_shell_missing")
        prior_shell_id = info.shell_id
        if mode == "forced-delete":
            response = await sandbox_client._request_json(
                info,
                "DELETE",
                f"v1/shells/{prior_shell_id}",
                headers=sandbox_client._auth_headers(),
                timeout=30.0,
            )
            if response.status_code != 204:
                raise RecoveryProbeError("probe_forced_delete_failed")
        else:
            await sleep(float(idle_seconds))
        recovered = await sandbox_client.execute_command(
            sandbox_id,
            'test "$(cat .managed-shell-recovery-state)" = managed-shell-recovery',
            working_dir="/tmp",
            timeout=30,
        )
        metadata = await sandbox_client.session_metadata(sandbox_id)
        current = registry.get(sandbox_id)
        if (
            recovered.exit_code != 0
            or current is None
            or not current.shell_id
            or current.shell_id == prior_shell_id
            or metadata.get("managed_shell_recovery_count") != 1
        ):
            raise RecoveryProbeError("probe_recovery_not_observed")
        observation = {
            "shell_replaced": True,
            "managed_shell_recovery_count": 1,
            "state_preserved": True,
        }
    except BaseException as error:  # cleanup must run for cancellation and signals
        failure = error
        if sandbox_id is not None:
            try:
                await sandbox_client.poison_assignment(
                    sandbox_id,
                    reason="managed_shell_recovery_probe_failed",
                    shell_failure_status="managed_shell_recovery_probe_failed",
                )
            except Exception:
                pass
    finally:
        if sandbox_id is not None:
            try:
                cleanup = await sandbox_client.delete(sandbox_id, timeout=300)
            except BaseException as error:
                if failure is None:
                    failure = error
        try:
            drain = await sandbox_client.drain_pool()
        except BaseException as error:
            if failure is None:
                failure = error

    if failure is not None:
        raise RecoveryProbeError("probe_execution_failed") from failure
    if (
        cleanup is None
        or cleanup.get("nested_recycle_verified") is not True
        or cleanup.get("shell_deleted") is not True
        or cleanup.get("poisoned") is not False
        or cleanup.get("managed_shell_recovery_count") != 1
        or not isinstance(drain, dict)
        or drain.get("drained") is not True
        or drain.get("failures") != {}
    ):
        raise RecoveryProbeError("probe_cleanup_unverified")
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "state": "passed",
        "probe_kind": "task-free-managed-shell-recovery",
        "mode": mode,
        "idle_seconds": idle_seconds,
        "lease_profile": "kimi-tb4-long",
        "lease_duration": "12h",
        "renewal_interval": "5m",
        "recovery_policy": "definitive-404-410-single-replay-v1",
        "provider_environment": FIRECRACKER_ENVIRONMENT,
        "task_network": "none",
        "provider_token_file_path_sha256": hashlib.sha256(str(provider_token_file).encode()).hexdigest(),
        "provider_profile_sha256": EXPECTED_PROVIDER_PROFILE_SHA256,
        "runtime_smoke_receipt_sha256": EXPECTED_RUNTIME_SMOKE_SHA256,
        "provider_context_contract_sha256": context_receipt["contract_sha256"],
        "outer_cleanup_verified": True,
        "duration_seconds": round(time.monotonic() - started, 3),
        **observation,
    }
    _publish_private(output, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("forced-delete", "idle-endurance"), required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--idle-seconds", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        asyncio.run(
            run_probe(
                mode=args.mode,
                image=args.image,
                idle_seconds=args.idle_seconds,
                output=args.output,
            )
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        print('{"category":"managed_shell_recovery_probe_failed","state":"blocked"}', file=sys.stderr)
        return 2
    print('{"probe_kind":"task-free-managed-shell-recovery","state":"passed"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
