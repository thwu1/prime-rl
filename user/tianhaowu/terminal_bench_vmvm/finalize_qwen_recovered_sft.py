#!/usr/bin/env python3
"""Create a pass-only format-v3 SFT export from the certified Qwen v6 union.

The recovered results and their certificate chain are immutable inputs.  The
only published output is a new private directory.  Process output is limited
to aggregate counts, digests, and stable error codes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import export_sft as exporter
import finalize_qwen_sft as common
import migrate_qwen_router_affinity as migration

SCHEMA_VERSION = 1
EXPORT_KIND = "qwen-recovered-union-pass-only-sft"
RECEIPT_KIND = "qwen-recovered-union-sft-omission-receipt"
RECEIPT_FILENAME = "recovered-union-omission-receipt.json"
PACKAGE_KIND = "qwen-2499-recovered-unfiltered-trajectory-package"
RECOVERED_KIND = "qwen-2499-error-retry-recovered-results"
MERGE_KIND = "qwen-2499-error-retry-recovered-results-manifest"
RETRY_KIND = "qwen-2499-exact-error-retry-run"
SUPERSEDING_KIND = "qwen-2499-error-retry-superseding-certificate"
POSTRUN_KIND = "qwen-2499-unfiltered-recovered-results-postrun"
RESULTS_FILENAME = "results.jsonl"
MERGE_FILENAME = "merge_manifest.json"
RECOVERED_CERTIFICATE_FILENAME = "qwen_2499_recovered_results_certificate.json"
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_JSONL_ROW_BYTES = 128 * 1024 * 1024
SET_COMMITMENT_ALGORITHM = "sha256-sorted-row-sha256-lines-v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PINNED_PACKAGE_MANIFEST_SHA256 = "c66c279e7cdc7fce30c07f7378d8dc37ce409f6b5d3f764cc15f74119c58f5d9"
PINNED_RESULTS_SHA256 = "6ecc98adc68b8cad0ba15f160c108e64fe69da89321cd179bbb2dd1a78dd7d31"
PINNED_MERGE_MANIFEST_SHA256 = "979093d477b46aa1fd4ec098bc1fdce042d9e98cf5bcfc9353e66f4fd7b8f0f1"
PINNED_RECOVERED_CERTIFICATE_SHA256 = "b4732854e7fa8d7d1f5b7772a8a2f1b6708bfd2bccffe5a16f0d50b850e8c228"
PINNED_RETRY_CERTIFICATE_SHA256 = "1ce10c6cc6815866acfa1d8a0474eaca919030d466eea0d28e2c2ff428656b75"
PINNED_SUPERSEDING_CERTIFICATE_SHA256 = "025474d6384c5ccbae9159f064c252d9664849a7a1e8f258917c51a7f8366798"
PINNED_POSTRUN_RECEIPT_SHA256 = "950f3713806a54576fac28b9557dc697d385be18f0eb95c37d30a43a20d2fd3b"
PINNED_CANONICAL_TASK_FILE_SHA256 = "5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c"
PINNED_TASKSET_ID = "terminal-bench-vmvm"
PINNED_DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
PINNED_SPLIT_SALT = "terminal-bench-vmvm-sft-v1"
PINNED_VALIDATION_PERMYRIAD = 500
PINNED_COUNTS = {
    "error": 24,
    "input": 2_499,
    "positive": 1_588,
    "selected_positive": 1_588,
    "strict_failures": 279,
    "zero": 887,
}


class RecoveredSFTError(RuntimeError):
    """A fail-closed error represented by a non-sensitive stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise RecoveredSFTError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class RecoveredSFTOptions:
    project_dir: Path
    expected_project_revision: str
    expected_finalizer_sha256: str
    package_manifest: Path
    expected_package_manifest_sha256: str
    source_dir: Path
    expected_results_sha256: str
    expected_merge_manifest_sha256: str
    expected_recovered_certificate_sha256: str
    retry_certificate: Path
    expected_retry_certificate_sha256: str
    superseding_certificate: Path
    expected_superseding_certificate_sha256: str
    postrun_receipt: Path
    expected_postrun_receipt_sha256: str
    canonical_task_file: Path
    expected_canonical_task_file_sha256: str
    taskset_id: str
    dataset_revision: str
    output_root: Path
    output_dir: Path
    expected_count: int
    expected_positive: int
    expected_zero: int
    expected_error: int
    expected_selected_positive: int
    expected_strict_failures: int
    validation_permyriad: int
    split_salt: str


@dataclass(frozen=True, slots=True)
class PinnedJSON:
    path: Path
    artifact: exporter.FileArtifact
    value: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LineageBinding:
    package: PinnedJSON
    merge: PinnedJSON
    recovered: PinnedJSON
    retry: PinnedJSON
    superseding: PinnedJSON
    postrun: PinnedJSON
    results: Path
    results_artifact: exporter.FileArtifact
    task_file: Path
    task_file_artifact: exporter.FileArtifact
    task_file_body: bytes
    outcomes: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ArchiveBinding:
    archive: exporter.FileArtifact
    sha256sums_path: Path
    sha256sums: exporter.FileArtifact
    chunks: tuple[tuple[Path, exporter.FileArtifact], ...]


RepositoryValidator = Callable[[Path, str, str], Mapping[str, Any]]
TraceValidator = Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]]
ArchiveValidator = Callable[[PinnedJSON, Path], ArchiveBinding]
IdentityValidator = Callable[[RecoveredSFTOptions], None]


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _valid_git_sha(value: object) -> bool:
    return isinstance(value, str) and common.GIT_SHA_PATTERN.fullmatch(value) is not None


def _validate_production_identity(options: RecoveredSFTOptions) -> None:
    observed = {
        "canonical_task_file_sha256": options.expected_canonical_task_file_sha256,
        "dataset_revision": options.dataset_revision,
        "error": options.expected_error,
        "input": options.expected_count,
        "merge_manifest_sha256": options.expected_merge_manifest_sha256,
        "package_manifest_sha256": options.expected_package_manifest_sha256,
        "positive": options.expected_positive,
        "postrun_receipt_sha256": options.expected_postrun_receipt_sha256,
        "recovered_certificate_sha256": options.expected_recovered_certificate_sha256,
        "results_sha256": options.expected_results_sha256,
        "retry_certificate_sha256": options.expected_retry_certificate_sha256,
        "selected_positive": options.expected_selected_positive,
        "split_salt": options.split_salt,
        "strict_failures": options.expected_strict_failures,
        "superseding_certificate_sha256": options.expected_superseding_certificate_sha256,
        "taskset_id": options.taskset_id,
        "validation_permyriad": options.validation_permyriad,
        "zero": options.expected_zero,
    }
    expected = {
        "canonical_task_file_sha256": PINNED_CANONICAL_TASK_FILE_SHA256,
        "dataset_revision": PINNED_DATASET_REVISION,
        "error": PINNED_COUNTS["error"],
        "input": PINNED_COUNTS["input"],
        "merge_manifest_sha256": PINNED_MERGE_MANIFEST_SHA256,
        "package_manifest_sha256": PINNED_PACKAGE_MANIFEST_SHA256,
        "positive": PINNED_COUNTS["positive"],
        "postrun_receipt_sha256": PINNED_POSTRUN_RECEIPT_SHA256,
        "recovered_certificate_sha256": PINNED_RECOVERED_CERTIFICATE_SHA256,
        "results_sha256": PINNED_RESULTS_SHA256,
        "retry_certificate_sha256": PINNED_RETRY_CERTIFICATE_SHA256,
        "selected_positive": PINNED_COUNTS["selected_positive"],
        "split_salt": PINNED_SPLIT_SALT,
        "strict_failures": PINNED_COUNTS["strict_failures"],
        "superseding_certificate_sha256": PINNED_SUPERSEDING_CERTIFICATE_SHA256,
        "taskset_id": PINNED_TASKSET_ID,
        "validation_permyriad": PINNED_VALIDATION_PERMYRIAD,
        "zero": PINNED_COUNTS["zero"],
    }
    if observed != expected:
        raise RecoveredSFTError("recovered_v6_identity_mismatch")


def _canonical_directory(path: Path, code: str) -> Path:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise RecoveredSFTError(code)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise RecoveredSFTError(code) from error
    if resolved != path or not path.is_dir() or path.is_symlink():
        raise RecoveredSFTError(code)
    return path


def _canonical_new_path(path: Path, root: Path, code: str) -> Path:
    if not path.is_absolute() or path != Path(os.path.normpath(path)) or os.path.lexists(path):
        raise RecoveredSFTError(code)
    if path.parent != root:
        raise RecoveredSFTError(code)
    return path


def _fingerprint(path: Path, code: str, *, modes: frozenset[int]) -> exporter.FileArtifact:
    try:
        source, before = exporter._open_regular(path)
    except exporter.ExportError as error:
        raise RecoveredSFTError(code) from error
    try:
        if before.st_nlink != 1 or stat.S_IMODE(before.st_mode) not in modes:
            raise RecoveredSFTError(code)
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(source.fileno())
    finally:
        source.close()
    if not exporter._same_file(before, after) or size != before.st_size:
        raise RecoveredSFTError(code)
    return exporter.FileArtifact(bytes=size, sha256=digest.hexdigest())


def _read_json(
    path: Path,
    expected_sha256: str,
    code: str,
    *,
    modes: frozenset[int] = frozenset({0o600}),
) -> PinnedJSON:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise RecoveredSFTError(code)
    if not _valid_sha256(expected_sha256):
        raise RecoveredSFTError(f"{code}_digest_invalid")
    try:
        body, artifact = exporter._read_stable_file(path, max_bytes=MAX_METADATA_BYTES)
    except exporter.ExportError as error:
        raise RecoveredSFTError(code) from error
    try:
        metadata = path.stat()
    except OSError as error:
        raise RecoveredSFTError(code) from error
    if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) not in modes:
        raise RecoveredSFTError(code)
    if artifact.sha256 != expected_sha256:
        raise RecoveredSFTError(f"{code}_digest_mismatch")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, ValueError) as error:
        raise RecoveredSFTError(code) from error
    if not isinstance(value, dict):
        raise RecoveredSFTError(code)
    return PinnedJSON(path=path, artifact=artifact, value=value)


def _artifact_record(value: object, code: str, *, rows: int | None = None) -> exporter.FileArtifact:
    if not isinstance(value, dict):
        raise RecoveredSFTError(code)
    allowed = {"bytes", "sha256"} | ({"rows"} if rows is not None else set())
    if set(value) != allowed:
        raise RecoveredSFTError(code)
    size = value.get("bytes")
    digest = value.get("sha256")
    if not _is_plain_int(size) or size < 0 or not _valid_sha256(digest):
        raise RecoveredSFTError(code)
    if rows is not None and value.get("rows") != rows:
        raise RecoveredSFTError(code)
    return exporter.FileArtifact(bytes=size, sha256=digest)


def _path_artifact_record(value: object, code: str) -> exporter.FileArtifact:
    if not isinstance(value, dict) or set(value) != {"bytes", "path", "sha256"}:
        raise RecoveredSFTError(code)
    if not isinstance(value.get("path"), str) or not value["path"]:
        raise RecoveredSFTError(code)
    return _artifact_record({"bytes": value.get("bytes"), "sha256": value.get("sha256")}, code)


def _outcomes(value: object, options: RecoveredSFTOptions, code: str) -> dict[str, int]:
    expected = {
        "error": options.expected_error,
        "positive": options.expected_positive,
        "zero": options.expected_zero,
    }
    if value != expected or sum(expected.values()) != options.expected_count:
        raise RecoveredSFTError(code)
    return expected


def _load_lineage(options: RecoveredSFTOptions) -> LineageBinding:
    source = _canonical_directory(options.source_dir, "source_dir_invalid")
    results = source / RESULTS_FILENAME
    merge_path = source / MERGE_FILENAME
    recovered_path = source / RECOVERED_CERTIFICATE_FILENAME
    package = _read_json(
        options.package_manifest,
        options.expected_package_manifest_sha256,
        "package_manifest_invalid",
        modes=frozenset({0o600, 0o644}),
    )
    merge = _read_json(merge_path, options.expected_merge_manifest_sha256, "merge_manifest_invalid")
    recovered = _read_json(
        recovered_path,
        options.expected_recovered_certificate_sha256,
        "recovered_certificate_invalid",
    )
    retry = _read_json(
        options.retry_certificate,
        options.expected_retry_certificate_sha256,
        "retry_certificate_invalid",
    )
    superseding = _read_json(
        options.superseding_certificate,
        options.expected_superseding_certificate_sha256,
        "superseding_certificate_invalid",
    )
    postrun = _read_json(
        options.postrun_receipt,
        options.expected_postrun_receipt_sha256,
        "postrun_receipt_invalid",
    )

    package_value = package.value
    inputs = package_value.get("inputs")
    coverage = package_value.get("coverage")
    lineage = package_value.get("lineage")
    if (
        package_value.get("schema_version") != 1
        or package_value.get("kind") != PACKAGE_KIND
        or package_value.get("package_version") != "v6"
        or package_value.get("state") != "ready"
        or not isinstance(inputs, dict)
        or not isinstance(coverage, dict)
        or not isinstance(lineage, dict)
        or coverage.get("canonical_tasks") != options.expected_count
    ):
        raise RecoveredSFTError("package_manifest_contract_invalid")
    outcomes = _outcomes(coverage.get("outcomes"), options, "package_outcomes_mismatch")
    results_artifact = _artifact_record(inputs.get("results"), "package_results_invalid", rows=options.expected_count)
    if results_artifact.sha256 != options.expected_results_sha256:
        raise RecoveredSFTError("results_digest_binding_mismatch")
    package_links = {
        "recovered_certificate": recovered.artifact,
        "recovered_merge_manifest": merge.artifact,
        "retry_certificate": retry.artifact,
        "superseding_certificate": superseding.artifact,
        "postrun_receipt": postrun.artifact,
    }
    for name, artifact in package_links.items():
        if _artifact_record(inputs.get(name), "package_lineage_invalid") != artifact:
            raise RecoveredSFTError("package_lineage_mismatch")
    if lineage.get("canonical_task_file_sha256") != options.expected_canonical_task_file_sha256:
        raise RecoveredSFTError("canonical_task_file_binding_mismatch")

    merge_value = merge.value
    merge_artifacts = merge_value.get("artifacts")
    if (
        merge_value.get("schema_version") != 1
        or merge_value.get("kind") != MERGE_KIND
        or merge_value.get("state") != "ready"
        or merge_value.get("mode") != "unfiltered"
        or merge_value.get("sft_selection") is not None
        or merge_value.get("outcomes") != outcomes
        or not isinstance(merge_artifacts, dict)
        or _path_artifact_record(merge_artifacts.get("results"), "merge_manifest_invalid") != results_artifact
        or _path_artifact_record(merge_artifacts.get("certificate"), "merge_manifest_invalid") != recovered.artifact
    ):
        raise RecoveredSFTError("merge_manifest_contract_invalid")

    recovered_value = recovered.value
    recovered_lineage = recovered_value.get("lineage")
    recovered_coverage = recovered_value.get("coverage")
    if (
        recovered_value.get("schema_version") != 1
        or recovered_value.get("kind") != RECOVERED_KIND
        or recovered_value.get("state") != "passed"
        or recovered_value.get("mode") != "unfiltered"
        or recovered_value.get("outcomes") != outcomes
        or not isinstance(recovered_lineage, dict)
        or not isinstance(recovered_coverage, dict)
        or recovered_coverage.get("task_count") != options.expected_count
        or recovered_coverage.get("exact") is not True
        or recovered_coverage.get("exhaustive") is not True
        or recovered_coverage.get("canonical_order") is not True
        or recovered_coverage.get("universe_task_file_sha256") != options.expected_canonical_task_file_sha256
        or _path_artifact_record(recovered_value.get("results"), "recovered_certificate_invalid") != results_artifact
    ):
        raise RecoveredSFTError("recovered_certificate_contract_invalid")
    selection_contract_sha256 = recovered_lineage.get("selection_contract_sha256")
    if (
        not _valid_sha256(selection_contract_sha256)
        or recovered_lineage.get("superseding_certificate_sha256") != superseding.artifact.sha256
        or merge_value.get("lineage") != recovered_lineage
        or lineage.get("selection_contract_sha256") != selection_contract_sha256
        or lineage.get("superseding_certificate_sha256") != superseding.artifact.sha256
        or lineage.get("retry_certificate_sha256") != retry.artifact.sha256
        or lineage.get("recovered_certificate_sha256") != recovered.artifact.sha256
        or lineage.get("recovered_merge_manifest_sha256") != merge.artifact.sha256
        or lineage.get("postrun_receipt_sha256") != postrun.artifact.sha256
    ):
        raise RecoveredSFTError("recovered_lineage_mismatch")

    retry_value = retry.value
    superseding_value = superseding.value
    if (
        retry_value.get("schema_version") != 1
        or retry_value.get("kind") != RETRY_KIND
        or retry_value.get("state") != "passed"
        or retry_value.get("selection_contract_sha256") != selection_contract_sha256
        or superseding_value.get("schema_version") != 1
        or superseding_value.get("kind") != SUPERSEDING_KIND
        or superseding_value.get("state") != "passed"
        or superseding_value.get("selection_contract_sha256") != selection_contract_sha256
        or not isinstance(superseding_value.get("predecessor"), dict)
        or superseding_value["predecessor"].get("sha256") != retry.artifact.sha256
    ):
        raise RecoveredSFTError("recovery_certificate_chain_invalid")

    postrun_value = postrun.value
    postrun_artifact = postrun_value.get("artifact")
    postrun_lineage = postrun_value.get("lineage")
    if (
        postrun_value.get("schema_version") != 1
        or postrun_value.get("kind") != POSTRUN_KIND
        or postrun_value.get("state") != "certified"
        or postrun_value.get("mode") != "unfiltered"
        or postrun_value.get("task_count") != options.expected_count
        or postrun_value.get("outcomes") != outcomes
        or not isinstance(postrun_artifact, dict)
        or not isinstance(postrun_lineage, dict)
        or _artifact_record(postrun_artifact.get("results"), "postrun_receipt_invalid") != results_artifact
        or _artifact_record(postrun_artifact.get("certificate"), "postrun_receipt_invalid") != recovered.artifact
        or _artifact_record(postrun_artifact.get("manifest"), "postrun_receipt_invalid") != merge.artifact
        or postrun_lineage.get("selection_contract_sha256") != selection_contract_sha256
        or postrun_lineage.get("retry_run_certificate_sha256") != retry.artifact.sha256
        or postrun_lineage.get("superseding_certificate_sha256") != superseding.artifact.sha256
    ):
        raise RecoveredSFTError("postrun_receipt_contract_invalid")

    if not _valid_sha256(options.expected_results_sha256):
        raise RecoveredSFTError("results_digest_invalid")
    try:
        metadata = results.stat()
    except OSError as error:
        raise RecoveredSFTError("results_invalid") from error
    if (
        results.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != results_artifact.bytes
    ):
        raise RecoveredSFTError("results_invalid")

    if (
        not options.canonical_task_file.is_absolute()
        or options.canonical_task_file != Path(os.path.normpath(options.canonical_task_file))
        or options.canonical_task_file.is_symlink()
    ):
        raise RecoveredSFTError("canonical_task_file_invalid")
    task_body, task_artifact = exporter._read_stable_file(options.canonical_task_file)
    task_metadata = options.canonical_task_file.stat()
    if (
        task_metadata.st_nlink != 1
        or stat.S_IMODE(task_metadata.st_mode) != 0o600
        or task_artifact.sha256 != options.expected_canonical_task_file_sha256
    ):
        raise RecoveredSFTError("canonical_task_file_invalid")
    return LineageBinding(
        package=package,
        merge=merge,
        recovered=recovered,
        retry=retry,
        superseding=superseding,
        postrun=postrun,
        results=results,
        results_artifact=results_artifact,
        task_file=options.canonical_task_file,
        task_file_artifact=task_artifact,
        task_file_body=task_body,
        outcomes=outcomes,
    )


def _validate_archive(package: PinnedJSON, verifier: Path) -> ArchiveBinding:
    package_root = _canonical_directory(package.path.parent, "package_root_invalid")
    chunks_root = _canonical_directory(package_root / "chunks", "package_chunks_invalid")
    try:
        root_names = {entry.name for entry in package_root.iterdir()}
        chunk_names = {entry.name for entry in chunks_root.iterdir()}
    except OSError as error:
        raise RecoveredSFTError("package_inventory_invalid") from error
    if root_names != {"README.md", "SHA256SUMS", "chunks", "manifest.json"}:
        raise RecoveredSFTError("package_inventory_invalid")

    archive_value = package.value.get("archive")
    chunks_value = package.value.get("chunks")
    chunk_bytes = package.value.get("chunk_bytes")
    if (
        not isinstance(archive_value, dict)
        or set(archive_value) != {"bytes", "compression", "member_count", "members", "name", "sha256"}
        or archive_value.get("compression") != "zstd-19-long31"
        or archive_value.get("member_count") != 7
        or not isinstance(archive_value.get("members"), list)
        or len(archive_value["members"]) != 7
        or not isinstance(archive_value.get("name"), str)
        or not archive_value["name"].endswith(".tar.zst")
        or not _is_plain_int(archive_value.get("bytes"))
        or archive_value["bytes"] < 1
        or not _valid_sha256(archive_value.get("sha256"))
        or not isinstance(chunks_value, list)
        or not chunks_value
        or not _is_plain_int(chunk_bytes)
        or not 0 < chunk_bytes < 100_000_000
    ):
        raise RecoveredSFTError("package_archive_contract_invalid")
    archive_name = archive_value["name"]
    expected_chunk_names = [f"{archive_name}.{index:03d}.part" for index in range(len(chunks_value))]
    if chunk_names != set(expected_chunk_names):
        raise RecoveredSFTError("package_chunk_inventory_invalid")
    expected_sums = bytearray()
    declared_chunks: list[tuple[Path, exporter.FileArtifact]] = []
    for index, value in enumerate(chunks_value):
        if not isinstance(value, dict) or set(value) != {"bytes", "name", "sha256"}:
            raise RecoveredSFTError("package_chunk_contract_invalid")
        if value.get("name") != expected_chunk_names[index]:
            raise RecoveredSFTError("package_chunk_sequence_invalid")
        artifact = _artifact_record(
            {"bytes": value.get("bytes"), "sha256": value.get("sha256")},
            "package_chunk_contract_invalid",
        )
        if artifact.bytes < 1 or artifact.bytes > chunk_bytes:
            raise RecoveredSFTError("package_chunk_size_invalid")
        if index + 1 < len(chunks_value) and artifact.bytes != chunk_bytes:
            raise RecoveredSFTError("package_chunk_size_invalid")
        path = chunks_root / value["name"]
        declared_chunks.append((path, artifact))
        expected_sums.extend(f"{artifact.sha256}  {value['name']}\n".encode("ascii"))

    sums_path = package_root / "SHA256SUMS"
    try:
        sums_body, sums_artifact = exporter._read_stable_file(sums_path, max_bytes=MAX_METADATA_BYTES)
    except exporter.ExportError as error:
        raise RecoveredSFTError("package_checksums_invalid") from error
    sums_metadata = sums_path.stat()
    if (
        sums_path.is_symlink()
        or sums_metadata.st_nlink != 1
        or stat.S_IMODE(sums_metadata.st_mode) not in {0o600, 0o644}
        or sums_body != bytes(expected_sums)
    ):
        raise RecoveredSFTError("package_checksums_invalid")

    if (
        not verifier.is_absolute()
        or verifier != Path(os.path.normpath(verifier))
        or verifier.is_symlink()
        or not verifier.is_file()
        or not Path("/usr/bin/zstd").is_file()
    ):
        raise RecoveredSFTError("archive_verifier_invalid")
    decompressor: subprocess.Popen[bytes] | None = None
    verifier_process: subprocess.Popen[bytes] | None = None
    try:
        decompressor = subprocess.Popen(
            ["/usr/bin/zstd", "--long=31", "-dc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert decompressor.stdout is not None
        verifier_process = subprocess.Popen(
            [sys.executable, str(verifier), str(package.path)],
            stdin=decompressor.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        decompressor.stdout.close()
        assert decompressor.stdin is not None
        archive_digest = hashlib.sha256()
        archive_size = 0
        observed_chunks: list[tuple[Path, exporter.FileArtifact]] = []
        try:
            for path, expected in declared_chunks:
                try:
                    source, before = exporter._open_regular(path)
                except exporter.ExportError as error:
                    raise RecoveredSFTError("package_chunk_invalid") from error
                digest = hashlib.sha256()
                size = 0
                try:
                    if before.st_nlink != 1 or stat.S_IMODE(before.st_mode) not in {0o600, 0o644}:
                        raise RecoveredSFTError("package_chunk_invalid")
                    while block := source.read(1 << 20):
                        digest.update(block)
                        archive_digest.update(block)
                        size += len(block)
                        archive_size += len(block)
                        decompressor.stdin.write(block)
                    after = os.fstat(source.fileno())
                finally:
                    source.close()
                observed = exporter.FileArtifact(bytes=size, sha256=digest.hexdigest())
                if not exporter._same_file(before, after) or observed != expected:
                    raise RecoveredSFTError("package_chunk_digest_mismatch")
                observed_chunks.append((path, observed))
        finally:
            with suppress(OSError):
                decompressor.stdin.close()
        decompressor_status = decompressor.wait(timeout=900)
        verifier_status = verifier_process.wait(timeout=900)
    except BaseException as error:
        if decompressor is not None and decompressor.stdin is not None:
            with suppress(OSError):
                decompressor.stdin.close()
        for process in (decompressor, verifier_process):
            if process is not None and process.poll() is None:
                with suppress(OSError):
                    process.terminate()
        for process in (decompressor, verifier_process):
            if process is not None:
                with suppress(OSError, subprocess.TimeoutExpired):
                    process.wait(timeout=10)
        if isinstance(error, RecoveredSFTError):
            raise
        raise RecoveredSFTError("package_archive_validation_failed") from error
    observed_archive = exporter.FileArtifact(bytes=archive_size, sha256=archive_digest.hexdigest())
    declared_archive = _artifact_record(
        {"bytes": archive_value.get("bytes"), "sha256": archive_value.get("sha256")},
        "package_archive_contract_invalid",
    )
    if decompressor_status != 0 or verifier_status != 0 or observed_archive != declared_archive:
        raise RecoveredSFTError("package_archive_validation_failed")
    return ArchiveBinding(
        archive=observed_archive,
        sha256sums_path=sums_path,
        sha256sums=sums_artifact,
        chunks=tuple(observed_chunks),
    )


def _validate_repository(project: Path, expected_revision: str, expected_finalizer_sha256: str) -> Mapping[str, Any]:
    if not _valid_sha256(expected_finalizer_sha256):
        raise RecoveredSFTError("finalizer_digest_invalid")
    try:
        root = common._validate_repository(project, expected_revision)
    except common.FinalizationError as error:
        raise RecoveredSFTError(error.code) from error
    workflow = root / "user" / "tianhaowu" / "terminal_bench_vmvm"
    finalizer = workflow / Path(__file__).name
    if Path(__file__).resolve(strict=True) != finalizer.resolve(strict=True):
        raise RecoveredSFTError("finalizer_runtime_origin_mismatch")
    files = {
        "audit_traces.py": _fingerprint(
            workflow / "audit_traces.py", "code_artifact_invalid", modes=frozenset({0o644})
        ),
        "direct_qwen_workers.py": _fingerprint(
            workflow / "direct_qwen_workers.py",
            "code_artifact_invalid",
            modes=frozenset({0o644}),
        ),
        "export_sft.py": _fingerprint(workflow / "export_sft.py", "code_artifact_invalid", modes=frozenset({0o644})),
        "finalize_qwen_sft.py": _fingerprint(
            workflow / "finalize_qwen_sft.py",
            "code_artifact_invalid",
            modes=frozenset({0o644}),
        ),
        Path(__file__).name: _fingerprint(finalizer, "code_artifact_invalid", modes=frozenset({0o644, 0o755})),
        "migrate_qwen_router_affinity.py": _fingerprint(
            workflow / "migrate_qwen_router_affinity.py",
            "code_artifact_invalid",
            modes=frozenset({0o644}),
        ),
        "verify_qwen_recovered_trace_archive.py": _fingerprint(
            workflow / "verify_qwen_recovered_trace_archive.py",
            "code_artifact_invalid",
            modes=frozenset({0o644}),
        ),
    }
    if files[Path(__file__).name].sha256 != expected_finalizer_sha256:
        raise RecoveredSFTError("finalizer_digest_mismatch")
    return {
        "files": {name: artifact.as_dict() for name, artifact in sorted(files.items())},
        "project_revision": expected_revision,
    }


def _set_commitment(values: set[str]) -> dict[str, int | str]:
    body = b"".join(value.encode("ascii") + b"\n" for value in sorted(values))
    return {
        "algorithm": SET_COMMITMENT_ALGORITHM,
        "count": len(values),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _known_issue_counts(trace: Mapping[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    nodes = trace.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        counts["traces_without_nodes"] += 1
        return counts
    length_turns = 0
    null_reasoning_tool_turns = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("sampled") is not True:
            continue
        if node.get("finish_reason") == "length":
            length_turns += 1
        message = node.get("message")
        if (
            isinstance(message, dict)
            and isinstance(message.get("tool_calls"), list)
            and bool(message["tool_calls"])
            and message.get("reasoning_content") is None
        ):
            null_reasoning_tool_turns += 1
    if length_turns:
        counts["sampled_finish_reason_length_traces"] += 1
        counts["sampled_finish_reason_length_turns"] += length_turns
    if null_reasoning_tool_turns:
        counts["sampled_tool_calls_null_reasoning_traces"] += 1
        counts["sampled_tool_calls_null_reasoning_turns"] += null_reasoning_tool_turns
    return counts


def _iter_source(source: Any) -> Iterator[bytes]:
    while raw := source.readline(MAX_JSONL_ROW_BYTES + 1):
        if len(raw) > MAX_JSONL_ROW_BYTES or not raw.endswith(b"\n") or not raw.strip():
            raise RecoveredSFTError("results_jsonl_invalid")
        yield raw


def _scan_and_write(
    *,
    binding: LineageBinding,
    options: RecoveredSFTOptions,
    staging: Path,
    trace_validator: TraceValidator,
) -> tuple[dict[str, Any], dict[str, exporter.FileArtifact]]:
    try:
        task_context = exporter._task_identity_context(
            {"id": options.taskset_id, "dataset_revision": options.dataset_revision},
            binding.task_file_body,
            expected_task_count=options.expected_count,
        )
    except exporter.ExportError as error:
        raise RecoveredSFTError(error.code) from error

    train_sink = exporter.JSONLSink(staging / "train" / "train.jsonl")
    validation_sink = exporter.JSONLSink(staging / "validation" / "train.jsonl")
    sinks = {"train": train_sink, "validation": validation_sink}
    counters: Counter[str] = Counter()
    counters.update(
        {
            "emitted_rows": 0,
            "error_traces": 0,
            "input_traces": 0,
            "positive_traces": 0,
            "selected_positive_traces": 0,
            "strict_failure_traces": 0,
            "strict_invalid_positive_traces": 0,
            "strict_invalid_zero_traces": 0,
            "strict_valid_zero_traces": 0,
            "train_rows": 0,
            "train_traces": 0,
            "validation_rows": 0,
            "validation_traces": 0,
            "zero_traces": 0,
        }
    )
    problem_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    seen_trace_ids: set[str] = set()
    seen_source_rows: set[str] = set()
    seen_slugs: set[str] = set()
    selected_rows: set[str] = set()
    omitted_rows: set[str] = set()
    error_rows: set[str] = set()
    zero_rows: set[str] = set()
    invalid_positive_rows: set[str] = set()
    split_task_hashes: dict[str, set[str]] = {"train": set(), "validation": set()}
    split_trace_indices = {"train": 0, "validation": 0}
    results_digest = hashlib.sha256()
    results_size = 0
    source = None
    try:
        try:
            source, before = exporter._open_regular(binding.results)
        except exporter.ExportError as error:
            raise RecoveredSFTError("results_invalid") from error
        if before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600:
            raise RecoveredSFTError("results_invalid")
        for source_trace_index, raw in enumerate(_iter_source(source)):
            results_digest.update(raw)
            results_size += len(raw)
            counters["input_traces"] += 1
            source_row_sha256 = hashlib.sha256(raw).hexdigest()
            if source_row_sha256 in seen_source_rows:
                raise RecoveredSFTError("duplicate_trace_row")
            seen_source_rows.add(source_row_sha256)
            try:
                trace = json.loads(raw)
            except (UnicodeDecodeError, ValueError) as error:
                raise RecoveredSFTError("results_jsonl_invalid") from error
            if not isinstance(trace, dict):
                raise RecoveredSFTError("trace_not_object")
            trace_id = trace.get("id")
            task = trace.get("task")
            if not isinstance(trace_id, str) or not trace_id or not isinstance(task, dict):
                raise RecoveredSFTError("trace_identity_invalid")
            trace_id_sha256 = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
            if trace_id_sha256 in seen_trace_ids:
                raise RecoveredSFTError("duplicate_trace_id")
            seen_trace_ids.add(trace_id_sha256)
            try:
                slug = exporter._opaque_task_slug(task)
            except exporter.ExportError as error:
                raise RecoveredSFTError(error.code) from error
            if slug not in task_context.approved_slugs:
                raise RecoveredSFTError("trace_task_slug_not_approved")
            if slug in seen_slugs:
                raise RecoveredSFTError("duplicate_task_trace")
            seen_slugs.add(slug)
            issue_counts.update(_known_issue_counts(trace))

            errors = trace.get("errors")
            if not isinstance(errors, list):
                raise RecoveredSFTError("trace_errors_invalid")
            if errors:
                counters["error_traces"] += 1
                counters["strict_failure_traces"] += 1
                error_rows.add(source_row_sha256)
                omitted_rows.add(source_row_sha256)
                continue
            try:
                reward = exporter._trace_reward(trace)
            except exporter.ExportError as error:
                raise RecoveredSFTError(error.code) from error
            outcome = "positive" if reward == 1.0 else "zero"
            counters[f"{outcome}_traces"] += 1
            try:
                nodes, tools = trace_validator(
                    trace,
                    reward=reward,
                    max_sequence_tokens=exporter.DEFAULT_MAX_SEQUENCE_TOKENS,
                    require_exact_provider_json=True,
                )
            except exporter.ExportError as error:
                counters["strict_failure_traces"] += 1
                counters[f"strict_invalid_{outcome}_traces"] += 1
                problem_counts[error.code] += 1
                omitted_rows.add(source_row_sha256)
                if outcome == "positive":
                    invalid_positive_rows.add(source_row_sha256)
                else:
                    zero_rows.add(source_row_sha256)
                continue
            if outcome == "zero":
                counters["strict_valid_zero_traces"] += 1
                zero_rows.add(source_row_sha256)
                omitted_rows.add(source_row_sha256)
                continue

            try:
                task_sha256 = exporter._task_identity_sha256(task_context, task)
            except exporter.ExportError as error:
                raise RecoveredSFTError(error.code) from error
            split = exporter._split_for_task(
                task_sha256,
                salt=options.split_salt,
                validation_permyriad=options.validation_permyriad,
            )
            emitted = 0
            try:
                rows = exporter._target_rows(
                    trace,
                    source_trace_index=source_trace_index,
                    source_split_row_index=split_trace_indices[split],
                    source_trace_sha256=source_row_sha256,
                    task_sha256=task_sha256,
                    reward=reward,
                    tools=tools,
                    routing_epoch=None,
                )
                for row in rows:
                    sinks[split].write(row)
                    emitted += 1
            except exporter.ExportError as error:
                raise RecoveredSFTError(error.code) from error
            if emitted < 1:
                raise RecoveredSFTError("trace_has_no_sft_targets")
            selected_rows.add(source_row_sha256)
            split_task_hashes[split].add(task_sha256)
            split_trace_indices[split] += 1
            counters["selected_positive_traces"] += 1
            counters["emitted_rows"] += emitted
            counters[f"{split}_traces"] += 1
            counters[f"{split}_rows"] += emitted
        after = os.fstat(source.fileno())
        if not exporter._same_file(before, after):
            raise RecoveredSFTError("results_changed")
    except BaseException:
        for sink in (train_sink, validation_sink):
            if not sink._file.closed:
                sink._file.close()
        raise
    finally:
        if source is not None:
            source.close()

    train_artifact = train_sink.close()
    validation_artifact = validation_sink.close()
    observed_results = exporter.FileArtifact(bytes=results_size, sha256=results_digest.hexdigest())
    if observed_results != binding.results_artifact:
        raise RecoveredSFTError("results_digest_mismatch")
    if counters["input_traces"] != options.expected_count or seen_slugs != task_context.approved_slugs:
        raise RecoveredSFTError("canonical_coverage_mismatch")
    observed_outcomes = {
        "error": counters["error_traces"],
        "positive": counters["positive_traces"],
        "zero": counters["zero_traces"],
    }
    if observed_outcomes != binding.outcomes:
        raise RecoveredSFTError("source_outcomes_mismatch")
    if counters["strict_invalid_positive_traces"]:
        raise RecoveredSFTError("positive_trace_not_trainable")
    if counters["selected_positive_traces"] != options.expected_selected_positive:
        raise RecoveredSFTError("selected_positive_count_mismatch")
    if counters["strict_failure_traces"] != options.expected_strict_failures:
        raise RecoveredSFTError("strict_failure_count_mismatch")
    if selected_rows & omitted_rows or selected_rows | omitted_rows != seen_source_rows:
        raise RecoveredSFTError("selection_partition_invalid")
    if split_task_hashes["train"] & split_task_hashes["validation"]:
        raise RecoveredSFTError("task_split_overlap")

    artifacts = {
        "train/train.jsonl": train_artifact,
        "validation/train.jsonl": validation_artifact,
    }
    audit = {
        "counts": dict(sorted(counters.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "problem_counts": dict(sorted(problem_counts.items())),
        "set_commitments": {
            "error": _set_commitment(error_rows),
            "invalid_positive": _set_commitment(invalid_positive_rows),
            "omitted": _set_commitment(omitted_rows),
            "selected": _set_commitment(selected_rows),
            "zero": _set_commitment(zero_rows),
        },
        "split_task_hashes": split_task_hashes,
    }
    return audit, artifacts


def _source_artifacts(
    binding: LineageBinding,
    archive: ArchiveBinding,
) -> dict[str, Any]:
    return {
        "archive": archive.archive.as_dict(),
        "canonical_task_file": binding.task_file_artifact.as_dict(),
        "chunks": [artifact.as_dict() for _path, artifact in archive.chunks],
        "merge_manifest": binding.merge.artifact.as_dict(),
        "package_manifest": binding.package.artifact.as_dict(),
        "package_sha256sums": archive.sha256sums.as_dict(),
        "postrun_receipt": binding.postrun.artifact.as_dict(),
        "recovered_certificate": binding.recovered.artifact.as_dict(),
        "results": binding.results_artifact.as_dict(),
        "retry_certificate": binding.retry.artifact.as_dict(),
        "superseding_certificate": binding.superseding.artifact.as_dict(),
    }


def _assert_sources_unchanged(binding: LineageBinding, archive: ArchiveBinding) -> None:
    expected = {
        binding.package.path: (binding.package.artifact, frozenset({0o600, 0o644})),
        binding.merge.path: (binding.merge.artifact, frozenset({0o600})),
        binding.recovered.path: (binding.recovered.artifact, frozenset({0o600})),
        binding.retry.path: (binding.retry.artifact, frozenset({0o600})),
        binding.superseding.path: (binding.superseding.artifact, frozenset({0o600})),
        binding.postrun.path: (binding.postrun.artifact, frozenset({0o600})),
        binding.results: (binding.results_artifact, frozenset({0o600})),
        binding.task_file: (binding.task_file_artifact, frozenset({0o600})),
    }
    for path, (artifact, modes) in expected.items():
        if _fingerprint(path, "source_changed", modes=modes) != artifact:
            raise RecoveredSFTError("source_changed")
    if (
        _fingerprint(
            archive.sha256sums_path,
            "source_changed",
            modes=frozenset({0o600, 0o644}),
        )
        != archive.sha256sums
    ):
        raise RecoveredSFTError("source_changed")
    for path, artifact in archive.chunks:
        if _fingerprint(path, "source_changed", modes=frozenset({0o600, 0o644})) != artifact:
            raise RecoveredSFTError("source_changed")


def _validate_published_output(
    path: Path,
    allow_incomplete: bool,
    expected: Mapping[str, exporter.FileArtifact],
) -> None:
    required_files = {
        "manifest.json",
        RECEIPT_FILENAME,
        "task-split.json",
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl",
        "validation/train.jsonl",
    }
    if set(expected) != required_files:
        raise RecoveredSFTError("published_artifact_contract_invalid")
    expected_root = {
        "manifest.json",
        RECEIPT_FILENAME,
        "task-split.json",
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train",
        "validation",
    }
    if allow_incomplete:
        expected_root.add(direct.MIGRATION_INCOMPLETE_FILENAME)
    try:
        root_metadata = path.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_IMODE(root_metadata.st_mode) != 0o700:
            raise RecoveredSFTError("published_artifact_mode_invalid")
        if {entry.name for entry in path.iterdir()} != expected_root:
            raise RecoveredSFTError("published_artifact_inventory_invalid")
        for directory in (path / "train", path / "validation"):
            metadata = directory.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise RecoveredSFTError("published_artifact_mode_invalid")
        if {entry.name for entry in (path / "train").iterdir()} != {"train.jsonl"} or {
            entry.name for entry in (path / "validation").iterdir()
        } != {"train.jsonl"}:
            raise RecoveredSFTError("published_artifact_inventory_invalid")
        for relative, artifact in expected.items():
            target = path / relative
            metadata = target.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise RecoveredSFTError("published_artifact_mode_invalid")
            if _fingerprint(target, "published_artifact_invalid", modes=frozenset({0o600})) != artifact:
                raise RecoveredSFTError("published_artifact_digest_mismatch")
        if allow_incomplete:
            marker = (path / direct.MIGRATION_INCOMPLETE_FILENAME).lstat()
            if not stat.S_ISREG(marker.st_mode) or marker.st_nlink != 1 or stat.S_IMODE(marker.st_mode) != 0o600:
                raise RecoveredSFTError("published_artifact_mode_invalid")
    except RecoveredSFTError:
        raise
    except OSError as error:
        raise RecoveredSFTError("published_artifact_invalid") from error


def finalize_recovered_sft(
    options: RecoveredSFTOptions,
    *,
    repository_validator: RepositoryValidator = _validate_repository,
    trace_validator: TraceValidator = exporter._validate_trainable_trace,
    archive_validator: ArchiveValidator = _validate_archive,
    identity_validator: IdentityValidator = _validate_production_identity,
) -> dict[str, Any]:
    """Validate, select, and atomically publish a recovered-union SFT export."""
    numeric = (
        options.expected_count,
        options.expected_positive,
        options.expected_zero,
        options.expected_error,
        options.expected_selected_positive,
        options.expected_strict_failures,
        options.validation_permyriad,
    )
    if any(not _is_plain_int(value) or value < 0 for value in numeric):
        raise RecoveredSFTError("count_argument_invalid")
    if (
        options.expected_count < 1
        or options.expected_positive + options.expected_zero + options.expected_error != options.expected_count
        or options.expected_selected_positive != options.expected_positive
        or not 0 <= options.validation_permyriad < exporter.SPLIT_BUCKETS
        or not options.split_salt
        or "\x00" in options.split_salt
        or not options.taskset_id
        or "\x00" in options.taskset_id
        or not _valid_git_sha(options.dataset_revision)
    ):
        raise RecoveredSFTError("configuration_invalid")
    identity_validator(options)
    output_root = _canonical_directory(options.output_root, "output_root_invalid")
    output = _canonical_new_path(options.output_dir, output_root, "output_path_invalid")
    project = _canonical_directory(options.project_dir, "project_dir_invalid")
    source = _canonical_directory(options.source_dir, "source_dir_invalid")
    package_root = _canonical_directory(options.package_manifest.parent, "package_root_invalid")
    if any(common._paths_overlap(output, protected) for protected in (project, source, package_root)):
        raise RecoveredSFTError("path_boundaries_overlap")
    code = repository_validator(
        options.project_dir,
        options.expected_project_revision,
        options.expected_finalizer_sha256,
    )
    binding = _load_lineage(options)
    archive = archive_validator(
        binding.package,
        options.project_dir / "user" / "tianhaowu" / "terminal_bench_vmvm" / "verify_qwen_recovered_trace_archive.py",
    )
    target_contract = exporter._load_target_rendering_contract()

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.recovered-sft-", dir=output_root))
    os.chmod(staging, 0o700)
    published = False
    try:
        audit, artifacts = _scan_and_write(
            binding=binding,
            options=options,
            staging=staging,
            trace_validator=trace_validator,
        )
        for directory in (staging / "train", staging / "validation"):
            os.chmod(directory, 0o700)
        split_task_hashes = audit.pop("split_task_hashes")
        task_split = {
            "format_version": exporter.FORMAT_VERSION,
            "split_salt": options.split_salt,
            "validation_permyriad": options.validation_permyriad,
            "train_task_sha256": sorted(split_task_hashes["train"]),
            "validation_task_sha256": sorted(split_task_hashes["validation"]),
        }
        task_split_artifact = exporter._write_json(staging / "task-split.json", task_split)
        contract_artifact = exporter._write_bytes(
            staging / exporter.TARGET_RENDERING_CONTRACT_FILENAME,
            target_contract.body,
        )
        if contract_artifact != target_contract.artifact:
            raise RecoveredSFTError("target_rendering_contract_copy_mismatch")
        artifacts["task-split.json"] = task_split_artifact
        artifacts[exporter.TARGET_RENDERING_CONTRACT_FILENAME] = contract_artifact

        omission_receipt = {
            "schema_version": SCHEMA_VERSION,
            "kind": RECEIPT_KIND,
            "state": "passed",
            "visibility": "private-aggregate-only",
            "selection": {
                "policy": "pass-only; fail-closed if any positive trace is not strictly trainable",
                "require_exact_provider_json": True,
                "require_model_io": True,
                "require_reasoning": True,
                "require_request_graph_match": True,
                "max_sequence_tokens": exporter.DEFAULT_MAX_SEQUENCE_TOKENS,
            },
            "counts": audit["counts"],
            "issue_counts": audit["issue_counts"],
            "problem_counts": audit["problem_counts"],
            "set_commitments": audit["set_commitments"],
            "source_artifacts": _source_artifacts(binding, archive),
            "task_identity": {
                "canonical_task_file": binding.task_file_artifact.as_dict(),
                "dataset_revision": options.dataset_revision,
                "policy": "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)",
                "taskset_id": options.taskset_id,
            },
            "split": {
                "policy": "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000",
                "split_salt": options.split_salt,
                "validation_permyriad": options.validation_permyriad,
            },
            "code": code,
        }
        receipt_artifact = exporter._write_json(staging / RECEIPT_FILENAME, omission_receipt)
        counts = audit["counts"]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": EXPORT_KIND,
            "artifacts": {name: artifact.as_dict() for name, artifact in sorted(artifacts.items())},
            "counts": {
                **counts,
                "selected_sft_tasks": counts["selected_positive_traces"],
            },
            "exporter": {
                "file_sha256": code["files"]["export_sft.py"]["sha256"],
                "format_version": exporter.FORMAT_VERSION,
            },
            "format": {
                "assistant_finish_reason": "retained verbatim for every sampled assistant message",
                "assistant_tool_calls": "OpenAI function-call objects",
                "history_assistant_reasoning": "retained verbatim",
                "loss_mask": "message.trainable; exactly one final assistant message is true",
                "sample_unit": "one unique sampled assistant node with its root-to-node context",
                "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
                "task_identity": "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)",
            },
            "max_sequence_tokens": exporter.DEFAULT_MAX_SEQUENCE_TOKENS,
            "recovered_union": {
                "lineage": _source_artifacts(binding, archive),
                "omission_receipt": receipt_artifact.as_dict(),
            },
            "selection": "pass-only",
            "source_validation": {
                "max_sequence_tokens": exporter.DEFAULT_MAX_SEQUENCE_TOKENS,
                "require_clean_stop": True,
                "require_exact_provider_json": True,
                "require_model_io": True,
                "require_reasoning": True,
                "require_request_graph_match": True,
            },
            "split": omission_receipt["split"],
            "target_rendering": target_contract.value,
            "taskset": {"id": options.taskset_id, "dataset_revision": options.dataset_revision},
        }
        manifest_artifact = exporter._write_json(staging / "manifest.json", manifest)
        published_artifacts = {
            **artifacts,
            RECEIPT_FILENAME: receipt_artifact,
            "manifest.json": manifest_artifact,
        }
        for directory in (staging / "train", staging / "validation", staging):
            exporter._fsync_dir(directory)

        _assert_sources_unchanged(binding, archive)
        if (
            repository_validator(
                options.project_dir,
                options.expected_project_revision,
                options.expected_finalizer_sha256,
            )
            != code
        ):
            raise RecoveredSFTError("project_changed_during_finalization")
        if exporter._load_target_rendering_contract() != target_contract:
            raise RecoveredSFTError("target_rendering_contract_changed")

        def validate_published(path: Path, allow_incomplete: bool) -> None:
            _validate_published_output(path, allow_incomplete, published_artifacts)
            if staging.exists():
                try:
                    shutil.rmtree(staging)
                    exporter._fsync_dir(output_root)
                except OSError as error:
                    raise RecoveredSFTError("staging_cleanup_failed") from error

        try:
            migration._publish_directory(staging, output, validate_published)
        except migration.MigrationError as error:
            code = "output_already_exists" if str(error) == "destination_exists" else "output_publish_failed"
            raise RecoveredSFTError(code) from error
        published = True
        return {
            "manifest_sha256": manifest_artifact.sha256,
            "omission_receipt_sha256": receipt_artifact.sha256,
            "rows": {
                "total": counts["emitted_rows"],
                "train": counts["train_rows"],
                "validation": counts["validation_rows"],
            },
            "selected_positive_traces": counts["selected_positive_traces"],
            "state": "finalized",
        }
    finally:
        if not published:
            with suppress(OSError):
                shutil.rmtree(staging)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument("--expected-finalizer-sha256", required=True)
    parser.add_argument("--package-manifest", type=Path, required=True)
    parser.add_argument("--expected-package-manifest-sha256", required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected-results-sha256", required=True)
    parser.add_argument("--expected-merge-manifest-sha256", required=True)
    parser.add_argument("--expected-recovered-certificate-sha256", required=True)
    parser.add_argument("--retry-certificate", type=Path, required=True)
    parser.add_argument("--expected-retry-certificate-sha256", required=True)
    parser.add_argument("--superseding-certificate", type=Path, required=True)
    parser.add_argument("--expected-superseding-certificate-sha256", required=True)
    parser.add_argument("--postrun-receipt", type=Path, required=True)
    parser.add_argument("--expected-postrun-receipt-sha256", required=True)
    parser.add_argument("--canonical-task-file", type=Path, required=True)
    parser.add_argument("--expected-canonical-task-file-sha256", required=True)
    parser.add_argument("--taskset-id", required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--expected-positive", type=int, required=True)
    parser.add_argument("--expected-zero", type=int, required=True)
    parser.add_argument("--expected-error", type=int, required=True)
    parser.add_argument("--expected-selected-positive", type=int, required=True)
    parser.add_argument("--expected-strict-failures", type=int, required=True)
    parser.add_argument("--validation-permyriad", type=int, required=True)
    parser.add_argument("--split-salt", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = finalize_recovered_sft(RecoveredSFTOptions(**vars(args)))
    except RecoveredSFTError as error:
        print(json.dumps({"code": error.code, "state": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "state": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
