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
import ctypes
import io
import json
import logging
import math
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

from .session import AsyncSession, SessionOutput
from .types import BackendInitError, BashResult

logger = logging.getLogger(__name__)


VACLI_BIN = "/public/fbpkgs/x86_64/vacli/latest/vacli"
DEFAULT_TENANT = "async_2347641"
DEFAULT_LEASE_TTL = "500s"
DEFAULT_TUNNEL_READY_TIMEOUT = (
    120.0  # seconds to wait for vacli to print tunnel mapping
)
DEFAULT_SSHD_READY_TIMEOUT = 180.0  # seconds to wait for sshd inside the leased VM
DEFAULT_VACLI_CLEANUP_TIMEOUT = (
    45.0  # seconds to wait for vacli to release before SIGKILL (measured ~33s)
)
HOST_MEMORY_HEADROOM_MIB = 512

_PR_SET_PDEATHSIG = 1
try:
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:
    _libc = None


def _child_pdeathsig() -> None:
    """preexec_fn for the vacli child: one prctl syscall (fork-safe).
    PR_SET_PDEATHSIG makes the kernel send this child SIGTERM the moment its
    parent (the env worker) dies -- even on a hard SIGKILL of the worker -- so
    vacli's --release-on-exit fires and the VM is freed instead of orphaned.
    """
    if _libc is not None:
        _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)

# Cap concurrent in-flight vacli leases per process: bursts of simultaneous
# lease attempts trigger FAAS tunnel-setup timeouts. Tune via env if needed.
MAX_CONCURRENT_LEASES = int(os.environ.get("VACLI_MAX_CONCURRENT_LEASES", "16"))
# Retries for `podman pull` inside the VM when DockerHub returns 429
# (toomanyrequests). The vmvm-registry mirror path needs no retries; this only
# matters for the docker.io fallback used when an image is not yet mirrored.
MAX_PULL_RETRIES = int(os.environ.get("VACLI_MAX_PULL_RETRIES", "20"))
IMAGE_PULL_TIMEOUT_SECONDS = int(os.environ.get("VACLI_IMAGE_PULL_TIMEOUT_SECONDS", "350"))
if IMAGE_PULL_TIMEOUT_SECONDS <= 0:
    raise ValueError("VACLI_IMAGE_PULL_TIMEOUT_SECONDS must be positive")
# Retries for the vacli lease bring-up itself. Concurrent launches race on
# Configerator/JustKnobs init ("isConfigeratorAvailable() returned false" ->
# "vacli died before tunnel was ready"), a transient thundering-herd failure at
# high concurrency; jittered retry disperses the herd. See [[vacli-lease-race]].
MAX_LEASE_RETRIES = int(os.environ.get("VACLI_LEASE_RETRIES", "20"))


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

# vacli prints the LeaseVmResponse as a single JSON line, e.g.:
# {"sessionId":{...},"auth_token":{...}}
# We capture it so a dropped tunnel can be re-established to the SAME VM via
# `lease --resume-with-session <json>` (no re-lease; container + files intact).
_LEASE_RESP_RE = re.compile(r'\{"sessionId":.*"auth_token":\{[^}]*\}\}')

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
    cpu: float | None = None
    memory_gb: float | None = None
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


@dataclass(frozen=True)
class VacliHostTunnel:
    gateway: str
    remote_port: int
    local_port: int
    relay_pid: int


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
        # Raw LeaseVmResponse JSON (captured from the lease log) — input to
        # `--resume-with-session` when re-establishing a dropped tunnel.
        self.lease_response: str | None = None
        self._resume_count = 0
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
                _popen_kwargs = dict(
                    stdout=log_fh,
                    stderr=self._sp.STDOUT,
                    process_group=0,
                )
                if self._sp is subprocess:
                    # real subprocess only (test mocks may not accept preexec_fn):
                    # kernel SIGTERMs vacli if the worker dies -> --release-on-exit
                    _popen_kwargs["preexec_fn"] = _child_pdeathsig
                self.proc = self._sp.Popen(cmd, **_popen_kwargs)
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
                # Capture the LeaseVmResponse once (needed later for resume).
                if self.lease_response is None:
                    for _line in text.splitlines():
                        if '"sessionId"' in _line and '"auth_token"' in _line:
                            _m = _LEASE_RESP_RE.search(_line)
                            if _m:
                                self.lease_response = _m.group(0)
                                break
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

    def restart_tunnel(self) -> "int | None":
        """Re-establish the x2p tunnel to the SAME VM after a dropped tunnel,
        via `lease --resume-with-session`, WITHOUT re-leasing — the VM, its
        podman container, and all on-disk state are preserved.

        The current vacli is SIGKILL'd first: `--release-on-exit` only fires on
        a *graceful* exit, so a hard kill leaves the VM leased (an un-resumed VM
        still reclaims when auto-renew stops at lease TTL — no permanent leak).
        Returns the new local ssh port, or None if the VM/lease is unrecoverable.

        Validated: SIGKILL keeps the VM alive and resume reconnects to it with
        files intact (see scripts/_resume_e2e_test.sh)."""
        if not self.lease_response:
            logger.warning("vacli.restart_tunnel: no LeaseVmResponse captured; cannot resume")
            return None
        # Hard-kill the current vacli (NOT SIGTERM: that would release the VM).
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.proc.wait(timeout=10)
            except Exception:
                pass
        self.proc = None
        self.ssh_port = None
        self._resume_count += 1
        # Fresh log per resume so wait_for_tunnel() parses the new mapping. Unlink
        # the prior log first so repeated resumes don't accumulate files on the host.
        _old_log = self.log_path
        base = self.log_path.name.split(".resume")[0]
        self.log_path = self.log_path.with_name(f"{base}.resume{self._resume_count}.log")
        try:
            _old_log.unlink()
        except (FileNotFoundError, OSError):
            pass
        cmd = [
            "stdbuf", "-oL", VACLI_BIN, "--x2p", "--faas-tenant-id", self.tenant_id,
            "lease", "--resume-with-session", self.lease_response,
            "--ttl", self.lease_ttl, "--auto-renew", "--tunnel-ports", "22",
            "--release-on-exit",
        ]
        logger.info("vacli.restart_tunnel: resuming session (attempt %d)", self._resume_count)
        # Respect the bring-up concurrency cap (released by wait_for_tunnel's finally).
        _lease_concurrency.acquire()
        self._concurrency_held = True
        try:
            with open(self.log_path, "wb") as log_fh:
                _popen_kwargs = dict(stdout=log_fh, stderr=self._sp.STDOUT, process_group=0)
                if self._sp is subprocess:
                    _popen_kwargs["preexec_fn"] = _child_pdeathsig
                self.proc = self._sp.Popen(cmd, **_popen_kwargs)
        except Exception as e:
            self._release_concurrency_slot()
            logger.warning("vacli.restart_tunnel: failed to spawn resume vacli: %s", e)
            return None
        try:
            return self.wait_for_tunnel()  # sets self.ssh_port; releases the slot
        except BackendInitError as e:
            logger.warning("vacli.restart_tunnel: resume tunnel not ready: %s", e)
            return None

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
            try:
                self.proc.wait(timeout=5)  # reap so vacli doesn't linger as a zombie
            except Exception:
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
            timeout=IMAGE_PULL_TIMEOUT_SECONDS,
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
    bypass = f"localhost,127.0.0.1,{gw}"
    exports = (
        "".join(
            "export %s=http://%s:8080\n" % (key, gw)
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
        )
        + f'export no_proxy="${{no_proxy:+$no_proxy,}}{bypass}"\n'
        + f'export NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}{bypass}"\n'
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
        self._host_tunnels: set[VacliHostTunnel] = set()
        # FIFO-backed persistent shell state (v1). The shell lives INSIDE the
        # container behind a named pipe, so an x2p tunnel drop does not kill it:
        # cwd/env + any in-flight command survive, and restart_session() re-attaches
        # to the SAME shell. Set up in _open_session; falls back to the legacy
        # streamed session (_fifo_mode=False) only if the image lacks bash+mkfifo.
        self._tools: dict[str, bool] = {}
        self._fifo_mode = False
        self._sess_nonce = ""
        self._sess_dir = ""
        self._cmd_seq = 0
        # (seq, command, timeout) for a command SENT to the shell whose result was
        # not yet collected (tunnel dropped mid-wait). recover_last() re-reads it
        # WITHOUT re-executing. None => nothing in flight.
        self._pending: tuple[int, str, float, float] | None = None
        self._last_command: str | None = None
        self._last_timeout: float | None = None
        # Set by restart_session when it had to REBUILD a dead in-container shell
        # (state lost); recover_last() then declines transparent recovery.
        self._shell_was_reset = False
        # Structured record of transient bring-up retries (recovered) so the
        # rollout's jsonl can show how many re-leases it took to come up.
        self.bringup_retries: list = []
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
                    self.bringup_retries.append(
                        {"attempt": _attempt + 1, "detail": str(_e)[:300]}
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
            self._open_session(run_entrypoint=True)
        except Exception:
            # Roll back any partial state so an init failure doesn't leak a
            # leased VM.
            self.destroy()
            raise

    def _open_session(self, run_entrypoint: bool = True) -> None:
        """Set up the persistent shell for the current container.

        Prefers a FIFO-backed shell living INSIDE the container (survives x2p
        tunnel drops -- cwd/env + in-flight command persist). Falls back to the
        legacy SSH-streamed `podman exec -i bash` only if the image lacks
        bash+mkfifo+setsid. Called by __init__ (run_entrypoint=True). NOTE:
        restart_session() does NOT call this in fifo mode -- the in-container
        shell survives a drop, so we re-attach (verify alive) rather than rebuild.

        setsid is required (not just bash+mkfifo): the reader runs under setsid so
        a timed-out runaway command can be group-killed; without it we cannot
        guarantee the runaway dies, so we fall back to the legacy session.
        """
        self._tools = self._probe_tools()
        if self._tools.get("bash") and self._tools.get("mkfifo") and self._tools.get("setsid"):
            self._fifo_mode = True
            self._setup_fifo_shell(run_entrypoint=run_entrypoint, run_start_script=True)
            return

        # --- legacy fallback: image has no fifo-capable shell (no drop-recovery) ---
        self._fifo_mode = False
        logger.warning(
            "vacli: image lacks bash+mkfifo (%s); using legacy streamed session "
            "(no mid-rollout drop recovery)", self._tools,
        )
        config = self.config
        _gw = getattr(self, "_proxy_gateway", None)
        _proxy_pre = (
            (
                "export http_proxy=http://{gw}:8080 https_proxy=http://{gw}:8080 "
                "HTTP_PROXY=http://{gw}:8080 HTTPS_PROXY=http://{gw}:8080 "
                'no_proxy="${{no_proxy:+$no_proxy,}}localhost,127.0.0.1,{gw}" '
                'NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}localhost,127.0.0.1,{gw}"; '.format(
                    gw=_gw
                )
                if _gw
                else ""
            )
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
        if run_entrypoint and config.entrypoint_script:
            # Run through the session so any state it sets up persists for
            # subsequent run_bash calls.
            self._session.communicate(config.entrypoint_script)

    # -- FIFO-backed persistent shell (v1) ---------------------------------

    def _probe_tools(self) -> dict[str, bool]:
        """Check which shell tools the container image provides. bash+mkfifo are
        required for the FIFO shell; setsid is optional (enables clean group-kill
        of a runaway command on timeout)."""
        script = (
            'for t in bash mkfifo setsid; do '
            'command -v "$t" >/dev/null 2>&1 && echo "have $t" || echo "miss $t"; done'
        )
        try:
            r = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " sh -c " + shlex.quote(script),
                timeout=60,
            )
            out = (r.stdout or b"").decode("utf-8", "replace")
        except Exception:
            out = ""
        return {t: (("have " + t) in out) for t in ("bash", "mkfifo", "setsid")}

    def _preamble(self) -> str:
        """Proxy + user start_script, applied once at shell setup so cwd/env it
        sets persist for every run_bash call (the bridge container netns needs the
        gateway proxy; the inherited 0.0.0.0:8080 is wrong)."""
        config = self.config
        gw = getattr(self, "_proxy_gateway", None)
        proxy_pre = (
            (
                "export http_proxy=http://{gw}:8080 https_proxy=http://{gw}:8080 "
                "HTTP_PROXY=http://{gw}:8080 HTTPS_PROXY=http://{gw}:8080 "
                'no_proxy="${{no_proxy:+$no_proxy,}}localhost,127.0.0.1,{gw}" '
                'NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}localhost,127.0.0.1,{gw}"; '.format(
                    gw=gw
                )
                if gw
                else ""
            )
            + "export HF_HUB_DISABLE_XET=1 HF_XET_DISABLE=1"
        )
        us = config.start_script or ""
        return "; ".join(x for x in (proxy_pre, us) if x)

    def _setup_fifo_shell(self, *, run_entrypoint: bool, run_start_script: bool = True) -> None:
        """Create the in-container persistent shell: a command FIFO, a held-writer
        keeping it open, and a detached `bash` LOOP that reads a command sequence
        number from the FIFO and `source`s the staged command body for that seq.

        Protocol (per command <seq>):
          * the body is staged out-of-band into c<seq> (atomic write+rename) so a
            torn FIFO write can never leave the reader mid-parse;
          * only a tiny integer token `<seq>` is pushed through the FIFO; the reader
            validates it is an integer (garbage/partial tokens are skipped), writes
            a `started` marker s<seq>, runs `source c<seq> </dev/null >o<seq> 2>&1`
            (current shell -> cwd/env persist; </dev/null -> a command reading stdin
            can't cannibalise the FIFO), then writes e<seq> (exit code) and d<seq>
            (done marker).
        Reads (_fifo_wait_read) are stateless/idempotent and recovery (recover_last)
        gates re-execution on the s<seq> marker, never on an ssh return code, so a
        drop can never double-execute a command.
        The reader runs under setsid (pgid==pid) so a runaway command can be
        group-killed on timeout. Requires bash+mkfifo+setsid (checked by caller)."""
        cid = str(self._container_id)
        nonce = uuid.uuid4().hex[:12]
        self._sess_nonce = nonce
        self._sess_dir = "/tmp/.vacli_sess_" + nonce
        self._cmd_seq = 0
        self._pending = None
        self._shell_was_reset = False
        D = self._sess_dir
        qD = shlex.quote(D)
        # 1) session dir + command fifo + (empty) reader log -- synchronous.
        setup = "set -e; rm -rf {D}; mkdir -p {D}; mkfifo {D}/cmd; : > {D}/log".format(D=qD)
        r = self._ssh_call_raw("podman exec " + cid + " bash -c " + shlex.quote(setup), timeout=60)
        if r.returncode != 0:
            raise BackendInitError(
                "fifo shell setup failed: "
                + (r.stdout or b"").decode("utf-8", "replace")[-400:]
            )
        # 2) held-writer: keeps the fifo open for writing so the reader's `read`
        #    never sees EOF between commands. Records its pid for clean teardown.
        hold = ('D={D}; echo $$ > "$D/holdpid"; '
                'exec -a vacli_hold_{n} sleep 2147483647 > "$D/cmd"').format(D=qD, n=nonce)
        self._ssh_call_raw("podman exec -d " + cid + " bash -c " + shlex.quote(hold), timeout=30)
        # 3) reader loop: records its pgid, then forever reads an integer seq from
        #    the fifo and runs the staged body for that seq in THIS shell.
        # Reader-internal vars are namespaced (__vacli_*) so a task command sourced in
        # THIS shell that uses common names (D, seq, last) cannot clobber the loop's
        # control state. __vacli_last is the AUTHORITATIVE exactly-once gate: it lives
        # in the reader's memory (not a file the command can delete/forge), and seq is
        # strictly increasing, so any re-pushed / torn-then-completed / duplicate token
        # for a seq <= the last STARTED seq is dropped -- a tunnel drop can never
        # double-execute a command no matter what recover_last re-pushes. `set +e` each
        # iteration neutralizes a prior body's `set -e` so a builtin returning non-zero
        # (e.g. the -le test, which is false on the normal path) can't kill the reader.
        reader = (
            '__vacli_d={D}; echo $$ > "$__vacli_d/pgid"; __vacli_last=0; '
            'while IFS= read -r __vacli_seq; do '
            'set +e; '
            'case "$__vacli_seq" in (""|*[!0-9]*) continue ;; esac; '
            'if [ "$__vacli_seq" -le "$__vacli_last" ] 2>/dev/null; then continue; fi; '
            '__vacli_last="$__vacli_seq"; '
            ': > "$__vacli_d/s$__vacli_seq"; '
            'source "$__vacli_d/c$__vacli_seq" < /dev/null > "$__vacli_d/o$__vacli_seq" 2>&1; '
            '__vacli_rc=$?; '
            'printf %s "$__vacli_rc" > "$__vacli_d/e$__vacli_seq"; '
            ': > "$__vacli_d/d$__vacli_seq"; '
            'done < "$__vacli_d/cmd"'
        ).format(D=qD)
        self._ssh_call_raw(
            "podman exec -d " + cid + " setsid bash -c " + shlex.quote(reader), timeout=30
        )
        # 4) wait for both the reader and held-writer processes to be live.
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._fifo_shell_alive():
                break
            time.sleep(0.3)
        else:
            raise BackendInitError("fifo reader/held-writer did not come up")
        # 5) preamble doubles as an end-to-end wiring probe (exercises stage+push+read).
        pre = self._preamble() if run_start_script else ""
        probe = self._fifo_run(pre or ":", timeout=max(30.0, 0.0))
        if probe["error_type"] in ("broken_pipe", "timeout", "other"):
            raise BackendInitError("fifo shell wiring probe failed: %r" % (probe,))
        # 6) entrypoint, in the persistent shell so its state sticks.
        if run_entrypoint and self.config.entrypoint_script:
            self._fifo_run(self.config.entrypoint_script, timeout=self.config.session_timeout)

    def _fifo_shell_alive(self) -> bool:
        """True iff BOTH the in-container reader (by pgid) and the held-writer (by
        holdpid) are alive. If the held-writer died the reader would EOF and exit
        after the next command, so both must be checked."""
        if not self._sess_dir or self._container_id is None:
            return False
        chk = ('D={D}; r=$(cat "$D/pgid" 2>/dev/null); h=$(cat "$D/holdpid" 2>/dev/null); '
               '[ -n "$r" ] && kill -0 "$r" 2>/dev/null && '
               '[ -n "$h" ] && kill -0 "$h" 2>/dev/null && echo ALIVE').format(
            D=shlex.quote(self._sess_dir))
        try:
            r = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(chk),
                timeout=30,
            )
        except Exception:
            return False
        return r.returncode == 0 and b"ALIVE" in (r.stdout or b"")

    def _teardown_fifo_shell(self) -> None:
        """Kill the in-container reader (and its current foreground command, via
        group-kill on the setsid pgid) plus the held-writer (by recorded pid), and
        remove the session dir. Best-effort; used on timeout and on dead-shell
        recreate to reset state like the legacy backend."""
        if not self._sess_dir or self._container_id is None:
            return
        script = (
            'D={D}; p=$(cat "$D/pgid" 2>/dev/null); h=$(cat "$D/holdpid" 2>/dev/null); '
            '[ -n "$p" ] && kill -KILL -"$p" 2>/dev/null; '
            '[ -n "$p" ] && kill -KILL "$p" 2>/dev/null; '
            '[ -n "$h" ] && kill -KILL "$h" 2>/dev/null; '
            'rm -rf "$D" 2>/dev/null; true'
        ).format(D=shlex.quote(self._sess_dir))
        try:
            self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
                timeout=30,
            )
        except Exception:
            pass
        self._sess_dir = ""
        self._pending = None

    def _fifo_stage(self, seq: int, command: str, fresh: bool = False) -> bool:
        """Stage the command body into c<seq> atomically (write tmp + rename), via
        stdin so size is bounded only by VM disk. Idempotent. Returns ssh-ok.

        When `fresh` (initial run of a brand-new seq), first remove any pre-existing
        s/o/e/d<seq> markers so a task command that forged the NEXT seq's done/output
        files can't make _fifo_wait_read return stale/forged data before the reader
        runs. Recovery re-stages with fresh=False so it never wipes the real markers
        it needs to decide whether the command already ran."""
        body = command if command.strip() else ":"
        pre = ('rm -f "$D/s{s}" "$D/o{s}" "$D/e{s}" "$D/d{s}"; ' if fresh else "").format(s=seq)
        script = ('D={D}; ' + pre + 'cat > "$D/c{s}.tmp" && mv -f "$D/c{s}.tmp" "$D/c{s}"').format(
            D=shlex.quote(self._sess_dir), s=seq)
        remote = "podman exec -i " + str(self._container_id) + " bash -c " + shlex.quote(script)
        argv = _ssh_opts(self._ssh_port, self._control_path) + ["root@localhost", remote]
        try:
            r = self._sp.run(
                argv, input=body.encode("utf-8"),
                stdout=self._sp.DEVNULL, stderr=self._sp.DEVNULL, timeout=60,
            )
        except Exception as e:
            logger.debug("fifo_stage failed: %s", e)
            return False
        return r.returncode == 0

    def _fifo_push(self, seq: int) -> bool:
        """Push the tiny trigger token `<seq>` into the FIFO (the reader then runs
        the staged body). A leading newline closes any partial line a prior torn
        write may have left. Returns ssh-ok (NOT proof of execution -- recovery
        keys off the s<seq> marker)."""
        script = 'D={D}; cat > "$D/cmd"'.format(D=shlex.quote(self._sess_dir))
        remote = "podman exec -i " + str(self._container_id) + " bash -c " + shlex.quote(script)
        argv = _ssh_opts(self._ssh_port, self._control_path) + ["root@localhost", remote]
        try:
            r = self._sp.run(
                argv, input=("\n%d\n" % seq).encode("ascii"),
                stdout=self._sp.DEVNULL, stderr=self._sp.DEVNULL, timeout=60,
            )
        except Exception as e:
            logger.debug("fifo_push failed: %s", e)
            return False
        return r.returncode == 0

    def _fifo_marker(self, seq: int, kind: str) -> "bool | None":
        """Tri-state existence check for marker file <kind><seq> inside the
        container: True (exists), False (definitely absent), None (ssh/tunnel
        failed -- unknown). Uses a unique echo token and the ssh rc so error text
        can't be misread as a verdict."""
        script = ('D={D}; if [ -e "$D/{k}{s}" ]; then echo VACLI_MARK_Y; '
                  'else echo VACLI_MARK_N; fi').format(D=shlex.quote(self._sess_dir), k=kind, s=seq)
        try:
            r = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
                timeout=30,
            )
        except Exception:
            return None
        if r.returncode != 0:
            return None
        out = r.stdout or b""
        if b"VACLI_MARK_Y" in out:
            return True
        if b"VACLI_MARK_N" in out:
            return False
        return None

    def _fifo_cleanup_seq(self, seq: int) -> None:
        """Remove the per-command files for a completed seq (bounded disk use)."""
        if not self._sess_dir or self._container_id is None:
            return
        script = 'D={D}; rm -f "$D/c{s}" "$D/o{s}" "$D/e{s}" "$D/d{s}" "$D/s{s}" 2>/dev/null; true'.format(
            D=shlex.quote(self._sess_dir), s=seq)
        try:
            self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
                timeout=30,
            )
        except Exception:
            pass

    def _fifo_wait_read(self, seq: int, timeout: float) -> BashResult:
        """Block (in-container, no x2p round-trips) until command <seq> finishes or
        `timeout` elapses, then return its output + exit code. Frames the reply
        between a leading `__VACLI_STATUS__` line and a trailing `__VACLI_END__`
        line; if the trailing marker is missing or ssh failed, the reply was
        truncated by a drop -> broken_pipe (recovery re-reads). Resumable."""
        maxb = self.config.max_session_buffer_size or (480 * 1024)
        t = max(1, int(timeout if timeout else self.config.session_timeout))
        script = (
            'D={D}; s={s}; deadline=$(( $(date +%s) + {t} )); '
            'while :; do '
            '[ -e "$D/d$s" ] && {{ st=ok; break; }}; '
            '[ "$(date +%s)" -ge "$deadline" ] && {{ st=timeout; break; }}; '
            'sleep 0.1; done; '
            'printf "__VACLI_STATUS__ %s %s\\n" "$st" "$(cat "$D/e$s" 2>/dev/null)"; '
            'head -c {mb1} "$D/o$s" 2>/dev/null; '
            'printf "\\n__VACLI_END__\\n"'
        ).format(D=shlex.quote(self._sess_dir), s=seq, t=t, mb1=maxb + 1)
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
        ]
        try:
            r = self._sp.run(
                argv, stdin=self._sp.DEVNULL, stdout=self._sp.PIPE,
                stderr=self._sp.DEVNULL, timeout=t + 40,
            )
        except Exception as e:
            return _bash_result(
                "error", f"[vacli] connection lost during wait: {e}", "broken_pipe", exit_code=-1
            )
        return self._parse_fifo_reply(r.returncode, r.stdout or b"")

    def _parse_fifo_reply(self, returncode: int, raw: bytes) -> BashResult:
        """Parse a framed reply: a leading `__VACLI_STATUS__ <st> <ec>` line, the
        command output, then a trailing `__VACLI_END__` line. A nonzero ssh rc or a
        missing/truncated frame means a drop cut the reply -> broken_pipe (recovery
        re-reads). Shared by _fifo_wait_read (recovery) and _fifo_exec_combined (hot
        path)."""
        maxb = self.config.max_session_buffer_size or (480 * 1024)
        si = raw.find(b"__VACLI_STATUS__")
        ei = raw.rfind(b"\n__VACLI_END__")
        if returncode != 0 or si < 0 or ei < 0 or si >= ei:
            return _bash_result(
                "error", f"[vacli] connection lost (rc={returncode}, truncated reply)",
                "broken_pipe", exit_code=-1,
            )
        nl = raw.find(b"\n", si)
        if nl < 0 or nl > ei:
            return _bash_result(
                "error", "[vacli] connection lost (malformed reply)", "broken_pipe", exit_code=-1
            )
        status_line = raw[si:nl].decode("utf-8", "replace")
        out_bytes = raw[nl + 1:ei]
        parts = status_line.split()
        st = parts[1] if len(parts) > 1 else "timeout"
        ec_str = parts[2] if len(parts) > 2 else ""
        too_long = len(out_bytes) > maxb
        output = (out_bytes[:maxb] if too_long else out_bytes).decode("utf-8", errors="ignore")
        if st == "timeout":
            return _bash_result("error", output, "timeout", exit_code=-1)
        if too_long:
            return _bash_result("error", output, "too_long", exit_code=-1)
        try:
            ec = int(ec_str)
        except (ValueError, TypeError):
            ec = -1
        if ec != 0:
            return _bash_result("error", output, "exit", exit_code=ec)
        return _bash_result("success", output, "none", exit_code=ec)

    def _fifo_exec_combined(self, seq: int, command: str, timeout: float) -> BashResult:
        """Happy-path fast lane: stage body + push token + wait + emit in ONE
        `podman exec` (4 x2p round-trips -> 1; ~4x lower per-command latency). Also
        frees the previous seq's files so disk stays bounded. On any drop the framed
        reply is absent -> broken_pipe with _pending kept, and recover_last() finishes
        the command via the careful separate path (the in-memory monotonic reader
        guard makes a re-push safe -> still exactly-once). Staging failure aborts
        before the token is pushed (exit 91 -> broken_pipe -> recover re-stages)."""
        maxb = self.config.max_session_buffer_size or (480 * 1024)
        t = max(1, int(timeout if timeout else self.config.session_timeout))
        body = command if command.strip() else ":"
        script = (
            'D={D}; s={s}; p={p}; '
            'rm -f "$D/c$p" "$D/o$p" "$D/e$p" "$D/d$p" "$D/s$p" 2>/dev/null; '   # bound disk: prev seq
            'rm -f "$D/s$s" "$D/o$s" "$D/e$s" "$D/d$s" 2>/dev/null; '            # fresh markers (anti-forge)
            'cat > "$D/c$s.tmp" && mv -f "$D/c$s.tmp" "$D/c$s" || exit 91; '     # stage body (stdin)
            'printf "\\n%s\\n" "$s" > "$D/cmd"; '                                # push token
            'deadline=$(( $(date +%s) + {t} )); '
            'while :; do '
            '[ -e "$D/d$s" ] && {{ st=ok; break; }}; '
            '[ "$(date +%s)" -ge "$deadline" ] && {{ st=timeout; break; }}; '
            'sleep 0.1; done; '
            'printf "__VACLI_STATUS__ %s %s\\n" "$st" "$(cat "$D/e$s" 2>/dev/null)"; '
            'head -c {mb1} "$D/o$s" 2>/dev/null; '
            'printf "\\n__VACLI_END__\\n"'
        ).format(D=shlex.quote(self._sess_dir), s=seq, p=seq - 1, t=t, mb1=maxb + 1)
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            "podman exec -i " + str(self._container_id) + " bash -c " + shlex.quote(script),
        ]
        try:
            r = self._sp.run(
                argv, input=body.encode("utf-8"), stdout=self._sp.PIPE,
                stderr=self._sp.DEVNULL, timeout=t + 40,
            )
        except Exception as e:
            return _bash_result(
                "error", f"[vacli] connection lost during exec: {e}", "broken_pipe", exit_code=-1
            )
        return self._parse_fifo_reply(r.returncode, r.stdout or b"")

    def _fifo_finish(self, seq: int, res: BashResult) -> BashResult:
        """Common post-read handling: clear pending, clean up per-command files,
        and on a real timeout reset the shell (legacy parity: kill the runaway +
        fresh cwd/env)."""
        self._pending = None
        self._fifo_cleanup_seq(seq)
        if res["error_type"] == "timeout":
            self._teardown_fifo_shell()
            try:
                self._setup_fifo_shell(run_entrypoint=False, run_start_script=True)
            except Exception as e:
                logger.warning("fifo: shell recreate after timeout failed: %s", e)
        return res

    def _fifo_run(self, command: str, timeout: float) -> BashResult:
        """Stage + trigger + collect one command in a SINGLE podman exec (hot path).
        On a tunnel drop the framed reply is absent -> broken_pipe with `_pending`
        kept, so recover_last() finishes it WITHOUT re-executing (the in-memory
        monotonic reader guard makes a re-push safe)."""
        self._cmd_seq += 1
        seq = self._cmd_seq
        start = time.monotonic()
        self._pending = (seq, command, timeout, start)
        res = self._fifo_exec_combined(seq, command, timeout)
        if res["error_type"] == "broken_pipe":
            return res  # _pending kept; recover_last() finishes it
        # Completed (success/exit/timeout/too_long): clear pending; on a real timeout
        # reset the shell (legacy parity: kill the runaway + fresh cwd/env). Per-command
        # files are freed by the NEXT command's combined call (prev-seq cleanup) and by
        # destroy()'s teardown, so no extra round-trip here.
        self._pending = None
        if res["error_type"] == "timeout":
            self._teardown_fifo_shell()
            try:
                self._setup_fifo_shell(run_entrypoint=False, run_start_script=True)
            except Exception as e:
                logger.warning("fifo: shell recreate after timeout failed: %s", e)
        return res

    def recover_last(self) -> "BashResult | None":
        """After restart_session() re-establishes the tunnel, finish the command
        the drop interrupted -- WITHOUT re-running one that already executed. The
        in-container shell + its in-flight command survived the drop. Execution is
        gated on the in-container `started` marker s<seq>, never on an ssh return
        code, so re-pushing a token that already ran is impossible.

        Returns the recovered BashResult, or None when there is nothing to recover
        or the shell had to be rebuilt (so env.py uses its legacy 'shell was reset'
        contract -- the in-flight command is genuinely gone in that case)."""
        if self._destroyed or not self._fifo_mode:
            return None
        if self._shell_was_reset:
            # restart_session had to recreate a DEAD shell: state + the in-flight
            # command are gone. Don't pretend transparency.
            self._shell_was_reset = False
            self._pending = None
            self._last_command = None
            return None
        if self._pending is None:
            return None
        seq, command, timeout, start = self._pending
        # 1) ensure the body is staged (idempotent atomic overwrite).
        m_c = self._fifo_marker(seq, "c")
        if m_c is None:
            return _bash_result("error", "[vacli] connection lost (probe c)", "broken_pipe", exit_code=-1)
        if m_c is False and not self._fifo_stage(seq, command):
            return _bash_result("error", "[vacli] connection lost (re-stage)", "broken_pipe", exit_code=-1)
        # 2) has the reader already STARTED this seq? (s<seq>). Only push if not.
        #    A small settle closes the (sub-ms) window between the token landing and
        #    the reader writing s<seq>; restart_session latency already dwarfs it.
        m_s = self._fifo_marker(seq, "s")
        if m_s is None:
            return _bash_result("error", "[vacli] connection lost (probe s)", "broken_pipe", exit_code=-1)
        if m_s is False:
            time.sleep(1.0)
            m_s = self._fifo_marker(seq, "s")
            if m_s is None:
                return _bash_result("error", "[vacli] connection lost (probe s2)", "broken_pipe", exit_code=-1)
            if m_s is False and not self._fifo_push(seq):
                return _bash_result("error", "[vacli] connection lost (re-push)", "broken_pipe", exit_code=-1)
        # 3) wait, clamping the budget to the time remaining on the original cap so
        #    repeated reconnects can't multiply a command's runtime.
        rem = max(2, int(timeout - (time.monotonic() - start)))
        res = self._fifo_wait_read(seq, rem)
        if res["error_type"] == "broken_pipe":
            return res  # dropped again; _pending kept for the next reconnect
        return self._fifo_finish(seq, res)



    def restart_session(self) -> bool:
        """Recover from a dropped ssh channel (e.g. ConnectionResetError during
        grading) by re-attaching a fresh bash session to the SAME container over
        the SAME lease. Nothing is re-leased and the container is never removed,
        so the agent's full filesystem state is preserved and a subsequent
        re-grade is valid. Returns True iff a live session is re-established.

        Returns False (caller should give up and score env_error) when the box
        is genuinely gone — lease/sshd dead or the container no longer running —
        because there is then nothing to grade."""
        if self._destroyed or self._container_id is None:
            return False
        # Drop the dead session.
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                pass
            self._session = None
        # Clear any stale ssh master socket, then re-open it via ControlMaster=auto.
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
        try:
            _wait_for_sshd(
                self._ssh_port,
                # Wait on the ORIGINAL tunnel first (vacli not yet killed) so a
                # transient x2p blip can SELF-HEAL -- production data showed ~2/3 of
                # mid-rollout drops recover within ~60s if we just wait, vs failing
                # the SIGKILL+resume path ("sshd unreachable after resume") while the
                # blip is still ongoing. 60s matches v0's original-port wait; only
                # after it stays dead do we SIGKILL + resume below (the fallback for a
                # genuinely-gone VM). Costs up to ~60s extra on a truly-dead box, but
                # those rollouts are dropped anyway, and it converts the common
                # self-healing blips into clean seamless recoveries.
                timeout=min(float(self.config.sshd_ready_timeout), 60.0),
                control_path=self._control_path,
                subprocess_mod=self.config.subprocess_mod,
            )
        except Exception as e:
            # sshd unreachable on the existing tunnel: the x2p tunnel (or the
            # vacli that owned it) is gone. Don't give up — the VM itself is
            # almost always still alive (we essentially never see the container
            # die). Re-establish a fresh tunnel to the SAME VM via resume.
            logger.warning(
                "vacli.restart_session: sshd not reachable: %s -- resuming tunnel", e
            )
            new_port = self._lease.restart_tunnel()
            if new_port is None:
                logger.warning(
                    "vacli.restart_session: tunnel resume failed; box unrecoverable"
                )
                return False
            self._ssh_port = new_port
            # Drop the stale ssh master (it pointed at the dead tunnel port).
            try:
                self._sp.run(
                    _ssh_opts(self._ssh_port, self._control_path)
                    + ["-O", "exit", "root@localhost"],
                    stdin=self._sp.DEVNULL, stdout=self._sp.DEVNULL,
                    stderr=self._sp.DEVNULL, timeout=10,
                )
            except Exception:
                pass
            try:
                _wait_for_sshd(
                    self._ssh_port,
                    timeout=min(float(self.config.sshd_ready_timeout), 60.0),
                    control_path=self._control_path,
                    subprocess_mod=self.config.subprocess_mod,
                )
            except Exception as e2:
                logger.warning(
                    "vacli.restart_session: sshd still unreachable after resume: %s", e2
                )
                return False
            logger.info(
                "vacli.restart_session: tunnel resumed to same VM on new port %d",
                self._ssh_port,
            )
        # The container must still be running, else the agent's work is gone.
        try:
            chk = self._ssh_call_raw(
                "podman inspect -f '{{.State.Running}}' " + str(self._container_id),
                timeout=30,
            )
        except Exception as e:
            logger.warning("vacli.restart_session: container check raised: %s", e)
            return False
        if chk.returncode != 0 or b"true" not in (chk.stdout or b"").lower():
            logger.warning(
                "vacli.restart_session: container %s not running (rc=%s) -- giving up",
                self._container_id, chk.returncode,
            )
            return False
        if not self._restore_host_tunnels():
            return False
        # FIFO mode: the persistent shell lives INSIDE the container, so it
        # survived the drop -- cwd/env + any in-flight command are intact. Do NOT
        # rebuild it (that would lose state); just verify it is still alive. Only
        # if it somehow died do we recreate a fresh one (state lost, box usable).
        if self._fifo_mode:
            if self._fifo_shell_alive():
                logger.info(
                    "vacli.restart_session: fifo shell survived drop on container %s "
                    "(state intact)", self._container_id,
                )
                return True
            logger.warning(
                "vacli.restart_session: fifo shell dead on container %s -- recreating",
                self._container_id,
            )
            # The shell (and any in-flight command) is genuinely gone: tear down the
            # orphaned reader/held-writer, then build a fresh shell. Flag it so
            # recover_last() declines transparent recovery (state was lost) and
            # env.py falls back to telling the agent the shell was reset.
            try:
                self._teardown_fifo_shell()
            except Exception:
                pass
            try:
                self._setup_fifo_shell(run_entrypoint=False, run_start_script=True)
            except Exception as e:
                logger.warning("vacli.restart_session: fifo shell recreate failed: %s", e)
                return False
            self._shell_was_reset = True
            return True
        # Legacy mode: re-attach a fresh bash to the same container; skip the task
        # entrypoint (state already exists) but re-apply the proxy/env preamble.
        try:
            self._open_session(run_entrypoint=False)
        except Exception as e:
            logger.warning("vacli.restart_session: re-open session failed: %s", e)
            return False
        logger.info(
            "vacli.restart_session: re-attached to container %s on same lease",
            self._container_id,
        )
        return True

    @property
    def duration(self) -> float:
        return time.perf_counter() - self.init_start_time

    # -- public ToolBackend surface ----------------------------------------

    def run_bash(self, command: str, timeout: float = 60.0) -> BashResult:
        """Run a command inside the container's persistent shell.

        `timeout` is the per-command cap. On expiry the running command is
        abandoned and the shell is reset for the next call. None falls back to the
        session_timeout.

        Shell state (cwd, env vars, sourced venvs, defined functions) persists
        across calls because every command runs in the same long-lived shell.
        In FIFO mode that shell lives inside the container, so a mid-rollout x2p
        tunnel drop does not destroy it: restart_session() re-attaches and
        recover_last() finishes the interrupted command.
        """
        if self._destroyed:
            return _bash_result("error", "", "exit", exit_code=-1)
        # FIFO-backed persistent shell (the v1 drop-recovery path).
        if self._fifo_mode:
            if not self._sess_dir:
                return _bash_result(
                    "error", "session not initialized", "other", exit_code=-1
                )
            self._last_command = command
            self._last_timeout = timeout
            return self._fifo_run(command, timeout)
        # Legacy streamed session (image without bash+mkfifo).
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
        for tunnel in list(self._host_tunnels):
            try:
                self.close_host_tunnel(tunnel)
            except Exception:
                logger.exception("vacli: host tunnel teardown failed")
        # Stop the persistent session first so its bash + ssh subprocess exit
        # cleanly before we yank the container out from under them.
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                logger.exception("vacli: session stop failed")
        # FIFO mode: kill the in-container reader + held-writer explicitly. `podman
        # rm -f` below would also nuke them, but this is cheap insurance if rm fails.
        if self._fifo_mode:
            try:
                self._teardown_fifo_shell()
            except Exception:
                pass
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

    def read_file(self, remote_path: str | Path) -> bytes:
        """Read a file from the container without mixing SSH stderr into its bytes."""
        if self._destroyed:
            raise RuntimeError("read_file called after destroy")
        if self._container_id is None:
            raise RuntimeError("read_file called before container init")
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            f"podman exec {self._container_id} cat -- {shlex.quote(str(remote_path))}",
        ]
        result = self._sp.run(
            argv,
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=self.config.session_timeout,
        )
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"read_file failed (rc={result.returncode}, path={remote_path}): {err}"
            )
        return result.stdout or b""

    def open_host_tunnel(self, local_port: int) -> tuple[VacliHostTunnel, str]:
        """Make a host-local TCP service reachable from the VMVM container."""
        if self._destroyed:
            raise RuntimeError("open_host_tunnel called after destroy")
        if self._container_id is None:
            raise RuntimeError("open_host_tunnel called before container init")
        if not 1 <= local_port <= 65535:
            raise ValueError(f"invalid local port: {local_port}")
        gateway = self._proxy_gateway
        forward = f"127.0.0.1:0:127.0.0.1:{local_port}"
        result = self._sp.run(
            _ssh_opts(self._ssh_port, self._control_path)
            + ["-O", "forward", "-R", forward, "root@localhost"],
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=30,
        )
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            raise BackendInitError(
                f"could not expose host port {local_port} to VMVM container: {err}"
            )
        output = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        try:
            remote_port = int(output.splitlines()[-1])
        except (IndexError, ValueError) as error:
            raise BackendInitError(
                f"SSH did not report an allocated reverse-forward port: {output!r}"
            ) from error
        if not 1 <= remote_port <= 65535:
            raise BackendInitError(f"SSH allocated an invalid reverse-forward port: {remote_port}")

        relay_log = f"/tmp/vacli_host_tunnel_{remote_port}.log"
        relay_command = (
            "set -e; command -v socat >/dev/null; "
            f"nohup socat TCP-LISTEN:{remote_port},bind={gateway},reuseaddr,fork "
            f"TCP:127.0.0.1:{remote_port} >{shlex.quote(relay_log)} 2>&1 </dev/null & "
            'pid=$!; kill -0 "$pid"; printf "__VACLIPID=%s\\n" "$pid"'
        )
        relay = self._ssh_call_raw(relay_command, timeout=30)
        match = re.search(rb"__VACLIPID=(\d+)", relay.stdout or b"")
        if relay.returncode != 0 or match is None:
            self._cancel_host_forward(remote_port, local_port)
            detail = (relay.stdout or b"").decode("utf-8", errors="replace").strip()
            raise BackendInitError(f"could not start VMVM bridge relay: {detail}")

        tunnel = VacliHostTunnel(gateway, remote_port, local_port, int(match.group(1)))
        self._host_tunnels.add(tunnel)
        probe_script = (
            "import socket; "
            f"socket.create_connection(({gateway!r}, {remote_port}), timeout=1).close()"
        )
        probe_command = (
            f"podman exec {self._container_id} python -c {shlex.quote(probe_script)}"
        )
        deadline = time.monotonic() + 10
        last_error = "reverse forward was not reachable"
        while time.monotonic() < deadline:
            probe = self._ssh_call_raw(probe_command, timeout=5)
            if probe.returncode == 0:
                url = f"http://{gateway}:{remote_port}"
                logger.info("vacli: host tunnel up at %s", url)
                return tunnel, url
            last_error = (probe.stdout or b"").decode("utf-8", errors="replace").strip()
            time.sleep(0.2)

        self.close_host_tunnel(tunnel)
        raise BackendInitError(
            f"could not expose host port {local_port} to VMVM container: {last_error}"
        )

    def _restore_host_tunnels(self) -> bool:
        """Restore reverse forwards after the SSH control master is replaced."""
        for tunnel in self._host_tunnels:
            relay = self._ssh_call_raw(f"kill -0 {tunnel.relay_pid}", timeout=30)
            if relay.returncode != 0:
                logger.warning(
                    "vacli.restart_session: host bridge relay %d is not running",
                    tunnel.relay_pid,
                )
                return False
            forward = f"127.0.0.1:{tunnel.remote_port}:127.0.0.1:{tunnel.local_port}"
            result = self._sp.run(
                _ssh_opts(self._ssh_port, self._control_path)
                + ["-O", "forward", "-R", forward, "root@localhost"],
                stdin=self._sp.DEVNULL,
                stdout=self._sp.PIPE,
                stderr=self._sp.PIPE,
                timeout=30,
            )
            if result.returncode != 0:
                detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
                logger.warning(
                    "vacli.restart_session: could not restore host tunnel on port %d: %s",
                    tunnel.remote_port,
                    detail,
                )
                return False
            logger.info(
                "vacli.restart_session: restored host tunnel on port %d",
                tunnel.remote_port,
            )
        return True

    def close_host_tunnel(self, tunnel: object) -> None:
        if not isinstance(tunnel, VacliHostTunnel):
            raise TypeError(f"unexpected VMVM host tunnel: {type(tunnel).__name__}")
        self._host_tunnels.discard(tunnel)
        relay_log = f"/tmp/vacli_host_tunnel_{tunnel.remote_port}.log"
        relay = self._ssh_call_raw(
            f"kill {tunnel.relay_pid} 2>/dev/null || true; rm -f {shlex.quote(relay_log)}",
            timeout=30,
        )
        if relay.returncode != 0:
            detail = (relay.stdout or b"").decode("utf-8", errors="replace").strip()
            logger.warning("vacli: host bridge relay teardown failed: %s", detail)
        result = self._cancel_host_forward(tunnel.remote_port, tunnel.local_port)
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            logger.warning("vacli: host tunnel teardown failed: %s", err)
            return
        logger.info("vacli: host tunnel down (port=%d)", tunnel.remote_port)

    def _cancel_host_forward(
        self, remote_port: int, local_port: int
    ) -> subprocess.CompletedProcess:
        forward = f"127.0.0.1:{remote_port}:127.0.0.1:{local_port}"
        result = self._sp.run(
            _ssh_opts(self._ssh_port, self._control_path)
            + ["-O", "cancel", "-R", forward, "root@localhost"],
            stdin=self._sp.DEVNULL,
            stdout=self._sp.DEVNULL,
            stderr=self._sp.PIPE,
            timeout=30,
        )
        return result

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
        self._ensure_host_memory()
        used = _resolve_image_in_vm(
            self._sp,
            self._ssh_port,
            self._control_path,
            self.config.image_url,
            getattr(self.config, "fallback_image_url", None),
        )
        run_argv = ["podman", "run", "-d", "--network", "bridge"]
        if self.config.cpu is not None:
            run_argv.extend(["--cpus", str(self.config.cpu)])
            run_argv.extend(["--env", f"GOMAXPROCS={math.ceil(self.config.cpu)}"])
        if self.config.memory_gb is not None:
            run_argv.extend(["--memory", f"{self.config.memory_gb}g"])
        run_argv.extend(
            ["--entrypoint", "/bin/bash", used, "-c", "tail -f /dev/null"]
        )
        run = self._ssh_call_raw(
            shlex.join(run_argv),
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

    def _ensure_host_memory(self) -> None:
        """Back task memory above the VM tier's RAM with per-lease host swap."""
        if self.config.memory_gb is None:
            return
        required_mib = math.ceil(self.config.memory_gb * 1024) + HOST_MEMORY_HEADROOM_MIB
        script = f"""
set -eu
required_mib={required_mib}
current_mib=$(awk '/^(MemTotal|SwapTotal):/ {{ total += $2 }} END {{ print int(total / 1024) }}' /proc/meminfo)
if [ "$current_mib" -ge "$required_mib" ]; then
    exit 0
fi
swap_mib=$((required_mib - current_mib))
swap_path=/var/lib/containers/storage/vmvm-runtime.swap
if grep -q "^$swap_path " /proc/swaps; then
    exit 0
fi
rm -f "$swap_path"
: > "$swap_path"
if command -v chattr >/dev/null 2>&1; then
    chattr +C "$swap_path" 2>/dev/null || :
fi
dd if=/dev/zero of="$swap_path" bs=1M count="$swap_mib" status=none
chmod 600 "$swap_path"
mkswap "$swap_path" >/dev/null
swapon "$swap_path"
""".strip()
        result = self._ssh_call_raw(
            "bash -c " + shlex.quote(script),
            timeout=180,
        )
        if result.returncode != 0:
            detail = (result.stdout or b"").decode("utf-8", errors="replace").strip()
            raise BackendInitError(f"VMVM host swap setup failed: {detail[-1000:]}")

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
