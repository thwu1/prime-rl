#!/usr/bin/env python3
"""Create and enforce the exact Qwen old-16 to current-24 repair transition."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import migrate_qwen_router_affinity as migration

SERVER_IDENTIFIER = "shared_qwen38_2p4t_e5ddc652"
CONTRACT_PATH = (
    Path(__file__).resolve().parent / "configs" / "eval" / "servers" / SERVER_IDENTIFIER / "repair_generation.json"
)
RUN_BUNDLE_DIRECTORY = f"serving_generation_{SERVER_IDENTIFIER}"
TRANSITION_FILENAME = "transition.json"
GENERATION_CONFIG_FILENAME = "repair_generation_config.toml"
CAPACITY_SMOKE_FILENAME = "capacity_smoke.json"
PREFIX_ROWS_FILENAME = "source_prefix_rows.sha256"
SOURCE_MANIFEST_FILENAME = "source_direct_workers.json"
TARGET_MANIFEST_FILENAME = "target_direct_workers.json"
KIND = "qwen-direct-repair-serving-generation-transition"
SCHEMA_VERSION = 1
MAX_METADATA_BYTES = 16 << 20
SHA256 = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")
SOURCE_FILES = {
    "source_config.toml": "config.toml",
    "source_direct_workers.json": "direct_workers.json",
    "source_input_config.toml": "inputs/source_config.toml",
    "source_inputs_manifest.json": "inputs/manifest.json",
    "source_provenance.txt": "provenance.txt",
}
SELECTION_FILES = {
    "repair_config.toml": "repair_config.toml",
    "repair_selection_manifest.json": "repair_manifest.json",
}
ROLLOUT_CONCURRENCY = 96
PROVIDER_CONCURRENCY = 48
QUEUE_SIZE = 48
VMVM_LEASE_CONCURRENCY = 4
CAPACITY_SMOKE_REQUESTS = 96
CAPACITY_SMOKE_KIND = "qwen-direct-serving-generation-capacity-smoke"
CAPACITY_SMOKE_SCHEMA_VERSION = 1
BUNDLE_FILES = frozenset(
    {
        *SOURCE_FILES,
        *SELECTION_FILES,
        PREFIX_ROWS_FILENAME,
        TARGET_MANIFEST_FILENAME,
        GENERATION_CONFIG_FILENAME,
    }
)
RUNTIME_FILES = (
    "direct_qwen_workers.py",
    "finalize_qwen_repair_sft.py",
    "materialize_qwen_repair.py",
    "merge_qwen_sft.py",
    "migrate_qwen_serving_generation.py",
    "qwen_repair_chain.py",
    "run_eval.sbatch",
    "run_qwen_direct_eval.sbatch",
    "run_qwen_repair_chain.sbatch",
    "snapshot_eval_inputs.py",
    "validate_task_approval.py",
)


class GenerationMigrationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise GenerationMigrationError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class BundleInputs:
    source_dir: Path
    selection_dir: Path
    deployment_root: Path
    repair_run_dir: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class SelectionBinding:
    manifest_sha256: str
    task_file_sha256: str
    union_indices_sha256: str
    union_count: int
    missing_count: int
    strict_invalid_count: int
    source_artifacts: Mapping[str, Mapping[str, int | str]]


CapacityRequester = Callable[[str, bytes, str, float], str]


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, indent=2, sort_keys=True).encode() + b"\n"


def _artifact(path: Path, code: str) -> dict[str, int | str]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("not regular")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1 << 20):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise GenerationMigrationError(code) from error
    finally:
        with contextlib.suppress(UnboundLocalError, OSError):
            os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise GenerationMigrationError(code)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _read_regular(
    path: Path,
    code: str,
    *,
    limit: int = MAX_METADATA_BYTES,
    required_mode: int | None = None,
) -> tuple[bytes, dict[str, int | str]]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > limit
            or (required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode)
        ):
            raise OSError("invalid regular file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            body = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
    except OSError as error:
        raise GenerationMigrationError(code) from error
    finally:
        if "descriptor" in locals() and descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
    if len(body) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise GenerationMigrationError(code)
    return body, {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def _read_json_artifact(
    path: Path,
    code: str,
    *,
    required_mode: int | None = None,
) -> tuple[dict[str, Any], dict[str, int | str]]:
    body, artifact = _read_regular(path, code, required_mode=required_mode)
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, ValueError) as error:
        raise GenerationMigrationError(code) from error
    if not isinstance(value, dict):
        raise GenerationMigrationError(code)
    return value, artifact


def _read_json(path: Path, code: str) -> dict[str, Any]:
    return _read_json_artifact(path, code)[0]


def _directory(path: Path, code: str, *, new: bool = False) -> Path:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise GenerationMigrationError(code)
    try:
        if new:
            parent = path.parent.resolve(strict=True)
            if parent / path.name != path or os.path.lexists(path):
                raise OSError("not new")
            return path
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise GenerationMigrationError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise GenerationMigrationError(code)
    return path


def _load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(path, "generation_contract_invalid")
    source = contract.get("source_generation")
    target = contract.get("target_generation")
    repair = contract.get("repair")
    routing = contract.get("routing")
    if (
        contract.get("kind") != "qwen-direct-repair-serving-generation-contract"
        or contract.get("schema_version") != 1
        or contract.get("server_identifier") != SERVER_IDENTIFIER
        or contract.get("model") != direct.EXPECTED_MODEL
        or not isinstance(source, dict)
        or not isinstance(target, dict)
        or not isinstance(repair, dict)
        or not isinstance(routing, dict)
        or source.get("worker_count") != 16
        or source.get("routing_epoch") != 3
        or source.get("results_row_count") != 1_392
        or not isinstance(source.get("canonical_path"), str)
        or not source["canonical_path"].startswith("/")
        or target.get("worker_count") != 24
        or (
            target.get("expected_overlap_workers"),
            target.get("expected_retired_workers"),
            target.get("expected_added_workers"),
        )
        != (15, 1, 9)
        or (
            repair.get("approved_task_count"),
            repair.get("missing_or_errored_count"),
            repair.get("strict_invalid_pass_count"),
            repair.get("repair_union_count"),
        )
        != (2_500, 1_151, 2, 1_153)
        or routing
        != {
            "capacity_smoke_requests": CAPACITY_SMOKE_REQUESTS,
            "max_concurrent_requests": PROVIDER_CONCURRENCY,
            "policy": "consistent_hash",
            "queue_size": QUEUE_SIZE,
            "request_id_headers": ["x-session-id"],
            "rollout_concurrency": ROLLOUT_CONCURRENCY,
            "vmvm_lease_concurrency": VMVM_LEASE_CONCURRENCY,
        }
        or any(
            not isinstance(value, str) or SHA256.fullmatch(value) is None
            for value in (
                source.get("spec_sha256"),
                source.get("endpoint_bundle_sha256"),
                target.get("spec_sha256"),
                target.get("endpoint_bundle_sha256"),
            )
        )
        or not isinstance(source.get("artifacts"), dict)
        or set(source["artifacts"]) != {*SOURCE_FILES.values(), "results.jsonl"}
        or any(
            not isinstance(record, dict)
            or set(record) != {"sha256", "size_bytes"}
            or not isinstance(record.get("sha256"), str)
            or SHA256.fullmatch(record["sha256"]) is None
            or not isinstance(record.get("size_bytes"), int)
            or isinstance(record.get("size_bytes"), bool)
            or record["size_bytes"] < 0
            for record in source["artifacts"].values()
        )
        or not isinstance(target.get("deployment_root"), str)
        or not target["deployment_root"].startswith("/")
    ):
        raise GenerationMigrationError("generation_contract_invalid")
    return contract


def _git(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GenerationMigrationError("code_provenance_invalid") from error
    if result.stderr:
        raise GenerationMigrationError("code_provenance_invalid")
    return result.stdout.strip()


def _code_state() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[3]
    revision = migration._repository_revision()
    tree = _git(repository, "rev-parse", f"{revision}^{{tree}}")
    submodules: dict[str, str] = {}
    for relative in ("deps/pydantic-config", "deps/renderers", "deps/verifiers"):
        fields = _git(repository, "ls-tree", revision, "--", relative).split(maxsplit=3)
        if len(fields) != 4 or fields[:2] != ["160000", "commit"] or fields[3] != relative:
            raise GenerationMigrationError("code_provenance_invalid")
        if _git(repository / relative, "rev-parse", "HEAD") != fields[2] or _git(
            repository / relative, "status", "--porcelain=v1", "--untracked-files=all"
        ):
            raise GenerationMigrationError("code_provenance_invalid")
        submodules[relative] = fields[2]
    workflow = Path(__file__).resolve().parent
    return {
        "revision": revision,
        "tree": tree,
        "submodules": submodules,
        "runtime_files": {
            name: _artifact(workflow / name, "code_provenance_invalid")["sha256"] for name in RUNTIME_FILES
        },
    }


def _source_artifacts(source: Path) -> dict[str, dict[str, int | str]]:
    return {
        relative: _artifact(source / relative, "source_artifact_invalid")
        for relative in (*SOURCE_FILES.values(), "results.jsonl")
    }


def _selection_artifacts(selection: Path) -> dict[str, dict[str, int | str]]:
    return {
        relative: _artifact(selection / relative, "repair_selection_invalid")
        for relative in (
            "repair_config.toml",
            "repair_manifest.json",
            "repair_missing_or_errored_tasks.txt",
            "repair_strict_invalid_pass_tasks.txt",
            "repair_tasks.txt",
        )
    }


def _load_selection(selection: Path, contract: Mapping[str, Any]) -> SelectionBinding:
    import finalize_qwen_repair_sft as finalizer

    manifest_path = selection / "repair_manifest.json"
    manifest_artifact = _artifact(manifest_path, "repair_selection_invalid")
    try:
        loaded = finalizer._load_repair_selection(
            manifest_path,
            str(manifest_artifact["sha256"]),
            contract["repair"]["repair_union_count"],
        )
    except finalizer.RepairFinalizationError as error:
        raise GenerationMigrationError("repair_selection_invalid") from error
    manifest = _read_json(manifest_path, "repair_selection_invalid")
    source = manifest.get("source")
    source_artifacts = source.get("artifacts") if isinstance(source, dict) else None
    expected = contract["source_generation"]["artifacts"]
    mapping = {
        "config": "config.toml",
        "direct_workers": "direct_workers.json",
        "inputs_manifest": "inputs/manifest.json",
        "source_config": "inputs/source_config.toml",
        "provenance": "provenance.txt",
        "results": "results.jsonl",
    }
    if (
        not isinstance(source_artifacts, dict)
        or any(source_artifacts.get(name) != expected[path] for name, path in mapping.items())
        or (
            loaded.approved_task_count,
            loaded.missing_or_errored_count,
            loaded.strict_invalid_pass_count,
            loaded.task_count,
        )
        != (2_500, 1_151, 2, 1_153)
    ):
        raise GenerationMigrationError("repair_selection_contract_mismatch")
    return SelectionBinding(
        manifest_sha256=str(manifest_artifact["sha256"]),
        task_file_sha256=loaded.task_file_sha256,
        union_indices_sha256=loaded.repair_union_indices_sha256,
        union_count=loaded.task_count,
        missing_count=loaded.missing_or_errored_count,
        strict_invalid_count=loaded.strict_invalid_pass_count,
        source_artifacts=source_artifacts,
    )


def _prefix(path: Path) -> tuple[dict[str, int | str], bytes, int]:
    digest = hashlib.sha256()
    rows: list[str] = []
    size = 0
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise OSError("not regular")
            for raw in handle:
                if not raw.endswith(b"\n") or not raw.strip():
                    raise GenerationMigrationError("source_results_prefix_invalid")
                digest.update(raw)
                size += len(raw)
                rows.append(hashlib.sha256(raw).hexdigest())
            after = os.fstat(handle.fileno())
    except OSError as error:
        raise GenerationMigrationError("source_results_prefix_invalid") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or len(rows) != len(set(rows)):
        raise GenerationMigrationError("source_results_prefix_invalid")
    body = "".join(f"{value}\n" for value in rows).encode()
    return {"sha256": digest.hexdigest(), "size_bytes": size}, body, len(rows)


def _workers(manifest: Mapping[str, Any]) -> list[direct.Worker]:
    values = manifest.get("workers")
    if not isinstance(values, list):
        raise GenerationMigrationError("worker_manifest_invalid")
    try:
        workers = [direct.Worker(**value) for value in values]
    except (TypeError, ValueError) as error:
        raise GenerationMigrationError("worker_manifest_invalid") from error
    if any(set(value) != direct.EXPECTED_WORKER_KEYS for value in values if isinstance(value, dict)):
        raise GenerationMigrationError("worker_manifest_invalid")
    return workers


def _identities(workers: Sequence[direct.Worker]) -> tuple[str, ...]:
    identities = tuple(
        sorted(
            hashlib.sha256(
                _json_bytes({"host": worker.host, "port": worker.port, "started_at": worker.started_at})
            ).hexdigest()
            for worker in workers
        )
    )
    if len(identities) != len(set(identities)):
        raise GenerationMigrationError("worker_identity_duplicate")
    return identities


def _target_manifest(
    contract: Mapping[str, Any],
    deployment: Path,
    workers: list[direct.Worker],
    task_sha256: str,
    repair_run: Path,
) -> dict[str, Any]:
    router_port, metrics_port = direct.derive_ports(repair_run)
    return {
        "admission": {
            "client_max_connections": PROVIDER_CONCURRENCY,
            "client_max_keepalive_connections": PROVIDER_CONCURRENCY,
            "rollout_concurrency": ROLLOUT_CONCURRENCY,
            "router_max_concurrent_requests": PROVIDER_CONCURRENCY,
            "router_queue_size": QUEUE_SIZE,
            "schema_version": direct.ADMISSION_SCHEMA_VERSION,
        },
        "approved_task_allowlist_sha256": task_sha256,
        "deployment_root": str(deployment),
        "endpoint_bundle_sha256": contract["target_generation"]["endpoint_bundle_sha256"],
        "model": direct.EXPECTED_MODEL,
        "router": {
            "host": "127.0.0.1",
            "max_concurrent_requests": PROVIDER_CONCURRENCY,
            "metrics_host": "127.0.0.1",
            "metrics_port": metrics_port,
            "policy": "consistent_hash",
            "port": router_port,
            "queue_size": QUEUE_SIZE,
            "queue_timeout_seconds": direct.ROUTER_QUEUE_TIMEOUT_SECONDS,
            "request_id_headers": ["x-session-id"],
            "request_timeout_seconds": 7_500,
            "retries": 0,
        },
        "schema_version": direct.ROUTER_MANIFEST_SCHEMA_VERSION,
        "spec_sha256": contract["target_generation"]["spec_sha256"],
        "workers": [
            {
                "host": worker.host,
                "metadata_file": worker.metadata_file,
                "metadata_sha256": worker.metadata_sha256,
                "port": worker.port,
                "started_at": worker.started_at,
            }
            for worker in workers
        ],
    }


def _generation_config(source: bytes) -> bytes:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GenerationMigrationError("repair_config_invalid") from error
    for key, value in (
        ("max_concurrent", ROLLOUT_CONCURRENCY),
        ("multiplex", ROLLOUT_CONCURRENCY),
        ("max_connections", PROVIDER_CONCURRENCY),
        ("max_keepalive_connections", PROVIDER_CONCURRENCY),
    ):
        text, count = re.subn(rf"(?m)^(\s*{key}\s*=\s*).*$", rf"\g<1>{value}", text)
        if count != 1:
            raise GenerationMigrationError("repair_config_invalid")
    return text.encode()


def _validate_generation_config(path: Path, task_file: Path, task_sha256: str) -> None:
    try:
        direct.validate_eval_config(
            path,
            approved_task_file=task_file,
            approved_task_file_sha256=task_sha256,
            expected_capacity=(ROLLOUT_CONCURRENCY, PROVIDER_CONCURRENCY),
        )
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, direct.DirectWorkerError) as error:
        raise GenerationMigrationError("repair_generation_config_invalid") from error
    if any(config.get(key) != 262_144 for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")):
        raise GenerationMigrationError("repair_generation_config_invalid")


def _manifest_bundle(workers: Sequence[direct.Worker]) -> str:
    digest = hashlib.sha256()
    for worker in workers:
        digest.update(f"{worker.metadata_sha256}  {worker.metadata_file}\n".encode())
    return digest.hexdigest()


def _copy(source: Path, destination: Path) -> None:
    migration._atomic_write(destination, source.read_bytes(), mode=0o600, exclusive=True)


def _validate_bundle(
    bundle: Path,
    inputs: BundleInputs,
    contract: Mapping[str, Any],
    *,
    contract_path: Path = CONTRACT_PATH,
    allow_incomplete: bool = False,
    code_state: Callable[[], Mapping[str, Any]] | None = None,
    source_manifest_validator: Callable[[Path], Mapping[str, Any]] | None = None,
    selection_loader: Callable[[Path, Mapping[str, Any]], SelectionBinding] | None = None,
) -> tuple[dict[str, Any], str]:
    code_state = code_state or _code_state
    source_manifest_validator = source_manifest_validator or direct.validate_saved_manifest
    selection_loader = selection_loader or _load_selection
    if not allow_incomplete:
        direct.reject_incomplete_migration(bundle)
    transition, transition_artifact = _read_json_artifact(bundle / TRANSITION_FILENAME, "transition_invalid")
    expected_names = {*BUNDLE_FILES, TRANSITION_FILENAME}
    if allow_incomplete:
        expected_names.add(direct.MIGRATION_INCOMPLETE_FILENAME)
    if (
        set(transition)
        != {
            "artifacts",
            "code",
            "contract_sha256",
            "kind",
            "repair_run",
            "repair_selection",
            "routing",
            "schema_version",
            "server_identifier",
            "source_generation",
            "target_generation",
            "worker_set_transition",
        }
        or transition.get("kind") != KIND
        or transition.get("schema_version") != SCHEMA_VERSION
        or transition.get("server_identifier") != SERVER_IDENTIFIER
        or transition.get("contract_sha256") != _artifact(contract_path, "generation_contract_invalid")["sha256"]
        or {entry.name for entry in bundle.iterdir()} != expected_names
        or transition.get("routing") != contract["routing"]
        or transition.get("code") != code_state()
    ):
        raise GenerationMigrationError("transition_invalid")
    artifacts = transition.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != BUNDLE_FILES:
        raise GenerationMigrationError("transition_artifacts_invalid")
    for name in BUNDLE_FILES:
        if artifacts.get(name) != _artifact(bundle / name, "transition_artifacts_invalid"):
            raise GenerationMigrationError("transition_artifacts_invalid")

    source_artifacts = _source_artifacts(inputs.source_dir)
    if source_artifacts != contract["source_generation"]["artifacts"] or any(
        artifacts[bundle_name] != source_artifacts[source_name] for bundle_name, source_name in SOURCE_FILES.items()
    ):
        raise GenerationMigrationError("source_artifact_mismatch")
    prefix_artifact, prefix_body, row_count = _prefix(inputs.source_dir / "results.jsonl")
    if (
        prefix_artifact != source_artifacts["results.jsonl"]
        or row_count != contract["source_generation"]["results_row_count"]
        or (bundle / PREFIX_ROWS_FILENAME).read_bytes() != prefix_body
    ):
        raise GenerationMigrationError("source_prefix_mismatch")
    selection = selection_loader(inputs.selection_dir, contract)
    selection_artifacts = _selection_artifacts(inputs.selection_dir)
    if any(
        artifacts[bundle_name] != selection_artifacts[source_name]
        for bundle_name, source_name in SELECTION_FILES.items()
    ):
        raise GenerationMigrationError("repair_selection_changed")
    if (bundle / GENERATION_CONFIG_FILENAME).read_bytes() != _generation_config(
        (bundle / "repair_config.toml").read_bytes()
    ):
        raise GenerationMigrationError("repair_generation_config_invalid")
    _validate_generation_config(
        bundle / GENERATION_CONFIG_FILENAME,
        inputs.selection_dir / "repair_tasks.txt",
        selection.task_file_sha256,
    )

    try:
        source_manifest = source_manifest_validator(bundle / SOURCE_MANIFEST_FILENAME)
    except (OSError, ValueError, direct.DirectWorkerError) as error:
        raise GenerationMigrationError("source_manifest_invalid") from error
    source_workers = _workers(source_manifest)
    target_manifest = _read_json(bundle / TARGET_MANIFEST_FILENAME, "target_manifest_invalid")
    target_workers = _workers(target_manifest)
    if (
        target_manifest
        != _target_manifest(
            contract, inputs.deployment_root, target_workers, selection.task_file_sha256, inputs.repair_run_dir
        )
        or len(target_workers) != 24
        or _manifest_bundle(target_workers) != contract["target_generation"]["endpoint_bundle_sha256"]
    ):
        raise GenerationMigrationError("target_manifest_invalid")
    source_ids, target_ids = set(_identities(source_workers)), set(_identities(target_workers))
    counts = (len(source_ids & target_ids), len(source_ids - target_ids), len(target_ids - source_ids))
    if counts != (15, 1, 9):
        raise GenerationMigrationError("worker_set_transition_invalid")
    expected_source = {
        "canonical_path": str(inputs.source_dir),
        "manifest_sha256": artifacts[SOURCE_MANIFEST_FILENAME]["sha256"],
        "results": {
            **prefix_artifact,
            "row_count": row_count,
            "row_hashes_sha256": artifacts[PREFIX_ROWS_FILENAME]["sha256"],
        },
        "spec_sha256": contract["source_generation"]["spec_sha256"],
        "endpoint_bundle_sha256": contract["source_generation"]["endpoint_bundle_sha256"],
        "worker_count": 16,
        "worker_identities": sorted(source_ids),
    }
    expected_target = {
        "deployment_root": str(inputs.deployment_root),
        "manifest_sha256": artifacts[TARGET_MANIFEST_FILENAME]["sha256"],
        "spec_sha256": contract["target_generation"]["spec_sha256"],
        "endpoint_bundle_sha256": contract["target_generation"]["endpoint_bundle_sha256"],
        "worker_count": 24,
        "worker_identities": sorted(target_ids),
    }
    expected_selection = {
        "artifacts": selection_artifacts,
        "canonical_path": str(inputs.selection_dir),
        "manifest_sha256": selection.manifest_sha256,
        "task_file_sha256": selection.task_file_sha256,
        "union_indices_sha256": selection.union_indices_sha256,
        "union_count": selection.union_count,
        "missing_count": selection.missing_count,
        "strict_invalid_count": selection.strict_invalid_count,
    }
    worker_transition = transition.get("worker_set_transition")
    if (
        transition.get("source_generation") != expected_source
        or transition.get("target_generation") != expected_target
        or transition.get("repair_selection") != expected_selection
        or transition.get("repair_run")
        != {
            "canonical_path": str(inputs.repair_run_dir),
            "manifest_sha256": artifacts[TARGET_MANIFEST_FILENAME]["sha256"],
        }
        or not isinstance(worker_transition, dict)
        or (
            worker_transition.get("overlap_count"),
            worker_transition.get("retired_count"),
            worker_transition.get("added_count"),
        )
        != counts
    ):
        raise GenerationMigrationError("transition_binding_mismatch")
    return transition, str(transition_artifact["sha256"])


def materialize(
    inputs: BundleInputs,
    *,
    contract_path: Path = CONTRACT_PATH,
    terminal_check: Callable[[str], bool] = migration.slurm_job_is_terminal,
    source_auditor: Callable[[Path], Mapping[str, Any]] = direct.audit_run_directory,
    worker_loader: Callable[..., tuple[list[direct.Worker], str, str]] = direct.load_workers,
    worker_probe: Callable[[list[direct.Worker]], None] = direct.probe_workers,
    code_state: Callable[[], Mapping[str, Any]] = _code_state,
    source_manifest_validator: Callable[[Path], Mapping[str, Any]] = direct.validate_saved_manifest,
    selection_loader: Callable[[Path, Mapping[str, Any]], SelectionBinding] = _load_selection,
) -> dict[str, Any]:
    contract = _load_contract(contract_path)
    source = _directory(inputs.source_dir, "source_path_invalid")
    selection = _directory(inputs.selection_dir, "repair_selection_path_invalid")
    deployment = _directory(inputs.deployment_root, "target_deployment_path_invalid")
    repair_run = _directory(inputs.repair_run_dir, "repair_run_path_invalid", new=True)
    output = _directory(inputs.output_dir, "transition_output_path_invalid", new=True)
    resolved = BundleInputs(source, selection, deployment, repair_run, output)
    if output.parent != selection or output.name != RUN_BUNDLE_DIRECTORY:
        raise GenerationMigrationError("transition_output_scope_invalid")
    if str(deployment) != contract["target_generation"]["deployment_root"]:
        raise GenerationMigrationError("target_deployment_path_mismatch")
    if str(source) != contract["source_generation"]["canonical_path"]:
        raise GenerationMigrationError("source_path_mismatch")
    try:
        with migration._source_locks(source):
            if any(not terminal_check(job) for job in migration._provenance_job_ids(source / "provenance.txt")):
                raise GenerationMigrationError("source_job_not_terminal")
            summary = source_auditor(source)
            if (
                summary.get("ok") is not True
                or summary.get("routing_epoch") != 3
                or summary.get("endpoints") != 16
                or summary.get("spec_sha256") != contract["source_generation"]["spec_sha256"]
                or summary.get("endpoint_bundle_sha256") != contract["source_generation"]["endpoint_bundle_sha256"]
                or summary.get("manifest_schema_version") != 3
                or summary.get("provider_concurrency") != 32
                or summary.get("queue_size") != 32
                or summary.get("router_policy") != "consistent_hash"
                or summary.get("request_id_headers") != ["x-session-id"]
            ):
                raise GenerationMigrationError("source_routing_contract_invalid")
            if _source_artifacts(source) != contract["source_generation"]["artifacts"]:
                raise GenerationMigrationError("source_artifact_mismatch")
            selection_binding = selection_loader(selection, contract)
            workers, spec, endpoint_bundle = worker_loader(
                deployment,
                expected_spec_sha256=contract["target_generation"]["spec_sha256"],
                expected_bundle_sha256=contract["target_generation"]["endpoint_bundle_sha256"],
                expected_count=24,
            )
            worker_probe(workers)
            if (len(workers), spec, endpoint_bundle) != (
                24,
                contract["target_generation"]["spec_sha256"],
                contract["target_generation"]["endpoint_bundle_sha256"],
            ):
                raise GenerationMigrationError("target_generation_mismatch")
            source_manifest = _read_json(source / "direct_workers.json", "source_manifest_invalid")
            source_ids, target_ids = set(_identities(_workers(source_manifest))), set(_identities(workers))
            counts = (len(source_ids & target_ids), len(source_ids - target_ids), len(target_ids - source_ids))
            if counts != (15, 1, 9):
                raise GenerationMigrationError("worker_set_transition_invalid")
            target_manifest = _target_manifest(
                contract, deployment, workers, selection_binding.task_file_sha256, repair_run
            )
            prefix_artifact, prefix_body, row_count = _prefix(source / "results.jsonl")
            if (prefix_artifact, row_count) != (
                contract["source_generation"]["artifacts"]["results.jsonl"],
                1_392,
            ):
                raise GenerationMigrationError("source_prefix_mismatch")
            code = code_state()
            staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=selection))
            try:
                for destination, relative in SOURCE_FILES.items():
                    _copy(source / relative, staging / destination)
                for destination, relative in SELECTION_FILES.items():
                    _copy(selection / relative, staging / destination)
                migration._atomic_write(
                    staging / GENERATION_CONFIG_FILENAME,
                    _generation_config((selection / "repair_config.toml").read_bytes()),
                    exclusive=True,
                )
                migration._atomic_write(staging / PREFIX_ROWS_FILENAME, prefix_body, exclusive=True)
                migration._atomic_write(
                    staging / TARGET_MANIFEST_FILENAME, _json_bytes(target_manifest), exclusive=True
                )
                artifacts = {name: _artifact(staging / name, "transition_artifact_invalid") for name in BUNDLE_FILES}
                selection_artifacts = _selection_artifacts(selection)
                transition = {
                    "artifacts": artifacts,
                    "code": code,
                    "contract_sha256": _artifact(contract_path, "generation_contract_invalid")["sha256"],
                    "kind": KIND,
                    "repair_run": {
                        "canonical_path": str(repair_run),
                        "manifest_sha256": artifacts[TARGET_MANIFEST_FILENAME]["sha256"],
                    },
                    "repair_selection": {
                        "artifacts": selection_artifacts,
                        "canonical_path": str(selection),
                        "manifest_sha256": selection_binding.manifest_sha256,
                        "task_file_sha256": selection_binding.task_file_sha256,
                        "union_indices_sha256": selection_binding.union_indices_sha256,
                        "union_count": selection_binding.union_count,
                        "missing_count": selection_binding.missing_count,
                        "strict_invalid_count": selection_binding.strict_invalid_count,
                    },
                    "routing": contract["routing"],
                    "schema_version": SCHEMA_VERSION,
                    "server_identifier": SERVER_IDENTIFIER,
                    "source_generation": {
                        "canonical_path": str(source),
                        "manifest_sha256": artifacts[SOURCE_MANIFEST_FILENAME]["sha256"],
                        "results": {
                            **prefix_artifact,
                            "row_count": row_count,
                            "row_hashes_sha256": artifacts[PREFIX_ROWS_FILENAME]["sha256"],
                        },
                        "spec_sha256": contract["source_generation"]["spec_sha256"],
                        "endpoint_bundle_sha256": contract["source_generation"]["endpoint_bundle_sha256"],
                        "worker_count": 16,
                        "worker_identities": sorted(source_ids),
                    },
                    "target_generation": {
                        "deployment_root": str(deployment),
                        "manifest_sha256": artifacts[TARGET_MANIFEST_FILENAME]["sha256"],
                        "spec_sha256": spec,
                        "endpoint_bundle_sha256": endpoint_bundle,
                        "worker_count": 24,
                        "worker_identities": sorted(target_ids),
                    },
                    "worker_set_transition": {
                        "overlap_count": counts[0],
                        "retired_count": counts[1],
                        "added_count": counts[2],
                    },
                }
                migration._atomic_write(staging / TRANSITION_FILENAME, _json_bytes(transition), exclusive=True)

                def validate(path: Path, incomplete: bool) -> None:
                    _validate_bundle(
                        path,
                        resolved,
                        contract,
                        contract_path=contract_path,
                        allow_incomplete=incomplete,
                        code_state=lambda: code,
                        source_manifest_validator=source_manifest_validator,
                        selection_loader=selection_loader,
                    )

                migration._publish_directory(staging, output, validate)
                if not staging.exists():
                    staging = None
            finally:
                if staging is not None and staging.exists():
                    shutil.rmtree(staging)
    except migration.MigrationError as error:
        raise GenerationMigrationError(str(error)) from error
    transition_sha256 = _artifact(output / TRANSITION_FILENAME, "transition_invalid")["sha256"]
    return {
        "added_workers": counts[2],
        "ok": True,
        "overlap_workers": counts[0],
        "repair_union_count": selection_binding.union_count,
        "retired_workers": counts[1],
        "server_identifier": SERVER_IDENTIFIER,
        "source_rows": row_count,
        "status": "materialized",
        "target_workers": len(workers),
        "transition_sha256": transition_sha256,
    }


def _bundle_inputs(bundle: Path, contract: Mapping[str, Any]) -> BundleInputs:
    transition = _read_json(bundle / TRANSITION_FILENAME, "transition_invalid")
    try:
        inputs = BundleInputs(
            _directory(Path(transition["source_generation"]["canonical_path"]), "source_path_invalid"),
            _directory(Path(transition["repair_selection"]["canonical_path"]), "repair_selection_path_invalid"),
            _directory(Path(transition["target_generation"]["deployment_root"]), "target_deployment_path_invalid"),
            Path(transition["repair_run"]["canonical_path"]),
            bundle,
        )
    except (KeyError, TypeError) as error:
        raise GenerationMigrationError("transition_binding_mismatch") from error
    if (
        str(inputs.source_dir) != contract["source_generation"]["canonical_path"]
        or str(inputs.deployment_root) != contract["target_generation"]["deployment_root"]
    ):
        raise GenerationMigrationError("transition_binding_mismatch")
    return inputs


def _lock_fd(run: Path, descriptor: int, name: str) -> None:
    try:
        descriptor_state = os.fstat(descriptor)
        path_state = (run / name).stat(follow_symlinks=False)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as error:
        raise GenerationMigrationError("launch_lock_invalid") from error
    if (descriptor_state.st_dev, descriptor_state.st_ino) != (path_state.st_dev, path_state.st_ino):
        raise GenerationMigrationError("launch_lock_invalid")


@contextlib.contextmanager
def _writer_available(run: Path) -> Iterator[None]:
    descriptor = os.open(run / ".writer.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GenerationMigrationError("writer_lock_busy") from error
        yield
    finally:
        os.close(descriptor)


def _capacity_payload() -> bytes:
    return json.dumps(
        {
            "max_tokens": 1,
            "messages": [{"content": "Reply with OK.", "role": "user"}],
            "model": direct.EXPECTED_MODEL,
            "stream": False,
            "temperature": 0,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _capacity_request(base_url: str, payload: bytes, session_id: str, timeout: float) -> str:
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": "Bearer EMPTY",
            "Content-Type": "application/json",
            "x-session-id": session_id,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_METADATA_BYTES + 1)
            status_code = response.status
    except (OSError, urllib.error.URLError) as error:
        raise GenerationMigrationError("capacity_smoke_request_failed") from error
    if status_code != 200 or len(body) > MAX_METADATA_BYTES:
        raise GenerationMigrationError("capacity_smoke_request_failed")
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GenerationMigrationError("capacity_smoke_response_invalid") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("choices"), list) or not parsed["choices"]:
        raise GenerationMigrationError("capacity_smoke_response_invalid")
    return hashlib.sha256(body).hexdigest()


def _capacity_certificate(
    run: Path,
    transition_sha256: str,
    *,
    require_exists: bool,
) -> tuple[dict[str, Any], dict[str, int | str] | None]:
    path = run / CAPACITY_SMOKE_FILENAME
    if not require_exists and os.path.lexists(path):
        raise GenerationMigrationError("capacity_smoke_exists")
    certificate, certificate_artifact = (
        _read_json_artifact(path, "capacity_smoke_invalid", required_mode=0o600) if require_exists else ({}, None)
    )
    transition, transition_artifact = _read_json_artifact(
        run / RUN_BUNDLE_DIRECTORY / TRANSITION_FILENAME,
        "run_transition_invalid",
    )
    if transition_artifact["sha256"] != transition_sha256:
        raise GenerationMigrationError("run_transition_invalid")
    manifest_artifact = _artifact(run / "direct_workers.json", "run_manifest_invalid")
    if manifest_artifact != transition["artifacts"][TARGET_MANIFEST_FILENAME]:
        raise GenerationMigrationError("run_manifest_invalid")
    manifest_sha256 = manifest_artifact["sha256"]
    expected = {
        "client_parallelism": CAPACITY_SMOKE_REQUESTS,
        "client_peak_in_flight": CAPACITY_SMOKE_REQUESTS,
        "endpoint_bundle_sha256": transition["target_generation"]["endpoint_bundle_sha256"],
        "kind": CAPACITY_SMOKE_KIND,
        "provider_concurrency": PROVIDER_CONCURRENCY,
        "queue_size": QUEUE_SIZE,
        "request_id_header": "x-session-id",
        "request_payload_sha256": hashlib.sha256(_capacity_payload()).hexdigest(),
        "rollout_concurrency": ROLLOUT_CONCURRENCY,
        "schema_version": CAPACITY_SMOKE_SCHEMA_VERSION,
        "server_identifier": SERVER_IDENTIFIER,
        "spec_sha256": transition["target_generation"]["spec_sha256"],
        "successful_requests": CAPACITY_SMOKE_REQUESTS,
        "target_manifest_sha256": manifest_sha256,
        "target_workers": 24,
        "transition_sha256": transition_sha256,
        "vmvm_lease_concurrency": VMVM_LEASE_CONCURRENCY,
    }
    if require_exists:
        if set(certificate) != {*expected, "elapsed_milliseconds", "response_digests_sha256"} or any(
            certificate.get(key) != value for key, value in expected.items()
        ):
            raise GenerationMigrationError("capacity_smoke_invalid")
        elapsed = certificate.get("elapsed_milliseconds")
        if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < 1:
            raise GenerationMigrationError("capacity_smoke_invalid")
        response_digest = certificate.get("response_digests_sha256")
        if not isinstance(response_digest, str) or SHA256.fullmatch(response_digest) is None:
            raise GenerationMigrationError("capacity_smoke_invalid")
    return expected, certificate_artifact


def capacity_smoke(
    run_dir: Path,
    base_url: str,
    expected_transition_sha256: str,
    *,
    router_lock_fd: int,
    requester: CapacityRequester = _capacity_request,
) -> dict[str, Any]:
    run = _directory(run_dir, "repair_run_path_invalid")
    _lock_fd(run, router_lock_fd, ".direct_router.lock")
    marker = run / direct.MIGRATION_INCOMPLETE_FILENAME
    if marker.read_bytes() != f"qwen-serving-generation-v1\n{expected_transition_sha256}\n".encode():
        raise GenerationMigrationError("launch_marker_invalid")
    bundle = _directory(run / RUN_BUNDLE_DIRECTORY, "run_transition_invalid")
    if _artifact(bundle / TRANSITION_FILENAME, "run_transition_invalid")["sha256"] != expected_transition_sha256:
        raise GenerationMigrationError("run_transition_invalid")
    manifest = _read_json(run / "direct_workers.json", "run_manifest_invalid")
    router = manifest.get("router")
    if (
        not isinstance(router, dict)
        or base_url != f"http://127.0.0.1:{router.get('port')}/v1"
        or manifest.get("workers") is None
        or len(manifest["workers"]) != 24
    ):
        raise GenerationMigrationError("capacity_smoke_router_invalid")
    _capacity_certificate(run, expected_transition_sha256, require_exists=False)

    payload = _capacity_payload()
    start = threading.Barrier(CAPACITY_SMOKE_REQUESTS)
    in_flight = threading.Barrier(CAPACITY_SMOKE_REQUESTS)
    counter_lock = threading.Lock()
    active = 0
    peak = 0

    def request(index: int) -> str:
        nonlocal active, peak
        try:
            start.wait(timeout=30)
            with counter_lock:
                active += 1
                peak = max(peak, active)
            in_flight.wait(timeout=30)
        except threading.BrokenBarrierError as error:
            raise GenerationMigrationError("capacity_smoke_parallelism_failed") from error
        session_id = hashlib.sha256(f"{expected_transition_sha256}:{index}".encode()).hexdigest()
        try:
            return requester(base_url, payload, session_id, 900)
        finally:
            with counter_lock:
                active -= 1

    started = time.monotonic_ns()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=CAPACITY_SMOKE_REQUESTS) as executor:
            response_digests = list(executor.map(request, range(CAPACITY_SMOKE_REQUESTS)))
    except Exception as error:
        if isinstance(error, GenerationMigrationError):
            raise
        raise GenerationMigrationError("capacity_smoke_failed") from error
    if (
        peak != CAPACITY_SMOKE_REQUESTS
        or len(response_digests) != CAPACITY_SMOKE_REQUESTS
        or any(SHA256.fullmatch(value) is None for value in response_digests)
    ):
        raise GenerationMigrationError("capacity_smoke_failed")
    certificate = {
        **_capacity_certificate(run, expected_transition_sha256, require_exists=False)[0],
        "elapsed_milliseconds": max(1, (time.monotonic_ns() - started) // 1_000_000),
        "response_digests_sha256": hashlib.sha256("".join(response_digests).encode()).hexdigest(),
    }
    try:
        migration._atomic_write(
            run / CAPACITY_SMOKE_FILENAME,
            _json_bytes(certificate),
            exclusive=True,
        )
    except migration.MigrationError as error:
        raise GenerationMigrationError("capacity_smoke_publish_failed") from error
    return {
        "certificate_sha256": _artifact(run / CAPACITY_SMOKE_FILENAME, "capacity_smoke_invalid")["sha256"],
        "client_parallelism": CAPACITY_SMOKE_REQUESTS,
        "ok": True,
        "successful_requests": CAPACITY_SMOKE_REQUESTS,
    }


def _live_target(
    inputs: BundleInputs,
    transition: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[list[direct.Worker], dict[str, Any]]:
    try:
        workers, spec, bundle = direct.load_workers(
            inputs.deployment_root,
            expected_spec_sha256=contract["target_generation"]["spec_sha256"],
            expected_bundle_sha256=contract["target_generation"]["endpoint_bundle_sha256"],
            expected_count=24,
        )
        direct.probe_workers(workers)
    except direct.DirectWorkerError as error:
        raise GenerationMigrationError("target_generation_unavailable") from error
    expected = _target_manifest(
        contract,
        inputs.deployment_root,
        workers,
        transition["repair_selection"]["task_file_sha256"],
        inputs.repair_run_dir,
    )
    archived = _read_json(inputs.output_dir / TARGET_MANIFEST_FILENAME, "target_manifest_invalid")
    if archived != expected or (spec, bundle, _identities(workers)) != (
        transition["target_generation"]["spec_sha256"],
        transition["target_generation"]["endpoint_bundle_sha256"],
        tuple(transition["target_generation"]["worker_identities"]),
    ):
        raise GenerationMigrationError("target_generation_changed")
    return workers, archived


def prepare_launch(
    bundle_dir: Path,
    run_dir: Path,
    urls: Path,
    ports: Path,
    *,
    lock_fd: int,
    resume: bool,
    contract_path: Path = CONTRACT_PATH,
) -> dict[str, Any]:
    contract = _load_contract(contract_path)
    bundle = _directory(bundle_dir, "transition_path_invalid")
    run = _directory(run_dir, "repair_run_path_invalid")
    _lock_fd(run, lock_fd, ".direct_router.lock")
    inputs = _bundle_inputs(bundle, contract)
    if inputs.repair_run_dir != run:
        raise GenerationMigrationError("repair_run_path_mismatch")
    with migration._source_locks(inputs.source_dir):
        if any(
            not migration.slurm_job_is_terminal(job)
            for job in migration._provenance_job_ids(inputs.source_dir / "provenance.txt")
        ):
            raise GenerationMigrationError("source_job_not_terminal")
        transition, transition_sha = _validate_bundle(bundle, inputs, contract, contract_path=contract_path)
        workers, manifest = _live_target(inputs, transition, contract)
    run_bundle = run / RUN_BUNDLE_DIRECTORY
    marker = run / direct.MIGRATION_INCOMPLETE_FILENAME
    if resume:
        if (
            marker.exists()
            or _artifact(run_bundle / TRANSITION_FILENAME, "run_transition_invalid")["sha256"] != transition_sha
        ):
            raise GenerationMigrationError("run_transition_incomplete")
        with _writer_available(run):
            audit_repair_run(run, contract_path=contract_path)
    else:
        if {entry.name for entry in run.iterdir()} != {".direct_router.lock"}:
            raise GenerationMigrationError("repair_run_not_empty")
        migration._atomic_write(marker, f"qwen-serving-generation-v1\n{transition_sha}\n".encode(), exclusive=True)
        try:
            staging = run / f".{RUN_BUNDLE_DIRECTORY}.{os.getpid()}.tmp"
            staging.mkdir(mode=0o700)
            migration._clone_tree(bundle, staging)
            migration._rename_noreplace(staging, run_bundle)
            _copy(bundle / TARGET_MANIFEST_FILENAME, run / "direct_workers.json")
            migration._fsync_directory(run)
        except BaseException:
            with contextlib.suppress(OSError):
                shutil.rmtree(run_bundle)
            with contextlib.suppress(OSError):
                (run / "direct_workers.json").unlink()
            with contextlib.suppress(OSError):
                marker.unlink()
            raise
    migration._atomic_write(urls, "".join(f"{worker.url}\n" for worker in workers).encode())
    router = manifest["router"]
    migration._atomic_write(
        ports,
        "\n".join(
            map(
                str,
                (
                    router["port"],
                    router["metrics_port"],
                    PROVIDER_CONCURRENCY,
                    QUEUE_SIZE,
                    router["queue_timeout_seconds"],
                    "consistent_hash",
                    "x-session-id",
                    24,
                    transition_sha,
                ),
            )
        ).encode()
        + b"\n",
    )
    return {"ok": True, "resume": resume, "target_workers": 24, "transition_sha256": transition_sha}


def _validate_run_inputs(run: Path, transition: Mapping[str, Any], transition_sha: str) -> str:
    inputs = run / "inputs"
    manifest = _read_json(inputs / "manifest.json", "run_inputs_invalid")
    expected = {
        "config": (
            "source_config.toml",
            run / RUN_BUNDLE_DIRECTORY / GENERATION_CONFIG_FILENAME,
            transition["artifacts"][GENERATION_CONFIG_FILENAME]["sha256"],
        ),
        "task_file": (
            "task_file.txt",
            Path(transition["repair_selection"]["canonical_path"]) / "repair_tasks.txt",
            transition["repair_selection"]["task_file_sha256"],
        ),
    }
    for name, (snapshot_name, source, digest) in expected.items():
        record = manifest.get(name)
        snapshot = inputs / snapshot_name
        if (
            not isinstance(record, dict)
            or record.get("sha256") != digest
            or record.get("snapshot") != str(snapshot.resolve())
            or record.get("source") != str(source)
            or _artifact(snapshot, "run_inputs_invalid")["sha256"] != digest
        ):
            raise GenerationMigrationError("run_inputs_invalid")
    _fields, capacity_artifact = _capacity_certificate(run, transition_sha, require_exists=True)
    assert capacity_artifact is not None
    capacity_sha = str(capacity_artifact["sha256"])
    manifest_sha = _artifact(run / "direct_workers.json", "run_manifest_invalid")["sha256"]
    try:
        provenance = direct.validate_router_provenance(
            run / "provenance.txt",
            str(manifest_sha),
            PROVIDER_CONCURRENCY,
        )
    except direct.DirectWorkerError as error:
        raise GenerationMigrationError("run_provenance_invalid") from error
    router_port = _read_json(run / "direct_workers.json", "run_manifest_invalid")["router"]["port"]
    required = {
        "direct_qwen_manifest_sha256": manifest_sha,
        "direct_qwen_provider_concurrency": str(PROVIDER_CONCURRENCY),
        "direct_qwen_request_id_headers": "x-session-id",
        "direct_qwen_router_policy": "consistent_hash",
        "inference_base_url": f"http://127.0.0.1:{router_port}/v1",
        "prime_rl": transition["code"]["revision"],
        "qwen_serving_generation_capacity_smoke_sha256": capacity_sha,
        "qwen_serving_generation_transition_sha256": transition_sha,
        "renderers": transition["code"]["submodules"]["deps/renderers"],
        "verifiers": transition["code"]["submodules"]["deps/verifiers"],
    }
    if any(provenance.get(key) != value for key, value in required.items()) or provenance.get(
        "inference_deployment_id"
    ):
        raise GenerationMigrationError("run_provenance_invalid")
    current: dict[str, str] | None = None
    for line in (run / "provenance.txt").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise GenerationMigrationError("run_provenance_invalid")
        if key == "resume_slurm_job_id":
            if current is not None and (
                current.get("resume_qwen_serving_generation_transition_sha256") != transition_sha
                or current.get("resume_qwen_serving_generation_capacity_smoke_sha256") != capacity_sha
            ):
                raise GenerationMigrationError("run_provenance_invalid")
            current = {key: value}
        elif current is not None and key.startswith("resume_"):
            current[key] = value
    if current is not None and (
        current.get("resume_qwen_serving_generation_transition_sha256") != transition_sha
        or current.get("resume_qwen_serving_generation_capacity_smoke_sha256") != capacity_sha
    ):
        raise GenerationMigrationError("run_provenance_invalid")
    return capacity_sha


def commit_launch(
    run_dir: Path,
    expected_transition_sha256: str,
    *,
    router_lock_fd: int,
    writer_lock_fd: int,
    contract_path: Path = CONTRACT_PATH,
) -> dict[str, Any]:
    run = _directory(run_dir, "repair_run_path_invalid")
    _lock_fd(run, router_lock_fd, ".direct_router.lock")
    _lock_fd(run, writer_lock_fd, ".writer.lock")
    marker = run / direct.MIGRATION_INCOMPLETE_FILENAME
    if marker.read_bytes() != f"qwen-serving-generation-v1\n{expected_transition_sha256}\n".encode():
        raise GenerationMigrationError("launch_marker_invalid")
    bundle = _directory(run / RUN_BUNDLE_DIRECTORY, "run_transition_invalid")
    _transition, transition_artifact = _read_json_artifact(bundle / TRANSITION_FILENAME, "run_transition_invalid")
    if transition_artifact["sha256"] != expected_transition_sha256:
        raise GenerationMigrationError("run_transition_invalid")
    contract = _load_contract(contract_path)
    inputs = _bundle_inputs(bundle, contract)
    with migration._source_locks(inputs.source_dir):
        transition, validated_transition_sha256 = _validate_bundle(
            bundle,
            BundleInputs(inputs.source_dir, inputs.selection_dir, inputs.deployment_root, run, bundle),
            contract,
            contract_path=contract_path,
        )
    if validated_transition_sha256 != expected_transition_sha256:
        raise GenerationMigrationError("run_transition_invalid")
    if _artifact(run / "direct_workers.json", "run_manifest_invalid") != _artifact(
        bundle / TARGET_MANIFEST_FILENAME, "run_manifest_invalid"
    ):
        raise GenerationMigrationError("run_manifest_invalid")
    _validate_run_inputs(run, transition, expected_transition_sha256)
    marker.unlink()
    migration._fsync_directory(run)
    return {"ok": True, "status": "committed", "transition_sha256": expected_transition_sha256}


def audit_repair_run(run_dir: Path, *, contract_path: Path = CONTRACT_PATH) -> dict[str, Any]:
    run = _directory(run_dir, "repair_run_path_invalid")
    direct.reject_incomplete_migration(run)
    bundle = _directory(run / RUN_BUNDLE_DIRECTORY, "run_transition_invalid")
    contract = _load_contract(contract_path)
    inputs = _bundle_inputs(bundle, contract)
    with migration._source_locks(inputs.source_dir):
        transition, transition_sha = _validate_bundle(
            bundle,
            BundleInputs(inputs.source_dir, inputs.selection_dir, inputs.deployment_root, run, bundle),
            contract,
            contract_path=contract_path,
        )
    if _artifact(run / "direct_workers.json", "run_manifest_invalid") != _artifact(
        bundle / TARGET_MANIFEST_FILENAME, "run_manifest_invalid"
    ):
        raise GenerationMigrationError("run_manifest_invalid")
    capacity_sha = _validate_run_inputs(run, transition, transition_sha)
    task_file = run / "inputs" / "task_file.txt"
    task_sha = _artifact(task_file, "run_inputs_invalid")["sha256"]
    if (
        direct.validate_eval_config(
            run / "config.toml",
            approved_task_file=task_file,
            approved_task_file_sha256=task_sha,
            expected_capacity=(ROLLOUT_CONCURRENCY, PROVIDER_CONCURRENCY),
        )
        != task_sha
    ):
        raise GenerationMigrationError("run_config_invalid")
    results = _artifact(run / "results.jsonl", "run_results_invalid")
    return {
        "capacity_smoke_sha256": capacity_sha,
        "endpoint_bundle_sha256": transition["target_generation"]["endpoint_bundle_sha256"],
        "endpoints": 24,
        "manifest_schema_version": 3,
        "model": direct.EXPECTED_MODEL,
        "ok": True,
        "provider_concurrency": PROVIDER_CONCURRENCY,
        "queue_size": QUEUE_SIZE,
        "request_id_headers": ["x-session-id"],
        "results_sha256": results["sha256"],
        "results_size_bytes": results["size_bytes"],
        "rollout_concurrency": ROLLOUT_CONCURRENCY,
        "router_policy": "consistent_hash",
        "routing_epoch": 1,
        "serving_generation": 2,
        "serving_generation_transition_sha256": transition_sha,
        "spec_sha256": transition["target_generation"]["spec_sha256"],
        "vmvm_lease_concurrency": VMVM_LEASE_CONCURRENCY,
    }


def main() -> None:
    parser = StableArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize_parser = commands.add_parser("materialize")
    for name in ("source-dir", "selection-dir", "deployment-root", "repair-run-dir", "output-dir"):
        materialize_parser.add_argument(f"--{name}", type=Path, required=True)
    prepare_parser = commands.add_parser("prepare-launch")
    for name in ("bundle-dir", "run-dir", "urls-output", "ports-output"):
        prepare_parser.add_argument(f"--{name}", type=Path, required=True)
    prepare_parser.add_argument("--router-lock-fd", type=int, required=True)
    prepare_parser.add_argument("--resume", action="store_true")
    smoke_parser = commands.add_parser("capacity-smoke")
    smoke_parser.add_argument("--run-dir", type=Path, required=True)
    smoke_parser.add_argument("--base-url", required=True)
    smoke_parser.add_argument("--expected-transition-sha256", required=True)
    smoke_parser.add_argument("--router-lock-fd", type=int, required=True)
    commit_parser = commands.add_parser("commit-launch")
    commit_parser.add_argument("--run-dir", type=Path, required=True)
    commit_parser.add_argument("--expected-transition-sha256", required=True)
    commit_parser.add_argument("--router-lock-fd", type=int, required=True)
    commit_parser.add_argument("--writer-lock-fd", type=int, required=True)
    audit_parser = commands.add_parser("audit-run")
    audit_parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "materialize":
            summary = materialize(
                BundleInputs(
                    args.source_dir, args.selection_dir, args.deployment_root, args.repair_run_dir, args.output_dir
                )
            )
        elif args.command == "prepare-launch":
            summary = prepare_launch(
                args.bundle_dir,
                args.run_dir,
                args.urls_output,
                args.ports_output,
                lock_fd=args.router_lock_fd,
                resume=args.resume,
            )
        elif args.command == "capacity-smoke":
            summary = capacity_smoke(
                args.run_dir,
                args.base_url,
                args.expected_transition_sha256,
                router_lock_fd=args.router_lock_fd,
            )
        elif args.command == "commit-launch":
            summary = commit_launch(
                args.run_dir,
                args.expected_transition_sha256,
                router_lock_fd=args.router_lock_fd,
                writer_lock_fd=args.writer_lock_fd,
            )
        else:
            summary = audit_repair_run(args.run_dir)
    except (OSError, ValueError, GenerationMigrationError, migration.MigrationError) as error:
        code = error.code if isinstance(error, GenerationMigrationError) else "generation_transition_failed"
        print(json.dumps({"code": code, "status": "error"}, sort_keys=True), file=os.sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(summary, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
