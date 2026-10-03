#!/usr/bin/env python3
"""Inert, authorization-bound cleanup for one failed Kimi v28 private root."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import signal
import stat
import struct
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

TOKEN = "f95ada640e979789f436081e"
EXPECTED_UID = 656177
TARGET_NODE = "g3-154-095"
TARGET_PARENT = Path("/tmp")
TARGET_NAME_PATTERN = r"k3-registry-pull-v28\.1760071\.0\.[A-Za-z0-9]{6}"
TARGET_NAME_RE = re.compile(TARGET_NAME_PATTERN)
TARGET_NAME_BYTES_RE = re.compile(os.fsencode(TARGET_NAME_PATTERN))

FAILED_JOB_ID = "1760071"
FAILED_JOB_NAME = "k3-reg-pull-153000-v28"
FAILED_JOB_COMMENT_RE = re.compile(r"k3-reg-pull-v28:[0-9a-f]{24}")
FAILED_CLUSTER = "fair-cw-use2-3"
FAILED_PARTITION = "g3"
FAILED_ACCOUNT = "ram"
FAILED_QOS = "g3_lowest"
FAILED_STATE = "FAILED"
FAILED_EXIT_CODE = "3:0"
FAILED_ELAPSED = "00:00:28"
FAILED_TIME_LIMIT = "00:30:00"
EXPECTED_TRES = {
    "billing": "4",
    "cpu": "4",
    "gres/gpu": "1",
    "mem": "16G",
    "node": "1",
}
ACCOUNTING_FIELDS = (
    "JobIDRaw",
    "JobName",
    "User",
    "Account",
    "QOS",
    "Partition",
    "NodeList",
    "State",
    "ExitCode",
    "Elapsed",
    "ReqTRES",
    "AllocTRES",
    "NNodes",
    "ReqCPUS",
    "TimeLimit",
    "Comment",
)

V28_SOURCE_COMMIT = "4d7b256fdce51a3d2a0dd7f336e18a927dd768ef"
V28_SOURCE_TREE = "572b4bd1fd2db7deab150374398a9760a7ebf719"
V28_SOURCE_SUBTREE = "8196764b93e052b4d897eb05cf1e98a123e2003a"
V28_CONTROL_COMMIT = "f7e5498e86d1ad524d2a05a2af1ccbefe2511c17"
V28_CONTROL_TREE = "bbe987e4856d4edb03bac27b3fb3c9ff10dce73d"
V28_CONTROL_SUBTREE = "e96599e760ff3bfcb52069edaf760e82dcdfd1f5"
V28_BUNDLE = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t153000z_v28"
V28_BUNDLE_HASHES = {
    "README.md": "6f46547c9d40dbb9f5c9deacbb78488eddb0214d3c3f94f2f053b97db2dfdea6",
    "classify_registry_error.sh": "46086ed6a6bc4eed4555d8bbe5fe4086f32ba601a79db028635f7cae40170d65",
    "compute_tools.sha256": "af255efed7ea7eba7ea3214bb24febe480476cb92dffd023021ef5e057e1dfba",
    "controller.py": "71a60e91764b9a1d0d24c9ca0ec87afe3e5719135649fd5ae4b8a029aec171ab",
    "launch.sh": "aed35b4e51c4c42c106ff52d7fa372a7d16f6d38ddf7fe1d1f899159b0a7fdcd",
    "pending.json": "a8d3dc1995cea78555666cc66188e9038a8a3d85a8bd9d41492d02acf70dfa7d",
    "podman_guard.sh": "bef59aaf16e7a4950b6426b2c4b1c29c405665b211a6364bd29d22e5af73e200",
    "probe_registry_gate.sh": "8acb57bf1f45112f38cd40eb46e0ba790133506c3799f544aee281ca506b0ca1",
    "run_registry_gate.sbatch": "7bf6df410a16e9d319d8596ce9931d34b110276ef4e1a9fed5fdf8dead7cc170",
    "test_controller.py": "2470aaf4758b5b72f4d861fd30f3dc0dd224d337191f7ce29463ae30c490f23f",
}
V28_CONTROL_HASHES = {
    "README.md": "4d83a7783fa09ddcd5cb282d2303a11eff8668e3d9b8d2376e4bed91de328a8c",
    "create_k3_registry_pull_gate_v28_approval.py": (
        "22d598adcf7aec01752d65c815cea77c6b26f817109f6aec40b9473864825dfb"
    ),
    "run_k3_registry_pull_gate_v28_exact.sh": ("4c82b008fc07b2923f9aa3425081786bb1050139d3f64da42f668707f2bf72c9"),
    "test_k3_registry_pull_gate_v28_controls.py": ("3829fb6e62e08126ef21b03e06fe3b3c5ae44f1f0ba66bd51f4e0ad57bb647ab"),
}
RAM_SOURCE_REVISION = "b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e"
RAM_SOURCE_TREE = "b205ec0f4e2f03f3b3cf5c9e7df7035a49df6772"
RAM_SOURCE_BUNDLE_SHA256 = "ad9c18c971638cf90b367d5827809a06e7fab46d92c38b8ebc9b6650bc7fbf08"
RAM_SOURCE_BUNDLE_SIZE = 5_424_367
APPROVAL_PATH = (
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/approvals/k3_registry_pull_gate_20260920t153000z_v28.approval.json"
)
APPROVAL_SHA256 = "53dbae2fa27cac7474a8561de2fd35399f0df7c9a0f6d2bd8bef7e873d686f5b"
RUN_ROOT = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_pull_gate_20260920t153000z_v28"
PUBLIC_LOG_PATH = (
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_registry_pull_gate_20260920t153000z_v28/slurm-1760071.log"
)
PUBLIC_LOG_SHA256 = "835fb21cf1f5ff4bd02b5619f66b861e8d8dda2a703431894efe15cb69e4a451"
TERMINAL_LOCK_PATH = (
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/locks/k3_registry_pull_gate_20260920t153000z_v28.lock"
)
TERMINAL_LOCK_SHA256 = "e167a7ac92dbaeb2785a17df15ff59f40225830b39d3d0412acff0054f2d91c1"
IMAGE_DIGEST = "sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20"

EXPECTED_LINEAGE = {
    "approval": {
        "mode": 0o400,
        "owner_uid": EXPECTED_UID,
        "path": APPROVAL_PATH,
        "sha256": APPROVAL_SHA256,
    },
    "authorization_scope": {
        "cleanup_only": True,
        "diagnostic_only": True,
        "production_authorized": False,
    },
    "bundle": {
        "files": V28_BUNDLE_HASHES,
        "path": V28_BUNDLE,
        "source_commit": V28_SOURCE_COMMIT,
        "source_subtree": V28_SOURCE_SUBTREE,
        "source_tree": V28_SOURCE_TREE,
    },
    "controls": {
        "files": V28_CONTROL_HASHES,
        "source_commit": V28_CONTROL_COMMIT,
        "source_subtree": V28_CONTROL_SUBTREE,
        "source_tree": V28_CONTROL_TREE,
    },
    "durable_job_result": {
        "path": f"{RUN_ROOT}/job_result.json",
        "present": False,
    },
    "image_digest": IMAGE_DIGEST,
    "public_log": {
        "category": "podman_info_runroot",
        "mode": 0o600,
        "nlink": 1,
        "owner_uid": EXPECTED_UID,
        "path": PUBLIC_LOG_PATH,
        "sha256": PUBLIC_LOG_SHA256,
        "size": 202,
    },
    "ram_source": {
        "bundle_sha256": RAM_SOURCE_BUNDLE_SHA256,
        "bundle_size": RAM_SOURCE_BUNDLE_SIZE,
        "revision": RAM_SOURCE_REVISION,
        "tree": RAM_SOURCE_TREE,
    },
    "run_namespace": {
        "owner_intent_path": f"{RUN_ROOT}/owner_intent.json",
        "root": RUN_ROOT,
        "submission": {
            "job_id": FAILED_JOB_ID,
            "mode": 0o400,
            "nlink": 1,
            "owner_uid": EXPECTED_UID,
            "path": f"{RUN_ROOT}/submission.json",
            "sha256": "8abce712c56b5a72a13fb93bf081266baf75825e536860ee72be1c4d2a53028b",
            "size": 98,
        },
    },
    "terminal_lock": {
        "category": "file_identity",
        "mode": 0o600,
        "nlink": 1,
        "owner_uid": EXPECTED_UID,
        "path": TERMINAL_LOCK_PATH,
        "sha256": TERMINAL_LOCK_SHA256,
        "size": 88,
    },
}

SHA_RE = re.compile(r"[0-9a-f]{64}")
FD_PATH_RE = re.compile(r"/proc/self/fd/([3-9]|[1-9][0-9]+)")
AUTH_FD_ENV = "K3_V28_RECOVERY_AUTH_FD"
AUTH_SHA_ENV = "K3_V28_RECOVERY_AUTH_SHA256"
HELPER_SHA_ENV = "EXPECTED_K3_V28_RECOVERY_HELPER_SHA256"
MAX_AUTHORIZATION_BYTES = 128 * 1024
MAX_PROC_FILE_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 8_192
MAX_DEPTH = 64
ROOT_STABILITY_SECONDS = 0.05
QUIET_SECONDS = 2.0
QUIESCENCE_TIMEOUT_SECONDS = 8.0

RESULT_FIELDS = {
    "artifact_type",
    "cleanup_status",
    "inventory_class",
    "match_state",
    "owner_state",
    "state",
}
STATES = {
    "already_verified",
    "audited",
    "recovered",
    "retained_ambiguous",
    "retained_authorization_invalid",
    "retained_cleanup_unverified",
    "retained_host_invalid",
    "retained_inventory_unsupported",
    "retained_mount_boundary",
    "retained_owner_present",
    "retained_quiescence_unverified",
    "retained_root_binding_invalid",
    "retained_signal",
    "retained_unclassified",
}
MATCH_STATES = {"absent", "ambiguous", "single", "unverified"}
INVENTORY_CLASSES = {
    "absent",
    "directory_only",
    "empty",
    "mixed_supported",
    "regular_only",
    "socket_only",
    "unverified",
}
OWNER_STATES = {"absent", "not_checked", "owner_present", "unverified"}
CLEANUP_STATES = {"not_requested", "unverified", "verified"}

_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_UNMOUNT = 0x00002000
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_IN_ISDIR = 0x40000000
_INOTIFY_MUTATION_MASK = (
    _IN_MODIFY
    | _IN_ATTRIB
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_UNMOUNT
    | _IN_Q_OVERFLOW
)
_INOTIFY_EVENT = struct.Struct("iIII")


class RecoveryError(RuntimeError):
    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state if state in STATES else "retained_unclassified"


@dataclass(frozen=True)
class Identity:
    device: int
    inode: int
    file_type: int
    mode: int
    owner_uid: int
    nlink: int
    size: int
    mount_id: int

    def object_key(self) -> tuple[int, int]:
        return (self.device, self.inode)

    def root_binding(self) -> dict[str, int]:
        return {
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "mount_id": self.mount_id,
            "nlink": self.nlink,
            "owner_uid": self.owner_uid,
        }


@dataclass(frozen=True, order=True)
class MountRecord:
    mount_id: int
    mount_point: str


@dataclass(frozen=True)
class Inventory:
    classification: str
    manifest: tuple[tuple[str, Identity], ...]
    socket_names: tuple[str, ...]

    def identities(self) -> set[tuple[int, int]]:
        return {identity.object_key() for _name, identity in self.manifest}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def descriptor_path(descriptor: int) -> Path:
    return Path(f"/proc/self/fd/{descriptor}")


def _read_limited(descriptor: int, maximum: int, state: str = "retained_unclassified") -> bytes:
    payload = bytearray()
    while len(payload) <= maximum:
        chunk = os.read(descriptor, min(1 << 20, maximum + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    if len(payload) > maximum:
        raise RecoveryError(state)
    return bytes(payload)


def _file_bytes_and_sha(descriptor: int, maximum: int) -> tuple[bytes, str]:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > maximum:
        raise RecoveryError("retained_authorization_invalid")
    os.lseek(descriptor, 0, os.SEEK_SET)
    payload = _read_limited(descriptor, maximum, "retained_authorization_invalid")
    os.lseek(descriptor, 0, os.SEEK_SET)
    after = os.fstat(descriptor)
    if len(payload) != info.st_size or (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
        raise RecoveryError("retained_authorization_invalid")
    return payload, sha256_bytes(payload)


def _inherited_fd(value: str, *, mode: int, nlink: int) -> int:
    if not value.isdecimal() or int(value) < 3:
        raise RecoveryError("retained_authorization_invalid")
    descriptor = -1
    try:
        descriptor = os.dup(int(value))
        info = os.fstat(descriptor)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise RecoveryError("retained_authorization_invalid") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != mode
        or info.st_uid != EXPECTED_UID
        or info.st_nlink != nlink
    ):
        os.close(descriptor)
        raise RecoveryError("retained_authorization_invalid")
    return descriptor


def _validate_self() -> int:
    match = FD_PATH_RE.fullmatch(str(Path(__file__)))
    expected = os.environ.get(HELPER_SHA_ENV, "")
    if match is None or SHA_RE.fullmatch(expected) is None:
        raise RecoveryError("retained_authorization_invalid")
    descriptor = _inherited_fd(match.group(1), mode=0o500, nlink=1)
    try:
        _payload, observed = _file_bytes_and_sha(descriptor, 2 << 20)
        if observed != expected:
            raise RecoveryError("retained_authorization_invalid")
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise RecoveryError("retained_authorization_invalid") from error
    except BaseException:
        os.close(descriptor)
        raise


def _parse_tres(raw: object) -> dict[str, str]:
    if not isinstance(raw, str):
        raise RecoveryError("retained_authorization_invalid")
    parsed: dict[str, str] = {}
    for item in raw.split(","):
        if item.count("=") != 1 or any(character.isspace() for character in item):
            raise RecoveryError("retained_authorization_invalid")
        key, value = item.split("=", 1)
        if not key or not value or key in parsed:
            raise RecoveryError("retained_authorization_invalid")
        parsed[key] = value
    if parsed != EXPECTED_TRES:
        raise RecoveryError("retained_authorization_invalid")
    return parsed


def _validate_accounting_record(value: object) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != set(ACCOUNTING_FIELDS)
        or any(not isinstance(value.get(field), str) for field in ACCOUNTING_FIELDS)
    ):
        raise RecoveryError("retained_authorization_invalid")
    record = dict(value)
    expected = {
        "Account": FAILED_ACCOUNT,
        "Elapsed": FAILED_ELAPSED,
        "ExitCode": FAILED_EXIT_CODE,
        "JobIDRaw": FAILED_JOB_ID,
        "JobName": FAILED_JOB_NAME,
        "NNodes": "1",
        "NodeList": TARGET_NODE,
        "Partition": FAILED_PARTITION,
        "QOS": FAILED_QOS,
        "ReqCPUS": "4",
        "State": FAILED_STATE,
        "TimeLimit": FAILED_TIME_LIMIT,
        "User": "tianhaowu",
    }
    if any(record.get(name) != expected_value for name, expected_value in expected.items()):
        raise RecoveryError("retained_authorization_invalid")
    if FAILED_JOB_COMMENT_RE.fullmatch(record["Comment"]) is None:
        raise RecoveryError("retained_authorization_invalid")
    _parse_tres(record["ReqTRES"])
    _parse_tres(record["AllocTRES"])
    return record


def _validate_terminal_evidence(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"squeue_absent", "stable_accounting_reads"}:
        raise RecoveryError("retained_authorization_invalid")
    reads = value.get("stable_accounting_reads")
    if value.get("squeue_absent") is not True or not isinstance(reads, list) or len(reads) != 2:
        raise RecoveryError("retained_authorization_invalid")
    first = _validate_accounting_record(reads[0])
    second = _validate_accounting_record(reads[1])
    if first != second:
        raise RecoveryError("retained_authorization_invalid")


def _validate_scratch_binding(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"identity", "name", "path"}:
        raise RecoveryError("retained_authorization_invalid")
    name = value.get("name")
    if not isinstance(name, str) or TARGET_NAME_RE.fullmatch(name) is None:
        raise RecoveryError("retained_authorization_invalid")
    if value.get("path") != str(TARGET_PARENT / name):
        raise RecoveryError("retained_authorization_invalid")
    identity = value.get("identity")
    fields = {"device", "inode", "mode", "mount_id", "nlink", "owner_uid"}
    if (
        not isinstance(identity, dict)
        or set(identity) != fields
        or any(type(identity.get(field)) is not int for field in fields)
        or identity["device"] < 0
        or identity["inode"] <= 0
        or identity["mount_id"] <= 0
        or identity["mode"] != 0o700
        or identity["nlink"] < 2
        or identity["owner_uid"] != EXPECTED_UID
    ):
        raise RecoveryError("retained_authorization_invalid")


def _validate_authorization_value(value: object, mode: str) -> dict[str, object]:
    required = {
        "artifact_type",
        "authorized_mode",
        "candidate_token",
        "lineage",
        "schema_version",
        "scratch_binding",
        "scratch_pattern",
        "target_node",
        "terminal_evidence",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise RecoveryError("retained_authorization_invalid")
    fixed = {
        "artifact_type": "k3_registry_pull_gate_v28_private_recovery_authorization_v1",
        "authorized_mode": mode,
        "candidate_token": TOKEN,
        "lineage": EXPECTED_LINEAGE,
        "schema_version": 1,
        "scratch_pattern": str(TARGET_PARENT / TARGET_NAME_PATTERN),
        "target_node": TARGET_NODE,
    }
    if any(value.get(name) != expected for name, expected in fixed.items()):
        raise RecoveryError("retained_authorization_invalid")
    _validate_terminal_evidence(value.get("terminal_evidence"))
    _validate_scratch_binding(value.get("scratch_binding"))
    return dict(value)


def _read_authorization(mode: str) -> tuple[int, dict[str, object]]:
    expected_sha = os.environ.get(AUTH_SHA_ENV, "")
    if SHA_RE.fullmatch(expected_sha) is None:
        raise RecoveryError("retained_authorization_invalid")
    descriptor = _inherited_fd(os.environ.get(AUTH_FD_ENV, ""), mode=0o400, nlink=1)
    try:
        payload, observed_sha = _file_bytes_and_sha(descriptor, MAX_AUTHORIZATION_BYTES)
        if observed_sha != expected_sha or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
            raise RecoveryError("retained_authorization_invalid")
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RecoveryError("retained_authorization_invalid") from error
        if canonical_json(value) + b"\n" != payload:
            raise RecoveryError("retained_authorization_invalid")
        return descriptor, _validate_authorization_value(value, mode)
    except OSError as error:
        os.close(descriptor)
        raise RecoveryError("retained_authorization_invalid") from error
    except BaseException:
        os.close(descriptor)
        raise


def _mount_id(descriptor: int) -> int:
    try:
        fdinfo = os.open(
            f"/proc/self/fdinfo/{descriptor}",
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        try:
            raw = _read_limited(fdinfo, 16 * 1024, "retained_mount_boundary")
        finally:
            os.close(fdinfo)
    except OSError as error:
        raise RecoveryError("retained_mount_boundary") from error
    values = []
    for line in raw.splitlines():
        if line.startswith(b"mnt_id:\t"):
            candidate = line.removeprefix(b"mnt_id:\t")
            if not candidate.isdigit() or int(candidate) <= 0:
                raise RecoveryError("retained_mount_boundary")
            values.append(int(candidate))
    if len(values) != 1:
        raise RecoveryError("retained_mount_boundary")
    return values[0]


def _identity(descriptor: int) -> Identity:
    info = os.fstat(descriptor)
    return Identity(
        device=info.st_dev,
        inode=info.st_ino,
        file_type=stat.S_IFMT(info.st_mode),
        mode=stat.S_IMODE(info.st_mode),
        owner_uid=info.st_uid,
        nlink=info.st_nlink,
        size=info.st_size,
        mount_id=_mount_id(descriptor),
    )


def _same_stable_object(left: Identity, right: Identity) -> bool:
    return (
        left.device,
        left.inode,
        left.file_type,
        left.owner_uid,
        left.mount_id,
    ) == (
        right.device,
        right.inode,
        right.file_type,
        right.owner_uid,
        right.mount_id,
    )


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute() or str(path) != os.path.normpath(path):
        raise RecoveryError("retained_root_binding_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    chains: list[list[int]] = []
    try:
        for _pass in range(2):
            chain = [os.open("/", flags)]
            chains.append(chain)
            for component in path.parts[1:]:
                if component in {"", ".", ".."}:
                    raise RecoveryError("retained_root_binding_invalid")
                chain.append(os.open(component, flags, dir_fd=chain[-1]))
        signatures = [tuple(_identity(descriptor) for descriptor in chain) for chain in chains]
        if signatures[0] != signatures[1]:
            raise RecoveryError("retained_root_binding_invalid")
        return os.dup(chains[0][-1])
    except OSError as error:
        raise RecoveryError("retained_root_binding_invalid") from error
    finally:
        for chain in chains:
            for descriptor in reversed(chain):
                os.close(descriptor)


def _unescape_mount_field(raw: bytes) -> str:
    output = bytearray()
    index = 0
    while index < len(raw):
        if raw[index] != 0x5C:
            output.append(raw[index])
            index += 1
            continue
        if index + 3 >= len(raw) or any(value not in b"01234567" for value in raw[index + 1 : index + 4]):
            raise RecoveryError("retained_mount_boundary")
        output.append(int(raw[index + 1 : index + 4], 8))
        index += 4
    result = os.fsdecode(bytes(output))
    if not result.startswith("/") or os.path.normpath(result) != result:
        raise RecoveryError("retained_mount_boundary")
    return result


def _mount_records() -> tuple[MountRecord, ...]:
    try:
        descriptor = os.open("/proc/self/mountinfo", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            raw = _read_limited(descriptor, 8 << 20, "retained_mount_boundary")
        finally:
            os.close(descriptor)
    except OSError as error:
        raise RecoveryError("retained_mount_boundary") from error
    records: list[MountRecord] = []
    for line in raw.splitlines():
        left, separator, _right = line.partition(b" - ")
        fields = left.split()
        if not separator or len(fields) < 6 or not fields[0].isdigit():
            raise RecoveryError("retained_mount_boundary")
        records.append(MountRecord(int(fields[0]), _unescape_mount_field(fields[4])))
    if not records:
        raise RecoveryError("retained_mount_boundary")
    return tuple(records)


def _path_contains(parent: str, child: str) -> bool:
    return parent == "/" or child == parent or child.startswith(parent.rstrip("/") + "/")


def _validate_mount_boundary(root_path: Path, parent_mount_id: int, root_mount_id: int) -> tuple[MountRecord, ...]:
    if root_mount_id != parent_mount_id:
        raise RecoveryError("retained_mount_boundary")
    root = str(root_path)
    records = _mount_records()
    if any(_path_contains(root, record.mount_point) for record in records):
        raise RecoveryError("retained_mount_boundary")
    covering = [record for record in records if _path_contains(record.mount_point, root)]
    if not covering:
        raise RecoveryError("retained_mount_boundary")
    longest = max(len(record.mount_point) for record in covering)
    active_ids = {record.mount_id for record in covering if len(record.mount_point) == longest}
    if active_ids != {root_mount_id}:
        raise RecoveryError("retained_mount_boundary")
    return tuple(sorted(record for record in records if _path_contains(record.mount_point, root)))


def _open_watch(directory_fd: int, mask: int = _INOTIFY_MUTATION_MASK) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.inotify_init1.argtypes = (ctypes.c_int,)
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32)
    libc.inotify_add_watch.restype = ctypes.c_int
    descriptor = int(libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
    if descriptor < 0:
        raise RecoveryError("retained_cleanup_unverified")
    if (
        libc.inotify_add_watch(
            descriptor,
            os.fsencode(descriptor_path(directory_fd)),
            mask,
        )
        < 0
    ):
        os.close(descriptor)
        raise RecoveryError("retained_cleanup_unverified")
    return descriptor


def _add_watch(watch_fd: int, directory_fd: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.inotify_add_watch.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32)
    libc.inotify_add_watch.restype = ctypes.c_int
    if (
        libc.inotify_add_watch(
            watch_fd,
            os.fsencode(descriptor_path(directory_fd)),
            _INOTIFY_MUTATION_MASK,
        )
        < 0
    ):
        raise RecoveryError("retained_cleanup_unverified")


def _read_events(descriptor: int) -> list[tuple[int, int, int, bytes]]:
    events: list[tuple[int, int, int, bytes]] = []
    while True:
        try:
            payload = os.read(descriptor, 1 << 20)
        except BlockingIOError:
            break
        if not payload:
            raise RecoveryError("retained_cleanup_unverified")
        offset = 0
        while offset < len(payload):
            if len(payload) - offset < _INOTIFY_EVENT.size:
                raise RecoveryError("retained_cleanup_unverified")
            watch, mask, cookie, name_size = _INOTIFY_EVENT.unpack_from(payload, offset)
            offset += _INOTIFY_EVENT.size
            if name_size > len(payload) - offset:
                raise RecoveryError("retained_cleanup_unverified")
            name = payload[offset : offset + name_size].split(b"\0", 1)[0]
            offset += name_size
            events.append((watch, mask, cookie, name))
    return events


def _matching_names(parent_fd: int) -> tuple[str, ...]:
    try:
        return tuple(sorted(name for name in os.listdir(parent_fd) if TARGET_NAME_RE.fullmatch(name) is not None))
    except OSError as error:
        raise RecoveryError("retained_root_binding_invalid") from error


def _stable_matching_names(parent_fd: int) -> tuple[str, ...]:
    watch_fd = _open_watch(parent_fd)
    try:
        if _read_events(watch_fd):
            raise RecoveryError("retained_root_binding_invalid")
        first = _matching_names(parent_fd)
        time.sleep(ROOT_STABILITY_SECONDS)
        second = _matching_names(parent_fd)
        events = _read_events(watch_fd)
        relevant = [
            event
            for event in events
            if event[1] & (_IN_DELETE_SELF | _IN_MOVE_SELF | _IN_UNMOUNT | _IN_Q_OVERFLOW | _IN_IGNORED)
            or TARGET_NAME_BYTES_RE.fullmatch(event[3]) is not None
        ]
        if first != second or relevant:
            raise RecoveryError("retained_root_binding_invalid")
        return second
    finally:
        os.close(watch_fd)


def _open_named_identity(
    parent_fd: int,
    name: str,
    state: str = "retained_root_binding_invalid",
) -> tuple[int, Identity]:
    descriptor = -1
    try:
        descriptor = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        return descriptor, _identity(descriptor)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise RecoveryError(state) from error
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _open_bound_root(
    binding: object,
) -> tuple[int, int, Path | None, Identity | None]:
    parent_fd = _open_absolute_directory(TARGET_PARENT)
    root_fd = -1
    try:
        names = _stable_matching_names(parent_fd)
        if len(names) > 1:
            raise RecoveryError("retained_ambiguous")
        if not names:
            if binding is not None:
                raise RecoveryError("retained_root_binding_invalid")
            return parent_fd, -1, None, None
        if not isinstance(binding, dict) or names[0] != binding.get("name"):
            raise RecoveryError("retained_root_binding_invalid")
        name = names[0]
        root_path = TARGET_PARENT / name
        root_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        root_identity = _identity(root_fd)
        named_fd, named_identity = _open_named_identity(parent_fd, name)
        try:
            expected = binding.get("identity")
            if (
                root_identity != named_identity
                or not isinstance(expected, dict)
                or root_identity.root_binding() != expected
                or root_identity.file_type != stat.S_IFDIR
                or root_identity.mode != 0o700
                or root_identity.owner_uid != EXPECTED_UID
                or root_identity.nlink < 2
                or _identity(parent_fd).mount_id != root_identity.mount_id
            ):
                raise RecoveryError("retained_root_binding_invalid")
        finally:
            os.close(named_fd)
        _validate_mount_boundary(root_path, _identity(parent_fd).mount_id, root_identity.mount_id)
        return parent_fd, root_fd, root_path, root_identity
    except OSError as error:
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)
        raise RecoveryError("retained_root_binding_invalid") from error
    except BaseException:
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)
        raise


def _entry_kind(identity: Identity) -> str:
    if identity.file_type == stat.S_IFDIR:
        return "directory"
    if identity.file_type == stat.S_IFREG:
        return "regular"
    if identity.file_type == stat.S_IFSOCK:
        return "socket"
    return "unsupported"


def _require_supported(identity: Identity, root_identity: Identity) -> None:
    if identity.device != root_identity.device or identity.mount_id != root_identity.mount_id:
        raise RecoveryError("retained_mount_boundary")
    if identity.owner_uid != EXPECTED_UID:
        raise RecoveryError("retained_inventory_unsupported")
    kind = _entry_kind(identity)
    if kind == "unsupported" or (kind in {"regular", "socket"} and identity.nlink != 1):
        raise RecoveryError("retained_inventory_unsupported")


def _open_entry(parent_fd: int, name: str, root_identity: Identity) -> tuple[int, Identity]:
    if (
        not name
        or "/" in name
        or "\0" in name
        or name in {".", ".."}
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        raise RecoveryError("retained_inventory_unsupported")
    named_fd, before = _open_named_identity(parent_fd, name, "retained_inventory_unsupported")
    os.close(named_fd)
    _require_supported(before, root_identity)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    if before.file_type == stat.S_IFDIR:
        flags |= os.O_DIRECTORY
    elif before.file_type == stat.S_IFSOCK:
        flags = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = -1
    after_fd = -1
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        opened = _identity(descriptor)
        after_fd, after = _open_named_identity(parent_fd, name, "retained_inventory_unsupported")
        os.close(after_fd)
        after_fd = -1
    except OSError as error:
        if after_fd >= 0:
            os.close(after_fd)
        if descriptor >= 0:
            os.close(descriptor)
        raise RecoveryError("retained_inventory_unsupported") from error
    except BaseException:
        if after_fd >= 0:
            os.close(after_fd)
        if descriptor >= 0:
            os.close(descriptor)
        raise
    if opened != before or after != opened:
        os.close(descriptor)
        raise RecoveryError("retained_inventory_unsupported")
    return descriptor, opened


def _inventory(root_fd: int, root_identity: Identity, watch_fd: int | None = None) -> Inventory:
    manifest: dict[str, Identity] = {"": _identity(root_fd)}
    kinds: set[str] = set()
    sockets: list[str] = []
    count = 0
    if manifest[""] != root_identity:
        raise RecoveryError("retained_root_binding_invalid")

    def walk(directory_fd: int, prefix: tuple[str, ...], depth: int) -> None:
        nonlocal count
        if depth > MAX_DEPTH:
            raise RecoveryError("retained_inventory_unsupported")
        if watch_fd is not None:
            _add_watch(watch_fd, directory_fd)
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as error:
            raise RecoveryError("retained_inventory_unsupported") from error
        for name in names:
            count += 1
            if count > MAX_ENTRIES:
                raise RecoveryError("retained_inventory_unsupported")
            descriptor, identity = _open_entry(directory_fd, name, root_identity)
            relative = "/".join((*prefix, name))
            manifest[relative] = identity
            kind = _entry_kind(identity)
            kinds.add(kind)
            try:
                if kind == "directory":
                    walk(descriptor, (*prefix, name), depth + 1)
                elif kind == "socket":
                    sockets.append(relative)
            finally:
                os.close(descriptor)

    walk(root_fd, (), 0)
    if not kinds:
        classification = "empty"
    elif len(kinds) == 1:
        classification = f"{next(iter(kinds))}_only"
    else:
        classification = "mixed_supported"
    return Inventory(classification, tuple(sorted(manifest.items())), tuple(sorted(sockets)))


def _read_proc_file_at(process_fd: int, name: str, maximum: int = MAX_PROC_FILE_BYTES) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=process_fd)
    try:
        return _read_limited(descriptor, maximum, "retained_quiescence_unverified")
    finally:
        os.close(descriptor)


def _process_ids() -> tuple[str, ...]:
    try:
        with os.scandir("/proc") as entries:
            return tuple(sorted((entry.name for entry in entries if entry.name.isdecimal()), key=int))
    except OSError as error:
        raise RecoveryError("retained_quiescence_unverified") from error


def _open_process(process_id: str) -> int:
    return os.open(
        f"/proc/{process_id}",
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )


def _process_owner(process_id: str) -> int:
    return os.stat(f"/proc/{process_id}", follow_symlinks=False).st_uid


def _disappeared(error: OSError) -> bool:
    return error.errno in {errno.ENOENT, errno.ESRCH}


def _socket_object_ids(root_path: Path, socket_names: Sequence[str]) -> set[bytes]:
    expected_paths = {os.fsencode(root_path / relative) for relative in socket_names}
    if not expected_paths:
        return set()
    try:
        descriptor = os.open("/proc/net/unix", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            raw = _read_limited(descriptor, MAX_PROC_FILE_BYTES, "retained_quiescence_unverified")
        finally:
            os.close(descriptor)
    except OSError as error:
        raise RecoveryError("retained_quiescence_unverified") from error
    object_ids: set[bytes] = set()
    for line in raw.splitlines()[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) == 8 and fields[7] in expected_paths:
            if not fields[6].isdigit():
                raise RecoveryError("retained_quiescence_unverified")
            object_ids.add(fields[6])
    return object_ids


def _same_uid_process_references(
    root_path: Path,
    identities: set[tuple[int, int]],
    socket_names: Sequence[str],
) -> bool:
    socket_ids = _socket_object_ids(root_path, socket_names)
    socket_targets = {b"socket:[" + object_id + b"]" for object_id in socket_ids}
    for process_id in _process_ids():
        if int(process_id) == os.getpid():
            continue
        process_fd = -1
        fd_directory = -1
        try:
            try:
                process_owner = _process_owner(process_id)
            except OSError as error:
                if _disappeared(error):
                    continue
                raise RecoveryError("retained_quiescence_unverified") from error
            if process_owner != EXPECTED_UID:
                continue
            try:
                process_fd = _open_process(process_id)
                process_info = os.fstat(process_fd)
            except OSError as error:
                if _disappeared(error):
                    continue
                raise RecoveryError("retained_quiescence_unverified") from error
            if process_info.st_uid != process_owner:
                raise RecoveryError("retained_quiescence_unverified")
            disappeared = False
            for special in ("cwd", "root"):
                try:
                    info = os.stat(special, dir_fd=process_fd, follow_symlinks=True)
                except OSError as error:
                    if _disappeared(error):
                        disappeared = True
                        break
                    raise RecoveryError("retained_quiescence_unverified") from error
                if (info.st_dev, info.st_ino) in identities:
                    return True
            if disappeared:
                continue
            try:
                fd_directory = os.open(
                    "fd",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=process_fd,
                )
                fd_names = os.listdir(fd_directory)
            except OSError as error:
                if _disappeared(error):
                    continue
                raise RecoveryError("retained_quiescence_unverified") from error
            for fd_name in fd_names:
                try:
                    target = os.fsencode(os.readlink(fd_name, dir_fd=fd_directory))
                    info = os.stat(fd_name, dir_fd=fd_directory, follow_symlinks=True)
                except OSError as error:
                    if _disappeared(error):
                        continue
                    raise RecoveryError("retained_quiescence_unverified") from error
                if (info.st_dev, info.st_ino) in identities or target in socket_targets:
                    return True
        finally:
            for descriptor in (fd_directory, process_fd):
                if descriptor >= 0:
                    os.close(descriptor)
    return False


def _quiesce(
    root_path: Path,
    inventory: Inventory,
    mutation_watch: int,
) -> bool:
    deadline = time.monotonic() + QUIESCENCE_TIMEOUT_SECONDS
    quiet_since: float | None = None
    while time.monotonic() < deadline:
        if _read_events(mutation_watch):
            raise RecoveryError("retained_quiescence_unverified")
        if _same_uid_process_references(root_path, inventory.identities(), inventory.socket_names):
            quiet_since = None
        else:
            now = time.monotonic()
            if quiet_since is None:
                quiet_since = now
            if now - quiet_since >= QUIET_SECONDS:
                return True
        time.sleep(0.1)
    return False


def _rename_noreplace(parent_fd: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    libc.renameat2.restype = ctypes.c_int
    if libc.renameat2(parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _normalized_events(events: Sequence[tuple[int, int, int, bytes]]) -> list[tuple[int, int, bytes]]:
    return [(mask & ~_IN_ISDIR, cookie, name) for _watch, mask, cookie, name in events]


def _expected_move(events: Sequence[tuple[int, int, int, bytes]], source: str, target: str) -> bool:
    normalized = _normalized_events(events)
    return (
        len(normalized) == 2
        and normalized[0][0] == _IN_MOVED_FROM
        and normalized[0][1] != 0
        and normalized[0][2] == os.fsencode(source)
        and normalized[1] == (_IN_MOVED_TO, normalized[0][1], os.fsencode(target))
    )


def _identity_at(parent_fd: int, name: str) -> Identity:
    descriptor, identity = _open_named_identity(parent_fd, name, "retained_cleanup_unverified")
    os.close(descriptor)
    return identity


def _restore_quarantine(
    parent_fd: int,
    original: str,
    quarantine: str,
    expected: Identity,
) -> None:
    try:
        try:
            os.stat(original, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            return
        if _identity_at(parent_fd, quarantine) != expected:
            return
        _rename_noreplace(parent_fd, quarantine, original)
        os.fsync(parent_fd)
        if _identity_at(parent_fd, original) != expected:
            return
    except (OSError, RecoveryError):
        return


def _detach_delete(
    parent_fd: int,
    name: str,
    descriptor: int,
    expected: Identity,
    *,
    directory: bool,
) -> None:
    move_watch = _open_watch(parent_fd)
    quarantine: str | None = None
    deleted = False
    try:
        if _read_events(move_watch) or _identity_at(parent_fd, name) != expected:
            raise RecoveryError("retained_cleanup_unverified")
        for _attempt in range(8):
            candidate = f".k3-v28-recovery-{os.getpid()}-{os.getrandom(32).hex()}"
            try:
                _rename_noreplace(parent_fd, name, candidate)
            except FileExistsError:
                continue
            quarantine = candidate
            break
        if quarantine is None:
            raise RecoveryError("retained_cleanup_unverified")
        os.fsync(parent_fd)
        if not _expected_move(_read_events(move_watch), name, quarantine):
            raise RecoveryError("retained_cleanup_unverified")
        if _identity_at(parent_fd, quarantine) != expected:
            raise RecoveryError("retained_cleanup_unverified")
    except (OSError, RecoveryError) as error:
        if quarantine is not None:
            _restore_quarantine(parent_fd, name, quarantine, expected)
        if isinstance(error, RecoveryError):
            raise
        raise RecoveryError("retained_cleanup_unverified") from error
    finally:
        os.close(move_watch)
    delete_watch = _open_watch(parent_fd)
    try:
        if _read_events(delete_watch) or quarantine is None or _identity_at(parent_fd, quarantine) != expected:
            raise RecoveryError("retained_cleanup_unverified")
        if directory:
            os.rmdir(quarantine, dir_fd=parent_fd)
        else:
            os.unlink(quarantine, dir_fd=parent_fd)
        deleted = True
        os.fsync(parent_fd)
        removed = _identity(descriptor)
        expected_type = stat.S_IFDIR if directory else expected.file_type
        if (
            removed.device != expected.device
            or removed.inode != expected.inode
            or removed.file_type != expected_type
            or removed.owner_uid != EXPECTED_UID
            or removed.mount_id != expected.mount_id
            or removed.nlink != 0
            or _normalized_events(_read_events(delete_watch)) != [(_IN_DELETE, 0, os.fsencode(quarantine))]
        ):
            raise RecoveryError("retained_cleanup_unverified")
    except (OSError, RecoveryError) as error:
        if not deleted and quarantine is not None:
            _restore_quarantine(parent_fd, name, quarantine, expected)
        if isinstance(error, RecoveryError):
            raise
        raise RecoveryError("retained_cleanup_unverified") from error
    finally:
        os.close(delete_watch)


def _content_events_are_expected(
    events: Sequence[tuple[int, int, int, bytes]],
    name: str,
) -> bool:
    allowed = _IN_ATTRIB | _IN_MODIFY | _IN_CLOSE_WRITE
    encoded = os.fsencode(name)
    return all(
        cookie == 0 and event_name == encoded and mask & ~(_IN_ISDIR | allowed) == 0
        for _wd, mask, cookie, event_name in events
    )


def _scrub_regular(
    parent_fd: int,
    name: str,
    descriptor: int,
    expected: Identity,
    root_identity: Identity,
) -> Identity:
    watch_fd = _open_watch(parent_fd)
    write_fd = -1
    try:
        if _read_events(watch_fd) or _identity_at(parent_fd, name) != expected:
            raise RecoveryError("retained_cleanup_unverified")
        os.fchmod(descriptor, 0o600)
        write_fd = os.open(descriptor_path(descriptor), os.O_WRONLY | os.O_CLOEXEC)
        writable = _identity(write_fd)
        if not _same_stable_object(writable, expected) or writable.nlink != 1:
            raise RecoveryError("retained_cleanup_unverified")
        os.ftruncate(write_fd, 0)
        os.fsync(write_fd)
        os.close(write_fd)
        write_fd = -1
        if not _content_events_are_expected(_read_events(watch_fd), name):
            raise RecoveryError("retained_cleanup_unverified")
        scrubbed = _identity(descriptor)
        named = _identity_at(parent_fd, name)
        _require_supported(scrubbed, root_identity)
        if (
            not _same_stable_object(scrubbed, expected)
            or scrubbed != named
            or scrubbed.mode != 0o600
            or scrubbed.nlink != 1
            or scrubbed.size != 0
        ):
            raise RecoveryError("retained_cleanup_unverified")
        return scrubbed
    except OSError as error:
        raise RecoveryError("retained_cleanup_unverified") from error
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(watch_fd)


def _direct_children(manifest: Mapping[str, Identity], relative: str) -> tuple[str, ...]:
    prefix = f"{relative}/" if relative else ""
    children = []
    for candidate in manifest:
        if candidate == relative or not candidate.startswith(prefix):
            continue
        suffix = candidate[len(prefix) :]
        if "/" not in suffix:
            children.append(suffix)
    return tuple(sorted(children))


def _scrub(
    root_fd: int,
    parent_fd: int,
    root_path: Path,
    root_identity: Identity,
    inventory: Inventory,
) -> None:
    manifest = dict(inventory.manifest)

    def scrub_directory(directory_fd: int, relative: str) -> None:
        expected_directory = manifest[relative]
        opened = _identity(directory_fd)
        if not _same_stable_object(opened, expected_directory):
            raise RecoveryError("retained_cleanup_unverified")
        expected_names = _direct_children(manifest, relative)
        if tuple(sorted(os.listdir(directory_fd))) != expected_names:
            raise RecoveryError("retained_cleanup_unverified")
        os.fchmod(directory_fd, 0o700)
        normalized = _identity(directory_fd)
        if not _same_stable_object(normalized, expected_directory) or normalized.mode != 0o700:
            raise RecoveryError("retained_cleanup_unverified")
        for name in expected_names:
            child_relative = f"{relative}/{name}" if relative else name
            expected = manifest[child_relative]
            descriptor, opened_child = _open_entry(directory_fd, name, root_identity)
            try:
                if opened_child != expected:
                    raise RecoveryError("retained_cleanup_unverified")
                kind = _entry_kind(opened_child)
                if kind == "directory":
                    scrub_directory(descriptor, child_relative)
                    current = _identity(descriptor)
                    named = _identity_at(directory_fd, name)
                    if current != named or current.mode != 0o700 or not _same_stable_object(current, expected):
                        raise RecoveryError("retained_cleanup_unverified")
                    _detach_delete(directory_fd, name, descriptor, current, directory=True)
                elif kind == "regular":
                    scrubbed = _scrub_regular(directory_fd, name, descriptor, expected, root_identity)
                    _detach_delete(directory_fd, name, descriptor, scrubbed, directory=False)
                elif kind == "socket":
                    _detach_delete(directory_fd, name, descriptor, expected, directory=False)
                else:
                    raise RecoveryError("retained_inventory_unsupported")
            finally:
                os.close(descriptor)
        if os.listdir(directory_fd):
            raise RecoveryError("retained_cleanup_unverified")
        os.fsync(directory_fd)

    current_mounts = _validate_mount_boundary(root_path, _identity(parent_fd).mount_id, _identity(root_fd).mount_id)
    scrub_directory(root_fd, "")
    os.fchmod(root_fd, 0o700)
    os.fsync(root_fd)
    os.fsync(parent_fd)
    final_root = _identity(root_fd)
    named_fd, named_root = _open_named_identity(parent_fd, root_path.name, "retained_cleanup_unverified")
    os.close(named_fd)
    final_mounts = _validate_mount_boundary(root_path, _identity(parent_fd).mount_id, final_root.mount_id)
    if (
        current_mounts != final_mounts
        or not _same_stable_object(final_root, root_identity)
        or final_root != named_root
        or final_root.mode != 0o700
        or final_root.nlink != 2
        or final_root.owner_uid != EXPECTED_UID
        or os.listdir(root_fd)
    ):
        raise RecoveryError("retained_cleanup_unverified")


def _signals_pending() -> bool:
    handled = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
    return bool(signal.sigpending() & handled)


def _result(
    *,
    state: str,
    match_state: str,
    inventory_class: str,
    owner_state: str,
    cleanup_status: str,
) -> dict[str, str]:
    value = {
        "artifact_type": "k3_registry_pull_gate_v28_private_recovery_result_v1",
        "cleanup_status": cleanup_status,
        "inventory_class": inventory_class,
        "match_state": match_state,
        "owner_state": owner_state,
        "state": state,
    }
    if (
        set(value) != RESULT_FIELDS
        or state not in STATES
        or match_state not in MATCH_STATES
        or inventory_class not in INVENTORY_CLASSES
        or owner_state not in OWNER_STATES
        or cleanup_status not in CLEANUP_STATES
    ):
        raise RecoveryError("retained_unclassified")
    return value


def _validate_host() -> None:
    if (
        os.getuid() != EXPECTED_UID
        or os.uname().nodename.split(".", 1)[0] != TARGET_NODE
        or os.environ.get("SLURMD_NODENAME") != TARGET_NODE
        or os.environ.get("SLURM_JOB_NODELIST") != TARGET_NODE
        or os.environ.get("SLURM_CLUSTER_NAME") != FAILED_CLUSTER
    ):
        raise RecoveryError("retained_host_invalid")


def execute(mode: str) -> dict[str, str]:
    if mode not in {"audit", "recover"}:
        raise RecoveryError("retained_authorization_invalid")
    _validate_host()
    self_fd = _validate_self()
    authorization_fd = -1
    parent_fd = -1
    root_fd = -1
    mutation_watch = -1
    try:
        authorization_fd, authorization = _read_authorization(mode)
        parent_fd, root_fd, root_path, root_identity = _open_bound_root(authorization["scratch_binding"])
        if root_fd < 0:
            return _result(
                state="already_verified",
                match_state="absent",
                inventory_class="absent",
                owner_state="not_checked",
                cleanup_status="verified",
            )
        assert root_path is not None and root_identity is not None
        if mode == "audit":
            inventory = _inventory(root_fd, root_identity)
            return _result(
                state="audited",
                match_state="single",
                inventory_class=inventory.classification,
                owner_state="not_checked",
                cleanup_status="not_requested",
            )
        initial_mounts = _validate_mount_boundary(
            root_path,
            _identity(parent_fd).mount_id,
            root_identity.mount_id,
        )
        mutation_watch = _open_watch(root_fd)
        initial = _inventory(root_fd, root_identity, mutation_watch)
        if _read_events(mutation_watch):
            raise RecoveryError("retained_quiescence_unverified")
        if not _quiesce(root_path, initial, mutation_watch):
            return _result(
                state="retained_owner_present",
                match_state="single",
                inventory_class=initial.classification,
                owner_state="owner_present",
                cleanup_status="unverified",
            )
        final = _inventory(root_fd, root_identity, mutation_watch)
        final_mounts = _validate_mount_boundary(
            root_path,
            _identity(parent_fd).mount_id,
            root_identity.mount_id,
        )
        if initial != final or initial_mounts != final_mounts or _read_events(mutation_watch):
            raise RecoveryError("retained_quiescence_unverified")
        if _signals_pending():
            raise RecoveryError("retained_signal")
        os.close(mutation_watch)
        mutation_watch = -1
        _scrub(root_fd, parent_fd, root_path, root_identity, final)
        return _result(
            state="recovered",
            match_state="single",
            inventory_class=final.classification,
            owner_state="absent",
            cleanup_status="verified",
        )
    finally:
        for descriptor in (mutation_watch, root_fd, parent_fd, authorization_fd, self_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    attempts = 0
    while offset < len(payload) and attempts < len(payload):
        count = os.write(descriptor, payload[offset:])
        if count <= 0 or count > len(payload) - offset:
            raise RecoveryError("retained_unclassified")
        offset += count
        attempts += 1
    if offset != len(payload):
        raise RecoveryError("retained_unclassified")


def _terminal_record(result: Mapping[str, str], descriptor: int = 1) -> NoReturn:
    payload = canonical_json(dict(result)) + b"\n"
    if len(payload) > 768:
        payload = (
            canonical_json(
                _result(
                    state="retained_unclassified",
                    match_state="unverified",
                    inventory_class="unverified",
                    owner_state="unverified",
                    cleanup_status="unverified",
                )
            )
            + b"\n"
        )
    _write_all(descriptor, payload)
    raise SystemExit(0 if result.get("state") in {"already_verified", "audited", "recovered"} else 2)


def main() -> NoReturn:
    handled = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
    signal.pthread_sigmask(signal.SIG_BLOCK, handled)
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    try:
        for handled_signal in handled:
            signal.signal(handled_signal, lambda _signum, _frame: None)
        result = execute(mode)
    except RecoveryError as error:
        result = _result(
            state=error.state,
            match_state="ambiguous" if error.state == "retained_ambiguous" else "unverified",
            inventory_class="unverified",
            owner_state="unverified",
            cleanup_status="unverified",
        )
    except BaseException:
        result = _result(
            state="retained_unclassified",
            match_state="unverified",
            inventory_class="unverified",
            owner_state="unverified",
            cleanup_status="unverified",
        )
    signal.pthread_sigmask(signal.SIG_BLOCK, handled)
    for handled_signal in handled:
        signal.signal(handled_signal, signal.SIG_IGN)
    _terminal_record(result)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        os._exit(2)
