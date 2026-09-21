#!/usr/bin/python3.12
"""Recover the sealed VMVM proxy only inside the one-shot v4 launcher process."""

from __future__ import annotations

import hashlib
import os
import signal
import stat
import sys
import types
from pathlib import Path

OWNER_UID = 656177
SYSTEM_PYTHON = Path("/usr/bin/python3.12")
RECOVERY_HELPER = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/"
    "vmvm_v4_recover_and_create_auth_599a27d3de4dafba2f59981c.py"
)
RECOVERY_HELPER_SHA256 = "e1bdd66650218e647ca874145fc8b31afaa7594e56d2d08c54b78d93040cb68c"
LAUNCHER = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/"
    "vmvm_owner_lifecycle_9d7841b36_v4/launch_vmvm_owner_lifecycle_v4.py"
)
LAUNCHER_SHA256 = "354595d2f0822052d6b42cfe12233d9629f75c82a01060745c33ca308000a731"
AUTHORIZATION = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/approvals/"
    "vmvm_owner_lifecycle_9d7841b36_v4_599a27d3de4dafba2f59981c."
    "authorization.json"
)
SELF_PATH = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_v4_recover_and_launch_599a27d3de4dafba2f59981c.py"
)
SELF_SHA_ENV = "EXPECTED_VMVM_V4_LAUNCH_RECOVERY_SHA256"
AUTHORIZATION_SHA_ENV = "EXPECTED_VMVM_V4_AUTHORIZATION_SHA256"
METADATA_HASH_ENV = {
    "authorization": "VMVM_V4_RECOVERY_V2_AUTHORIZATION_SHA256",
    "environment": "VMVM_V4_RECOVERY_V2_ENVIRONMENT_SHA256",
    "failure": "VMVM_V4_RECOVERY_V2_FAILURE_SHA256",
    "receipt": "VMVM_V4_RECOVERY_V2_RECEIPT_SHA256",
}
HANDLED_SIGNALS = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
SUCCESS_OUTPUT = b'{"kind":"vmvm_v4_launch_recovery_candidate","state":"passed"}\n'
SUBMISSION_OUTPUT = b'{"state":"submitted","submission_attempts":1}\n'
FAILURE_OUTPUT = b'{"code":"vmvm_v4_launch_recovery_failed","state":"failed"}\n'
INTERRUPTED = False
TERMINAL_LATCHED = False
SUBMISSION_COMMITTED = False


class LaunchRecoveryInterrupted(BaseException):
    pass


def signal_handler(_signum: int, _frame: object) -> None:
    global INTERRUPTED, TERMINAL_LATCHED
    INTERRUPTED = True
    if TERMINAL_LATCHED:
        return
    TERMINAL_LATCHED = True
    raise LaunchRecoveryInterrupted


def install_signal_handlers() -> None:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal_handler)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def emit_bounded(descriptor: int, payload: bytes) -> None:
    if len(payload) > 256 or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise RuntimeError("output_contract")
    if os.write(descriptor, payload) != len(payload):
        raise RuntimeError("output_write")


def signature(info: os.stat_result) -> tuple[int, ...]:
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


def stable_file(path: Path, *, mode: int, expected: str, maximum: int) -> bytes:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    parent_fd = -1
    fd = -1
    try:
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != mode
            or before.st_uid != OWNER_UID
            or before.st_gid != OWNER_UID
            or before.st_nlink != 1
            or before.st_size > maximum
        ):
            raise RuntimeError("identity")
        fd = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        opened = os.fstat(fd)
        if signature(opened) != signature(before):
            raise RuntimeError("identity")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise RuntimeError("identity")
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if signature(after) != signature(opened) or signature(named) != signature(opened):
            raise RuntimeError("identity")
    finally:
        if fd >= 0:
            os.close(fd)
        if parent_fd >= 0:
            os.close(parent_fd)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("identity")
    return raw


def validate_environment() -> tuple[str, str, dict[str, str]]:
    allowed = {
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
        SELF_SHA_ENV,
        AUTHORIZATION_SHA_ENV,
        *METADATA_HASH_ENV.values(),
    }
    expected = {
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
    }
    self_sha = os.environ.get(SELF_SHA_ENV, "")
    authorization_sha = os.environ.get(AUTHORIZATION_SHA_ENV, "")
    metadata_hashes = {
        label: os.environ.get(environment_name, "") for label, environment_name in METADATA_HASH_ENV.items()
    }
    if (
        set(os.environ) != allowed
        or any(os.environ.get(name) != value for name, value in expected.items())
        or not os.environ.get("TMUX")
        or not os.environ.get("THRIFT_TLS_CL_CERT_PATH")
        or not os.environ.get("THRIFT_TLS_CL_KEY_PATH")
        or not os.environ.get("X2P_ENV")
        or not os.environ.get("X2P_CFG_ENV")
        or len(self_sha) != 64
        or any(character not in "0123456789abcdef" for character in self_sha)
        or len(authorization_sha) != 64
        or any(character not in "0123456789abcdef" for character in authorization_sha)
        or any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in metadata_hashes.values()
        )
        or os.getuid() != OWNER_UID
        or os.geteuid() != OWNER_UID
        or Path.cwd() != Path("/storage/home/tianhaowu")
        or Path(sys.executable).resolve(strict=True) != SYSTEM_PYTHON
    ):
        raise RuntimeError("environment")
    return self_sha, authorization_sha, metadata_hashes


def stable_recovery_module() -> types.ModuleType:
    raw = stable_file(
        RECOVERY_HELPER,
        mode=0o500,
        expected=RECOVERY_HELPER_SHA256,
        maximum=1 << 20,
    )
    module = types.ModuleType("vmvm_v4_recovery_for_one_shot_launch")
    module.__file__ = str(RECOVERY_HELPER)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(RECOVERY_HELPER), "exec"), module.__dict__)  # noqa: S102
    return module


def stable_launcher_module(raw: bytes) -> types.ModuleType:
    module = types.ModuleType("vmvm_owner_lifecycle_v4_for_one_shot_launch")
    module.__file__ = str(LAUNCHER)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(LAUNCHER), "exec"), module.__dict__)  # noqa: S102
    return module


def canonicalize_tls(environment: dict[str, str]) -> None:
    for name in ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH"):
        raw_path = environment.get(name, "")
        if not raw_path or not Path(raw_path).is_absolute():
            raise RuntimeError("credentials")
        path = Path(os.path.realpath(raw_path))
        if path.resolve(strict=True) != path:
            raise RuntimeError("credentials")
        environment[name] = str(path)


def audit_launcher(launcher: types.ModuleType, authorization_sha: str) -> None:
    launcher._validate_outer_environment()
    authorization, authorization_raw, _authorization_sha = launcher.load_authorization(AUTHORIZATION, authorization_sha)
    artifact_root = LAUNCHER.parent
    private = launcher.validate_authorization(
        authorization,
        launcher=LAUNCHER,
        wrapper=artifact_root / "run_vmvm_owner_lifecycle_v4.sbatch",
        probe=artifact_root / "probe_vmvm_owner_lifecycle_v4.py",
        finalizer=artifact_root / "finalize_vmvm_owner_lifecycle_v4.py",
    )
    launcher.validate_source()
    launcher._ensure_absent()
    start_date = launcher.datetime.now(launcher.UTC).date().isoformat()
    if not launcher._name_absent(private["job_name"], start_date):
        raise RuntimeError("namespace")
    del authorization_raw


def launch_with_commit_latch(launcher: types.ModuleType, authorization_sha: str) -> dict[str, object]:
    global SUBMISSION_COMMITTED, TERMINAL_LATCHED
    original_publish_success = launcher._publish_success

    def publish_success(*args: object, **kwargs: object) -> object:
        global SUBMISSION_COMMITTED, TERMINAL_LATCHED
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        try:
            return original_publish_success(*args, **kwargs)
        finally:
            commit_state = kwargs.get("commit_state")
            if isinstance(commit_state, dict) and commit_state == {"committed": True}:
                SUBMISSION_COMMITTED = True
                TERMINAL_LATCHED = True
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    launcher._publish_success = publish_success
    try:
        result = launcher.launch(AUTHORIZATION, authorization_sha)
    finally:
        launcher._publish_success = original_publish_success
    return result


def terminalize(
    descriptor: int,
    payload: bytes,
    returncode: int,
    secret_state: dict[str, str | None],
) -> int:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        os.environ.pop("X2P_PROXY_URL", None)
        os.environ.pop(SELF_SHA_ENV, None)
        os.environ.pop(AUTHORIZATION_SHA_ENV, None)
        for environment_name in METADATA_HASH_ENV.values():
            os.environ.pop(environment_name, None)
        secret_state["proxy"] = None
        try:
            emit_bounded(descriptor, payload)
        except BaseException:
            return 2
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    return returncode


def main() -> int:
    global INTERRUPTED, SUBMISSION_COMMITTED, TERMINAL_LATCHED
    INTERRUPTED = False
    SUBMISSION_COMMITTED = False
    TERMINAL_LATCHED = False
    terminal = (2, FAILURE_OUTPUT, 2)
    terminal_result = 2
    secret_state: dict[str, str | None] = {"proxy": None}
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"audit", "execute"}:
            raise RuntimeError("arguments")
        mode = sys.argv[1]
        install_signal_handlers()
        self_sha, authorization_sha, metadata_hashes = validate_environment()
        if Path(__file__).resolve(strict=True) != SELF_PATH:
            raise RuntimeError("self_path")
        stable_file(
            SELF_PATH,
            mode=0o500,
            expected=self_sha,
            maximum=1 << 20,
        )
        recovery = stable_recovery_module()
        if recovery.METADATA_HASH_ENV != METADATA_HASH_ENV:
            raise RuntimeError("recovery_contract")
        launcher_raw = stable_file(
            LAUNCHER,
            mode=0o500,
            expected=LAUNCHER_SHA256,
            maximum=4 << 20,
        )
        stable_file(
            AUTHORIZATION,
            mode=0o400,
            expected=authorization_sha,
            maximum=1 << 20,
        )
        if INTERRUPTED:
            raise LaunchRecoveryInterrupted
        secret_state["proxy"] = recovery.recover_proxy(metadata_hashes)
        if INTERRUPTED:
            raise LaunchRecoveryInterrupted
        child_environment = {
            name: value
            for name, value in os.environ.items()
            if name
            not in {
                SELF_SHA_ENV,
                AUTHORIZATION_SHA_ENV,
                *METADATA_HASH_ENV.values(),
            }
        }
        child_environment["APPROVED_DIAGNOSTIC_LAUNCHER_SHA256"] = LAUNCHER_SHA256
        child_environment["X2P_PROXY_URL"] = secret_state["proxy"] or ""
        canonicalize_tls(child_environment)
        arguments = [
            str(LAUNCHER),
            "--authorization",
            str(AUTHORIZATION),
            "--authorization-file-sha256",
            authorization_sha,
        ]
        launcher = stable_launcher_module(launcher_raw)
        os.environ.clear()
        os.environ.update(child_environment)
        sys.argv = arguments
        if mode == "audit":
            audit_launcher(launcher, authorization_sha)
            terminal = (1, SUCCESS_OUTPUT, 0)
        else:
            launcher._validate_outer_environment()
            result = launch_with_commit_latch(launcher, authorization_sha)
            if result != {"state": "submitted", "submission_attempts": 1}:
                raise RuntimeError("launcher_result")
            terminal = (1, SUBMISSION_OUTPUT, 0)
        TERMINAL_LATCHED = True
    except BaseException:  # noqa: BLE001
        TERMINAL_LATCHED = True
        terminal = (1, SUBMISSION_OUTPUT, 0) if SUBMISSION_COMMITTED else (2, FAILURE_OUTPUT, 2)
    finally:
        terminal_result = terminalize(*terminal, secret_state)
    return terminal_result


if __name__ == "__main__":
    raise SystemExit(main())
