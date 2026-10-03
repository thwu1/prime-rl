#!/usr/bin/env python3
"""Build the private offline-catalog plan for the sealed Qwen repair lane.

This controller intentionally emits only aggregate counts on stdout. Task
keys, image references, requirements, and every digest transitively binding
the provider partition remain in owned, single-link files below the private
deployment root.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import materialize_qwen_repair_provider_union as provider_union
import migrate_qwen_serving_generation as generation
from materialize_qwen_provider_union import (
    CANONICAL_DATASET_REVISION,
    DEPLOYMENT_NAMESPACE,
    MixedMaterializationError,
    _canonical_json,
    _open_private_output_root,
    _read_private_artifact,
    _read_regular,
    publish_exclusive,
    sha256,
)
from terminal_bench_vmvm.offline_verifier_catalog import (
    CatalogIdentity,
    ExpectedTaskBinding,
    OfflineCatalogError,
    _allowlist_sha256,
    binding_plan_sha256,
    catalog_consumer_code_sha256,
    ordered_requirements_sha256,
)
from terminal_bench_vmvm.offline_verifier_catalog_materializer import (
    MAX_SHARED_POOL_BUILD_CONCURRENCY,
    MAX_SHARED_POOL_PROBE_CONCURRENCY,
    MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
    MaterializationPlan,
    WorkerPolicy,
    materialization_plan_payload,
    materializer_controller_code_sha256,
    worker_environment_sha256,
    worker_recovery_scope_sha256,
)
from terminal_bench_vmvm.sandoq_catalog_worker import (
    _REQUIRED_ENVIRONMENT as REQUIRED_WORKER_RUNTIME_INVARIANTS,
)
from terminal_bench_vmvm.sandoq_catalog_worker import (
    PINNED_PROVIDER_COMMIT,
    PINNED_PROVIDER_SOURCE_SHA256,
    PINNED_PROVIDER_TREE,
    PINNED_SANDOQ_CLIENT,
    WORKER_PROTOCOL_VERSION,
)
from terminal_bench_vmvm.source_wheels import (
    canonical_json as catalog_canonical_json,
)
from terminal_bench_vmvm.source_wheels import (
    is_digest_pinned_image,
    strict_json_loads,
)
from terminal_bench_vmvm.taskset import (
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
    _image_ref,
    _network_modes,
    _test_script_requirements,
    offline_requirements_extractor_sha256,
)

SCHEMA_VERSION = 1
KIND = "qwen-repair-sandoq-offline-catalog-plan"
EXPECTED_REPAIR_COUNT = 1233
EXPECTED_SANDOQ_COUNT = 1233
EXPECTED_VMVM_COUNT = 0
EXPECTED_ROLLOUT_CONCURRENCY = 64
EXPECTED_PROVIDER_CONCURRENCY = 32
EXPECTED_OUTBOUND_DENYLIST = [
    "logprobs",
    "prompt_logprobs",
    "top_logprobs",
    "return_token_ids",
]
EXPECTED_PHASE_TIMEOUTS = {
    "setup": 3_600,
    "rollout": 36_000,
    "finalize": 3_600,
    "scoring": 21_600,
}
MAX_POLICY_BYTES = 16 * 1024 * 1024
MAX_CONFIG_BYTES = 4 * 1024 * 1024
MAX_TASK_METADATA_BYTES = 4 * 1024 * 1024
MAX_DEPENDENCY_SOURCE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_MANIFEST_BYTES = 64 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TASK_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,511}")


class CatalogPlanError(ValueError):
    """Stable, aggregate-only preparation failure."""


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise CatalogPlanError("arguments_invalid")


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise CatalogPlanError(code)
    raise CatalogPlanError(code) from error


def _exact(value: object, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _fail(code)
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _bounded_positive(value: object, *, maximum: int = 86_400) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        _fail("catalog_plan_policy_invalid")
    return value


def _sha256_file(path: Path, *, maximum: int) -> str:
    payload = _read_regular(path)
    if not 1 <= len(payload) <= maximum:
        _fail("catalog_plan_input_invalid")
    return sha256(payload)


def _validate_owned_regular(path: Path, *, executable: bool = False) -> None:
    try:
        resolved = path.resolve(strict=True)
        listed = path.lstat()
    except OSError as error:
        _fail("catalog_plan_input_invalid", error)
    if (
        resolved != path
        or not stat.S_ISREG(listed.st_mode)
        or listed.st_uid != os.geteuid()
        or listed.st_nlink != 1
        or (bool(listed.st_mode & stat.S_IXUSR) is not executable)
        or bool(listed.st_mode & 0o022)
    ):
        _fail("catalog_plan_input_invalid")


def _validate_argument_paths(arguments: Mapping[str, Any]) -> None:
    path_names = {
        "source",
        "dataset",
        "sandoq_template",
        "vmvm_template",
        "repair_selection_manifest",
        "historical_source_dir",
        "sandoq_tasks",
        "vmvm_tasks",
        "sandoq_config",
        "vmvm_config",
        "provider_receipt",
        "private_output_root",
        "policy",
        "worker_contract",
        "worker",
        "plan",
        "plan_receipt",
    }
    try:
        paths = {name: arguments[name] for name in path_names}
    except KeyError as error:
        _fail("catalog_plan_path_invalid", error)
    if any(
        not isinstance(path, Path)
        or not path.is_absolute()
        or path != Path(os.path.normpath(path))
        for path in paths.values()
    ):
        _fail("catalog_plan_path_invalid")
    private_root = paths["private_output_root"]
    private_names = {
        "sandoq_tasks",
        "vmvm_tasks",
        "sandoq_config",
        "vmvm_config",
        "provider_receipt",
        "policy",
        "worker_contract",
        "plan",
        "plan_receipt",
    }
    if any(paths[name].parent != private_root for name in private_names):
        _fail("catalog_plan_path_invalid")
    collision_paths = [paths[name] for name in private_names]
    if paths["worker"].parent == private_root:
        collision_paths.append(paths["worker"])
    if len(collision_paths) != len(set(collision_paths)):
        _fail("catalog_plan_path_invalid")
    for name in (
        "repair_selection_manifest_sha256",
        "provider_receipt_sha256",
        "policy_sha256",
        "worker_contract_sha256",
    ):
        if not _is_sha256(arguments.get(name)):
            _fail("catalog_plan_input_invalid")


@dataclass(frozen=True)
class PlanPolicy:
    sha256: str
    generator_sha256: str
    worker_contract_sha256: str
    worker: WorkerPolicy
    inventory_probe_code_sha256: str
    inventory_probe_environment_sha256: str
    inventory_probe_approval_sha256: str
    source_policy_sha256: str
    source_policy_approval_sha256: str
    approved_binary_artifacts: tuple[str, ...]
    approved_source_attestations: tuple[str, ...]
    approved_toolchains: tuple[str, ...]


@dataclass(frozen=True)
class DatasetPathSeal:
    task_root: Path
    relative: Path
    required: bool
    read_content: bool
    parent_identities: tuple[tuple[int, ...] | None, ...]
    file_identity: tuple[int, ...] | None
    content_sha256: str | None


def _parse_allowlist(value: object, code: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or value != sorted(set(value))
        or (not allow_empty and not value)
        or not all(_is_sha256(item) for item in value)
    ):
        _fail(code)
    return tuple(value)


def _load_worker_contract(body: bytes, expected_sha256: str) -> dict[str, Any]:
    if sha256(body) != expected_sha256:
        _fail("worker_contract_invalid")
    try:
        raw = strict_json_loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _fail("worker_contract_invalid", error)
    contract = _exact(
        raw,
        {
            "schema_version",
            "worker_protocol_version",
            "provider_commit",
            "provider_tree",
            "provider_source_sha256",
            "sandoq_client_version",
            "worker_runtime_sha256",
            "python_runtime_manifest_sha256",
            "worker_provision_identity_sha256",
            "worker_site_manifest_sha256",
            "cleanup_receipt_verifier_sha256",
            "inventory_probe_code_sha256",
            "inventory_probe_environment_sha256",
            "required_environment_names",
            "runtime_invariants",
        },
        "worker_contract_invalid",
    )
    if (
        body != catalog_canonical_json(contract)
        or contract["schema_version"] != 1
        or contract["worker_protocol_version"] != WORKER_PROTOCOL_VERSION
        or contract["provider_commit"] != PINNED_PROVIDER_COMMIT
        or contract["provider_tree"] != PINNED_PROVIDER_TREE
        or contract["provider_source_sha256"] != PINNED_PROVIDER_SOURCE_SHA256
        or contract["sandoq_client_version"] != PINNED_SANDOQ_CLIENT
        or not all(
            _is_sha256(contract[key])
            for key in (
                "provider_source_sha256",
                "worker_runtime_sha256",
                "python_runtime_manifest_sha256",
                "worker_provision_identity_sha256",
                "worker_site_manifest_sha256",
                "cleanup_receipt_verifier_sha256",
                "inventory_probe_code_sha256",
                "inventory_probe_environment_sha256",
            )
        )
        or not isinstance(contract["required_environment_names"], list)
        or contract["required_environment_names"]
        != sorted(set(contract["required_environment_names"]))
        or not all(isinstance(name, str) for name in contract["required_environment_names"])
        or contract["runtime_invariants"] != dict(sorted(REQUIRED_WORKER_RUNTIME_INVARIANTS.items()))
    ):
        _fail("worker_contract_invalid")
    return contract


def _load_policy(
    body: bytes,
    expected_sha256: str,
    *,
    worker_path: Path,
    worker_contract: Mapping[str, Any],
    worker_contract_sha256: str,
    provider_receipt_sha256: str,
) -> PlanPolicy:
    if sha256(body) != expected_sha256 or len(body) > MAX_POLICY_BYTES:
        _fail("catalog_plan_policy_invalid")
    try:
        raw = strict_json_loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _fail("catalog_plan_policy_invalid", error)
    value = _exact(
        raw,
        {
            "schema_version",
            "kind",
            "deployment_namespace",
            "expected_counts",
            "generator_sha256",
            "provider_materialization_receipt_sha256",
            "worker_contract_sha256",
            "worker",
            "catalog_policy",
        },
        "catalog_plan_policy_invalid",
    )
    counts = _exact(
        value["expected_counts"],
        {"repair", "sandoq", "vmvm"},
        "catalog_plan_policy_invalid",
    )
    if (
        body != _canonical_json(value)
        or value["schema_version"] != SCHEMA_VERSION
        or value["kind"] != KIND
        or value["deployment_namespace"] != DEPLOYMENT_NAMESPACE
        or counts
        != {
            "repair": EXPECTED_REPAIR_COUNT,
            "sandoq": EXPECTED_SANDOQ_COUNT,
            "vmvm": EXPECTED_VMVM_COUNT,
        }
        or not _is_sha256(value["generator_sha256"])
        or value["provider_materialization_receipt_sha256"] != provider_receipt_sha256
        or value["worker_contract_sha256"] != worker_contract_sha256
    ):
        _fail("catalog_plan_policy_invalid")
    generator_sha256 = _sha256_file(Path(__file__).resolve(strict=True), maximum=MAX_CONFIG_BYTES)
    if value["generator_sha256"] != generator_sha256:
        _fail("catalog_plan_generator_changed")
    worker_value = _exact(
        value["worker"],
        {
            "executable_sha256",
            "runtime_sha256",
            "materializer_code_sha256",
            "cleanup_receipt_verifier_sha256",
            "environment_sha256",
            "recovery_scope_sha256",
            "ecr_rotator_sha256",
            "environment_names",
            "timeouts_seconds",
            "concurrency",
        },
        "catalog_plan_policy_invalid",
    )
    environment_names = worker_value["environment_names"]
    timeouts = _exact(
        worker_value["timeouts_seconds"],
        {"recover", "probe", "build", "validate"},
        "catalog_plan_policy_invalid",
    )
    concurrency = _exact(
        worker_value["concurrency"],
        {"probe", "build", "validate"},
        "catalog_plan_policy_invalid",
    )
    if (
        not isinstance(environment_names, list)
        or environment_names != sorted(set(environment_names))
        or not all(isinstance(name, str) for name in environment_names)
        or concurrency
        != {
            "probe": MAX_SHARED_POOL_PROBE_CONCURRENCY,
            "build": MAX_SHARED_POOL_BUILD_CONCURRENCY,
            "validate": MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
        }
        or not all(
            _is_sha256(worker_value[key])
            for key in (
                "executable_sha256",
                "runtime_sha256",
                "materializer_code_sha256",
                "cleanup_receipt_verifier_sha256",
                "environment_sha256",
                "recovery_scope_sha256",
                "ecr_rotator_sha256",
            )
        )
    ):
        _fail("catalog_plan_policy_invalid")
    executable_sha256 = _sha256_file(worker_path, maximum=256 * 1024 * 1024)
    _validate_owned_regular(worker_path, executable=True)
    environment_sha256 = worker_environment_sha256(tuple(environment_names))
    worker = WorkerPolicy(
        executable_sha256=executable_sha256,
        runtime_sha256=str(worker_contract["worker_runtime_sha256"]),
        materializer_code_sha256=materializer_controller_code_sha256(),
        cleanup_receipt_verifier_sha256=str(worker_contract["cleanup_receipt_verifier_sha256"]),
        environment_sha256=environment_sha256,
        recovery_scope_sha256=worker_recovery_scope_sha256(environment_sha256),
        ecr_rotator_sha256=str(worker_value["ecr_rotator_sha256"]),
        environment_names=tuple(environment_names),
        recovery_timeout_seconds=_bounded_positive(timeouts["recover"]),
        probe_timeout_seconds=_bounded_positive(timeouts["probe"]),
        build_timeout_seconds=_bounded_positive(timeouts["build"]),
        validate_timeout_seconds=_bounded_positive(timeouts["validate"]),
        probe_concurrency=int(concurrency["probe"]),
        build_concurrency=int(concurrency["build"]),
        validate_concurrency=int(concurrency["validate"]),
    )
    expected_worker = {
        "executable_sha256": worker.executable_sha256,
        "runtime_sha256": worker.runtime_sha256,
        "materializer_code_sha256": worker.materializer_code_sha256,
        "cleanup_receipt_verifier_sha256": worker.cleanup_receipt_verifier_sha256,
        "environment_sha256": worker.environment_sha256,
        "recovery_scope_sha256": worker.recovery_scope_sha256,
        "ecr_rotator_sha256": worker.ecr_rotator_sha256,
    }
    if (
        any(worker_value[key] != expected for key, expected in expected_worker.items())
        or worker_contract["required_environment_names"] != list(environment_names)
    ):
        _fail("catalog_plan_policy_mismatch")
    catalog = _exact(
        value["catalog_policy"],
        {
            "inventory_probe_code_sha256",
            "inventory_probe_environment_sha256",
            "inventory_probe_approval_sha256",
            "catalog_consumer_code_sha256",
            "requirements_extractor_sha256",
            "source_policy_sha256",
            "source_policy_approval_sha256",
            "approved_binary_artifacts",
            "approved_source_attestations",
            "approved_toolchains",
        },
        "catalog_plan_policy_invalid",
    )
    if (
        not all(
            _is_sha256(catalog[key])
            for key in (
                "inventory_probe_code_sha256",
                "inventory_probe_environment_sha256",
                "inventory_probe_approval_sha256",
                "catalog_consumer_code_sha256",
                "requirements_extractor_sha256",
                "source_policy_sha256",
                "source_policy_approval_sha256",
            )
        )
        or catalog["inventory_probe_code_sha256"] != worker_contract["inventory_probe_code_sha256"]
        or catalog["inventory_probe_environment_sha256"]
        != worker_contract["inventory_probe_environment_sha256"]
        or catalog["catalog_consumer_code_sha256"] != catalog_consumer_code_sha256()
        or catalog["requirements_extractor_sha256"] != offline_requirements_extractor_sha256()
    ):
        _fail("catalog_plan_policy_mismatch")
    binaries = _parse_allowlist(catalog["approved_binary_artifacts"], "catalog_plan_policy_invalid")
    sources = _parse_allowlist(catalog["approved_source_attestations"], "catalog_plan_policy_invalid")
    toolchains = _parse_allowlist(
        catalog["approved_toolchains"],
        "catalog_plan_policy_invalid",
        allow_empty=False,
    )
    return PlanPolicy(
        sha256=expected_sha256,
        generator_sha256=generator_sha256,
        worker_contract_sha256=str(value["worker_contract_sha256"]),
        worker=worker,
        inventory_probe_code_sha256=str(catalog["inventory_probe_code_sha256"]),
        inventory_probe_environment_sha256=str(catalog["inventory_probe_environment_sha256"]),
        inventory_probe_approval_sha256=str(catalog["inventory_probe_approval_sha256"]),
        source_policy_sha256=str(catalog["source_policy_sha256"]),
        source_policy_approval_sha256=str(catalog["source_policy_approval_sha256"]),
        approved_binary_artifacts=binaries,
        approved_source_attestations=sources,
        approved_toolchains=toolchains,
    )


def _task_members(body: bytes) -> tuple[str, ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("catalog_plan_selection_invalid", error)
    members = tuple(text.splitlines())
    if (
        not body
        or not text.endswith("\n")
        or "\r" in text
        or len(members) != EXPECTED_SANDOQ_COUNT
        or len(members) != len(set(members))
        or any(TASK_KEY_RE.fullmatch(member) is None for member in members)
    ):
        _fail("catalog_plan_selection_invalid")
    return members


def _image_manifest(body: bytes) -> dict[str, dict[str, str]]:
    try:
        raw = strict_json_loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _fail("catalog_plan_image_manifest_invalid", error)
    images = raw.get("images", raw) if isinstance(raw, dict) else None
    if not isinstance(images, dict):
        _fail("catalog_plan_image_manifest_invalid")
    normalized: dict[str, dict[str, str]] = {}
    for task_key, entry in images.items():
        if not isinstance(task_key, str) or TASK_KEY_RE.fullmatch(task_key) is None:
            _fail("catalog_plan_image_manifest_invalid")
        if isinstance(entry, str):
            normalized[task_key] = {"agent": entry}
        elif isinstance(entry, dict) and all(
            isinstance(role, str) and isinstance(reference, str)
            for role, reference in entry.items()
        ):
            normalized[task_key] = dict(entry)
        else:
            _fail("catalog_plan_image_manifest_invalid")
    return normalized


def _dataset_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _dataset_parent_identities(
    task_root: Path,
    relative: Path,
) -> tuple[tuple[int, ...] | None, ...]:
    if relative.is_absolute() or not relative.name or ".." in relative.parts:
        _fail("catalog_plan_dataset_invalid")
    candidates = [task_root]
    current = task_root
    for component in relative.parts[:-1]:
        current /= component
        candidates.append(current)
    identities: list[tuple[int, ...] | None] = []
    missing = False
    for candidate in candidates:
        if missing:
            identities.append(None)
            continue
        try:
            listed = candidate.lstat()
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            missing = True
            identities.append(None)
            continue
        except OSError as error:
            _fail("catalog_plan_dataset_invalid", error)
        if (
            not stat.S_ISDIR(listed.st_mode)
            or listed.st_uid != os.geteuid()
            or bool(listed.st_mode & 0o022)
            or resolved != candidate
            or (candidate != task_root and not resolved.is_relative_to(task_root))
        ):
            _fail("catalog_plan_dataset_invalid")
        identities.append(_dataset_identity(listed))
    return tuple(identities)


def _dataset_path_state(
    task_root: Path,
    relative: Path,
    *,
    required: bool,
    read_content: bool,
) -> tuple[DatasetPathSeal, bytes | None]:
    parent_identities = _dataset_parent_identities(task_root, relative)
    path = task_root / relative
    if any(identity is None for identity in parent_identities):
        if required or os.path.lexists(path):
            _fail("catalog_plan_dataset_invalid")
        return (
            DatasetPathSeal(
                task_root=task_root,
                relative=relative,
                required=required,
                read_content=read_content,
                parent_identities=parent_identities,
                file_identity=None,
                content_sha256=None,
            ),
            None,
        )
    try:
        listed = path.lstat()
    except FileNotFoundError:
        if required:
            _fail("catalog_plan_dataset_invalid")
        return (
            DatasetPathSeal(
                task_root=task_root,
                relative=relative,
                required=required,
                read_content=read_content,
                parent_identities=parent_identities,
                file_identity=None,
                content_sha256=None,
            ),
            None,
        )
    except OSError as error:
        _fail("catalog_plan_dataset_invalid", error)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        _fail("catalog_plan_dataset_invalid", error)
    if (
        not stat.S_ISREG(listed.st_mode)
        or listed.st_uid != os.geteuid()
        or listed.st_nlink != 1
        or bool(listed.st_mode & 0o022)
        or resolved != path
        or not resolved.is_relative_to(task_root)
    ):
        _fail("catalog_plan_dataset_invalid")
    body: bytes | None = None
    if read_content:
        try:
            body = _read_regular(path)
        except MixedMaterializationError as error:
            _fail("catalog_plan_dataset_invalid", error)
        if len(body) > MAX_DEPENDENCY_SOURCE_BYTES:
            _fail("catalog_plan_dataset_invalid")
    try:
        listed_after = path.lstat()
    except OSError as error:
        _fail("catalog_plan_dataset_invalid", error)
    parent_identities_after = _dataset_parent_identities(task_root, relative)
    if (
        _dataset_identity(listed) != _dataset_identity(listed_after)
        or parent_identities != parent_identities_after
    ):
        _fail("catalog_plan_dataset_changed")
    return (
        DatasetPathSeal(
            task_root=task_root,
            relative=relative,
            required=required,
            read_content=read_content,
            parent_identities=parent_identities,
            file_identity=_dataset_identity(listed),
            content_sha256=sha256(body) if body is not None else None,
        ),
        body,
    )


def _verify_dataset_path_seal(seal: DatasetPathSeal) -> None:
    observed, _ = _dataset_path_state(
        seal.task_root,
        seal.relative,
        required=seal.required,
        read_content=seal.read_content,
    )
    if observed != seal:
        _fail("catalog_plan_dataset_changed")


def _extract_test_requirements(task_dir: Path) -> tuple[str, ...]:
    _test_script_requirements.cache_clear()
    try:
        return TerminalBenchVMVMTaskset._test_requirements(
            SimpleNamespace(task_dir=str(task_dir))
        )
    except (OSError, RuntimeError, ValueError) as error:
        _fail("catalog_plan_requirements_invalid", error)
    finally:
        _test_script_requirements.cache_clear()


def _extract_bindings(
    config: TerminalBenchVMVMConfig,
    members: Sequence[str],
    image_manifest: Mapping[str, Mapping[str, str]],
) -> tuple[ExpectedTaskBinding, ...]:
    try:
        dataset = config.dataset_dir.resolve(strict=True)
    except OSError as error:
        _fail("catalog_plan_dataset_invalid", error)
    bindings: list[ExpectedTaskBinding] = []
    all_seals: list[DatasetPathSeal] = []
    for member in members:
        task_dir = dataset / member
        try:
            task_status = task_dir.lstat()
            resolved_task = task_dir.resolve(strict=True)
        except OSError as error:
            _fail("catalog_plan_dataset_invalid", error)
        if (
            not stat.S_ISDIR(task_status.st_mode)
            or task_status.st_uid != os.geteuid()
            or bool(task_status.st_mode & 0o022)
            or task_dir.is_symlink()
            or resolved_task.parent != dataset
        ):
            _fail("catalog_plan_dataset_invalid")
        task_seals: list[DatasetPathSeal] = []
        metadata_seal, metadata_body = _dataset_path_state(
            task_dir,
            Path("task.toml"),
            required=True,
            read_content=True,
        )
        task_seals.append(metadata_seal)
        # Presence is required by the real task loader, but the plan generator
        # deliberately never opens task instructions.
        instruction_seal, _ = _dataset_path_state(
            task_dir,
            Path("instruction.md"),
            required=True,
            read_content=False,
        )
        task_seals.append(instruction_seal)
        dependency_seals: dict[Path, DatasetPathSeal] = {}
        for relative in (
            Path("environment/Dockerfile"),
            Path("tests/Dockerfile"),
            Path("tests/test.sh"),
        ):
            seal, _ = _dataset_path_state(
                task_dir,
                relative,
                required=relative == Path("tests/test.sh"),
                read_content=True,
            )
            dependency_seals[relative] = seal
            task_seals.append(seal)
        try:
            if metadata_body is None or len(metadata_body) > MAX_TASK_METADATA_BYTES:
                _fail("catalog_plan_dataset_invalid")
            metadata = tomllib.loads(metadata_body.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            _fail("catalog_plan_dataset_invalid", error)
        environment = metadata.get("environment", {})
        verifier = metadata.get("verifier", {})
        if not isinstance(environment, dict) or not isinstance(verifier, dict):
            _fail("catalog_plan_dataset_invalid")
        verifier_environment = verifier.get("environment") or environment
        if not isinstance(verifier_environment, dict):
            _fail("catalog_plan_dataset_invalid")
        mode = verifier.get("environment_mode")
        if mode is None:
            mode = "separate" if verifier.get("environment") is not None else "shared"
        if mode not in {"shared", "separate"}:
            _fail("catalog_plan_dataset_invalid")
        try:
            agent_network, verifier_network = _network_modes(member, metadata, mode)
        except (TypeError, ValueError) as error:
            _fail("catalog_plan_network_invalid", error)
        manifested = image_manifest.get(member)
        if manifested is None or "agent" not in manifested:
            _fail("catalog_plan_image_manifest_invalid")
        # Match TerminalBenchVMVMTaskset.load_tasks exactly: a sealed manifest
        # always wins over a task.toml declaration, even when
        # use_declared_images is set.
        agent_image = manifested["agent"]
        verifier_tests_baked = (
            dependency_seals[Path("tests/Dockerfile")].file_identity is not None
        )
        if mode == "shared":
            runtime_role = "shared-agent"
            image = agent_image
            network = agent_network
            requirements = _extract_test_requirements(task_dir)
        else:
            runtime_role = "separate-verifier"
            declared_verifier = verifier_environment.get("docker_image")
            if manifested.get("verifier"):
                image = manifested["verifier"]
            elif config.use_declared_images and declared_verifier:
                image = str(declared_verifier)
            elif verifier_tests_baked:
                image = _image_ref(
                    config.image_prefix,
                    member,
                    config.image_tag,
                    config.verifier_image_suffix,
                )
            else:
                image = agent_image
            network = verifier_network
            if verifier_tests_baked:
                requirements = ()
            else:
                requirements = _extract_test_requirements(task_dir)
        for seal in task_seals:
            _verify_dataset_path_seal(seal)
        all_seals.extend(task_seals)
        if network != "no-network" or not is_digest_pinned_image(image):
            _fail("catalog_plan_runtime_binding_invalid")
        bindings.append(
            ExpectedTaskBinding(
                task_key=member,
                runtime_role=runtime_role,
                image=image,
                requirements=requirements,
            )
        )
    if len(bindings) != EXPECTED_SANDOQ_COUNT:
        _fail("catalog_plan_binding_incomplete")
    try:
        TerminalBenchVMVMTaskset(config)._validate_dataset_revision(dataset)
    except (OSError, RuntimeError, ValueError) as error:
        _fail("catalog_plan_dataset_invalid", error)
    for seal in all_seals:
        _verify_dataset_path_seal(seal)
    return tuple(bindings)


def _validate_sandoq_config(
    body: bytes,
    *,
    sandoq_tasks: Path,
    task_sha256: str,
    dataset: Path,
) -> tuple[TerminalBenchVMVMConfig, bytes]:
    if len(body) > MAX_CONFIG_BYTES:
        _fail("catalog_plan_config_invalid")
    try:
        raw = tomllib.loads(body.decode("utf-8"))
        taskset_raw = raw["taskset"]
        config = TerminalBenchVMVMConfig.model_validate(taskset_raw)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        _fail("catalog_plan_config_invalid", error)
    try:
        config_task_file = config.task_file.resolve(strict=True) if config.task_file is not None else None
        config_dataset = config.dataset_dir.resolve(strict=True)
        config_image_manifest = (
            config.image_manifest.resolve(strict=True) if config.image_manifest is not None else None
        )
    except OSError as error:
        _fail("catalog_plan_config_invalid", error)
    client = raw.get("client")
    sampling = raw.get("sampling")
    harness = raw.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    timeouts = raw.get("timeout")
    retries = raw.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
    if (
        raw.get("model") != "Qwen3.8-2.4T-A95B"
        or raw.get("num_tasks") != EXPECTED_SANDOQ_COUNT
        or raw.get("num_rollouts") != 1
        or raw.get("max_concurrent") != EXPECTED_ROLLOUT_CONCURRENCY
        or raw.get("max_turns") != 200
        or raw.get("multiplex") != EXPECTED_ROLLOUT_CONCURRENCY
        or raw.get("max_input_tokens") != 262_144
        or raw.get("max_output_tokens") != 262_144
        or raw.get("max_total_tokens") != 262_144
        or raw.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("outbound_body_denylist") != EXPECTED_OUTBOUND_DENYLIST
        or client.get("base_url") != "http://127.0.0.1:8000/v1"
        or client.get("api_key_var") != "OPENAI_API_KEY"
        or client.get("timeout") != 7_200
        or client.get("connect_timeout") != 30
        or client.get("max_connections") != EXPECTED_PROVIDER_CONCURRENCY
        or client.get("max_keepalive_connections") != EXPECTED_PROVIDER_CONCURRENCY
        or not isinstance(sampling, dict)
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("temperature") != 0.7
        or sampling.get("top_p") != 0.95
        or sampling.get("top_k") != 20
        or sampling.get("max_tokens") != 32_768
        or sampling.get("chat_template_kwargs")
        != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(harness, dict)
        or harness.get("id") != "terminal-bench-sandoq-host"
        or harness.get("command_timeout_seconds") != 240
        or harness.get("command_kill_grace_seconds") != 10
        or harness.get("max_command_output_chars") != 100_000
        or harness.get("request_timeout_seconds") != 15_000
        or not isinstance(runtime, dict)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("session_timeout") != 43_200
        or runtime.get("network_access") is not False
        or runtime.get("host_tunnel") != "none"
        or runtime.get("expected_environment") != "oci-runner-firecracker"
        or timeouts != EXPECTED_PHASE_TIMEOUTS
        or not isinstance(rollout_retries, dict)
        or rollout_retries.get("max_retries") != 0
        or config.verifier_runtime_retries != 0
        or config.enable_compose
        or config.tasks is not None
        or config.dataset_revision != CANONICAL_DATASET_REVISION
        or config.task_file is None
        or not config.task_file.is_absolute()
        or config_task_file != sandoq_tasks
        or config.task_file_sha256 != task_sha256
        or not config.dataset_dir.is_absolute()
        or config_dataset != dataset
        or config.image_manifest is None
        or not config.image_manifest.is_absolute()
        or config_image_manifest is None
        or config_image_manifest != config.image_manifest
        or config.image_manifest_sha256 is None
        or any(
            value is not None
            for value in (
                config.offline_verifier_catalog,
                config.offline_verifier_catalog_sha256,
                config.offline_verifier_catalog_identity,
                config.offline_verifier_catalog_task_file,
                config.offline_verifier_catalog_task_file_sha256,
                config.offline_verifier_project_root,
            )
        )
    ):
        _fail("catalog_plan_config_invalid")
    _validate_owned_regular(config_image_manifest)
    image_manifest_body = _read_regular(config_image_manifest)
    _validate_owned_regular(config_image_manifest)
    if not 1 <= len(image_manifest_body) <= MAX_IMAGE_MANIFEST_BYTES:
        _fail("catalog_plan_image_manifest_invalid")
    if sha256(image_manifest_body) != config.image_manifest_sha256:
        _fail("catalog_plan_image_manifest_invalid")
    try:
        taskset = TerminalBenchVMVMTaskset(config)
        taskset._validate_dataset_revision(dataset)
    except (OSError, RuntimeError, ValueError) as error:
        _fail("catalog_plan_dataset_invalid", error)
    return config, image_manifest_body


def _generator_receipt(
    *,
    plan_payload: bytes,
    identity: CatalogIdentity,
    policy: PlanPolicy,
    provider_receipt_sha256: str,
    config_sha256: str,
    bindings: Sequence[ExpectedTaskBinding],
) -> bytes:
    assignment_hashes: list[str] = []
    group_hashes: set[str] = set()
    requirement_hashes: set[str] = set()
    for binding in bindings:
        requirement_sha256 = ordered_requirements_sha256(binding.requirements)
        assignment_core = {
            "task_key": binding.task_key,
            "runtime_role": binding.runtime_role,
            "image": binding.image,
            "requirements": list(binding.requirements),
            "requirements_sha256": requirement_sha256,
        }
        assignment_hashes.append(sha256(catalog_canonical_json(assignment_core)))
        group_hashes.add(
            sha256(
                catalog_canonical_json(
                    {
                        "runtime_role": binding.runtime_role,
                        "image": binding.image,
                        "requirements_sha256": requirement_sha256,
                    }
                )
            )
        )
        requirement_hashes.add(requirement_sha256)
    if len(assignment_hashes) != len(set(assignment_hashes)):
        _fail("catalog_plan_binding_duplicate")

    def set_commitment(kind: str, values: Sequence[str]) -> str:
        ordered = sorted(values)
        if len(ordered) != len(set(ordered)) or not all(_is_sha256(value) for value in ordered):
            _fail("catalog_plan_binding_invalid")
        return sha256(
            catalog_canonical_json(
                {"schema_version": 1, "kind": kind, "member_sha256": ordered}
            )
        )

    images = {binding.image for binding in bindings}
    groups = {
        (binding.runtime_role, binding.image, tuple(binding.requirements))
        for binding in bindings
    }
    requirement_sets = {tuple(binding.requirements) for binding in bindings}
    roles = {
        role: sum(binding.runtime_role == role for binding in bindings)
        for role in ("shared-agent", "separate-verifier")
    }
    return _canonical_json(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "state": "sealed",
            "deployment_namespace": DEPLOYMENT_NAMESPACE,
            "counts": {
                "tasks": len(bindings),
                "sandoq": EXPECTED_SANDOQ_COUNT,
                "vmvm": EXPECTED_VMVM_COUNT,
                "images": len(images),
                "probe_groups": len(groups),
                "requirement_sets": len(requirement_sets),
                "shared_agent": roles["shared-agent"],
                "separate_verifier": roles["separate-verifier"],
            },
            "bindings": {
                "plan_sha256": sha256(plan_payload),
                "identity_sha256": identity.sha256,
                "policy_sha256": policy.sha256,
                "generator_sha256": policy.generator_sha256,
                "provider_materialization_receipt_sha256": provider_receipt_sha256,
                "sandoq_config_sha256": config_sha256,
                "worker_contract_sha256": policy.worker_contract_sha256,
            },
            # These are private commitments. They mechanically bind every
            # assignment and each deduplicated probe/requirement group without
            # copying task keys, images, or dependency strings into the
            # aggregate receipt.
            "private_set_commitments": {
                "assignments": {
                    "unique_count": len(assignment_hashes),
                    "set_sha256": set_commitment("assignments", assignment_hashes),
                },
                "probe_groups": {
                    "unique_count": len(group_hashes),
                    "set_sha256": set_commitment("probe-groups", tuple(group_hashes)),
                },
                "requirement_sets": {
                    "unique_count": len(requirement_hashes),
                    "set_sha256": set_commitment(
                        "requirement-sets", tuple(requirement_hashes)
                    ),
                },
            },
            "runtime_contract": {
                "provider": "sandoq",
                "environment": "oci-runner-firecracker",
                "task_network": "none",
                "host_harness": True,
                "rollout_retries": 0,
                "verifier_runtime_retries": 0,
                "catalog_epoch_exclusive": True,
                "probe_concurrency": MAX_SHARED_POOL_PROBE_CONCURRENCY,
                "build_concurrency": MAX_SHARED_POOL_BUILD_CONCURRENCY,
                "validate_concurrency": MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
            },
        }
    )


def _provider_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in (
            "source",
            "dataset",
            "sandoq_template",
            "vmvm_template",
            "repair_selection_manifest",
            "repair_selection_manifest_sha256",
            "historical_source_dir",
            "sandoq_tasks",
            "vmvm_tasks",
            "sandoq_config",
            "vmvm_config",
            "provider_receipt",
            "provider_receipt_sha256",
            "private_output_root",
        )
    }


def _validate_provider_materialization(arguments: Mapping[str, Any]) -> dict[str, Any]:
    values = _provider_arguments(arguments)
    values["receipt"] = values.pop("provider_receipt")
    values["receipt_sha256"] = values.pop("provider_receipt_sha256")
    try:
        receipt = provider_union.validate_materialization(**values)
    except (OSError, provider_union.RepairProviderMaterializationError) as error:
        _fail("provider_materialization_invalid", error)
    partition = receipt.get("partition") if isinstance(receipt, dict) else None
    if partition != {
        "disjoint": True,
        "exhaustive": True,
        "sandoq_count": EXPECTED_SANDOQ_COUNT,
        "vmvm_count": EXPECTED_VMVM_COUNT,
        "total_count": EXPECTED_REPAIR_COUNT,
    }:
        _fail("provider_materialization_invalid")
    return receipt


def _derive_plan(
    arguments: Mapping[str, Any],
) -> tuple[bytes, bytes, dict[str, int], tuple[int, int]]:
    _validate_argument_paths(arguments)
    try:
        repair_count = generation._load_contract()["repair"]["repair_union_count"]
    except (KeyError, TypeError, generation.GenerationMigrationError) as error:
        _fail("repair_contract_invalid", error)
    if repair_count != EXPECTED_REPAIR_COUNT:
        _fail("repair_contract_count_changed")
    _validate_provider_materialization(arguments)
    private_root = arguments["private_output_root"]
    assert isinstance(private_root, Path)
    inputs = (
        arguments["sandoq_tasks"],
        arguments["vmvm_tasks"],
        arguments["sandoq_config"],
        arguments["vmvm_config"],
        arguments["provider_receipt"],
        arguments["policy"],
        arguments["worker_contract"],
    )
    outputs = (arguments["plan"], arguments["plan_receipt"])
    if not all(isinstance(path, Path) for path in (*inputs, *outputs)):
        _fail("catalog_plan_path_invalid")
    if not isinstance(arguments["dataset"], Path) or not isinstance(arguments["worker"], Path):
        _fail("catalog_plan_path_invalid")
    _validate_owned_regular(arguments["worker"], executable=True)
    with _open_private_output_root(
        private_root,
        (*inputs, *outputs),
        forbidden_roots=(Path(__file__).resolve().parents[3], arguments["dataset"]),
        validate_existing=False,
    ) as opened:
        task_body = _read_private_artifact(opened, arguments["sandoq_tasks"])
        config_body = _read_private_artifact(opened, arguments["sandoq_config"])
        provider_receipt_body = _read_private_artifact(opened, arguments["provider_receipt"])
        policy_body = _read_private_artifact(opened, arguments["policy"])
        worker_contract_body = _read_private_artifact(opened, arguments["worker_contract"])
        if (
            sha256(provider_receipt_body) != arguments["provider_receipt_sha256"]
            or sha256(policy_body) != arguments["policy_sha256"]
            or sha256(worker_contract_body) != arguments["worker_contract_sha256"]
        ):
            _fail("catalog_plan_input_changed")
        members = _task_members(task_body)
        config, image_manifest_body = _validate_sandoq_config(
            config_body,
            sandoq_tasks=arguments["sandoq_tasks"],
            task_sha256=sha256(task_body),
            dataset=arguments["dataset"].resolve(strict=True),
        )
        image_manifest = _image_manifest(image_manifest_body)
        bindings = _extract_bindings(config, members, image_manifest)
        image_manifest_path = config.image_manifest
        if image_manifest_path is None:
            _fail("catalog_plan_image_manifest_changed")
        _validate_owned_regular(image_manifest_path)
        if _read_regular(image_manifest_path) != image_manifest_body:
            _fail("catalog_plan_image_manifest_changed")
        _validate_owned_regular(image_manifest_path)
        policy = _load_policy(
            policy_body,
            arguments["policy_sha256"],
            worker_path=arguments["worker"],
            worker_contract=_load_worker_contract(
                worker_contract_body,
                arguments["worker_contract_sha256"],
            ),
            worker_contract_sha256=arguments["worker_contract_sha256"],
            provider_receipt_sha256=arguments["provider_receipt_sha256"],
        )
        identity = CatalogIdentity(
            dataset_revision=str(config.dataset_revision),
            task_selection_sha256=sha256(task_body),
            expected_task_count=EXPECTED_SANDOQ_COUNT,
            binding_plan_sha256=binding_plan_sha256(bindings),
            catalog_consumer_code_sha256=catalog_consumer_code_sha256(),
            image_manifest_sha256=str(config.image_manifest_sha256),
            requirements_extractor_sha256=offline_requirements_extractor_sha256(),
            inventory_probe_code_sha256=policy.inventory_probe_code_sha256,
            inventory_probe_environment_sha256=policy.inventory_probe_environment_sha256,
            inventory_probe_approval_sha256=policy.inventory_probe_approval_sha256,
            source_policy_sha256=policy.source_policy_sha256,
            source_policy_approval_sha256=policy.source_policy_approval_sha256,
            approved_binary_artifacts_sha256=_allowlist_sha256(
                "binary-artifacts", policy.approved_binary_artifacts
            ),
            approved_source_attestations_sha256=_allowlist_sha256(
                "source-attestations", policy.approved_source_attestations
            ),
            approved_toolchains_sha256=_allowlist_sha256(
                "toolchains", policy.approved_toolchains
            ),
        )
        plan_payload = materialization_plan_payload(
            identity=identity,
            worker=policy.worker,
            approved_binary_artifacts=policy.approved_binary_artifacts,
            approved_source_attestations=policy.approved_source_attestations,
            approved_toolchains=policy.approved_toolchains,
            tasks=bindings,
        )
        receipt_payload = _generator_receipt(
            plan_payload=plan_payload,
            identity=identity,
            policy=policy,
            provider_receipt_sha256=arguments["provider_receipt_sha256"],
            config_sha256=sha256(config_body),
            bindings=bindings,
        )
        # Reopen every private provider input and the immutable source before
        # allowing deterministic publication.
        _validate_provider_materialization(arguments)
        if (
            _read_private_artifact(opened, arguments["sandoq_tasks"]) != task_body
            or _read_private_artifact(opened, arguments["sandoq_config"]) != config_body
            or _read_private_artifact(opened, arguments["provider_receipt"])
            != provider_receipt_body
            or _read_private_artifact(opened, arguments["policy"]) != policy_body
            or _read_private_artifact(opened, arguments["worker_contract"])
            != worker_contract_body
        ):
            _fail("catalog_plan_input_changed")
        counts = json.loads(receipt_payload)["counts"]
        return plan_payload, receipt_payload, counts, (opened.device, opened.inode)


def prepare(**arguments: Any) -> dict[str, int]:
    try:
        plan_payload, receipt_payload, counts, root_identity = _derive_plan(arguments)
        private_root = arguments["private_output_root"]
        with _open_private_output_root(
            private_root,
            (arguments["plan"], arguments["plan_receipt"]),
            forbidden_roots=(Path(__file__).resolve().parents[3], arguments["dataset"]),
            validate_existing=False,
        ) as opened:
            if (opened.device, opened.inode) != root_identity:
                _fail("catalog_plan_input_changed")
            publish_exclusive(
                opened,
                [
                    (arguments["plan"], plan_payload),
                    (arguments["plan_receipt"], receipt_payload),
                ],
            )
        loaded = MaterializationPlan.load(
            arguments["plan"],
            sha256(plan_payload),
            project_root=Path(__file__).resolve().parents[3],
            dataset_root=arguments["dataset"].resolve(strict=True),
        )
    except CatalogPlanError:
        raise
    except (MixedMaterializationError, OfflineCatalogError, OSError) as error:
        _fail("catalog_plan_input_invalid", error)
    if loaded.expected_task_count != EXPECTED_SANDOQ_COUNT:
        _fail("catalog_plan_publication_invalid")
    return dict(counts)


def validate(**arguments: Any) -> dict[str, int]:
    try:
        plan_payload, receipt_payload, counts, root_identity = _derive_plan(arguments)
        private_root = arguments["private_output_root"]
        with _open_private_output_root(
            private_root,
            (arguments["plan"], arguments["plan_receipt"]),
            forbidden_roots=(Path(__file__).resolve().parents[3], arguments["dataset"]),
        ) as opened:
            if (opened.device, opened.inode) != root_identity:
                _fail("catalog_plan_input_changed")
            if (
                _read_private_artifact(opened, arguments["plan"]) != plan_payload
                or _read_private_artifact(opened, arguments["plan_receipt"]) != receipt_payload
            ):
                _fail("catalog_plan_publication_invalid")
    except CatalogPlanError:
        raise
    except (MixedMaterializationError, OfflineCatalogError, OSError) as error:
        _fail("catalog_plan_input_invalid", error)
    return dict(counts)


def _parse_args() -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sandoq-template", type=Path, required=True)
    parser.add_argument("--vmvm-template", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest-sha256", required=True)
    parser.add_argument("--historical-source-dir", type=Path, required=True)
    parser.add_argument("--sandoq-tasks", type=Path, required=True)
    parser.add_argument("--vmvm-tasks", type=Path, required=True)
    parser.add_argument("--sandoq-config", type=Path, required=True)
    parser.add_argument("--vmvm-config", type=Path, required=True)
    parser.add_argument("--provider-receipt", type=Path, required=True)
    parser.add_argument("--provider-receipt-sha256", required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--worker-contract", type=Path, required=True)
    parser.add_argument("--worker-contract-sha256", required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-receipt", type=Path, required=True)
    parser.add_argument("--validate", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        arguments = vars(_parse_args())
        validate_only = bool(arguments.pop("validate"))
        summary = validate(**arguments) if validate_only else prepare(**arguments)
    # This CLI is a privacy boundary: unexpected ordinary exceptions must not
    # surface task paths, dependency strings, or member names in a traceback.
    except Exception:
        print(json.dumps({"state": "failed", "error": "catalog_plan_invalid"}, sort_keys=True))
        return 1
    print(json.dumps({"state": "sealed", "counts": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
