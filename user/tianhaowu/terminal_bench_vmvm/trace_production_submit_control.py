#!/usr/bin/env python3
"""One-shot held submission controller for the production trace auditor."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUTHORIZATION_TYPE = "terminal_bench_vmvm_production_trace_audit_authorization_v2"
INTENT_TYPE = "terminal_bench_vmvm_production_trace_audit_launch_intent_v2"
HELD_AUTHORIZATION_TYPE = "terminal_bench_vmvm_production_trace_audit_held_authorization_v2"
RECEIPT_TYPE = "terminal_bench_vmvm_production_trace_audit_submission_receipt_v2"
PERMIT_TYPE = "terminal_bench_vmvm_production_trace_audit_activation_permit_v2"
FAILURE_TYPE = "terminal_bench_vmvm_production_trace_audit_submission_failure_v2"
SCHEMA_VERSION = 1
ADMISSION_SCHEMA_VERSION = 2
OWNER = "tianhaowu"
OWNER_UID = 656177
OWNER_USER_ID = f"{OWNER}({OWNER_UID})"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
JOB_NAME_RE = re.compile(r"trace-production-audit-[0-9a-f]{16}")
SAFE_CODE_RE = re.compile(r"[a-z0-9_]{1,96}")
TERMINAL_STATES = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "TIMEOUT",
    }
)
HELD_TIMEOUT_SECONDS = 982
ACTIVATION_TIMEOUT_SECONDS = 742
CANCEL_IDENTITY_TIMEOUT_SECONDS = 180
CANCEL_TERMINAL_TIMEOUT_SECONDS = 300
QUERY_TIMEOUT_SECONDS = 20
POLL_SECONDS = 2
TERMINAL_ROUNDS = 6
MAX_OUTPUT_BYTES = 64 * 1024
RESERVATION_LINK_COUNT = 2


class SubmissionError(RuntimeError):
    """A submission invariant failed with an aggregate-safe code."""


class LifecycleError(SubmissionError):
    def __init__(self, code: str, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.evidence = dict(evidence or {})


class SchedulerObservationError(SubmissionError):
    """A partial scheduler view failed after retaining identity conflicts."""

    def __init__(self, code: str, conflicts: Sequence[str] = ()) -> None:
        super().__init__(code)
        self.conflicts = tuple(sorted(set(conflicts)))


class SubmissionInterrupted(BaseException):
    """A handled signal that must enter exact-job cleanup."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


Runner = Callable[[Sequence[str], float], CommandResult]


@contextmanager
def _defer_handled_signals() -> Iterator[None]:
    """Make one scheduler-observation/latch update indivisible by our handlers."""

    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def fail(code: str) -> None:
    raise SubmissionError(code if SAFE_CODE_RE.fullmatch(code) else "submission_failed")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("json_duplicate_key")
        result[key] = value
    return result


def strict_json(raw: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise SubmissionError(code) from error
    if not isinstance(value, dict):
        fail(code)
    return value


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@dataclass
class ReservationAnchor:
    path: Path
    parent_path: Path
    parent_fd: int
    descriptor: int
    parent_identity: tuple[int, int]
    identity: tuple[int, int]

    def record(self) -> dict[str, int]:
        return {
            "device": self.identity[0],
            "inode": self.identity[1],
            "owner_uid": OWNER_UID,
            "parent_device": self.parent_identity[0],
            "parent_inode": self.parent_identity[1],
        }

    def batch_arguments(self) -> list[str]:
        record = self.record()
        return [
            str(record["device"]),
            str(record["inode"]),
            str(record["parent_device"]),
            str(record["parent_inode"]),
        ]

    def revalidate(self, *, expected_mode: int) -> None:
        fresh_parent = -1
        fresh_reservation = -1
        try:
            parent_status = os.fstat(self.parent_fd)
            reservation_status = os.fstat(self.descriptor)
            visible_status = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            fresh_parent = os.open(
                self.parent_path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
            fresh_parent_status = os.fstat(fresh_parent)
            fresh_reservation = os.open(
                self.path.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=fresh_parent,
            )
            fresh_reservation_status = os.fstat(fresh_reservation)
        except OSError as error:
            raise SubmissionError("reservation_changed") from error
        finally:
            if fresh_reservation >= 0:
                os.close(fresh_reservation)
            if fresh_parent >= 0:
                os.close(fresh_parent)
        if (
            not stat.S_ISDIR(parent_status.st_mode)
            or stat.S_IMODE(parent_status.st_mode) != 0o700
            or parent_status.st_uid != OWNER_UID
            or (parent_status.st_dev, parent_status.st_ino) != self.parent_identity
            or (fresh_parent_status.st_dev, fresh_parent_status.st_ino) != self.parent_identity
            or not stat.S_ISDIR(reservation_status.st_mode)
            or stat.S_IMODE(reservation_status.st_mode) != expected_mode
            or reservation_status.st_uid != OWNER_UID
            or reservation_status.st_nlink != RESERVATION_LINK_COUNT
            or (reservation_status.st_dev, reservation_status.st_ino) != self.identity
            or visible_status.st_nlink != RESERVATION_LINK_COUNT
            or (visible_status.st_dev, visible_status.st_ino) != self.identity
            or fresh_reservation_status.st_nlink != RESERVATION_LINK_COUNT
            or (fresh_reservation_status.st_dev, fresh_reservation_status.st_ino) != self.identity
        ):
            fail("reservation_changed")

    def close(self) -> None:
        for field in ("descriptor", "parent_fd"):
            descriptor = getattr(self, field)
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass
            finally:
                setattr(self, field, -1)


def stable_bytes(
    path: Path,
    *,
    expected_sha256: str,
    mode: int | None,
    uid: int = OWNER_UID,
    maximum: int = 64 * 1024 * 1024,
) -> bytes:
    descriptor = -1
    try:
        if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
            fail("artifact_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (mode is not None and stat.S_IMODE(before.st_mode) != mode)
            or before.st_uid != uid
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > maximum
        ):
            fail("artifact_invalid")
        body = b""
        while len(body) < before.st_size:
            block = os.read(descriptor, min(1 << 20, before.st_size - len(body)))
            if not block:
                fail("artifact_invalid")
            body += block
        after = os.fstat(descriptor)
        visible = os.stat(path, follow_symlinks=False)
    except SubmissionError:
        raise
    except OSError as error:
        raise SubmissionError("artifact_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        _signature(before) != _signature(after)
        or _signature(after) != _signature(visible)
        or sha256_bytes(body) != expected_sha256
    ):
        fail("artifact_invalid")
    return body


def _envelope(body: Mapping[str, Any], hash_field: str) -> bytes:
    value = {**body, hash_field: sha256_bytes(canonical_json(body))}
    return json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def load_authorization(path: Path, expected_sha256: str) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        fail("authorization_invalid")
    raw = stable_bytes(path, expected_sha256=expected_sha256, mode=0o400, maximum=2 * 1024 * 1024)
    value = strict_json(raw, "authorization_invalid")
    body = dict(value)
    embedded = body.pop("authorization_sha256", None)
    if (
        raw != canonical_json(value) + b"\n"
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_type") != AUTHORIZATION_TYPE
        or value.get("state") != "approved"
        or embedded != sha256_bytes(canonical_json(body))
    ):
        fail("authorization_invalid")
    submission = value.get("audit_submission")
    nonce = value.get("authorization_nonce")
    if (
        not isinstance(nonce, str)
        or SHA256_RE.fullmatch(nonce) is None
        or not isinstance(submission, dict)
        or set(submission)
        != {
            "cluster",
            "job_name",
            "launch_token_sha256",
            "log_path",
            "policy",
            "reservation_dir",
            "resources",
        }
        or submission.get("job_name") != f"trace-production-audit-{nonce[:16]}"
        or JOB_NAME_RE.fullmatch(str(submission.get("job_name", ""))) is None
        or submission.get("launch_token_sha256") != sha256_bytes(nonce.encode("ascii"))
        or submission.get("policy")
        != {
            "held_submission": True,
            "one_shot": True,
            "requeue": False,
            "wrapper_transport": "sbatch_stdin_exact_bytes",
        }
        or submission.get("resources")
        != {
            "account": "ram",
            "cpus_per_task": 2,
            "memory": "8G",
            "nodes": 1,
            "ntasks": 1,
            "partition": "cpu_x86",
            "qos": "cpu_x86_lowest",
            "time_limit": "02:00:00",
        }
    ):
        fail("audit_submission_authorization_invalid")
    cluster = submission.get("cluster")
    reservation = submission.get("reservation_dir")
    log_path = submission.get("log_path")
    if (
        not isinstance(cluster, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", cluster) is None
        or not isinstance(reservation, str)
        or not isinstance(log_path, str)
        or not Path(reservation).is_absolute()
        or not Path(log_path).is_absolute()
        or "\n" in reservation
        or "\r" in reservation
        or "\n" in log_path
        or "\r" in log_path
        or "%j" not in Path(log_path).name
    ):
        fail("audit_submission_authorization_invalid")
    return value


def _scheduler_environment(certificate: str, private_key: str) -> dict[str, str]:
    return {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "THRIFT_TLS_CL_CERT_PATH": certificate,
        "THRIFT_TLS_CL_KEY_PATH": private_key,
    }


def run_command(
    argv: Sequence[str],
    timeout: float,
    *,
    scheduler_environment: Mapping[str, str],
) -> CommandResult:
    if not argv or not Path(argv[0]).is_absolute():
        fail("scheduler_command_invalid")
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=dict(scheduler_environment),
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SubmissionError("scheduler_unavailable") from error
    if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
        fail("scheduler_output_oversize")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _rows(result: CommandResult, width: int, code: str) -> list[list[str]]:
    if result.returncode != 0 or result.stderr:
        fail(code)
    try:
        rows = [line.split("|") for line in result.stdout.decode("utf-8").splitlines() if line]
    except UnicodeDecodeError as error:
        raise SubmissionError(code) from error
    if any(len(row) != width for row in rows):
        fail(code)
    return rows


def scheduler_state(value: str) -> str:
    return value.split()[0].removesuffix("+") if value else "UNKNOWN"


def _query_timeout(
    deadline: float | None,
    clock: Callable[[], float] = time.monotonic,
) -> float:
    if deadline is None:
        return float(QUERY_TIMEOUT_SECONDS)
    remaining = deadline - clock()
    if remaining <= 0:
        fail("scheduler_query_deadline_exhausted")
    return min(float(QUERY_TIMEOUT_SECONDS), remaining)


def _scontrol(result: CommandResult) -> dict[str, str]:
    if result.returncode != 0 or result.stderr:
        fail("scheduler_identity_unavailable")
    try:
        text = result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise SubmissionError("scheduler_identity_invalid") from error
    if not text or "\n" in text or "\r" in text:
        fail("scheduler_identity_invalid")
    matches = tuple(re.finditer(r"(?:^| )([A-Za-z][A-Za-z0-9/]*)=", text))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = match.group(1)
        if key in values:
            fail("scheduler_identity_invalid")
        values[key] = text[match.end() : end].strip()
    if not values:
        fail("scheduler_identity_invalid")
    return values


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_reservation(path: Path) -> ReservationAnchor:
    parent_fd = -1
    reservation_fd = -1
    try:
        parent = path.parent.resolve(strict=True)
        if path != parent / path.name or not path.name:
            fail("reservation_not_fresh")
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        parent_status = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_status.st_mode)
            or stat.S_IMODE(parent_status.st_mode) != 0o700
            or parent_status.st_uid != OWNER_UID
        ):
            fail("reservation_not_fresh")
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            fail("reservation_not_fresh")
        os.mkdir(path.name, 0o700, dir_fd=parent_fd)
        reservation_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        reservation_status = os.fstat(reservation_fd)
        visible_status = os.stat(
            path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(reservation_status.st_mode)
            or stat.S_IMODE(reservation_status.st_mode) != 0o700
            or reservation_status.st_uid != OWNER_UID
            or reservation_status.st_nlink != RESERVATION_LINK_COUNT
            or visible_status.st_nlink != RESERVATION_LINK_COUNT
            or (reservation_status.st_dev, reservation_status.st_ino) != (visible_status.st_dev, visible_status.st_ino)
        ):
            fail("reservation_not_fresh")
        os.fsync(parent_fd)
        anchor = ReservationAnchor(
            path=path,
            parent_path=parent,
            parent_fd=parent_fd,
            descriptor=reservation_fd,
            parent_identity=(parent_status.st_dev, parent_status.st_ino),
            identity=(reservation_status.st_dev, reservation_status.st_ino),
        )
        anchor.revalidate(expected_mode=0o700)
        parent_fd = -1
        reservation_fd = -1
        return anchor
    except SubmissionError:
        raise
    except (OSError, RuntimeError) as error:
        raise SubmissionError("reservation_not_fresh") from error
    finally:
        if reservation_fd >= 0:
            os.close(reservation_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def publish_once(
    anchor: ReservationAnchor,
    name: str,
    raw: bytes,
    mode: int = 0o400,
) -> str:
    descriptor = -1
    temporary = f".{name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    try:
        anchor.revalidate(expected_mode=0o700)
        try:
            os.stat(name, dir_fd=anchor.descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            fail("reservation_entry_exists")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            mode,
            dir_fd=anchor.descriptor,
        )
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                fail("reservation_publication_failed")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary,
            name,
            src_dir_fd=anchor.descriptor,
            dst_dir_fd=anchor.descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=anchor.descriptor)
        temporary = ""
        os.fsync(anchor.descriptor)
        anchor.revalidate(expected_mode=0o700)
    except SubmissionError:
        raise
    except OSError as error:
        raise SubmissionError("reservation_publication_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=anchor.descriptor)
            except OSError:
                pass
    return sha256_bytes(raw)


def scheduler_name_matches(
    job_name: str,
    cluster: str,
    runner: Runner,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[str]:
    queue = _rows(
        runner(
            [
                "/usr/bin/squeue",
                "-M",
                cluster,
                "--noheader",
                "--user",
                OWNER,
                "--name",
                job_name,
                "--format=%A|%j",
            ],
            _query_timeout(deadline, clock),
        ),
        2,
        "scheduler_name_query_unavailable",
    )
    accounting = _rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                cluster,
                "--noheader",
                "--parsable2",
                "--starttime=now-1day",
                "--name",
                job_name,
                "--allocations",
                "--format=JobIDRaw,JobName",
            ],
            _query_timeout(deadline, clock),
        ),
        2,
        "scheduler_name_query_unavailable",
    )
    matches: list[str] = []
    for observed_id, observed_name in [*queue, *accounting]:
        if observed_name != job_name or JOB_ID_RE.fullmatch(observed_id) is None:
            fail("scheduler_name_query_invalid")
        matches.append(observed_id)
    return sorted(set(matches), key=int)


def _job_expectations(authorization: Mapping[str, Any], job_id: str) -> dict[str, str]:
    submission = authorization["audit_submission"]
    resources = submission["resources"]
    project = authorization["source"]["project_root"]
    log_path = submission["log_path"].replace("%j", job_id)
    return {
        "Account": resources["account"],
        "Comment": f"trace-audit-{submission['launch_token_sha256'][:32]}",
        "Command": "(null)",
        "JobId": job_id,
        "JobName": submission["job_name"],
        "NumCPUs": str(resources["cpus_per_task"]),
        "Partition": resources["partition"],
        "QOS": resources["qos"],
        "Requeue": "0",
        "Restarts": "0",
        "StdErr": log_path,
        "StdOut": log_path,
        "TimeLimit": resources["time_limit"],
        "UserId": OWNER_USER_ID,
        "WorkDir": project,
    }


def scheduler_snapshot(
    authorization: Mapping[str, Any],
    job_id: str,
    *,
    held: bool,
    runner: Runner,
    conflict_latch: set[str] | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[set[str], set[str], str]:
    submission = authorization["audit_submission"]
    cluster = submission["cluster"]
    expected = _job_expectations(authorization, job_id)
    conflicts: set[str] = set()
    mismatches: set[str] = set()

    def retain_conflict(field: str) -> None:
        conflicts.add(field)
        if conflict_latch is not None:
            conflict_latch.add(field)

    def rows(argv: Sequence[str], width: int) -> list[list[str]]:
        try:
            return _rows(
                runner(argv, _query_timeout(deadline, clock)),
                width,
                "scheduler_phase_unavailable",
            )
        except SubmissionError as error:
            raise SchedulerObservationError(
                "scheduler_phase_unavailable",
                tuple(conflicts),
            ) from error

    try:
        record = _scontrol(
            runner(
                ["/usr/bin/scontrol", "-M", cluster, "show", "job", "-o", job_id],
                _query_timeout(deadline, clock),
            )
        )
    except SubmissionError:
        return {"scontrol_unavailable"}, set(), "UNKNOWN"
    for field, expected_value in expected.items():
        observed = record.get(field)
        if observed != expected_value:
            mismatches.add(field)
        if field in {
            "Command",
            "Comment",
            "JobId",
            "JobName",
            "UserId",
            "WorkDir",
        } and observed not in {
            None,
            "",
            expected_value,
        }:
            retain_conflict(field)
    state = scheduler_state(record.get("JobState", ""))
    node_list = record.get("NodeList", "")
    if held:
        if (
            state != "PENDING"
            or record.get("Reason") != "JobHeldUser"
            or record.get("Priority") != "0"
            or record.get("StartTime") != "Unknown"
            or record.get("NumNodes") != "1-1"
            or node_list not in {"", "(null)", "N/A"}
            or record.get("BatchHost", "") not in {"", "(null)"}
        ):
            mismatches.add("held_state")
    elif (
        state not in {"PENDING", "CONFIGURING", "RUNNING"}
        or record.get("Reason") == "JobHeldUser"
        or record.get("NumNodes") != "1"
        or (state in {"CONFIGURING", "RUNNING"} and node_list in {"", "(null)", "N/A", "Unknown"})
    ):
        mismatches.add("activation_state")
    try:
        queue = rows(
            [
                "/usr/bin/squeue",
                "-M",
                cluster,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%u|%T|%r|%D|%N",
            ],
            7,
        )
        for (
            queue_id,
            queue_name,
            queue_user,
            _queue_state,
            _reason,
            _nodes,
            _queue_nodes,
        ) in queue:
            for field, observed, exact in (
                ("JobId", queue_id, job_id),
                ("JobName", queue_name, submission["job_name"]),
                ("UserId", queue_user, OWNER),
            ):
                if observed != exact:
                    retain_conflict(field)

        step_queue = rows(
            [
                "/usr/bin/squeue",
                "-M",
                cluster,
                "--steps",
                "--noheader",
                "--jobs",
                job_id,
                "--format=%i|%j|%u|%T",
            ],
            4,
        )
        for step_id, _step_name, step_user, _step_state in step_queue:
            if not step_id.startswith(f"{job_id}."):
                retain_conflict("JobId")
            if step_user != OWNER:
                retain_conflict("UserId")

        allocations = rows(
            [
                "/usr/bin/sacct",
                "-M",
                cluster,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,User,State,Start,NodeList,Restarts",
            ],
            7,
        )
        for (
            allocation_id,
            allocation_name,
            user,
            _raw_state,
            _started,
            _nodes,
            _restarts,
        ) in allocations:
            for field, observed, exact in (
                ("JobId", allocation_id, job_id),
                ("JobName", allocation_name, submission["job_name"]),
                ("UserId", user, OWNER),
            ):
                if observed != exact:
                    retain_conflict(field)

        all_rows = rows(
            [
                "/usr/bin/sacct",
                "-M",
                cluster,
                "--noheader",
                "--parsable2",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ],
            2,
        )
        for row_id, _row_state in all_rows:
            if row_id != job_id and not row_id.startswith(f"{job_id}."):
                retain_conflict("JobId")
    except SchedulerObservationError:
        mismatches.add("scheduler_phase_unavailable")
        mismatches.update(conflicts)
        raise SchedulerObservationError(
            "scheduler_phase_unavailable",
            tuple(conflicts),
        ) from None
    if len(queue) != 1:
        mismatches.add("queue_cardinality")
    else:
        queue_id, queue_name, queue_user, queue_state, reason, nodes, queue_nodes = queue[0]
        for field, observed, exact in (
            ("JobId", queue_id, job_id),
            ("JobName", queue_name, submission["job_name"]),
            ("UserId", queue_user, OWNER),
        ):
            if observed != exact:
                mismatches.add(f"queue_{field}")
                retain_conflict(field)
        if held:
            if (
                scheduler_state(queue_state) != "PENDING"
                or reason != "JobHeldUser"
                or nodes != "1"
                or queue_nodes not in {"", "(null)", "N/A"}
            ):
                mismatches.add("held_queue")
        elif scheduler_state(queue_state) not in {"PENDING", "CONFIGURING", "RUNNING"} or reason == "JobHeldUser":
            mismatches.add("activation_queue")
    for step_id, _step_name, step_user, step_state in step_queue:
        if not step_id.startswith(f"{job_id}."):
            retain_conflict("JobId")
        if step_user != OWNER:
            retain_conflict("UserId")
        if scheduler_state(step_state) not in {"PENDING", "CONFIGURING", "RUNNING"}:
            mismatches.add("step_queue_state")
    if held and step_queue:
        mismatches.add("held_step_queue")
    if len(allocations) != 1:
        mismatches.add("accounting_cardinality")
    else:
        allocation_id, allocation_name, user, raw_state, started, nodes, restarts = allocations[0]
        for field, observed, exact in (
            ("JobId", allocation_id, job_id),
            ("JobName", allocation_name, submission["job_name"]),
            ("UserId", user, OWNER),
        ):
            if observed != exact:
                mismatches.add(f"accounting_{field}")
                retain_conflict(field)
        accounting_state = scheduler_state(raw_state)
        if held:
            if (
                accounting_state != "PENDING"
                or started not in {"", "Unknown", "N/A"}
                or nodes not in {"", "(null)", "N/A"}
                or restarts != "0"
            ):
                mismatches.add("held_accounting")
        elif accounting_state not in {"PENDING", "CONFIGURING", "RUNNING"} or restarts != "0":
            mismatches.add("activation_accounting")
    if held:
        if len(all_rows) != 1 or all_rows[0] != [job_id, "PENDING"]:
            mismatches.add("held_steps")
    elif (
        not all_rows
        or all_rows[0][0] != job_id
        or any(
            (row_id != job_id and not row_id.startswith(f"{job_id}."))
            or scheduler_state(row_state) not in {"PENDING", "CONFIGURING", "RUNNING"}
            for row_id, row_state in all_rows
        )
    ):
        mismatches.add("activation_steps")
    mismatches.update(conflicts)
    return mismatches, conflicts, state


def poll_phase(
    authorization: Mapping[str, Any],
    job_id: str,
    *,
    held: bool,
    timeout: int,
    runner: Runner,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    conflict_latch: set[str] | None = None,
) -> dict[str, Any]:
    started = clock()
    deadline = started + timeout
    polls = 0
    consecutive = 0
    conflicts = conflict_latch if conflict_latch is not None else set()
    observed: Counter[str] = Counter()
    final: set[str] = set()
    state = "UNKNOWN"
    max_iterations = timeout // POLL_SECONDS + 2
    while clock() < deadline and polls < max_iterations:
        with _defer_handled_signals():
            try:
                mismatches, current_conflicts, state = scheduler_snapshot(
                    authorization,
                    job_id,
                    held=held,
                    runner=runner,
                    conflict_latch=conflicts,
                    deadline=deadline,
                    clock=clock,
                )
            except SchedulerObservationError as error:
                mismatches = {"scheduler_phase_unavailable"}
                current_conflicts = set(error.conflicts)
                conflicts.update(current_conflicts)
            except SubmissionError:
                mismatches = {"scheduler_phase_unavailable"}
                current_conflicts = set()
        polls += 1
        conflicts.update(current_conflicts)
        observed.update(mismatches)
        final = mismatches
        if conflicts:
            break
        consecutive = consecutive + 1 if not mismatches else 0
        if consecutive >= 2:
            return {
                "converged": True,
                "elapsed_milliseconds": int((clock() - started) * 1000),
                "explicit_conflict_fields": [],
                "final_mismatch_fields": [],
                "mismatch_fields": sorted(observed),
                "mismatch_occurrences": dict(sorted(observed.items())),
                "polls": polls,
                "required_consecutive": 2,
                "state": state,
                "timeout_seconds": timeout,
            }
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    return {
        "converged": False,
        "elapsed_milliseconds": int((clock() - started) * 1000),
        "explicit_conflict_fields": sorted(conflicts),
        "final_mismatch_fields": sorted(final),
        "mismatch_fields": sorted(observed),
        "mismatch_occurrences": dict(sorted(observed.items())),
        "polls": polls,
        "required_consecutive": 2,
        "state": state,
        "timeout_seconds": timeout,
    }


def _sbatch_command(authorization: Mapping[str, Any], batch_arguments: Sequence[str]) -> list[str]:
    submission = authorization["audit_submission"]
    resources = submission["resources"]
    comment = f"trace-audit-{submission['launch_token_sha256'][:32]}"
    return [
        "/usr/bin/sbatch",
        "-M",
        submission["cluster"],
        "--parsable",
        "--hold",
        f"--comment={comment}",
        f"--job-name={submission['job_name']}",
        f"--chdir={authorization['source']['project_root']}",
        f"--partition={resources['partition']}",
        f"--qos={resources['qos']}",
        f"--account={resources['account']}",
        f"--time={resources['time_limit']}",
        f"--nodes={resources['nodes']}",
        f"--ntasks={resources['ntasks']}",
        f"--cpus-per-task={resources['cpus_per_task']}",
        f"--mem={resources['memory']}",
        "--no-requeue",
        f"--output={submission['log_path']}",
        f"--error={submission['log_path']}",
        "--open-mode=truncate",
        "--export=NONE",
        "-",
        *batch_arguments,
    ]


def invoke_sbatch(
    command: Sequence[str],
    wrapper: bytes,
    scheduler_environment: Mapping[str, str],
) -> tuple[str, int, bytes]:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(scheduler_environment),
            start_new_session=True,
        )
        stdout, stderr = process.communicate(input=wrapper, timeout=60)
        outcome = "completed"
    except subprocess.TimeoutExpired as error:
        outcome = "timeout"
        if process is None:
            raise SubmissionError("sbatch_start_failed") from error
        try:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate(timeout=10)
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                raise SubmissionError("sbatch_cleanup_unproven") from cleanup_error
        except OSError as cleanup_error:
            raise SubmissionError("sbatch_cleanup_unproven") from cleanup_error
    except OSError as error:
        raise SubmissionError("sbatch_start_failed") from error
    except BaseException as primary:
        if process is None:
            raise
        cleanup_error: BaseException | None = None
        with _defer_handled_signals():
            try:
                for process_signal in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, process_signal)
                    except ProcessLookupError:
                        pass
                    except OSError as error:
                        cleanup_error = error
                    try:
                        process.communicate(timeout=10)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                _prove_process_group_empty(process.pid)
            except BaseException as error:
                cleanup_error = error
        if cleanup_error is not None:
            raise SubmissionError("sbatch_cleanup_unproven") from primary
        raise
    if process is None or process.poll() is None:
        fail("sbatch_cleanup_unproven")
    _prove_process_group_empty(process.pid)
    if len(stdout) > 4096 or len(stderr) > 4096:
        fail("sbatch_output_oversize")
    if stderr:
        outcome = "stderr"
    return outcome, int(process.returncode), stdout


def _prove_process_group_empty(
    process_group: int,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Boundedly terminate and prove absence of the complete local sbatch group."""

    deadline = clock() + 60
    consecutive_absent = 0
    termination_sent = False
    while clock() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            consecutive_absent += 1
            if consecutive_absent >= TERMINAL_ROUNDS:
                return
        except OSError as error:
            raise SubmissionError("sbatch_process_group_unproven") from error
        else:
            consecutive_absent = 0
            try:
                os.killpg(
                    process_group,
                    signal.SIGKILL if termination_sent else signal.SIGTERM,
                )
            except ProcessLookupError:
                pass
            except OSError as error:
                raise SubmissionError("sbatch_process_group_unproven") from error
            termination_sent = True
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(0.05, remaining))
    fail("sbatch_process_group_unproven")


def parse_sbatch_candidate(outcome: str, returncode: int, stdout: bytes) -> str | None:
    try:
        lines = stdout.decode("ascii").splitlines()
    except UnicodeDecodeError:
        return None
    if outcome == "completed" and returncode == 0 and len(lines) == 1:
        candidate = lines[0].split(";", 1)[0]
        if JOB_ID_RE.fullmatch(candidate) is not None:
            return candidate
    return None


def resolve_submission(
    job_name: str,
    cluster: str,
    direct_candidate: str | None,
    *,
    runner: Runner,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str | None, bool, dict[str, int]]:
    deadline = clock() + 60
    polls = 0
    zero_rounds = 0
    while clock() < deadline:
        matches = scheduler_name_matches(
            job_name,
            cluster,
            runner,
            deadline=deadline,
            clock=clock,
        )
        polls += 1
        if direct_candidate is not None:
            if matches == [direct_candidate]:
                return (
                    direct_candidate,
                    True,
                    {"polls": polls, "zero_rounds": zero_rounds},
                )
            if matches and matches != [direct_candidate]:
                fail("submission_identity_ambiguous")
        else:
            if len(matches) == 1:
                return matches[0], False, {"polls": polls, "zero_rounds": zero_rounds}
            if len(matches) > 1:
                fail("submission_identity_ambiguous")
            zero_rounds += 1
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    if direct_candidate is not None:
        fail("submission_visibility_unproven")
    if zero_rounds < TERMINAL_ROUNDS:
        fail("submission_ambiguity_unresolved")
    return None, False, {"polls": polls, "zero_rounds": zero_rounds}


def _precontrol_identity(
    authorization: Mapping[str, Any],
    job_id: str,
    *,
    runner: Runner,
    conflict_latch: set[str] | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, tuple[str, ...]]:
    submission = authorization["audit_submission"]
    expected = _job_expectations(authorization, job_id)
    with _defer_handled_signals():
        try:
            record = _scontrol(
                runner(
                    [
                        "/usr/bin/scontrol",
                        "-M",
                        submission["cluster"],
                        "show",
                        "job",
                        "-o",
                        job_id,
                    ],
                    _query_timeout(deadline, clock),
                )
            )
        except SubmissionError:
            return "unavailable", ()
        conflicts = tuple(
            sorted(
                field
                for field in (
                    "Command",
                    "Comment",
                    "JobId",
                    "JobName",
                    "UserId",
                    "WorkDir",
                )
                if record.get(field) not in {None, "", expected[field]}
            )
        )
        if conflict_latch is not None:
            conflict_latch.update(conflicts)
        if conflicts:
            return "conflict", conflicts
        if any(record.get(field) in {None, ""} for field in expected):
            return "incomplete", ()
        return "exact", ()


def _terminal_snapshot(
    authorization: Mapping[str, Any],
    job_id: str,
    *,
    runner: Runner,
    conflict_latch: set[str] | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, str, str, tuple[str, ...]]:
    submission = authorization["audit_submission"]
    cluster = submission["cluster"]
    conflicts: set[str] = set()
    if conflict_latch:
        return "conflict", "UNKNOWN", "", tuple(sorted(conflict_latch))

    def retain_conflict(field: str) -> None:
        conflicts.add(field)
        if conflict_latch is not None:
            conflict_latch.add(field)

    identity, observed_conflicts = _precontrol_identity(
        authorization,
        job_id,
        runner=runner,
        conflict_latch=conflict_latch,
        deadline=deadline,
        clock=clock,
    )
    conflicts.update(observed_conflicts)
    if identity == "conflict":
        return "conflict", "UNKNOWN", "", tuple(sorted(conflicts))

    def unavailable() -> tuple[str, str, str, tuple[str, ...]]:
        if conflicts or conflict_latch:
            combined = set(conflicts)
            if conflict_latch is not None:
                combined.update(conflict_latch)
            return "conflict", "UNKNOWN", "", tuple(sorted(combined))
        return "unavailable", "UNKNOWN", "", ()

    try:
        with _defer_handled_signals():
            queue = _rows(
                runner(
                    [
                        "/usr/bin/squeue",
                        "-M",
                        cluster,
                        "--noheader",
                        "--jobs",
                        job_id,
                        "--format=%A|%j|%u|%T",
                    ],
                    _query_timeout(deadline, clock),
                ),
                4,
                "terminal_queue_unavailable",
            )
            for observed_id, observed_name, observed_user, _state in queue:
                if observed_id != job_id:
                    retain_conflict("JobId")
                if observed_name != submission["job_name"]:
                    retain_conflict("JobName")
                if observed_user != OWNER:
                    retain_conflict("UserId")
    except SubmissionError:
        return unavailable()
    try:
        with _defer_handled_signals():
            step_queue = _rows(
                runner(
                    [
                        "/usr/bin/squeue",
                        "-M",
                        cluster,
                        "--steps",
                        "--noheader",
                        "--jobs",
                        job_id,
                        "--format=%i|%j|%u|%T",
                    ],
                    _query_timeout(deadline, clock),
                ),
                4,
                "terminal_queue_unavailable",
            )
            for observed_id, _observed_name, observed_user, _state in step_queue:
                if observed_id != job_id and not observed_id.startswith(f"{job_id}."):
                    retain_conflict("JobId")
                if observed_user != OWNER:
                    retain_conflict("UserId")
    except SubmissionError:
        return unavailable()
    try:
        with _defer_handled_signals():
            allocations = _rows(
                runner(
                    [
                        "/usr/bin/sacct",
                        "-M",
                        cluster,
                        "--noheader",
                        "--parsable2",
                        "--allocations",
                        "-j",
                        job_id,
                        "--format=JobIDRaw,JobName,User,State,ExitCode,Restarts",
                    ],
                    _query_timeout(deadline, clock),
                ),
                6,
                "terminal_accounting_unavailable",
            )
            for (
                observed_id,
                observed_name,
                observed_user,
                _state,
                _exit,
                _restarts,
            ) in allocations:
                if observed_id != job_id:
                    retain_conflict("JobId")
                if observed_name != submission["job_name"]:
                    retain_conflict("JobName")
                if observed_user != OWNER:
                    retain_conflict("UserId")
    except SubmissionError:
        return unavailable()
    try:
        with _defer_handled_signals():
            all_rows = _rows(
                runner(
                    [
                        "/usr/bin/sacct",
                        "-M",
                        cluster,
                        "--noheader",
                        "--parsable2",
                        "-j",
                        job_id,
                        "--format=JobIDRaw,State,ExitCode,Restarts",
                    ],
                    _query_timeout(deadline, clock),
                ),
                4,
                "terminal_accounting_unavailable",
            )
            for observed_id, _state, _exit, _restarts in all_rows:
                if observed_id != job_id and not observed_id.startswith(f"{job_id}."):
                    retain_conflict("JobId")
    except SubmissionError:
        return unavailable()
    expected_name = submission["job_name"]
    if conflicts:
        return "conflict", "UNKNOWN", "", tuple(sorted(conflicts))
    if queue or step_queue:
        return "active", "UNKNOWN", "", ()
    if len(allocations) != 1 or not all_rows:
        return "incomplete", "UNKNOWN", "", ()
    allocation = allocations[0]
    state = scheduler_state(allocation[3])
    if (
        allocation[:3] != [job_id, expected_name, OWNER]
        or state not in TERMINAL_STATES
        or not allocation[4]
        or allocation[5] != "0"
        or any(
            scheduler_state(row_state) not in TERMINAL_STATES or not exit_code or restarts not in {"", "0"}
            for _row_id, row_state, exit_code, restarts in all_rows
        )
    ):
        return "active", state, "", ()
    signature = sha256_bytes(canonical_json(sorted(all_rows)))
    return "terminal", state, signature, ()


def _prove_name_exclusive(
    authorization: Mapping[str, Any],
    job_id: str,
    *,
    runner: Runner,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, int]:
    submission = authorization["audit_submission"]
    deadline = clock() + CANCEL_IDENTITY_TIMEOUT_SECONDS
    consecutive = 0
    polls = 0
    while clock() < deadline:
        matches = scheduler_name_matches(
            submission["job_name"],
            submission["cluster"],
            runner,
            deadline=deadline,
            clock=clock,
        )
        polls += 1
        consecutive = consecutive + 1 if matches == [job_id] else 0
        if consecutive >= TERMINAL_ROUNDS:
            return {"consecutive": consecutive, "polls": polls}
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    fail("name_exclusivity_unproven")


def cancel_and_prove(
    authorization: Mapping[str, Any],
    job_id: str,
    *,
    direct_provenance: bool,
    runner: Runner,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    conflict_latch: set[str] | None = None,
) -> dict[str, Any]:
    deadline = clock() + CANCEL_IDENTITY_TIMEOUT_SECONDS
    polls = 0
    identity = "unavailable"
    conflicts = conflict_latch if conflict_latch is not None else set()
    while clock() < deadline:
        identity, observed_conflicts = _precontrol_identity(
            authorization,
            job_id,
            runner=runner,
            conflict_latch=conflicts,
            deadline=deadline,
            clock=clock,
        )
        polls += 1
        conflicts.update(observed_conflicts)
        if conflicts or identity == "exact":
            break
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    if conflicts or (identity != "exact" and not direct_provenance):
        raise LifecycleError(
            "cancellation_unconfirmed",
            {
                "cancel_attempts": 0,
                "explicit_conflict_fields": sorted(conflicts),
                "identity_polls": polls,
                "identity_status": "conflict" if conflicts else identity,
            },
        )
    precontrol_deadline = clock() + QUERY_TIMEOUT_SECONDS * 5
    before, state, signature, terminal_conflicts = _terminal_snapshot(
        authorization,
        job_id,
        runner=runner,
        conflict_latch=conflicts,
        deadline=precontrol_deadline,
        clock=clock,
    )
    conflicts.update(terminal_conflicts)
    if conflicts:
        raise LifecycleError(
            "cancellation_unconfirmed",
            {
                "cancel_attempts": 0,
                "explicit_conflict_fields": sorted(conflicts),
                "identity_polls": polls,
                "identity_status": "conflict",
            },
        )
    cancel_attempts = 0
    cancel_outcome = "not_needed"
    if before != "terminal":
        cancel_attempts = 1
        try:
            result = runner(
                [
                    "/usr/bin/scancel",
                    "-M",
                    authorization["audit_submission"]["cluster"],
                    job_id,
                ],
                QUERY_TIMEOUT_SECONDS,
            )
        except BaseException as error:
            raise LifecycleError(
                "cancellation_unconfirmed",
                {
                    "cancel_attempts": 1,
                    "cancel_command_outcome": "unavailable",
                    "explicit_conflict_fields": [],
                    "identity_polls": polls,
                    "identity_status": ("exact" if identity == "exact" else "direct_provenance_fallback"),
                },
            ) from error
        cancel_outcome = (
            "completed" if result.returncode == 0 and not result.stdout and not result.stderr else "nonzero"
        )
    deadline = clock() + CANCEL_TERMINAL_TIMEOUT_SECONDS
    consecutive = 0
    previous = signature if before == "terminal" else ""
    terminal_polls = 0
    while clock() < deadline:
        status, state, signature, terminal_conflicts = _terminal_snapshot(
            authorization,
            job_id,
            runner=runner,
            conflict_latch=conflicts,
            deadline=deadline,
            clock=clock,
        )
        terminal_polls += 1
        conflicts.update(terminal_conflicts)
        if conflicts:
            raise LifecycleError(
                "cancellation_unconfirmed",
                {
                    "cancel_attempts": cancel_attempts,
                    "cancel_command_outcome": cancel_outcome,
                    "explicit_conflict_fields": sorted(conflicts),
                    "identity_polls": polls,
                    "identity_status": "conflict",
                },
            )
        consecutive = consecutive + 1 if status == "terminal" and signature == previous else int(status == "terminal")
        previous = signature if status == "terminal" else ""
        if consecutive >= TERMINAL_ROUNDS:
            try:
                name_exclusivity = _prove_name_exclusive(
                    authorization,
                    job_id,
                    runner=runner,
                    sleeper=sleeper,
                    clock=clock,
                )
            except SubmissionError as error:
                raise LifecycleError(
                    "cancellation_unconfirmed",
                    {
                        "cancel_attempts": cancel_attempts,
                        "cancel_command_outcome": cancel_outcome,
                        "explicit_conflict_fields": [],
                        "identity_polls": polls,
                        "identity_status": "name_exclusivity_unproven",
                        "terminal_consecutive": consecutive,
                        "terminal_polls": terminal_polls,
                        "terminal_state": state,
                    },
                ) from error
            return {
                "cancel_attempts": cancel_attempts,
                "cancel_command_outcome": cancel_outcome,
                "explicit_conflict_fields": [],
                "identity_polls": polls,
                "identity_status": "exact" if identity == "exact" else "direct_provenance_fallback",
                "terminal_consecutive": consecutive,
                "terminal_polls": terminal_polls,
                "terminal_state": state,
                "name_exclusivity": name_exclusivity,
            }
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    raise LifecycleError(
        "cancellation_unconfirmed",
        {
            "cancel_attempts": cancel_attempts,
            "cancel_command_outcome": cancel_outcome,
            "explicit_conflict_fields": [],
            "identity_polls": polls,
            "identity_status": "exact" if identity == "exact" else "direct_provenance_fallback",
            "terminal_consecutive": consecutive,
            "terminal_polls": terminal_polls,
            "terminal_state": state,
        },
    )


def _git(root: Path, *arguments: str) -> bytes:
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    try:
        completed = subprocess.run(
            [
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.untrackedCache=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=False,
            capture_output=True,
            env=environment,
            timeout=QUERY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SubmissionError("source_git_unavailable") from error
    if completed.returncode != 0 or completed.stderr or len(completed.stdout) > MAX_OUTPUT_BYTES:
        fail("source_git_invalid")
    return completed.stdout


def validate_source(authorization: Mapping[str, Any]) -> dict[str, str]:
    source = authorization.get("source")
    if not isinstance(source, dict):
        fail("source_authorization_invalid")
    try:
        root = Path(source["project_root"])
        revision = source["prime_rl_commit"]
        tree = source["prime_rl_git_tree"]
        gitlinks = source["gitlinks"]
        artifacts = source["artifacts"]
    except (KeyError, TypeError) as error:
        raise SubmissionError("source_authorization_invalid") from error
    try:
        root_status = root.stat(follow_symlinks=False)
        if (
            root.resolve(strict=True) != root
            or root.is_symlink()
            or not stat.S_ISDIR(root_status.st_mode)
            or stat.S_IMODE(root_status.st_mode) != 0o555
            or root_status.st_uid != OWNER_UID
        ):
            fail("source_root_invalid")
    except (OSError, RuntimeError) as error:
        raise SubmissionError("source_root_invalid") from error
    if (
        _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() != b"HEAD"
        or _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() != revision
        or _git(root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip() != tree
        or _git(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        or _git(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            ":(glob)**/*.py",
            ":(glob)**/*.pyc",
            ":(glob)**/*.so",
            ":(glob)**/*.pyd",
            ":(glob)**/sitecustomize.py",
            ":(glob)**/usercustomize.py",
        )
    ):
        fail("source_checkout_invalid")
    for label, relative in (
        ("verifiers", "deps/verifiers"),
        ("renderers", "deps/renderers"),
        ("pydantic_config", "deps/pydantic-config"),
    ):
        child = root / relative
        if (
            _git(child, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() != gitlinks[label]
            or _git(child, "rev-parse", "--abbrev-ref", "HEAD").strip() != b"HEAD"
            or _git(child, "status", "--porcelain=v1", "--untracked-files=all")
            or _git(
                child,
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                ":(glob)**/*.py",
                ":(glob)**/*.pyc",
                ":(glob)**/*.so",
                ":(glob)**/*.pyd",
                ":(glob)**/sitecustomize.py",
                ":(glob)**/usercustomize.py",
            )
        ):
            fail("source_gitlink_invalid")
    observed: dict[str, str] = {}
    if not isinstance(artifacts, dict):
        fail("source_authorization_invalid")
    for label, record in sorted(artifacts.items()):
        if (
            not isinstance(label, str)
            or not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or not isinstance(record.get("path"), str)
            or not isinstance(record.get("sha256"), str)
            or SHA256_RE.fullmatch(record["sha256"]) is None
        ):
            fail("source_authorization_invalid")
        path = Path(record["path"])
        body = stable_bytes(path, expected_sha256=record["sha256"], mode=None)
        if not path.is_relative_to(root):
            fail("source_artifact_invalid")
        observed[label] = sha256_bytes(body)
    return observed


def validate_python(authorization: Mapping[str, Any], path: Path, expected_sha256: str) -> None:
    runtime = authorization["source"]["runtime"]
    if runtime.get("python") != {"path": str(path), "sha256": expected_sha256}:
        fail("python_runtime_invalid")
    stable_bytes(path, expected_sha256=expected_sha256, mode=0o755, uid=0)
    required_tools = {
        "bash": "/usr/bin/bash",
        "chmod": "/usr/bin/chmod",
        "env": "/usr/bin/env",
        "git": "/usr/bin/git",
        "id": "/usr/bin/id",
        "mktemp": "/usr/bin/mktemp",
        "realpath": "/usr/bin/realpath",
        "rmdir": "/usr/bin/rmdir",
        "sacct": "/usr/bin/sacct",
        "sbatch": "/usr/bin/sbatch",
        "scancel": "/usr/bin/scancel",
        "scontrol": "/usr/bin/scontrol",
        "sha256sum": "/usr/bin/sha256sum",
        "sleep": "/usr/bin/sleep",
        "squeue": "/usr/bin/squeue",
        "stat": "/usr/bin/stat",
    }
    tools = runtime.get("tools")
    if not isinstance(tools, dict) or set(tools) != set(required_tools):
        fail("runtime_tools_invalid")
    for label, expected_path in required_tools.items():
        record = tools.get(label)
        if (
            not isinstance(record, dict)
            or record.get("path") != expected_path
            or not isinstance(record.get("sha256"), str)
            or SHA256_RE.fullmatch(record["sha256"]) is None
        ):
            fail("runtime_tools_invalid")
        stable_bytes(
            Path(expected_path),
            expected_sha256=record["sha256"],
            mode=0o755,
            uid=0,
        )


def _seal_reservation(
    anchor: ReservationAnchor,
    committed: dict[str, bool],
) -> None:
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        anchor.revalidate(expected_mode=0o700)
        os.fsync(anchor.descriptor)
        os.fchmod(anchor.descriptor, 0o500)
        # Mode 0500 is the batch admission point.  Record it while handled
        # signals remain blocked and before any later operation can fail.
        committed["value"] = True
        os.fsync(anchor.descriptor)
        os.fsync(anchor.parent_fd)
        try:
            anchor.revalidate(expected_mode=0o500)
        except SubmissionError as error:
            raise LifecycleError("reservation_commit_ambiguous") from error
    except OSError as error:
        if committed["value"]:
            raise LifecycleError("reservation_commit_ambiguous") from error
        raise
    finally:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        except OSError:
            if not committed["value"]:
                raise


def _publish_success(
    anchor: ReservationAnchor,
    receipt_raw: bytes,
    permit_raw: bytes,
    committed: dict[str, bool],
) -> None:
    """Publish both admission records and make mode 0500 the sole commit point."""

    if committed != {"value": False}:
        fail("success_commit_state_invalid")
    expected_before = {"held_authorization.json", "launch_intent.json"}
    try:
        anchor.revalidate(expected_mode=0o700)
        if {entry.name for entry in os.scandir(anchor.descriptor)} != expected_before:
            fail("success_publication_invalid")
    except (OSError, RuntimeError) as error:
        raise SubmissionError("success_publication_invalid") from error
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    success_entries = {"activation_permit.json", "submission_receipt.json"}
    try:
        publish_once(anchor, "submission_receipt.json", receipt_raw)
        publish_once(anchor, "activation_permit.json", permit_raw)
        if {entry.name for entry in os.scandir(anchor.descriptor)} != expected_before | success_entries:
            fail("success_publication_invalid")
        anchor.revalidate(expected_mode=0o700)
        _seal_reservation(anchor, committed)
        # No fallible operation belongs after the durable mode transition.
    except BaseException as primary:
        if committed["value"]:
            raise
        rollback_failed = False
        try:
            for name in sorted(success_entries):
                try:
                    os.unlink(name, dir_fd=anchor.descriptor)
                except FileNotFoundError:
                    pass
                except OSError:
                    rollback_failed = True
            try:
                os.fsync(anchor.descriptor)
            except OSError:
                rollback_failed = True
            try:
                anchor.revalidate(expected_mode=0o700)
            except SubmissionError:
                rollback_failed = True
        except OSError:
            rollback_failed = True
        if rollback_failed:
            raise LifecycleError("success_publication_rollback_failed") from primary
        raise
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def _safe_exception_code(error: BaseException | None) -> str:
    if isinstance(error, SubmissionInterrupted):
        return "submission_interrupted"
    if isinstance(error, SubmissionError):
        code = str(error)
        if SAFE_CODE_RE.fullmatch(code):
            return code
    return "submission_failed"


def _failure_body(
    authorization_path: Path,
    authorization_sha256: str,
    reservation_identity: Mapping[str, int],
    code: str,
    cancellation: Mapping[str, Any] | None,
) -> bytes:
    return _envelope(
        {
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "artifact_type": FAILURE_TYPE,
            "state": "failed",
            "code": code if SAFE_CODE_RE.fullmatch(code) else "submission_failed",
            "audit_authorization": {
                "path": str(authorization_path),
                "sha256": authorization_sha256,
            },
            "reservation_identity": dict(reservation_identity),
            "cancellation": dict(cancellation or {}),
            "promotion_authorized": False,
        },
        "submission_failure_sha256",
    )


def submit(
    authorization_path: Path,
    authorization_sha256: str,
    wrapper: bytes,
    wrapper_sha256: str,
    python_path: Path,
    python_sha256: str,
    batch_arguments: Sequence[str],
    certificate: str,
    private_key: str,
    *,
    runner: Runner | None = None,
    sbatch_invoker: Callable[[Sequence[str], bytes, Mapping[str, str]], tuple[str, int, bytes]] = invoke_sbatch,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    authorization = load_authorization(authorization_path, authorization_sha256)
    submission = authorization["audit_submission"]
    root = Path(submission["reservation_dir"])
    scheduler_environment = _scheduler_environment(certificate, private_key)
    if runner is None:
        runner = lambda argv, timeout: run_command(  # noqa: E731
            argv,
            timeout,
            scheduler_environment=scheduler_environment,
        )
    if sha256_bytes(wrapper) != wrapper_sha256:
        fail("wrapper_capture_invalid")
    source_artifacts = authorization["source"]["artifacts"]
    expected_wrapper = source_artifacts.get("production_audit_wrapper")
    if expected_wrapper != {
        "path": str(
            Path(authorization["source"]["project_root"])
            / "user/tianhaowu/terminal_bench_vmvm/run_trace_production_audit.sbatch"
        ),
        "sha256": wrapper_sha256,
    }:
        fail("wrapper_capture_invalid")
    validate_python(authorization, python_path, python_sha256)
    source_digest = sha256_bytes(canonical_json(validate_source(authorization)))
    run_dir = Path(authorization["run"]["path"])
    if any(
        os.path.lexists(run_dir / name)
        for name in (
            "production_trace_certificate.json",
            "production_trace_checkpoint.json",
        )
    ):
        fail("audit_output_already_exists")
    if scheduler_name_matches(submission["job_name"], submission["cluster"], runner):
        fail("scheduler_name_not_fresh")
    reservation_anchor = create_reservation(root)
    reservation_identity = reservation_anchor.record()
    committed = {"value": False}
    job_id: str | None = None
    direct_candidate: str | None = None
    direct_provenance = False
    submission_attempted = False
    no_job_proved = False
    conflict_seen: set[str] = set()
    cancellation: Mapping[str, Any] | None = None
    old_handlers: dict[signal.Signals, Any] = {}

    def interrupted(_signum: int, _frame: Any) -> None:
        if not committed["value"]:
            raise SubmissionInterrupted()

    for handled in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        old_handlers[handled] = signal.signal(handled, interrupted)
    try:
        intent_body = {
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "artifact_type": INTENT_TYPE,
            "state": "reserved",
            "audit_authorization": {
                "path": str(authorization_path),
                "sha256": authorization_sha256,
            },
            "job_name_sha256": sha256_bytes(submission["job_name"].encode("ascii")),
            "wrapper_sha256": wrapper_sha256,
            "source_manifest_sha256": source_digest,
            "policy": submission["policy"],
            "reservation_identity": reservation_identity,
        }
        intent_raw = _envelope(intent_body, "launch_intent_sha256")
        intent_sha256 = publish_once(
            reservation_anchor,
            "launch_intent.json",
            intent_raw,
        )

        # This is the final mutable-input/name gate adjacent to the sole sbatch.
        if load_authorization(authorization_path, authorization_sha256) != authorization:
            fail("authorization_changed")
        validate_python(authorization, python_path, python_sha256)
        if sha256_bytes(canonical_json(validate_source(authorization))) != source_digest:
            fail("source_changed")
        canonical_wrapper = stable_bytes(
            Path(expected_wrapper["path"]),
            expected_sha256=wrapper_sha256,
            mode=None,
        )
        if canonical_wrapper != wrapper:
            fail("wrapper_capture_invalid")
        if scheduler_name_matches(submission["job_name"], submission["cluster"], runner):
            fail("scheduler_name_not_fresh")
        if any(
            os.path.lexists(run_dir / name)
            for name in (
                "production_trace_certificate.json",
                "production_trace_checkpoint.json",
            )
        ):
            fail("audit_output_already_exists")

        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        try:
            reservation_anchor.revalidate(expected_mode=0o700)
            submission_attempted = True
            outcome, returncode, stdout = sbatch_invoker(
                _sbatch_command(
                    authorization,
                    [*batch_arguments, *reservation_anchor.batch_arguments()],
                ),
                wrapper,
                scheduler_environment,
            )
            direct_candidate = parse_sbatch_candidate(outcome, returncode, stdout)
            if direct_candidate is not None:
                job_id = direct_candidate
                direct_provenance = True
            job_id, resolved_direct, visibility = resolve_submission(
                submission["job_name"],
                submission["cluster"],
                direct_candidate,
                runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            direct_provenance = direct_provenance or resolved_direct
            no_job_proved = job_id is None
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if job_id is None:
            if outcome == "completed" and returncode == 0:
                fail("sbatch_success_without_job")
            fail("sbatch_submission_failed")

        held = poll_phase(
            authorization,
            job_id,
            held=True,
            timeout=HELD_TIMEOUT_SECONDS,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
            conflict_latch=conflict_seen,
        )
        conflict_seen.update(held["explicit_conflict_fields"])
        if conflict_seen:
            raise LifecycleError("scheduler_identity_conflict")
        if held["converged"] is not True:
            raise LifecycleError("held_identity_not_converged")
        held_after = poll_phase(
            authorization,
            job_id,
            held=True,
            timeout=QUERY_TIMEOUT_SECONDS * 2,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
            conflict_latch=conflict_seen,
        )
        conflict_seen.update(held_after["explicit_conflict_fields"])
        if conflict_seen:
            raise LifecycleError("scheduler_identity_conflict")
        if held_after["converged"] is not True:
            raise LifecycleError("held_identity_not_converged")
        reservation_anchor.revalidate(expected_mode=0o700)
        held_body = {
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "artifact_type": HELD_AUTHORIZATION_TYPE,
            "state": "held_authorized",
            "audit_authorization": {
                "path": str(authorization_path),
                "sha256": authorization_sha256,
            },
            "intent_sha256": intent_sha256,
            "job": {
                "cluster": submission["cluster"],
                "id": job_id,
                "name": submission["job_name"],
            },
            "held": held,
            "held_after_authorization": held_after,
            "wrapper_sha256": wrapper_sha256,
            "reservation_identity": reservation_identity,
        }
        held_raw = _envelope(held_body, "held_authorization_sha256")
        held_sha256 = publish_once(
            reservation_anchor,
            "held_authorization.json",
            held_raw,
        )

        precontrol, precontrol_conflicts = _precontrol_identity(
            authorization,
            job_id,
            runner=runner,
            conflict_latch=conflict_seen,
        )
        conflict_seen.update(precontrol_conflicts)
        if conflict_seen:
            raise LifecycleError("scheduler_identity_conflict")
        if precontrol != "exact":
            raise LifecycleError("release_identity_unavailable")
        final_held = poll_phase(
            authorization,
            job_id,
            held=True,
            timeout=QUERY_TIMEOUT_SECONDS * 2,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
            conflict_latch=conflict_seen,
        )
        conflict_seen.update(final_held["explicit_conflict_fields"])
        if conflict_seen:
            raise LifecycleError("scheduler_identity_conflict")
        if final_held["converged"] is not True:
            raise LifecycleError("held_state_lost_before_release")
        reservation_anchor.revalidate(expected_mode=0o700)
        release = runner(
            ["/usr/bin/scontrol", "-M", submission["cluster"], "release", job_id],
            QUERY_TIMEOUT_SECONDS,
        )
        release_outcome = (
            "completed" if release.returncode == 0 and not release.stdout and not release.stderr else "nonzero"
        )
        if release_outcome != "completed":
            raise LifecycleError("release_failed")
        activation = poll_phase(
            authorization,
            job_id,
            held=False,
            timeout=ACTIVATION_TIMEOUT_SECONDS,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
            conflict_latch=conflict_seen,
        )
        conflict_seen.update(activation["explicit_conflict_fields"])
        if conflict_seen:
            raise LifecycleError("scheduler_identity_conflict")
        if activation["converged"] is not True:
            raise LifecycleError("activation_not_converged")
        reservation_anchor.revalidate(expected_mode=0o700)

        if load_authorization(authorization_path, authorization_sha256) != authorization:
            raise LifecycleError("authorization_changed")
        validate_python(authorization, python_path, python_sha256)
        if sha256_bytes(canonical_json(validate_source(authorization))) != source_digest:
            raise LifecycleError("source_changed")
        if canonical_wrapper != stable_bytes(
            Path(expected_wrapper["path"]),
            expected_sha256=wrapper_sha256,
            mode=None,
        ):
            raise LifecycleError("wrapper_capture_invalid")
        if any(
            os.path.lexists(run_dir / name)
            for name in (
                "production_trace_certificate.json",
                "production_trace_checkpoint.json",
            )
        ):
            raise LifecycleError("audit_output_already_exists")
        receipt_body = {
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "artifact_type": RECEIPT_TYPE,
            "state": "submitted",
            "audit_authorization": {
                "path": str(authorization_path),
                "sha256": authorization_sha256,
            },
            "intent_sha256": intent_sha256,
            "held_authorization": {
                "path": str(root / "held_authorization.json"),
                "sha256": held_sha256,
            },
            "job": held_body["job"],
            "held": held,
            "held_after_authorization": held_after,
            "held_before_release": final_held,
            "release": {"attempts": 1, "outcome": release_outcome},
            "activation": activation,
            "submission_visibility": visibility,
            "source_manifest_sha256": source_digest,
            "wrapper_sha256": wrapper_sha256,
            "reservation_identity": reservation_identity,
            "promotion_authorized": False,
        }
        receipt_raw = _envelope(receipt_body, "submission_receipt_sha256")
        receipt_sha256 = sha256_bytes(receipt_raw)
        permit_raw = _envelope(
            {
                "schema_version": ADMISSION_SCHEMA_VERSION,
                "artifact_type": PERMIT_TYPE,
                "state": "activated",
                "audit_authorization": {
                    "path": str(authorization_path),
                    "sha256": authorization_sha256,
                },
                "submission_receipt": {
                    "path": str(root / "submission_receipt.json"),
                    "sha256": receipt_sha256,
                },
                "job_id_sha256": sha256_bytes(job_id.encode("ascii")),
                "job_name_sha256": sha256_bytes(submission["job_name"].encode("ascii")),
                "reservation_identity": reservation_identity,
            },
            "activation_permit_sha256",
        )
        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        try:
            _publish_success(
                reservation_anchor,
                receipt_raw,
                permit_raw,
                committed,
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        return {
            "state": "submitted",
            "submission_receipt_sha256": receipt_sha256,
        }
    except BaseException:
        primary = sys.exception()
        if committed["value"]:
            raise
        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        try:
            if submission_attempted and job_id is None and not no_job_proved:
                try:
                    recovered, recovered_direct, recovered_visibility = resolve_submission(
                        submission["job_name"],
                        submission["cluster"],
                        direct_candidate,
                        runner=runner,
                        sleeper=sleeper,
                        clock=clock,
                    )
                except BaseException:
                    cancellation = {
                        "cancel_attempts": 0,
                        "confirmed": False,
                        "explicit_conflict_fields": [],
                        "identity_status": "unknown_candidate",
                        "reason": "submission_outcome_unknown",
                    }
                    primary = LifecycleError("cancellation_unconfirmed", cancellation)
                else:
                    job_id = recovered
                    direct_provenance = direct_provenance or recovered_direct
                    visibility = recovered_visibility
                    no_job_proved = job_id is None
                    if no_job_proved:
                        cancellation = {
                            "cancel_attempts": 0,
                            "confirmed": True,
                            "explicit_conflict_fields": [],
                            "identity_status": "no_job_proved",
                            "reason": "no_job_proved",
                        }
            if job_id is not None:
                if conflict_seen:
                    cancellation = {
                        "cancel_attempts": 0,
                        "explicit_conflict_fields": sorted(conflict_seen),
                        "identity_status": "conflict",
                    }
                    primary = LifecycleError("cancellation_unconfirmed", cancellation)
                else:
                    try:
                        cancellation = cancel_and_prove(
                            authorization,
                            job_id,
                            direct_provenance=direct_provenance,
                            runner=runner,
                            sleeper=sleeper,
                            clock=clock,
                            conflict_latch=conflict_seen,
                        )
                    except LifecycleError as error:
                        cancellation = error.evidence
                        primary = error
                    except BaseException:
                        cancellation = {
                            "cancel_attempts": 0,
                            "explicit_conflict_fields": [],
                            "identity_status": "unavailable",
                        }
                        primary = LifecycleError("cancellation_unconfirmed", cancellation)
            try:
                reservation_anchor.revalidate(expected_mode=0o700)
            except SubmissionError:
                if isinstance(primary, LifecycleError) and str(primary) == "cancellation_unconfirmed":
                    primary.evidence["reservation_identity_status"] = "changed"
                else:
                    primary = LifecycleError(
                        "reservation_changed",
                        {"cancellation": dict(cancellation or {})},
                    )
            else:
                if any(
                    name in {entry.name for entry in os.scandir(reservation_anchor.descriptor)}
                    for name in ("submission_receipt.json", "activation_permit.json")
                ):
                    raise SubmissionError("success_publication_ambiguous")
                code = _safe_exception_code(primary)
                publish_once(
                    reservation_anchor,
                    "submission_failure.json",
                    _failure_body(
                        authorization_path,
                        authorization_sha256,
                        reservation_identity,
                        code,
                        cancellation,
                    ),
                )
                _seal_reservation(reservation_anchor, committed)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if primary is None:
            fail("submission_failed")
        raise primary
    finally:
        try:
            for handled, previous_handler in old_handlers.items():
                try:
                    signal.signal(handled, previous_handler)
                except (OSError, ValueError):
                    if not committed["value"]:
                        raise
        finally:
            reservation_anchor.close()


def _descriptor_bytes(descriptor: int, expected_sha256: str, *, sealed: bool) -> bytes:
    try:
        before = os.fstat(descriptor)
        body = b""
        while len(body) < before.st_size:
            block = os.pread(descriptor, min(1 << 20, before.st_size - len(body)), len(body))
            if not block:
                fail("captured_source_invalid")
            body += block
        after = os.fstat(descriptor)
        if sealed:
            required = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
            observed_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
        else:
            observed_seals = 0
    except OSError as error:
        raise SubmissionError("captured_source_invalid") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or _signature(before) != _signature(after)
        or sha256_bytes(body) != expected_sha256
        or (sealed and (before.st_nlink != 0 or observed_seals != required))
    ):
        fail("captured_source_invalid")
    return body


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--submitter-sha256", required=True)
    parser.add_argument("--wrapper-sha256", required=True)
    parser.add_argument("--bootstrap-sha256", required=True)
    parser.add_argument("--controller-sha256", required=True)
    parser.add_argument("--submission-controller-sha256", required=True)
    parser.add_argument("--python-path", type=Path, required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--tls-certificate", required=True)
    parser.add_argument("--tls-key", required=True)
    parser.add_argument("--submitter-fd", type=int, required=True)
    parser.add_argument("--wrapper-fd", type=int, required=True)
    args = parser.parse_args(argv)
    hashes = (
        args.authorization_sha256,
        args.submitter_sha256,
        args.wrapper_sha256,
        args.bootstrap_sha256,
        args.controller_sha256,
        args.submission_controller_sha256,
        args.python_sha256,
    )
    if any(SHA256_RE.fullmatch(value) is None for value in hashes):
        fail("expected_identity_invalid")
    authorization = load_authorization(args.authorization, args.authorization_sha256)
    source = authorization["source"]
    workflow = args.project_dir / "user/tianhaowu/terminal_bench_vmvm"
    expected_artifacts = {
        "production_audit_bootstrap": (
            workflow / "trace_production_bootstrap.py",
            args.bootstrap_sha256,
        ),
        "production_audit_submission_controller": (
            workflow / "trace_production_submit_control.py",
            args.submission_controller_sha256,
        ),
        "production_audit_submitter": (
            workflow / "submit_trace_production_audit.sh",
            args.submitter_sha256,
        ),
        "production_audit_wrapper": (
            workflow / "run_trace_production_audit.sbatch",
            args.wrapper_sha256,
        ),
        "production_certificate": (
            workflow / "certify_trace_production.py",
            args.controller_sha256,
        ),
    }
    if (
        source.get("project_root") != str(args.project_dir)
        or source.get("prime_rl_commit") != args.revision
        or source.get("prime_rl_git_tree") != args.tree
        or any(
            source.get("artifacts", {}).get(label) != {"path": str(path), "sha256": digest}
            for label, (path, digest) in expected_artifacts.items()
        )
    ):
        fail("source_authorization_invalid")
    submitter = _descriptor_bytes(args.submitter_fd, args.submitter_sha256, sealed=True)
    wrapper = _descriptor_bytes(args.wrapper_fd, args.wrapper_sha256, sealed=False)
    if submitter != stable_bytes(
        expected_artifacts["production_audit_submitter"][0],
        expected_sha256=args.submitter_sha256,
        mode=None,
    ):
        fail("submitter_capture_invalid")
    for credential in (args.tls_certificate, args.tls_key):
        descriptor = -1
        try:
            descriptor = os.open(credential, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            status = os.fstat(descriptor)
        except OSError as error:
            raise SubmissionError("scheduler_auth_invalid") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not stat.S_ISREG(status.st_mode):
            fail("scheduler_auth_invalid")
    batch_arguments = [
        str(args.authorization),
        args.authorization_sha256,
        str(args.project_dir),
        args.revision,
        args.tree,
        args.submitter_sha256,
        args.wrapper_sha256,
        args.bootstrap_sha256,
        args.controller_sha256,
        args.submission_controller_sha256,
        str(args.python_path),
        args.python_sha256,
        args.tls_certificate,
        args.tls_key,
        authorization["audit_submission"]["reservation_dir"],
        authorization["audit_submission"]["job_name"],
    ]
    result = submit(
        args.authorization,
        args.authorization_sha256,
        wrapper,
        args.wrapper_sha256,
        args.python_path,
        args.python_sha256,
        batch_arguments,
        args.tls_certificate,
        args.tls_key,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SubmissionError as error:
        code = str(error)
        if SAFE_CODE_RE.fullmatch(code) is None:
            code = "submission_failed"
        print(
            json.dumps({"code": code, "status": "error"}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except BaseException:
        print('{"code":"submission_failed","status":"error"}', file=sys.stderr)
        raise SystemExit(2) from None
