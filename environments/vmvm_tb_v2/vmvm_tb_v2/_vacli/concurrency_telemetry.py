"""Aggregate-only concurrency telemetry for one VMVM evaluator process."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

SCHEMA_VERSION = 1
MAX_TELEMETRY_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
TELEMETRY_PATH_ENV = "VMVM_CONCURRENCY_TELEMETRY_PATH"
EVAL_IDENTITY_ENV = "VMVM_CONCURRENCY_TELEMETRY_EVAL_RUN_IDENTITY_SHA256"
EVAL_ROLE_ENV = "VMVM_CONCURRENCY_TELEMETRY_EVAL_RUN_ROLE"
SLURM_JOB_ID_ENV = "VMVM_CONCURRENCY_TELEMETRY_SLURM_JOB_ID"

_OBSERVATION_KEYS = {
    "active_vmvm_runtimes_at_publish",
    "counter_violations",
    "lease_start_attempts",
    "lease_start_finishes",
    "lease_startups_at_publish",
    "lease_tunnels_ready",
    "peak_active_vmvm_runtimes",
    "peak_concurrent_lease_startups",
    "vmvm_runtime_ready",
    "vmvm_runtime_starts",
    "vmvm_runtime_stops",
}


class ConcurrencyTelemetryError(ValueError):
    """Concurrency evidence is absent, malformed, or internally inconsistent."""


class LeaseStartTelemetry(Protocol):
    def lease_start_entered(self) -> None: ...

    def lease_start_finished(self) -> None: ...


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConcurrencyTelemetryError("concurrency_telemetry_invalid")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ConcurrencyTelemetryError("concurrency_telemetry_invalid")


def _require_metadata(
    eval_run_identity_sha256: str,
    eval_run_role: str,
    slurm_job_id: str,
) -> None:
    if (
        not isinstance(eval_run_identity_sha256, str)
        or SHA256_RE.fullmatch(eval_run_identity_sha256) is None
        or not isinstance(eval_run_role, str)
        or eval_run_role not in {"smoke", "tb4", "mobius"}
        or not isinstance(slurm_job_id, str)
        or SLURM_JOB_ID_RE.fullmatch(slurm_job_id) is None
    ):
        raise ConcurrencyTelemetryError("concurrency_telemetry_binding_invalid")


class ConcurrencyTelemetry:
    """Thread-safe process-local counters published once at interpreter exit."""

    def __init__(
        self,
        path: Path,
        *,
        eval_run_identity_sha256: str,
        eval_run_role: str,
        slurm_job_id: str,
        register_atexit: bool = True,
    ) -> None:
        _require_metadata(eval_run_identity_sha256, eval_run_role, slurm_job_id)
        if path.name != "concurrency_telemetry.json":
            raise ConcurrencyTelemetryError("concurrency_telemetry_path_invalid")
        try:
            parent = path.parent.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ConcurrencyTelemetryError("concurrency_telemetry_path_invalid") from error
        self.path = parent / path.name
        self.eval_run_identity_sha256 = eval_run_identity_sha256
        self.eval_run_role = eval_run_role
        self.slurm_job_id = slurm_job_id
        self.process_id = os.getpid()
        self._lock = threading.Lock()
        self._published = False
        self._active_vmvm_runtimes = 0
        self._active_lease_startups = 0
        self._peak_active_vmvm_runtimes = 0
        self._peak_concurrent_lease_startups = 0
        self._vmvm_runtime_starts = 0
        self._vmvm_runtime_ready = 0
        self._vmvm_runtime_stops = 0
        self._lease_start_attempts = 0
        self._lease_tunnels_ready = 0
        self._lease_start_finishes = 0
        self._counter_violations = 0
        if register_atexit:
            atexit.register(self.publish)

    @classmethod
    def from_environment(cls) -> ConcurrencyTelemetry | None:
        raw_path = os.environ.get(TELEMETRY_PATH_ENV)
        metadata = {
            EVAL_IDENTITY_ENV: os.environ.get(EVAL_IDENTITY_ENV),
            EVAL_ROLE_ENV: os.environ.get(EVAL_ROLE_ENV),
            SLURM_JOB_ID_ENV: os.environ.get(SLURM_JOB_ID_ENV),
        }
        if raw_path is None and all(value is None for value in metadata.values()):
            return None
        if not raw_path or any(not value for value in metadata.values()):
            raise ConcurrencyTelemetryError("concurrency_telemetry_environment_incomplete")
        return cls(
            Path(raw_path),
            eval_run_identity_sha256=str(metadata[EVAL_IDENTITY_ENV]),
            eval_run_role=str(metadata[EVAL_ROLE_ENV]),
            slurm_job_id=str(metadata[SLURM_JOB_ID_ENV]),
        )

    def vmvm_runtime_started(self) -> None:
        with self._lock:
            self._active_vmvm_runtimes += 1
            self._vmvm_runtime_starts += 1
            self._peak_active_vmvm_runtimes = max(
                self._peak_active_vmvm_runtimes,
                self._active_vmvm_runtimes,
            )

    def vmvm_runtime_became_ready(self) -> None:
        with self._lock:
            if self._active_vmvm_runtimes < 1:
                self._counter_violations += 1
            self._vmvm_runtime_ready += 1

    def vmvm_runtime_stopped(self) -> None:
        with self._lock:
            if self._active_vmvm_runtimes < 1:
                self._counter_violations += 1
                return
            self._active_vmvm_runtimes -= 1
            self._vmvm_runtime_stops += 1

    def lease_start_entered(self) -> None:
        with self._lock:
            self._active_lease_startups += 1
            self._lease_start_attempts += 1
            self._peak_concurrent_lease_startups = max(
                self._peak_concurrent_lease_startups,
                self._active_lease_startups,
            )

    def lease_tunnel_became_ready(self) -> None:
        with self._lock:
            if self._active_lease_startups < 1:
                self._counter_violations += 1
            self._lease_tunnels_ready += 1

    def lease_start_finished(self) -> None:
        with self._lock:
            if self._active_lease_startups < 1:
                self._counter_violations += 1
                return
            self._active_lease_startups -= 1
            self._lease_start_finishes += 1

    def _observations(self) -> dict[str, int]:
        return {
            "active_vmvm_runtimes_at_publish": self._active_vmvm_runtimes,
            "counter_violations": self._counter_violations,
            "lease_start_attempts": self._lease_start_attempts,
            "lease_start_finishes": self._lease_start_finishes,
            "lease_startups_at_publish": self._active_lease_startups,
            "lease_tunnels_ready": self._lease_tunnels_ready,
            "peak_active_vmvm_runtimes": self._peak_active_vmvm_runtimes,
            "peak_concurrent_lease_startups": self._peak_concurrent_lease_startups,
            "vmvm_runtime_ready": self._vmvm_runtime_ready,
            "vmvm_runtime_starts": self._vmvm_runtime_starts,
            "vmvm_runtime_stops": self._vmvm_runtime_stops,
        }

    def publish(self) -> None:
        """Atomically publish one mode-0400 aggregate artifact without replacement."""

        if os.getpid() != self.process_id:
            return
        with self._lock:
            if self._published:
                return
            observations = self._observations()
            complete = (
                observations["active_vmvm_runtimes_at_publish"] == 0
                and observations["lease_startups_at_publish"] == 0
                and observations["counter_violations"] == 0
                and observations["vmvm_runtime_starts"] == observations["vmvm_runtime_stops"]
                and observations["lease_start_attempts"] == observations["lease_start_finishes"]
            )
            body = {
                "schema_version": SCHEMA_VERSION,
                "state": "complete" if complete else "incomplete",
                "eval_run_identity_sha256": self.eval_run_identity_sha256,
                "eval_run_role": self.eval_run_role,
                "slurm_job_id": self.slurm_job_id,
                "process_id": self.process_id,
                "measurement_scope": "single_evaluator_process",
                "observations": observations,
            }
            payload = {
                **body,
                "concurrency_telemetry_sha256": hashlib.sha256(_canonical_json(body)).hexdigest(),
            }
            encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fchmod(handle.fileno(), 0o400)
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, self.path)
                except FileExistsError as error:
                    raise ConcurrencyTelemetryError("concurrency_telemetry_already_exists") from error
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
            self._published = True


class LeaseStartConcurrencyLimiter:
    """Bounded lease-start limiter whose telemetry transition is atomic.

    Keeping the permit count and telemetry count under the same condition lock
    prevents a descheduled acquirer or releaser from making the reported peak
    smaller than the true peak number of permit holders.
    """

    def __init__(
        self,
        value: int,
        telemetry: LeaseStartTelemetry | None,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("semaphore initial value must be > 0")
        self._initial_value = value
        self._value = value
        self._condition = threading.Condition(threading.Lock())
        self._telemetry = telemetry

    def _acquire(
        self,
        *,
        measured: bool,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        with self._condition:
            while self._value == 0:
                if cancel_event is not None and cancel_event.is_set():
                    return False
                self._condition.wait(timeout=0.1 if cancel_event is not None else None)
            if cancel_event is not None and cancel_event.is_set():
                return False
            self._value -= 1
            try:
                if measured and self._telemetry is not None:
                    self._telemetry.lease_start_entered()
            except BaseException:
                self._value += 1
                self._condition.notify()
                raise
            return True

    def _release(self, *, measured: bool) -> None:
        with self._condition:
            if self._value >= self._initial_value:
                raise ValueError("Semaphore released too many times")
            try:
                if measured and self._telemetry is not None:
                    self._telemetry.lease_start_finished()
            finally:
                self._value += 1
                self._condition.notify()

    def acquire(self, cancel_event: threading.Event | None = None) -> bool:
        """Acquire one measured lease-start permit."""

        return self._acquire(measured=True, cancel_event=cancel_event)

    def release(self) -> None:
        """Release one measured lease-start permit."""

        self._release(measured=True)

    @contextmanager
    def unmeasured_permit(self) -> Iterator[None]:
        """Share capacity without reporting a lease-start telemetry holder."""

        self._acquire(measured=False)
        try:
            yield
        finally:
            self._release(measured=False)


def load_concurrency_telemetry_artifact(
    path: Path,
    *,
    eval_run_identity_sha256: str,
    eval_run_role: str,
    slurm_job_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Load evidence and return the record for the exact bytes validated."""

    _require_metadata(eval_run_identity_sha256, eval_run_role, slurm_job_id)
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat(follow_symlinks=False)
        if (
            resolved.name != "concurrency_telemetry.json"
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o400
            or before.st_size > MAX_TELEMETRY_BYTES
        ):
            raise ConcurrencyTelemetryError("concurrency_telemetry_unreadable")
        raw = resolved.read_bytes()
        after = resolved.stat(follow_symlinks=False)
    except OSError as error:
        raise ConcurrencyTelemetryError("concurrency_telemetry_unreadable") from error
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_signature != after_signature or len(raw) != after.st_size:
        raise ConcurrencyTelemetryError("concurrency_telemetry_changed")
    artifact = {
        "path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConcurrencyTelemetryError("concurrency_telemetry_invalid") from error
    expected_keys = {
        "schema_version",
        "state",
        "eval_run_identity_sha256",
        "eval_run_role",
        "slurm_job_id",
        "process_id",
        "measurement_scope",
        "observations",
        "concurrency_telemetry_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ConcurrencyTelemetryError("concurrency_telemetry_invalid")
    observations = value.get("observations")
    self_hash = value.get("concurrency_telemetry_sha256")
    body = {key: item for key, item in value.items() if key != "concurrency_telemetry_sha256"}
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or value.get("state") != "complete"
        or value.get("eval_run_identity_sha256") != eval_run_identity_sha256
        or value.get("eval_run_role") != eval_run_role
        or value.get("slurm_job_id") != slurm_job_id
        or type(value.get("process_id")) is not int
        or value["process_id"] < 1
        or value.get("measurement_scope") != "single_evaluator_process"
        or not isinstance(observations, dict)
        or set(observations) != _OBSERVATION_KEYS
        or not isinstance(self_hash, str)
        or SHA256_RE.fullmatch(self_hash) is None
        or hashlib.sha256(_canonical_json(body)).hexdigest() != self_hash
    ):
        raise ConcurrencyTelemetryError("concurrency_telemetry_invalid")
    if any(type(item) is not int or item < 0 for item in observations.values()):
        raise ConcurrencyTelemetryError("concurrency_telemetry_observations_invalid")
    if (
        observations["counter_violations"] != 0
        or observations["active_vmvm_runtimes_at_publish"] != 0
        or observations["lease_startups_at_publish"] != 0
        or observations["vmvm_runtime_starts"] < 1
        or observations["vmvm_runtime_starts"] != observations["vmvm_runtime_stops"]
        or observations["vmvm_runtime_ready"] > observations["vmvm_runtime_starts"]
        or observations["lease_start_attempts"] < 1
        or observations["lease_start_attempts"] != observations["lease_start_finishes"]
        or observations["lease_tunnels_ready"] > observations["lease_start_attempts"]
        or observations["lease_start_attempts"] < observations["vmvm_runtime_starts"]
        or observations["lease_tunnels_ready"] < observations["vmvm_runtime_ready"]
        or not 1 <= observations["peak_active_vmvm_runtimes"] <= observations["vmvm_runtime_starts"]
        or not 1 <= observations["peak_concurrent_lease_startups"] <= observations["lease_start_attempts"]
    ):
        raise ConcurrencyTelemetryError("concurrency_telemetry_observations_invalid")
    return value, artifact


def load_concurrency_telemetry(
    path: Path,
    *,
    eval_run_identity_sha256: str,
    eval_run_role: str,
    slurm_job_id: str,
) -> dict[str, Any]:
    """Load strict, self-hashed, complete aggregate concurrency evidence."""

    value, _ = load_concurrency_telemetry_artifact(
        path,
        eval_run_identity_sha256=eval_run_identity_sha256,
        eval_run_role=eval_run_role,
        slurm_job_id=slurm_job_id,
    )
    return value


TELEMETRY = ConcurrencyTelemetry.from_environment()
