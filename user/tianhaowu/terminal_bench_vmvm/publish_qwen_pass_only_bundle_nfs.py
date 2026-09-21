"""Publish a validated pass-only SFT bundle safely on NFSv3.

The destination is non-authoritative until ``manifest.json`` is atomically
hard-linked into it. All payload copying and exact tree validation happen
before that commit point. No rollback deletion is attempted after commit.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any


class PublishError(RuntimeError):
    pass


MANIFEST = "manifest.json"
CERTIFICATE = "source-continuation-pass-only-certificate.json"
EXPECTED_KIND = "qwen-sandoq-source-continuation-pass-only-merged-sft"
EXPECTED_ARTIFACTS = frozenset(
    {
        "target-rendering-contract.json",
        "task-split.json",
        "train/train.jsonl",
        "validation/train.jsonl",
    }
)
EXPECTED_DIRECTORIES = frozenset({".", "train", "validation"})
FICLONE = 0x40049409
MAX_MANIFEST_BYTES = 16 << 20
MAX_CERTIFICATE_BYTES = 16 << 20
HEX = frozenset("0123456789abcdef")


def _directory_flags() -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _file_flags(*, writable: bool = False, create: bool = False) -> int:
    flags = (os.O_RDWR if writable else os.O_RDONLY) | os.O_CLOEXEC
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def _validate_directory_metadata(metadata: os.stat_result, code: str) -> None:
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid():
        raise PublishError(code)


def _validate_file_metadata(metadata: os.stat_result, code: str) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise PublishError(code)


def _open_private_directory(path: Path, code: str) -> tuple[int, tuple[int, int]]:
    try:
        listed = path.lstat()
        if path.resolve(strict=True) != path:
            raise PublishError(code)
        _validate_directory_metadata(listed, code)
        descriptor = os.open(path, _directory_flags())
        opened = os.fstat(descriptor)
        _validate_directory_metadata(opened, code)
        if _directory_identity(listed) != _directory_identity(opened):
            raise PublishError(code)
    except BaseException:
        with contextlib.suppress(UnboundLocalError, OSError):
            os.close(descriptor)
        raise
    return descriptor, _directory_identity(opened)


def _assert_directory_binding(descriptor: int, identity: tuple[int, int], code: str) -> None:
    metadata = os.fstat(descriptor)
    _validate_directory_metadata(metadata, code)
    if _directory_identity(metadata) != identity:
        raise PublishError(code)


def _assert_directory_path_binding(
    path: Path,
    descriptor: int,
    identity: tuple[int, int],
    code: str,
) -> None:
    try:
        listed = path.lstat()
        if path.resolve(strict=True) != path:
            raise PublishError(code)
    except OSError as error:
        raise PublishError(code) from error
    _validate_directory_metadata(listed, code)
    _assert_directory_binding(descriptor, identity, code)
    if _directory_identity(listed) != identity:
        raise PublishError(code)


def _open_child_directory(parent_descriptor: int, name: str, code: str) -> tuple[int, tuple[int, int]]:
    listed = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    _validate_directory_metadata(listed, code)
    descriptor = os.open(name, _directory_flags(), dir_fd=parent_descriptor)
    opened = os.fstat(descriptor)
    _validate_directory_metadata(opened, code)
    if _directory_identity(listed) != _directory_identity(opened):
        os.close(descriptor)
        raise PublishError(code)
    return descriptor, _directory_identity(opened)


def _open_regular(parent_descriptor: int, name: str, code: str) -> tuple[int, tuple[int, int, int, int]]:
    listed = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    _validate_file_metadata(listed, code)
    descriptor = os.open(name, _file_flags(), dir_fd=parent_descriptor)
    opened = os.fstat(descriptor)
    _validate_file_metadata(opened, code)
    if _file_identity(listed) != _file_identity(opened):
        os.close(descriptor)
        raise PublishError(code)
    return descriptor, _file_identity(opened)


def _read_all(descriptor: int, limit: int, code: str) -> bytes:
    metadata = os.fstat(descriptor)
    if metadata.st_size > limit:
        raise PublishError(code)
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    size = 0
    while chunk := os.read(descriptor, min(1 << 20, limit + 1 - size)):
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise PublishError(code)
    return b"".join(chunks)


def _write_all(descriptor: int, body: bytes) -> None:
    view = memoryview(body)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise PublishError("manifest_write_failed")
        view = view[written:]


def _digest_open_file(descriptor: int, identity: tuple[int, int, int, int], code: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1 << 20):
        digest.update(chunk)
        size += len(chunk)
    after = os.fstat(descriptor)
    _validate_file_metadata(after, code)
    if _file_identity(after) != identity or size != after.st_size:
        raise PublishError(code)
    return size, digest.hexdigest()


def _names(descriptor: int) -> list[str]:
    duplicate = os.dup(descriptor)
    try:
        with os.scandir(duplicate) as iterator:
            return sorted(entry.name for entry in iterator)
    finally:
        with contextlib.suppress(OSError):
            os.close(duplicate)


def _tree_records(
    descriptor: int,
    *,
    ignored_root_names: frozenset[str] = frozenset(),
) -> list[tuple[str, str, int, int, str]]:
    root_metadata = os.fstat(descriptor)
    _validate_directory_metadata(root_metadata, "bundle_root_invalid")
    records: list[tuple[str, str, int, int, str]] = [("directory", ".", stat.S_IMODE(root_metadata.st_mode), 0, "")]

    def walk(current: int, prefix: str, root: bool) -> None:
        for name in _names(current):
            if root and name in ignored_root_names:
                continue
            metadata = os.stat(name, dir_fd=current, follow_symlinks=False)
            relative = f"{prefix}/{name}" if prefix else name
            if stat.S_ISDIR(metadata.st_mode):
                child, identity = _open_child_directory(current, name, "bundle_entry_invalid")
                try:
                    records.append(("directory", relative, 0o700, 0, ""))
                    walk(child, relative, False)
                    _assert_directory_binding(child, identity, "bundle_changed")
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                child, identity = _open_regular(current, name, "bundle_entry_invalid")
                try:
                    size, digest = _digest_open_file(child, identity, "bundle_changed")
                    records.append(("file", relative, 0o600, size, digest))
                finally:
                    os.close(child)
            else:
                raise PublishError("bundle_entry_invalid")

    walk(descriptor, "", True)
    return records


def _copy_regular(source_parent: int, destination_parent: int, name: str) -> None:
    source, source_identity = _open_regular(source_parent, name, "source_entry_invalid")
    destination = -1
    try:
        destination = os.open(
            name,
            _file_flags(writable=True, create=True),
            0o600,
            dir_fd=destination_parent,
        )
        try:
            fcntl.ioctl(destination, FICLONE, source)
        except OSError as error:
            if error.errno not in {
                errno.EINVAL,
                errno.ENOTTY,
                errno.EOPNOTSUPP,
                errno.EXDEV,
            }:
                raise
            os.lseek(source, 0, os.SEEK_SET)
            while chunk := os.read(source, 1 << 20):
                _write_all(destination, chunk)
        os.fchmod(destination, 0o600)
        os.fsync(destination)
        destination_metadata = os.fstat(destination)
        _validate_file_metadata(destination_metadata, "destination_entry_invalid")
        if destination_metadata.st_size != source_identity[2]:
            raise PublishError("destination_entry_invalid")
        source_after = os.fstat(source)
        if _file_identity(source_after) != source_identity:
            raise PublishError("source_changed")
    finally:
        if destination >= 0:
            os.close(destination)
        os.close(source)


def _copy_payload(source: int, destination: int, *, root: bool = True) -> None:
    for name in _names(source):
        if root and name == MANIFEST:
            continue
        metadata = os.stat(name, dir_fd=source, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            source_child, source_identity = _open_child_directory(source, name, "source_entry_invalid")
            try:
                os.mkdir(name, 0o700, dir_fd=destination)
                destination_child, destination_identity = _open_child_directory(
                    destination,
                    name,
                    "destination_entry_invalid",
                )
                try:
                    _copy_payload(source_child, destination_child, root=False)
                    os.fsync(destination_child)
                    _assert_directory_binding(destination_child, destination_identity, "destination_changed")
                finally:
                    os.close(destination_child)
                _assert_directory_binding(source_child, source_identity, "source_changed")
            finally:
                os.close(source_child)
        elif stat.S_ISREG(metadata.st_mode):
            _copy_regular(source, destination, name)
        else:
            raise PublishError("source_entry_invalid")


def _manifest(
    source: int,
    expected_manifest_sha256: str,
    expected_certificate_sha256: str,
) -> tuple[bytes, dict[str, tuple[int, str]]]:
    manifest_descriptor, manifest_identity = _open_regular(source, MANIFEST, "manifest_invalid")
    try:
        body = _read_all(manifest_descriptor, MAX_MANIFEST_BYTES, "manifest_invalid")
        if _file_identity(os.fstat(manifest_descriptor)) != manifest_identity:
            raise PublishError("manifest_changed")
    finally:
        os.close(manifest_descriptor)
    if hashlib.sha256(body).hexdigest() != expected_manifest_sha256:
        raise PublishError("manifest_digest_mismatch")
    try:
        value: Any = json.loads(body)
        certificate = value["certificate"]["artifact"]
        artifacts = value["artifacts"]
    except (KeyError, TypeError, ValueError) as error:
        raise PublishError("manifest_contract_invalid") from error
    if (
        not isinstance(value, dict)
        or value.get("kind") != EXPECTED_KIND
        or value.get("selection") != "pass-only"
        or not isinstance(certificate, dict)
        or set(certificate) != {"bytes", "sha256"}
        or not isinstance(certificate.get("bytes"), int)
        or isinstance(certificate.get("bytes"), bool)
        or certificate.get("bytes") < 0
        or not isinstance(certificate.get("sha256"), str)
        or not _valid_digest(certificate["sha256"])
        or certificate.get("sha256") != expected_certificate_sha256
        or not isinstance(artifacts, dict)
        or frozenset(artifacts) != EXPECTED_ARTIFACTS
    ):
        raise PublishError("manifest_contract_invalid")
    expected_files: dict[str, tuple[int, str]] = {}
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict) or set(artifact) != {"bytes", "sha256"}:
            raise PublishError("manifest_contract_invalid")
        size = artifact.get("bytes")
        digest = artifact.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not _valid_digest(digest)
        ):
            raise PublishError("manifest_contract_invalid")
        expected_files[name] = (size, digest)
    certificate_descriptor, certificate_identity = _open_regular(source, CERTIFICATE, "certificate_invalid")
    try:
        certificate_body = _read_all(certificate_descriptor, MAX_CERTIFICATE_BYTES, "certificate_invalid")
        if _file_identity(os.fstat(certificate_descriptor)) != certificate_identity:
            raise PublishError("certificate_changed")
    finally:
        os.close(certificate_descriptor)
    if hashlib.sha256(certificate_body).hexdigest() != expected_certificate_sha256 or certificate.get("bytes") != len(
        certificate_body
    ):
        raise PublishError("certificate_invalid")
    expected_files[CERTIFICATE] = (len(certificate_body), expected_certificate_sha256)
    return body, expected_files


def _valid_digest(value: str) -> bool:
    return len(value) == 64 and all(character in HEX for character in value)


def _validate_payload_records(
    records: list[tuple[str, str, int, int, str]],
    expected_files: dict[str, tuple[int, str]],
) -> None:
    observed_directories = {path for kind, path, _mode, _size, _digest in records if kind == "directory"}
    observed_files = {
        path: (size, digest) for kind, path, mode, size, digest in records if kind == "file" and mode == 0o600
    }
    if (
        observed_directories != EXPECTED_DIRECTORIES
        or observed_files != expected_files
        or len(records) != len(EXPECTED_DIRECTORIES) + len(expected_files)
    ):
        raise PublishError("published_payload_contract_invalid")


def _link_noreplace(
    source_descriptor: int,
    destination_descriptor: int,
    destination_name: str,
) -> None:
    try:
        os.link(
            f"/proc/self/fd/{source_descriptor}",
            destination_name,
            dst_dir_fd=destination_descriptor,
            follow_symlinks=True,
        )
    except FileExistsError as error:
        raise PublishError("manifest_already_exists") from error
    except OSError as error:
        raise PublishError("manifest_commit_failed") from error


def publish(
    source_path: Path,
    destination_path: Path,
    *,
    expected_manifest_sha256: str,
    expected_certificate_sha256: str,
) -> dict[str, str]:
    if not _valid_digest(expected_manifest_sha256) or not _valid_digest(expected_certificate_sha256):
        raise PublishError("expected_digest_invalid")
    source_path = Path(os.path.normpath(source_path if source_path.is_absolute() else Path.cwd() / source_path))
    destination_path = Path(
        os.path.normpath(destination_path if destination_path.is_absolute() else Path.cwd() / destination_path)
    )
    if not destination_path.name:
        raise PublishError("destination_invalid")
    if (
        source_path == destination_path
        or source_path.is_relative_to(destination_path)
        or destination_path.is_relative_to(source_path)
    ):
        raise PublishError("source_destination_overlap")
    source, source_identity = _open_private_directory(source_path, "source_invalid")
    parent, parent_identity = _open_private_directory(destination_path.parent, "destination_parent_invalid")
    destination = -1
    destination_identity: tuple[int, int] | None = None
    temporary_manifest = f".{destination_path.name}.manifest-{secrets.token_hex(16)}"
    temporary_manifest_descriptor = -1
    manifest_link_descriptor = -1
    commit_attempted = False
    try:
        try:
            os.mkdir(destination_path.name, 0o700, dir_fd=parent)
        except FileExistsError as error:
            raise PublishError("destination_exists") from error
        destination, destination_identity = _open_child_directory(
            parent,
            destination_path.name,
            "destination_invalid",
        )
        manifest_body, expected_files = _manifest(source, expected_manifest_sha256, expected_certificate_sha256)
        _copy_payload(source, destination)
        source_payload = _tree_records(source, ignored_root_names=frozenset({MANIFEST}))
        destination_payload = _tree_records(destination)
        if source_payload != destination_payload:
            raise PublishError("published_payload_mismatch")
        _validate_payload_records(destination_payload, expected_files)
        _assert_directory_binding(source, source_identity, "source_changed")
        _assert_directory_binding(destination, destination_identity, "destination_changed")
        _assert_directory_binding(parent, parent_identity, "destination_parent_changed")
        temporary_manifest_descriptor = os.open(
            temporary_manifest,
            _file_flags(writable=True, create=True),
            0o600,
            dir_fd=parent,
        )
        _write_all(temporary_manifest_descriptor, manifest_body)
        os.fchmod(temporary_manifest_descriptor, 0o600)
        os.fsync(temporary_manifest_descriptor)
        temporary_metadata = os.fstat(temporary_manifest_descriptor)
        _validate_file_metadata(temporary_metadata, "temporary_manifest_invalid")
        if (
            temporary_metadata.st_size != len(manifest_body)
            or _digest_open_file(
                temporary_manifest_descriptor,
                _file_identity(temporary_metadata),
                "temporary_manifest_invalid",
            )[1]
            != expected_manifest_sha256
        ):
            raise PublishError("temporary_manifest_invalid")
        os.fsync(destination)
        os.fsync(parent)
        _assert_directory_binding(source, source_identity, "source_changed")
        if _tree_records(destination) != destination_payload:
            raise PublishError("destination_changed")
        _assert_directory_binding(destination, destination_identity, "destination_changed")
        _assert_directory_binding(parent, parent_identity, "destination_parent_changed")
        temporary_identity = _file_identity(os.fstat(temporary_manifest_descriptor))
        if temporary_identity != _file_identity(temporary_metadata):
            raise PublishError("temporary_manifest_changed")
        os.close(temporary_manifest_descriptor)
        temporary_manifest_descriptor = -1
        listed_temporary = os.stat(temporary_manifest, dir_fd=parent, follow_symlinks=False)
        if _file_identity(listed_temporary) != temporary_identity:
            raise PublishError("temporary_manifest_changed")
        manifest_link_descriptor = os.open(
            temporary_manifest,
            os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent,
        )
        if _file_identity(os.fstat(manifest_link_descriptor)) != temporary_identity:
            raise PublishError("temporary_manifest_changed")
        _assert_directory_path_binding(source_path, source, source_identity, "source_path_changed")
        _assert_directory_path_binding(
            destination_path.parent,
            parent,
            parent_identity,
            "destination_parent_path_changed",
        )
        _assert_directory_path_binding(
            destination_path,
            destination,
            destination_identity,
            "destination_path_changed",
        )
        commit_attempted = True
        _link_noreplace(manifest_link_descriptor, destination, MANIFEST)
        os.close(manifest_link_descriptor)
        manifest_link_descriptor = -1
        listed_temporary = os.stat(temporary_manifest, dir_fd=parent, follow_symlinks=False)
        if _file_identity(listed_temporary) != temporary_identity:
            raise PublishError("temporary_manifest_changed")
        os.unlink(temporary_manifest, dir_fd=parent)
        try:
            os.stat(temporary_manifest, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PublishError("temporary_manifest_unlink_failed")
        published_manifest = os.stat(MANIFEST, dir_fd=destination, follow_symlinks=False)
        _validate_file_metadata(published_manifest, "published_manifest_invalid")
        if _file_identity(published_manifest) != temporary_identity:
            raise PublishError("published_manifest_invalid")
        published_payload = _tree_records(destination, ignored_root_names=frozenset({MANIFEST}))
        if published_payload != destination_payload:
            raise PublishError("published_payload_changed")
        _validate_payload_records(published_payload, expected_files)
        os.fsync(destination)
        os.fsync(parent)
        _assert_directory_path_binding(
            destination_path.parent,
            parent,
            parent_identity,
            "destination_parent_path_changed",
        )
        _assert_directory_path_binding(
            destination_path,
            destination,
            destination_identity,
            "destination_path_changed",
        )
        return {"state": "published"}
    except BaseException as error:
        if temporary_manifest_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(temporary_manifest_descriptor)
            temporary_manifest_descriptor = -1
        if manifest_link_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(manifest_link_descriptor)
            manifest_link_descriptor = -1
        if commit_attempted:
            raise PublishError("publish_commit_indeterminate") from error
        raise PublishError("publish_precommit_incomplete") from error
    finally:
        if temporary_manifest_descriptor >= 0:
            os.close(temporary_manifest_descriptor)
        if manifest_link_descriptor >= 0:
            os.close(manifest_link_descriptor)
        if destination >= 0:
            os.close(destination)
        os.close(parent)
        os.close(source)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-certificate-sha256", required=True)
    args = parser.parse_args()
    try:
        result = publish(
            args.source,
            args.destination,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_certificate_sha256=args.expected_certificate_sha256,
        )
    except PublishError as error:
        raise SystemExit(str(error)) from None
    except Exception:  # noqa: BLE001 - the CLI boundary must not expose paths or tracebacks
        raise SystemExit("publish_operation_failed") from None
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
