#!/usr/bin/env python3
"""Audit or exclusively install the reviewed VMVM v4 recovery controls."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

TOKEN = "f6ce50ed0fbe4782ecf8b9af"
OWNER_UID = 656177
BASE_COMMIT = "bf22bf5c6228da3efd14e8279ca61d9ab64c6116"
BASE_TREE = "0c29f9985332e20865b1696f4b90d96512cfdcf1"
RECOVERY_SUBTREE = "64cbc0a1c180b29b2b0a85820a8e3031f0437fda"
RECOVERY_HELPER_SHA256 = "faf05cc04b15c0193d575c6cb1a946bd7677966497e4db53db6abf53c97a6840"
PACKAGE_RELATIVE = Path("user/tianhaowu/terminal_bench_vmvm/vmvm_v4_scratch_recovery_controls_f6ce50ed0fbe4782ecf8b9af")
HELPER_RELATIVE = Path(
    "user/tianhaowu/terminal_bench_vmvm/"
    "vmvm_owner_lifecycle_v4_scratch_recovery_7d204ee4a313968c25bfbda7/"
    "recover_vmvm_owner_lifecycle_v4_scratch.py"
)
DESTINATION = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/vmvm_v4_scratch_recovery_controls_f6ce50ed0fbe4782ecf8b9af"
)
FILES = {
    "README.md": (PACKAGE_RELATIVE / "README.md", 0o400),
    "control.py": (PACKAGE_RELATIVE / "control.py", 0o500),
    "recover_vmvm_owner_lifecycle_v4_scratch.py": (HELPER_RELATIVE, 0o500),
    "run_stage.sbatch": (PACKAGE_RELATIVE / "run_stage.sbatch", 0o500),
}
GIT_OBJECT_RE = re.compile(r"[0-9a-f]{40}")
GIT_ENV = {
    "HOME": "/nonexistent",
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}


class FreezeError(RuntimeError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(repo: Path, *arguments: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        env=GIT_ENV,
    )
    if result.returncode != 0 or result.stderr or len(result.stdout) > 4 << 20:
        raise FreezeError("source")
    return result.stdout if binary else result.stdout.decode("ascii", "strict").strip()


def source_snapshot(repo: Path, reviewed_commit: str, reviewed_tree: str, reviewed_subtree: str) -> dict[str, bytes]:
    if any(GIT_OBJECT_RE.fullmatch(value) is None for value in (reviewed_commit, reviewed_tree, reviewed_subtree)):
        raise FreezeError("review")
    if git(repo, "rev-parse", f"{reviewed_commit}^{{commit}}") != reviewed_commit:
        raise FreezeError("source")
    if git(repo, "rev-parse", f"{reviewed_commit}^{{tree}}") != reviewed_tree:
        raise FreezeError("source")
    if git(repo, "merge-base", "--is-ancestor", BASE_COMMIT, reviewed_commit) != "":
        raise FreezeError("source")
    recovery_path = str(HELPER_RELATIVE.parent)
    if git(repo, "rev-parse", f"{reviewed_commit}:{recovery_path}") != RECOVERY_SUBTREE:
        raise FreezeError("source")
    if git(repo, "rev-parse", f"{reviewed_commit}:{PACKAGE_RELATIVE}") != reviewed_subtree:
        raise FreezeError("source")
    payloads: dict[str, bytes] = {}
    for name, (relative, _mode) in FILES.items():
        raw = git(repo, "show", f"{reviewed_commit}:{relative}", binary=True)
        assert isinstance(raw, bytes)
        if not raw:
            raise FreezeError("source")
        payloads[name] = raw
    if sha256(payloads["recover_vmvm_owner_lifecycle_v4_scratch.py"]) != RECOVERY_HELPER_SHA256:
        raise FreezeError("source")
    return payloads


def manifest(
    reviewed_commit: str,
    reviewed_tree: str,
    reviewed_subtree: str,
    payloads: dict[str, bytes],
) -> dict[str, object]:
    return {
        "artifact_type": "vmvm_v4_scratch_recovery_controls_manifest_v1",
        "base_commit": BASE_COMMIT,
        "base_tree": BASE_TREE,
        "control_source_commit": reviewed_commit,
        "control_source_subtree": reviewed_subtree,
        "control_source_tree": reviewed_tree,
        "files": {
            name: {"mode": format(FILES[name][1], "04o"), "sha256": sha256(payload), "size": len(payload)}
            for name, payload in sorted(payloads.items())
        },
        "recovery_subtree": RECOVERY_SUBTREE,
        "schema_version": 1,
        "token": TOKEN,
    }


def _write_exclusive(parent_fd: int, name: str, payload: bytes, mode: int) -> None:
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=parent_fd)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise FreezeError("write")
            view = view[written:]
        os.fsync(fd)
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != mode
            or opened.st_uid != OWNER_UID
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink, opened.st_size)
            != (named.st_dev, named.st_ino, named.st_mode, named.st_uid, named.st_nlink, named.st_size)
        ):
            raise FreezeError("write")
        os.lseek(fd, 0, os.SEEK_SET)
        if os.read(fd, len(payload) + 1) != payload:
            raise FreezeError("write")
    finally:
        os.close(fd)


def _open_directory(path: Path, *, mode: int) -> int:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise FreezeError("write")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    chains: list[list[int]] = []
    try:
        for _index in range(2):
            chain = [os.open("/", flags)]
            chains.append(chain)
            for component in path.parts[1:]:
                if component in {"", ".", ".."}:
                    raise FreezeError("write")
                chain.append(os.open(component, flags, dir_fd=chain[-1]))
        identities = [
            [(info.st_dev, info.st_ino, info.st_mode, info.st_uid) for fd in chain for info in (os.fstat(fd),)]
            for chain in chains
        ]
        final = os.fstat(chains[0][-1])
        if identities[0] != identities[1] or stat.S_IMODE(final.st_mode) != mode or final.st_uid != OWNER_UID:
            raise FreezeError("write")
        return os.dup(chains[0][-1])
    except OSError as error:
        raise FreezeError("write") from error
    finally:
        for chain in chains:
            for descriptor in reversed(chain):
                os.close(descriptor)


def install(payloads: dict[str, bytes], manifest_value: dict[str, object]) -> None:
    parent = DESTINATION.parent
    parent_fd = _open_directory(parent, mode=0o700)
    bundle_fd = -1
    try:
        os.mkdir(DESTINATION.name, 0o700, dir_fd=parent_fd)
        bundle_fd = os.open(
            DESTINATION.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        for name, payload in sorted(payloads.items()):
            _write_exclusive(bundle_fd, name, payload, FILES[name][1])
        _write_exclusive(bundle_fd, "manifest.json", canonical(manifest_value), 0o400)
        os.fsync(bundle_fd)
        os.fchmod(bundle_fd, 0o555)
        opened = os.fstat(bundle_fd)
        named = os.stat(DESTINATION.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o555
            or opened.st_uid != OWNER_UID
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise FreezeError("write")
        os.fsync(parent_fd)
    except FileExistsError as error:
        raise FreezeError("freshness") from error
    finally:
        if bundle_fd >= 0:
            os.close(bundle_fd)
        os.close(parent_fd)


def output(state: str, category: str) -> NoReturn:
    payload = canonical(
        {
            "artifact_type": "vmvm_v4_scratch_recovery_freeze_public_v1",
            "category": category
            if category in {"success", "freshness", "review", "source", "write", "internal"}
            else "internal",
            "state": state,
        }
    )
    try:
        os.write(1, payload)
    except OSError:
        pass
    raise SystemExit(0 if state == "success" else 2)


def main() -> NoReturn:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in {"audit-source", "install"}:
        output("failed", "review")
    reviewed_commit = os.environ.get("EXPECTED_VMVM_V4_CONTROL_COMMIT", "")
    reviewed_tree = os.environ.get("EXPECTED_VMVM_V4_CONTROL_TREE", "")
    reviewed_subtree = os.environ.get("EXPECTED_VMVM_V4_CONTROL_SUBTREE", "")
    repo_text = os.environ.get("VMVM_V4_CONTROL_REPOSITORY", "")
    try:
        repo = Path(repo_text)
        if not repo.is_absolute() or repo.resolve() != repo or not (repo / ".git").exists():
            raise FreezeError("source")
        payloads = source_snapshot(repo, reviewed_commit, reviewed_tree, reviewed_subtree)
        value = manifest(reviewed_commit, reviewed_tree, reviewed_subtree, payloads)
        if mode == "install":
            install(payloads, value)
    except FreezeError as error:
        output("failed", str(error))
    except BaseException:
        output("failed", "internal")
    output("success", "success")


if __name__ == "__main__":
    main()
