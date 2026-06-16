# Copyright (c) Meta Platforms, Inc. and affiliates.

"""vacli-based ToolBackend, side-by-side with the existing DES-backed VMVMBackend.

The DES backend (apps/rl/utils/container_backends/vmvm_backend.py) talks to the
cluster's VMVM pool via `des_exec_cloud`, which inlines every command argument
into argv. That bounds file transfer to ~128 KiB (Linux `MAX_ARG_STRLEN`) and
forces a fresh process per call. This backend leases the same VMVM pool via
`vacli` instead, exposes the VM over an SSH x2p tunnel, and runs every call
through a persistent SSH master connection. Transfers stream over stdin via
`tar`, so file size is bounded only by VM disk.

Drop-in compatibility: `VacliVMVMBackend` and `VacliVMVMBackend_NoServer`
implement the same `ToolBackend` Protocol (and the same concrete
`transfer_file(content, remote_path)` method that `paperbench_dev._SandboxBackend`
relies on) as their DES siblings. Nothing in `vmvm_backend.py`, `des_helper.py`,
or any env code is modified by importing this module.

Memory references this module honors:
- [[vmvm-transport-tar-wins]] — file transfers use tar+ssh, not rsync/scp.
- [[vacli-coreweave-stderr-noise]] — vacli/podman emit ODS telemetry on stderr
  on success; we check exit code only, never stderr content, when deciding
  success/failure of an operation.
- [[vmvm-transfer-arg-max-limit]] — the DES limit this backend exists to escape.
"""

from __future__ import annotations

import asyncio
import atexit
import io
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .types import BackendInitError, BashResult
from .session import AsyncSession, SessionOutput

logger = logging.getLogger(__name__)


VACLI_BIN = "/public/fbpkgs/x86_64/vacli/latest/vacli"
DEFAULT_TENANT = "async_2347641"
DEFAULT_LEASE_TTL = "500s"
DEFAULT_TUNNEL_READY_TIMEOUT = (
    120.0  # seconds to wait for vacli to print tunnel mapping
)
DEFAULT_SSHD_READY_TIMEOUT = 180.0  # seconds to wait for sshd inside the leased VM
DEFAULT_VACLI_CLEANUP_TIMEOUT = (
    30.0  # seconds to wait for vacli to release before SIGKILL
)

# Cap concurrent in-flight vacli leases per process: bursts of simultaneous
# lease attempts trigger FAAS tunnel-setup timeouts. Tune via env if needed.
MAX_CONCURRENT_LEASES = int(os.environ.get("VACLI_MAX_CONCURRENT_LEASES", "16"))
# Retries for `podman pull` inside the VM when DockerHub returns 429
# (toomanyrequests). The vmvm-registry mirror path needs no retries; this only
# matters for the docker.io fallback used when an image is not yet mirrored.
MAX_PULL_RETRIES = int(os.environ.get("VACLI_MAX_PULL_RETRIES", "10"))
# Retries for the vacli lease bring-up itself. Concurrent launches race on
# Configerator/JustKnobs init ("isConfigeratorAvailable() returned false" ->
# "vacli died before tunnel was ready"), a transient thundering-herd failure at
# high concurrency; jittered retry disperses the herd. See [[vacli-lease-race]].
MAX_LEASE_RETRIES = int(os.environ.get("VACLI_LEASE_RETRIES", "4"))


_THREADED_CHILD_WATCHER = None


def _install_threaded_child_watcher() -> None:
    """Make asyncio.get_child_watcher() return a stdlib ThreadedChildWatcher.

    prime-rl installs uvloop as the global policy. uvloop's policy.get_child_watcher()
    raises NotImplementedError, so a stdlib SelectorEventLoop (which we use for the
    session loops) cannot spawn subprocesses (_make_subprocess_transport calls the
    global get_child_watcher()). ThreadedChildWatcher is loop-agnostic and thread-safe
    (one waiter thread per child), so it drives our SelectorEventLoops at high
    concurrency. uvloop's own loops never call get_child_watcher(), so this is a
    no-op for them. Idempotent; installed once.
    """
    global _THREADED_CHILD_WATCHER
    if _THREADED_CHILD_WATCHER is not None:
        return
    _THREADED_CHILD_WATCHER = asyncio.ThreadedChildWatcher()

    def _get_watcher():
        return _THREADED_CHILD_WATCHER

    asyncio.events.get_child_watcher = _get_watcher
    asyncio.get_child_watcher = _get_watcher
_lease_concurrency = threading.BoundedSemaphore(MAX_CONCURRENT_LEASES)

# Tunnel mapping line emitted by vacli on stdout, e.g.:
# [{"vm_port":22,"local_port":10000}]
_TUNNEL_RE = re.compile(r'\[\s*\{[^]]*"vm_port"\s*:\s*22[^]]*\}\s*\]')

# Container IDs come from parsing untrusted stdout (podman over ssh); we
# interpolate them into shell commands below, so reject anything that isn't
# the expected hex form before storing.
_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")


def _validate_container_id(cid: str) -> str:
    if not _CONTAINER_ID_RE.match(cid):
        raise BackendInitError(
            f"podman returned malformed container id (expected hex): {cid!r}"
        )
    return cid


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VacliVMVMConfig:
    """Configuration for `VacliVMVMBackend` (server-backed equivalent of `VMVMConfig`).

    `image_url` is required to match `VMVMConfig`'s shape — a bare-VM variant
    (no podman, ssh directly) could be added later without breaking this signature.
    """

    image_url: str
    work_dir: str
    session_timeout: float
    # Secondary image tried if `image_url` fails to pull (docker.io fallback
    # for tasks not mirrored into vmvm-registry).
    fallback_image_url: str | None = None
    start_script: str = ""
    entrypoint_script: str = ""
    tenant_id: str = DEFAULT_TENANT
    lease_ttl: str = DEFAULT_LEASE_TTL
    tunnel_ready_timeout: float = DEFAULT_TUNNEL_READY_TIMEOUT
    sshd_ready_timeout: float = DEFAULT_SSHD_READY_TIMEOUT
    client_id: str = "cwm_rl"
    # Override the AsyncSession per-command stdout buffer cap (bytes). None
    # means use the AsyncSession default (480 KB). Bump this for callers that
    # legitimately need to read large bash outputs in one call — e.g.
    # paperbench_dev streams its submission tarball through `tar | base64` and
    # easily exceeds 480 KB for larger submissions. Setting this here doesn't
    # affect any other AsyncSession user (the cap is per-instance).
    max_session_buffer_size: int | None = None
    # Test seam: lets unit tests inject a stub `subprocess`-shaped namespace
    # (must expose `Popen`, `run`, `PIPE`, `DEVNULL`, `STDOUT`, `TimeoutExpired`)
    # so we never spawn real vacli/ssh. Production: leave None → real subprocess.
    subprocess_mod: Any = None


# ---------------------------------------------------------------------------
# Lease + SSH helpers — small, reusable, easy to stub
# ---------------------------------------------------------------------------


class VacliLease:
    """Background `vacli` process holding a VMVM lease + an x2p SSH tunnel.

    Lifecycle:
      lease = VacliLease(tenant, log_path, subprocess_mod=...)
      lease.start()                  # spawns vacli; non-blocking
      port = lease.wait_for_tunnel() # blocks until JSON tunnel mapping appears
      ...
      lease.cleanup()                # SIGTERM → vacli's --release-on-exit fires

    `cleanup()` is registered with `atexit` at construction so an unhandled
    exception still releases the VM.
    """

    def __init__(
        self,
        tenant_id: str,
        log_path: Path,
        *,
        lease_ttl: str = DEFAULT_LEASE_TTL,
        tunnel_ready_timeout: float = DEFAULT_TUNNEL_READY_TIMEOUT,
        cleanup_timeout: float = DEFAULT_VACLI_CLEANUP_TIMEOUT,
        subprocess_mod: Any = None,
        image_url: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.log_path = log_path
        self.lease_ttl = lease_ttl
        self.tunnel_ready_timeout = tunnel_ready_timeout
        self.cleanup_timeout = cleanup_timeout
        self._sp = subprocess_mod or subprocess
        self._image_url = image_url
        self.proc: Any = None
        self.ssh_port: int | None = None
        self._cleaned_up = False
        self._concurrency_held = False
        atexit.register(self.cleanup)

    def start(self) -> None:
        _lease_concurrency.acquire()
        self._concurrency_held = True
        cmd = [
            "stdbuf",
            "-oL",
            VACLI_BIN,
            "--x2p",
            "--faas-tenant-id",
            self.tenant_id,
            "lease",
            "--ttl",
            self.lease_ttl,
            "--auto-renew",
            "--tunnel-ports",
            "22",
            "--release-on-exit",
        ]
        # NOTE: image pre-pull via --tier-overrides removed; podman pull
        # inside the VM uses vmvm-registry.fbinfra.net mirror instead.
        logger.info(
            f"vacli: leasing VMVM (tenant={self.tenant_id}); log={self.log_path}"
        )
        try:
            # `with open(...)` closes the parent's fd after Popen returns;
            # the child has already inherited its own dup'd copy via Popen
            # (stdout=log_fh), so closing here is safe and avoids holding
            # one fd open per lease for the backend's lifetime.
            with open(self.log_path, "wb") as log_fh:
                # New process group via `process_group=0` (added in Python 3.11):
                # a Ctrl-C in our terminal doesn't go straight to vacli; we want
                # to SIGTERM it ourselves so cleanup is ordered. Prefer this over
                # `preexec_fn=os.setsid` because preexec_fn runs in the forked
                # child between fork() and exec() and is not safe in multi-
                # threaded processes (we are).
                self.proc = self._sp.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=self._sp.STDOUT,
                    process_group=0,
                )
        except Exception:
            self._release_concurrency_slot()
            raise

    def wait_for_tunnel(self) -> int:
        """Poll the vacli log for the tunnel mapping; return the local port for vm_port=22.

        Per [[vacli-coreweave-stderr-noise]]: we look at stdout content, not
        exit code or stderr. The success signal is the JSON tunnel mapping
        being printed to stdout.
        """
        if self.proc is None:
            raise BackendInitError("vacli lease never started; call .start() first")
        try:
            deadline = time.time() + self.tunnel_ready_timeout
            while time.time() < deadline:
                # If vacli died, the lease is gone; surface a useful tail.
                if self.proc.poll() is not None:
                    tail = self._log_tail(20)
                    raise BackendInitError(
                        f"vacli died before tunnel was ready (exit {self.proc.returncode}). "
                        f"Tail of log:\n{tail}"
                    )
                try:
                    text = self.log_path.read_text(errors="replace")
                except FileNotFoundError:
                    text = ""
                for match in _TUNNEL_RE.finditer(text):
                    try:
                        tunnels = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        continue
                    for t in tunnels:
                        if t.get("vm_port") == 22:
                            self.ssh_port = int(t["local_port"])
                            logger.info(
                                f"vacli: tunnel ready, ssh port = {self.ssh_port}"
                            )
                            return self.ssh_port
                time.sleep(1)
            raise BackendInitError(
                f"vacli never printed tunnel mapping in {self.tunnel_ready_timeout}s. "
                f"Tail of log:\n{self._log_tail(30)}"
            )
        finally:
            self._release_concurrency_slot()

    def cleanup(self) -> None:
        if self._cleaned_up or self.proc is None or self.proc.poll() is not None:
            self._cleaned_up = True
            self._release_concurrency_slot()
            return
        self._cleaned_up = True
        logger.info("vacli: SIGTERM — releasing lease (--release-on-exit)")
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=self.cleanup_timeout)
        except self._sp.TimeoutExpired:
            logger.warning(
                f"vacli: alive after {self.cleanup_timeout}s; SIGKILL "
                f"(lease will expire via TTL)"
            )
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        # Defensive: release if start() succeeded but wait_for_tunnel never ran.
        self._release_concurrency_slot()

    def _release_concurrency_slot(self) -> None:
        """Release the `_lease_concurrency` slot if held. Idempotent."""
        if self._concurrency_held:
            self._concurrency_held = False
            try:
                _lease_concurrency.release()
            except ValueError:
                pass

    def _log_tail(self, n: int) -> str:
        try:
            lines = self.log_path.read_text(errors="replace").splitlines()
        except FileNotFoundError:
            return "(log file not found)"
        return "\n".join("  " + ln for ln in lines[-n:])


def _ssh_opts(
    port: int,
    control_path: str | None = None,
    *,
    connect_timeout: int = 5,
) -> list[str]:
    """Build the ssh argv prefix for a vacli x2p tunnel target.

    When `control_path` is set, enable ControlMaster=auto so subsequent
    `run_bash` calls reuse the same TCP+auth handshake. Each VM has a fresh
    host key (no point persisting it in known_hosts).
    """
    args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        # Keep the tunnel alive during long agent think times: ssh-level
        # heartbeats every 30s defeat NAT/firewall idle teardown and let us
        # detect a dead connection within ~90s instead of hanging in read.
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-p",
        str(port),
    ]
    if control_path is not None:
        args += [
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={control_path}",
            "-o",
            "ControlPersist=600",
        ]
    return args


def _wait_for_sshd(
    port: int,
    *,
    timeout: float,
    control_path: str | None = None,
    subprocess_mod: Any = None,
) -> None:
    """Poll `ssh root@localhost true` until it returns 0 or `timeout` elapses."""
    sp = subprocess_mod or subprocess
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc = sp.run(
            _ssh_opts(port, control_path) + ["root@localhost", "true"],
            stdin=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        ).returncode
        if rc == 0:
            return
        time.sleep(1)
    raise BackendInitError(f"sshd not ready on port {port} after {timeout}s")


def _bash_result(
    status: Literal["success", "error"],
    output: str,
    error_type: Literal[
        "none", "timeout", "too_long", "exit", "broken_pipe", "other"
    ] = "none",
    exit_code: int = 0,
) -> BashResult:
    """Build a BashResult TypedDict in the shape both backends already use.

    `exit_code` is required by downstream consumers (tool_types.make_python_plugin,
    swerl/tools.py, swerl/eval_backend/eval.py) which index `bash_result["exit_code"]`
    directly. Use -1 for cases where we don't have a real shell exit code
    (timeout, broken pipe, backend-internal errors) — matches the DES convention.
    """
    return BashResult(
        status=status, output=output, error_type=error_type, exit_code=exit_code
    )


def _pull_image_in_vm(sp, ssh_port, control_path, image):
    """Pull `image` inside the leased VM through a *login* shell.

    A login shell (`bash -l`) is required so /etc/profile.d/http_proxy.sh is
    sourced -- a non-login `ssh host cmd` shell does NOT inherit the VM's
    HTTP(S)_PROXY env, which podman needs to reach docker.io. Retries on
    DockerHub 429 (toomanyrequests); the vmvm-registry mirror succeeds on the
    first attempt so retries only bite the docker.io fallback.
    Returns (ok, last_output)."""
    inner = "podman pull --quiet=false " + shlex.quote(image)
    remote = "bash -l -c " + shlex.quote(inner)
    last = ""
    for attempt in range(MAX_PULL_RETRIES):
        r = sp.run(
            _ssh_opts(ssh_port, control_path) + ["root@localhost", remote],
            stdin=sp.DEVNULL,
            stdout=sp.PIPE,
            stderr=sp.STDOUT,
            timeout=350,
        )
        last = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
        if r.returncode == 0:
            return True, last
        # Retry ANY transient pull failure (rate-limit AND blob-copy/network drops,
        # which are common at high concurrency), not just 429. Longer backoff for
        # rate-limit; shorter for other transient errors.
        if attempt < MAX_PULL_RETRIES - 1:
            import random as _rnd
            rate_limited = "toomanyrequests" in last
            base = min(15 * (attempt + 1), 90) if rate_limited else min(5 * (attempt + 1), 30)
            wait = base + _rnd.uniform(0.0, base)  # jitter: disperse the 80-VM pull herd
            logger.warning(
                f"vacli: podman pull failed for {image} "
                f"(attempt {attempt + 1}/{MAX_PULL_RETRIES}, rate_limited={rate_limited}), "
                f"retrying in {wait}s"
            )
            time.sleep(wait)
            continue
        return False, last
    return False, last


def _resolve_image_in_vm(sp, ssh_port, control_path, primary, fallback=None):
    """Pull `primary`, then `fallback` if given, returning the ref that worked.
    Raises BackendInitError if every candidate fails."""
    candidates = [primary]
    if fallback and fallback != primary:
        candidates.append(fallback)
    last_out = ""
    for img in candidates:
        ok, last_out = _pull_image_in_vm(sp, ssh_port, control_path, img)
        if ok:
            return img
        logger.warning(f"vacli: pull failed for {img}; trying next candidate")
    raise BackendInitError(
        f"podman pull failed for all candidates {candidates}: {last_out[-800:]!r}"
    )


def _ensure_python_in_container(sp, ssh_port, control_path, cid):
    """Symlink `python` -> python3 inside the container if absent.

    Matches DES VMVMBackend.prepare_server_container, which creates
    /usr/local/bin/python so the agent's `python ...` commands work. Without
    this, vacli's container only has `python3` and bare `python` exits 127 --
    a behavioral mismatch vs the DES baseline. Best-effort / non-fatal."""
    script = (
        "if ! command -v python >/dev/null 2>&1 && "
        "command -v python3 >/dev/null 2>&1; then "
        'ln -sf "$(command -v python3)" /usr/local/bin/python 2>/dev/null || '
        'ln -sf "$(command -v python3)" /tmp/python 2>/dev/null; fi'
    )
    remote = "podman exec " + cid + " bash -lc " + shlex.quote(script)
    try:
        sp.run(
            _ssh_opts(ssh_port, control_path) + ["root@localhost", remote],
            stdin=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
            timeout=60,
        )
    except Exception:
        logger.warning("vacli: ensure-python symlink step failed (non-fatal)")


def _setup_bridge_proxy(sp, ssh_port, control_path, cid):
    """For a `--network bridge` container: detect the bridge gateway and write
    the egress proxy (now reachable at gateway:8080, not 0.0.0.0:8080) into
    /etc/profile.d so `bash -l` paths (e.g. test exec) get egress. Returns the
    gateway IP so the persistent (non-login) session can export it too. The
    container inherits http_proxy=0.0.0.0:8080 from the host, which is wrong once
    it has its own netns; gateway:8080 routes back to the host socat proxy.
    Best-effort; returns gateway IP (default 10.88.0.1)."""
    gw = "10.88.0.1"
    try:
        r = sp.run(
            _ssh_opts(ssh_port, control_path)
            + ["root@localhost", "podman exec " + cid + " ip route"],
            stdin=sp.DEVNULL, stdout=sp.PIPE, stderr=sp.DEVNULL, timeout=30,
        )
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            f = line.split()
            if f[:1] == ["default"] and "via" in f:
                gw = f[f.index("via") + 1]
                break
    except Exception:
        logger.warning("vacli: bridge gateway detection failed; using 10.88.0.1")
    exports = "".join(
        "export %s=http://%s:8080\n" % (k, gw)
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
    )
    exports += "export HF_HUB_DISABLE_XET=1\nexport HF_XET_DISABLE=1\n"
    script = "cat > /etc/profile.d/zz_vacli_proxy.sh <<\x27VACLIEOF\x27\n" + exports + "VACLIEOF\n"
    remote = "podman exec -i " + cid + " sh -c " + shlex.quote(script)
    try:
        sp.run(
            _ssh_opts(ssh_port, control_path) + ["root@localhost", remote],
            stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=30,
        )
    except Exception:
        logger.warning("vacli: writing container proxy profile failed (non-fatal)")
    return gw


# ---------------------------------------------------------------------------
# Persistent-shell adapter
# ---------------------------------------------------------------------------


class VacliSession:
    """Sync wrapper around `AsyncSession` running on a private event-loop thread.

    The DES backend gets its persistent-shell semantics by running `AsyncSession`
    inside a python server on the VM and talking to it over TCP. We don't run
    such a server, so `AsyncSession` runs in our own process and we bridge its
    asyncio API to the sync `ToolBackend.run_bash` surface here.

    Lifetime:
      - `__init__` spawns a daemon thread running a private event loop. Daemon
        so a caller who forgets `stop()` doesn't hang interpreter shutdown.
      - `start()` launches the underlying bash subprocess on that loop. The
        process is loop-bound (`asyncio.subprocess.Process`), which is why the
        loop has to outlive every `communicate()` call.
      - `stop()` is the primary cleanup path: cancels the AsyncSession, stops
        the loop, joins the thread. The daemon flag is only a fallback.
    """

    def __init__(
        self,
        command_args: list[str],
        timeout: float,
        start_script: str | None = None,
        max_buffer_size: int | None = None,
    ) -> None:
        # Force the stdlib selector loop (NOT uvloop): prime-rl installs uvloop
        # globally, and many uvloop loops spawning subprocesses concurrently race
        # on uvloop's process-global child watcher ('Racing with another loop to
        # spawn a process') at high concurrency. SelectorEventLoop uses the
        # thread-safe ThreadedChildWatcher, so 128+ concurrent leases spawn cleanly.
        _install_threaded_child_watcher()
        self._loop = asyncio.SelectorEventLoop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="vacli-session-loop"
        )
        self._thread.start()
        # AsyncSession must be constructed on the loop's thread because it
        # creates asyncio primitives (Locks, Futures) bound to the running loop.
        self._session: AsyncSession = self._submit(
            self._construct_session(
                command_args, timeout, start_script, max_buffer_size
            )
        )
        self._stopped = False

    @staticmethod
    async def _construct_session(
        command_args: list[str],
        timeout: float,
        start_script: str | None,
        max_buffer_size: int | None,
    ) -> AsyncSession:
        kwargs: dict[str, Any] = {
            "command_args": command_args,
            "timeout": timeout,
            "start_script": start_script,
        }
        if max_buffer_size is not None:
            kwargs["max_buffer_size"] = max_buffer_size
        return AsyncSession(**kwargs)

    def start(self) -> None:
        self._submit(self._session.start())

    def communicate(self, command: str, timeout: "float | None" = None) -> SessionOutput:
        return self._submit(self._session.communicate(command, timeout=timeout))

    def get_exitcode(self) -> int | None:
        return self._submit(self._session.get_exitcode())

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        # AsyncSession.stop() is sync but touches the loop-owned subprocess;
        # call it from the loop thread to avoid cross-thread proc handling.
        try:
            self._submit(self._stop_session_async())
        except Exception:
            logger.exception("vacli session: error stopping AsyncSession")
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        try:
            self._loop.close()
        except Exception:
            pass

    async def _stop_session_async(self) -> None:
        self._session.stop()

    def _submit(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


# ---------------------------------------------------------------------------
# Backend classes
# ---------------------------------------------------------------------------


class VacliVMVMBackend:
    """vacli-backed equivalent of `VMVMBackend` with a persistent shell.

    Each instance:
      1. Leases a VMVM via vacli (--release-on-exit + atexit safety net).
      2. Opens a long-lived SSH master connection via ControlMaster=auto.
      3. Pulls + runs a podman container for `image_url`.
      4. Runs all subsequent `run_bash` calls inside the container, reusing
         the SSH master so handshake cost is paid once.

    "Persistent shell" here means: a stable container (pid namespace, cwd,
    env vars set inside `start_script` persist), not a single bash process.
    The DES `VMVMBackend` keeps a single AsyncSession process; this one
    keeps a single container. Both preserve per-call state for callers that
    depend on `cd …` / `export …` semantics across calls.
    """

    def __init__(self, config: VacliVMVMConfig) -> None:
        self.config = config
        self._sp = config.subprocess_mod or subprocess
        self.init_start_time = time.perf_counter()
        self._destroyed = False
        # Random nonces keep multiple backends on the same host from sharing
        # ssh control sockets / vacli log files.
        nonce = uuid.uuid4().hex[:8]
        tmp = Path(tempfile.gettempdir())
        self._control_path = str(tmp / f"vacli_ctl_{os.getpid()}_{nonce}")
        self._vacli_log = tmp / f"vacli_lease_{os.getpid()}_{nonce}.log"

        self._lease = VacliLease(
            tenant_id=config.tenant_id,
            log_path=self._vacli_log,
            lease_ttl=config.lease_ttl,
            tunnel_ready_timeout=config.tunnel_ready_timeout,
            subprocess_mod=config.subprocess_mod,
        )
        self._container_id: str | None = None
        self._session: VacliSession | None = None
        try:
            # Retry lease bring-up with jittered backoff: concurrent launches
            # race on Configerator init -> "vacli died before tunnel was ready"
            # (transient). Fresh lease each attempt (old proc already died).
            import random as _random
            for _attempt in range(MAX_LEASE_RETRIES):
                try:
                    self._lease.start()
                    self._ssh_port = self._lease.wait_for_tunnel()
                    # Full bring-up inside the retry envelope: sshd readiness and
                    # container pull/start are the ssh-dependent steps that saturate
                    # under high concurrency (the dominant env_error cause). A failure
                    # here abandons this VM and re-leases a FRESH one rather than
                    # failing the rollout. Previously these two steps were outside the
                    # loop -> a single slow sshd / dropped ssh handshake = instant 0.
                    _wait_for_sshd(
                        self._ssh_port,
                        timeout=config.sshd_ready_timeout,
                        control_path=self._control_path,
                        subprocess_mod=config.subprocess_mod,
                    )
                    self._container_id = self._start_container()
                    break
                except BackendInitError as _e:
                    try:
                        self._lease.cleanup()
                    except Exception:
                        pass
                    self._container_id = None
                    if _attempt + 1 >= MAX_LEASE_RETRIES:
                        raise
                    _wait = min(2.0 * (2 ** _attempt), 20.0) + _random.uniform(0.0, 3.0)
                    logger.warning(
                        "vacli: bring-up failed (attempt %d/%d): %s -- retry in %.1fs"
                        % (_attempt + 1, MAX_LEASE_RETRIES, str(_e)[:150], _wait)
                    )
                    time.sleep(_wait)
                    _nonce = uuid.uuid4().hex[:8]
                    self._control_path = str(tmp / f"vacli_ctl_{os.getpid()}_{_nonce}")
                    self._vacli_log = tmp / f"vacli_lease_{os.getpid()}_{_nonce}.log"
                    self._lease = VacliLease(
                        tenant_id=config.tenant_id,
                        log_path=self._vacli_log,
                        lease_ttl=config.lease_ttl,
                        tunnel_ready_timeout=config.tunnel_ready_timeout,
                        subprocess_mod=config.subprocess_mod,
                    )
            # Persistent bash inside the container, driven via stdin over the
            # SSH master. Non-interactive `bash` (NOT `bash -i`): interactive
            # mode echoes every command back, prints PS1 on every line, and
            # corrupts the sentinel-detection stream that AsyncSession reads.
            # `stdbuf -oL` defeats libc block-buffering so small-output reads
            # don't hang waiting for a 4KB flush. Matches DES, which spawns
            # AsyncSession with `["/bin/bash"]` (see remote/server.py callers).
            # Bridge networking: the inherited http_proxy=0.0.0.0:8080 is wrong
            # in the container netns. Export the gateway proxy as the first thing
            # the (non-login) session does, so solve.sh subprocesses inherit it.
            _gw = getattr(self, "_proxy_gateway", None)
            _proxy_pre = (
                ("export http_proxy=http://{gw}:8080 https_proxy=http://{gw}:8080 "
                 "HTTP_PROXY=http://{gw}:8080 HTTPS_PROXY=http://{gw}:8080; ".format(gw=_gw)
                 if _gw else "")
                + "export HF_HUB_DISABLE_XET=1 HF_XET_DISABLE=1"
            )
            _us = config.start_script or ""
            _eff = ("; ".join(x for x in (_proxy_pre, _us) if x)) or None
            self._session = VacliSession(
                command_args=_ssh_opts(self._ssh_port, self._control_path)
                + [
                    "root@localhost",
                    f"podman exec -i {self._container_id} stdbuf -oL bash",
                ],
                timeout=config.session_timeout,
                start_script=_eff,
                max_buffer_size=config.max_session_buffer_size,
            )
            self._session.start()
            if config.entrypoint_script:
                # Run through the session so any state it sets up persists for
                # subsequent run_bash calls.
                self._session.communicate(config.entrypoint_script)
        except Exception:
            # Roll back any partial state so an init failure doesn't leak a
            # leased VM.
            self.destroy()
            raise

    @property
    def duration(self) -> float:
        return time.perf_counter() - self.init_start_time

    # -- public ToolBackend surface ----------------------------------------

    def run_bash(self, command: str, timeout: float = 60.0) -> BashResult:
        """Run a command inside the container's persistent bash session.

        `timeout` is the per-command cap (passed through to AsyncSession). On
        expiry the running command is abandoned and the bash session is restarted
        for the next call. None falls back to the AsyncSession session_timeout.

        Shell state (cwd, env vars, sourced venvs, defined functions) persists
        across calls because all commands are fed into the same long-lived
        `bash -i` process via stdin. Matches DES's `VMVMBackend` semantics.
        """
        if self._destroyed:
            return _bash_result("error", "", "exit", exit_code=-1)
        if self._session is None:
            return _bash_result(
                "error", "session not initialized", "other", exit_code=-1
            )
        t0 = time.perf_counter()
        logger.debug(
            f"vacli.run_bash starting (cmd_len={len(command)} head={command[:80]!r})"
        )
        try:
            output = self._session.communicate(command, timeout=timeout)
        except Exception as e:
            logger.debug(
                f"vacli.run_bash raised after {time.perf_counter() - t0:.1f}s: "
                f"{type(e).__name__}: {e}"
            )
            return _bash_result(
                "error", f"{type(e).__name__}: {e}", "other", exit_code=-1
            )
        # AsyncSession's `status` reports session-level health (timeout, broken
        # pipe, bash died). A user command exiting non-zero is NOT a session
        # failure — bash stays alive. But DES's convention is that a non-zero
        # exit is reported as status="error", error_type="exit". Match that so
        # downstream consumers (tool_types.make_python_plugin, swerl/tools.py,
        # swerl/eval_backend/eval.py) see the same shape from both backends.
        logger.debug(
            f"vacli.run_bash communicate returned in {time.perf_counter() - t0:.1f}s "
            f"status={output['status']!r} error_type={output['error_type']!r} "
            f"output_len={len(output['output'])}"
        )
        if output["status"] == "success":
            exit_code = self._session.get_exitcode()
            if exit_code is None:
                exit_code = -1
            if exit_code != 0:
                return _bash_result(
                    "error", output["output"], "exit", exit_code=exit_code
                )
            return _bash_result("success", output["output"], "none", exit_code=0)
        # Session-level error (timeout / broken_pipe / exit / too_long / other).
        # get_exitcode would itself try to talk to a dead session — skip it.
        return _bash_result(
            output["status"], output["output"], output["error_type"], exit_code=-1
        )

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        # Stop the persistent session first so its bash + ssh subprocess exit
        # cleanly before we yank the container out from under them.
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                logger.exception("vacli: session stop failed")
        # Best-effort container teardown; failures here shouldn't block lease release.
        if self._container_id:
            try:
                self._sp.run(
                    _ssh_opts(self._ssh_port, self._control_path)
                    + ["root@localhost", f"podman rm -f {self._container_id}"],
                    stdin=self._sp.DEVNULL,
                    stdout=self._sp.DEVNULL,
                    stderr=self._sp.DEVNULL,
                    timeout=30,
                )
            except Exception:
                logger.exception("vacli: container teardown failed")
        # Close the SSH master so the lease can be released cleanly.
        try:
            self._sp.run(
                _ssh_opts(self._ssh_port, self._control_path)
                + ["-O", "exit", "root@localhost"],
                stdin=self._sp.DEVNULL,
                stdout=self._sp.DEVNULL,
                stderr=self._sp.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass
        self._lease.cleanup()

    def transfer_file(self, file_content: str | bytes, remote_path: str | Path) -> None:
        """Stream a file's bytes into the container via tar over the SSH master.

        Bytes flow through stdin pipes the whole way — no argv inlining — so
        this is bounded only by VM disk, not by `MAX_ARG_STRLEN`.
        """
        if self._destroyed:
            raise RuntimeError("transfer_file called after destroy")
        if self._container_id is None:
            raise RuntimeError("transfer_file called before container init")
        data = (
            file_content.encode("utf-8")
            if isinstance(file_content, str)
            else file_content
        )
        rp = Path(remote_path)
        remote_dir = rp.parent.as_posix() or "/"
        remote_name = rp.name
        # Build a single-file tar in memory keyed at the destination basename;
        # extract it in the destination directory inside the container.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=remote_name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        tar_bytes = buf.getvalue()

        # `ssh ... podman exec -i cid sh -c 'mkdir -p DIR && tar -C DIR -xf -'`
        # The bytes go via stdin, not argv.
        remote_cmd = (
            f"mkdir -p {shlex.quote(remote_dir)} && "
            f"tar -C {shlex.quote(remote_dir)} -xf -"
        )
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            f"podman exec -i {self._container_id} sh -c {shlex.quote(remote_cmd)}",
        ]
        result = self._sp.run(
            argv,
            input=tar_bytes,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=self.config.session_timeout,
        )
        # Per [[vacli-coreweave-stderr-noise]]: stderr is unreliable; trust exit code only.
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"transfer_file failed (rc={result.returncode}, path={remote_path}): {err}"
            )

    def get_debugging_info(self) -> dict[str, Any]:
        return {
            "config": str(self.config),
            "container_id": self._container_id,
            "ssh_port": self._ssh_port,
            "vacli_log": str(self._vacli_log),
            "control_path": self._control_path,
        }

    # -- internals ---------------------------------------------------------

    def _start_container(self) -> str:
        """Pull the image (vmvm-registry mirror, then docker.io fallback) and
        start a long-running detached container."""
        used = _resolve_image_in_vm(
            self._sp,
            self._ssh_port,
            self._control_path,
            self.config.image_url,
            getattr(self.config, "fallback_image_url", None),
        )
        run = self._ssh_call_raw(
            "podman run -d --network bridge --entrypoint /bin/bash "
            + shlex.quote(used)
            + " -c "
            + shlex.quote("tail -f /dev/null"),
            timeout=int(self.config.session_timeout),
        )
        if run.returncode != 0:
            raise BackendInitError(
                f"podman run failed: rc={run.returncode} stderr={run.stderr!r}"
            )
        cid = run.stdout.decode("utf-8", errors="replace").strip()
        if not cid:
            raise BackendInitError(
                f"podman run returned empty container id; stderr={run.stderr!r}"
            )
        cid = _validate_container_id(cid)
        _ensure_python_in_container(
            self._sp, self._ssh_port, self._control_path, cid
        )
        # --network bridge gives the container its own netns so task workloads
        # can bind :8080 (the host egress proxy occupies :8080 in the *host*
        # netns). Repoint http_proxy at the bridge gateway so egress still works.
        self._proxy_gateway = _setup_bridge_proxy(
            self._sp, self._ssh_port, self._control_path, cid
        )
        return cid

    def _ssh_call_raw(
        self, remote_cmd: str, *, timeout: int
    ) -> subprocess.CompletedProcess:
        """Issue one ssh invocation that runs `remote_cmd` on the VM. Combines
        the VM's stderr into stdout (the agent and the BashResult shape both
        expect a single text stream)."""
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            remote_cmd,
        ]
        return self._sp.run(
            argv,
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.STDOUT,
            timeout=timeout,
        )

