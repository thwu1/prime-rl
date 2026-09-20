#!/usr/bin/env python3
"""Inert, authorization-bound verifier for one retained VMVM v4 scratch inode."""

from __future__ import annotations

import contextlib
import ctypes
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
from typing import Literal, NoReturn

TOKEN = "7d204ee4a313968c25bfbda7"
TARGET_NODE = "cpu-140-255"
TARGET_ROOT = Path("/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch")
QUARANTINE_ROOT = TARGET_ROOT.with_name(f"{TARGET_ROOT.name}-quarantine-{TOKEN}")
EXPECTED_UID = 656177
FAILED_JOB_ID = "1760059"
FAILED_RECEIPT_SHA256 = "d99b126b71913a59304e9cc8af400dee09ac84901a0f4dad52eef18111824ae2"
V4_SOURCE_COMMIT = "ea035668d4b43d1bf8fe588ca4469a2b7a46c5a3"
V4_SOURCE_TREE = "9ed4462ca48f288608fccfeb79dadae23b6470c8"
EVALUATOR_COMMIT = "9d7841b36bafcd58769041925b00deba7c25ffca"
EVALUATOR_TREE = "7f4027723ab036b888b1baee8c0d51c962653f68"
BACKEND_SHA256 = "13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a"
V4_BUNDLE_HASHES = {
    "README.md": "a665e362557e124b77caef8eb59e178152021545bdf14e5086041990f7488db3",
    "finalize_vmvm_owner_lifecycle_v4.py": "03b11faee9088da7c65be946752839e1eb6055bc435dc3543b92fec44e4cdc62",
    "launch_vmvm_owner_lifecycle_v4.py": "354595d2f0822052d6b42cfe12233d9629f75c82a01060745c33ca308000a731",
    "probe_vmvm_owner_lifecycle_v4.py": "4065b1d528f594638b55faa140294106703986103c1bb4821bb545c2aa4859ae",
    "run_vmvm_owner_lifecycle_v4.sbatch": "a8fb8c04574d4de1cfa0cdb9137366baf34c74e72469bcd7e3c7a6814da46287",
    "test_vmvm_owner_lifecycle_v4.py": "5660f22fe1b2c1aa46b6020f6df897fbde842f6a52254ce3b6fe94b8766c2d2d",
}
SHA_RE = re.compile(r"[0-9a-f]{64}")
FD_PATH_RE = re.compile(r"/proc/self/fd/([3-9]|[1-9][0-9]+)")
RESULT_FIELDS = {
    "artifact_type",
    "cleanup_status",
    "inventory_class",
    "owner_state",
    "state",
}
INVENTORY_CLASSES = {
    "empty",
    "regular_only",
    "socket_only",
    "directory_only",
    "mixed_supported",
    "unsupported",
    "unverified",
}
OWNER_STATES = {"absent", "not_checked", "owner_present", "unverified"}
CLEANUP_STATES = {"not_requested", "quarantined", "unverified"}
STATES = {
    "audited",
    "quarantined",
    "retained_authorization_invalid",
    "retained_cleanup_unverified",
    "retained_host_invalid",
    "retained_inventory_unsupported",
    "retained_owner_present",
    "retained_quiescence_unverified",
    "retained_root_binding_invalid",
    "retained_signal",
    "retained_unclassified",
}
MAX_AUTHORIZATION_BYTES = 32 * 1024
QUIESCENCE_SECONDS = 2.0
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_ATTRIB = 0x00000004
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_Q_OVERFLOW = 0x00004000
_IN_ISDIR = 0x40000000
_INOTIFY_MASK = (
    _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_ATTRIB
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_Q_OVERFLOW
)
_INOTIFY_EVENT = struct.Struct("iIII")
_MUTATION_SIGNALS = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}


class RecoveryError(RuntimeError):
    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state if state in STATES else "retained_unclassified"


@dataclass
class BoundEntry:
    descriptor: int
    device: int
    inode: int
    kind: Literal["directory", "regular", "socket"]
    mode: int
    mount_id: int
    nlink: int
    owner_uid: int
    relative: str

    @property
    def identity(self) -> tuple[int, ...]:
        base = (
            self.device,
            self.inode,
            stat.S_IFDIR if self.kind == "directory" else 0,
            self.mode,
            self.owner_uid,
        )
        if self.kind == "directory":
            return (*base, self.mount_id)
        file_type = stat.S_IFREG if self.kind == "regular" else stat.S_IFSOCK
        return (self.device, self.inode, file_type, self.mode, self.owner_uid, self.nlink, self.mount_id)

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass
class BoundInventory:
    entries: dict[str, BoundEntry]
    mount_id: int

    @property
    def identities(self) -> set[tuple[int, int]]:
        return {(entry.device, entry.inode) for entry in self.entries.values()}

    def close(self) -> None:
        for entry in reversed(tuple(self.entries.values())):
            with contextlib.suppress(OSError):
                entry.close()

    def parent_for(self, root_fd: int, relative: str) -> tuple[int, str]:
        parent, separator, name = relative.rpartition("/")
        if not name or name in {".", ".."}:
            raise RecoveryError("retained_inventory_unsupported")
        if not separator:
            return root_fd, name
        entry = self.entries.get(parent)
        if entry is None or entry.kind != "directory" or entry.descriptor < 0:
            raise RecoveryError("retained_inventory_unsupported")
        return entry.descriptor, name


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def descriptor_path(descriptor: int) -> Path:
    return Path(f"/proc/self/fd/{descriptor}")


def _known_mount_ids() -> set[int]:
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
        values = {int(line.split(" ", 1)[0]) for line in lines if line}
    except (OSError, ValueError) as error:
        raise RecoveryError("retained_root_binding_invalid") from error
    if not values:
        raise RecoveryError("retained_root_binding_invalid")
    return values


def _descriptor_mount_id(descriptor: int, known: set[int] | None = None) -> int:
    try:
        fields = {
            name: value
            for line in Path(f"/proc/self/fdinfo/{descriptor}").read_text().splitlines()
            if ":" in line
            for name, value in (line.split(":", 1),)
        }
        mount_id = int(fields["mnt_id"].strip())
    except (KeyError, OSError, ValueError) as error:
        raise RecoveryError("retained_root_binding_invalid") from error
    if mount_id <= 0 or (known is not None and mount_id not in known):
        raise RecoveryError("retained_root_binding_invalid")
    return mount_id


def _require_mount_id(
    descriptor: int,
    expected: int,
    known: set[int],
    failure_state: str,
) -> int:
    observed = _descriptor_mount_id(descriptor, known)
    if observed != expected:
        raise RecoveryError(failure_state)
    return observed


def descriptor_identity(descriptor: int, known_mounts: set[int] | None = None) -> dict[str, int]:
    info = os.fstat(descriptor)
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "mount_id": _descriptor_mount_id(descriptor, known_mounts),
        "owner_uid": info.st_uid,
    }


def _directory_identity_at(parent_fd: int, name: str, known_mounts: set[int]) -> dict[str, int]:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=parent_fd,
    )
    try:
        return descriptor_identity(descriptor, known_mounts)
    finally:
        os.close(descriptor)


def _file_sha256(descriptor: int, maximum: int) -> tuple[bytes, str]:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > maximum:
        raise RecoveryError("retained_authorization_invalid")
    os.lseek(descriptor, 0, os.SEEK_SET)
    payload = bytearray()
    while len(payload) <= maximum:
        chunk = os.read(descriptor, min(1 << 20, maximum + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if len(payload) != info.st_size or len(payload) > maximum:
        raise RecoveryError("retained_authorization_invalid")
    value = bytes(payload)
    return value, sha256_bytes(value)


def _inherited_fd(value: str, *, mode: int, nlink: int) -> int:
    if not value.isdecimal() or int(value) < 3:
        raise RecoveryError("retained_authorization_invalid")
    descriptor = os.dup(int(value))
    info = os.fstat(descriptor)
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
    expected = os.environ.get("EXPECTED_VMVM_V4_RECOVERY_HELPER_SHA256", "")
    if match is None or SHA_RE.fullmatch(expected) is None:
        raise RecoveryError("retained_authorization_invalid")
    descriptor = os.dup(int(match.group(1)))
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o500
        or info.st_uid != EXPECTED_UID
        or info.st_nlink != 1
    ):
        os.close(descriptor)
        raise RecoveryError("retained_authorization_invalid")
    _payload, observed = _file_sha256(descriptor, 1 << 20)
    if observed != expected:
        os.close(descriptor)
        raise RecoveryError("retained_authorization_invalid")
    return descriptor


def _read_authorization(mode: str) -> tuple[int, dict[str, object]]:
    expected_sha = os.environ.get("VMVM_V4_RECOVERY_AUTH_SHA256", "")
    if SHA_RE.fullmatch(expected_sha) is None:
        raise RecoveryError("retained_authorization_invalid")
    descriptor = _inherited_fd(
        os.environ.get("VMVM_V4_RECOVERY_AUTH_FD", ""),
        mode=0o400,
        nlink=1,
    )
    try:
        payload, observed_sha = _file_sha256(descriptor, MAX_AUTHORIZATION_BYTES)
        if observed_sha != expected_sha or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
            raise RecoveryError("retained_authorization_invalid")
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RecoveryError("retained_authorization_invalid") from error
        if not isinstance(value, dict) or canonical_json(value) + b"\n" != payload:
            raise RecoveryError("retained_authorization_invalid")
        required = {
            "artifact_type",
            "authorized_mode",
            "backend_sha256",
            "candidate_token",
            "evaluator_commit",
            "evaluator_tree",
            "failed_job",
            "failure_receipt_sha256",
            "quarantine_root",
            "schema_version",
            "scratch_identity",
            "scratch_root",
            "target_node",
            "v4_bundle_hashes",
            "v4_source_commit",
            "v4_source_tree",
        }
        if set(value) != required:
            raise RecoveryError("retained_authorization_invalid")
        expected_fixed = {
            "artifact_type": "vmvm_v4_scratch_recovery_authorization_v1",
            "authorized_mode": mode,
            "backend_sha256": BACKEND_SHA256,
            "candidate_token": TOKEN,
            "evaluator_commit": EVALUATOR_COMMIT,
            "evaluator_tree": EVALUATOR_TREE,
            "failed_job": {
                "exit_code": "2:0",
                "job_id": FAILED_JOB_ID,
                "state": "FAILED",
            },
            "failure_receipt_sha256": FAILED_RECEIPT_SHA256,
            "quarantine_root": str(QUARANTINE_ROOT),
            "schema_version": 1,
            "scratch_root": str(TARGET_ROOT),
            "target_node": TARGET_NODE,
            "v4_bundle_hashes": V4_BUNDLE_HASHES,
            "v4_source_commit": V4_SOURCE_COMMIT,
            "v4_source_tree": V4_SOURCE_TREE,
        }
        for name, expected_value in expected_fixed.items():
            if value.get(name) != expected_value:
                raise RecoveryError("retained_authorization_invalid")
        identity = value.get("scratch_identity")
        if (
            not isinstance(identity, dict)
            or set(identity) != {"device", "inode", "mode", "mount_id", "owner_uid"}
            or any(type(identity.get(name)) is not int for name in identity)
            or identity["device"] < 0
            or identity["inode"] <= 0
            or identity["mode"] != 0o700
            or identity["mount_id"] <= 0
            or identity["owner_uid"] != EXPECTED_UID
        ):
            raise RecoveryError("retained_authorization_invalid")
        return descriptor, value
    except BaseException:
        os.close(descriptor)
        raise


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute() or str(path) != os.path.normpath(path):
        raise RecoveryError("retained_root_binding_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    chains: list[list[int]] = []
    try:
        known_mounts = _known_mount_ids()
        for _pass in range(2):
            chain = [os.open("/", flags)]
            chains.append(chain)
            for component in path.parts[1:]:
                if component in {"", ".", ".."}:
                    raise RecoveryError("retained_root_binding_invalid")
                chain.append(os.open(component, flags, dir_fd=chain[-1]))
        signatures = [
            [
                (
                    item.st_dev,
                    item.st_ino,
                    item.st_mode,
                    item.st_uid,
                    _descriptor_mount_id(descriptor, known_mounts),
                )
                for descriptor, item in ((descriptor, os.fstat(descriptor)) for descriptor in chain)
            ]
            for chain in chains
        ]
        if signatures[0] != signatures[1]:
            raise RecoveryError("retained_root_binding_invalid")
        return os.dup(chains[0][-1])
    except OSError as error:
        raise RecoveryError("retained_root_binding_invalid") from error
    finally:
        for chain in chains:
            for descriptor in reversed(chain):
                os.close(descriptor)


def _open_bound_root(expected: Mapping[str, object]) -> tuple[int, int]:
    parent_fd = _open_absolute_directory(TARGET_ROOT.parent)
    try:
        root_fd = os.open(
            TARGET_ROOT.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
    except OSError as error:
        os.close(parent_fd)
        raise RecoveryError("retained_root_binding_invalid") from error
    try:
        known_mounts = _known_mount_ids()
        actual = descriptor_identity(root_fd, known_mounts)
        parent_mount_id = _descriptor_mount_id(parent_fd, known_mounts)
        root_mount_id = _require_mount_id(
            root_fd,
            parent_mount_id,
            known_mounts,
            "retained_root_binding_invalid",
        )
        named_identity = _directory_identity_at(parent_fd, TARGET_ROOT.name, known_mounts)
        if (
            actual != expected
            or named_identity != actual
            or actual["mode"] != 0o700
            or root_mount_id != parent_mount_id
        ):
            raise RecoveryError("retained_root_binding_invalid")
    except BaseException:
        os.close(root_fd)
        os.close(parent_fd)
        raise
    return parent_fd, root_fd


def _leaf_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    file_type = stat.S_IFMT(info.st_mode)
    if file_type not in {stat.S_IFREG, stat.S_IFSOCK} or info.st_uid != EXPECTED_UID or info.st_nlink != 1:
        raise RecoveryError("retained_inventory_unsupported")
    return (
        info.st_dev,
        info.st_ino,
        file_type,
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_nlink,
    )


def _inventory(root_fd: int) -> tuple[str, tuple[str, ...], BoundInventory]:
    kinds: set[str] = set()
    sockets: list[str] = []
    entries: dict[str, BoundEntry] = {}
    known_mounts = _known_mount_ids()
    root_mount_id = _descriptor_mount_id(root_fd, known_mounts)

    def walk(directory_fd: int, prefix: tuple[str, ...]) -> None:
        for name in sorted(os.listdir(directory_fd)):
            if not name or "/" in name or name in {".", ".."}:
                raise RecoveryError("retained_inventory_unsupported")
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise RecoveryError("retained_inventory_unsupported") from error
            if info.st_uid != EXPECTED_UID:
                raise RecoveryError("retained_inventory_unsupported")
            relative = "/".join((*prefix, name))
            if stat.S_ISDIR(info.st_mode):
                kinds.add("directory")
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    opened = os.fstat(child_fd)
                    mount_id = _require_mount_id(
                        child_fd,
                        root_mount_id,
                        known_mounts,
                        "retained_inventory_unsupported",
                    )
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or opened.st_uid != EXPECTED_UID:
                        raise RecoveryError("retained_inventory_unsupported")
                    entries[relative] = BoundEntry(
                        descriptor=child_fd,
                        device=opened.st_dev,
                        inode=opened.st_ino,
                        kind="directory",
                        mode=stat.S_IMODE(opened.st_mode),
                        mount_id=mount_id,
                        nlink=opened.st_nlink,
                        owner_uid=opened.st_uid,
                        relative=relative,
                    )
                    child_fd = -1
                    walk(entries[relative].descriptor, (*prefix, name))
                finally:
                    if child_fd >= 0:
                        os.close(child_fd)
            elif stat.S_ISREG(info.st_mode) or stat.S_ISSOCK(info.st_mode):
                kind = "socket" if stat.S_ISSOCK(info.st_mode) else "regular"
                descriptor = os.open(
                    name,
                    os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                opened = os.fstat(descriptor)
                try:
                    identity = _leaf_identity(opened)
                    mount_id = _require_mount_id(
                        descriptor,
                        root_mount_id,
                        known_mounts,
                        "retained_inventory_unsupported",
                    )
                    if identity != _leaf_identity(info):
                        raise RecoveryError("retained_inventory_unsupported")
                    entries[relative] = BoundEntry(
                        descriptor=descriptor,
                        device=opened.st_dev,
                        inode=opened.st_ino,
                        kind=kind,
                        mode=stat.S_IMODE(opened.st_mode),
                        mount_id=mount_id,
                        nlink=opened.st_nlink,
                        owner_uid=opened.st_uid,
                        relative=relative,
                    )
                    descriptor = -1
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
                kinds.add(kind)
                if kind == "socket":
                    sockets.append(relative)
            else:
                raise RecoveryError("retained_inventory_unsupported")

    try:
        walk(root_fd, ())
    except BaseException:
        BoundInventory(entries, root_mount_id).close()
        raise
    if not kinds:
        classification = "empty"
    elif len(kinds) > 1:
        classification = "mixed_supported"
    else:
        classification = f"{next(iter(kinds))}_only"
    return classification, tuple(sockets), BoundInventory(entries, root_mount_id)


def _process_references(
    process_root: Path,
    *,
    socket_names: Sequence[str],
    socket_object_ids: set[bytes],
    bound_identities: set[tuple[int, int]],
) -> bool:
    socket_basenames = {name.rsplit("/", 1)[-1].encode() for name in socket_names}
    command = (process_root / "cmdline").read_bytes()[: 1 << 20]
    if os.fsencode(TARGET_ROOT) in command or any(name in command for name in socket_basenames):
        return True
    for link_name in ("cwd", "root"):
        try:
            info = os.stat(process_root / link_name, follow_symlinks=True)
        except (FileNotFoundError, ProcessLookupError):
            continue
        if (info.st_dev, info.st_ino) in bound_identities:
            return True
    fd_directory = os.open(process_root / "fd", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for fd_name in os.listdir(fd_directory):
            try:
                target = os.readlink(fd_name, dir_fd=fd_directory).encode()
                info = os.stat(fd_name, dir_fd=fd_directory, follow_symlinks=True)
            except (FileNotFoundError, ProcessLookupError):
                continue
            if (info.st_dev, info.st_ino) in bound_identities or any(
                target == b"socket:[" + object_id + b"]" for object_id in socket_object_ids
            ):
                return True
    finally:
        os.close(fd_directory)
    return False


def _same_uid_process_references(
    socket_names: Sequence[str],
    bound_identities: set[tuple[int, int]],
) -> bool:
    socket_basenames = {name.rsplit("/", 1)[-1].encode() for name in socket_names}
    socket_object_ids: set[bytes] = set()
    try:
        for line in Path("/proc/net/unix").read_bytes().splitlines()[1:]:
            fields = line.split(maxsplit=7)
            if len(fields) == 8 and any(fields[7].endswith(b"/" + name) for name in socket_basenames):
                socket_object_ids.add(fields[6])
    except OSError as error:
        raise RecoveryError("retained_quiescence_unverified") from error
    for entry in os.scandir("/proc"):
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        process_root = Path("/proc") / entry.name
        try:
            try:
                process_uid = process_root.stat().st_uid
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError as error:
                raise RecoveryError("retained_quiescence_unverified") from error
            if process_uid != EXPECTED_UID:
                continue
            try:
                if _process_references(
                    process_root,
                    socket_names=socket_names,
                    socket_object_ids=socket_object_ids,
                    bound_identities=bound_identities,
                ):
                    return True
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError as error:
                raise RecoveryError("retained_quiescence_unverified") from error
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as error:
            raise RecoveryError("retained_quiescence_unverified") from error
    return False


def _quiesce(
    root_fd: int,
    sockets: Sequence[str],
    bound_identities: set[tuple[int, int]],
    inventory: BoundInventory,
) -> bool:
    # Recovery must never address a ControlMaster through a mutable pathname.
    # A live owner is a closed failure; only already-stale sockets are eligible
    # for descriptor-bound removal below.
    for relative in sockets:
        entry = inventory.entries.get(relative)
        parent_fd, name = inventory.parent_for(root_fd, relative)
        if entry is None or entry.kind != "socket" or _identity_at(parent_fd, name, directory=False) != entry.identity:
            raise RecoveryError("retained_quiescence_unverified")
    deadline = time.monotonic() + QUIESCENCE_SECONDS
    while time.monotonic() < deadline:
        if _same_uid_process_references(sockets, bound_identities):
            return False
        time.sleep(min(0.1, deadline - time.monotonic()))
    return not _same_uid_process_references(sockets, bound_identities)


def _open_watch(directory_fd: int) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = int(libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
    if descriptor < 0:
        raise RecoveryError("retained_cleanup_unverified")
    watch = int(
        libc.inotify_add_watch(
            ctypes.c_int(descriptor),
            ctypes.c_char_p(os.fsencode(descriptor_path(directory_fd))),
            ctypes.c_uint32(_INOTIFY_MASK),
        )
    )
    if watch < 0:
        os.close(descriptor)
        raise RecoveryError("retained_cleanup_unverified")
    return descriptor


def _read_events(descriptor: int) -> list[tuple[int, int, bytes]]:
    events: list[tuple[int, int, bytes]] = []
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
            _watch, mask, cookie, name_size = _INOTIFY_EVENT.unpack_from(payload, offset)
            offset += _INOTIFY_EVENT.size
            if name_size > len(payload) - offset:
                raise RecoveryError("retained_cleanup_unverified")
            name = payload[offset : offset + name_size].split(b"\0", 1)[0]
            offset += name_size
            events.append((mask & ~_IN_ISDIR, cookie, name))
    return events


def _rename_noreplace(parent_fd: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _expected_move(events: Sequence[tuple[int, int, bytes]], source: str, target: str) -> bool:
    return (
        len(events) == 2
        and events[0][0] == _IN_MOVED_FROM
        and events[0][1] != 0
        and events[0][2] == os.fsencode(source)
        and events[1] == (_IN_MOVED_TO, events[0][1], os.fsencode(target))
    )


def _identity_at(parent_fd: int, name: str, *, directory: bool) -> tuple[int, ...]:
    flags = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        info = os.fstat(descriptor)
        mount_id = _descriptor_mount_id(descriptor)
        if directory:
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != EXPECTED_UID:
                raise RecoveryError("retained_cleanup_unverified")
            return (
                info.st_dev,
                info.st_ino,
                stat.S_IFDIR,
                stat.S_IMODE(info.st_mode),
                info.st_uid,
                mount_id,
            )
        return (*_leaf_identity(info), mount_id)
    finally:
        os.close(descriptor)


def _quarantine_root_verified(parent_fd: int, root_fd: int, expected: Mapping[str, object]) -> None:
    if QUARANTINE_ROOT.parent != TARGET_ROOT.parent:
        raise RecoveryError("retained_root_binding_invalid")
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _MUTATION_SIGNALS)
    watch_fd = -1
    try:
        known_mounts = _known_mount_ids()
        if (
            descriptor_identity(root_fd, known_mounts) != expected
            or _directory_identity_at(parent_fd, TARGET_ROOT.name, known_mounts) != expected
            or _descriptor_mount_id(parent_fd, known_mounts) != int(expected["mount_id"])
        ):
            raise RecoveryError("retained_root_binding_invalid")
        try:
            os.stat(QUARANTINE_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryError("retained_cleanup_unverified")
        watch_fd = _open_watch(parent_fd)
        if _read_events(watch_fd):
            raise RecoveryError("retained_cleanup_unverified")
        if _directory_identity_at(parent_fd, TARGET_ROOT.name, known_mounts) != expected:
            raise RecoveryError("retained_root_binding_invalid")
        # renameat2 has no compare-by-inode form. The authorization therefore
        # requires a quiescent same-UID namespace; any raced substitute is kept
        # intact in quarantine and rejected by the retained-FD check below.
        _rename_noreplace(parent_fd, TARGET_ROOT.name, QUARANTINE_ROOT.name)
        os.fsync(parent_fd)
        if not _expected_move(_read_events(watch_fd), TARGET_ROOT.name, QUARANTINE_ROOT.name):
            raise RecoveryError("retained_cleanup_unverified")
        try:
            os.stat(TARGET_ROOT.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryError("retained_cleanup_unverified")
        if (
            descriptor_identity(root_fd, known_mounts) != expected
            or _directory_identity_at(parent_fd, QUARANTINE_ROOT.name, known_mounts) != expected
        ):
            raise RecoveryError("retained_cleanup_unverified")
    except OSError as error:
        raise RecoveryError("retained_cleanup_unverified") from error
    finally:
        try:
            if watch_fd >= 0:
                os.close(watch_fd)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def _result(
    *,
    state: str,
    inventory_class: str,
    owner_state: str,
    cleanup_status: str,
) -> dict[str, str]:
    value = {
        "artifact_type": "vmvm_v4_scratch_recovery_result_v1",
        "cleanup_status": cleanup_status,
        "inventory_class": inventory_class,
        "owner_state": owner_state,
        "state": state,
    }
    if (
        set(value) != RESULT_FIELDS
        or state not in STATES
        or inventory_class not in INVENTORY_CLASSES
        or owner_state not in OWNER_STATES
        or cleanup_status not in CLEANUP_STATES
    ):
        raise RecoveryError("retained_unclassified")
    return value


def execute(mode: str) -> dict[str, str]:
    if mode not in {"audit", "recover"}:
        raise RecoveryError("retained_authorization_invalid")
    if (
        os.getuid() != EXPECTED_UID
        or os.uname().nodename.split(".", 1)[0] != TARGET_NODE
        or os.environ.get("SLURMD_NODENAME") != TARGET_NODE
    ):
        raise RecoveryError("retained_host_invalid")
    self_fd = _validate_self()
    authorization_fd = -1
    parent_fd = -1
    root_fd = -1
    inventory: BoundInventory | None = None
    try:
        authorization_fd, authorization = _read_authorization(mode)
        identity = authorization["scratch_identity"]
        assert isinstance(identity, dict)
        parent_fd, root_fd = _open_bound_root(identity)
        inventory_class, sockets, inventory = _inventory(root_fd)
        if mode == "audit":
            return _result(
                state="audited",
                inventory_class=inventory_class,
                owner_state="not_checked",
                cleanup_status="not_requested",
            )
        bound_identities = inventory.identities | {(int(identity["device"]), int(identity["inode"]))}
        if not _quiesce(root_fd, sockets, bound_identities, inventory):
            return _result(
                state="retained_owner_present",
                inventory_class=inventory_class,
                owner_state="owner_present",
                cleanup_status="unverified",
            )
        _quarantine_root_verified(parent_fd, root_fd, identity)
        return _result(
            state="quarantined",
            inventory_class=inventory_class,
            owner_state="absent",
            cleanup_status="quarantined",
        )
    finally:
        if inventory is not None:
            inventory.close()
        for descriptor in (root_fd, parent_fd, authorization_fd, self_fd):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)


def _terminal_record(result: Mapping[str, str]) -> NoReturn:
    payload = canonical_json(dict(result)) + b"\n"
    if len(payload) > 512:
        payload = (
            canonical_json(
                _result(
                    state="retained_unclassified",
                    inventory_class="unverified",
                    owner_state="unverified",
                    cleanup_status="unverified",
                )
            )
            + b"\n"
        )
    offset = 0
    while offset < len(payload):
        written = os.write(1, payload[offset:])
        if written <= 0:
            raise SystemExit(2)
        offset += written
    raise SystemExit(0 if result.get("state") in {"audited", "quarantined"} else 2)


def main() -> NoReturn:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    handled = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    signal.pthread_sigmask(signal.SIG_BLOCK, handled)
    interrupted = False

    def on_signal(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True
        raise RecoveryError("retained_signal")

    result: dict[str, str]
    try:
        for handled_signal in handled:
            signal.signal(handled_signal, on_signal)
        result = execute(mode)
    except RecoveryError as error:
        result = _result(
            state=error.state,
            inventory_class="unverified",
            owner_state="unverified",
            cleanup_status="unverified",
        )
    except BaseException:
        result = _result(
            state="retained_unclassified",
            inventory_class="unverified",
            owner_state="unverified",
            cleanup_status="unverified",
        )
    signal.pthread_sigmask(signal.SIG_BLOCK, handled)
    for handled_signal in handled:
        signal.signal(handled_signal, signal.SIG_IGN)
    if interrupted and result["state"] not in {"quarantined", "audited"}:
        result = _result(
            state="retained_signal",
            inventory_class="unverified",
            owner_state="unverified",
            cleanup_status="unverified",
        )
    _terminal_record(result)


if __name__ == "__main__":
    main()
