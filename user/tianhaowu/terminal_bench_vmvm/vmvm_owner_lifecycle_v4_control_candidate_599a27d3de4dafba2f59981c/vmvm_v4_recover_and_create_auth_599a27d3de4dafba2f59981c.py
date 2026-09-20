#!/usr/bin/python3.12
# ruff: noqa: BLE001, S102
"""Recover one hash-bound X2P value in-process and invoke the reviewed v4 creator."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
SYSTEM_PYTHON = Path("/usr/bin/python3.12")
AUTH_V2 = BASE / ("approvals/vmvm_owner_lifecycle_9d7841b36_v2_9a7c24d1e6b8035f0c42a719.authorization.json")
FAILURE_V2 = BASE / "diagnostics/vmvm_owner_lifecycle_9d7841b36_v2.probe-failure.json"
RESERVATION_V2 = BASE / "diagnostics/vmvm_owner_lifecycle_9d7841b36_v2.launch-reservation"
RECEIPT_V2 = RESERVATION_V2 / "submission_receipt.json"
ENVIRONMENT_V2 = RESERVATION_V2 / "slurm_environment.bin"
CREATOR_V4 = BASE / "diagnostics/create_vmvm_owner_lifecycle_authorization_v4_599a27d3de4dafba2f59981c.py"
SELF_PATH = BASE / ("diagnostics/vmvm_v4_recover_and_create_auth_599a27d3de4dafba2f59981c.py")
CREATOR_V4_SHA256 = "b80177040312e767b3be316be9938e5172495e4317b724eaf2d951392b2b8d97"
SELF_SHA_ENV = "EXPECTED_VMVM_V4_RECOVERY_CREATE_SHA256"
METADATA_HASH_ENV = {
    "authorization": "VMVM_V4_RECOVERY_V2_AUTHORIZATION_SHA256",
    "environment": "VMVM_V4_RECOVERY_V2_ENVIRONMENT_SHA256",
    "failure": "VMVM_V4_RECOVERY_V2_FAILURE_SHA256",
    "receipt": "VMVM_V4_RECOVERY_V2_RECEIPT_SHA256",
}
OWNER_UID = 656177
JOB_NAME_V2 = "vmvm-owner-v2-9a7c24d1e6b8035f0c42a719"
SOURCE_REVISION = "9d7841b36bafcd58769041925b00deba7c25ffca"
BACKEND_SHA256 = "13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a"
HANDLED_SIGNALS = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
SUCCESS_OUTPUT = b'{"kind":"vmvm_v4_credential_recovery_candidate","state":"passed"}\n'
FAILURE_OUTPUT = b'{"code":"credential_recovery_failed","state":"failed"}\n'
INTERRUPTED = False
TERMINAL_LATCHED = False


class RecoveryInterrupted(BaseException):
    pass


def signal_handler(_signum: int, _frame: object) -> None:
    global INTERRUPTED, TERMINAL_LATCHED
    INTERRUPTED = True
    if TERMINAL_LATCHED:
        return
    TERMINAL_LATCHED = True
    raise RecoveryInterrupted


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


def stable_file(path: Path, *, mode: int, expected: str, maximum: int = 1 << 20) -> bytes:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        raw = bytearray()
        while len(raw) <= maximum:
            block = os.read(descriptor, min(65536, maximum + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            signature(before) != signature(opened)
            or signature(opened) != signature(after)
            or signature(after) != signature(named)
            or not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != mode
            or opened.st_uid != OWNER_UID
            or opened.st_nlink != 1
            or len(raw) != opened.st_size
            or len(raw) > maximum
            or hashlib.sha256(raw).hexdigest() != expected
        ):
            raise RuntimeError("file_identity")
        return bytes(raw)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_object(raw: bytes, *, newline: bool) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("json") from error
    if not isinstance(value, dict) or raw != canonical(value) + (b"\n" if newline else b""):
        raise RuntimeError("canonical")
    return value


def parse_environment(raw: bytes) -> dict[str, str]:
    if not raw or not raw.endswith(b"\0"):
        raise RuntimeError("environment")
    parsed: dict[str, str] = {}
    for record in raw[:-1].split(b"\0"):
        name, separator, value = record.partition(b"=")
        if separator != b"=" or not name or not name.isascii() or b"\0" in value:
            raise RuntimeError("environment")
        decoded_name = name.decode("ascii")
        if decoded_name in parsed or re.fullmatch(r"[A-Z][A-Z0-9_]*", decoded_name) is None:
            raise RuntimeError("environment")
        parsed[decoded_name] = value.decode("utf-8", "strict")
    return parsed


def validate_environment() -> tuple[str, dict[str, str]]:
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
        or re.fullmatch(r"[0-9a-f]{64}", self_sha) is None
        or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in metadata_hashes.values())
        or os.getuid() != OWNER_UID
        or os.geteuid() != OWNER_UID
        or Path.cwd() != Path("/storage/home/tianhaowu")
        or Path(sys.executable).resolve(strict=True) != SYSTEM_PYTHON
    ):
        raise RuntimeError("environment")
    return self_sha, metadata_hashes


def stable_creator() -> types.ModuleType:
    raw = stable_file(CREATOR_V4, mode=0o500, expected=CREATOR_V4_SHA256)
    module = types.ModuleType("vmvm_owner_lifecycle_authorization_creator_v4_recovered")
    module.__file__ = str(CREATOR_V4)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(CREATOR_V4), "exec"), module.__dict__)
    return module


def recover_proxy(metadata_hashes: dict[str, str]) -> str:
    if set(metadata_hashes) != set(METADATA_HASH_ENV):
        raise RuntimeError("metadata")
    auth_raw = stable_file(
        AUTH_V2,
        mode=0o400,
        expected=metadata_hashes["authorization"],
    )
    failure_raw = stable_file(
        FAILURE_V2,
        mode=0o400,
        expected=metadata_hashes["failure"],
    )
    receipt_raw = stable_file(
        RECEIPT_V2,
        mode=0o400,
        expected=metadata_hashes["receipt"],
    )
    environment_raw = stable_file(
        ENVIRONMENT_V2,
        mode=0o400,
        expected=metadata_hashes["environment"],
    )
    auth = canonical_object(auth_raw, newline=False)
    failure = canonical_object(failure_raw, newline=True)
    receipt = canonical_object(receipt_raw, newline=True)
    environment = parse_environment(environment_raw)

    auth_body = dict(auth)
    authorization_sha = auth_body.pop("authorization_sha256", None)
    if (
        auth.get("schema_version") != 1
        or auth.get("artifact_type") != "vmvm_owner_lifecycle_diagnostic_authorization_v2"
        or auth.get("state") != "approved"
        or not isinstance(authorization_sha, str)
        or hashlib.sha256(canonical(auth_body)).hexdigest() != authorization_sha
        or not isinstance(auth.get("launch"), dict)
        or auth["launch"].get("job_name") != JOB_NAME_V2
    ):
        raise RuntimeError("authorization")

    failure_job = failure.get("job")
    receipt_job = receipt.get("job")
    if (
        failure.get("schema_version") != 1
        or failure.get("artifact_type") != "vmvm_owner_lifecycle_probe_failure_receipt_v2"
        or failure.get("state") != "failed"
        or failure.get("failure_class") != "site_binding_invalid"
        or failure.get("cleanup_status") != "verified"
        or failure.get("diagnostic_only") is not True
        or failure.get("production_authorized") is not False
        or failure.get("task_data_accessed") is not False
        or failure.get("model_endpoint_accessed") is not False
        or failure.get("source_revision") != SOURCE_REVISION
        or failure.get("backend_sha256") != BACKEND_SHA256
        or not isinstance(failure_job, dict)
        or failure_job != receipt_job
        or failure_job.get("job_name") != JOB_NAME_V2
        or failure_job.get("cluster") != "fair-cw-use2-3"
        or re.fullmatch(r"[1-9][0-9]*", str(failure_job.get("job_id"))) is None
        or failure.get("authorization_file_sha256") != hashlib.sha256(auth_raw).hexdigest()
        or failure.get("authorization_sha256") != authorization_sha
        or failure.get("environment_sha256") != hashlib.sha256(environment_raw).hexdigest()
        or failure.get("submission_receipt_sha256") != hashlib.sha256(receipt_raw).hexdigest()
    ):
        raise RuntimeError("failure_lineage")

    if (
        receipt.get("artifact_type") != "vmvm_owner_lifecycle_submission_receipt_v2"
        or receipt.get("state") != "submitted"
        or receipt.get("production_authorized") is not False
        or receipt.get("submission_attempts") != 1
        or receipt.get("release_attempts") != 1
        or receipt.get("release_outcome") != "completed"
        or receipt.get("authorization_file_sha256") != hashlib.sha256(auth_raw).hexdigest()
        or receipt.get("authorization_sha256") != authorization_sha
        or receipt.get("environment_sha256") != hashlib.sha256(environment_raw).hexdigest()
    ):
        raise RuntimeError("receipt_lineage")

    credentials = auth.get("credentials")
    if not isinstance(credentials, dict) or set(credentials) != {"tls", "x2p"}:
        raise RuntimeError("credentials")
    x2p = credentials.get("x2p")
    if not isinstance(x2p, dict) or set(x2p) != {
        "X2P_ENV",
        "X2P_CFG_ENV",
        "X2P_PROXY_URL",
    }:
        raise RuntimeError("credentials")
    for name in ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL"):
        record = x2p.get(name)
        value = environment.get(name)
        if (
            not isinstance(record, dict)
            or set(record) != {"sha256"}
            or not isinstance(value, str)
            or not value
            or "\0" in value
            or "\n" in value
            or "\r" in value
            or len(value.encode()) > 4096
            or hashlib.sha256(value.encode()).hexdigest() != record.get("sha256")
        ):
            raise RuntimeError("credentials")
    if environment["X2P_ENV"] != os.environ["X2P_ENV"] or environment["X2P_CFG_ENV"] != os.environ["X2P_CFG_ENV"]:
        raise RuntimeError("credentials")
    return environment["X2P_PROXY_URL"]


def canonicalize_tls(environment: dict[str, str]) -> None:
    for name in ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH"):
        raw_path = environment.get(name, "")
        if not raw_path or not Path(raw_path).is_absolute():
            raise RuntimeError("credentials")
        path = Path(os.path.realpath(raw_path))
        if path.resolve(strict=True) != path:
            raise RuntimeError("credentials")
        environment[name] = str(path)


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
    global INTERRUPTED, TERMINAL_LATCHED
    INTERRUPTED = False
    TERMINAL_LATCHED = False
    terminal = (2, FAILURE_OUTPUT, 2)
    terminal_result = 2
    secret_state: dict[str, str | None] = {"proxy": None}
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"audit", "execute"}:
            raise RuntimeError("arguments")
        mode = sys.argv[1]
        install_signal_handlers()
        self_sha, metadata_hashes = validate_environment()
        if Path(__file__).resolve(strict=True) != SELF_PATH:
            raise RuntimeError("self_path")
        stable_file(SELF_PATH, mode=0o500, expected=self_sha)
        if INTERRUPTED:
            raise RuntimeError("interrupted")
        secret_state["proxy"] = recover_proxy(metadata_hashes)
        creator = stable_creator()
        if INTERRUPTED:
            raise RuntimeError("interrupted")
        os.environ.pop(SELF_SHA_ENV, None)
        for environment_name in METADATA_HASH_ENV.values():
            os.environ.pop(environment_name, None)
        os.environ["X2P_PROXY_URL"] = secret_state["proxy"] or ""
        canonicalize_tls(os.environ)
        if mode == "audit":
            launcher = creator.load_launcher()
            creator.validate_environment(launcher)
            if creator.AUTHORIZATION.exists() or creator.AUTHORIZATION.is_symlink():
                raise RuntimeError("authorization_exists")
            launcher.validate_source()
            launcher._ensure_absent()
            if not launcher._name_absent(creator.JOB_NAME, datetime.now(UTC).date().isoformat()):
                raise RuntimeError("job_name_exists")
            body = creator.authorization_body(launcher)
            authorization_sha = launcher.sha256_bytes(launcher.canonical_json(body))
            authorization = {**body, "authorization_sha256": authorization_sha}
            paths = {label: creator.LAUNCHER.parent / name for label, (name, _mode) in creator.FILE_MODES.items()}
            launcher.validate_authorization(
                authorization,
                launcher=paths["launcher"],
                wrapper=paths["wrapper"],
                probe=paths["probe"],
                finalizer=paths["finalizer"],
            )
            terminal = (1, SUCCESS_OUTPUT, 0)
        else:
            creator.install_signal_handlers()
            creator.create_authorization()
            terminal = (1, creator.SUCCESS_OUTPUT, 0)
        TERMINAL_LATCHED = True
    except BaseException:
        TERMINAL_LATCHED = True
        terminal = (2, FAILURE_OUTPUT, 2)
    finally:
        terminal_result = terminalize(*terminal, secret_state)
    return terminal_result


if __name__ == "__main__":
    raise SystemExit(main())
