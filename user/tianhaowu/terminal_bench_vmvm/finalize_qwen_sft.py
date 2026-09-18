#!/usr/bin/env python3
"""Finalize one terminal Qwen routing-epoch-3 run as a text SFT dataset.

The finalizer emits only aggregate counts, hashes, and stable error codes. Child
process output is never forwarded, so task identifiers, trace bodies, prompts,
tool payloads, and provider responses cannot enter the scheduler log.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import direct_qwen_workers as direct
import migrate_qwen_router_affinity as migration

INDEX_FILENAME = "qwen_router_epochs.jsonl"
MAX_CHILD_OUTPUT_BYTES = 1 << 20
MAX_PROVENANCE_BYTES = 1 << 20
MAX_SEQUENCE_TOKENS = 262_144
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REQUIRED_RUNTIME_SUBMODULES = (
    "deps/pydantic-config",
    "deps/renderers",
    "deps/verifiers",
)

Selection = Literal["pass-only", "all-outcomes"]


class FinalizationError(RuntimeError):
    """A fail-closed finalization error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise FinalizationError("arguments_invalid")


@dataclass(frozen=True)
class FinalizeOptions:
    project_dir: Path
    expected_project_revision: str
    source_root: Path
    source_dir: Path
    expected_provenance_sha256: str
    output_root: Path
    output_dir: Path
    expected_count: int
    selection: Selection
    validation_permyriad: int
    split_salt: str


@dataclass(frozen=True)
class ResolvedPaths:
    project_dir: Path
    source_root: Path
    source_dir: Path
    results: Path
    provenance: Path
    output_root: Path
    output_dir: Path


RepositoryValidator = Callable[[Path, str], Path]
SourceAuditor = Callable[[Path, int, str], dict[str, Any]]
CommandRunner = Callable[[list[str], Path, str], dict[str, Any]]


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_normalized_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(path))


def _canonical_existing_directory(path: Path, code: str) -> Path:
    if not _is_normalized_absolute(path):
        raise FinalizationError(code)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise FinalizationError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise FinalizationError(code)
    return resolved


def _unsafe_boundary(path: Path) -> bool:
    if path == Path(path.anchor) or len(path.parts) < 5:
        return True
    try:
        home = Path.home().resolve(strict=True)
    except OSError:
        return True
    return path == home or home.is_relative_to(path)


def _strict_descendant(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _regular_file(path: Path, code: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise FinalizationError(code) from error
    if not stat.S_ISREG(metadata.st_mode) or path.resolve(strict=True) != path:
        raise FinalizationError(code)
    return path


def _resolve_paths(options: FinalizeOptions) -> ResolvedPaths:
    project = _canonical_existing_directory(options.project_dir, "project_path_unsafe")
    source_root = _canonical_existing_directory(options.source_root, "source_root_unsafe")
    output_root = _canonical_existing_directory(options.output_root, "output_root_unsafe")
    if _unsafe_boundary(source_root) or _unsafe_boundary(output_root):
        raise FinalizationError("path_boundary_unsafe")
    if _paths_overlap(source_root, output_root):
        raise FinalizationError("path_boundaries_overlap")

    source = _canonical_existing_directory(options.source_dir, "source_path_unsafe")
    if not _strict_descendant(source, source_root):
        raise FinalizationError("source_outside_boundary")

    output = options.output_dir
    if not _is_normalized_absolute(output) or not output.name or os.path.lexists(output):
        raise FinalizationError("output_path_unsafe")
    output_parent = _canonical_existing_directory(output.parent, "output_parent_unsafe")
    if output != output_parent / output.name or not _strict_descendant(output, output_root):
        raise FinalizationError("output_outside_boundary")
    if _paths_overlap(project, source) or _paths_overlap(project, output):
        raise FinalizationError("runtime_path_overlaps_project")
    if _paths_overlap(source, output):
        raise FinalizationError("output_overlaps_source")

    results = _regular_file(source / "results.jsonl", "source_results_invalid")
    provenance = _regular_file(source / "provenance.txt", "source_provenance_invalid")
    _regular_file(source / "config.toml", "source_config_invalid")
    return ResolvedPaths(
        project_dir=project,
        source_root=source_root,
        source_dir=source,
        results=results,
        provenance=provenance,
        output_root=output_root,
        output_dir=output,
    )


def _run_git(project_dir: Path, arguments: list[str], code: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_dir), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise FinalizationError(code) from error
    if len(completed.stdout.encode()) > MAX_CHILD_OUTPUT_BYTES or completed.stderr:
        raise FinalizationError(code)
    return completed.stdout


def _validate_repository(
    project_dir: Path,
    expected_revision: str,
    *,
    required_submodules: tuple[str, ...] = REQUIRED_RUNTIME_SUBMODULES,
) -> Path:
    if GIT_SHA_PATTERN.fullmatch(expected_revision) is None:
        raise FinalizationError("project_revision_invalid")
    project = _canonical_existing_directory(project_dir, "project_path_unsafe")
    top_level = _run_git(project, ["rev-parse", "--show-toplevel"], "project_revision_unavailable").strip()
    head = _run_git(project, ["rev-parse", "HEAD"], "project_revision_unavailable").strip()
    head_name = _run_git(
        project,
        ["rev-parse", "--abbrev-ref", "HEAD"],
        "project_revision_unavailable",
    ).strip()
    if top_level != str(project) or head != expected_revision:
        raise FinalizationError("project_revision_mismatch")
    if head_name != "HEAD":
        raise FinalizationError("project_not_detached")
    status = _run_git(
        project,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        "project_status_unavailable",
    )
    if status:
        raise FinalizationError("project_not_clean")
    for relative in required_submodules:
        tree_record = _run_git(
            project,
            ["ls-tree", expected_revision, "--", relative],
            "project_submodules_unavailable",
        ).strip()
        fields = tree_record.split(maxsplit=3)
        if (
            len(fields) != 4
            or fields[0] != "160000"
            or fields[1] != "commit"
            or GIT_SHA_PATTERN.fullmatch(fields[2]) is None
            or fields[3] != relative
        ):
            raise FinalizationError("project_submodule_mismatch")
        submodule = project / relative
        observed = _run_git(submodule, ["rev-parse", "HEAD"], "project_submodules_unavailable").strip()
        submodule_status = _run_git(
            submodule,
            ["status", "--porcelain=v1", "--untracked-files=all"],
            "project_submodules_unavailable",
        )
        if observed != fields[2] or submodule_status:
            raise FinalizationError("project_submodule_mismatch")
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    _regular_file(workflow / "finalize_qwen_sft.py", "project_finalizer_invalid")
    _regular_file(workflow / "migrate_qwen_router_affinity.py", "project_labeler_invalid")
    _regular_file(workflow / "export_sft.py", "project_exporter_invalid")
    return project


def _stable_sha256(path: Path, *, max_bytes: int | None = None) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise FinalizationError("source_artifact_unreadable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise FinalizationError("source_artifact_invalid")
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, 1 << 20):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise FinalizationError("source_artifact_too_large")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after):
        raise FinalizationError("source_artifact_changed")
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_output(staged: Path, destination: Path) -> None:
    if os.path.lexists(destination):
        raise FinalizationError("output_already_exists")
    try:
        staged_metadata = staged.lstat()
    except OSError as error:
        raise FinalizationError("output_publish_failed") from error
    if not stat.S_ISDIR(staged_metadata.st_mode):
        raise FinalizationError("output_publish_failed")
    try:
        migration._rename_noreplace(staged, destination)
    except migration.MigrationError as error:
        code = "output_already_exists" if str(error) == "destination_exists" else "output_publish_failed"
        raise FinalizationError(code) from error
    except OSError as error:
        raise FinalizationError("output_publish_failed") from error
    try:
        _fsync_directory(destination.parent)
    except OSError as error:
        try:
            destination_metadata = destination.lstat()
            if stat.S_ISDIR(destination_metadata.st_mode) and (
                destination_metadata.st_dev,
                destination_metadata.st_ino,
            ) == (staged_metadata.st_dev, staged_metadata.st_ino):
                shutil.rmtree(destination)
                _fsync_directory(destination.parent)
        except OSError:
            pass
        raise FinalizationError("output_publish_failed") from error


def _source_locks_available(source_dir: Path) -> None:
    descriptors: list[int] = []
    try:
        for filename in (".direct_router.lock", ".writer.lock"):
            path = source_dir / filename
            flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags)
            except OSError as error:
                raise FinalizationError("source_lock_invalid") from error
            descriptors.append(descriptor)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise FinalizationError("source_lock_invalid")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise FinalizationError("source_run_active") from error
    finally:
        for descriptor in reversed(descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _audit_source(source_dir: Path, expected_count: int, expected_provenance_sha256: str) -> dict[str, Any]:
    if SHA256_PATTERN.fullmatch(expected_provenance_sha256) is None:
        raise FinalizationError("expected_provenance_digest_invalid")
    provenance = source_dir / "provenance.txt"
    if _stable_sha256(provenance, max_bytes=MAX_PROVENANCE_BYTES) != expected_provenance_sha256:
        raise FinalizationError("source_provenance_digest_mismatch")
    try:
        config = tomllib.loads((source_dir / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise FinalizationError("source_config_invalid") from error
    if config.get("num_tasks") != expected_count or config.get("num_rollouts") != 1:
        raise FinalizationError("source_expected_count_mismatch")
    try:
        summary = direct.audit_run_directory(source_dir)
    except (OSError, ValueError, direct.DirectWorkerError) as error:
        raise FinalizationError("source_routing_provenance_invalid") from error
    if (
        summary.get("routing_epoch") != 3
        or summary.get("manifest_schema_version") != direct.ROUTER_MANIFEST_SCHEMA_VERSION
        or summary.get("router_policy") != direct.ROUTER_POLICY
        or summary.get("request_id_headers") != list(direct.ROUTER_REQUEST_ID_HEADERS)
        or summary.get("provider_concurrency") != direct.PRODUCTION_PROVIDER_CONCURRENCY
    ):
        raise FinalizationError("source_not_routing_epoch_3")
    if _stable_sha256(provenance, max_bytes=MAX_PROVENANCE_BYTES) != expected_provenance_sha256:
        raise FinalizationError("source_provenance_changed")
    return summary


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    if not body or len(body) > MAX_CHILD_OUTPUT_BYTES:
        raise FinalizationError(code)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise FinalizationError(code) from error
    if not isinstance(value, dict):
        raise FinalizationError(code)
    return value


def _run_json_command(command: list[str], cwd: Path, code: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise FinalizationError(code) from error
    if completed.returncode != 0 or completed.stderr or len(completed.stdout) > MAX_CHILD_OUTPUT_BYTES:
        raise FinalizationError(code)
    return _parse_json_object(completed.stdout, code)


def _validate_label_summary(summary: Mapping[str, Any], index: Path, expected_count: int) -> dict[str, int]:
    expected_keys = {
        "ok",
        "results_sha256",
        "rows",
        "index_sha256",
        "epoch_1_rows",
        "epoch_2_rows",
        "epoch_3_rows",
    }
    if set(summary) != expected_keys or summary.get("ok") is not True:
        raise FinalizationError("routing_index_summary_invalid")
    counts = {f"epoch_{epoch}": summary.get(f"epoch_{epoch}_rows") for epoch in range(1, 4)}
    if (
        not all(_is_plain_int(value) and value >= 0 for value in counts.values())
        or not _is_plain_int(summary.get("rows"))
        or summary["rows"] != expected_count
        or sum(counts.values()) != expected_count
        or counts["epoch_3"] < 1
        or SHA256_PATTERN.fullmatch(str(summary.get("results_sha256"))) is None
        or SHA256_PATTERN.fullmatch(str(summary.get("index_sha256"))) is None
    ):
        raise FinalizationError("routing_index_summary_invalid")
    _regular_file(index, "routing_index_invalid")
    if _stable_sha256(index) != summary["index_sha256"]:
        raise FinalizationError("routing_index_digest_mismatch")
    return counts


def _validate_export_summary(
    summary: Mapping[str, Any],
    output_dir: Path,
    expected_count: int,
    selection: Selection,
    expected_index_sha256: str,
) -> None:
    expected_keys = {
        "excluded_error_traces",
        "input_traces",
        "output_sha256",
        "rows",
        "routing_epoch_rows",
        "selected_traces",
        "selection",
        "status",
    }
    if set(summary) != expected_keys or summary.get("status") != "exported" or summary.get("selection") != selection:
        raise FinalizationError("sft_export_summary_invalid")
    count_keys = ("excluded_error_traces", "input_traces", "selected_traces")
    if not all(_is_plain_int(summary.get(key)) and summary[key] >= 0 for key in count_keys):
        raise FinalizationError("sft_export_summary_invalid")
    if summary["input_traces"] != expected_count or summary["selected_traces"] > expected_count:
        raise FinalizationError("sft_export_summary_invalid")
    rows = summary.get("rows")
    if (
        not isinstance(rows, dict)
        or set(rows) != {"total", "train", "validation"}
        or not all(_is_plain_int(value) and value >= 0 for value in rows.values())
        or rows["total"] != rows["train"] + rows["validation"]
    ):
        raise FinalizationError("sft_export_summary_invalid")
    routing_rows = summary.get("routing_epoch_rows")
    if (
        not isinstance(routing_rows, dict)
        or set(routing_rows) != {"1", "2", "3"}
        or not all(_is_plain_int(value) and value >= 0 for value in routing_rows.values())
        or sum(routing_rows.values()) != rows["total"]
    ):
        raise FinalizationError("sft_export_summary_invalid")
    output_hashes = summary.get("output_sha256")
    if (
        not isinstance(output_hashes, dict)
        or set(output_hashes) != {"manifest", "routing_epoch_index", "train", "validation"}
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in output_hashes.values())
        or output_hashes["routing_epoch_index"] != expected_index_sha256
    ):
        raise FinalizationError("sft_export_summary_invalid")
    published = _canonical_existing_directory(output_dir, "sft_output_invalid")
    manifest = _regular_file(published / "manifest.json", "sft_output_invalid")
    train = _regular_file(published / "train" / "train.jsonl", "sft_output_invalid")
    validation = _regular_file(published / "validation" / "train.jsonl", "sft_output_invalid")
    routing_index = _regular_file(published / INDEX_FILENAME, "sft_output_invalid")
    routing_index_sha256 = _stable_sha256(routing_index)
    if (
        _stable_sha256(manifest) != output_hashes["manifest"]
        or _stable_sha256(train) != output_hashes["train"]
        or _stable_sha256(validation) != output_hashes["validation"]
        or routing_index_sha256 != output_hashes["routing_epoch_index"]
    ):
        raise FinalizationError("sft_output_digest_mismatch")
    try:
        manifest_body = manifest.read_bytes()
    except OSError as error:
        raise FinalizationError("sft_output_invalid") from error
    if hashlib.sha256(manifest_body).hexdigest() != output_hashes["manifest"]:
        raise FinalizationError("sft_output_digest_mismatch")
    manifest_value = _parse_json_object(manifest_body, "sft_output_invalid")
    artifacts = manifest_value.get("artifacts")
    routing_artifact = artifacts.get(INDEX_FILENAME) if isinstance(artifacts, dict) else None
    if routing_artifact != {"bytes": routing_index.stat().st_size, "sha256": routing_index_sha256}:
        raise FinalizationError("sft_output_digest_mismatch")


def _validate_options(options: FinalizeOptions) -> None:
    if platform.machine() != "x86_64":
        raise FinalizationError("x86_64_required")
    if not _is_plain_int(options.expected_count) or options.expected_count < 1:
        raise FinalizationError("expected_count_invalid")
    if options.selection not in {"pass-only", "all-outcomes"}:
        raise FinalizationError("selection_invalid")
    if not _is_plain_int(options.validation_permyriad) or not 0 <= options.validation_permyriad < 10_000:
        raise FinalizationError("validation_permyriad_invalid")
    if not options.split_salt or "\x00" in options.split_salt:
        raise FinalizationError("split_salt_invalid")


def finalize_qwen_sft(
    options: FinalizeOptions,
    *,
    repository_validator: RepositoryValidator = _validate_repository,
    source_auditor: SourceAuditor = _audit_source,
    command_runner: CommandRunner = _run_json_command,
) -> dict[str, Any]:
    """Create an external routing index, then export SFT with that exact index."""
    _validate_options(options)
    project = repository_validator(options.project_dir, options.expected_project_revision)
    paths = _resolve_paths(options)
    if paths.project_dir != project:
        raise FinalizationError("project_path_mismatch")
    _source_locks_available(paths.source_dir)
    source_auditor(
        paths.source_dir,
        options.expected_count,
        options.expected_provenance_sha256,
    )
    repository_validator(paths.project_dir, options.expected_project_revision)

    workflow = paths.project_dir / "user" / "tianhaowu" / "terminal_bench_vmvm"
    with tempfile.TemporaryDirectory(
        prefix=f".{paths.output_dir.name}.finalize-",
        dir=paths.output_dir.parent,
    ) as staging:
        staging_dir = Path(staging)
        index = staging_dir / INDEX_FILENAME
        staged_output = staging_dir / "dataset"
        label_summary = command_runner(
            [
                sys.executable,
                str(workflow / "migrate_qwen_router_affinity.py"),
                "label",
                "--run-dir",
                str(paths.source_dir),
                "--output",
                str(index),
            ],
            paths.project_dir,
            "routing_index_failed",
        )
        epoch_input_rows = _validate_label_summary(label_summary, index, options.expected_count)
        repository_validator(paths.project_dir, options.expected_project_revision)
        if _stable_sha256(paths.provenance, max_bytes=MAX_PROVENANCE_BYTES) != options.expected_provenance_sha256:
            raise FinalizationError("source_provenance_changed")

        export_summary = command_runner(
            [
                sys.executable,
                str(workflow / "export_sft.py"),
                str(paths.results),
                "--output-dir",
                str(staged_output),
                "--selection",
                options.selection,
                "--expected-count",
                str(options.expected_count),
                "--validation-permyriad",
                str(options.validation_permyriad),
                "--split-salt",
                options.split_salt,
                "--max-sequence-tokens",
                str(MAX_SEQUENCE_TOKENS),
                "--routing-epoch-index",
                str(index),
            ],
            paths.project_dir,
            "sft_export_failed",
        )
        _validate_export_summary(
            export_summary,
            staged_output,
            options.expected_count,
            options.selection,
            label_summary["index_sha256"],
        )
        repository_validator(paths.project_dir, options.expected_project_revision)
        if _stable_sha256(paths.provenance, max_bytes=MAX_PROVENANCE_BYTES) != options.expected_provenance_sha256:
            raise FinalizationError("source_provenance_changed")
        _publish_output(staged_output, paths.output_dir)

    return {
        "excluded_error_traces": export_summary["excluded_error_traces"],
        "input_traces": export_summary["input_traces"],
        "output_sha256": export_summary["output_sha256"],
        "routing_epoch_input_traces": epoch_input_rows,
        "routing_epoch_rows": export_summary["routing_epoch_rows"],
        "rows": export_summary["rows"],
        "selected_traces": export_summary["selected_traces"],
        "selection": options.selection,
        "status": "finalized",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected-provenance-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--selection", choices=("pass-only", "all-outcomes"), required=True)
    parser.add_argument("--validation-permyriad", type=int, required=True)
    parser.add_argument("--split-salt", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        options = FinalizeOptions(
            project_dir=args.project_dir,
            expected_project_revision=args.expected_project_revision,
            source_root=args.source_root,
            source_dir=args.source_dir,
            expected_provenance_sha256=args.expected_provenance_sha256,
            output_root=args.output_root,
            output_dir=args.output_dir,
            expected_count=args.expected_count,
            selection=args.selection,
            validation_permyriad=args.validation_permyriad,
            split_salt=args.split_salt,
        )
        summary = finalize_qwen_sft(options)
    except FinalizationError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
