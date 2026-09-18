#!/usr/bin/env python3
"""Copy-on-write migration of a terminal Qwen round-robin eval to sticky routing."""

from __future__ import annotations

import argparse
import contextlib
import copy
import ctypes
import errno
import fcntl
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct

FICLONE = 0x40049409
AT_FDCWD = -100
RENAME_NOREPLACE = 1
TERMINAL_SLURM_STATES = frozenset(
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
        "SPECIAL_EXIT",
        "TIMEOUT",
    }
)
REQUIRED_SOURCE_FILES = (
    "config.toml",
    "direct_workers.json",
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "provenance.txt",
    "results.jsonl",
)
EXPECTED_VERIFIERS_REVISION = direct.ADMISSION_VERIFIERS_REVISION
EXPECTED_RESUME_MODULE_SHA256 = direct.ADMISSION_RESUME_MODULE_SHA256
REPAIR_SELECTION_KIND = "qwen-aggregate-repair-selection"
REPAIR_SELECTION_SCHEMA_VERSION = 2
MAX_REPAIR_SELECTION_BYTES = 1 << 20
COMPATIBLE_RESUME_VERIFIERS_REVISIONS = frozenset(
    {
        EXPECTED_VERIFIERS_REVISION,
        "bb2c42dace0aeecd177e2834f3c87a1d438aed44",
        "fbfbe91d987e0f5bdbcae3eef8c0a272ab9805d5",
        "08a3bf6df2e4f2e04dc1d33e1ee78b7e4da22697",
    }
)


class MigrationError(ValueError):
    """The source run cannot be safely migrated."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_selection_allows_incomplete_tail(
    path: Path | None,
    expected_sha256: str | None,
    results_path: Path,
) -> bool:
    if (path is None) != (expected_sha256 is None):
        raise MigrationError("repair_selection_arguments_invalid")
    if path is None:
        return False
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise MigrationError("repair_selection_digest_invalid")
    absolute = path if path.is_absolute() else Path.cwd() / path
    normalized = Path(os.path.normpath(absolute))
    try:
        if normalized.resolve(strict=True) != normalized:
            raise MigrationError("repair_selection_invalid")
        descriptor = os.open(normalized, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except (OSError, RuntimeError) as error:
        raise MigrationError("repair_selection_invalid") from error
    try:
        handle = os.fdopen(descriptor, "rb")
    except (OSError, ValueError) as error:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise MigrationError("repair_selection_invalid") from error
    try:
        with handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600:
                raise MigrationError("repair_selection_invalid")
            body = handle.read(MAX_REPAIR_SELECTION_BYTES + 1)
            after = os.fstat(handle.fileno())
    except OSError as error:
        raise MigrationError("repair_selection_invalid") from error
    if (
        len(body) > MAX_REPAIR_SELECTION_BYTES
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or hashlib.sha256(body).hexdigest() != expected_sha256
    ):
        raise MigrationError("repair_selection_digest_mismatch")
    try:
        manifest = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MigrationError("repair_selection_invalid") from error
    selection = manifest.get("selection") if isinstance(manifest, dict) else None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    artifacts = source.get("artifacts") if isinstance(source, dict) else None
    results = artifacts.get("results") if isinstance(artifacts, dict) else None
    missing_count = selection.get("missing_or_errored_count") if isinstance(selection, dict) else None
    results_size = results.get("size_bytes") if isinstance(results, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != REPAIR_SELECTION_KIND
        or manifest.get("schema_version") != REPAIR_SELECTION_SCHEMA_VERSION
        or isinstance(missing_count, bool)
        or not isinstance(missing_count, int)
        or missing_count < 0
        or not isinstance(results, dict)
        or set(results) != {"sha256", "size_bytes"}
        or not isinstance(results.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", results["sha256"]) is None
        or isinstance(results_size, bool)
        or not isinstance(results_size, int)
        or results_size < 0
    ):
        raise MigrationError("repair_selection_invalid")
    try:
        observed_results_size = results_path.stat().st_size
        observed_results_sha256 = _sha256(results_path)
    except OSError as error:
        raise MigrationError("source_results_unreadable") from error
    if results["sha256"] != observed_results_sha256 or results_size != observed_results_size:
        raise MigrationError("repair_selection_invalid")
    return missing_count > 0


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _atomic_write(
    path: Path,
    payload: bytes,
    mode: int = 0o600,
    *,
    exclusive: bool = False,
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            try:
                _rename_noreplace(temporary, path)
            except OSError as error:
                if error.errno not in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV}:
                    raise
                try:
                    os.link(temporary, path, follow_symlinks=False)
                except FileExistsError as link_error:
                    raise MigrationError("epoch_index_output_exists") from link_error
                # The link is the commit point.  Never roll it back if removing
                # the known temporary hard link fails; staging owners validate
                # exact entries and clean their private tree before publication.
                with contextlib.suppress(OSError):
                    temporary.unlink()
            except MigrationError as error:
                if str(error) != "destination_exists":
                    raise
                raise MigrationError("epoch_index_output_exists") from error
        else:
            os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MigrationError(f"invalid_json:{path.name}") from error
    if not isinstance(value, dict):
        raise MigrationError(f"json_not_object:{path.name}")
    return value


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError(f"slurm_query_failed:{command[0]}") from error
    return completed.stdout


def _repository_revision() -> str:
    repository = Path(__file__).resolve().parents[3]
    try:
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError("migration_repository_revision_unavailable") from error
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise MigrationError("migration_repository_revision_invalid")
    try:
        status = subprocess.run(
            ["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError("migration_repository_status_unavailable") from error
    if status:
        raise MigrationError("migration_repository_not_clean")
    return revision


def _normalize_slurm_state(raw: str) -> str | None:
    state = raw.strip()
    if re.fullmatch(r"[A-Z][A-Z_]*", state):
        return state
    cancelled = re.fullmatch(r"CANCELLED by ([0-9]+)", state)
    if cancelled is not None:
        return "CANCELLED"
    return None


def slurm_job_is_terminal(job_id: str) -> bool:
    if re.fullmatch(r"[1-9][0-9]*", job_id) is None:
        raise MigrationError("invalid_source_slurm_job_id")
    raw_states = _run(["sacct", "-X", "-n", "-P", "-j", job_id, "--format=State%64"])
    raw_states = [line.split("|", 1)[0] for line in raw_states.splitlines() if line.strip()]
    states = [_normalize_slurm_state(state) for state in raw_states]
    return bool(states) and all(state is not None and state in TERMINAL_SLURM_STATES for state in states)


def _provenance_job_ids(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise MigrationError("source_provenance_unreadable") from error
    job_ids: list[str] = []
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key in {"slurm_job_id", "resume_slurm_job_id"}:
            if re.fullmatch(r"[1-9][0-9]*", value) is None:
                raise MigrationError("invalid_source_slurm_job_id")
            job_ids.append(value)
    if not job_ids:
        raise MigrationError("source_slurm_job_id_missing")
    return job_ids


@contextlib.contextmanager
def _source_locks(source: Path) -> Iterator[None]:
    descriptors: list[int] = []
    try:
        for filename in (".direct_router.lock", ".writer.lock"):
            path = source / filename
            try:
                descriptor = os.open(
                    path,
                    os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                )
            except OSError as error:
                raise MigrationError(f"source_lock_unavailable:{filename}") from error
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise MigrationError(f"source_lock_not_regular:{filename}")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise MigrationError(f"source_lock_busy:{filename}") from error
        yield
    finally:
        for descriptor in reversed(descriptors):
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _copy_file(source: Path, destination: Path) -> None:
    source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise MigrationError(f"source_entry_not_regular:{source.name}")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            metadata.st_mode & 0o777,
        )
        try:
            try:
                fcntl.ioctl(destination_fd, FICLONE, source_fd)
            except OSError as error:
                if error.errno not in {errno.EINVAL, errno.ENOTTY, errno.EOPNOTSUPP, errno.EXDEV}:
                    raise
                while chunk := os.read(source_fd, 1 << 20):
                    view = memoryview(chunk)
                    while view:
                        written = os.write(destination_fd, view)
                        view = view[written:]
            os.fchmod(destination_fd, metadata.st_mode & 0o777)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _clone_tree(source: Path, destination: Path) -> None:
    for entry in os.scandir(source):
        source_entry = Path(entry.path)
        destination_entry = destination / entry.name
        if entry.is_symlink():
            raise MigrationError(f"source_symlink_forbidden:{entry.name}")
        if entry.is_dir(follow_symlinks=False):
            destination_entry.mkdir(mode=stat.S_IMODE(entry.stat().st_mode))
            _clone_tree(source_entry, destination_entry)
        elif entry.is_file(follow_symlinks=False):
            _copy_file(source_entry, destination_entry)
        else:
            raise MigrationError(f"source_special_entry_forbidden:{entry.name}")


def _rename_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise MigrationError("renameat2_unavailable")
    result = renameat2(
        AT_FDCWD,
        os.fsencode(source),
        AT_FDCWD,
        os.fsencode(destination),
        RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise MigrationError("destination_exists")
        raise OSError(error_number, os.strerror(error_number), destination)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    directories = [root]
    for current, names, _files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in names:
            child = current_path / name
            if child.is_symlink() or not child.is_dir():
                raise MigrationError(f"published_directory_invalid:{name}")
            directories.append(child)
    for directory in reversed(directories):
        _fsync_directory(directory)


def _publish_with_incomplete_marker(
    source: Path,
    destination: Path,
    validate: Callable[[Path, bool], None],
) -> None:
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError as error:
        raise MigrationError("destination_exists") from error
    marker = destination / direct.MIGRATION_INCOMPLETE_FILENAME
    marker_descriptor = -1
    try:
        marker_descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        os.write(marker_descriptor, b"qwen-router-affinity-migration-v1\n")
        os.fsync(marker_descriptor)
        marker_metadata = os.fstat(marker_descriptor)
        _fsync_directory(destination)
        _fsync_directory(destination.parent)
        _clone_tree(source, destination)
        _fsync_tree(destination)
        validate(destination, True)
        observed_marker = marker.lstat()
        if (
            not stat.S_ISREG(observed_marker.st_mode)
            or observed_marker.st_dev != marker_metadata.st_dev
            or observed_marker.st_ino != marker_metadata.st_ino
        ):
            raise MigrationError("migration_incomplete_marker_changed")
        marker.unlink()
        _fsync_directory(destination)
        _fsync_directory(destination.parent)
    except Exception:
        with contextlib.suppress(OSError):
            if marker_descriptor >= 0:
                os.close(marker_descriptor)
                marker_descriptor = -1
        with contextlib.suppress(OSError):
            shutil.rmtree(destination)
        raise
    finally:
        if marker_descriptor >= 0:
            os.close(marker_descriptor)


def _publish_directory(
    source: Path,
    destination: Path,
    validate: Callable[[Path, bool], None],
) -> None:
    marker = source / direct.MIGRATION_INCOMPLETE_FILENAME
    try:
        marker_descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as error:
        raise MigrationError("staging_incomplete_marker_unavailable") from error
    try:
        os.write(marker_descriptor, b"qwen-router-migration-v1\n")
        os.fsync(marker_descriptor)
        marker_metadata = os.fstat(marker_descriptor)
        _fsync_tree(source)
        try:
            _rename_noreplace(source, destination)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV}:
                raise
            os.close(marker_descriptor)
            marker_descriptor = -1
            marker.unlink()
            _fsync_directory(source)
            _publish_with_incomplete_marker(source, destination, validate)
            return
        try:
            validate(destination, True)
            published_marker = destination / direct.MIGRATION_INCOMPLETE_FILENAME
            observed_marker = published_marker.lstat()
            if (
                not stat.S_ISREG(observed_marker.st_mode)
                or observed_marker.st_dev != marker_metadata.st_dev
                or observed_marker.st_ino != marker_metadata.st_ino
            ):
                raise MigrationError("migration_incomplete_marker_changed")
            published_marker.unlink()
            _fsync_directory(destination)
            _fsync_directory(destination.parent)
        except Exception:
            with contextlib.suppress(OSError):
                shutil.rmtree(destination)
            raise
    finally:
        if marker_descriptor >= 0:
            os.close(marker_descriptor)


def _rewrite_toml_path(text: str, key: str, old: Path, new: Path) -> str:
    old_literal = json.dumps(str(old))
    new_literal = json.dumps(str(new))
    pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s*=\s*){re.escape(old_literal)}\s*$")
    rewritten, count = pattern.subn(rf"\g<1>{new_literal}", text)
    if count != 1:
        raise MigrationError(f"source_config_{key}_path_not_unique")
    return rewritten


def _declared_source_matches_record(declared: str, recorded: str) -> bool:
    declared_path = Path(declared)
    recorded_path = Path(recorded)
    if not recorded_path.is_absolute():
        return False
    if declared_path.is_absolute():
        return declared_path.resolve() == recorded_path.resolve()
    if not declared_path.parts or ".." in declared_path.parts:
        return False
    return recorded_path.parts[-len(declared_path.parts) :] == declared_path.parts


def _rewrite_toml_integer(text: str, key: str, old: int, new: int) -> str:
    pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s*=\s*){old}\s*$")
    rewritten, count = pattern.subn(rf"\g<1>{new}", text)
    if count != 1:
        raise MigrationError(f"source_config_{key}_not_unique")
    return rewritten


def _rewrite_child_paths(
    source: Path,
    storage: Path,
    child: Path,
    *,
    archive_source_config_filename: str | None = direct.ROUTING_EPOCH1_SOURCE_CONFIG_FILENAME,
    provider_concurrency: tuple[int, int] | None = None,
) -> None:
    config_path = storage / "config.toml"
    source_config_path = storage / "inputs" / "source_config.toml"
    inputs_manifest_path = storage / "inputs" / "manifest.json"
    try:
        config_text = config_path.read_text(encoding="utf-8")
        config = tomllib.loads(config_text)
        source_config_text = source_config_path.read_text(encoding="utf-8")
        source_config = tomllib.loads(source_config_text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise MigrationError("source_config_invalid") from error
    taskset = config.get("taskset")
    source_taskset = source_config.get("taskset")
    if not isinstance(taskset, dict) or not isinstance(source_taskset, dict):
        raise MigrationError("source_config_taskset_invalid")
    inputs_manifest = _read_json_object(inputs_manifest_path)
    config_record = inputs_manifest.get("config")
    if not isinstance(config_record, dict) or set(config_record) != {
        "source",
        "snapshot",
        "sha256",
    }:
        raise MigrationError("source_inputs_config_record_invalid")
    if Path(str(config_record.get("snapshot", ""))).resolve() != (
        source / "inputs" / "source_config.toml"
    ).resolve() or config_record.get("sha256") != _sha256(source_config_path):
        raise MigrationError("source_inputs_config_record_mismatch")
    if archive_source_config_filename is not None:
        _copy_file(source_config_path, storage / "inputs" / archive_source_config_filename)

    for key, filename in (("task_file", "task_file.txt"), ("image_manifest", "image_manifest.json")):
        saved_value = taskset.get(key)
        source_value = source_taskset.get(key)
        record = inputs_manifest.get(key)
        if saved_value is None and source_value is None and key == "image_manifest":
            continue
        if not isinstance(record, dict) or set(record) != {"source", "snapshot", "sha256"}:
            raise MigrationError(f"source_inputs_{key}_record_invalid")
        expected_snapshot = source / "inputs" / filename
        hash_key = f"{key}_sha256"
        record_sha256 = record.get("sha256")
        if (
            not isinstance(saved_value, str)
            or Path(saved_value).resolve() != expected_snapshot.resolve()
            or not isinstance(source_value, str)
            or not isinstance(record.get("source"), str)
            or not _declared_source_matches_record(source_value, record["source"])
            or Path(str(record.get("snapshot", ""))).resolve() != expected_snapshot.resolve()
            or not expected_snapshot.is_file()
            or expected_snapshot.is_symlink()
            or not isinstance(record_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", record_sha256) is None
            or taskset.get(hash_key) != record_sha256
            or source_taskset.get(hash_key) != record_sha256
            or _sha256(expected_snapshot) != record_sha256
        ):
            raise MigrationError(f"source_config_{key}_snapshot_mismatch")
        child_snapshot = child / "inputs" / filename
        config_text = _rewrite_toml_path(
            config_text,
            key,
            Path(saved_value),
            child_snapshot,
        )
        source_config_text = _rewrite_toml_path(
            source_config_text,
            key,
            Path(source_value),
            child_snapshot,
        )
        record["source"] = str(child_snapshot)
        record["snapshot"] = str(child_snapshot)
    if provider_concurrency is not None:
        old_concurrency, new_concurrency = provider_concurrency
        for key in ("max_connections", "max_keepalive_connections"):
            config_text = _rewrite_toml_integer(config_text, key, old_concurrency, new_concurrency)
            source_config_text = _rewrite_toml_integer(
                source_config_text,
                key,
                old_concurrency,
                new_concurrency,
            )
    _atomic_write(config_path, config_text.encode())
    _atomic_write(source_config_path, source_config_text.encode())
    config_record["source"] = str(child / "inputs" / "source_config.toml")
    config_record["snapshot"] = str(child / "inputs" / "source_config.toml")
    config_record["sha256"] = _sha256(source_config_path)
    _atomic_write(inputs_manifest_path, _json_bytes(inputs_manifest))


def _plan_retained_results(
    source_results: Path,
    retained_output: Path,
    row_hashes_output: Path,
    num_tasks: int,
) -> tuple[str, int, int, int, str]:
    offsets: dict[int, int] = {}
    with source_results.open("rb") as results:
        while True:
            offset = results.tell()
            raw = results.readline()
            if not raw:
                break
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                if not raw.endswith(b"\n"):
                    break
                raise MigrationError("source_results_invalid_complete_row") from error
            task = row.get("task") if isinstance(row, dict) else None
            index = task.get("idx") if isinstance(task, dict) else None
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < num_tasks:
                raise MigrationError("source_results_task_index_invalid")
            if not row.get("errors") and index not in offsets:
                offsets[index] = offset

    retained_digest = hashlib.sha256()
    row_hashes: list[str] = []
    retained_size = 0
    with source_results.open("rb") as results, retained_output.open("wb") as retained:
        os.fchmod(retained.fileno(), 0o600)
        for index in range(num_tasks):
            offset = offsets.get(index)
            if offset is None:
                continue
            results.seek(offset)
            raw = results.readline()
            if not raw.endswith(b"\n"):
                raw += b"\n"
            retained.write(raw)
            retained_digest.update(raw)
            retained_size += len(raw)
            row_hashes.append(hashlib.sha256(raw).hexdigest())
        retained.flush()
        os.fsync(retained.fileno())
    if len(row_hashes) != len(set(row_hashes)):
        raise MigrationError("retained_result_row_hash_collision")
    row_hashes_payload = "".join(f"{digest}\n" for digest in row_hashes).encode()
    _atomic_write(row_hashes_output, row_hashes_payload)
    return (
        retained_digest.hexdigest(),
        retained_size,
        len(row_hashes),
        num_tasks - len(row_hashes),
        hashlib.sha256(row_hashes_payload).hexdigest(),
    )


def _load_verifiers_resume(expected_revision: str):
    repository = Path(__file__).resolve().parents[3]
    dependency = repository / "deps" / "verifiers"
    try:
        observed = subprocess.run(
            ["git", "-C", str(dependency), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError("verifiers_revision_unavailable") from error
    # The admission transition remains bound to the historical source revision,
    # while a later runtime may carry compatible verifier fixes. Permit only the
    # reviewed combined runtime revision below, and still require byte-for-byte identity
    # of the resume planner before importing it.
    if expected_revision != EXPECTED_VERIFIERS_REVISION or observed not in COMPATIBLE_RESUME_VERIFIERS_REVISIONS:
        raise MigrationError("verifiers_revision_mismatch")
    try:
        status = subprocess.run(
            ["git", "-C", str(dependency), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError("verifiers_worktree_status_unavailable") from error
    if status:
        raise MigrationError("verifiers_worktree_not_clean")
    resume_path = dependency / "verifiers" / "v1" / "cli" / "eval" / "resume.py"
    if not resume_path.is_file() or resume_path.is_symlink() or _sha256(resume_path) != EXPECTED_RESUME_MODULE_SHA256:
        raise MigrationError("verifiers_resume_module_mismatch")
    for entry in (
        dependency,
        repository / "deps" / "renderers",
        repository / "deps" / "pydantic-config" / "src",
    ):
        value = str(entry)
        if value not in sys.path:
            sys.path.insert(0, value)
    try:
        importlib.import_module("pydantic_core")
    except ImportError:
        staged_site = Path(
            os.environ.get(
                "PYTHON_SITE_X86_64",
                "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64",
            )
        )
        sys.path.insert(0, str(staged_site))
    try:
        sys.dont_write_bytecode = True
        module = importlib.import_module("verifiers.v1.cli.eval.resume")
    except (ImportError, OSError) as error:
        raise MigrationError("verifiers_resume_planner_unavailable") from error
    if Path(module.__file__).resolve() != resume_path.resolve():
        raise MigrationError("verifiers_resume_module_origin_mismatch")
    return module


def _plan_retained_results_with_verifiers(
    source_results: Path,
    retained_output: Path,
    lineage_output: Path,
    num_tasks: int,
    *,
    verifiers_revision: str,
    epoch1_hashes: set[str],
) -> dict[str, Any]:
    """Materialize exactly the rows selected by the pinned resume planner."""
    selected_idxs = list(range(num_tasks))
    selected_payload = "".join(f"{index}\n" for index in selected_idxs).encode()
    resume = _load_verifiers_resume(verifiers_revision)
    try:
        keep, owed = resume.plan(
            source_results.parent,
            selected_idxs,
            1,
            False,
            require_exact_tokens=False,
            require_logprobs=False,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MigrationError("verifiers_resume_plan_failed") from error
    if (
        not isinstance(keep, list)
        or any(isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 for offset in keep)
        or len(keep) != len(set(keep))
        or not isinstance(owed, dict)
        or any(
            isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < num_tasks or count != 1
            for index, count in owed.items()
        )
        or len(keep) + sum(owed.values()) != num_tasks
    ):
        raise MigrationError("verifiers_resume_plan_invalid")

    retained_digest = hashlib.sha256()
    retained_size = 0
    lineage: list[dict[str, Any]] = []
    retained_idxs: list[int] = []
    with source_results.open("rb") as results, retained_output.open("wb") as retained:
        os.fchmod(retained.fileno(), 0o600)
        for offset in keep:
            results.seek(offset)
            raw = results.readline()
            if not raw.endswith(b"\n"):
                raise MigrationError("verifiers_resume_plan_incomplete_row")
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise MigrationError("verifiers_resume_plan_invalid_row") from error
            task = row.get("task") if isinstance(row, dict) else None
            index = task.get("idx") if isinstance(task, dict) else None
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < num_tasks or row.get("errors"):
                raise MigrationError("verifiers_resume_plan_selected_unusable_row")
            retained.write(raw)
            retained_digest.update(raw)
            retained_size += len(raw)
            digest = hashlib.sha256(raw).hexdigest()
            retained_idxs.append(index)
            lineage.append(
                {
                    "row_sha256": digest,
                    "routing_epoch": 1 if digest in epoch1_hashes else 2,
                }
            )
        retained.flush()
        os.fsync(retained.fileno())
    digests = [record["row_sha256"] for record in lineage]
    if len(digests) != len(set(digests)):
        raise MigrationError("retained_result_row_hash_collision")
    if not epoch1_hashes.issubset(digests):
        raise MigrationError("verifiers_resume_plan_dropped_parent_row")
    if (
        len(retained_idxs) != len(set(retained_idxs))
        or set(retained_idxs).intersection(owed)
        or set(retained_idxs).union(owed) != set(selected_idxs)
    ):
        raise MigrationError("verifiers_resume_plan_task_partition_invalid")
    lineage_payload = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode() for record in lineage
    )
    _atomic_write(lineage_output, lineage_payload)
    return {
        "retained_results_sha256": retained_digest.hexdigest(),
        "retained_results_size_bytes": retained_size,
        "retained_row_count": len(lineage),
        "owed_rollout_count": sum(owed.values()),
        "epoch2_lineage_sha256": hashlib.sha256(lineage_payload).hexdigest(),
        "selected_idxs_sha256": hashlib.sha256(selected_payload).hexdigest(),
        "planner_verifiers_revision": verifiers_revision,
        "planner_module_sha256": EXPECTED_RESUME_MODULE_SHA256,
        "num_rollouts": 1,
        "group": False,
        "require_exact_tokens": False,
        "require_logprobs": False,
        "shuffle": False,
    }


def _validate_source(source: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    for relative in REQUIRED_SOURCE_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise MigrationError(f"source_file_missing_or_symlink:{relative}")
    legacy_manifest = _read_json_object(source / "direct_workers.json")
    upgraded_manifest = direct.upgrade_legacy_manifest(legacy_manifest)
    config_path = source / "config.toml"
    task_allowlist_sha256 = direct.validate_eval_config(
        config_path,
        allow_historical_retry_policy=True,
    )
    if task_allowlist_sha256 != upgraded_manifest["approved_task_allowlist_sha256"]:
        raise MigrationError("source_task_allowlist_mismatch")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    expected_url = f"http://127.0.0.1:{upgraded_manifest['router']['port']}/v1"
    if str(config["client"].get("base_url", "")).rstrip("/") != expected_url:
        raise MigrationError("source_router_url_mismatch")
    provenance = direct._read_provenance(source / "provenance.txt")
    if str(provenance.get("inference_base_url", "")).rstrip("/") != expected_url:
        raise MigrationError("source_provenance_url_mismatch")
    if provenance.get("inference_deployment_id"):
        raise MigrationError("source_provenance_deployment_id_present")
    for key in ("prime_rl", "verifiers", "renderers"):
        if re.fullmatch(r"[0-9a-f]{40}", provenance.get(key, "")) is None:
            raise MigrationError(f"source_provenance_{key}_invalid")
    return upgraded_manifest, provenance, config


def _validate_admission_source(source: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    for relative in REQUIRED_SOURCE_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise MigrationError(f"source_file_missing_or_symlink:{relative}")
    forbidden = (
        direct.ADMISSION_TRANSITION_FILENAME,
        direct.ROUTING_EPOCH2_MANIFEST_FILENAME,
        direct.ROUTING_EPOCH2_CONFIG_FILENAME,
        direct.ROUTING_EPOCH2_ROWS_FILENAME,
        direct.ROUTING_EPOCH2_PROVENANCE_FILENAME,
    )
    if any((source / name).exists() or (source / name).is_symlink() for name in forbidden):
        raise MigrationError("source_admission_epoch_already_present")
    for name in (
        direct.ROUTING_EPOCH2_SOURCE_CONFIG_FILENAME,
        direct.ROUTING_EPOCH2_INPUTS_MANIFEST_FILENAME,
    ):
        path = source / "inputs" / name
        if path.exists() or path.is_symlink():
            raise MigrationError("source_admission_epoch_already_present")

    manifest_path = source / "direct_workers.json"
    manifest = direct.validate_saved_manifest(manifest_path)
    provenance = direct.validate_router_provenance(
        source / "provenance.txt",
        _sha256(manifest_path),
    )
    transition = direct.validate_routing_transition(source, manifest, provenance)
    if transition is None or provenance.get("qwen_router_epoch") != "2":
        raise MigrationError("source_is_not_routing_epoch2")
    config_path = source / "config.toml"
    task_allowlist_sha256 = direct.validate_eval_config(
        config_path,
        allow_historical_retry_policy=True,
    )
    if task_allowlist_sha256 != manifest["approved_task_allowlist_sha256"]:
        raise MigrationError("source_task_allowlist_mismatch")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise MigrationError("source_config_invalid") from error
    if (
        config.get("max_concurrent") != direct.MAX_DIRECT_CONCURRENCY
        or config.get("multiplex") != direct.MAX_DIRECT_CONCURRENCY
        or not direct._is_plain_int(config.get("num_rollouts"))
        or config.get("num_rollouts") != 1
        or config.get("shuffle", False) is not False
        or direct.provider_concurrency(config) != direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY
        or manifest["router"].get("max_concurrent_requests") != direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY
        or manifest["router"].get("queue_size")
        != direct.MAX_DIRECT_CONCURRENCY - direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY
    ):
        raise MigrationError("source_admission_contract_invalid")
    expected_url = f"http://127.0.0.1:{manifest['router']['port']}/v1"
    if str(config["client"].get("base_url", "")).rstrip("/") != expected_url:
        raise MigrationError("source_router_url_mismatch")
    if str(provenance.get("inference_base_url", "")).rstrip("/") != expected_url:
        raise MigrationError("source_provenance_url_mismatch")
    if provenance.get("inference_deployment_id"):
        raise MigrationError("source_provenance_deployment_id_present")
    for key in ("prime_rl", "verifiers", "renderers"):
        if re.fullmatch(r"[0-9a-f]{40}", provenance.get(key, "")) is None:
            raise MigrationError(f"source_provenance_{key}_invalid")
    if provenance["verifiers"] != EXPECTED_VERIFIERS_REVISION:
        raise MigrationError("source_verifiers_revision_mismatch")
    return manifest, provenance, config


def _rewrite_provenance_value(text: str, key: str, old: str, new: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}={re.escape(old)}$")
    rewritten, count = pattern.subn(f"{key}={new}", text)
    if count != 1:
        raise MigrationError(f"source_provenance_{key}_not_unique")
    return rewritten


def migrate(
    source_dir: Path,
    output_dir: Path,
    *,
    terminal_check: Callable[[str], bool] = slurm_job_is_terminal,
) -> dict[str, Any]:
    source = source_dir.resolve(strict=True)
    output_parent = output_dir.parent.resolve(strict=True)
    output = output_parent / output_dir.name
    if output.exists() or output.is_symlink():
        raise MigrationError("destination_exists")
    if output == source or output.is_relative_to(source):
        raise MigrationError("destination_overlaps_source")
    direct.reject_incomplete_migration(source)

    with _source_locks(source):
        job_ids = _provenance_job_ids(source / "provenance.txt")
        if any(not terminal_check(job_id) for job_id in job_ids):
            raise MigrationError("source_slurm_job_not_terminal")
        upgraded_manifest, provenance, config = _validate_source(source)
        num_tasks = config.get("num_tasks")
        if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
            raise MigrationError("source_num_tasks_invalid")
        source_hashes = {
            "config_sha256": _sha256(source / "config.toml"),
            "source_config_sha256": _sha256(source / "inputs" / "source_config.toml"),
            "inputs_manifest_sha256": _sha256(source / "inputs" / "manifest.json"),
            "provenance_sha256": _sha256(source / "provenance.txt"),
            "results_sha256": _sha256(source / "results.jsonl"),
            "direct_workers_sha256": _sha256(source / "direct_workers.json"),
        }
        source_results_size = (source / "results.jsonl").stat().st_size
        temporary: Path | None = Path(tempfile.mkdtemp(prefix=f".{output.name}.migrate-", dir=output_parent))
        try:
            assert temporary is not None
            _clone_tree(source, temporary)
            if _sha256(temporary / "results.jsonl") != source_hashes["results_sha256"]:
                raise MigrationError("copied_results_hash_mismatch")
            old_router_log = temporary / "direct_router.log"
            if old_router_log.exists():
                old_router_log.rename(temporary / "direct_router.epoch-1.log")
            _rewrite_child_paths(source, temporary, output)

            legacy_manifest_path = temporary / direct.ROUTING_EPOCH1_MANIFEST_FILENAME
            (temporary / "direct_workers.json").replace(legacy_manifest_path)
            active_manifest_path = temporary / "direct_workers.json"
            _atomic_write(active_manifest_path, _json_bytes(upgraded_manifest))
            direct.validate_saved_manifest(active_manifest_path)

            retained_temporary = temporary / ".results.retained.tmp"
            epoch1_rows_path = temporary / direct.ROUTING_EPOCH1_ROWS_FILENAME
            (
                retained_sha256,
                retained_size,
                retained_count,
                owed_count,
                epoch1_rows_sha256,
            ) = _plan_retained_results(
                source / "results.jsonl",
                retained_temporary,
                epoch1_rows_path,
                num_tasks,
            )
            if owed_count < 1:
                raise MigrationError("source_has_nothing_to_resume")
            retained_temporary.replace(temporary / "results.jsonl")

            transition = {
                "schema_version": 1,
                "kind": direct.ROUTING_TRANSITION_KIND,
                "source": {
                    "canonical_path": str(source),
                    "slurm_job_id": job_ids[-1],
                    "prime_rl": provenance["prime_rl"],
                    "verifiers": provenance["verifiers"],
                    "renderers": provenance["renderers"],
                    **source_hashes,
                    "results_size_bytes": source_results_size,
                },
                "resume_plan": {
                    "retained_results_sha256": retained_sha256,
                    "retained_results_size_bytes": retained_size,
                    "retained_row_count": retained_count,
                    "owed_rollout_count": owed_count,
                    "epoch1_row_hashes_sha256": epoch1_rows_sha256,
                },
                "from_router": {
                    "manifest_schema_version": 1,
                    "policy": "round_robin",
                    "request_id_headers": [],
                },
                "to_router": {
                    "manifest_schema_version": direct.AFFINITY_MANIFEST_SCHEMA_VERSION,
                    "policy": direct.ROUTER_POLICY,
                    "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
                    "spec_sha256": upgraded_manifest["spec_sha256"],
                    "endpoint_bundle_sha256": upgraded_manifest["endpoint_bundle_sha256"],
                    "direct_workers_sha256": _sha256(active_manifest_path),
                },
                "child": {
                    "canonical_path": str(output),
                    "routing_epoch": 2,
                    "config_sha256": _sha256(temporary / "config.toml"),
                    "source_config_sha256": _sha256(temporary / "inputs" / "source_config.toml"),
                    "inputs_manifest_sha256": _sha256(temporary / "inputs" / "manifest.json"),
                },
            }
            transition_path = temporary / direct.ROUTING_TRANSITION_FILENAME
            _atomic_write(transition_path, _json_bytes(transition))
            transition_sha256 = _sha256(transition_path)
            provenance_path = temporary / "provenance.txt"
            provenance_text = provenance_path.read_text(encoding="utf-8")
            if any(
                key in provenance
                for key in (
                    "direct_qwen_manifest_sha256",
                    "qwen_router_transition_sha256",
                    "qwen_router_epoch",
                )
            ):
                raise MigrationError("source_provenance_already_has_routing_epoch")
            provenance_text += (
                f"qwen_router_transition_sha256={transition_sha256}\n"
                "qwen_router_epoch=2\n"
                f"direct_qwen_manifest_sha256={transition['to_router']['direct_workers_sha256']}\n"
                f"direct_qwen_router_policy={direct.ROUTER_POLICY}\n"
                f"direct_qwen_request_id_headers={','.join(direct.ROUTER_REQUEST_ID_HEADERS)}\n"
            )
            _atomic_write(provenance_path, provenance_text.encode())

            def validate_published(path: Path, allow_incomplete: bool) -> None:
                published_manifest = direct.validate_saved_manifest(path / "direct_workers.json")
                child_provenance = direct.validate_router_provenance(
                    path / "provenance.txt",
                    transition["to_router"]["direct_workers_sha256"],
                )
                direct.validate_routing_transition(
                    path,
                    published_manifest,
                    child_provenance,
                    allow_incomplete=allow_incomplete,
                )

            _publish_directory(temporary, output, validate_published)
            if not temporary.exists():
                temporary = None
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)

    return {
        "ok": True,
        "source": str(source),
        "output": str(output),
        "retained_rows": retained_count,
        "owed_rollouts": owed_count,
        "retained_results_sha256": retained_sha256,
        "transition_sha256": transition_sha256,
        "router_policy": direct.ROUTER_POLICY,
        "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
    }


def migrate_admission(
    source_dir: Path,
    output_dir: Path,
    *,
    terminal_check: Callable[[str], bool] = slurm_job_is_terminal,
) -> dict[str, Any]:
    """Create routing epoch 3 with a 32-request provider admission bound."""
    source = source_dir.resolve(strict=True)
    output_parent = output_dir.parent.resolve(strict=True)
    output = output_parent / output_dir.name
    if output.exists() or output.is_symlink():
        raise MigrationError("destination_exists")
    if output == source or output.is_relative_to(source):
        raise MigrationError("destination_overlaps_source")
    direct.reject_incomplete_migration(source)

    with _source_locks(source):
        job_ids = _provenance_job_ids(source / "provenance.txt")
        if any(not terminal_check(job_id) for job_id in job_ids):
            raise MigrationError("source_slurm_job_not_terminal")
        source_manifest, provenance, config = _validate_admission_source(source)
        num_tasks = config.get("num_tasks")
        if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
            raise MigrationError("source_num_tasks_invalid")
        source_hashes = {
            "config_sha256": _sha256(source / "config.toml"),
            "source_config_sha256": _sha256(source / "inputs" / "source_config.toml"),
            "inputs_manifest_sha256": _sha256(source / "inputs" / "manifest.json"),
            "provenance_sha256": _sha256(source / "provenance.txt"),
            "results_sha256": _sha256(source / "results.jsonl"),
            "direct_workers_sha256": _sha256(source / "direct_workers.json"),
            "routing_transition_sha256": _sha256(source / direct.ROUTING_TRANSITION_FILENAME),
        }
        source_results_size = (source / "results.jsonl").stat().st_size
        temporary: Path | None = Path(tempfile.mkdtemp(prefix=f".{output.name}.migrate-", dir=output_parent))
        try:
            assert temporary is not None
            _clone_tree(source, temporary)
            if _sha256(temporary / "results.jsonl") != source_hashes["results_sha256"]:
                raise MigrationError("copied_results_hash_mismatch")

            epoch2_archives = (
                (temporary / "config.toml", temporary / direct.ROUTING_EPOCH2_CONFIG_FILENAME),
                (
                    temporary / "inputs" / "source_config.toml",
                    temporary / "inputs" / direct.ROUTING_EPOCH2_SOURCE_CONFIG_FILENAME,
                ),
                (
                    temporary / "inputs" / "manifest.json",
                    temporary / "inputs" / direct.ROUTING_EPOCH2_INPUTS_MANIFEST_FILENAME,
                ),
                (temporary / "provenance.txt", temporary / direct.ROUTING_EPOCH2_PROVENANCE_FILENAME),
            )
            for source_path, archive_path in epoch2_archives:
                _copy_file(source_path, archive_path)
            old_router_log = temporary / "direct_router.log"
            if old_router_log.exists():
                old_router_log.rename(temporary / "direct_router.epoch-2.log")
            stale_epoch_index = temporary / "qwen_router_epochs.jsonl"
            if stale_epoch_index.exists():
                stale_epoch_index.unlink()

            _rewrite_child_paths(
                source,
                temporary,
                output,
                archive_source_config_filename=None,
                provider_concurrency=(
                    direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY,
                    direct.PRODUCTION_PROVIDER_CONCURRENCY,
                ),
            )

            epoch2_manifest_path = temporary / direct.ROUTING_EPOCH2_MANIFEST_FILENAME
            (temporary / "direct_workers.json").replace(epoch2_manifest_path)
            target_manifest = copy.deepcopy(source_manifest)
            target_manifest["schema_version"] = direct.ROUTER_MANIFEST_SCHEMA_VERSION
            target_manifest["router"]["max_concurrent_requests"] = direct.PRODUCTION_PROVIDER_CONCURRENCY
            target_manifest["router"]["queue_size"] = (
                direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY
            )
            target_manifest["admission"] = {
                "schema_version": direct.ADMISSION_SCHEMA_VERSION,
                "rollout_concurrency": direct.MAX_DIRECT_CONCURRENCY,
                "client_max_connections": direct.PRODUCTION_PROVIDER_CONCURRENCY,
                "client_max_keepalive_connections": direct.PRODUCTION_PROVIDER_CONCURRENCY,
                "router_max_concurrent_requests": direct.PRODUCTION_PROVIDER_CONCURRENCY,
                "router_queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY,
            }
            active_manifest_path = temporary / "direct_workers.json"
            _atomic_write(active_manifest_path, _json_bytes(target_manifest))
            direct.validate_saved_manifest(active_manifest_path)

            retained_temporary = temporary / ".results.retained.tmp"
            epoch2_rows_path = temporary / direct.ROUTING_EPOCH2_ROWS_FILENAME
            epoch1_hashes = set(direct._read_epoch1_row_hashes(temporary / direct.ROUTING_EPOCH1_ROWS_FILENAME))
            resume_plan = _plan_retained_results_with_verifiers(
                source / "results.jsonl",
                retained_temporary,
                epoch2_rows_path,
                num_tasks,
                verifiers_revision=provenance["verifiers"],
                epoch1_hashes=epoch1_hashes,
            )
            if resume_plan["owed_rollout_count"] < 1:
                raise MigrationError("source_has_nothing_to_resume")
            retained_temporary.replace(temporary / "results.jsonl")

            transition = {
                "schema_version": 1,
                "kind": direct.ADMISSION_TRANSITION_KIND,
                "source": {
                    "canonical_path": str(source),
                    "slurm_job_id": job_ids[-1],
                    "prime_rl": provenance["prime_rl"],
                    "verifiers": provenance["verifiers"],
                    "renderers": provenance["renderers"],
                    **source_hashes,
                    "results_size_bytes": source_results_size,
                },
                "resume_plan": resume_plan,
                "from_router": {
                    "manifest_schema_version": direct.AFFINITY_MANIFEST_SCHEMA_VERSION,
                    "policy": direct.ROUTER_POLICY,
                    "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
                    "max_concurrent_requests": direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY,
                    "queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY,
                    "spec_sha256": source_manifest["spec_sha256"],
                    "endpoint_bundle_sha256": source_manifest["endpoint_bundle_sha256"],
                    "direct_workers_sha256": source_hashes["direct_workers_sha256"],
                },
                "to_router": {
                    "manifest_schema_version": direct.ROUTER_MANIFEST_SCHEMA_VERSION,
                    "policy": direct.ROUTER_POLICY,
                    "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
                    "max_concurrent_requests": direct.PRODUCTION_PROVIDER_CONCURRENCY,
                    "queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY,
                    "spec_sha256": target_manifest["spec_sha256"],
                    "endpoint_bundle_sha256": target_manifest["endpoint_bundle_sha256"],
                    "direct_workers_sha256": _sha256(active_manifest_path),
                },
                "child": {
                    "canonical_path": str(output),
                    "routing_epoch": 3,
                    "migration_prime_rl": _repository_revision(),
                    "config_sha256": _sha256(temporary / "config.toml"),
                    "source_config_sha256": _sha256(temporary / "inputs" / "source_config.toml"),
                    "inputs_manifest_sha256": _sha256(temporary / "inputs" / "manifest.json"),
                },
            }
            admission_path = temporary / direct.ADMISSION_TRANSITION_FILENAME
            _atomic_write(admission_path, _json_bytes(transition))
            admission_sha256 = _sha256(admission_path)

            provenance_path = temporary / "provenance.txt"
            provenance_text = provenance_path.read_text(encoding="utf-8")
            if "qwen_router_admission_transition_sha256" in provenance:
                raise MigrationError("source_provenance_already_has_admission_epoch")
            provenance_text = _rewrite_provenance_value(
                provenance_text,
                "direct_qwen_manifest_sha256",
                source_hashes["direct_workers_sha256"],
                transition["to_router"]["direct_workers_sha256"],
            )
            provenance_text = _rewrite_provenance_value(provenance_text, "qwen_router_epoch", "2", "3")
            provenance_text += f"direct_qwen_provider_concurrency={direct.PRODUCTION_PROVIDER_CONCURRENCY}\n"
            provenance_text += f"qwen_router_admission_transition_sha256={admission_sha256}\n"
            _atomic_write(provenance_path, provenance_text.encode())

            def validate_published(path: Path, allow_incomplete: bool) -> None:
                published_manifest = direct.validate_saved_manifest(path / "direct_workers.json")
                child_provenance = direct.validate_router_provenance(
                    path / "provenance.txt",
                    transition["to_router"]["direct_workers_sha256"],
                    direct.PRODUCTION_PROVIDER_CONCURRENCY,
                )
                direct.validate_routing_transition(
                    path,
                    published_manifest,
                    child_provenance,
                    allow_incomplete=allow_incomplete,
                )
                approved_sha256 = direct.validate_eval_config(
                    path / "config.toml",
                    allow_historical_retry_policy=True,
                )
                if approved_sha256 != published_manifest["approved_task_allowlist_sha256"]:
                    raise MigrationError("published_task_allowlist_mismatch")

            _publish_directory(temporary, output, validate_published)
            if not temporary.exists():
                temporary = None
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)

    return {
        "ok": True,
        "source": str(source),
        "output": str(output),
        "retained_rows": resume_plan["retained_row_count"],
        "owed_rollouts": resume_plan["owed_rollout_count"],
        "retained_results_sha256": resume_plan["retained_results_sha256"],
        "transition_sha256": admission_sha256,
        "routing_epoch": 3,
        "router_policy": direct.ROUTER_POLICY,
        "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
        "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
        "queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY,
    }


def label_routing_epochs(
    run_dir: Path,
    output_path: Path,
    *,
    repair_selection_manifest: Path | None = None,
    repair_selection_manifest_sha256: str | None = None,
    terminal_check: Callable[[str], bool] = slurm_job_is_terminal,
) -> dict[str, Any]:
    run = run_dir.resolve(strict=True)
    if output_path.is_symlink():
        raise MigrationError("epoch_index_symlink_forbidden")
    try:
        output_parent = output_path.parent.resolve(strict=True)
    except OSError as error:
        raise MigrationError("epoch_index_output_invalid") from error
    if not output_path.name:
        raise MigrationError("epoch_index_output_invalid")
    output = output_parent / output_path.name
    if output.is_relative_to(run):
        raise MigrationError("epoch_index_output_overlaps_source")
    if os.path.lexists(output):
        raise MigrationError("epoch_index_output_exists")
    direct.reject_incomplete_migration(run)
    with _source_locks(run):
        job_ids = _provenance_job_ids(run / "provenance.txt")
        if any(not terminal_check(job_id) for job_id in job_ids):
            raise MigrationError("run_slurm_job_not_terminal")
        manifest = direct.validate_saved_manifest(run / "direct_workers.json")
        provenance = direct._read_provenance(run / "provenance.txt")
        direct.validate_routing_transition(run, manifest, provenance)
        current_epoch = int(provenance.get("qwen_router_epoch", "1"))
        epoch1_hashes = set(direct._read_epoch1_row_hashes(run / direct.ROUTING_EPOCH1_ROWS_FILENAME))
        epoch2_lineage = (
            direct._read_epoch2_lineage(run / direct.ROUTING_EPOCH2_ROWS_FILENAME) if current_epoch >= 3 else []
        )
        epoch2_hashes = {record["row_sha256"] for record in epoch2_lineage}
        results_path = run / "results.jsonl"
        results_sha256 = _sha256(results_path)
        allow_incomplete_final_fragment = _repair_selection_allows_incomplete_tail(
            repair_selection_manifest,
            repair_selection_manifest_sha256,
            results_path,
        )
        records: list[dict[str, Any]] = []
        counts = {epoch: 0 for epoch in range(1, current_epoch + 1)}
        ignored_incomplete_tail = False
        with results_path.open("rb") as results:
            for row_number, raw in enumerate(results):
                try:
                    json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    if allow_incomplete_final_fragment and not raw.endswith(b"\n"):
                        ignored_incomplete_tail = True
                        break
                    if not raw.endswith(b"\n"):
                        raise MigrationError("results_has_incomplete_tail") from error
                    raise MigrationError("results_invalid_complete_row") from error
                digest = hashlib.sha256(raw).hexdigest()
                if digest in epoch1_hashes:
                    epoch = 1
                elif digest in epoch2_hashes:
                    epoch = 2
                else:
                    epoch = current_epoch
                counts[epoch] += 1
                records.append(
                    {
                        "row": row_number,
                        "row_sha256": digest,
                        "routing_epoch": epoch,
                    }
                )
        transition_sha256 = _sha256(run / direct.ROUTING_TRANSITION_FILENAME)
        header = {
            "schema_version": 1,
            "kind": "qwen-routing-epoch-index",
            "results_sha256": results_sha256,
            "transition_sha256": transition_sha256,
            "admission_transition_sha256": (
                _sha256(run / direct.ADMISSION_TRANSITION_FILENAME) if current_epoch >= 3 else None
            ),
            "routing_epoch": current_epoch,
            "row_count": len(records),
        }
        payload = (json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n").encode() + b"".join(
            (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode() for record in records
        )
        _atomic_write(output, payload, exclusive=True)
        _fsync_directory(output_parent)
    summary = {
        "ok": True,
        "results_sha256": results_sha256,
        "rows": len(records),
        "ignored_incomplete_tail": ignored_incomplete_tail,
        "index_sha256": _sha256(output),
    }
    summary.update({f"epoch_{epoch}_rows": count for epoch, count in counts.items()})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--source-dir", type=Path, required=True)
    migrate_parser.add_argument("--output-dir", type=Path, required=True)
    admission_parser = subparsers.add_parser("migrate-admission")
    admission_parser.add_argument("--source-dir", type=Path, required=True)
    admission_parser.add_argument("--output-dir", type=Path, required=True)
    label_parser = subparsers.add_parser("label")
    label_parser.add_argument("--run-dir", type=Path, required=True)
    label_parser.add_argument("--output", type=Path, required=True)
    label_parser.add_argument("--repair-selection-manifest", type=Path)
    label_parser.add_argument("--repair-selection-manifest-sha256")
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            summary = migrate(args.source_dir, args.output_dir)
        elif args.command == "migrate-admission":
            summary = migrate_admission(args.source_dir, args.output_dir)
        else:
            summary = label_routing_epochs(
                args.run_dir,
                args.output,
                repair_selection_manifest=args.repair_selection_manifest,
                repair_selection_manifest_sha256=args.repair_selection_manifest_sha256,
            )
    except (OSError, MigrationError, direct.DirectWorkerError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
