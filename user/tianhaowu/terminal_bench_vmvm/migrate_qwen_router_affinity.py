#!/usr/bin/env python3
"""Copy-on-write migration of a terminal Qwen round-robin eval to sticky routing."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
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


class MigrationError(ValueError):
    """The source run cannot be safely migrated."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
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
    try:
        _rename_noreplace(source, destination)
    except OSError as error:
        if error.errno not in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV}:
            raise
        _publish_with_incomplete_marker(source, destination, validate)
        return
    try:
        validate(destination, False)
        _fsync_directory(destination)
        _fsync_directory(destination.parent)
    except Exception:
        with contextlib.suppress(OSError):
            shutil.rmtree(destination)
        raise


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


def _rewrite_child_paths(source: Path, storage: Path, child: Path) -> None:
    config_path = storage / "config.toml"
    source_config_path = storage / "inputs" / "source_config.toml"
    epoch1_source_config_path = storage / "inputs" / direct.ROUTING_EPOCH1_SOURCE_CONFIG_FILENAME
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
    _copy_file(source_config_path, epoch1_source_config_path)

    for key, filename in (("task_file", "task_file.txt"), ("image_manifest", "image_manifest.json")):
        saved_value = taskset.get(key)
        source_value = source_taskset.get(key)
        record = inputs_manifest.get(key)
        if saved_value is None and source_value is None and key == "image_manifest":
            continue
        if not isinstance(record, dict) or set(record) != {"source", "snapshot", "sha256"}:
            raise MigrationError(f"source_inputs_{key}_record_invalid")
        expected_snapshot = source / "inputs" / filename
        if (
            not isinstance(saved_value, str)
            or Path(saved_value).resolve() != expected_snapshot.resolve()
            or not isinstance(source_value, str)
            or not isinstance(record.get("source"), str)
            or not _declared_source_matches_record(source_value, record["source"])
            or Path(str(record.get("snapshot", ""))).resolve() != expected_snapshot.resolve()
        ):
            raise MigrationError(f"source_config_{key}_path_mismatch")
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
    _atomic_write(config_path, config_text.encode())
    _atomic_write(source_config_path, source_config_text.encode())
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


def _validate_source(source: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    for relative in REQUIRED_SOURCE_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise MigrationError(f"source_file_missing_or_symlink:{relative}")
    legacy_manifest = _read_json_object(source / "direct_workers.json")
    upgraded_manifest = direct.upgrade_legacy_manifest(legacy_manifest)
    config_path = source / "config.toml"
    task_allowlist_sha256 = direct.validate_eval_config(config_path)
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
                    "manifest_schema_version": direct.ROUTER_MANIFEST_SCHEMA_VERSION,
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
            if temporary is not None:
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


def label_routing_epochs(
    run_dir: Path,
    output_path: Path,
    *,
    terminal_check: Callable[[str], bool] = slurm_job_is_terminal,
) -> dict[str, Any]:
    run = run_dir.resolve(strict=True)
    output = output_path.resolve(strict=False)
    if output.parent != run:
        raise MigrationError("epoch_index_must_be_inside_run")
    if output.is_symlink():
        raise MigrationError("epoch_index_symlink_forbidden")
    direct.reject_incomplete_migration(run)
    with _source_locks(run):
        job_ids = _provenance_job_ids(run / "provenance.txt")
        if any(not terminal_check(job_id) for job_id in job_ids):
            raise MigrationError("run_slurm_job_not_terminal")
        manifest = direct.validate_saved_manifest(run / "direct_workers.json")
        provenance = direct._read_provenance(run / "provenance.txt")
        direct.validate_routing_transition(run, manifest, provenance)
        epoch1_hashes = set(direct._read_epoch1_row_hashes(run / direct.ROUTING_EPOCH1_ROWS_FILENAME))
        results_path = run / "results.jsonl"
        results_sha256 = _sha256(results_path)
        records: list[dict[str, Any]] = []
        counts = {1: 0, 2: 0}
        with results_path.open("rb") as results:
            for row_number, raw in enumerate(results):
                if not raw.endswith(b"\n"):
                    raise MigrationError("results_has_incomplete_tail")
                digest = hashlib.sha256(raw).hexdigest()
                epoch = 1 if digest in epoch1_hashes else 2
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
            "row_count": len(records),
        }
        payload = (json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n").encode() + b"".join(
            (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode() for record in records
        )
        _atomic_write(output, payload)
    return {
        "ok": True,
        "results_sha256": results_sha256,
        "rows": len(records),
        "epoch_1_rows": counts[1],
        "epoch_2_rows": counts[2],
        "index_sha256": _sha256(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--source-dir", type=Path, required=True)
    migrate_parser.add_argument("--output-dir", type=Path, required=True)
    label_parser = subparsers.add_parser("label")
    label_parser.add_argument("--run-dir", type=Path, required=True)
    label_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            summary = migrate(args.source_dir, args.output_dir)
        else:
            output = args.output or args.run_dir / "qwen_router_epochs.jsonl"
            summary = label_routing_epochs(args.run_dir, output)
    except (OSError, MigrationError, direct.DirectWorkerError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
