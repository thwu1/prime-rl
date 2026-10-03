#!/usr/bin/python3.12
# ruff: noqa: BLE001
"""Invoke one reviewed VMVM v4 recovery helper through retained file descriptors."""

from __future__ import annotations

import hashlib
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, NamedTuple

BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
SYSTEM_PYTHON = Path("/usr/bin/python3.12")
WORKING_DIRECTORY = Path("/storage/home/tianhaowu")
TOKEN = "599a27d3de4dafba2f59981c"
SELF_PATH = BASE / f"diagnostics/invoke_vmvm_owner_lifecycle_v4_{TOKEN}.py"
SELF_SHA_ENV = "EXPECTED_VMVM_V4_INVOCATION_SHA256"

CREATOR = BASE / f"diagnostics/create_vmvm_owner_lifecycle_authorization_v4_{TOKEN}.py"
RECOVER_CREATE = BASE / f"diagnostics/vmvm_v4_recover_and_create_auth_{TOKEN}.py"
RECOVER_LAUNCH = BASE / f"diagnostics/vmvm_v4_recover_and_launch_{TOKEN}.py"
AUTHORIZATION_V4 = BASE / (f"approvals/vmvm_owner_lifecycle_9d7841b36_v4_{TOKEN}.authorization.json")
CONTROL_FILES = {
    "creator": (
        CREATOR,
        "b80177040312e767b3be316be9938e5172495e4317b724eaf2d951392b2b8d97",
    ),
    "create": (
        RECOVER_CREATE,
        "e1bdd66650218e647ca874145fc8b31afaa7594e56d2d08c54b78d93040cb68c",
    ),
    "launch": (
        RECOVER_LAUNCH,
        "d91ec94418153eba17320aacc71c8c84a3f6b251abf3311c4ef41663a0637455",
    ),
}

AUTHORIZATION_V2 = BASE / ("approvals/vmvm_owner_lifecycle_9d7841b36_v2_9a7c24d1e6b8035f0c42a719.authorization.json")
FAILURE_V2 = BASE / "diagnostics/vmvm_owner_lifecycle_9d7841b36_v2.probe-failure.json"
RESERVATION_V2 = BASE / "diagnostics/vmvm_owner_lifecycle_9d7841b36_v2.launch-reservation"
RECEIPT_V2 = RESERVATION_V2 / "submission_receipt.json"
ENVIRONMENT_V2 = RESERVATION_V2 / "slurm_environment.bin"
LINEAGE_FILES = {
    "authorization": AUTHORIZATION_V2,
    "environment": ENVIRONMENT_V2,
    "failure": FAILURE_V2,
    "receipt": RECEIPT_V2,
}
METADATA_HASH_ENV = {
    "authorization": "VMVM_V4_RECOVERY_V2_AUTHORIZATION_SHA256",
    "environment": "VMVM_V4_RECOVERY_V2_ENVIRONMENT_SHA256",
    "failure": "VMVM_V4_RECOVERY_V2_FAILURE_SHA256",
    "receipt": "VMVM_V4_RECOVERY_V2_RECEIPT_SHA256",
}
HELPER_SHA_ENV = {
    "create": "EXPECTED_VMVM_V4_RECOVERY_CREATE_SHA256",
    "launch": "EXPECTED_VMVM_V4_LAUNCH_RECOVERY_SHA256",
}
AUTHORIZATION_SHA_ENV = "EXPECTED_VMVM_V4_AUTHORIZATION_SHA256"

OWNER_UID = 656177
HANDLED_SIGNALS = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
MAXIMUM_ARTIFACT_BYTES = 1 << 20
CHILD_TIMEOUT_SECONDS = 3_600
CHILD_TERM_GRACE_SECONDS = 720
CHILD_KILL_GRACE_SECONDS = 10
POLL_SECONDS = 1.0
FAILURE_OUTPUT = b'{"code":"vmvm_v4_invocation_failed","state":"failed"}\n'
SUCCESS_OUTPUT = {
    ("create", "audit"): b'{"kind":"vmvm_v4_invocation","operation":"create_audit","state":"passed"}\n',
    ("create", "execute"): b'{"kind":"vmvm_v4_invocation","operation":"create_execute","state":"created"}\n',
    ("launch", "audit"): b'{"kind":"vmvm_v4_invocation","operation":"launch_audit","state":"passed"}\n',
    ("launch", "execute"): b'{"kind":"vmvm_v4_invocation","operation":"launch_execute","state":"submitted"}\n',
}
EXPECTED_CHILD_OUTPUT = {
    ("create", "audit"): b'{"kind":"vmvm_v4_credential_recovery_candidate","state":"passed"}\n',
    ("create", "execute"): (
        b'{"kind":"vmvm_owner_lifecycle_diagnostic_authorization_create_v4_candidate","state":"created"}\n'
    ),
    ("launch", "audit"): b'{"kind":"vmvm_v4_launch_recovery_candidate","state":"passed"}\n',
    ("launch", "execute"): b'{"state":"submitted","submission_attempts":1}\n',
}

INTERRUPTED = False
INTERRUPT_SIGNAL: int | None = None
TERMINAL_LATCHED = False
CHILD_OUTCOME: tuple[str, str] | None = None


class BoundFile(NamedTuple):
    descriptor: int
    parent_descriptor: int
    path: Path
    identity: tuple[int, ...]
    sha256: str


def signal_handler(signum: int, _frame: object) -> None:
    global INTERRUPTED, INTERRUPT_SIGNAL
    if TERMINAL_LATCHED:
        return
    INTERRUPTED = True
    if INTERRUPT_SIGNAL is None:
        INTERRUPT_SIGNAL = signum


def install_signal_handlers() -> None:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal_handler)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def open_directory_components(path: Path) -> int:
    if not path.is_absolute() or path != Path(*path.parts):
        raise RuntimeError("path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            if component in {"", ".", ".."}:
                raise RuntimeError("path")
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            previous_descriptor = descriptor
            descriptor = child
            os.close(previous_descriptor)
        if os.readlink(f"/proc/self/fd/{descriptor}") != str(path):
            raise RuntimeError("directory_identity")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_descriptor_hash(descriptor: int, maximum: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while total <= maximum:
        block = os.read(descriptor, min(65536, maximum + 1 - total))
        if not block:
            break
        total += len(block)
        digest.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if total > maximum:
        raise RuntimeError("file_size")
    return digest.hexdigest(), total


def open_bound_file(
    path: Path,
    *,
    mode: int,
    maximum: int = MAXIMUM_ARTIFACT_BYTES,
    expected_sha256: str | None = None,
) -> BoundFile:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    parent_descriptor = -1
    descriptor = -1
    try:
        parent_descriptor = open_directory_components(path.parent)
        before = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(descriptor)
        observed_sha256, observed_size = read_descriptor_hash(descriptor, maximum)
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        identity = file_identity(opened)
        if (
            descriptor < 3
            or parent_descriptor < 3
            or file_identity(before) != identity
            or file_identity(after) != identity
            or file_identity(named) != identity
            or not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != mode
            or opened.st_uid != OWNER_UID
            or opened.st_nlink != 1
            or observed_size != opened.st_size
            or (expected_sha256 is not None and observed_sha256 != expected_sha256)
            or os.readlink(f"/proc/self/fd/{descriptor}") != str(path)
        ):
            raise RuntimeError("file_identity")
        return BoundFile(
            descriptor=descriptor,
            parent_descriptor=parent_descriptor,
            path=path,
            identity=identity,
            sha256=observed_sha256,
        )
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        raise
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def verify_bound_name(bound: BoundFile) -> None:
    opened = os.fstat(bound.descriptor)
    named = os.stat(bound.path.name, dir_fd=bound.parent_descriptor, follow_symlinks=False)
    if (
        file_identity(opened) != bound.identity
        or file_identity(named) != bound.identity
        or os.readlink(f"/proc/self/fd/{bound.descriptor}") != str(bound.path)
    ):
        raise RuntimeError("file_identity")


def close_bound_file(bound: BoundFile) -> None:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        try:
            os.close(bound.descriptor)
        finally:
            os.close(bound.parent_descriptor)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def stable_hash(path: Path, *, mode: int, expected_sha256: str | None = None) -> str:
    bound = open_bound_file(path, mode=mode, expected_sha256=expected_sha256)
    try:
        verify_bound_name(bound)
        return bound.sha256
    finally:
        close_bound_file(bound)


def validate_self_invocation(expected_sha256: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RuntimeError("self_hash")
    match = re.fullmatch(r"/proc/self/fd/([1-9][0-9]*)", sys.argv[0])
    if match is None or Path(__file__) != Path(sys.argv[0]):
        raise RuntimeError("self_invocation")
    descriptor = int(match.group(1))
    if descriptor < 3:
        raise RuntimeError("self_invocation")
    opened = os.fstat(descriptor)
    observed_sha256, observed_size = read_descriptor_hash(descriptor, MAXIMUM_ARTIFACT_BYTES)
    parent_descriptor = open_directory_components(SELF_PATH.parent)
    try:
        named = os.stat(SELF_PATH.name, dir_fd=parent_descriptor, follow_symlinks=False)
    finally:
        os.close(parent_descriptor)
    if (
        file_identity(opened) != file_identity(named)
        or not stat.S_ISREG(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o500
        or opened.st_uid != OWNER_UID
        or opened.st_nlink != 1
        or observed_size != opened.st_size
        or observed_sha256 != expected_sha256
        or os.readlink(f"/proc/self/fd/{descriptor}") != str(SELF_PATH)
    ):
        raise RuntimeError("self_identity")


def checked_environment_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise RuntimeError("environment") from error
    if not value or len(encoded) > 4096 or any(character in value for character in ("\0", "\n", "\r")):
        raise RuntimeError("environment")
    return value


def build_child_environment(environment: Mapping[str, str]) -> dict[str, str]:
    if (
        os.getuid() != OWNER_UID
        or os.geteuid() != OWNER_UID
        or Path.cwd() != WORKING_DIRECTORY
        or Path(sys.executable).resolve(strict=True) != SYSTEM_PYTHON
        or sys.flags.isolated != 1
        or sys.flags.no_site != 1
        or sys.flags.dont_write_bytecode != 1
        or environment.get("TMUX_PANE") != "%0"
    ):
        raise RuntimeError("execution_context")
    selected = {
        name: checked_environment_value(environment, name)
        for name in (
            "TMUX",
            "THRIFT_TLS_CL_CERT_PATH",
            "THRIFT_TLS_CL_KEY_PATH",
            "X2P_ENV",
            "X2P_CFG_ENV",
        )
    }
    for name in ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH"):
        if not Path(selected[name]).is_absolute():
            raise RuntimeError("environment")
    return {
        "HOME": str(WORKING_DIRECTORY),
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX": selected["TMUX"],
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
        "THRIFT_TLS_CL_CERT_PATH": selected["THRIFT_TLS_CL_CERT_PATH"],
        "THRIFT_TLS_CL_KEY_PATH": selected["THRIFT_TLS_CL_KEY_PATH"],
        "X2P_ENV": selected["X2P_ENV"],
        "X2P_CFG_ENV": selected["X2P_CFG_ENV"],
    }


def validate_child_environment(target: str, environment: Mapping[str, str]) -> None:
    expected_names = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "TMUX",
        "TMUX_PANE",
        "TZ",
        "USER",
        "THRIFT_TLS_CL_CERT_PATH",
        "THRIFT_TLS_CL_KEY_PATH",
        "X2P_ENV",
        "X2P_CFG_ENV",
        HELPER_SHA_ENV[target],
        *METADATA_HASH_ENV.values(),
    }
    if target == "launch":
        expected_names.add(AUTHORIZATION_SHA_ENV)
    fixed = {
        "HOME": str(WORKING_DIRECTORY),
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
    }
    hash_names = {*METADATA_HASH_ENV.values(), HELPER_SHA_ENV[target]}
    if target == "launch":
        hash_names.add(AUTHORIZATION_SHA_ENV)
    if (
        set(environment) != expected_names
        or any(environment.get(name) != value for name, value in fixed.items())
        or environment.get(HELPER_SHA_ENV[target]) != CONTROL_FILES[target][1]
        or any(re.fullmatch(r"[0-9a-f]{64}", environment.get(name, "")) is None for name in hash_names)
    ):
        raise RuntimeError("child_environment")
    for name in (
        "TMUX",
        "THRIFT_TLS_CL_CERT_PATH",
        "THRIFT_TLS_CL_KEY_PATH",
        "X2P_ENV",
        "X2P_CFG_ENV",
    ):
        checked_environment_value(environment, name)
    if any(not Path(environment[name]).is_absolute() for name in ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH")):
        raise RuntimeError("child_environment")


def process_start_ticks(process_id: int) -> int:
    raw = Path(f"/proc/{process_id}/stat").read_text()
    close = raw.rfind(")")
    fields = raw[close + 2 :].split()
    if close < 0 or len(fields) < 20:
        raise RuntimeError("process_identity")
    return int(fields[19])


def same_process(process_id: int, start_ticks: int) -> bool:
    try:
        return process_start_ticks(process_id) == start_ticks
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        return False


def group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def signal_child_group(
    process: subprocess.Popen[bytes],
    process_group: int,
    start_ticks: int,
    signum: int,
) -> None:
    if process.poll() is None:
        if same_process(process.pid, start_ticks):
            try:
                current_group = os.getpgid(process.pid)
            except ProcessLookupError:
                current_group = -1
            if current_group not in {-1, process_group}:
                raise RuntimeError("process_identity")
        elif process.poll() is None:
            raise RuntimeError("process_identity")
    if group_exists(process_group):
        os.killpg(process_group, signum)


def terminate_child(
    process: subprocess.Popen[bytes],
    process_group: int,
    start_ticks: int,
    initial_signal: int,
) -> tuple[bytes, bytes]:
    signal_child_group(process, process_group, start_ticks, initial_signal)
    term_deadline = time.monotonic() + CHILD_TERM_GRACE_SECONDS
    try:
        return process.communicate(timeout=CHILD_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        signal_child_group(process, process_group, start_ticks, signal.SIGKILL)
        try:
            return process.communicate(timeout=CHILD_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("child_cleanup") from error
    finally:
        while group_exists(process_group) and time.monotonic() < term_deadline:
            time.sleep(min(0.1, max(0.0, term_deadline - time.monotonic())))
        if group_exists(process_group):
            os.killpg(process_group, signal.SIGKILL)
            kill_deadline = time.monotonic() + CHILD_KILL_GRACE_SECONDS
            while group_exists(process_group) and time.monotonic() < kill_deadline:
                time.sleep(min(0.1, max(0.0, kill_deadline - time.monotonic())))
        if group_exists(process_group):
            raise RuntimeError("child_cleanup")


def reap_spawn_failure(process: subprocess.Popen[bytes]) -> None:
    process_group = -1
    try:
        process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        if process_group == process.pid:
            os.killpg(process_group, signal.SIGTERM)
        else:
            process.terminate()
    try:
        process.communicate(timeout=CHILD_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        if process_group == process.pid and group_exists(process_group):
            os.killpg(process_group, signal.SIGKILL)
        else:
            process.kill()
        try:
            process.communicate(timeout=CHILD_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("child_cleanup") from error
    if process_group == process.pid and group_exists(process_group):
        os.killpg(process_group, signal.SIGKILL)
        deadline = time.monotonic() + CHILD_KILL_GRACE_SECONDS
        while group_exists(process_group) and time.monotonic() < deadline:
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if group_exists(process_group):
            raise RuntimeError("child_cleanup")


def invoke_helper(
    bound: BoundFile,
    *,
    target: str,
    mode: str,
    environment: Mapping[str, str],
) -> tuple[int, bytes, bytes]:
    global CHILD_OUTCOME, INTERRUPTED, TERMINAL_LATCHED
    validate_child_environment(target, environment)
    verify_bound_name(bound)
    process: subprocess.Popen[bytes] | None = None
    process_group = -1
    start_ticks = -1
    try:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        try:
            if INTERRUPTED:
                raise RuntimeError("interrupted")
            process = subprocess.Popen(
                [str(SYSTEM_PYTHON), "-I", "-S", "-B", f"/proc/self/fd/{bound.descriptor}", mode],
                cwd=WORKING_DIRECTORY,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=(bound.descriptor,),
                start_new_session=True,
            )
            start_ticks = process_start_ticks(process.pid)
            process_group = os.getpgid(process.pid)
            if process_group != process.pid:
                raise RuntimeError("process_group")
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except BaseException:
        if process is not None:
            reap_spawn_failure(process)
        raise

    started = time.monotonic()
    interrupted_at: float | None = None
    timed_out = False
    stdout = b""
    stderr = b""
    try:
        while True:
            now = time.monotonic()
            if INTERRUPTED and interrupted_at is None:
                interrupted_at = now
                signal_child_group(
                    process,
                    process_group,
                    start_ticks,
                    INTERRUPT_SIGNAL or signal.SIGTERM,
                )
            if interrupted_at is None and now - started >= CHILD_TIMEOUT_SECONDS:
                timed_out = True
                interrupted_at = now
                signal_child_group(process, process_group, start_ticks, signal.SIGTERM)
            if interrupted_at is not None and now - interrupted_at >= CHILD_TERM_GRACE_SECONDS:
                signal_child_group(process, process_group, start_ticks, signal.SIGKILL)
                try:
                    stdout, stderr = process.communicate(timeout=CHILD_KILL_GRACE_SECONDS)
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError("child_cleanup") from error
                break
            deadline = (
                interrupted_at + CHILD_TERM_GRACE_SECONDS
                if interrupted_at is not None
                else started + CHILD_TIMEOUT_SECONDS
            )
            try:
                stdout, stderr = process.communicate(timeout=min(POLL_SECONDS, max(0.01, deadline - now)))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            stdout, stderr = terminate_child(
                process,
                process_group,
                start_ticks,
                signal.SIGTERM,
            )
    if process.returncode is None or same_process(process.pid, start_ticks):
        raise RuntimeError("child_reap")
    exact_success = process.returncode == 0 and stdout == EXPECTED_CHILD_OUTPUT[(target, mode)] and not stderr
    if exact_success:
        CHILD_OUTCOME = (target, mode)
        TERMINAL_LATCHED = True
    if group_exists(process_group):
        terminate_child(process, process_group, start_ticks, signal.SIGTERM)
        raise RuntimeError("child_descendant")
    if timed_out and not exact_success:
        raise RuntimeError("child_timeout")
    return process.returncode, stdout, stderr


def prepare_invocation(target: str, environment: dict[str, str]) -> tuple[BoundFile, dict[str, str]]:
    metadata_hashes = {label: stable_hash(path, mode=0o400) for label, path in LINEAGE_FILES.items()}
    for label, (path, expected_sha256) in CONTROL_FILES.items():
        if label != target:
            stable_hash(path, mode=0o500, expected_sha256=expected_sha256)
    helper_path, helper_sha256 = CONTROL_FILES[target]
    bound = open_bound_file(
        helper_path,
        mode=0o500,
        expected_sha256=helper_sha256,
    )
    try:
        environment[HELPER_SHA_ENV[target]] = helper_sha256
        for label, environment_name in METADATA_HASH_ENV.items():
            environment[environment_name] = metadata_hashes[label]
        if target == "launch":
            environment[AUTHORIZATION_SHA_ENV] = stable_hash(AUTHORIZATION_V4, mode=0o400)
        return bound, environment
    except BaseException:
        close_bound_file(bound)
        raise
    finally:
        metadata_hashes.clear()


def emit_bounded(descriptor: int, payload: bytes) -> None:
    if len(payload) > 256 or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise RuntimeError("output_contract")
    if os.write(descriptor, payload) != len(payload):
        raise RuntimeError("output_write")


def terminalize(descriptor: int, payload: bytes, returncode: int) -> int:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        os.environ.clear()
        try:
            emit_bounded(descriptor, payload)
        except BaseException:
            return 2
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    return returncode


def main() -> int:
    global CHILD_OUTCOME, INTERRUPTED, INTERRUPT_SIGNAL, TERMINAL_LATCHED
    INTERRUPTED = False
    INTERRUPT_SIGNAL = None
    TERMINAL_LATCHED = False
    CHILD_OUTCOME = None
    terminal = (2, FAILURE_OUTPUT, 2)
    child_environment: dict[str, str] = {}
    bound: BoundFile | None = None
    try:
        install_signal_handlers()
        if len(sys.argv) != 3 or sys.argv[1] not in {"create", "launch"} or sys.argv[2] not in {"audit", "execute"}:
            raise RuntimeError("arguments")
        target, mode = sys.argv[1:]
        expected_self_sha256 = os.environ.get(SELF_SHA_ENV, "")
        validate_self_invocation(expected_self_sha256)
        child_environment = build_child_environment(os.environ)
        os.environ.clear()
        if INTERRUPTED:
            raise RuntimeError("interrupted")
        bound, child_environment = prepare_invocation(target, child_environment)
        if INTERRUPTED:
            raise RuntimeError("interrupted")
        verify_bound_name(bound)
        returncode, stdout, stderr = invoke_helper(
            bound,
            target=target,
            mode=mode,
            environment=child_environment,
        )
        if returncode != 0 or stdout != EXPECTED_CHILD_OUTPUT[(target, mode)] or stderr:
            raise RuntimeError("helper_outcome")
        terminal = (1, SUCCESS_OUTPUT[(target, mode)], 0)
        TERMINAL_LATCHED = True
    except BaseException:
        TERMINAL_LATCHED = True
        terminal = (1, SUCCESS_OUTPUT[CHILD_OUTCOME], 0) if CHILD_OUTCOME is not None else (2, FAILURE_OUTPUT, 2)
    finally:
        child_environment.clear()
        if bound is not None:
            try:
                close_bound_file(bound)
            except BaseException:
                if terminal[2] != 0:
                    terminal = (2, FAILURE_OUTPUT, 2)
        return terminalize(*terminal)


if __name__ == "__main__":
    raise SystemExit(main())
