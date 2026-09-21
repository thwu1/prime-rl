"""Job-local owner for reusable outer OCI-runner sessions."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import fcntl
import json
import os
import posixpath
import queue
import random
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sandoq_provider.ecr import ECRConfig, ECRCredentialCache
from sandoq_provider.gateway import SandoqHttpResponse, SandoqHttpTransportError, get_gateway_adapter
from sandoq_provider.secrets import read_secret_file
from sandoq_provider.utils import duration_seconds, exception_http_status

GIB = 1024**3
_DEFAULT_GATEWAY_RETRY_ATTEMPTS = 15
_DEFAULT_GATEWAY_RETRY_INTERVAL_SECONDS = 2.0
_DEFAULT_ENVIRONMENT = "oci-runner-firecracker"
_DEFAULT_TOKEN_FILE = "~/.config/oci-runner/firecracker-token"


def default_socket_path() -> Path:
    job_id = os.environ.get("SLURM_JOB_ID") or f"local-{os.getpgid(0)}"
    directory = Path(os.environ.get("TMPDIR", "/tmp")) / f"oci-runner-pool-{os.getuid()}"
    return directory / f"{job_id}.sock"


def _owner_path(socket_path: Path) -> Path:
    return socket_path.with_suffix(socket_path.suffix + ".owner.json")


def _process_start_identity(pid: int) -> str | None:
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        fields = proc_stat.read_text().split()
    except OSError:
        fields = []
    if len(fields) > 21:
        return f"linux:{fields[21]}"
    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return f"ps:{value}" if completed.returncode == 0 and value else None


def _read_owner(socket_path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(_owner_path(socket_path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _owner_is_live(owner: dict[str, object] | None) -> bool:
    if owner is None:
        return False
    try:
        pid = int(owner["pid"])
        expected_identity = str(owner["process_start_identity"])
    except (KeyError, TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return _process_start_identity(pid) == expected_identity


@dataclass(frozen=True)
class PoolConfig:
    socket_path: Path
    wal_path: Path
    base_url: str
    environment: str
    token_file: Path
    lease_duration: str
    owner: str
    size: int
    min_size: int
    create_deadline_s: float
    drain_timeout_s: float
    heartbeat_timeout_s: float
    renewal_interval_s: float
    renewal_workers: int
    create_workers: int
    bootstrap_workers: int
    bootstrap_workers_per_image: int
    drain_workers: int
    gateway_retry_attempts: int
    gateway_retry_interval_s: float
    max_reuse_count: int
    reuse_jitter: int
    image_cache_max_entries: int
    event_log: Path | None
    ecr: ECRConfig
    managed_shell_recovery: bool = False

    @classmethod
    def from_env(cls) -> PoolConfig:
        socket_value = os.environ.get("OCI_RUNNER_POOL_SOCKET")
        socket_path = Path(socket_value).expanduser() if socket_value else default_socket_path()
        event_value = os.environ.get("OCI_RUNNER_POOL_EVENT_LOG")
        if event_value is None and os.environ.get("PRIME_RL_OUTPUT_DIR"):
            event_value = str(Path(os.environ["PRIME_RL_OUTPUT_DIR"]) / "pool_events.jsonl")
        if event_value is None:
            event_value = str(socket_path.with_suffix(".events.jsonl"))
        wal_value = os.environ.get("OCI_RUNNER_POOL_WAL")
        if wal_value is None and os.environ.get("PRIME_RL_OUTPUT_DIR"):
            job_id = os.environ.get("SLURM_JOB_ID") or f"local-{os.getpgid(0)}"
            wal_value = str(Path(os.environ["PRIME_RL_OUTPUT_DIR"]) / "control" / f"oci_pool_{job_id}.wal.jsonl")
        size = int(os.environ.get("OCI_RUNNER_POOL_SIZE", "32"))
        min_size = int(os.environ.get("OCI_RUNNER_POOL_MIN_SIZE", "0"))
        if not 0 <= min_size <= size:
            raise ValueError("OCI_RUNNER_POOL_MIN_SIZE must be between zero and OCI_RUNNER_POOL_SIZE")
        lease_duration = os.environ.get("OCI_RUNNER_LEASE_DURATION", "1h")
        lease_seconds = duration_seconds(lease_duration, 3600.0)
        renewal_interval_s = duration_seconds(
            os.environ.get("OCI_RUNNER_POOL_RENEW_INTERVAL"),
            min(lease_seconds / 3.0, 600.0),
        )
        renewal_workers = int(os.environ.get("OCI_RUNNER_POOL_RENEW_WORKERS", "16"))
        create_workers = int(os.environ.get("OCI_RUNNER_POOL_CREATE_WORKERS", "8"))
        bootstrap_workers = int(os.environ.get("OCI_RUNNER_POOL_BOOTSTRAP_WORKERS", "8"))
        bootstrap_workers_per_image = int(os.environ.get("OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE", "8"))
        drain_workers = int(os.environ.get("OCI_RUNNER_POOL_DRAIN_WORKERS", "32"))
        gateway_retry_attempts = int(
            os.environ.get("OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS", str(_DEFAULT_GATEWAY_RETRY_ATTEMPTS))
        )
        gateway_retry_interval_s = duration_seconds(
            os.environ.get("OCI_RUNNER_GATEWAY_RETRY_INTERVAL"),
            _DEFAULT_GATEWAY_RETRY_INTERVAL_SECONDS,
        )
        max_reuse_count = int(os.environ.get("OCI_RUNNER_POOL_MAX_REUSE_COUNT", "6"))
        reuse_jitter = int(os.environ.get("OCI_RUNNER_POOL_REUSE_JITTER", "2"))
        image_cache_max_entries = int(os.environ.get("OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES", "2"))
        managed_shell_recovery = os.environ.get("SANDOQ_LEASE_PROFILE") == "kimi-tb4-long"
        declared_shell_recovery = os.environ.get("OCI_RUNNER_MANAGED_SHELL_RECOVERY")
        if declared_shell_recovery is not None and declared_shell_recovery != ("1" if managed_shell_recovery else "0"):
            raise ValueError("OCI_RUNNER_MANAGED_SHELL_RECOVERY disagrees with SANDOQ_LEASE_PROFILE")
        if renewal_interval_s <= 0:
            raise ValueError("OCI_RUNNER_POOL_RENEW_INTERVAL must be positive")
        if renewal_workers < 1:
            raise ValueError("OCI_RUNNER_POOL_RENEW_WORKERS must be positive")
        if create_workers < 1:
            raise ValueError("OCI_RUNNER_POOL_CREATE_WORKERS must be positive")
        if bootstrap_workers < 1:
            raise ValueError("OCI_RUNNER_POOL_BOOTSTRAP_WORKERS must be positive")
        if bootstrap_workers_per_image < 1:
            raise ValueError("OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE must be positive")
        if drain_workers < 1:
            raise ValueError("OCI_RUNNER_POOL_DRAIN_WORKERS must be positive")
        if gateway_retry_attempts < 1:
            raise ValueError("OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS must be positive")
        if gateway_retry_interval_s < 0:
            raise ValueError("OCI_RUNNER_GATEWAY_RETRY_INTERVAL must be nonnegative")
        if max_reuse_count < 1:
            raise ValueError("OCI_RUNNER_POOL_MAX_REUSE_COUNT must be positive")
        if not 0 <= reuse_jitter < max_reuse_count:
            raise ValueError("OCI_RUNNER_POOL_REUSE_JITTER must be nonnegative and below the base reuse count")
        if image_cache_max_entries < 0:
            raise ValueError("OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES must be nonnegative")
        return cls(
            socket_path=socket_path,
            wal_path=Path(wal_value).expanduser() if wal_value else socket_path.with_suffix(".wal.jsonl"),
            base_url=os.environ.get("OCI_RUNNER_BASE_URL", "https://sandoq.eks-prod.cf.aws.metafb.cloud").rstrip("/"),
            environment=os.environ.get("OCI_RUNNER_ENVIRONMENT", _DEFAULT_ENVIRONMENT),
            token_file=Path(os.environ.get("OCI_RUNNER_TOKEN_FILE", _DEFAULT_TOKEN_FILE)).expanduser(),
            lease_duration=lease_duration,
            owner=os.environ.get("SANDOQ_OWNER") or os.environ.get("USER") or "prime-rl",
            size=size,
            min_size=min_size,
            create_deadline_s=duration_seconds(os.environ.get("OCI_RUNNER_CREATE_DEADLINE"), 600.0),
            drain_timeout_s=duration_seconds(os.environ.get("OCI_RUNNER_POOL_DRAIN_TIMEOUT"), 240.0),
            heartbeat_timeout_s=duration_seconds(os.environ.get("OCI_RUNNER_POOL_HEARTBEAT_TIMEOUT"), 45.0),
            renewal_interval_s=renewal_interval_s,
            renewal_workers=renewal_workers,
            create_workers=create_workers,
            bootstrap_workers=bootstrap_workers,
            bootstrap_workers_per_image=bootstrap_workers_per_image,
            drain_workers=drain_workers,
            gateway_retry_attempts=gateway_retry_attempts,
            gateway_retry_interval_s=gateway_retry_interval_s,
            max_reuse_count=max_reuse_count,
            reuse_jitter=reuse_jitter,
            image_cache_max_entries=image_cache_max_entries,
            event_log=Path(event_value).expanduser() if event_value else None,
            ecr=ECRConfig.from_env(),
            managed_shell_recovery=managed_shell_recovery,
        )


@dataclass
class Slot:
    slot_id: int
    generation: int = 0
    state: str = "new"
    outer_session_id: str | None = None
    exec_url: str | None = None
    port_urls: dict[str, str] = field(default_factory=dict)
    assignment_id: str | None = None
    reuse_count: int = 0
    reuse_threshold: int = 0
    request_id: str = ""
    images: dict[str, float] = field(default_factory=dict)
    created_at: float | None = None
    outer_missing: bool = False
    create_failures: int = 0
    next_create_at: float = 0.0
    delete_failures: int = 0
    next_delete_at: float = 0.0


@dataclass
class Assignment:
    assignment_id: str
    client_id: str
    slot_id: int
    requested_image: str
    acquired_at: float
    ticket_id: str | None = None
    shell_id: str | None = None
    shell_failure_status: str | None = None
    resolved_digest: str | None = None
    ready: bool = False
    shell_generation: int = 0
    shell_recovering: bool = False
    active_shell_operation: str | None = None
    active_shell_operation_deadline: float = 0.0
    managed_shell_failure_status: str | None = None
    managed_shell_recovery_count: int = 0


@dataclass
class AcquireWaiter:
    ticket_id: str
    client_id: str
    requested_image: str
    created_at: float
    expires_at: float
    response: dict[str, object] | None = None


class _EventWriter:
    """Single-writer batched telemetry sink kept off lease-critical paths."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.pending: queue.Queue[str | None] = queue.Queue(maxsize=10_000)
        self.dropped = 0
        self.state_lock = threading.Lock()
        self.closing = threading.Event()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.thread = threading.Thread(target=self._run, daemon=True, name="oci-pool-events")
            self.thread.start()

    def append(self, encoded: str) -> None:
        if self.path is None:
            return
        with self.state_lock:
            if self.stopped.is_set() or self.closing.is_set():
                self.dropped += 1
                return
            try:
                self.pending.put_nowait(encoded)
            except queue.Full:
                self.dropped += 1

    def flush(self, timeout: float = 5.0) -> None:
        del timeout
        if self.path is None:
            return
        self.pending.join()

    def close(self, timeout: float = 5.0) -> None:
        with self.state_lock:
            if self.thread is None or self.stopped.is_set():
                return
            self.closing.set()
            try:
                self.pending.put(None, timeout=max(timeout, 0.0))
            except queue.Full as exc:
                raise TimeoutError("OCI pool event queue did not accept its shutdown marker") from exc
        self.thread.join(timeout=timeout)
        if self.thread.is_alive() or not self.stopped.is_set():
            raise TimeoutError("OCI pool event writer did not flush before shutdown")

    def _run(self) -> None:
        assert self.path is not None
        with self.path.open("a", encoding="utf-8") as stream:
            while True:
                item = self.pending.get()
                if item is None:
                    self.pending.task_done()
                    break
                batch = [item]
                stop_after_batch = False
                while len(batch) < 256:
                    try:
                        following = self.pending.get_nowait()
                    except queue.Empty:
                        break
                    if following is None:
                        self.pending.task_done()
                        stop_after_batch = True
                        break
                    batch.append(following)
                stream.writelines(batch)
                stream.flush()
                for _ in batch:
                    self.pending.task_done()
                if stop_after_batch:
                    break
        self.stopped.set()


def _read_token(path: Path) -> str:
    return read_secret_file(path, "OCI runner token", RuntimeError)


class PoolBroker:
    def __init__(self, config: PoolConfig) -> None:
        self.config = config
        _read_token(config.token_file)
        self.process_start_identity = _process_start_identity(os.getpid())
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.slots = [Slot(slot_id=index) for index in range(config.size)]
        self.idle_slots: deque[int] = deque()
        self.assignments: dict[str, Assignment] = {}
        self.waiter_order: deque[str] = deque()
        self.waiters: dict[str, AcquireWaiter] = {}
        self.releasing_assignments: set[str] = set()
        self.release_results: dict[str, dict[str, object]] = {}
        self.clients: dict[str, float] = {}
        self.registered_clients: set[str] = set()
        self.accepting = False
        self.recovering = True
        self.draining = False
        self.stopped = threading.Event()
        self.started = False
        self._startup_stop = threading.Event()
        self._startup_done = threading.Event()
        self.departure_generation = 0
        self.drain_deletions: list[dict[str, object]] = []
        self.drain_failures: dict[int, str] = {}
        self.drain_deadline: float | None = None
        self.active_creates = 0
        self._wal_lock = threading.Lock()
        self._reconcile_event = threading.Event()
        self._maintenance_stop = threading.Event()
        self._reconcile_thread: threading.Thread | None = None
        self._maintenance_thread: threading.Thread | None = None
        self._create_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=config.create_workers,
            thread_name_prefix="oci-create",
        )
        self._delete_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=config.drain_workers,
            thread_name_prefix="oci-delete-retry",
        )
        self._event_writer = _EventWriter(config.event_log)
        self.ecr_credentials = {
            registry: ECRCredentialCache(config.ecr, registry) for registry in config.ecr.authenticated_registries
        }
        self.gateway = get_gateway_adapter(config.base_url, config.owner)

    def start(self) -> None:
        """Recover node-local state after the socket is bound, then begin warming."""
        with self.lock:
            if self.started:
                return
            self.started = True
        try:
            with self.lock:
                if self.draining or self._startup_stop.is_set() or self.stopped.is_set():
                    return
            self.config.socket_path.with_suffix(".drained.json").unlink(missing_ok=True)
            self._event(
                "pool_started",
                size=self.config.size,
                min_size=self.config.min_size,
                lease_duration=self.config.lease_duration,
                renewal_interval_seconds=self.config.renewal_interval_s,
                renewal_workers=self.config.renewal_workers,
                create_workers=self.config.create_workers,
                bootstrap_workers=self.config.bootstrap_workers,
                bootstrap_workers_per_image=self.config.bootstrap_workers_per_image,
                drain_workers=self.config.drain_workers,
                max_reuse_count=self.config.max_reuse_count,
                reuse_jitter=self.config.reuse_jitter,
                image_cache_max_entries=self.config.image_cache_max_entries,
                recovering=True,
            )
            while not self._startup_stop.is_set() and not self.stopped.is_set() and not self._recover_orphans():
                self._event("pool_recovery_retry", retry_delay_seconds=5.0)
                self._startup_stop.wait(5.0)
            with self.changed:
                if self.draining or self._startup_stop.is_set() or self.stopped.is_set():
                    return
                self.recovering = False
                self.accepting = True
                self._event("pool_recovery_completed", accepting=True)
                self._reconcile_thread = threading.Thread(
                    target=self._reconcile_loop,
                    daemon=True,
                    name="oci-pool-reconciler",
                )
                self._maintenance_thread = threading.Thread(
                    target=self._maintenance_loop,
                    daemon=True,
                    name="oci-pool-maintenance",
                )
                self._reconcile_thread.start()
                self._maintenance_thread.start()
                self.changed.notify_all()
            self._reconcile_event.set()
        finally:
            self._startup_done.set()

    def _event(self, event: str, **values: object) -> None:
        if self.config.event_log is None:
            return
        row = {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": event,
            "timestamp": time.time(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "wandb_run_id": os.environ.get("WANDB_SHARED_RUN_ID"),
            **values,
        }
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        writer = getattr(self, "_event_writer", None)
        if writer is not None:
            writer.append(encoded)
            return
        self.config.event_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config.event_log, "a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.write(encoded)
                stream.flush()
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _wal_event(self, event: str, **values: object) -> None:
        row = {
            "schema_version": 2,
            "event": event,
            "timestamp": time.time(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "wandb_run_id": os.environ.get("WANDB_SHARED_RUN_ID"),
            **values,
        }
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        self.config.wal_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._wal_lock, self.config.wal_path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def _recover_orphans(self) -> bool:
        path = self.config.wal_path
        if not path.exists():
            return True
        live: dict[str, tuple[int | None, int | None]] = {}
        generations: dict[int, int] = {}
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = row.get("outer_session_id")
                if not isinstance(session_id, str):
                    continue
                if row.get("event") == "outer_created":
                    slot_id = row.get("slot_id")
                    generation = row.get("generation")
                    live[session_id] = (
                        slot_id if isinstance(slot_id, int) else None,
                        generation if isinstance(generation, int) else None,
                    )
                    if isinstance(slot_id, int) and isinstance(generation, int):
                        generations[slot_id] = max(generations.get(slot_id, 0), generation)
                elif row.get("event") == "outer_deleted":
                    live.pop(session_id, None)
        for slot_id, generation in generations.items():
            if 0 <= slot_id < len(self.slots):
                self.slots[slot_id].generation = generation
        if not live:
            return True
        self._event("pool_recovery_started", orphan_count=len(live))
        deadline = time.monotonic() + self.config.drain_timeout_s

        def recover(session_id: str) -> tuple[str, Exception | None]:
            try:
                self._delete_outer(session_id, deadline=deadline)
                self._wal_event("outer_deleted", outer_session_id=session_id, reason="broker_recovery")
                return session_id, None
            except Exception as exc:
                return session_id, exc

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.config.drain_workers, len(live)),
            thread_name_prefix="oci-recovery",
        )
        futures = {executor.submit(recover, session_id): session_id for session_id in sorted(live)}
        failed: set[str] = set()
        done, pending = concurrent.futures.wait(
            futures,
            timeout=max(deadline - time.monotonic(), 0.0),
        )
        for future in done:
            expected_session_id = futures[future]
            try:
                session_id, error = future.result()
            except concurrent.futures.CancelledError:
                failed.add(expected_session_id)
                continue
            if error is None:
                self._event("outer_deleted", outer_session_id=session_id, reason="broker_recovery")
            else:
                failed.add(session_id)
                self._event(
                    "outer_delete_failed", outer_session_id=session_id, reason="broker_recovery", error=str(error)
                )
        for future in pending:
            failed.add(futures[future])
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        if failed:
            self._event("pool_recovery_incomplete", remaining_orphans=len(failed))
        return not failed

    def _start_create(self, slot: Slot) -> None:
        with self.lock:
            if self.draining or slot.state not in {"new", "poisoned"}:
                return
            if slot.outer_session_id is not None:
                return
            slot.next_create_at = 0.0
        self._reconcile_event.set()

    def _desired_capacity_locked(self) -> int:
        return min(self.config.size, max(self.config.min_size, len(self.assignments) + len(self.waiter_order)))

    def _reconcile_creates(self) -> float | None:
        with self.lock:
            if self.draining or self.recovering:
                return None
            active_capacity = sum(slot.state in {"creating", "idle", "assigned", "recycling"} for slot in self.slots)
            needed = self._desired_capacity_locked() - active_capacity
            available_workers = self.config.create_workers - self.active_creates
            launch_count = min(max(needed, 0), max(available_workers, 0))
            now = time.monotonic()
            candidates = [
                slot
                for slot in self.slots
                if slot.state == "new" and slot.outer_session_id is None and slot.next_create_at <= now
            ][:launch_count]
            next_retry = min(
                (
                    slot.next_create_at
                    for slot in self.slots
                    if slot.state == "new" and slot.outer_session_id is None and slot.next_create_at > now
                ),
                default=None,
            )
            for slot in candidates:
                slot.state = "creating"
                if not slot.request_id:
                    slot.generation += 1
                    slot.request_id = f"oci-pool-{self.config.socket_path.stem}-{slot.slot_id}-{slot.generation}"
                    slot.reuse_threshold = random.randint(
                        max(1, self.config.max_reuse_count - self.config.reuse_jitter),
                        self.config.max_reuse_count + self.config.reuse_jitter,
                    )
                slot.outer_missing = False
                self.active_creates += 1
                self._create_executor.submit(self._create_slot, slot)
            return next_retry

    def _reconcile_loop(self) -> None:
        while not self.stopped.is_set():
            next_retry = self._reconcile_creates()
            timeout = 5.0
            if next_retry is not None:
                timeout = min(timeout, max(next_retry - time.monotonic(), 0.01))
            self._reconcile_event.wait(timeout)
            self._reconcile_event.clear()

    def _append_idle_locked(self, slot: Slot) -> None:
        slot.state = "idle"
        if not hasattr(self, "idle_slots"):
            self.idle_slots = deque()
        self.idle_slots.append(slot.slot_id)
        if hasattr(self, "waiter_order"):
            self._assign_waiters_locked()

    def _take_idle_locked(self) -> Slot | None:
        while self.idle_slots:
            slot = self.slots[self.idle_slots.popleft()]
            if slot.state == "idle" and slot.outer_session_id and slot.exec_url:
                return slot
        return None

    def _unready_counts_locked(self) -> tuple[int, dict[str, int]]:
        by_image: dict[str, int] = {}
        total = 0
        for assignment in self.assignments.values():
            if assignment.ready:
                continue
            total += 1
            by_image[assignment.requested_image] = by_image.get(assignment.requested_image, 0) + 1
        return total, by_image

    def _expire_waiters_locked(self) -> None:
        now = time.monotonic()
        retained: deque[str] = deque()
        while self.waiter_order:
            ticket_id = self.waiter_order.popleft()
            waiter = self.waiters.get(ticket_id)
            if waiter is None:
                continue
            if waiter.expires_at <= now:
                self.waiters.pop(ticket_id, None)
                continue
            retained.append(ticket_id)
        self.waiter_order = retained

    def _assign_waiters_locked(self) -> None:
        self._expire_waiters_locked()
        while self.accepting and self.idle_slots and self.waiter_order:
            unready, by_image = self._unready_counts_locked()
            if unready >= self.config.bootstrap_workers:
                return
            selected: AcquireWaiter | None = None
            for _ in range(len(self.waiter_order)):
                ticket_id = self.waiter_order.popleft()
                waiter = self.waiters.get(ticket_id)
                if waiter is None or waiter.response is not None:
                    continue
                if waiter.client_id not in self.clients:
                    self.waiters.pop(ticket_id, None)
                    continue
                if by_image.get(waiter.requested_image, 0) >= self.config.bootstrap_workers_per_image:
                    self.waiter_order.append(ticket_id)
                    continue
                selected = waiter
                break
            if selected is None:
                return
            slot = self._take_idle_locked()
            if slot is None:
                self.waiter_order.appendleft(selected.ticket_id)
                return
            assignment_id = "assignment-" + uuid.uuid4().hex
            slot.state = "assigned"
            slot.assignment_id = assignment_id
            slot.reuse_count += 1
            assignment = Assignment(
                assignment_id=assignment_id,
                client_id=selected.client_id,
                slot_id=slot.slot_id,
                requested_image=selected.requested_image,
                acquired_at=time.time(),
                ticket_id=selected.ticket_id,
            )
            self.assignments[assignment_id] = assignment
            selected.response = {
                "status": "assigned",
                "ticket_id": selected.ticket_id,
                "assignment_id": assignment_id,
                "outer_session_id": slot.outer_session_id,
                "exec_url": slot.exec_url,
                "port_urls": slot.port_urls,
                "slot_id": slot.slot_id,
                "generation": slot.generation,
                "reuse_count": slot.reuse_count,
                "reuse_threshold": slot.reuse_threshold or self.config.max_reuse_count,
                "pool_wait_seconds": time.monotonic() - selected.created_at,
                "outer_age_seconds": (max(time.time() - slot.created_at, 0.0) if slot.created_at is not None else None),
            }
            by_image[selected.requested_image] = by_image.get(selected.requested_image, 0) + 1
            unready += 1
            # Capture the count while the assignment table is still protected by
            # ``self.lock``.  Replaying acquired/released event order is not an
            # authoritative concurrency measurement because release telemetry is
            # emitted after the slot is made available to another waiter.
            self._event(
                "assignment_acquired",
                **selected.response,
                requested_image=selected.requested_image,
                active_assignment_count=len(self.assignments),
            )

    def _create_slot(self, slot: Slot) -> None:
        try:
            session = self.gateway.create_session(
                self.config.environment,
                self.config.lease_duration,
                slot.request_id,
                timeout=self.config.create_deadline_s,
            )
            outer_id = session.session_id
            port_urls = dict(session.port_urls)
            exec_url = str(port_urls.get("exec") or "")
            if not outer_id:
                raise RuntimeError(f"outer lease returned incomplete connection data: {session.raw}")
            with self.changed:
                slot.outer_session_id = outer_id
                slot.port_urls = port_urls
                # Keep the newly-created lease hidden behind the slot lock until
                # its recovery identity is durable. If the WAL write fails, the
                # exception path retains the lease on a poisoned slot for cleanup.
                self._wal_event(
                    "outer_created",
                    outer_session_id=outer_id,
                    slot_id=slot.slot_id,
                    generation=slot.generation,
                    request_id=slot.request_id,
                    reuse_threshold=slot.reuse_threshold,
                )
            if not exec_url:
                self._delete_slot(slot, "incomplete_connection_data")
                raise RuntimeError(f"outer lease returned incomplete connection data: {session.raw}")
            if not exec_url.endswith("/"):
                exec_url += "/"
            with self.changed:
                slot.exec_url = exec_url
                slot.created_at = time.time()
                slot.reuse_count = 0
                slot.create_failures = 0
                slot.next_create_at = 0.0
                self._event(
                    "outer_created",
                    outer_session_id=outer_id,
                    slot_id=slot.slot_id,
                    generation=slot.generation,
                    request_id=slot.request_id,
                    reuse_threshold=slot.reuse_threshold,
                    create_retry_count=session.raw.get("_retry_count"),
                )
                create_retry_count = int(session.raw.get("_retry_count", 0) or 0)
                if create_retry_count:
                    self._event(
                        "capacity_backpressure",
                        outer_session_id=outer_id,
                        slot_id=slot.slot_id,
                        generation=slot.generation,
                        request_id=slot.request_id,
                        retry_count=create_retry_count,
                    )
                if self.draining:
                    delete_immediately = True
                else:
                    self._append_idle_locked(slot)
                    delete_immediately = False
                    self.changed.notify()
            if delete_immediately:
                self._delete_slot(slot, "drain_during_create", deadline=self.drain_deadline)
        except Exception as exc:
            http_status = exception_http_status(exc)
            with self.changed:
                if slot.outer_session_id:
                    slot.state = "poisoned"
                else:
                    slot.state = "new" if not self.draining else "drained"
                    slot.create_failures += 1
                    if http_status == 429:
                        retry_ceiling = min(600.0, 0.5 * 2 ** min(slot.create_failures, 11))
                        retry_delay = random.uniform(0.0, retry_ceiling)
                    else:
                        retry_ceiling = min(30.0, 0.5 * 2 ** min(slot.create_failures, 6))
                        retry_delay = retry_ceiling * random.uniform(0.75, 1.25)
                    slot.next_create_at = time.monotonic() + retry_delay
                if self.draining and slot.outer_session_id is not None:
                    self.drain_failures[slot.slot_id] = str(exc)
                self.changed.notify()
            self._event(
                "capacity_backpressure" if http_status == 429 else "outer_create_failed",
                outer_session_id=slot.outer_session_id,
                slot_id=slot.slot_id,
                generation=slot.generation,
                request_id=slot.request_id,
                http_status=http_status,
                error=str(exc),
            )
        finally:
            with self.changed:
                self.active_creates = max(self.active_creates - 1, 0)
                self.changed.notify_all()
            self._reconcile_event.set()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {_read_token(self.config.token_file)}"}

    def _request_json_idempotent(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
        retry_stats: dict[str, int] | None = None,
    ) -> SandoqHttpResponse:
        """Retry broker-owned replay-safe requests within one absolute deadline."""
        deadline = time.monotonic() + timeout
        last_response: SandoqHttpResponse | None = None
        last_error: SandoqHttpTransportError | None = None
        for attempt in range(self.config.gateway_retry_attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = self.gateway.request_json(
                    method,
                    url,
                    body=body,
                    headers=headers,
                    timeout=remaining,
                )
            except SandoqHttpTransportError as exc:
                last_error = exc
                last_response = None
            else:
                last_response = response
                last_error = None
                if response.status_code not in (502, 503):
                    return response
            if attempt + 1 >= self.config.gateway_retry_attempts:
                break
            if retry_stats is not None:
                retry_stats["retry_count"] = retry_stats.get("retry_count", 0) + 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.config.gateway_retry_interval_s, remaining))
        if retry_stats is not None:
            retry_stats["exhausted_count"] = retry_stats.get("exhausted_count", 0) + 1
        if last_error is not None:
            raise last_error from None
        if last_response is not None:
            return last_response
        raise TimeoutError("OCI runner pool gateway retry deadline expired")

    def _outer_exec(
        self,
        slot: Slot,
        command: str,
        timeout: float = 60.0,
        *,
        retry_stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if slot.exec_url is None:
            raise RuntimeError("slot has no exec URL")
        response = self._request_json_idempotent(
            "POST",
            slot.exec_url + "v1/exec",
            body={"command": ["bash", "-lc", command], "timeout": int(timeout)},
            headers=self._auth_headers(),
            timeout=timeout + 30.0,
            retry_stats=retry_stats,
        )
        status, body = response.status_code, response.body
        result = body.get("result") if isinstance(body.get("result"), dict) else body
        exit_code = result.get("exitCode", result.get("exit_code"))
        if status != 200 or exit_code != 0 or result.get("timedOut", result.get("timed_out", False)):
            raise RuntimeError(f"outer cleanup command failed: HTTP {status}: {body}")
        return result

    def _delete_shell(
        self,
        slot: Slot,
        shell_id: str,
        *,
        retry_stats: dict[str, int] | None = None,
    ) -> None:
        if slot.exec_url is None:
            raise RuntimeError("slot has no exec URL")
        response = self._request_json_idempotent(
            "DELETE",
            f"{slot.exec_url}v1/shells/{shell_id}",
            headers=self._auth_headers(),
            timeout=30.0,
            retry_stats=retry_stats,
        )
        status, body = response.status_code, response.body
        if status not in (204, 404):
            raise RuntimeError(f"persistent shell deletion failed: HTTP {status}, expected 204 or 404: {body}")

    def _delete_outer(self, session_id: str, *, deadline: float | None = None) -> None:
        timeout = max(self.config.drain_timeout_s, 30.0)
        overall_timeout = None
        if deadline is not None:
            overall_timeout = max(deadline - time.monotonic(), 0.1)
            timeout = min(timeout, overall_timeout)
        self.gateway.delete_session(
            session_id,
            timeout=timeout,
            prime=True,
            overall_timeout=overall_timeout,
        )

    @staticmethod
    def _schedule_delete_retry_locked(slot: Slot) -> None:
        slot.state = "poisoned"
        slot.delete_failures += 1
        retry_ceiling = min(300.0, 5.0 * 2 ** min(slot.delete_failures - 1, 6))
        slot.next_delete_at = time.monotonic() + retry_ceiling * random.uniform(0.75, 1.25)

    def _delete_slot(
        self,
        slot: Slot,
        reason: str,
        *,
        deadline: float | None = None,
    ) -> dict[str, object]:
        with self.changed:
            while slot.state == "deleting" and slot.outer_session_id:
                if deadline is None:
                    self.changed.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"outer deletion is already in progress for slot {slot.slot_id}")
                self.changed.wait(timeout=remaining)
            session_id = slot.outer_session_id
            if not session_id:
                slot.state = "drained" if self.draining else "new"
                self.changed.notify_all()
                return {"outer_session_id": None, "verified_http_status": 404}
            slot.state = "deleting"
        try:
            self._delete_outer(session_id, deadline=deadline)
        except Exception as exc:
            self._event(
                "outer_delete_failed",
                outer_session_id=session_id,
                slot_id=slot.slot_id,
                generation=slot.generation,
                reason=reason,
                error=str(exc),
            )
            with self.changed:
                # Keep the identity and connection metadata so final drain (or
                # broker recovery from the ledger) can retry the same outer.
                # An untyped 404 or transient error is never permission to
                # reuse the slot or replace it with an untracked lease.
                self._schedule_delete_retry_locked(slot)
                self.changed.notify_all()
            raise
        else:
            try:
                self._wal_event(
                    "outer_deleted",
                    outer_session_id=session_id,
                    slot_id=slot.slot_id,
                    generation=slot.generation,
                    reason=reason,
                )
            except Exception:
                # Keep the identity until its tombstone is durable. A retry is
                # safe because deletion is idempotent and a typed 404 succeeds.
                with self.changed:
                    self._schedule_delete_retry_locked(slot)
                    self.changed.notify_all()
                raise
            self._event(
                "outer_deleted",
                outer_session_id=session_id,
                slot_id=slot.slot_id,
                generation=slot.generation,
                reason=reason,
                verified_http_status=404,
            )
            response = {"outer_session_id": session_id, "verified_http_status": 404}
            if reason == "drain_during_create":
                with self.lock:
                    self.drain_deletions.append(response)
            with self.changed:
                slot.outer_session_id = None
                slot.exec_url = None
                slot.port_urls.clear()
                slot.assignment_id = None
                slot.images.clear()
                slot.created_at = None
                slot.reuse_count = 0
                slot.reuse_threshold = 0
                slot.request_id = ""
                slot.outer_missing = False
                slot.create_failures = 0
                slot.next_create_at = 0.0
                slot.delete_failures = 0
                slot.next_delete_at = 0.0
                slot.state = "drained" if self.draining else "new"
                self.changed.notify()
            self._reconcile_event.set()
            return response

    def _storage_bytes(self, slot: Slot) -> int:
        result = self._outer_exec(
            slot,
            "du -sb /home/runner/.local/share/containers/storage 2>/dev/null | awk '{print $1}'",
            30.0,
        )
        try:
            return int(str(result.get("stdout") or "0").strip() or "0")
        except ValueError:
            return 0

    def _prune_images(self, slot: Slot) -> None:
        storage_bytes = self._storage_bytes(slot)
        storage_target = 30 * GIB if storage_bytes > 45 * GIB else None
        if len(slot.images) <= self.config.image_cache_max_entries and storage_target is None:
            return
        pruned = False
        for image, _ in sorted(slot.images.items(), key=lambda item: item[1]):
            self._outer_exec(slot, f"podman image rm {shlex.quote(image)} >/dev/null 2>&1 || true", 120.0)
            slot.images.pop(image, None)
            pruned = True
            storage_bytes = self._storage_bytes(slot)
            entries_bounded = len(slot.images) <= self.config.image_cache_max_entries
            storage_bounded = storage_target is None or storage_bytes < storage_target
            if entries_bounded and storage_bounded:
                break
        if pruned:
            self._outer_exec(slot, "podman image prune -f >/dev/null", 120.0)

    def register(self, client_id: str) -> dict[str, object]:
        with self.changed:
            if self.draining:
                raise RuntimeError("OCI runner pool is draining")
            self.clients[client_id] = time.monotonic()
            self.registered_clients.add(client_id)
            return {"registered": True, "pool_size": self.config.size, "recovering": self.recovering}

    def heartbeat(self, client_id: str) -> dict[str, object]:
        with self.lock:
            if client_id not in self.clients:
                raise RuntimeError("pool client is not registered")
            self.clients[client_id] = time.monotonic()
        return {"heartbeat": True}

    def ecr_credential(self, client_id: str, assignment_id: str, registry: str) -> dict[str, object]:
        with self.lock:
            assignment = self.assignments.get(assignment_id)
            if assignment is None or assignment.client_id != client_id:
                raise RuntimeError("unknown pool assignment")
        cache = self.ecr_credentials.get(registry)
        if cache is None:
            raise RuntimeError(f"ECR registry is not configured for authentication: {registry!r}")
        credential = cache.get()
        with self.lock:
            assignment = self.assignments.get(assignment_id)
            if assignment is None or assignment.client_id != client_id:
                raise RuntimeError("unknown pool assignment")
            self._event(
                "ecr_credential_vended",
                assignment_id=assignment_id,
                registry=registry,
                source=credential["source"],
                generation=credential["generation"],
                reused=credential["reused"],
                age_seconds=credential["age_seconds"],
            )
        return credential

    def acquire(
        self,
        client_id: str,
        requested_image: str,
        timeout_seconds: float | None = None,
        ticket_id: str | None = None,
    ) -> dict[str, object]:
        # Pool queueing is distinct from creating one outer session.  At large
        # logical capacities a bounded bootstrap cohort can legitimately take
        # longer than the per-session create deadline to reach a waiter.  Honor
        # the caller's end-to-end setup budget when it is supplied.
        acquire_timeout = max(timeout_seconds, 0.0) if timeout_seconds is not None else self.config.create_deadline_s
        now = time.monotonic()
        with self.lock:
            if client_id not in self.clients:
                raise RuntimeError("pool client is not registered")
            if self.draining or not self.accepting and not self.recovering:
                raise RuntimeError("OCI runner pool is not accepting acquisitions")
            normalized_ticket = ticket_id or "ticket-" + uuid.uuid4().hex
            waiter = self.waiters.get(normalized_ticket)
            if waiter is None:
                if acquire_timeout <= 0:
                    raise TimeoutError("OCI runner pool acquisition deadline expired")
                waiter = AcquireWaiter(
                    ticket_id=normalized_ticket,
                    client_id=client_id,
                    requested_image=requested_image,
                    created_at=now,
                    expires_at=now + acquire_timeout,
                )
                self.waiters[normalized_ticket] = waiter
                self.waiter_order.append(normalized_ticket)
            elif waiter.client_id != client_id or waiter.requested_image != requested_image:
                raise RuntimeError("pool acquisition ticket does not match the original request")
            if waiter.response is None and waiter.expires_at <= now:
                self.waiters.pop(normalized_ticket, None)
                raise TimeoutError("timed out waiting for an OCI runner pool slot")
            self._assign_waiters_locked()
            response = (
                dict(waiter.response)
                if waiter.response is not None
                else {
                    "status": "pending",
                    "ticket_id": normalized_ticket,
                    "recovering": self.recovering,
                    "poll_after_seconds": 0.1,
                }
            )
        self._reconcile_event.set()
        return response

    def cancel_acquire(self, client_id: str, ticket_id: str) -> dict[str, object]:
        assignment_to_cancel: Assignment | None = None
        with self.lock:
            waiter = self.waiters.get(ticket_id)
            if waiter is None:
                return {"cancelled": False, "ticket_id": ticket_id}
            if waiter.client_id != client_id:
                raise RuntimeError("pool acquisition ticket belongs to a different client")
            if waiter.response is not None:
                assignment_id = str(waiter.response["assignment_id"])
                assignment_to_cancel = self.assignments.get(assignment_id)
                if assignment_id in self.releasing_assignments:
                    # release() deliberately drops the lock while it performs
                    # remote cleanup. Do not make its slot idle underneath it.
                    return {
                        "cancelled": False,
                        "ticket_id": ticket_id,
                        "reason": "release_in_progress",
                    }
            self.waiters.pop(ticket_id, None)
            try:
                self.waiter_order.remove(ticket_id)
            except ValueError:
                pass
            if assignment_to_cancel is not None:
                slot = self.slots[assignment_to_cancel.slot_id]
                self.assignments.pop(assignment_to_cancel.assignment_id, None)
                slot.assignment_id = None
                slot.reuse_count = max(slot.reuse_count - 1, 0)
                self._event(
                    "assignment_cancelled",
                    assignment_id=assignment_to_cancel.assignment_id,
                    outer_session_id=slot.outer_session_id,
                    slot_id=slot.slot_id,
                    generation=slot.generation,
                    requested_image=assignment_to_cancel.requested_image,
                    cancellation_verified=True,
                )
                self._append_idle_locked(slot)
        self._reconcile_event.set()
        return {"cancelled": True, "ticket_id": ticket_id}

    def update(self, client_id: str, assignment_id: str, values: dict[str, object]) -> dict[str, object]:
        with self.changed:
            assignment = self.assignments.get(assignment_id)
            if assignment is None or assignment.client_id != client_id:
                raise RuntimeError("unknown pool assignment")
            if shell_id := values.get("shell_id"):
                normalized_shell_id = str(shell_id)
                if assignment.shell_id not in {None, normalized_shell_id}:
                    raise RuntimeError("managed shell replacement requires broker recovery")
                if assignment.shell_id is None and getattr(self.config, "managed_shell_recovery", False):
                    self._wal_event(
                        "managed_shell_bound",
                        assignment_id=assignment_id,
                        outer_session_id=self.slots[assignment.slot_id].outer_session_id,
                        slot_id=assignment.slot_id,
                        generation=self.slots[assignment.slot_id].generation,
                        shell_id=normalized_shell_id,
                        shell_generation=assignment.shell_generation,
                    )
                assignment.shell_id = normalized_shell_id
            if digest := values.get("resolved_digest"):
                assignment.resolved_digest = str(digest)
            slot = self.slots[assignment.slot_id]
            cached_images = values.get("cached_images")
            if isinstance(cached_images, list) and all(
                isinstance(image, str) and image and not any(c.isspace() for c in image) for image in cached_images
            ):
                images = list(dict.fromkeys(cached_images))
            else:
                images = [assignment.requested_image]
            cached_at = time.time()
            for image in images:
                slot.images[image] = cached_at
            if values.get("ready") is True and not assignment.ready:
                assignment.ready = True
                self._event(
                    "assignment_ready",
                    assignment_id=assignment_id,
                    slot_id=assignment.slot_id,
                    requested_image=assignment.requested_image,
                    bootstrap_seconds=max(time.time() - assignment.acquired_at, 0.0),
                )
                self._assign_waiters_locked()
        return {"updated": True}

    def begin_shell_command(
        self,
        client_id: str,
        assignment_id: str,
        expected_shell_id: str,
        *,
        timeout_seconds: float,
        request_timeout_seconds: float,
    ) -> dict[str, object]:
        if (
            not self.config.managed_shell_recovery
            or not expected_shell_id
            or not 0 < request_timeout_seconds <= timeout_seconds <= 300
        ):
            raise RuntimeError("managed shell command reservation is invalid")
        deadline = time.monotonic() + timeout_seconds
        with self.changed:
            while True:
                remaining = deadline - time.monotonic()
                # Never grant a reservation unless the caller still has its
                # complete original HTTP budget. Otherwise its local timeout
                # could release the token while the server-side command is
                # still allowed to run.
                if remaining < request_timeout_seconds:
                    raise TimeoutError("managed shell command reservation timed out")
                assignment = self.assignments.get(assignment_id)
                if assignment is None or assignment.client_id != client_id:
                    raise RuntimeError("unknown pool assignment")
                if assignment_id in self.releasing_assignments:
                    raise RuntimeError("pool assignment release is in progress")
                if assignment.managed_shell_failure_status is not None:
                    return {
                        "status": "terminal_failure",
                        "failure_status": assignment.managed_shell_failure_status,
                    }
                if assignment.shell_id != expected_shell_id:
                    if not assignment.shell_id:
                        raise RuntimeError("pool assignment has no managed shell")
                    return {
                        "status": "shell_replaced",
                        "shell_id": assignment.shell_id,
                        "shell_generation": assignment.shell_generation,
                    }
                if not assignment.shell_recovering and assignment.active_shell_operation is None:
                    operation_id = "shell-operation-" + uuid.uuid4().hex
                    assignment.active_shell_operation = operation_id
                    # The gateway request uses the remaining reservation
                    # budget. Keep a small broker-side completion grace so a
                    # request timing out at that boundary cannot race release.
                    assignment.active_shell_operation_deadline = deadline + 5.0
                    return {
                        "status": "authorized",
                        "operation_id": operation_id,
                        "shell_id": assignment.shell_id,
                        "shell_generation": assignment.shell_generation,
                        "request_timeout_seconds": request_timeout_seconds,
                        "operation_deadline_monotonic": assignment.active_shell_operation_deadline,
                    }
                self.changed.wait(timeout=min(remaining, 0.25))

    def complete_shell_command(
        self,
        client_id: str,
        assignment_id: str,
        operation_id: str,
    ) -> dict[str, object]:
        with self.changed:
            assignment = self.assignments.get(assignment_id)
            if assignment is None or assignment.client_id != client_id:
                if assignment_id in self.releasing_assignments:
                    return {"completed": False, "release_in_progress": True}
                raise RuntimeError("unknown pool assignment")
            if assignment.active_shell_operation != operation_id:
                raise RuntimeError("managed shell command reservation mismatch")
            assignment.active_shell_operation = None
            assignment.active_shell_operation_deadline = 0.0
            self.changed.notify_all()
            return {"completed": True}

    @staticmethod
    def _validated_managed_workdir(value: str) -> str:
        if (
            not value.startswith("/")
            or value != posixpath.normpath(value)
            or "\x00" in value
            or "\n" in value
            or "\r" in value
        ):
            raise RuntimeError("managed shell recovery workdir is invalid")
        return value

    @staticmethod
    def _managed_shell_ids(body: object) -> set[str]:
        value = body
        if isinstance(value, dict) and "result" in value:
            value = value["result"]
        if isinstance(value, dict) and "shells" in value:
            value = value["shells"]
        if not isinstance(value, list):
            raise RuntimeError("managed shell inventory response is invalid")
        shell_ids: set[str] = set()
        for item in value:
            if isinstance(item, str) and item:
                shell_id = item
            elif isinstance(item, dict):
                shell_id = item.get("shellId", item.get("id"))
                if not isinstance(shell_id, str) or not shell_id:
                    raise RuntimeError("managed shell inventory response is invalid")
            else:
                raise RuntimeError("managed shell inventory response is invalid")
            shell_ids.add(shell_id)
        return shell_ids

    def recover_managed_shell(
        self,
        client_id: str,
        assignment_id: str,
        expected_shell_id: str,
        *,
        workdir: str,
    ) -> dict[str, object]:
        if not self.config.managed_shell_recovery:
            raise RuntimeError("managed shell recovery is disabled")
        normalized_workdir = self._validated_managed_workdir(workdir)
        reservation_deadline = time.monotonic() + 300.0
        with self.changed:
            while True:
                assignment = self.assignments.get(assignment_id)
                if assignment is None or assignment.client_id != client_id:
                    raise RuntimeError("unknown pool assignment")
                if assignment_id in self.releasing_assignments:
                    raise RuntimeError("pool assignment release is in progress")
                if assignment.managed_shell_failure_status is not None:
                    raise RuntimeError("managed shell recovery previously failed")
                if assignment.shell_id != expected_shell_id:
                    if not assignment.shell_id:
                        raise RuntimeError("pool assignment has no managed shell")
                    return {
                        "status": "already_recovered",
                        "shell_id": assignment.shell_id,
                        "shell_generation": assignment.shell_generation,
                    }
                if not assignment.shell_recovering and assignment.active_shell_operation is None:
                    assignment.shell_recovering = True
                    slot = self.slots[assignment.slot_id]
                    outer_id = slot.outer_session_id
                    exec_url = slot.exec_url
                    slot_id = slot.slot_id
                    slot_generation = slot.generation
                    break
                remaining = reservation_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("managed shell recovery reservation timed out")
                self.changed.wait(timeout=min(remaining, 0.25))
        new_shell_id: str | None = None
        try:
            if not outer_id or not exec_url:
                raise RuntimeError("managed shell recovery outer session is unavailable")
            health = self.gateway.request_json(
                "GET",
                exec_url + "healthz",
                timeout=10.0,
            )
            shells = self.gateway.request_json(
                "GET",
                exec_url + "v1/shells",
                headers=self._auth_headers(),
                timeout=10.0,
            )
            if health.status_code != 200 or shells.status_code != 200:
                raise RuntimeError("managed shell recovery outer diagnostics failed")
            if expected_shell_id in self._managed_shell_ids(shells.body):
                raise RuntimeError("managed shell command outcome is ambiguous")
            created = self.gateway.request_json(
                "POST",
                exec_url + "v1/shells",
                body={"container": "task"},
                headers=self._auth_headers(),
                timeout=30.0,
            )
            body = created.body
            candidate = body.get("shellId", body.get("id")) if isinstance(body, dict) else None
            if created.status_code not in (200, 201) or not isinstance(candidate, str) or not candidate:
                raise RuntimeError("managed shell replacement creation failed")
            new_shell_id = candidate
            initialized = self._request_json_idempotent(
                "POST",
                exec_url + "v1/exec",
                body={"command": ["cd", normalized_workdir], "shellId": new_shell_id, "timeout": 30},
                headers=self._auth_headers(),
                timeout=60.0,
            )
            result = (
                initialized.body.get("result") if isinstance(initialized.body.get("result"), dict) else initialized.body
            )
            if (
                initialized.status_code != 200
                or not isinstance(result, dict)
                or result.get("exitCode", result.get("exit_code")) != 0
                or result.get("timedOut", result.get("timed_out", False)) is not False
            ):
                raise RuntimeError("managed shell replacement initialization failed")
            with self.changed:
                current = self.assignments.get(assignment_id)
                if current is not assignment or assignment_id in self.releasing_assignments:
                    raise RuntimeError("managed shell recovery assignment changed")
                next_generation = assignment.shell_generation + 1
                # Keep the broker lock across the durable transition and the
                # in-memory publication.  Release therefore cannot observe an
                # unrecorded replacement or race between the WAL append and
                # assignment update.
                self._wal_event(
                    "managed_shell_recovered",
                    assignment_id=assignment_id,
                    outer_session_id=outer_id,
                    slot_id=slot_id,
                    generation=slot_generation,
                    prior_shell_id=expected_shell_id,
                    shell_id=new_shell_id,
                    shell_generation=next_generation,
                )
                assignment.shell_id = new_shell_id
                assignment.shell_generation = next_generation
                assignment.managed_shell_recovery_count += 1
                self._event(
                    "managed_shell_recovered",
                    assignment_id=assignment_id,
                    outer_session_id=outer_id,
                    slot_id=slot_id,
                    generation=slot_generation,
                    shell_generation=next_generation,
                    recovery_count=assignment.managed_shell_recovery_count,
                )
                assignment.shell_recovering = False
                self.changed.notify_all()
            return {
                "status": "recovered",
                "shell_id": new_shell_id,
                "shell_generation": next_generation,
            }
        except Exception as error:
            if new_shell_id is not None:
                with contextlib.suppress(Exception):
                    self._delete_shell(slot, new_shell_id)
            with self.changed:
                current = self.assignments.get(assignment_id)
                if current is assignment:
                    assignment.managed_shell_failure_status = "managed_shell_recovery_failed"
                    assignment.shell_failure_status = "managed_shell_recovery_failed"
                    self._event(
                        "managed_shell_recovery_failed",
                        assignment_id=assignment_id,
                        outer_session_id=outer_id,
                        slot_id=slot_id,
                        generation=slot_generation,
                        error_type=type(error).__name__,
                    )
                    assignment.shell_recovering = False
                    self.changed.notify_all()
            raise RuntimeError("managed shell recovery failed") from error

    def _remember_release_locked(self, assignment_id: str, response: dict[str, object]) -> None:
        self.release_results[assignment_id] = dict(response)
        limit = max(self.config.size * 32, 1024)
        while len(self.release_results) > limit:
            self.release_results.pop(next(iter(self.release_results)))

    def release(
        self,
        client_id: str,
        assignment_id: str,
        *,
        poison: bool = False,
        reason: str = "release",
        shell_failure_status: str | None = None,
    ) -> dict[str, object]:
        started = time.monotonic()
        with self.changed:
            while assignment_id in self.releasing_assignments and not self.draining:
                self.changed.wait(timeout=0.25)
            if cached := self.release_results.get(assignment_id):
                return dict(cached)
            if assignment_id in self.releasing_assignments:
                return {
                    "status": "release_in_progress",
                    "assignment_id": assignment_id,
                    "nested_recycle_verified": False,
                    "shell_deleted": False,
                    "poisoned": True,
                    "duration": time.monotonic() - started,
                    "timings": {"nested_recycle": 0.0},
                }
            assignment = self.assignments.get(assignment_id)
            if assignment is None:
                if self.draining:
                    return {
                        "status": "already_released",
                        "assignment_id": assignment_id,
                        "nested_recycle_verified": False,
                        "shell_deleted": False,
                        "poisoned": True,
                        "duration": time.monotonic() - started,
                        "timings": {"nested_recycle": 0.0},
                    }
                raise RuntimeError("unknown pool assignment")
            if assignment.client_id != client_id and reason not in {"stale_client", "client_departure", "drain"}:
                raise RuntimeError("pool assignment belongs to a different client")
            self.releasing_assignments.add(assignment_id)
            serialization_deadline = max(
                time.monotonic() + self.config.drain_timeout_s,
                assignment.active_shell_operation_deadline + 5.0,
            )
            while assignment.shell_recovering or assignment.active_shell_operation is not None:
                now = time.monotonic()
                if assignment.active_shell_operation is not None and assignment.active_shell_operation_deadline <= now:
                    assignment.active_shell_operation = None
                    assignment.active_shell_operation_deadline = 0.0
                    assignment.managed_shell_failure_status = "managed_shell_operation_abandoned"
                    assignment.shell_failure_status = "managed_shell_operation_abandoned"
                    self._event(
                        "managed_shell_operation_abandoned",
                        assignment_id=assignment_id,
                        slot_id=assignment.slot_id,
                        shell_generation=assignment.shell_generation,
                    )
                    self.changed.notify_all()
                    continue
                remaining = serialization_deadline - time.monotonic()
                if remaining <= 0:
                    self.releasing_assignments.discard(assignment_id)
                    self.changed.notify_all()
                    raise TimeoutError("managed shell activity did not quiesce before release")
                self.changed.wait(timeout=min(remaining, 0.25))
            assignment.shell_failure_status = assignment.managed_shell_failure_status or shell_failure_status
            if assignment.managed_shell_failure_status is not None:
                poison = True
                reason = "managed_shell_lost"
            slot = self.slots[assignment.slot_id]
            slot.state = "recycling"
        recycle_verified = False
        shell_deleted = False
        gateway_retry_stats = {"retry_count": 0, "exhausted_count": 0}
        error: Exception | None = None
        try:
            if poison:
                raise RuntimeError(f"assignment was poisoned: {reason}")
            if slot.outer_missing:
                raise RuntimeError("outer session was authoritatively missing during renewal")
            if not assignment.shell_id:
                raise RuntimeError("assignment has no persistent shell to delete")
            self._delete_shell(slot, assignment.shell_id, retry_stats=gateway_retry_stats)
            shell_deleted = True
            assignment_dir = f"/home/runner/shared/.assignments/{assignment_id}"
            cleanup = "\n".join(
                [
                    "set -eu",
                    "podman rm -f task >/dev/null 2>&1 || true",
                    "rm -rf /home/runner/shared/.prime-rl-transfer " + assignment_dir,
                    "mkdir -p /home/runner/shared/.prime-rl-transfer",
                    'test -z "$(podman ps -aq --filter name=^task$)"',
                    'test -z "$(find /home/runner/shared/.prime-rl-transfer -mindepth 1 -print -quit)"',
                    f"test ! -e {assignment_dir}",
                ]
            )
            self._outer_exec(slot, cleanup, 120.0, retry_stats=gateway_retry_stats)
            recycle_verified = True
            self._prune_images(slot)
        except Exception as exc:
            error = exc
        with self.lock:
            if slot.outer_missing and recycle_verified:
                recycle_verified = False
                error = RuntimeError("outer session was authoritatively missing during renewal")
        release_generation = slot.generation
        release_reuse_count = slot.reuse_count
        reuse_threshold = slot.reuse_threshold or self.config.max_reuse_count
        retire_for_reuse = recycle_verified and release_reuse_count >= reuse_threshold
        with self.changed:
            self.assignments.pop(assignment_id, None)
            if assignment.ticket_id is not None:
                self.waiters.pop(assignment.ticket_id, None)
            slot.assignment_id = None
            if recycle_verified and not self.draining and not retire_for_reuse:
                self._append_idle_locked(slot)
                self.changed.notify()
            else:
                slot.state = "poisoned"
        deletion: dict[str, object] | None = None
        deletion_error: Exception | None = None
        if not recycle_verified:
            try:
                deletion = self._delete_slot(slot, f"poisoned:{reason}")
            except Exception as exc:
                deletion_error = exc
            else:
                with self.lock:
                    clients_remain = bool(self.clients)
                if not self.draining and clients_remain and reason not in {"drain", "signal_cleanup"}:
                    self._start_create(slot)
        elif retire_for_reuse:
            try:
                deletion = self._delete_slot(slot, "reuse_limit")
            except Exception as exc:
                deletion_error = exc
            else:
                with self.lock:
                    clients_remain = bool(self.clients)
                if not self.draining and clients_remain:
                    self._start_create(slot)
        deletion_confirmed = deletion is not None
        response: dict[str, object] = {
            "status": (
                "retired"
                if retire_for_reuse and deletion_confirmed
                else ("recycled" if recycle_verified and not retire_for_reuse else "poisoned")
            ),
            "assignment_id": assignment_id,
            "outer_session_id": deletion.get("outer_session_id") if deletion else slot.outer_session_id,
            "slot_id": slot.slot_id,
            "generation": release_generation,
            "reuse_count": release_reuse_count,
            "reuse_threshold": reuse_threshold,
            "nested_recycle_verified": recycle_verified,
            "shell_id": assignment.shell_id,
            "shell_generation": assignment.shell_generation,
            "managed_shell_recovery_count": assignment.managed_shell_recovery_count,
            "shell_deleted": shell_deleted,
            "shell_failure_status": assignment.shell_failure_status,
            "poisoned": not recycle_verified or deletion_error is not None,
            "outer_retired": retire_for_reuse and deletion_confirmed,
            "retirement_reason": ("reuse_limit" if retire_for_reuse and deletion_confirmed else None),
            "cleanup_gateway_retry_count": gateway_retry_stats["retry_count"],
            "cleanup_gateway_retry_exhausted_count": gateway_retry_stats["exhausted_count"],
            "duration": time.monotonic() - started,
        }
        response["timings"] = {"nested_recycle": response["duration"]}
        if deletion:
            response["outer_deletion_verified_http_status"] = deletion["verified_http_status"]
        if deletion_error is not None:
            response["error"] = f"outer deletion was not confirmed: {deletion_error}"
        elif error is not None:
            response["error"] = str(error)
        with self.changed:
            self._remember_release_locked(assignment_id, response)
            # Publish the terminal lifecycle row before declaring the release
            # complete. Drain waits on ``releasing_assignments``, so it cannot
            # close the event writer while this row is still pending enqueue.
            self._event("assignment_released", **response, reason=reason)
            self.releasing_assignments.discard(assignment_id)
            self.changed.notify_all()
        return response

    def depart(self, client_id: str) -> dict[str, object]:
        with self.changed:
            assignment_ids = [
                assignment.assignment_id
                for assignment in self.assignments.values()
                if assignment.client_id == client_id
            ]
            waiter_ids = [ticket_id for ticket_id, waiter in self.waiters.items() if waiter.client_id == client_id]
            for ticket_id in waiter_ids:
                self.waiters.pop(ticket_id, None)
                try:
                    self.waiter_order.remove(ticket_id)
                except ValueError:
                    pass
            self.clients.pop(client_id, None)
            no_clients = not self.clients
            reached_expected = len(self.registered_clients) >= max(self.config.min_size, 1)
            self.departure_generation += 1
            departure_generation = self.departure_generation
        for assignment_id in assignment_ids:
            try:
                self.release(client_id, assignment_id, poison=True, reason="client_departure")
            except Exception as exc:
                self._event("assignment_release_failed", assignment_id=assignment_id, error=str(exc))
        if no_clients and reached_expected:
            drain_result = self.drain("final_client_departure")
            return {"departed": True, "active_clients": 0, "drain": drain_result}
        if no_clients:
            drain_result = self._delayed_empty_drain(departure_generation)
            return {"departed": True, "active_clients": 0, "drain": drain_result}
        return {"departed": True, "active_clients": len(self.clients)}

    def _delayed_empty_drain(self, departure_generation: int) -> dict[str, object] | None:
        if self.stopped.wait(5.0):
            return None
        with self.lock:
            if self.clients or self.departure_generation != departure_generation or self.draining:
                return None
        return self.drain("last_partial_client_departure")

    def status(self) -> dict[str, object]:
        with self.lock:
            slot_counts: dict[str, int] = {}
            for slot in self.slots:
                slot_counts[slot.state] = slot_counts.get(slot.state, 0) + 1
            unready, by_image = self._unready_counts_locked()
            return {
                "accepting": self.accepting,
                "recovering": self.recovering,
                "draining": self.draining,
                "clients": len(self.clients),
                "assignments": len(self.assignments),
                "ready_assignments": len(self.assignments) - unready,
                "unready_assignments": unready,
                "unready_by_image": by_image,
                "waiters": len(self.waiter_order),
                "idle_queue": len(self.idle_slots),
                "active_creates": self.active_creates,
                "queued_creates": 0,
                "create_workers": self.config.create_workers,
                "bootstrap_workers": self.config.bootstrap_workers,
                "drain_workers": self.config.drain_workers,
                "slot_counts": slot_counts,
                "broker_threads": threading.active_count(),
                "event_queue_depth": self._event_writer.pending.qsize(),
                "event_records_dropped": self._event_writer.dropped,
                "slots": [asdict(slot) for slot in self.slots],
                "pid": os.getpid(),
                "process_start_identity": self.process_start_identity,
            }

    def _renew_outer(self, outer_id: str) -> None:
        started = time.monotonic()
        event_values: dict[str, object] = {
            "outer_session_id": outer_id,
            "renewal_status": None,
            "status_code": None,
            "expires_at": None,
            "response_received": None,
            "renewal_reason": None,
        }
        try:
            renewal = self.gateway.renew_lease(
                outer_id,
                self.config.lease_duration,
                timeout=30.0,
            )
            event_values.update(
                renewal_status=renewal.status.value,
                status_code=renewal.status_code,
                expires_at=renewal.expires_at,
                response_received=renewal.response_received,
                renewal_reason=renewal.server_reason,
            )
            if not renewal.ok:
                raise RuntimeError(f"official renewal status={renewal.status.value}")
            self._event(
                "outer_renewed",
                duration=time.monotonic() - started,
                **event_values,
            )
        except Exception as exc:
            is_session_not_found = getattr(self.gateway, "is_session_not_found", lambda error: False)
            authoritative_missing = is_session_not_found(exc)
            idle_missing_slot: Slot | None = None
            with self.lock:
                slot = next((slot for slot in self.slots if slot.outer_session_id == outer_id), None)
                still_live = slot is not None
                if authoritative_missing and slot is not None:
                    slot.outer_missing = True
                    if slot.state == "idle":
                        slot.state = "poisoned"
                        idle_missing_slot = slot
            if still_live:
                self._event(
                    "outer_renewal_failed",
                    duration=time.monotonic() - started,
                    **event_values,
                    authoritative_missing=authoritative_missing,
                    error=str(exc),
                )
            if idle_missing_slot is not None:
                try:
                    self._delete_slot(idle_missing_slot, "renewal_session_not_found")
                except Exception:
                    # _delete_slot records the failure and retains the poisoned
                    # identity for final drain or broker recovery.
                    return
                with self.lock:
                    should_replace = bool(self.clients) and not self.draining
                if should_replace:
                    self._start_create(idle_missing_slot)

    def _renew_outer_sessions(self, outer_ids: list[str]) -> None:
        if not outer_ids:
            return
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.config.renewal_workers, len(outer_ids))
        ) as executor:
            list(executor.map(self._renew_outer, outer_ids))

    def _retry_poisoned_slot(self, slot: Slot) -> None:
        try:
            self._delete_slot(slot, "poisoned_retry")
        except Exception:
            return
        with self.lock:
            should_replace = bool(self.clients) and not self.draining
        if should_replace:
            self._start_create(slot)

    def _schedule_poisoned_deletes(self, now: float) -> None:
        with self.changed:
            if self.draining:
                return
            candidates = [
                slot
                for slot in self.slots
                if slot.state == "poisoned"
                and slot.assignment_id is None
                and slot.outer_session_id is not None
                and slot.next_delete_at <= now
            ]
            for slot in candidates:
                # Claim the slot before submitting so consecutive maintenance
                # passes cannot schedule duplicate DELETE operations.
                slot.state = "delete_queued"
                self._delete_executor.submit(self._retry_poisoned_slot, slot)

    def _expire_abandoned_shell_operations(self, now: float) -> None:
        expired: list[tuple[str, Assignment]] = []
        with self.changed:
            for assignment_id, assignment in self.assignments.items():
                if assignment.active_shell_operation is not None and assignment.active_shell_operation_deadline <= now:
                    assignment.active_shell_operation = None
                    assignment.active_shell_operation_deadline = 0.0
                    assignment.managed_shell_failure_status = "managed_shell_operation_abandoned"
                    assignment.shell_failure_status = "managed_shell_operation_abandoned"
                    self._event(
                        "managed_shell_operation_abandoned",
                        assignment_id=assignment_id,
                        slot_id=assignment.slot_id,
                        shell_generation=assignment.shell_generation,
                    )
                    expired.append((assignment_id, assignment))
            if expired:
                self.changed.notify_all()

    def _maintenance_loop(self) -> None:
        renew_interval = self.config.renewal_interval_s
        last_renewal = 0.0
        while not self._maintenance_stop.wait(5.0) and not self.stopped.is_set():
            now = time.monotonic()
            with self.lock:
                if self.draining:
                    return
                self._expire_waiters_locked()
                stale_clients = [
                    client_id
                    for client_id, heartbeat in self.clients.items()
                    if now - heartbeat > self.config.heartbeat_timeout_s
                ]
            for client_id in stale_clients:
                with self.lock:
                    assignments = [
                        assignment.assignment_id
                        for assignment in self.assignments.values()
                        if assignment.client_id == client_id
                    ]
                    waiter_ids = [
                        ticket_id for ticket_id, waiter in self.waiters.items() if waiter.client_id == client_id
                    ]
                    for ticket_id in waiter_ids:
                        self.waiters.pop(ticket_id, None)
                        try:
                            self.waiter_order.remove(ticket_id)
                        except ValueError:
                            pass
                    self.clients.pop(client_id, None)
                for assignment_id in assignments:
                    try:
                        self.release(client_id, assignment_id, poison=True, reason="stale_client")
                    except Exception as exc:
                        self._event("assignment_release_failed", assignment_id=assignment_id, error=str(exc))
            with self.lock:
                drain_stale_pool = bool(stale_clients) and not self.clients and not self.draining
            if drain_stale_pool:
                self.drain("all_clients_stale")
                return
            with self.lock:
                retry_poisoned = not self.draining
            if retry_poisoned:
                self._schedule_poisoned_deletes(now)
            self._expire_abandoned_shell_operations(now)
            if now - last_renewal >= renew_interval:
                with self.lock:
                    outer_ids = [
                        slot.outer_session_id
                        for slot in self.slots
                        if slot.outer_session_id and slot.state not in {"poisoned", "delete_queued", "deleting"}
                    ]
                self._renew_outer_sessions([outer_id for outer_id in outer_ids if outer_id is not None])
                last_renewal = time.monotonic()

    def drain(self, reason: str = "signal") -> dict[str, object]:
        started = time.monotonic()
        with self.changed:
            if self.draining:
                return {"draining": True}
            self.accepting = False
            self.draining = True
            self.waiter_order.clear()
            self.waiters.clear()
            self.changed.notify_all()
        maintenance_stop = getattr(self, "_maintenance_stop", None)
        if maintenance_stop is not None:
            maintenance_stop.set()
        startup_stop = getattr(self, "_startup_stop", None)
        if startup_stop is not None:
            startup_stop.set()
        self._reconcile_event.set()
        deadline = time.monotonic() + self.config.drain_timeout_s
        self.drain_deadline = deadline
        startup_done = getattr(self, "_startup_done", None)
        startup_incomplete = False
        if self.started and startup_done is not None:
            startup_incomplete = not startup_done.wait(timeout=max(deadline - time.monotonic(), 0.0))
        maintenance_thread = getattr(self, "_maintenance_thread", None)
        maintenance_incomplete = False
        if maintenance_thread is not None and maintenance_thread is not threading.current_thread():
            maintenance_thread.join(timeout=max(deadline - time.monotonic(), 0.0))
            maintenance_incomplete = maintenance_thread.is_alive()
        assignment_deadline = deadline - min(60.0, self.config.drain_timeout_s / 4.0)
        with self.changed:
            while (self.assignments or self.releasing_assignments) and time.monotonic() < assignment_deadline:
                self.changed.wait(timeout=min(assignment_deadline - time.monotonic(), 0.25))

        abandoned: list[tuple[Assignment, str | None, int, int]] = []
        unserialized_slot_ids: set[int] = set()
        with self.lock:
            has_remaining_assignments = bool(self.assignments)
            incomplete_release_count = len(self.releasing_assignments)
        if has_remaining_assignments:
            with self.changed:
                for assignment in self.assignments.values():
                    slot = self.slots[assignment.slot_id]
                    abandoned.append((assignment, slot.outer_session_id, slot.generation, slot.reuse_count))
                    if assignment.shell_recovering or assignment.active_shell_operation is not None:
                        unserialized_slot_ids.add(slot.slot_id)
                    slot.assignment_id = None
                    slot.state = "poisoned"
                self.assignments.clear()
                self.changed.notify_all()

        slots = [slot for slot in self.slots if slot.outer_session_id and slot.slot_id not in unserialized_slot_ids]
        with self.lock:
            results = list(self.drain_deletions)
        failures: dict[int, str] = {
            slot_id: "managed shell activity did not quiesce before pool drain"
            for slot_id in sorted(unserialized_slot_ids)
        }
        if startup_incomplete:
            failures[-3] = "pool startup did not stop before the drain deadline"
        if maintenance_incomplete:
            failures[-2] = "pool maintenance did not stop before the drain deadline"
        if incomplete_release_count:
            failures[-1] = f"{incomplete_release_count} assignment releases exceeded the pool drain deadline"
        if slots:
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self.config.drain_workers, len(slots)),
                thread_name_prefix="oci-drain",
            )
            futures = {executor.submit(self._delete_slot, slot, reason, deadline=deadline): slot for slot in slots}
            done, pending = concurrent.futures.wait(
                futures,
                timeout=max(deadline - time.monotonic(), 0.0),
            )
            for future in done:
                slot = futures[future]
                try:
                    deletion = future.result()
                    # A maintenance deletion can win the race after ``slots``
                    # was snapshotted.  _delete_slot then returns the exact
                    # verified no-op receipt below; the real session tombstone
                    # is already durable and a synthetic ``null`` session must
                    # not be published in the final drain marker.
                    if deletion.get("outer_session_id") is None:
                        if deletion.get("verified_http_status") != 404:
                            raise RuntimeError("no-op outer deletion was not verified")
                    else:
                        results.append(deletion)
                except Exception as exc:
                    failures[slot.slot_id] = str(exc)
            for future in pending:
                slot = futures[future]
                failures[slot.slot_id] = "outer deletion exceeded pool drain deadline"
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        if abandoned:
            deleted_outer_ids = {result.get("outer_session_id") for result in results}
            for assignment, outer_session_id, generation, reuse_count in abandoned:
                deletion_verified = outer_session_id in deleted_outer_ids
                response: dict[str, object] = {
                    "status": "poisoned",
                    "assignment_id": assignment.assignment_id,
                    "outer_session_id": outer_session_id,
                    "slot_id": assignment.slot_id,
                    "generation": generation,
                    "reuse_count": reuse_count,
                    "nested_recycle_verified": False,
                    "shell_id": assignment.shell_id,
                    "shell_deleted": False,
                    "shell_failure_status": assignment.shell_failure_status or reason,
                    "poisoned": True,
                    "outer_deletion_verified_http_status": 404 if deletion_verified else None,
                    "duration": time.monotonic() - started,
                    "timings": {"nested_recycle": 0.0},
                }
                with self.changed:
                    self._remember_release_locked(assignment.assignment_id, response)
                    self.releasing_assignments.discard(assignment.assignment_id)
                    self.changed.notify_all()
                self._event(
                    "assignment_released",
                    **response,
                    reason=reason,
                )

        while time.monotonic() < deadline:
            with self.changed:
                if self.active_creates == 0:
                    break
                self.changed.wait(timeout=min(deadline - time.monotonic(), 0.25))
        with self.lock:
            known_deletions = {result.get("outer_session_id") for result in results}
            results.extend(
                result for result in self.drain_deletions if result.get("outer_session_id") not in known_deletions
            )
            failures.update(self.drain_failures)
            for slot in self.slots:
                if slot.state == "creating":
                    failures.setdefault(slot.slot_id, "outer creation was still active at the pool drain deadline")
        marker = self.config.socket_path.with_suffix(".drained.json")
        gateway_close_error_type: str | None = None
        event_writer_close_error: Exception | None = None
        try:
            if failures:
                marker.unlink(missing_ok=True)
                self._event(
                    "pool_drain_incomplete",
                    reason=reason,
                    deleted=len(results),
                    failures=failures,
                    event_records_dropped=getattr(self._event_writer, "dropped", 0),
                )
            else:
                self._event(
                    "pool_drained",
                    reason=reason,
                    deleted=len(results),
                    failures={},
                    event_records_dropped=getattr(self._event_writer, "dropped", 0),
                )
        finally:
            # Resource cleanup has already completed. Stop local workers and
            # flush telemetry before publishing the authoritative drain marker
            # so a successful marker cannot cover a partial event log.
            with contextlib.suppress(Exception):
                self._delete_executor.shutdown(wait=False, cancel_futures=True)
            with contextlib.suppress(Exception):
                self._create_executor.shutdown(wait=False, cancel_futures=True)
            try:
                self.gateway.close()
            except Exception as exc:
                # The official client's telemetry exporter may time out after
                # every session is already gone. Preserve only the non-secret
                # exception type for observability and keep the verified drain.
                gateway_close_error_type = type(exc).__name__
                with contextlib.suppress(Exception):
                    self._event("gateway_close_failed", error_type=gateway_close_error_type)
            finally:
                self.stopped.set()
                try:
                    self._event_writer.close()
                except Exception as exc:  # noqa: BLE001 - fail closed below
                    event_writer_close_error = exc
        event_records_dropped = getattr(self._event_writer, "dropped", 0)
        if failures or event_writer_close_error is not None:
            marker.unlink(missing_ok=True)
        else:
            marker.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "reason": reason,
                        "timestamp": time.time(),
                        "deleted": results,
                        "failures": {},
                        "event_records_dropped": event_records_dropped,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        if event_writer_close_error is not None:
            raise RuntimeError("OCI pool event log did not close cleanly") from event_writer_close_error
        response: dict[str, object] = {
            "drained": not failures,
            "deleted": results,
            "failures": failures,
        }
        if gateway_close_error_type is not None:
            response["gateway_close_error_type"] = gateway_close_error_type
        return response

    def dispatch(self, request: dict[str, Any]) -> dict[str, object]:
        operation = request.get("operation")
        client_id = str(request.get("client_id") or "")
        if operation == "ping":
            return {"pong": True, "recovering": self.recovering, "pid": os.getpid()}
        if operation == "register":
            return self.register(client_id)
        if operation == "heartbeat":
            return self.heartbeat(client_id)
        if operation == "ecr_credential":
            return self.ecr_credential(
                client_id,
                str(request["assignment_id"]),
                str(request["registry"]),
            )
        if operation == "acquire":
            timeout_seconds = request.get("timeout_seconds")
            return self.acquire(
                client_id,
                str(request["requested_image"]),
                float(timeout_seconds) if timeout_seconds is not None else None,
                str(request["ticket_id"]) if request.get("ticket_id") is not None else None,
            )
        if operation == "cancel_acquire":
            return self.cancel_acquire(client_id, str(request["ticket_id"]))
        if operation == "update":
            return self.update(client_id, str(request["assignment_id"]), dict(request.get("values") or {}))
        if operation == "begin_shell_command":
            return self.begin_shell_command(
                client_id,
                str(request["assignment_id"]),
                str(request["expected_shell_id"]),
                timeout_seconds=float(request["timeout_seconds"]),
                request_timeout_seconds=float(request["request_timeout_seconds"]),
            )
        if operation == "complete_shell_command":
            return self.complete_shell_command(
                client_id,
                str(request["assignment_id"]),
                str(request["operation_id"]),
            )
        if operation == "recover_managed_shell":
            return self.recover_managed_shell(
                client_id,
                str(request["assignment_id"]),
                str(request["expected_shell_id"]),
                workdir=str(request["workdir"]),
            )
        if operation == "release":
            return self.release(
                client_id,
                str(request["assignment_id"]),
                poison=bool(request.get("poison")),
                reason=str(request.get("reason") or "release"),
                shell_failure_status=(
                    str(request["shell_failure_status"]) if request.get("shell_failure_status") is not None else None
                ),
            )
        if operation == "depart":
            return self.depart(client_id)
        if operation == "status":
            return self.status()
        if operation == "drain":
            return self.drain(str(request.get("reason") or "request"))
        raise RuntimeError(f"unknown pool operation: {operation}")


class _AsyncUnixServer:
    """Multiplex persistent clients without dedicating one broker thread each."""

    _BLOCKING_OPERATIONS = {
        "begin_shell_command",
        "drain",
        "depart",
        "ecr_credential",
        "recover_managed_shell",
        "release",
    }

    def __init__(self, broker: PoolBroker) -> None:
        self.broker = broker
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=broker.config.drain_workers,
            thread_name_prefix="oci-request",
        )
        self.tasks: set[asyncio.Task[None]] = set()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        write_lock = asyncio.Lock()
        connection_tasks: set[asyncio.Task[None]] = set()
        try:
            while line := await reader.readline():
                task = asyncio.create_task(self._process(line, writer, write_lock))
                self.tasks.add(task)
                connection_tasks.add(task)
                task.add_done_callback(self.tasks.discard)
                task.add_done_callback(connection_tasks.discard)
        finally:
            if connection_tasks:
                await asyncio.gather(*connection_tasks, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _process(
        self,
        line: bytes,
        writer: asyncio.StreamWriter,
        write_lock: asyncio.Lock,
    ) -> None:
        request_id: object = None
        try:
            request = json.loads(line)
            request_id = request.get("request_id")
            if request.get("operation") in self._BLOCKING_OPERATIONS:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(self.executor, self.broker.dispatch, request)
            else:
                result = self.broker.dispatch(request)
            response = {"ok": True, "request_id": request_id, "result": result}
        except Exception as exc:
            response = {"ok": False, "request_id": request_id, "error": str(exc)}
        encoded = (json.dumps(response, separators=(",", ":")) + "\n").encode()
        try:
            async with write_lock:
                writer.write(encoded)
                await writer.drain()
        except (ConnectionError, OSError):
            return

    async def close(self) -> None:
        if self.tasks:
            _, pending = await asyncio.wait(self.tasks, timeout=self.broker.config.drain_timeout_s + 5.0)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        self.executor.shutdown(wait=False, cancel_futures=True)


def run_broker() -> None:
    config = PoolConfig.from_env()
    config.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.socket_path.parent.chmod(0o700)
    owner = _read_owner(config.socket_path)
    if config.socket_path.exists() and _owner_is_live(owner):
        raise RuntimeError(f"OCI runner pool broker already owns {config.socket_path}")
    config.socket_path.unlink(missing_ok=True)
    broker = PoolBroker(config)
    owner_path = _owner_path(config.socket_path)

    def stop(signum: int, _frame: object) -> None:
        threading.Thread(target=broker.drain, args=(f"signal_{signum}",), daemon=False).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, stop)

    async def serve() -> None:
        async_server = _AsyncUnixServer(broker)
        server = await asyncio.start_unix_server(async_server.handle, path=str(config.socket_path), backlog=512)
        config.socket_path.chmod(0o700)
        process_identity = broker.process_start_identity
        owner_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "process_start_identity": process_identity,
                    "socket_path": str(config.socket_path),
                },
                sort_keys=True,
            )
            + "\n"
        )
        owner_path.chmod(0o600)
        threading.Thread(target=broker.start, daemon=True, name="oci-pool-startup").start()
        try:
            while not broker.stopped.is_set():
                await asyncio.sleep(0.1)
            await asyncio.sleep(0)
        finally:
            server.close()
            await server.wait_closed()
            await async_server.close()

    try:
        asyncio.run(serve())
    finally:
        if not broker.draining:
            broker.drain("broker_exit")
        try:
            config.socket_path.unlink()
        except FileNotFoundError:
            pass
        current_owner = _read_owner(config.socket_path)
        if current_owner is not None and int(current_owner.get("pid", -1)) == os.getpid():
            owner_path.unlink(missing_ok=True)


class _PoolConnectionError(RuntimeError):
    pass


class PoolClient:
    def __init__(self, config: PoolConfig | None = None) -> None:
        self.config = config or PoolConfig.from_env()
        self.client_id = f"client-{os.getpid()}-{uuid.uuid4().hex}"
        self._closed = False
        self._reconnect_lock = threading.Lock()
        self._connection_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, queue.Queue[dict[str, object] | BaseException]] = {}
        self._connection: socket.socket | None = None
        self._reader: Any = None
        self._reader_thread: threading.Thread | None = None
        self._owner_pid = os.getpid()
        self._ensure_broker()
        self._request("register")
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True, name="oci-pool-heartbeat")
        self._heartbeat.start()

    def _raw_request(self, payload: dict[str, object], timeout: float = 30.0) -> dict[str, object]:
        if os.getpid() != self._owner_pid:
            self._reset_after_fork()
        deadline = time.monotonic() + timeout
        connection = self._ensure_connection(deadline)
        request_id = uuid.uuid4().hex
        response_queue: queue.Queue[dict[str, object] | BaseException] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        framed = {"request_id": request_id, **payload}
        try:
            with self._write_lock:
                connection.sendall((json.dumps(framed, separators=(",", ":")) + "\n").encode())
        except OSError as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            self._fail_connection(connection, _PoolConnectionError(str(exc)))
            raise _PoolConnectionError(str(exc)) from exc
        remaining = deadline - time.monotonic()
        try:
            response = response_queue.get(timeout=max(remaining, 0.001))
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"OCI runner pool request {payload.get('operation')} timed out") from exc
        if isinstance(response, BaseException):
            raise response
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "OCI runner pool request failed"))
        return dict(response.get("result") or {})

    def _ensure_connection(self, deadline: float) -> socket.socket:
        with self._connection_lock:
            if self._connection is not None:
                return self._connection
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(max(deadline - time.monotonic(), 0.1))
            try:
                connection.connect(str(self.config.socket_path))
            except OSError as exc:
                connection.close()
                raise _PoolConnectionError(str(exc)) from exc
            connection.settimeout(None)
            reader = connection.makefile("rb")
            self._connection = connection
            self._reader = reader
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                args=(connection, reader),
                daemon=True,
                name="oci-pool-reader",
            )
            self._reader_thread.start()
            return connection

    def _reader_loop(self, connection: socket.socket, reader: Any) -> None:
        error: BaseException = _PoolConnectionError("OCI runner pool broker closed the connection")
        try:
            while line := reader.readline():
                try:
                    response = json.loads(line)
                    request_id = str(response["request_id"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    error = _PoolConnectionError(f"invalid OCI runner pool response: {type(exc).__name__}")
                    break
                with self._pending_lock:
                    response_queue = self._pending.pop(request_id, None)
                if response_queue is not None:
                    response_queue.put(response)
        except OSError as exc:
            error = _PoolConnectionError(str(exc))
        finally:
            try:
                reader.close()
            except OSError:
                pass
            self._fail_connection(connection, error)

    def _fail_connection(self, connection: socket.socket, error: BaseException) -> None:
        with self._connection_lock:
            if self._connection is not connection:
                return
            self._close_connection_locked()
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            try:
                response_queue.put_nowait(error)
            except queue.Full:
                pass

    def _reset_after_fork(self) -> None:
        self._connection_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._connection = None
        self._reader = None
        self._reader_thread = None
        self._owner_pid = os.getpid()
        self.client_id = f"client-{os.getpid()}-{uuid.uuid4().hex}"

    def _close_connection_locked(self) -> None:
        connection = self._connection
        self._reader = None
        self._connection = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _ensure_broker(self) -> None:
        path = self.config.socket_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        lock_path = path.with_suffix(path.suffix + ".lock")
        with open(lock_path, "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    self._raw_request({"operation": "ping"}, timeout=5.0)
                    return
                except _PoolConnectionError:
                    owner = _read_owner(path)
                    if _owner_is_live(owner):
                        deadline = time.monotonic() + 30.0
                        while time.monotonic() < deadline:
                            try:
                                self._raw_request({"operation": "ping"}, timeout=5.0)
                                return
                            except _PoolConnectionError:
                                time.sleep(0.2)
                        raise RuntimeError(
                            f"OCI runner pool broker process {owner.get('pid')} is alive but unresponsive; "
                            "refusing to replace its socket"
                        )
                    path.unlink(missing_ok=True)
                    _owner_path(path).unlink(missing_ok=True)
                broker_env = os.environ.copy()
                extension_root = str(Path(__file__).resolve().parents[1])
                broker_env["PYTHONPATH"] = extension_root + (
                    os.pathsep + broker_env["PYTHONPATH"] if broker_env.get("PYTHONPATH") else ""
                )
                subprocess.Popen(
                    [sys.executable, "-m", "sandoq_provider.pool", "--broker"],
                    env=broker_env,
                    close_fds=True,
                )
                deadline = time.monotonic() + 30.0
                while time.monotonic() < deadline:
                    try:
                        self._raw_request({"operation": "ping"}, timeout=5.0)
                        return
                    except _PoolConnectionError:
                        time.sleep(0.1)
                raise RuntimeError(f"OCI runner pool broker did not bind {path} within 30s")
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _request(self, operation: str, timeout: float = 30.0, **values: object) -> dict[str, object]:
        payload = {"operation": operation, "client_id": self.client_id, **values}
        try:
            return self._raw_request(payload, timeout=timeout)
        except _PoolConnectionError:
            with self._reconnect_lock:
                self._ensure_broker()
                if operation != "register":
                    self._raw_request({"operation": "register", "client_id": self.client_id}, timeout=30.0)
            return self._raw_request(payload, timeout=timeout)

    def _heartbeat_loop(self) -> None:
        while not self._closed:
            time.sleep(10.0)
            if self._closed:
                return
            try:
                self._request("heartbeat", timeout=5.0)
            except Exception:
                return

    def acquire(self, requested_image: str, *, deadline: float | None = None) -> dict[str, object]:
        started = time.monotonic()
        absolute_deadline = deadline if deadline is not None else started + self.config.create_deadline_s
        ticket_id = "ticket-" + uuid.uuid4().hex
        delay = 0.05
        try:
            while True:
                remaining = absolute_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("OCI runner pool acquisition deadline expired")
                response = self._request(
                    "acquire",
                    timeout=min(remaining, 10.0) + 1.0,
                    requested_image=requested_image,
                    timeout_seconds=remaining,
                    ticket_id=ticket_id,
                )
                if response.get("status") == "assigned":
                    response.pop("status", None)
                    response.pop("ticket_id", None)
                    return response
                time.sleep(min(delay * random.uniform(0.75, 1.25), remaining))
                delay = min(delay * 2.0, 1.0)
        except BaseException:
            try:
                self._request("cancel_acquire", timeout=5.0, ticket_id=ticket_id)
            except Exception:
                pass
            raise

    def ecr_credential(self, assignment_id: str, registry: str) -> dict[str, object]:
        return self._request(
            "ecr_credential",
            timeout=self.config.ecr.command_timeout_s + 30.0,
            assignment_id=assignment_id,
            registry=registry,
        )

    def update(self, assignment_id: str, **values: object) -> dict[str, object]:
        return self._request("update", assignment_id=assignment_id, values=values)

    def begin_shell_command(
        self,
        assignment_id: str,
        expected_shell_id: str,
        *,
        timeout_seconds: float,
        request_timeout_seconds: float,
    ) -> dict[str, object]:
        return self._request(
            "begin_shell_command",
            timeout=timeout_seconds + 5.0,
            assignment_id=assignment_id,
            expected_shell_id=expected_shell_id,
            timeout_seconds=timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )

    def complete_shell_command(self, assignment_id: str, operation_id: str) -> dict[str, object]:
        return self._request(
            "complete_shell_command",
            timeout=30.0,
            assignment_id=assignment_id,
            operation_id=operation_id,
        )

    def recover_managed_shell(
        self,
        assignment_id: str,
        expected_shell_id: str,
        *,
        workdir: str,
    ) -> dict[str, object]:
        return self._request(
            "recover_managed_shell",
            timeout=125.0,
            assignment_id=assignment_id,
            expected_shell_id=expected_shell_id,
            workdir=workdir,
        )

    def release(
        self,
        assignment_id: str,
        *,
        poison: bool = False,
        reason: str = "release",
        shell_failure_status: str | None = None,
    ) -> dict[str, object]:
        return self._request(
            "release",
            timeout=max(self.config.drain_timeout_s, 330.0) + 30.0,
            assignment_id=assignment_id,
            poison=poison,
            reason=reason,
            shell_failure_status=shell_failure_status,
        )

    def depart(self) -> None:
        if self._closed:
            return
        try:
            self._request("depart", timeout=max(self.config.drain_timeout_s, 30.0) + 30.0)
        finally:
            self._closed = True
            with self._connection_lock:
                self._close_connection_locked()

    def drain(self, reason: str = "explicit_client_drain") -> dict[str, object]:
        if self._closed:
            raise RuntimeError("pool client is closed")
        try:
            return self._request(
                "drain",
                timeout=max(self.config.drain_timeout_s, 30.0) + 60.0,
                reason=reason,
            )
        finally:
            self._closed = True
            with self._connection_lock:
                self._close_connection_locked()


_client_lock = threading.Lock()
_client: PoolClient | None = None


def get_pool_client() -> PoolClient:
    global _client
    with _client_lock:
        if _client is None or _client._closed or _client._owner_pid != os.getpid():
            _client = PoolClient()
        return _client


def depart_pool_client() -> None:
    with _client_lock:
        client = _client
    if client is not None:
        client.depart()


atexit.register(depart_pool_client)


if __name__ == "__main__":
    run_broker()
