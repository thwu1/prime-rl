#!/usr/bin/env python3
"""Two-stage, authorization-bound control for the retained VMVM v4 scratch root."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

TOKEN = "f6ce50ed0fbe4782ecf8b9af"
OWNER = "tianhaowu"
OWNER_UID = 656177
OWNER_IDENTITY = "tianhaowu(656177)"
CLUSTER = "fair-cw-use2-3"
TARGET_NODE = "cpu-140-255"
TARGET_ROOT = Path("/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch")
QUARANTINE_ROOT = TARGET_ROOT.with_name(
    "tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch-quarantine-7d204ee4a313968c25bfbda7"
)
FAILED_JOB_ID = "1760059"
FAILED_RECEIPT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_owner_lifecycle_9d7841b36_v4.probe-failure.json"
)
FAILED_JOB_EXPECTED = {
    "Account": "ram",
    "Elapsed": "00:03:59",
    "ExitCode": "2:0",
    "JobIDRaw": FAILED_JOB_ID,
    "NodeList": TARGET_NODE,
    "Partition": "cpu_x86",
    "QOS": "cpu_x86_lowest",
    "State": "FAILED",
    "User": OWNER,
}
FAILED_RECEIPT_SHA256 = "d99b126b71913a59304e9cc8af400dee09ac84901a0f4dad52eef18111824ae2"
BASE_COMMIT = "bf22bf5c6228da3efd14e8279ca61d9ab64c6116"
BASE_TREE = "0c29f9985332e20865b1696f4b90d96512cfdcf1"
RECOVERY_SUBTREE = "64cbc0a1c180b29b2b0a85820a8e3031f0437fda"
RECOVERY_HELPER_SHA256 = "faf05cc04b15c0193d575c6cb1a946bd7677966497e4db53db6abf53c97a6840"
V4_SOURCE_COMMIT = "ea035668d4b43d1bf8fe588ca4469a2b7a46c5a3"
V4_SOURCE_TREE = "9ed4462ca48f288608fccfeb79dadae23b6470c8"
EVALUATOR_COMMIT = "9d7841b36bafcd58769041925b00deba7c25ffca"
EVALUATOR_TREE = "7f4027723ab036b888b1baee8c0d51c962653f68"
VERIFIERS_REVISION = "615b1a30ee3d23cf8d835b64174229c19da887bc"
RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
BACKEND_SHA256 = "13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a"

BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
BUNDLE = BASE / f"watchers/vmvm_v4_scratch_recovery_controls_{TOKEN}"
PREFLIGHT_RECEIPT = BASE / f"approvals/vmvm_v4_scratch_recovery_{TOKEN}.preflight.json"
AUDIT_AUTHORIZATION = BASE / f"approvals/vmvm_v4_scratch_recovery_{TOKEN}.audit.approval.json"
RECOVERY_AUTHORIZATION = BASE / f"approvals/vmvm_v4_scratch_recovery_{TOKEN}.recover.approval.json"
AUDIT_RECEIPT = BASE / f"diagnostics/vmvm_v4_scratch_recovery_{TOKEN}.audit.json"
RECOVERY_RECEIPT = BASE / f"diagnostics/vmvm_v4_scratch_recovery_{TOKEN}.recovery.json"
AUDIT_LOG = BASE / f"logs/vmvm_v4_scratch_recovery_{TOKEN}.audit-%j.log"
RECOVERY_LOG = BASE / f"logs/vmvm_v4_scratch_recovery_{TOKEN}.recover-%j.log"
AUDIT_RESERVATION = BASE / f"locks/vmvm_v4_scratch_recovery_{TOKEN}.audit.lock"
RECOVERY_RESERVATION = BASE / f"locks/vmvm_v4_scratch_recovery_{TOKEN}.recover.lock"

MANIFEST = BUNDLE / "manifest.json"
CONTROL = BUNDLE / "control.py"
BATCH = BUNDLE / "run_stage.sbatch"
HELPER = BUNDLE / "recover_vmvm_owner_lifecycle_v4_scratch.py"
README = BUNDLE / "README.md"
AUDIT_JOB_NAME = f"vmvm-v4-audit-{TOKEN[:12]}"
RECOVERY_JOB_NAME = f"vmvm-v4-recover-{TOKEN[:12]}"
COMMENT_PREFIX = f"vmvm-v4-scratch:{TOKEN}:"

SBATCH = Path("/usr/bin/sbatch")
SCONTROL = Path("/usr/bin/scontrol")
SQUEUE = Path("/usr/bin/squeue")
SACCT = Path("/usr/bin/sacct")
SCANCEL = Path("/usr/bin/scancel")
TOOL_HASHES = {
    Path("/usr/bin/python3.12"): "1a301bb1763139d48ae638d97b11edf56de6cd185e1b054eae6dc28c271c0c5f",
    Path("/usr/bin/bash"): "af955ef55333c8fc9c5aa50df91ad1a629d9a79a9afa125cd5e9629585f78015",
    Path("/usr/bin/sha256sum"): "0d7b5c0cc4132d6a17b3a005f2949d0e2b16bbd7f43c35c9de251ef673742f19",
    SBATCH: "3c1029c3a436107bf48b3b2d450e5fd1c9b204e6674906005cbbbb3c7df7feda",
    SCONTROL: "395549996ab93fbbb806b8d68d355a97d9dbdf28dad2f421872b8d1fbdabe4ad",
    SQUEUE: "45fa838a4882d58d7bd2604f52b79aae98fafe1d165008d56f7220a4e7faf341",
    SACCT: "5149de553e71a44118c6f30e0f7bba5cb55f540308a7943f084f24709b588c57",
    SCANCEL: "6b8c2c876e8e47b42995901d7c51244fca8c0f180ba9b6a4c3ed7373fdeebac9",
}
STAGES = frozenset({"audit", "recover"})
SHA_RE = re.compile(r"[0-9a-f]{64}")
JOB_RE = re.compile(r"[1-9][0-9]{0,19}")
FD_RE = re.compile(r"/proc/self/fd/([3-9]|[1-9][0-9]+)")
MAX_JSON = 64 * 1024
SETTLE_SECONDS = 2.0
QUERY_TIMEOUT = 20
JOB_TIME_LIMIT = "00:15:00"
JOB_CPUS = "1"
JOB_MEMORY = "1G"
PARTITION = "cpu_x86"
QOS = "cpu_x86_lowest"
ACCOUNT = "ram"
PUBLIC_KINDS = {
    "preflight": "vmvm_v4_scratch_static_preflight_public_v1",
    "authorize-audit": "vmvm_v4_scratch_authorization_public_v1",
    "authorize-recover": "vmvm_v4_scratch_authorization_public_v1",
    "launch-audit": "vmvm_v4_scratch_launch_public_v1",
    "launch-recover": "vmvm_v4_scratch_launch_public_v1",
    "node-audit": "vmvm_v4_scratch_stage_public_v1",
    "node-recover": "vmvm_v4_scratch_stage_public_v1",
}
PUBLIC_CATEGORIES = frozenset(
    {
        "success",
        "authorization",
        "binding",
        "freshness",
        "host",
        "inventory",
        "internal",
        "interrupted",
        "old_job",
        "publication",
        "quiescence",
        "root_state",
        "scheduler",
    }
)
FORBIDDEN_ENV_PREFIXES = ("X2P_", "THRIFT_TLS_", "AWS_", "HF_", "WANDB_")
FORBIDDEN_ENV_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MODEL",
        "MODEL_ID",
        "TASK_ID",
        "DATASET",
    }
)
STATIC_SAFE_ENV = {
    "HOME": "/nonexistent",
    "USER": OWNER,
    "LOGNAME": OWNER,
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "SLURM_CLUSTER_NAME": CLUSTER,
}
HANDLED_SIGNALS = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
_COMMITTED_ACTION: str | None = None


class ControlError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category if category in PUBLIC_CATEGORIES else "internal"


class Interrupted(ControlError):
    def __init__(self) -> None:
        super().__init__("interrupted")


@dataclass
class BoundFile:
    fd: int
    payload: bytes
    digest: str
    identity: tuple[int, int, int, int, int, int]

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


@dataclass(frozen=True)
class SubmitAttempt:
    stdout: bytes
    stderr: bytes
    returncode: int | None
    outcome: str


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise ControlError("publication")
        view = view[written:]


def _read_all(fd: int, maximum: int = MAX_JSON) -> bytes:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > maximum:
        raise ControlError("binding")
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(fd, min(1 << 20, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    payload = b"".join(chunks)
    if len(payload) != info.st_size or len(payload) > maximum:
        raise ControlError("binding")
    return payload


def _open_absolute_parent(path: Path) -> tuple[int, str]:
    if not path.is_absolute() or str(path) != os.path.normpath(path) or path.name in {"", ".", ".."}:
        raise ControlError("binding")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    chains: list[list[int]] = []
    try:
        for _index in range(2):
            chain = [os.open("/", flags)]
            chains.append(chain)
            for component in path.parent.parts[1:]:
                if component in {"", ".", ".."}:
                    raise ControlError("binding")
                chain.append(os.open(component, flags, dir_fd=chain[-1]))
        signatures = [
            [(s.st_dev, s.st_ino, s.st_mode, s.st_uid) for fd in chain for s in (os.fstat(fd),)] for chain in chains
        ]
        if signatures[0] != signatures[1]:
            raise ControlError("binding")
        return os.dup(chains[0][-1]), path.name
    except OSError as error:
        raise ControlError("binding") from error
    finally:
        for chain in chains:
            for fd in reversed(chain):
                os.close(fd)


def open_bound_file(
    path: Path,
    *,
    mode: int,
    maximum: int = MAX_JSON,
    expected_sha256: str | None = None,
    owner_uid: int = OWNER_UID,
) -> BoundFile:
    parent_fd, name = _open_absolute_parent(path)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        info = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_uid != owner_uid
            or info.st_nlink != 1
            or (named.st_dev, named.st_ino, named.st_mode, named.st_uid, named.st_nlink, named.st_size) != identity
        ):
            raise ControlError("binding")
        payload = _read_all(fd, maximum)
        observed = digest(payload)
        if expected_sha256 is not None and observed != expected_sha256:
            raise ControlError("binding")
        named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_nlink, after.st_size) != identity or (
            named_after.st_dev,
            named_after.st_ino,
            named_after.st_mode,
            named_after.st_uid,
            named_after.st_nlink,
            named_after.st_size,
        ) != identity:
            raise ControlError("binding")
        return BoundFile(fd, payload, observed, identity)
    except OSError as error:
        with contextlib.suppress(UnboundLocalError, OSError):
            os.close(fd)
        raise ControlError("binding") from error
    except BaseException:
        with contextlib.suppress(UnboundLocalError, OSError):
            os.close(fd)
        raise
    finally:
        os.close(parent_fd)


def parse_canonical_json(bound: BoundFile, *, artifact_type: str) -> dict[str, object]:
    if not bound.payload.endswith(b"\n") or bound.payload.count(b"\n") != 1:
        raise ControlError("binding")
    try:
        value = json.loads(bound.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ControlError("binding") from error
    if not isinstance(value, dict) or canonical(value) != bound.payload or value.get("artifact_type") != artifact_type:
        raise ControlError("binding")
    return value


def publish_exclusive(path: Path, value: object, *, mode: int = 0o400) -> str:
    payload = canonical(value)
    parent_fd, name = _open_absolute_parent(path)
    fd = -1
    try:
        parent_info = os.fstat(parent_fd)
        if stat.S_IMODE(parent_info.st_mode) != 0o700 or parent_info.st_uid != OWNER_UID:
            raise ControlError("publication")
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=parent_fd,
        )
        _write_all(fd, payload)
        os.fsync(fd)
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != mode
            or opened.st_uid != OWNER_UID
            or opened.st_nlink != 1
            or (named.st_dev, named.st_ino, named.st_mode, named.st_uid, named.st_nlink, named.st_size)
            != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink, opened.st_size)
        ):
            raise ControlError("publication")
        os.lseek(fd, 0, os.SEEK_SET)
        if os.read(fd, len(payload) + 1) != payload:
            raise ControlError("publication")
        final_named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        final_opened = os.fstat(fd)
        if final_opened.st_size != len(payload) or (
            final_opened.st_dev,
            final_opened.st_ino,
            final_opened.st_mode,
            final_opened.st_uid,
            final_opened.st_nlink,
        ) != (final_named.st_dev, final_named.st_ino, final_named.st_mode, final_named.st_uid, final_named.st_nlink):
            raise ControlError("publication")
        os.fsync(parent_fd)
        return digest(payload)
    except FileExistsError as error:
        raise ControlError("freshness") from error
    except OSError as error:
        raise ControlError("publication") from error
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def _existing_publication(path: Path, value: object) -> str:
    payload = canonical(value)
    bound = open_bound_file(path, mode=0o400)
    try:
        if bound.payload != payload:
            raise ControlError("publication")
        return bound.digest
    finally:
        bound.close()


def _commit_publication(action: str, path: Path, value: object, *, irreversible: bool = False) -> str:
    global _COMMITTED_ACTION
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    if not irreversible and signal.sigpending() & HANDLED_SIGNALS:
        raise Interrupted()
    try:
        published = publish_exclusive(path, value)
    except BaseException as error:
        if not irreversible:
            raise
        try:
            published = _existing_publication(path, value)
        except BaseException:
            raise error
    _COMMITTED_ACTION = action
    return published


def _validate_tool(path: Path) -> None:
    bound = open_bound_file(
        path,
        mode=0o755,
        maximum=8 << 20,
        expected_sha256=TOOL_HASHES[path],
        owner_uid=0,
    )
    bound.close()


def _run(arguments: Sequence[str], *, timeout: int = QUERY_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            env=STATIC_SAFE_ENV,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ControlError("scheduler") from error
    if len(result.stdout) > 1 << 20 or len(result.stderr) > 1 << 20:
        raise ControlError("scheduler")
    return result


def _squeue_absent(job_id: str) -> None:
    result = _run((str(SQUEUE), "-M", CLUSTER, "-h", "-j", job_id, "-o", "%A|%T|%R"))
    if result.returncode != 0 or result.stderr or result.stdout.strip():
        raise ControlError("old_job")


def _accounting_snapshot(job_id: str, *, expected: Mapping[str, str]) -> bytes:
    fields = tuple(expected)
    result = _run(
        (
            str(SACCT),
            "-M",
            CLUSTER,
            "-X",
            "-n",
            "-P",
            "-j",
            job_id,
            "-o",
            ",".join(fields),
        )
    )
    if result.returncode != 0 or result.stderr:
        raise ControlError("old_job")
    rows = [line.split("|") for line in result.stdout.decode("ascii", "strict").splitlines() if line]
    if len(rows) != 1 or len(rows[0]) != len(fields):
        raise ControlError("old_job")
    observed = dict(zip(fields, rows[0], strict=True))
    if any(observed[name] != value for name, value in expected.items()):
        raise ControlError("old_job")
    return result.stdout


def stable_terminal_job(job_id: str, *, expected: Mapping[str, str]) -> str:
    _squeue_absent(job_id)
    first = _accounting_snapshot(job_id, expected=expected)
    time.sleep(0.05)
    _squeue_absent(job_id)
    second = _accounting_snapshot(job_id, expected=expected)
    if first != second:
        raise ControlError("old_job")
    return digest(first)


def _manifest() -> tuple[BoundFile, dict[str, object]]:
    _require_private_directory(BUNDLE, mode=0o555)
    expected = os.environ.get("EXPECTED_VMVM_V4_RECOVERY_MANIFEST_SHA256")
    if SHA_RE.fullmatch(expected or "") is None:
        raise ControlError("binding")
    bound = open_bound_file(MANIFEST, mode=0o400, expected_sha256=expected)
    value = parse_canonical_json(bound, artifact_type="vmvm_v4_scratch_recovery_controls_manifest_v1")
    required = {
        "artifact_type",
        "base_commit",
        "base_tree",
        "control_source_commit",
        "control_source_subtree",
        "control_source_tree",
        "files",
        "recovery_subtree",
        "schema_version",
        "token",
    }
    if set(value) != required or value != {
        "artifact_type": "vmvm_v4_scratch_recovery_controls_manifest_v1",
        "base_commit": BASE_COMMIT,
        "base_tree": BASE_TREE,
        "control_source_commit": value.get("control_source_commit"),
        "control_source_subtree": value.get("control_source_subtree"),
        "control_source_tree": value.get("control_source_tree"),
        "files": value.get("files"),
        "recovery_subtree": RECOVERY_SUBTREE,
        "schema_version": 1,
        "token": TOKEN,
    }:
        bound.close()
        raise ControlError("binding")
    if any(
        SHA_RE.fullmatch(str(value.get(name, ""))) is None
        for name in ("control_source_commit", "control_source_subtree", "control_source_tree")
    ):
        bound.close()
        raise ControlError("binding")
    files = value.get("files")
    required_files = {
        "README.md": 0o400,
        "control.py": 0o500,
        "recover_vmvm_owner_lifecycle_v4_scratch.py": 0o500,
        "run_stage.sbatch": 0o500,
    }
    if not isinstance(files, dict) or set(files) != set(required_files):
        bound.close()
        raise ControlError("binding")
    control_record = files.get("control.py")
    if not isinstance(control_record, dict) or control_record.get("sha256") != os.environ.get(
        "VMVM_V4_RECOVERY_CONTROL_SHA256"
    ):
        bound.close()
        raise ControlError("binding")
    try:
        for name, mode in required_files.items():
            record = files.get(name)
            if (
                not isinstance(record, dict)
                or set(record) != {"mode", "sha256", "size"}
                or record.get("mode") != format(mode, "04o")
                or SHA_RE.fullmatch(str(record.get("sha256", ""))) is None
                or type(record.get("size")) is not int
                or int(record["size"]) < 1
                or int(record["size"]) > 2 << 20
            ):
                raise ControlError("binding")
            item = open_bound_file(
                BUNDLE / name,
                mode=mode,
                maximum=max(MAX_JSON, int(record["size"])),
                expected_sha256=str(record["sha256"]),
            )
            try:
                if len(item.payload) != record["size"]:
                    raise ControlError("binding")
                if name == "recover_vmvm_owner_lifecycle_v4_scratch.py" and item.digest != RECOVERY_HELPER_SHA256:
                    raise ControlError("binding")
            finally:
                item.close()
    except BaseException:
        bound.close()
        raise
    return bound, value


def _namespace_paths() -> tuple[Path, ...]:
    return (
        PREFLIGHT_RECEIPT,
        AUDIT_AUTHORIZATION,
        RECOVERY_AUTHORIZATION,
        AUDIT_RECEIPT,
        RECOVERY_RECEIPT,
        AUDIT_RESERVATION,
        RECOVERY_RESERVATION,
    )


def _require_fresh(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ControlError("freshness") from error
        raise ControlError("freshness")


def _require_log_namespace_fresh() -> None:
    parent_fd, _name = _open_absolute_parent(AUDIT_LOG)
    try:
        prefixes = (
            AUDIT_LOG.name.split("%j", 1)[0],
            RECOVERY_LOG.name.split("%j", 1)[0],
        )
        if any(name.startswith(prefix) for name in os.listdir(parent_fd) for prefix in prefixes):
            raise ControlError("freshness")
    finally:
        os.close(parent_fd)


def _require_private_directory(path: Path, *, mode: int) -> None:
    parent_fd, name = _open_absolute_parent(path)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            opened = os.fstat(fd)
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != mode
                or opened.st_uid != OWNER_UID
                or (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid)
                != (named.st_dev, named.st_ino, named.st_mode, named.st_uid)
            ):
                raise ControlError("binding")
        finally:
            os.close(fd)
    except OSError as error:
        raise ControlError("binding") from error
    finally:
        os.close(parent_fd)


def _require_stage_name_fresh(stage: str) -> None:
    job_name = AUDIT_JOB_NAME if stage == "audit" else RECOVERY_JOB_NAME
    queue = _run((str(SQUEUE), "-M", CLUSTER, "-h", "--name", job_name, "-o", "%A|%j"))
    history = _run(
        (
            str(SACCT),
            "-M",
            CLUSTER,
            "-X",
            "-n",
            "-P",
            "--name",
            job_name,
            "--starttime",
            "1970-01-01",
            "-o",
            "JobIDRaw,JobName,State",
        )
    )
    if (
        queue.returncode != 0
        or queue.stderr
        or queue.stdout.strip()
        or history.returncode != 0
        or history.stderr
        or history.stdout.strip()
    ):
        raise ControlError("freshness")


def _require_scheduler_names_fresh() -> None:
    for stage in sorted(STAGES):
        _require_stage_name_fresh(stage)


def _named_job_ids(stage: str) -> set[str]:
    job_name = AUDIT_JOB_NAME if stage == "audit" else RECOVERY_JOB_NAME
    comment = f"{COMMENT_PREFIX}{stage}"
    found: set[str] = set()
    queue = _run(
        (
            str(SQUEUE),
            "-M",
            CLUSTER,
            "-h",
            "--name",
            job_name,
            "-o",
            "%.20A|%.64j|%.128k|%.64u",
        )
    )
    accounting = _run(
        (
            str(SACCT),
            "-M",
            CLUSTER,
            "-X",
            "-n",
            "-P",
            "--name",
            job_name,
            "--starttime",
            "2026-09-20",
            "-o",
            "JobIDRaw,JobName,Comment,User",
        )
    )
    if queue.returncode != 0 or queue.stderr or accounting.returncode != 0 or accounting.stderr:
        raise ControlError("scheduler")
    for payload in (queue.stdout, accounting.stdout):
        try:
            rows = payload.decode("ascii", "strict").splitlines()
        except UnicodeDecodeError as error:
            raise ControlError("scheduler") from error
        for line in rows:
            if not line:
                continue
            fields = line.split("|")
            if len(fields) != 4:
                raise ControlError("scheduler")
            job_id, observed_name, observed_comment, user = fields
            if (
                observed_name != job_name
                or observed_comment != comment
                or user != OWNER
                or JOB_RE.fullmatch(job_id) is None
            ):
                raise ControlError("scheduler")
            found.add(job_id)
    return found


def static_preflight() -> None:
    manifest, _value = _manifest()
    failure_receipt: BoundFile | None = None
    try:
        for tool in TOOL_HASHES:
            _validate_tool(tool)
        _require_private_directory(BUNDLE, mode=0o555)
        for parent in {path.parent for path in _namespace_paths()} | {AUDIT_LOG.parent, RECOVERY_LOG.parent}:
            _require_private_directory(parent, mode=0o700)
        _require_fresh(_namespace_paths())
        _require_log_namespace_fresh()
        _require_scheduler_names_fresh()
        failure_receipt = open_bound_file(
            FAILED_RECEIPT,
            mode=0o400,
            maximum=MAX_JSON,
            expected_sha256=FAILED_RECEIPT_SHA256,
        )
        old_job_sha = stable_terminal_job(FAILED_JOB_ID, expected=FAILED_JOB_EXPECTED)
        payload = {
            "artifact_type": "vmvm_v4_scratch_recovery_static_preflight_v1",
            "base_commit": BASE_COMMIT,
            "base_tree": BASE_TREE,
            "bundle_manifest_sha256": manifest.digest,
            "candidate_token": TOKEN,
            "failed_job": dict(FAILED_JOB_EXPECTED),
            "failed_job_accounting_sha256": old_job_sha,
            "failed_job_queue_observations": 2,
            "failed_receipt_sha256": FAILED_RECEIPT_SHA256,
            "recovery_helper_sha256": RECOVERY_HELPER_SHA256,
            "recovery_subtree": RECOVERY_SUBTREE,
            "quarantine_root": str(QUARANTINE_ROOT),
            "schema_version": 1,
            "state": "ready",
            "target_node": TARGET_NODE,
            "target_root": str(TARGET_ROOT),
        }
        _commit_publication("preflight", PREFLIGHT_RECEIPT, payload)
    finally:
        if failure_receipt is not None:
            failure_receipt.close()
        manifest.close()


def _load_preflight() -> tuple[BoundFile, dict[str, object]]:
    expected = os.environ.get("EXPECTED_VMVM_V4_PREFLIGHT_SHA256", "")
    if SHA_RE.fullmatch(expected) is None:
        raise ControlError("authorization")
    bound = open_bound_file(PREFLIGHT_RECEIPT, mode=0o400, expected_sha256=expected)
    value = parse_canonical_json(bound, artifact_type="vmvm_v4_scratch_recovery_static_preflight_v1")
    required = {
        "artifact_type",
        "base_commit",
        "base_tree",
        "bundle_manifest_sha256",
        "candidate_token",
        "failed_job",
        "failed_job_accounting_sha256",
        "failed_job_queue_observations",
        "failed_receipt_sha256",
        "recovery_helper_sha256",
        "recovery_subtree",
        "quarantine_root",
        "schema_version",
        "state",
        "target_node",
        "target_root",
    }
    if (
        set(value) != required
        or value.get("base_commit") != BASE_COMMIT
        or value.get("base_tree") != BASE_TREE
        or value.get("candidate_token") != TOKEN
        or value.get("failed_job") != FAILED_JOB_EXPECTED
        or value.get("failed_receipt_sha256") != FAILED_RECEIPT_SHA256
        or value.get("failed_job_queue_observations") != 2
        or value.get("recovery_helper_sha256") != RECOVERY_HELPER_SHA256
        or value.get("recovery_subtree") != RECOVERY_SUBTREE
        or value.get("quarantine_root") != str(QUARANTINE_ROOT)
        or value.get("schema_version") != 1
        or value.get("state") != "ready"
        or value.get("target_node") != TARGET_NODE
        or value.get("target_root") != str(TARGET_ROOT)
        or SHA_RE.fullmatch(str(value.get("bundle_manifest_sha256", ""))) is None
        or SHA_RE.fullmatch(str(value.get("failed_job_accounting_sha256", ""))) is None
    ):
        bound.close()
        raise ControlError("binding")
    return bound, value


def _job_contract(stage: str) -> dict[str, object]:
    return {
        "account": ACCOUNT,
        "cluster": CLUSTER,
        "comment": f"{COMMENT_PREFIX}{stage}",
        "cpus": JOB_CPUS,
        "exclusive": True,
        "job_name": AUDIT_JOB_NAME if stage == "audit" else RECOVERY_JOB_NAME,
        "memory": JOB_MEMORY,
        "node": TARGET_NODE,
        "partition": PARTITION,
        "qos": QOS,
        "requeue": False,
        "time_limit": JOB_TIME_LIMIT,
    }


def _authorization_common(
    stage: str,
    manifest_sha: str,
    preflight_sha: str,
    bundle_files: object,
) -> dict[str, object]:
    return {
        "authorized_stage": stage,
        "backend_sha256": BACKEND_SHA256,
        "base_commit": BASE_COMMIT,
        "base_tree": BASE_TREE,
        "bundle_manifest_sha256": manifest_sha,
        "bundle_files": bundle_files,
        "candidate_token": TOKEN,
        "evaluator_commit": EVALUATOR_COMMIT,
        "evaluator_tree": EVALUATOR_TREE,
        "failed_job": dict(FAILED_JOB_EXPECTED),
        "failed_receipt_sha256": FAILED_RECEIPT_SHA256,
        "job_contract": _job_contract(stage),
        "preflight_receipt_sha256": preflight_sha,
        "recovery_helper_sha256": RECOVERY_HELPER_SHA256,
        "recovery_subtree": RECOVERY_SUBTREE,
        "runtime_gitlinks": {
            "deps/pydantic-config": PYDANTIC_CONFIG_REVISION,
            "deps/renderers": RENDERERS_REVISION,
            "deps/verifiers": VERIFIERS_REVISION,
        },
        "target_node": TARGET_NODE,
        "target_root": str(TARGET_ROOT),
        "quarantine_root": str(QUARANTINE_ROOT),
        "v4_source_commit": V4_SOURCE_COMMIT,
        "v4_source_tree": V4_SOURCE_TREE,
    }


def authorize_audit() -> None:
    manifest, _manifest_value = _manifest()
    preflight, preflight_value = _load_preflight()
    try:
        _require_fresh((AUDIT_AUTHORIZATION, AUDIT_RECEIPT, AUDIT_RESERVATION))
        _require_stage_name_fresh("audit")
        if preflight_value["bundle_manifest_sha256"] != manifest.digest:
            raise ControlError("binding")
        old_job_sha = stable_terminal_job(FAILED_JOB_ID, expected=FAILED_JOB_EXPECTED)
        if old_job_sha != preflight_value["failed_job_accounting_sha256"]:
            raise ControlError("old_job")
        value = {
            **_authorization_common("audit", manifest.digest, preflight.digest, _manifest_value["files"]),
            "artifact_type": "vmvm_v4_scratch_recovery_audit_authorization_v1",
            "receipt_path": str(AUDIT_RECEIPT),
            "root_cardinality": [0, 1],
            "schema_version": 1,
        }
        _commit_publication("authorize-audit", AUDIT_AUTHORIZATION, value)
    finally:
        preflight.close()
        manifest.close()


def _load_authorization(stage: str, *, inherited_fd: int | None = None) -> tuple[BoundFile, dict[str, object]]:
    path = AUDIT_AUTHORIZATION if stage == "audit" else RECOVERY_AUTHORIZATION
    expected = os.environ.get("VMVM_V4_RECOVERY_AUTH_SHA256") if inherited_fd is not None else None
    if inherited_fd is None:
        expected_name = (
            "EXPECTED_VMVM_V4_AUDIT_AUTH_SHA256" if stage == "audit" else "EXPECTED_VMVM_V4_RECOVERY_AUTH_SHA256"
        )
        expected = os.environ.get(expected_name, "")
        if SHA_RE.fullmatch(expected) is None:
            raise ControlError("authorization")
        bound = open_bound_file(path, mode=0o400, expected_sha256=expected)
    else:
        if SHA_RE.fullmatch(expected or "") is None or inherited_fd < 3:
            raise ControlError("authorization")
        fd = os.dup(inherited_fd)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o400
                or info.st_uid != OWNER_UID
                or info.st_nlink != 1
            ):
                raise ControlError("authorization")
            payload = _read_all(fd)
            bound = BoundFile(
                fd,
                payload,
                digest(payload),
                (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size),
            )
            fd = -1
            if bound.digest != expected:
                raise ControlError("authorization")
        finally:
            if fd >= 0:
                os.close(fd)
    artifact = (
        "vmvm_v4_scratch_recovery_audit_authorization_v1"
        if stage == "audit"
        else "vmvm_v4_scratch_recovery_authorization_v1"
    )
    value = parse_canonical_json(bound, artifact_type=artifact)
    bundle_files = value.get("bundle_files")
    if not isinstance(bundle_files, dict):
        bound.close()
        raise ControlError("authorization")
    if (
        SHA_RE.fullmatch(str(value.get("bundle_manifest_sha256", ""))) is None
        or SHA_RE.fullmatch(str(value.get("preflight_receipt_sha256", ""))) is None
    ):
        bound.close()
        raise ControlError("authorization")
    common = _authorization_common(
        stage,
        str(value.get("bundle_manifest_sha256", "")),
        str(value.get("preflight_receipt_sha256", "")),
        bundle_files,
    )
    expected_bundle_modes = {
        "README.md": "0400",
        "control.py": "0500",
        "recover_vmvm_owner_lifecycle_v4_scratch.py": "0500",
        "run_stage.sbatch": "0500",
    }
    if (
        set(bundle_files) != set(expected_bundle_modes)
        or any(
            not isinstance(record, dict)
            or set(record) != {"mode", "sha256", "size"}
            or SHA_RE.fullmatch(str(record.get("sha256", ""))) is None
            or record.get("mode") != expected_bundle_modes[name]
            or type(record.get("size")) is not int
            or int(record["size"]) < 1
            or int(record["size"]) > 2 << 20
            for name, record in bundle_files.items()
        )
        or bundle_files["recover_vmvm_owner_lifecycle_v4_scratch.py"]["sha256"] != RECOVERY_HELPER_SHA256
    ):
        bound.close()
        raise ControlError("authorization")
    if any(value.get(name) != expected_value for name, expected_value in common.items()):
        bound.close()
        raise ControlError("authorization")
    if value.get("schema_version") != 1 or value.get("receipt_path") != str(
        AUDIT_RECEIPT if stage == "audit" else RECOVERY_RECEIPT
    ):
        bound.close()
        raise ControlError("authorization")
    if stage == "audit":
        if set(value) != set(common) | {
            "artifact_type",
            "receipt_path",
            "root_cardinality",
            "schema_version",
        } or value.get("root_cardinality") != [0, 1]:
            bound.close()
            raise ControlError("authorization")
    else:
        if set(value) != set(common) | {
            "artifact_type",
            "audit_public_log_sha256",
            "audit_receipt",
            "audit_receipt_sha256",
            "receipt_path",
            "schema_version",
        }:
            bound.close()
            raise ControlError("authorization")
        audit_receipt = value.get("audit_receipt")
        if (
            not isinstance(audit_receipt, dict)
            or SHA_RE.fullmatch(str(value.get("audit_receipt_sha256", ""))) is None
            or SHA_RE.fullmatch(str(value.get("audit_public_log_sha256", ""))) is None
        ):
            bound.close()
            raise ControlError("authorization")
        if digest(canonical(audit_receipt)) != value["audit_receipt_sha256"]:
            bound.close()
            raise ControlError("authorization")
        try:
            _validate_audit_value(audit_receipt)
        except BaseException:
            bound.close()
            raise
    return bound, value


def _validate_audit_value(value: Mapping[str, object]) -> None:
    required = {
        "artifact_type",
        "audit_authorization_sha256",
        "candidate_token",
        "inventory_sha256",
        "job",
        "quiescence",
        "quarantine",
        "root",
        "schema_version",
        "state",
    }
    root = value.get("root")
    job = value.get("job")
    if (
        set(value) != required
        or value.get("candidate_token") != TOKEN
        or value.get("schema_version") != 1
        or value.get("state") != "audited"
        or value.get("quiescence") != {"observations": 2, "state": "absent"}
        or value.get("quarantine") != {"state": "absent"}
        or not isinstance(job, dict)
        or set(job) != {"cluster", "job_id", "job_name", "node"}
        or job.get("cluster") != CLUSTER
        or JOB_RE.fullmatch(str(job.get("job_id", ""))) is None
        or job.get("job_name") != AUDIT_JOB_NAME
        or job.get("node") != TARGET_NODE
        or not isinstance(root, dict)
        or root.get("state") not in {"absent", "present"}
        or SHA_RE.fullmatch(str(value.get("inventory_sha256", ""))) is None
        or SHA_RE.fullmatch(str(value.get("audit_authorization_sha256", ""))) is None
    ):
        raise ControlError("binding")
    if root["state"] == "absent":
        if set(root) != {"state"} or value["inventory_sha256"] != digest(canonical([])):
            raise ControlError("binding")
    else:
        identity = root.get("identity")
        if (
            set(root) != {"identity", "inventory_class", "state"}
            or root.get("inventory_class")
            not in {"empty", "regular_only", "socket_only", "directory_only", "mixed_supported"}
            or not isinstance(identity, dict)
            or set(identity) != {"device", "inode", "mode", "mount_id", "owner_uid"}
            or any(type(identity.get(name)) is not int for name in identity)
            or identity.get("device", -1) < 0
            or identity.get("inode", 0) <= 0
            or identity.get("mode") != 0o700
            or identity.get("mount_id", 0) <= 0
            or identity.get("owner_uid") != OWNER_UID
        ):
            raise ControlError("binding")


def _load_audit_receipt() -> tuple[BoundFile, dict[str, object]]:
    expected = os.environ.get("EXPECTED_VMVM_V4_AUDIT_RECEIPT_SHA256", "")
    if SHA_RE.fullmatch(expected) is None:
        raise ControlError("authorization")
    bound = open_bound_file(AUDIT_RECEIPT, mode=0o400, expected_sha256=expected)
    value = parse_canonical_json(bound, artifact_type="vmvm_v4_scratch_recovery_audit_receipt_v1")
    try:
        _validate_audit_value(value)
    except BaseException:
        bound.close()
        raise
    return bound, value


def _validate_stage_log(stage: str, job_id: str) -> str:
    path = Path(str(AUDIT_LOG if stage == "audit" else RECOVERY_LOG).replace("%j", job_id))
    bound = open_bound_file(path, mode=0o600, maximum=1024)
    try:
        expected = public_record(f"node-{stage}", "success", "success")
        if bound.payload != expected:
            raise ControlError("binding")
        return bound.digest
    finally:
        bound.close()


def authorize_recovery() -> None:
    manifest, _manifest_value = _manifest()
    preflight, preflight_value = _load_preflight()
    audit_auth, _audit_auth_value = _load_authorization("audit")
    audit_receipt, audit_value = _load_audit_receipt()
    try:
        _require_fresh((RECOVERY_AUTHORIZATION, RECOVERY_RECEIPT, RECOVERY_RESERVATION))
        _require_stage_name_fresh("recover")
        if (
            preflight_value["bundle_manifest_sha256"] != manifest.digest
            or audit_value["audit_authorization_sha256"] != audit_auth.digest
        ):
            raise ControlError("binding")
        job = audit_value["job"]
        assert isinstance(job, dict)
        expected = {
            "ExitCode": "0:0",
            "JobIDRaw": str(job["job_id"]),
            "JobName": AUDIT_JOB_NAME,
            "NodeList": TARGET_NODE,
            "State": "COMPLETED",
            "User": OWNER,
        }
        stable_terminal_job(str(job["job_id"]), expected=expected)
        audit_log_sha = _validate_stage_log("audit", str(job["job_id"]))
        old_job_sha = stable_terminal_job(FAILED_JOB_ID, expected=FAILED_JOB_EXPECTED)
        if old_job_sha != preflight_value["failed_job_accounting_sha256"]:
            raise ControlError("old_job")
        value = {
            **_authorization_common("recover", manifest.digest, preflight.digest, _manifest_value["files"]),
            "artifact_type": "vmvm_v4_scratch_recovery_authorization_v1",
            "audit_public_log_sha256": audit_log_sha,
            "audit_receipt": audit_value,
            "audit_receipt_sha256": audit_receipt.digest,
            "receipt_path": str(RECOVERY_RECEIPT),
            "schema_version": 1,
        }
        _commit_publication("authorize-recover", RECOVERY_AUTHORIZATION, value)
    finally:
        audit_receipt.close()
        audit_auth.close()
        preflight.close()
        manifest.close()


def _parse_scontrol(raw: bytes) -> dict[str, str]:
    try:
        line = raw.decode("ascii", "strict").strip()
        fields = shlex.split(line)
    except (UnicodeDecodeError, ValueError) as error:
        raise ControlError("scheduler") from error
    values: dict[str, str] = {}
    for field in fields:
        if "=" not in field:
            continue
        name, value = field.split("=", 1)
        if not name or name in values:
            raise ControlError("scheduler")
        values[name] = value
    return values


def _held_projection(record: Mapping[str, str], job_id: str, stage: str) -> tuple[str, ...]:
    contract = _job_contract(stage)
    expected = {
        "Account": ACCOUNT,
        "Command": str(BATCH),
        "Comment": str(contract["comment"]),
        "JobId": job_id,
        "JobName": str(contract["job_name"]),
        "JobState": "PENDING",
        "MinMemoryNode": JOB_MEMORY,
        "NumCPUs": JOB_CPUS,
        "NumNodes": "1",
        "Partition": PARTITION,
        "QOS": QOS,
        "Reason": "JobHeldUser",
        "ReqNodeList": TARGET_NODE,
        "Requeue": "0",
        "StdErr": str(AUDIT_LOG if stage == "audit" else RECOVERY_LOG).replace("%j", job_id),
        "StdOut": str(AUDIT_LOG if stage == "audit" else RECOVERY_LOG).replace("%j", job_id),
        "TimeLimit": JOB_TIME_LIMIT,
        "UserId": OWNER_IDENTITY,
        "WorkDir": str(BUNDLE),
    }
    if any(record.get(name) != value for name, value in expected.items()):
        raise ControlError("scheduler")
    if record.get("Dependency") not in {"(null)", ""} or record.get("ExcNodeList") not in {"(null)", ""}:
        raise ControlError("scheduler")
    return tuple(f"{name}={record[name]}" for name in sorted(expected))


def _stable_held(job_id: str, stage: str) -> str:
    last: tuple[tuple[str, ...], bytes] | None = None
    stable = 0
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = _run((str(SCONTROL), "-M", CLUSTER, "show", "job", "-o", job_id))
        if result.returncode == 0 and not result.stderr:
            projection = (_held_projection(_parse_scontrol(result.stdout), job_id, stage), result.stdout)
            stable = stable + 1 if projection == last else 1
            last = projection
            if stable == 2:
                return digest(result.stdout)
        time.sleep(1)
    raise ControlError("scheduler")


def _job_environment(
    stage: str, authorization: BoundFile, manifest: BoundFile, manifest_value: Mapping[str, object]
) -> dict[str, str]:
    files = manifest_value.get("files")
    assert isinstance(files, dict)
    control_record = files["control.py"]
    batch_record = files["run_stage.sbatch"]
    assert isinstance(control_record, dict) and isinstance(batch_record, dict)
    return {
        **STATIC_SAFE_ENV,
        "VMVM_V4_RECOVERY_STAGE": stage,
        "VMVM_V4_RECOVERY_AUTH_PATH": str(AUDIT_AUTHORIZATION if stage == "audit" else RECOVERY_AUTHORIZATION),
        "VMVM_V4_RECOVERY_AUTH_SHA256": authorization.digest,
        "VMVM_V4_RECOVERY_BATCH_SHA256": str(batch_record["sha256"]),
        "VMVM_V4_RECOVERY_CONTROL_PATH": str(CONTROL),
        "VMVM_V4_RECOVERY_CONTROL_SHA256": str(control_record["sha256"]),
        "VMVM_V4_RECOVERY_HELPER_PATH": str(HELPER),
        "VMVM_V4_RECOVERY_HELPER_SHA256": RECOVERY_HELPER_SHA256,
        "VMVM_V4_RECOVERY_MANIFEST_SHA256": manifest.digest,
        "VMVM_V4_RECOVERY_RECEIPT_PATH": str(AUDIT_RECEIPT if stage == "audit" else RECOVERY_RECEIPT),
    }


def _write_export(values: Mapping[str, str]) -> tuple[Path, int, int]:
    if any(not name or "=" in name or "\0" in name or "\0" in value for name, value in values.items()):
        raise ControlError("binding")
    directory = Path(tempfile.mkdtemp(prefix=f"vmvm-v4-{TOKEN}-", dir="/dev/shm"))
    path = directory / "environment.nul"
    raw = b"".join(f"{name}={values[name]}".encode("ascii") + b"\0" for name in sorted(values))
    directory_fd = -1
    fd = -1
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        directory_info = os.fstat(directory_fd)
        named_directory = os.stat(directory, follow_symlinks=False)
        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or stat.S_IMODE(directory_info.st_mode) != 0o700
            or directory_info.st_uid != OWNER_UID
            or (directory_info.st_dev, directory_info.st_ino) != (named_directory.st_dev, named_directory.st_ino)
        ):
            raise ControlError("binding")
        fd = os.open(
            path.name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=directory_fd,
        )
        _write_all(fd, raw)
        os.fsync(fd)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        raise
    return path, directory_fd, fd


def _scrub_export(path: Path, directory_fd: int, file_fd: int) -> None:
    try:
        opened = os.fstat(file_fd)
        named = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o400
            or opened.st_uid != OWNER_UID
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise ControlError("binding")
        size = opened.st_size
        os.lseek(file_fd, 0, os.SEEK_SET)
        if size:
            _write_all(file_fd, b"\0" * size)
        os.ftruncate(file_fd, 0)
        os.fsync(file_fd)
        scrubbed = os.fstat(file_fd)
        named_after = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            scrubbed.st_dev,
            scrubbed.st_ino,
            scrubbed.st_mode,
            scrubbed.st_uid,
            scrubbed.st_nlink,
            scrubbed.st_size,
        ) != (
            named_after.st_dev,
            named_after.st_ino,
            named_after.st_mode,
            named_after.st_uid,
            named_after.st_nlink,
            named_after.st_size,
        ) or scrubbed.st_size != 0:
            raise ControlError("binding")
        os.fsync(directory_fd)
    finally:
        os.close(file_fd)
        os.close(directory_fd)


def sbatch_command(stage: str, export_path: Path) -> list[str]:
    log = AUDIT_LOG if stage == "audit" else RECOVERY_LOG
    contract = _job_contract(stage)
    return [
        str(SBATCH),
        "-M",
        CLUSTER,
        "--parsable",
        "--hold",
        f"--job-name={contract['job_name']}",
        f"--comment={contract['comment']}",
        f"--chdir={BUNDLE}",
        f"--partition={PARTITION}",
        f"--account={ACCOUNT}",
        f"--qos={QOS}",
        f"--nodelist={TARGET_NODE}",
        "--nodes=1",
        "--ntasks=1",
        f"--cpus-per-task={JOB_CPUS}",
        f"--mem={JOB_MEMORY}",
        f"--time={JOB_TIME_LIMIT}",
        "--exclusive",
        "--no-requeue",
        "--signal=B:TERM@120",
        f"--output={log}",
        f"--error={log}",
        "--open-mode=truncate",
        f"--export-file={export_path}",
        str(BATCH),
    ]


def _group_exists(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_submit(process: subprocess.Popen[bytes]) -> None:
    if _group_exists(process.pid):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 2
        while _group_exists(process.pid) and time.monotonic() < deadline:
            if process.poll() is None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=min(0.1, deadline - time.monotonic()))
            else:
                time.sleep(min(0.1, deadline - time.monotonic()))
        if _group_exists(process.pid):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise ControlError("scheduler") from error
    deadline = time.monotonic() + 5
    while _group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(min(0.1, deadline - time.monotonic()))
    if process.poll() is None or _group_exists(process.pid):
        raise ControlError("scheduler")


def _bounded_submit(command: Sequence[str]) -> SubmitAttempt:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=STATIC_SAFE_ENV,
        )
        if os.getpgid(process.pid) != process.pid:
            raise ControlError("scheduler")
        stdout, stderr = process.communicate(timeout=30)
        if len(stdout) > 4096 or len(stderr) > 4096 or _group_exists(process.pid):
            raise ControlError("scheduler")
        return SubmitAttempt(stdout, stderr, process.returncode, "completed")
    except subprocess.TimeoutExpired:
        if process is not None:
            _stop_submit(process)
        return SubmitAttempt(b"", b"", None, "timeout")
    except BaseException:
        if process is not None:
            _stop_submit(process)
        raise


def _recover_submission(stage: str, direct: str | None) -> str:
    deadline = time.monotonic() + 60
    last_error: ControlError | None = None
    while time.monotonic() < deadline:
        try:
            candidates = _named_job_ids(stage)
            if direct is not None:
                candidates.add(direct)
            if len(candidates) > 1:
                raise ControlError("scheduler")
            if len(candidates) == 1:
                return next(iter(candidates))
            last_error = None
        except ControlError as error:
            last_error = error
        time.sleep(1)
    if last_error is not None:
        raise last_error
    raise ControlError("scheduler")


def _cancel(job_id: str) -> None:
    with contextlib.suppress(BaseException):
        _run((str(SCANCEL), "-M", CLUSTER, job_id))


def _cancel_named(stage: str) -> None:
    with contextlib.suppress(BaseException):
        for candidate in _named_job_ids(stage):
            _cancel(candidate)


def _create_reservation(path: Path) -> tuple[int, int, str]:
    parent_fd, name = _open_absolute_parent(path)
    try:
        parent_info = os.fstat(parent_fd)
        if stat.S_IMODE(parent_info.st_mode) != 0o700 or parent_info.st_uid != OWNER_UID:
            raise ControlError("binding")
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return parent_fd, fd, name
    except BaseException:
        os.close(parent_fd)
        raise


def _seal_reservation(parent_fd: int, fd: int, name: str, payload: bytes) -> None:
    _write_all(fd, payload)
    os.fsync(fd)
    os.fchmod(fd, 0o400)
    opened = os.fstat(fd)
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o400
        or opened.st_uid != OWNER_UID
        or opened.st_nlink != 1
        or (opened.st_dev, opened.st_ino, opened.st_size) != (named.st_dev, named.st_ino, named.st_size)
    ):
        raise ControlError("publication")
    os.lseek(fd, 0, os.SEEK_SET)
    if os.read(fd, len(payload) + 1) != payload:
        raise ControlError("publication")
    os.fsync(parent_fd)


def launch(stage: str) -> None:
    manifest, manifest_value = _manifest()
    preflight, preflight_value = _load_preflight()
    authorization, authorization_value = _load_authorization(stage)
    job_id: str | None = None
    reservation = AUDIT_RESERVATION if stage == "audit" else RECOVERY_RESERVATION
    reservation_fd = -1
    reservation_parent_fd = -1
    export_path: Path | None = None
    export_parent_fd = -1
    export_file_fd = -1
    submission_attempted = False
    try:
        if (
            authorization_value["bundle_manifest_sha256"] != manifest.digest
            or authorization_value["bundle_files"] != manifest_value["files"]
            or authorization_value["preflight_receipt_sha256"] != preflight.digest
            or preflight_value["bundle_manifest_sha256"] != manifest.digest
        ):
            raise ControlError("binding")
        for parent in {
            reservation.parent,
            (AUDIT_LOG if stage == "audit" else RECOVERY_LOG).parent,
            (AUDIT_RECEIPT if stage == "audit" else RECOVERY_RECEIPT).parent,
        }:
            _require_private_directory(parent, mode=0o700)
        _require_fresh((reservation, AUDIT_RECEIPT if stage == "audit" else RECOVERY_RECEIPT))
        _require_stage_name_fresh(stage)
        old_job_sha = stable_terminal_job(FAILED_JOB_ID, expected=FAILED_JOB_EXPECTED)
        if old_job_sha != preflight_value["failed_job_accounting_sha256"]:
            raise ControlError("old_job")
        if stage == "recover":
            audit_receipt, audit_value = _load_audit_receipt()
            try:
                if (
                    authorization_value["audit_receipt_sha256"] != audit_receipt.digest
                    or authorization_value["audit_receipt"] != audit_value
                ):
                    raise ControlError("binding")
                audit_job = audit_value["job"]
                assert isinstance(audit_job, dict)
                stable_terminal_job(
                    str(audit_job["job_id"]),
                    expected={
                        "ExitCode": "0:0",
                        "JobIDRaw": str(audit_job["job_id"]),
                        "JobName": AUDIT_JOB_NAME,
                        "NodeList": TARGET_NODE,
                        "State": "COMPLETED",
                        "User": OWNER,
                    },
                )
                if authorization_value["audit_public_log_sha256"] != _validate_stage_log(
                    "audit", str(audit_job["job_id"])
                ):
                    raise ControlError("binding")
            finally:
                audit_receipt.close()
        reservation_parent_fd, reservation_fd, reservation_name = _create_reservation(reservation)
        export_path, export_parent_fd, export_file_fd = _write_export(
            _job_environment(stage, authorization, manifest, manifest_value)
        )
        submission_attempted = True
        attempt = _bounded_submit(sbatch_command(stage, export_path))
        candidate: str | None = None
        if attempt.stdout:
            try:
                parsed = attempt.stdout.decode("ascii", "strict").strip().split(";", 1)[0]
            except UnicodeDecodeError:
                parsed = ""
            if JOB_RE.fullmatch(parsed) is not None:
                candidate = parsed
        job_id = _recover_submission(stage, candidate)
        if attempt.outcome != "completed" or attempt.returncode != 0 or attempt.stderr or candidate != job_id:
            raise ControlError("scheduler")
        held_identity_sha256 = _stable_held(job_id, stage)
        reservation_payload = canonical(
            {
                "artifact_type": "vmvm_v4_scratch_recovery_reservation_v1",
                "authorization_sha256": authorization.digest,
                "candidate_token": TOKEN,
                "held_identity_observations": 2,
                "held_identity_sha256": held_identity_sha256,
                "job_id": job_id,
                "stage": stage,
            }
        )
        _seal_reservation(reservation_parent_fd, reservation_fd, reservation_name, reservation_payload)
        _scrub_export(export_path, export_parent_fd, export_file_fd)
        export_path = None
        export_parent_fd = -1
        export_file_fd = -1
        signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        release = _run((str(SCONTROL), "-M", CLUSTER, "release", job_id))
        if release.returncode != 0 or release.stdout or release.stderr:
            raise ControlError("scheduler")
        global _COMMITTED_ACTION
        _COMMITTED_ACTION = f"launch-{stage}"
    except BaseException:
        if job_id is not None:
            _cancel(job_id)
        elif submission_attempted:
            _cancel_named(stage)
        raise
    finally:
        if export_path is not None and export_parent_fd >= 0 and export_file_fd >= 0:
            with contextlib.suppress(BaseException):
                _scrub_export(export_path, export_parent_fd, export_file_fd)
            export_parent_fd = -1
            export_file_fd = -1
        if reservation_fd >= 0:
            os.close(reservation_fd)
        if reservation_parent_fd >= 0:
            os.close(reservation_parent_fd)
        authorization.close()
        preflight.close()
        manifest.close()


def _validate_node_environment(stage: str) -> None:
    required = {
        "VMVM_V4_RECOVERY_STAGE",
        "VMVM_V4_RECOVERY_AUTH_FD",
        "VMVM_V4_RECOVERY_AUTH_SHA256",
        "VMVM_V4_RECOVERY_CONTROL_SHA256",
        "VMVM_V4_RECOVERY_HELPER_FD",
        "VMVM_V4_RECOVERY_HELPER_SHA256",
        "VMVM_V4_RECOVERY_MANIFEST_SHA256",
        "VMVM_V4_RECOVERY_RECEIPT_PATH",
    }
    if any(name not in os.environ or not os.environ[name] for name in required):
        raise ControlError("authorization")
    if os.environ["VMVM_V4_RECOVERY_STAGE"] != stage:
        raise ControlError("authorization")
    if any(name in FORBIDDEN_ENV_NAMES or name.startswith(FORBIDDEN_ENV_PREFIXES) for name in os.environ):
        raise ControlError("authorization")
    if (
        os.environ.get("SLURM_CLUSTER_NAME") != CLUSTER
        or os.environ.get("SLURMD_NODENAME") != TARGET_NODE
        or os.environ.get("SLURM_JOB_NAME") != (AUDIT_JOB_NAME if stage == "audit" else RECOVERY_JOB_NAME)
        or JOB_RE.fullmatch(os.environ.get("SLURM_JOB_ID", "")) is None
    ):
        raise ControlError("host")
    cwd = Path.cwd()
    process_root = Path("/proc/self/root").resolve()
    if (
        cwd == TARGET_ROOT
        or TARGET_ROOT in cwd.parents
        or process_root == TARGET_ROOT
        or TARGET_ROOT in process_root.parents
    ):
        raise ControlError("host")


def _fd_from_env(name: str, *, mode: int, expected_sha: str) -> BoundFile:
    value = os.environ.get(name, "")
    if not value.isdecimal() or int(value) < 3 or SHA_RE.fullmatch(expected_sha) is None:
        raise ControlError("binding")
    fd = os.dup(int(value))
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_uid != OWNER_UID
            or info.st_nlink != 1
        ):
            raise ControlError("binding")
        payload = _read_all(fd, 2 << 20)
        if digest(payload) != expected_sha:
            raise ControlError("binding")
        bound = BoundFile(
            fd,
            payload,
            expected_sha,
            (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size),
        )
        fd = -1
        return bound
    finally:
        if fd >= 0:
            os.close(fd)


def _validate_control_self() -> BoundFile:
    expected = os.environ.get("VMVM_V4_RECOVERY_CONTROL_SHA256", "")
    match = FD_RE.fullmatch(str(Path(__file__)))
    if match is None or SHA_RE.fullmatch(expected) is None:
        raise ControlError("binding")
    source_fd = int(match.group(1))
    fd = os.dup(source_fd)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o500
            or info.st_uid != OWNER_UID
            or info.st_nlink != 1
        ):
            raise ControlError("binding")
        payload = _read_all(fd, 2 << 20)
        if digest(payload) != expected:
            raise ControlError("binding")
        return BoundFile(
            fd,
            payload,
            expected,
            (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size),
        )
    except BaseException:
        os.close(fd)
        raise


def _load_helper(bound: BoundFile) -> types.ModuleType:
    module_name = f"_vmvm_v4_recovery_{TOKEN}"
    module = types.ModuleType(module_name)
    module.__file__ = f"/proc/self/fd/{bound.fd}"
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(compile(bound.payload, module.__file__, "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _inventory_commitment(inventory: object) -> str:
    entries = getattr(inventory, "entries")
    values = []
    for relative, entry in sorted(entries.items()):
        values.append(
            {
                "identity": list(entry.identity),
                "kind": entry.kind,
                "relative": relative,
            }
        )
    return digest(canonical(values))


def _same_uid_path_reference(path: Path) -> bool:
    target = os.fsencode(path)
    for entry in os.scandir("/proc"):
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        process = Path("/proc") / entry.name
        try:
            if process.stat().st_uid != OWNER_UID:
                continue
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as error:
            raise ControlError("quiescence") from error
        try:
            if target in (process / "cmdline").read_bytes()[: 1 << 20]:
                return True
            for link in ("cwd", "root"):
                try:
                    value = os.fsencode(os.readlink(process / link))
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if value == target or value.startswith(target + b"/") or value.startswith(target + b" (deleted)"):
                    return True
            directory_fd = os.open(process / "fd", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                for name in os.listdir(directory_fd):
                    try:
                        value = os.fsencode(os.readlink(name, dir_fd=directory_fd))
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    if value == target or value.startswith(target + b"/") or value.startswith(target + b" (deleted)"):
                        return True
            finally:
                os.close(directory_fd)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as error:
            raise ControlError("quiescence") from error
    return False


def _same_uid_target_reference() -> bool:
    return _same_uid_path_reference(TARGET_ROOT)


def _same_uid_quarantine_reference() -> bool:
    return _same_uid_path_reference(QUARANTINE_ROOT)


def _target_parent_changed(helper: types.ModuleType, watch_fd: int) -> bool:
    watched_names = {os.fsencode(TARGET_ROOT.name), os.fsencode(QUARANTINE_ROOT.name)}
    for mask, _cookie, name in helper._read_events(watch_fd):
        if mask & helper._IN_Q_OVERFLOW or name in watched_names:
            return True
    return False


def _root_observation(
    helper: types.ModuleType,
    *,
    prove_quiescence: bool,
    authorized_quarantine: tuple[Mapping[str, object], str] | None = None,
) -> tuple[dict[str, object], str, object | None, int, int, int, int]:
    parent_fd = helper._open_absolute_directory(TARGET_ROOT.parent)
    parent_watch_fd = -1
    root_watch_fd = -1
    root_fd = -1
    inventory = None
    try:
        parent_watch_fd = helper._open_watch(parent_fd)
        try:
            os.stat(QUARANTINE_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            quarantined = False
        else:
            quarantined = True
        if quarantined and authorized_quarantine is None:
            raise ControlError("freshness")
        selected_name = QUARANTINE_ROOT.name if quarantined else TARGET_ROOT.name
        if quarantined:
            try:
                os.stat(TARGET_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ControlError("root_state")
        try:
            root_fd = os.open(
                selected_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            if quarantined:
                raise ControlError("root_state") from None
            if prove_quiescence and (_same_uid_target_reference() or _same_uid_quarantine_reference()):
                raise ControlError("quiescence")
            time.sleep(SETTLE_SECONDS if prove_quiescence else 0)
            try:
                os.stat(TARGET_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                if _target_parent_changed(helper, parent_watch_fd):
                    raise ControlError("root_state")
                if prove_quiescence and (_same_uid_target_reference() or _same_uid_quarantine_reference()):
                    raise ControlError("quiescence")
                result = (
                    {"state": "absent"},
                    digest(canonical([])),
                    None,
                    parent_fd,
                    -1,
                    parent_watch_fd,
                    -1,
                )
                parent_watch_fd = -1
                return result
            raise ControlError("root_state")
        except OSError as error:
            raise ControlError("root_state") from error
        known_mounts = helper._known_mount_ids()
        identity = helper.descriptor_identity(root_fd, known_mounts)
        if identity["mode"] != 0o700 or identity["owner_uid"] != OWNER_UID:
            raise ControlError("root_state")
        if helper._directory_identity_at(parent_fd, selected_name, known_mounts) != identity:
            raise ControlError("root_state")
        inventory_class, sockets, inventory = helper._inventory(root_fd)
        root_watch_fd = helper._open_watch(root_fd)
        commitment = _inventory_commitment(inventory)
        if quarantined:
            assert authorized_quarantine is not None
            expected_root, expected_inventory_sha = authorized_quarantine
            expected_identity = expected_root.get("identity")
            if (
                expected_root.get("state") != "present"
                or not isinstance(expected_identity, dict)
                or identity != expected_identity
                or inventory_class != expected_root.get("inventory_class")
                or commitment != expected_inventory_sha
            ):
                raise ControlError("root_state")
        if prove_quiescence:
            identities = inventory.identities | {(identity["device"], identity["inode"])}
            if helper._same_uid_process_references(sockets, identities):
                raise ControlError("quiescence")
            time.sleep(SETTLE_SECONDS)
            if helper._same_uid_process_references(sockets, identities):
                raise ControlError("quiescence")
            second_class, _second_sockets, second = helper._inventory(root_fd)
            try:
                if second_class != inventory_class or _inventory_commitment(second) != commitment:
                    raise ControlError("root_state")
            finally:
                second.close()
            if helper._directory_identity_at(parent_fd, selected_name, known_mounts) != identity:
                raise ControlError("root_state")
            if helper._read_events(root_watch_fd) or _target_parent_changed(helper, parent_watch_fd):
                raise ControlError("root_state")
            other_name = TARGET_ROOT.name if quarantined else QUARANTINE_ROOT.name
            try:
                os.stat(other_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ControlError("root_state")
        result = (
            {
                "identity": identity,
                "inventory_class": inventory_class,
                "state": "quarantined" if quarantined else "present",
            },
            commitment,
            inventory,
            parent_fd,
            root_fd,
            parent_watch_fd,
            root_watch_fd,
        )
        parent_watch_fd = -1
        root_watch_fd = -1
        return result
    except BaseException:
        if inventory is not None:
            inventory.close()
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)
        raise
    finally:
        if root_watch_fd >= 0:
            os.close(root_watch_fd)
        if parent_watch_fd >= 0:
            os.close(parent_watch_fd)


def _close_observation(
    inventory: object | None,
    parent_fd: int,
    root_fd: int,
    parent_watch_fd: int = -1,
    root_watch_fd: int = -1,
) -> None:
    if inventory is not None:
        inventory.close()
    for descriptor in (root_watch_fd, parent_watch_fd):
        if descriptor >= 0:
            os.close(descriptor)
    if root_fd >= 0:
        os.close(root_fd)
    os.close(parent_fd)


def _watchers_clean(helper: types.ModuleType, parent_watch_fd: int, root_watch_fd: int) -> None:
    if root_watch_fd >= 0 and helper._read_events(root_watch_fd):
        raise ControlError("root_state")
    if _target_parent_changed(helper, parent_watch_fd):
        raise ControlError("root_state")


def _revalidate_observation(
    helper: types.ModuleType,
    root: Mapping[str, object],
    inventory_sha: str,
    inventory: object | None,
    parent_fd: int,
    root_fd: int,
    parent_watch_fd: int,
    root_watch_fd: int,
) -> None:
    if root["state"] == "absent":
        try:
            os.stat(TARGET_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ControlError("root_state")
        try:
            os.stat(QUARANTINE_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ControlError("freshness")
        if _same_uid_target_reference() or _same_uid_quarantine_reference():
            raise ControlError("quiescence")
        _watchers_clean(helper, parent_watch_fd, root_watch_fd)
        return
    if inventory is None or root_fd < 0 or root_watch_fd < 0:
        raise ControlError("root_state")
    identity = root.get("identity")
    if not isinstance(identity, dict):
        raise ControlError("root_state")
    known_mounts = helper._known_mount_ids()
    if (
        helper.descriptor_identity(root_fd, known_mounts) != identity
        or helper._directory_identity_at(parent_fd, TARGET_ROOT.name, known_mounts) != identity
    ):
        raise ControlError("root_state")
    try:
        os.stat(QUARANTINE_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise ControlError("freshness")
    second_class, sockets, second = helper._inventory(root_fd)
    try:
        if second_class != root["inventory_class"] or _inventory_commitment(second) != inventory_sha:
            raise ControlError("root_state")
        identities = second.identities | {(int(identity["device"]), int(identity["inode"]))}
        if helper._same_uid_process_references(sockets, identities):
            raise ControlError("quiescence")
    finally:
        second.close()
    _watchers_clean(helper, parent_watch_fd, root_watch_fd)


def _revalidate_quarantined_root(
    helper: types.ModuleType,
    identity: Mapping[str, object],
    inventory_class: object,
    inventory_sha: str,
    parent_fd: int,
    root_fd: int,
    parent_watch_fd: int,
    root_watch_fd: int,
    *,
    expect_move: bool = True,
) -> None:
    known_mounts = helper._known_mount_ids()
    try:
        os.stat(TARGET_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise ControlError("root_state")
    if (
        helper.descriptor_identity(root_fd, known_mounts) != identity
        or helper._directory_identity_at(parent_fd, QUARANTINE_ROOT.name, known_mounts) != identity
    ):
        raise ControlError("root_state")
    second_class, sockets, second = helper._inventory(root_fd)
    try:
        if second_class != inventory_class or _inventory_commitment(second) != inventory_sha:
            raise ControlError("root_state")
        identities = second.identities | {(int(identity["device"]), int(identity["inode"]))}
        if helper._same_uid_process_references(sockets, identities):
            raise ControlError("quiescence")
    finally:
        second.close()
    if _same_uid_target_reference() or _same_uid_quarantine_reference():
        raise ControlError("quiescence")
    if expect_move:
        parent_events = helper._read_events(parent_watch_fd)
        if not helper._expected_move(parent_events, TARGET_ROOT.name, QUARANTINE_ROOT.name):
            raise ControlError("root_state")
        if helper._read_events(root_watch_fd) != [(helper._IN_MOVE_SELF, 0, b"")]:
            raise ControlError("root_state")
    else:
        _watchers_clean(helper, parent_watch_fd, root_watch_fd)


def _enter_terminal_boundary() -> None:
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    if signal.sigpending() & HANDLED_SIGNALS:
        raise Interrupted()


def _quarantined_root_matches_audit(root: Mapping[str, object], audit_root: Mapping[str, object]) -> bool:
    return audit_root.get("state") == "present" and root == {
        "identity": audit_root.get("identity"),
        "inventory_class": audit_root.get("inventory_class"),
        "state": "quarantined",
    }


def _recovery_receipt_value(
    authorization: BoundFile,
    authorization_value: Mapping[str, object],
    audit_root: Mapping[str, object],
    identity: Mapping[str, object],
) -> dict[str, object]:
    return {
        "artifact_type": "vmvm_v4_scratch_recovery_receipt_v1",
        "audit_receipt_sha256": str(authorization_value["audit_receipt_sha256"]),
        "candidate_token": TOKEN,
        "job": {
            "cluster": CLUSTER,
            "job_id": os.environ["SLURM_JOB_ID"],
            "job_name": RECOVERY_JOB_NAME,
            "node": TARGET_NODE,
        },
        "recovery_authorization_sha256": authorization.digest,
        "root_after": {"identity": dict(identity), "state": "quarantined"},
        "root_before": dict(audit_root),
        "schema_version": 1,
        "state": "quarantined",
    }


def _finalize_quarantined_recovery(
    helper: types.ModuleType,
    authorization: BoundFile,
    authorization_value: Mapping[str, object],
    audit_root: Mapping[str, object],
    root: Mapping[str, object],
    inventory_sha: str,
    parent_fd: int,
    root_fd: int,
    parent_watch_fd: int,
    root_watch_fd: int,
    *,
    expect_move: bool,
) -> None:
    if not _quarantined_root_matches_audit(root, audit_root):
        raise ControlError("root_state")
    identity = root["identity"]
    assert isinstance(identity, dict)
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    time.sleep(SETTLE_SECONDS)
    _revalidate_quarantined_root(
        helper,
        identity,
        root["inventory_class"],
        inventory_sha,
        parent_fd,
        root_fd,
        parent_watch_fd,
        root_watch_fd,
        expect_move=expect_move,
    )
    value = _recovery_receipt_value(authorization, authorization_value, audit_root, identity)
    _commit_publication("node-recover", RECOVERY_RECEIPT, value, irreversible=True)


def _resume_quarantined_recovery(
    helper: types.ModuleType,
    authorization: BoundFile,
    authorization_value: Mapping[str, object],
    audit_root: Mapping[str, object],
    inventory_sha: str,
) -> None:
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    observation = _root_observation(
        helper,
        prove_quiescence=True,
        authorized_quarantine=(audit_root, inventory_sha),
    )
    root, observed_sha, inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd = observation
    try:
        if observed_sha != inventory_sha:
            raise ControlError("root_state")
        _finalize_quarantined_recovery(
            helper,
            authorization,
            authorization_value,
            audit_root,
            root,
            observed_sha,
            parent_fd,
            root_fd,
            parent_watch_fd,
            root_watch_fd,
            expect_move=False,
        )
    finally:
        _close_observation(inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd)


def node_stage(stage: str) -> None:
    _validate_node_environment(stage)
    self_expected = os.environ["VMVM_V4_RECOVERY_CONTROL_SHA256"]
    self_match = FD_RE.fullmatch(str(Path(__file__)))
    if self_match is None:
        raise ControlError("binding")
    self_bound = _fd_from_env("VMVM_V4_RECOVERY_CONTROL_FD", mode=0o500, expected_sha=self_expected)
    helper_bound = _fd_from_env(
        "VMVM_V4_RECOVERY_HELPER_FD",
        mode=0o500,
        expected_sha=os.environ["VMVM_V4_RECOVERY_HELPER_SHA256"],
    )
    auth_fd_value = os.environ["VMVM_V4_RECOVERY_AUTH_FD"]
    if not auth_fd_value.isdecimal():
        raise ControlError("authorization")
    authorization, authorization_value = _load_authorization(stage, inherited_fd=int(auth_fd_value))
    helper = _load_helper(helper_bound)
    inventory = None
    parent_fd = -1
    root_fd = -1
    parent_watch_fd = -1
    root_watch_fd = -1
    audit_root: Mapping[str, object] | None = None
    audit_inventory_sha: str | None = None
    try:
        if int(self_match.group(1)) != int(os.environ["VMVM_V4_RECOVERY_CONTROL_FD"]):
            raise ControlError("binding")
        if authorization_value["recovery_helper_sha256"] != helper_bound.digest:
            raise ControlError("binding")
        if authorization_value["bundle_manifest_sha256"] != os.environ["VMVM_V4_RECOVERY_MANIFEST_SHA256"]:
            raise ControlError("binding")
        bundle_files = authorization_value["bundle_files"]
        assert isinstance(bundle_files, dict)
        control_record = bundle_files["control.py"]
        helper_record = bundle_files["recover_vmvm_owner_lifecycle_v4_scratch.py"]
        assert isinstance(control_record, dict) and isinstance(helper_record, dict)
        if control_record["sha256"] != self_bound.digest or helper_record["sha256"] != helper_bound.digest:
            raise ControlError("binding")
        receipt_path = Path(os.environ["VMVM_V4_RECOVERY_RECEIPT_PATH"])
        if receipt_path != (AUDIT_RECEIPT if stage == "audit" else RECOVERY_RECEIPT):
            raise ControlError("authorization")
        authorized_quarantine = None
        if stage == "recover":
            audit = authorization_value["audit_receipt"]
            assert isinstance(audit, dict)
            candidate_root = audit["root"]
            candidate_inventory_sha = audit["inventory_sha256"]
            assert isinstance(candidate_root, dict) and isinstance(candidate_inventory_sha, str)
            audit_root = candidate_root
            audit_inventory_sha = candidate_inventory_sha
            if audit_root["state"] == "present":
                authorized_quarantine = (audit_root, audit_inventory_sha)
        (
            root,
            inventory_sha,
            inventory,
            parent_fd,
            root_fd,
            parent_watch_fd,
            root_watch_fd,
        ) = _root_observation(
            helper,
            prove_quiescence=True,
            authorized_quarantine=authorized_quarantine,
        )
        if stage == "audit":
            value = {
                "artifact_type": "vmvm_v4_scratch_recovery_audit_receipt_v1",
                "audit_authorization_sha256": authorization.digest,
                "candidate_token": TOKEN,
                "inventory_sha256": inventory_sha,
                "job": {
                    "cluster": CLUSTER,
                    "job_id": os.environ["SLURM_JOB_ID"],
                    "job_name": AUDIT_JOB_NAME,
                    "node": TARGET_NODE,
                },
                "quiescence": {"observations": 2, "state": "absent"},
                "quarantine": {"state": "absent"},
                "root": root,
                "schema_version": 1,
                "state": "audited",
            }
            _enter_terminal_boundary()
            _revalidate_observation(
                helper,
                root,
                inventory_sha,
                inventory,
                parent_fd,
                root_fd,
                parent_watch_fd,
                root_watch_fd,
            )
            _commit_publication("node-audit", AUDIT_RECEIPT, value)
            return
        assert audit_root is not None and audit_inventory_sha is not None
        if inventory_sha != audit_inventory_sha:
            raise ControlError("root_state")
        if root["state"] == "present":
            if root != audit_root:
                raise ControlError("root_state")
            assert inventory is not None and root_fd >= 0 and parent_fd >= 0
            identity = root["identity"]
            assert isinstance(identity, dict)
            _enter_terminal_boundary()
            _revalidate_observation(
                helper,
                root,
                inventory_sha,
                inventory,
                parent_fd,
                root_fd,
                parent_watch_fd,
                root_watch_fd,
            )
            sockets = tuple(relative for relative, entry in inventory.entries.items() if entry.kind == "socket")
            identities = inventory.identities | {(int(identity["device"]), int(identity["inode"]))}
            if not helper._quiesce(root_fd, sockets, identities, inventory):
                raise ControlError("quiescence")
            _enter_terminal_boundary()
            helper._quarantine_root_verified(parent_fd, root_fd, identity)
            quarantined = {
                "identity": root["identity"],
                "inventory_class": root["inventory_class"],
                "state": "quarantined",
            }
            _finalize_quarantined_recovery(
                helper,
                authorization,
                authorization_value,
                audit_root,
                quarantined,
                inventory_sha,
                parent_fd,
                root_fd,
                parent_watch_fd,
                root_watch_fd,
                expect_move=True,
            )
            return
        if root["state"] == "quarantined":
            _finalize_quarantined_recovery(
                helper,
                authorization,
                authorization_value,
                audit_root,
                root,
                inventory_sha,
                parent_fd,
                root_fd,
                parent_watch_fd,
                root_watch_fd,
                expect_move=False,
            )
            return
        if root != audit_root:
            raise ControlError("root_state")
        if root["state"] == "absent":
            time.sleep(SETTLE_SECONDS)
            _enter_terminal_boundary()
            _revalidate_observation(
                helper,
                root,
                inventory_sha,
                inventory,
                parent_fd,
                root_fd,
                parent_watch_fd,
                root_watch_fd,
            )
            value = {
                "artifact_type": "vmvm_v4_scratch_recovery_receipt_v1",
                "audit_receipt_sha256": str(authorization_value["audit_receipt_sha256"]),
                "candidate_token": TOKEN,
                "job": {
                    "cluster": CLUSTER,
                    "job_id": os.environ["SLURM_JOB_ID"],
                    "job_name": RECOVERY_JOB_NAME,
                    "node": TARGET_NODE,
                },
                "recovery_authorization_sha256": authorization.digest,
                "root_after": {"state": "absent"},
                "root_before": dict(audit_root),
                "schema_version": 1,
                "state": "already_absent",
            }
            _commit_publication("node-recover", RECOVERY_RECEIPT, value)
            return
        raise ControlError("root_state")
    except BaseException as error:
        if stage == "recover" and audit_root is not None and audit_inventory_sha is not None:
            try:
                _resume_quarantined_recovery(
                    helper,
                    authorization,
                    authorization_value,
                    audit_root,
                    audit_inventory_sha,
                )
            except BaseException:
                pass
            else:
                return
        if isinstance(error, helper.RecoveryError):
            category = {
                "retained_inventory_unsupported": "inventory",
                "retained_owner_present": "quiescence",
                "retained_quiescence_unverified": "quiescence",
                "retained_root_binding_invalid": "root_state",
            }.get(error.state, "internal")
            raise ControlError(category) from error
        raise
    finally:
        if parent_fd >= 0:
            _close_observation(inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd)
        authorization.close()
        helper_bound.close()
        self_bound.close()


def public_record(action: str, state: str, category: str) -> bytes:
    if action not in PUBLIC_KINDS or state not in {"success", "failed"} or category not in PUBLIC_CATEGORIES:
        action = "preflight"
        state = "failed"
        category = "internal"
    stage = "audit" if "audit" in action else "recover" if "recover" in action else "none"
    return canonical(
        {
            "action": action,
            "artifact_type": PUBLIC_KINDS[action],
            "category": category,
            "stage": stage,
            "state": state,
        }
    )


def _terminal(action: str, state: str, category: str) -> NoReturn:
    payload = public_record(action, state, category)
    if len(payload) > 384:
        payload = public_record("preflight", "failed", "internal")
    with contextlib.suppress(OSError):
        _write_all(1, payload)
    raise SystemExit(0 if state == "success" else 2)


def main() -> NoReturn:
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action not in PUBLIC_KINDS:
        _terminal("preflight", "failed", "authorization")
    global _COMMITTED_ACTION
    _COMMITTED_ACTION = None
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)

    def interrupt(_signum: int, _frame: object) -> None:
        raise Interrupted()

    for item in HANDLED_SIGNALS:
        signal.signal(item, interrupt)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, HANDLED_SIGNALS)
    category = "success"
    state = "success"
    self_bound: BoundFile | None = None
    try:
        self_bound = _validate_control_self()
        if action == "preflight":
            static_preflight()
        elif action == "authorize-audit":
            authorize_audit()
        elif action == "authorize-recover":
            authorize_recovery()
        elif action == "launch-audit":
            launch("audit")
        elif action == "launch-recover":
            launch("recover")
        elif action == "node-audit":
            node_stage("audit")
        elif action == "node-recover":
            node_stage("recover")
    except ControlError as error:
        category = error.category
        state = "failed"
    except BaseException:
        category = "internal"
        state = "failed"
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    if _COMMITTED_ACTION == action:
        category = "success"
        state = "success"
    for item in HANDLED_SIGNALS:
        signal.signal(item, signal.SIG_IGN)
    for name in tuple(os.environ):
        if name.startswith("VMVM_V4_RECOVERY_"):
            os.environ.pop(name, None)
    if self_bound is not None:
        self_bound.close()
    _terminal(action, state, category)


if __name__ == "__main__":
    main()
