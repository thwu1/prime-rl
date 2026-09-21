#!/usr/bin/env python3
"""Publish an aggregate-only Kimi TB4 Sandoq diagnostic union.

The union is intentionally ineligible for certification and trace rollout.
Task identifiers and raw task errors are consumed only to validate exact
coverage and are never included in the published record or CLI output.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import direct_kimi_workers as direct_workers
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_provider_split_launch as standard
import prepare_kimi_tb4_sandoq_fallback as fallback
from eval_run_identity import EvalIdentityError, _verify_source_record, load_eval_run_identity_bytes

KIND = "kimi-tb4-sandoq-diagnostic-union"
SCHEMA_VERSION = 1
EXECUTED_TASKS = split.LEGACY_SANDOQ_TASKS + fallback.MEMORY_8G_TASKS + fallback.MEMORY_16G_TASKS
SYNTHETIC_ZERO_TASKS = fallback.COMPOSE_EXCLUDED_TASKS + fallback.GPU_UNSUPPORTED_TASKS
EXPECTED_LANES = ("standard_legacy", "fallback_memory_8g", "fallback_memory_16g")
PROVENANCE_KEY_RE = re.compile(r"[a-z][a-z0-9_]*\Z")


class KimiDiagnosticUnionError(ValueError):
    """An aggregate-only error from the non-certifying diagnostic union."""


@dataclass(frozen=True, slots=True)
class LaneBinding:
    name: str
    role: str
    output_dir: Path
    config_sha256: str
    selector_sha256: str
    members: tuple[str, ...]
    concurrency: int
    resource_multiplier: float
    memory_resource_multiplier: float | None
    enable_compose: bool


@dataclass(frozen=True, slots=True)
class PlanBinding:
    standard_plan_sha256: str
    fallback_plan_sha256: str
    manifest_sha256: str
    manifest_value: Mapping[str, Any]
    verifier_modes: Mapping[str, str]
    lanes: tuple[LaneBinding, ...]
    compose_excluded: tuple[str, ...]
    gpu_unsupported: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _HeldTreeRoot:
    path: Path
    parent_path: Path
    parent: int
    descriptor: int
    name: str
    identity: tuple[int, int, int, int]
    parent_identity: tuple[int, int, int, int]


class RetainedAuditEvidence:
    """Keep every audited inode and quiescence lock alive through publication."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self.artifacts = split._HeldArtifactSet.create()
        self.direct_artifacts = direct_workers._HeldArtifactSet.create()
        self._runs: list[split._HeldRunEvidence] = []
        self._router_locks: dict[Path, Any] = {}
        self._tree_roots: dict[Path, _HeldTreeRoot] = {}
        self._source_closures: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> RetainedAuditEvidence:
        self._stack.__enter__()
        self._stack.callback(self.artifacts.close)
        self._stack.callback(self.direct_artifacts.close)
        self._stack.callback(self._close_tree_roots)
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return self._stack.__exit__(*exc_info)

    def close_after_commit(self) -> None:
        """Release local descriptors without turning a committed marker into failure."""

        cleanup = self._stack.pop_all()
        try:
            cleanup.close()
        except BaseException:
            # The output marker is already authoritative. These are only local
            # descriptors/locks and process exit is the final cleanup fallback.
            pass

    def retain_run(self, run_dir: Path) -> split._HeldRunEvidence:
        evidence = split._open_held_run_evidence(run_dir)
        self._stack.callback(evidence.close)
        writer_lock = self._stack.enter_context(split._open_private_writer_lock_at(evidence.directory, ".writer.lock"))
        try:
            fcntl.flock(writer_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KimiDiagnosticUnionError("diagnostic_run_active") from error

        router_path = split._router_lock_path(evidence.files["eval_run_identity.json"].body)
        if router_path not in self._router_locks:
            router_lock = self._stack.enter_context(split._open_private_writer_lock(router_path))
            try:
                fcntl.flock(router_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise KimiDiagnosticUnionError("diagnostic_run_active") from error
            self._router_locks[router_path] = router_lock
        self._runs.append(evidence)
        return evidence

    def retain_tree_root(self, path: Path) -> None:
        """Retain one authenticated tree root and its immediate parent."""

        try:
            absolute = split._absolute_path(path)
            if absolute in self._tree_roots:
                return
            absolute, parent, descriptor, name = split._open_anchored(
                absolute,
                directory=True,
                code="diagnostic_evidence_root_invalid",
            )
        except split.KimiProviderSplitError as error:
            raise KimiDiagnosticUnionError("diagnostic_evidence_root_invalid") from error
        try:
            metadata = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            parent_metadata = os.fstat(parent)
            visible_parent = absolute.parent.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or split._directory_identity(metadata) != split._directory_identity(visible)
                or split._directory_identity(parent_metadata) != split._directory_identity(visible_parent)
                or absolute.resolve(strict=True) != absolute
                or absolute.parent.resolve(strict=True) != absolute.parent
            ):
                raise KimiDiagnosticUnionError("diagnostic_evidence_root_invalid")
            self._tree_roots[absolute] = _HeldTreeRoot(
                path=absolute,
                parent_path=absolute.parent,
                parent=parent,
                descriptor=descriptor,
                name=name,
                identity=split._directory_identity(metadata),
                parent_identity=split._directory_identity(parent_metadata),
            )
        except BaseException:
            os.close(descriptor)
            os.close(parent)
            raise

    def retain_source_closure(self, source: Mapping[str, Any]) -> None:
        try:
            body = split.canonical_json(source)
            value = json.loads(body)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise KimiDiagnosticUnionError("diagnostic_source_contract_invalid") from error
        if not isinstance(value, dict):
            raise KimiDiagnosticUnionError("diagnostic_source_contract_invalid")
        self._source_closures[split.sha256_bytes(body)] = value

    def revalidate_source_closures(self) -> None:
        try:
            for source in self._source_closures.values():
                _verify_source_record(source)
        except (EvalIdentityError, KeyError, OSError, TypeError, ValueError) as error:
            raise KimiDiagnosticUnionError("diagnostic_source_closure_changed") from error

    def _close_tree_roots(self) -> None:
        for root in self._tree_roots.values():
            os.close(root.descriptor)
            os.close(root.parent)
        self._tree_roots.clear()

    def revalidate(self) -> None:
        for evidence in self._runs:
            evidence.revalidate()
        self.artifacts.revalidate()
        self.direct_artifacts.revalidate()
        for root in self._tree_roots.values():
            try:
                held = os.fstat(root.descriptor)
                visible = os.stat(root.name, dir_fd=root.parent, follow_symlinks=False)
                held_parent = os.fstat(root.parent)
                visible_parent = root.parent_path.lstat()
                resolved = root.path.resolve(strict=True)
                resolved_parent = root.parent_path.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise KimiDiagnosticUnionError("diagnostic_evidence_root_changed") from error
            if (
                split._directory_identity(held) != root.identity
                or split._directory_identity(visible) != root.identity
                or split._directory_identity(held_parent) != root.parent_identity
                or split._directory_identity(visible_parent) != root.parent_identity
                or resolved != root.path
                or resolved_parent != root.parent_path
            ):
                raise KimiDiagnosticUnionError("diagnostic_evidence_root_changed")

    def evidence_roots(self) -> tuple[Path, ...]:
        roots = set(self._tree_roots)
        roots.update(evidence.root for evidence in self._runs)
        roots.update(artifact.parent_path for artifact in self.artifacts.artifacts.values())
        roots.update(artifact.parent_path for artifact in self.direct_artifacts.artifacts.values())
        return tuple(sorted(roots, key=str))

    def evidence_directory_descriptors(self) -> tuple[int, ...]:
        descriptors = [root.descriptor for root in self._tree_roots.values()]
        descriptors.extend(evidence.directory for evidence in self._runs)
        descriptors.extend(artifact.parent for artifact in self.artifacts.artifacts.values())
        descriptors.extend(artifact.parent for artifact in self.direct_artifacts.artifacts.values())
        return tuple(descriptors)


def _read_plan(
    path: Path,
    expected_sha256: str,
    *,
    code: str,
    held: split._HeldArtifactSet,
) -> tuple[bytes, dict[str, Any]]:
    try:
        body = split.read_regular(
            path,
            code=code,
            maximum_bytes=2 * 1024 * 1024,
            private=True,
            held=held,
        )
    except split.KimiProviderSplitError as error:
        raise KimiDiagnosticUnionError(code) from error
    if split.SHA256_RE.fullmatch(expected_sha256 or "") is None or split.sha256_bytes(body) != expected_sha256:
        raise KimiDiagnosticUnionError(f"{code}_digest_mismatch")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KimiDiagnosticUnionError(code) from error
    if not isinstance(value, dict) or split.canonical_json(value) != body:
        raise KimiDiagnosticUnionError(code)
    return body, value


def _artifact_digest(plan: Mapping[str, Any], name: str) -> str:
    source = plan.get("source")
    record = source.get(name) if isinstance(source, dict) else None
    digest = record.get("sha256") if isinstance(record, dict) else None
    if not isinstance(digest, str) or split.SHA256_RE.fullmatch(digest) is None:
        raise KimiDiagnosticUnionError("plan_source_invalid")
    return digest


def _selector_members(
    path: Path,
    expected_count: int,
    held: split._HeldArtifactSet,
) -> tuple[str, ...]:
    try:
        body = split.read_regular(
            path,
            code="selector_invalid",
            maximum_bytes=1 << 20,
            private=True,
            held=held,
        )
        text = body.decode("utf-8")
    except (split.KimiProviderSplitError, UnicodeDecodeError) as error:
        raise KimiDiagnosticUnionError("selector_invalid") from error
    members = tuple(text.splitlines())
    if (
        len(members) != expected_count
        or len(set(members)) != expected_count
        or any(split.TASK_ID_RE.fullmatch(member) is None for member in members)
        or body != split._selector_payload(members)
    ):
        raise KimiDiagnosticUnionError("selector_invalid")
    return members


def _int_field(value: object, *, code: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise KimiDiagnosticUnionError(code) from error
    if isinstance(value, bool) or parsed < 1 or str(parsed) != str(value):
        raise KimiDiagnosticUnionError(code)
    return parsed


def _assert_exact_partition(
    legacy: tuple[str, ...],
    memory_8g: tuple[str, ...],
    memory_16g: tuple[str, ...],
    compose: tuple[str, ...],
    gpu: tuple[str, ...],
    all_tasks: set[str],
) -> None:
    groups = tuple(map(set, (legacy, memory_8g, memory_16g, compose, gpu)))
    expected_counts = (
        split.LEGACY_SANDOQ_TASKS,
        fallback.MEMORY_8G_TASKS,
        fallback.MEMORY_16G_TASKS,
        fallback.COMPOSE_EXCLUDED_TASKS,
        fallback.GPU_UNSUPPORTED_TASKS,
    )
    if tuple(map(len, groups)) != expected_counts:
        raise KimiDiagnosticUnionError("diagnostic_partition_cardinality_invalid")
    if any(groups[left] & groups[right] for left in range(len(groups)) for right in range(left + 1, len(groups))):
        raise KimiDiagnosticUnionError("diagnostic_partition_overlap")
    if set().union(*groups) != all_tasks:
        raise KimiDiagnosticUnionError("diagnostic_partition_not_exhaustive")


def _retain_artifact(
    record: object,
    held: split._HeldArtifactSet,
    *,
    code: str,
) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise KimiDiagnosticUnionError(code)
    path_value = record.get("path")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise KimiDiagnosticUnionError(code)
    path = Path(path_value)
    try:
        body = split.read_regular(
            path,
            code=code,
            maximum_bytes=8 * 1024 * 1024,
            private=True,
            held=held,
        )
    except split.KimiProviderSplitError as error:
        raise KimiDiagnosticUnionError(code) from error
    if record.get("bytes") != len(body) or record.get("sha256") != split.sha256_bytes(body):
        raise KimiDiagnosticUnionError(code)
    return path, body


def _retain_private_bundle(
    directory: Path,
    names: tuple[str, ...],
    held: split._HeldArtifactSet,
) -> dict[str, bytes]:
    bodies: dict[str, bytes] = {}
    for name in names:
        bodies[name] = split.read_regular(
            directory / name,
            code="diagnostic_plan_evidence_invalid",
            maximum_bytes=8 * 1024 * 1024,
            private=True,
            held=held,
        )
    marker = split.read_regular(
        directory / split.BUNDLE_COMMIT,
        code="diagnostic_plan_evidence_invalid",
        maximum_bytes=64 * 1024,
        private=True,
        held=held,
    )
    if marker != split._committed_bundle_files(bodies)[split.BUNDLE_COMMIT]:
        raise KimiDiagnosticUnionError("diagnostic_plan_evidence_invalid")
    return bodies


def authenticate_plans(
    standard_plan_path: Path,
    standard_plan_sha256: str,
    fallback_plan_path: Path,
    fallback_plan_sha256: str,
    held: split._HeldArtifactSet,
) -> PlanBinding:
    """Authenticate both sealed plans and return only their private bindings."""

    try:
        standard_lane = standard.verify_launch_plan(
            standard_plan_path,
            standard_plan_sha256,
            "legacy_sandoq",
        )
        fallback_8g = fallback.verify_completed(
            fallback_plan_path,
            fallback_plan_sha256,
            "memory_8g",
        )
        fallback_16g = fallback.verify_completed(
            fallback_plan_path,
            fallback_plan_sha256,
            "memory_16g",
        )
    except (standard.PreparationError, fallback.FallbackPreparationError, split.KimiProviderSplitError) as error:
        raise KimiDiagnosticUnionError("diagnostic_plan_invalid") from error

    _standard_body, standard_plan = _read_plan(
        standard_plan_path,
        standard_plan_sha256,
        code="standard_plan_invalid",
        held=held,
    )
    _fallback_body, fallback_plan = _read_plan(
        fallback_plan_path,
        fallback_plan_sha256,
        code="fallback_plan_invalid",
        held=held,
    )
    for name in ("resource_manifest", "image_manifest", "base_config"):
        if _artifact_digest(standard_plan, name) != _artifact_digest(fallback_plan, name):
            raise KimiDiagnosticUnionError("diagnostic_plan_source_mismatch")

    manifest_paths = tuple(Path(str(lane["manifest"])) for lane in (standard_lane, fallback_8g, fallback_16g))
    manifest_digests = tuple(str(lane["manifest_sha256"]) for lane in (standard_lane, fallback_8g, fallback_16g))
    if len(set(manifest_digests)) != 1:
        raise KimiDiagnosticUnionError("diagnostic_manifest_mismatch")
    try:
        manifest_bodies = tuple(
            split.read_regular(path, code="resource_manifest_invalid", private=True, held=held)
            for path in manifest_paths
        )
        manifest_value, entries = split.parse_manifest(manifest_bodies[0], manifest_digests[0])
        standard_partition, _receipt = split._read_partition_bundle(
            Path(str(standard_lane["partition_dir"])),
            manifest_paths[0],
            manifest_digests[0],
            held,
        )
    except split.KimiProviderSplitError as error:
        raise KimiDiagnosticUnionError("diagnostic_partition_invalid") from error
    if len(set(manifest_bodies)) != 1:
        raise KimiDiagnosticUnionError("diagnostic_manifest_mismatch")

    fallback_partition_dir = Path(str(fallback_8g["partition_dir"]))
    if fallback_partition_dir != Path(str(fallback_16g["partition_dir"])):
        raise KimiDiagnosticUnionError("diagnostic_fallback_partition_mismatch")
    low = _selector_members(fallback_partition_dir / fallback.LOW_SELECTOR, fallback.LOW_RESOURCE_TASKS, held)
    memory_8g = _selector_members(
        Path(str(fallback_8g["selector"])),
        fallback.MEMORY_8G_TASKS,
        held,
    )
    memory_16g = _selector_members(
        Path(str(fallback_16g["selector"])),
        fallback.MEMORY_16G_TASKS,
        held,
    )
    compose = _selector_members(
        fallback_partition_dir / fallback.COMPOSE_SELECTOR,
        fallback.COMPOSE_EXCLUDED_TASKS,
        held,
    )
    gpu = _selector_members(
        fallback_partition_dir / fallback.GPU_SELECTOR,
        fallback.GPU_UNSUPPORTED_TASKS,
        held,
    )
    all_tasks = {entry.task_id for entry in entries}
    _assert_exact_partition(low, memory_8g, memory_16g, compose, gpu, all_tasks)
    if (
        set(low) != set(standard_partition.legacy_sandoq)
        or set(memory_8g) | set(memory_16g) | set(compose) != set(standard_partition.large_provider)
        or set(compose) != set(standard_partition.compose_required)
        or set(gpu) != set(standard_partition.gpu_unsupported)
    ):
        raise KimiDiagnosticUnionError("diagnostic_plan_partition_mismatch")

    outputs = {
        Path(str(standard_lane["output_dir"])),
        Path(str(fallback_8g["output_dir"])),
        Path(str(fallback_16g["output_dir"])),
    }
    if len(outputs) != len(EXPECTED_LANES) or any(not path.is_absolute() for path in outputs):
        raise KimiDiagnosticUnionError("diagnostic_output_binding_invalid")

    lanes = (
        LaneBinding(
            name="standard_legacy",
            role="kimi-direct-tb4-diagnostic",
            output_dir=Path(str(standard_lane["output_dir"])),
            config_sha256=str(standard_lane["config_sha256"]),
            selector_sha256=str(standard_lane["selector_sha256"]),
            members=tuple(standard_partition.legacy_sandoq),
            concurrency=_int_field(standard_lane["concurrency"], code="standard_lane_invalid"),
            resource_multiplier=1.0,
            memory_resource_multiplier=None,
            enable_compose=True,
        ),
        LaneBinding(
            name="fallback_memory_8g",
            role="kimi-direct-tb4-sandoq-fallback-diagnostic",
            output_dir=Path(str(fallback_8g["output_dir"])),
            config_sha256=str(fallback_8g["config_sha256"]),
            selector_sha256=str(fallback_8g["selector_sha256"]),
            members=memory_8g,
            concurrency=_int_field(fallback_8g["concurrency"], code="fallback_lane_invalid"),
            resource_multiplier=1.0,
            memory_resource_multiplier=fallback.MEMORY_8G_MULTIPLIER,
            enable_compose=False,
        ),
        LaneBinding(
            name="fallback_memory_16g",
            role="kimi-direct-tb4-sandoq-fallback-diagnostic",
            output_dir=Path(str(fallback_16g["output_dir"])),
            config_sha256=str(fallback_16g["config_sha256"]),
            selector_sha256=str(fallback_16g["selector_sha256"]),
            members=memory_16g,
            concurrency=_int_field(fallback_16g["concurrency"], code="fallback_lane_invalid"),
            resource_multiplier=1.0,
            memory_resource_multiplier=fallback.MEMORY_16G_MULTIPLIER,
            enable_compose=False,
        ),
    )
    if tuple(len(lane.members) for lane in lanes) != (
        split.LEGACY_SANDOQ_TASKS,
        fallback.MEMORY_8G_TASKS,
        fallback.MEMORY_16G_TASKS,
    ):
        raise KimiDiagnosticUnionError("diagnostic_executed_coverage_invalid")

    standard_partition_dir = Path(str(standard_lane["partition_dir"]))
    standard_launch_bodies = _retain_private_bundle(
        standard_plan_path.parent,
        (
            standard.LEGACY_CONFIG,
            standard.LARGE_CONFIG,
            standard.REVIEWED_BASE_CONFIG,
            standard.LAUNCH_PLAN,
        ),
        held,
    )
    standard_resource_bodies = _retain_private_bundle(
        manifest_paths[0].parent,
        (standard.RESOURCE_MANIFEST, standard.PINNED_IMAGE_MANIFEST),
        held,
    )
    standard_partition_bodies = _retain_private_bundle(
        standard_partition_dir,
        (
            split.LEGACY_SELECTOR,
            split.LARGE_SELECTOR,
            split.GPU_SELECTOR,
            split.PARTITION_RECEIPT,
        ),
        held,
    )
    fallback_launch_bodies = _retain_private_bundle(
        fallback_plan_path.parent,
        (
            fallback.MEMORY_8G_CONFIG,
            fallback.MEMORY_16G_CONFIG,
            fallback.BASE_CONFIG,
            fallback.PLAN,
        ),
        held,
    )
    fallback_resource_bodies = _retain_private_bundle(
        manifest_paths[1].parent,
        (fallback.RESOURCE_MANIFEST, fallback.PINNED_IMAGE_MANIFEST),
        held,
    )
    fallback_partition_bodies = _retain_private_bundle(
        fallback_partition_dir,
        (
            fallback.LOW_SELECTOR,
            fallback.MEMORY_8G_SELECTOR,
            fallback.MEMORY_16G_SELECTOR,
            fallback.COMPOSE_SELECTOR,
            fallback.GPU_SELECTOR,
            fallback.PARTITION_RECEIPT,
        ),
        held,
    )
    expected_fallback_partition = fallback._partition_files(
        manifest_digests[0],
        fallback.FallbackPartition(low, memory_8g, memory_16g, compose, gpu),
    )
    if fallback_partition_bodies != expected_fallback_partition:
        raise KimiDiagnosticUnionError("diagnostic_fallback_partition_mismatch")
    for plan, launch_bodies, resource_bodies in (
        (standard_plan, standard_launch_bodies, standard_resource_bodies),
        (fallback_plan, fallback_launch_bodies, fallback_resource_bodies),
    ):
        source = plan["source"]
        for name, bundle, member in (
            ("resource_manifest", resource_bodies, standard.RESOURCE_MANIFEST),
            ("image_manifest", resource_bodies, standard.PINNED_IMAGE_MANIFEST),
            ("base_config", launch_bodies, standard.REVIEWED_BASE_CONFIG),
        ):
            _path, body = _retain_artifact(source[name], held, code="diagnostic_plan_source_invalid")
            if body != bundle[member]:
                raise KimiDiagnosticUnionError("diagnostic_plan_source_invalid")
    for plan, partition_bodies, receipt_name in (
        (standard_plan, standard_partition_bodies, split.PARTITION_RECEIPT),
        (fallback_plan, fallback_partition_bodies, fallback.PARTITION_RECEIPT),
    ):
        _receipt_path, receipt_body = _retain_artifact(
            plan["source"]["partition_receipt"],
            held,
            code="diagnostic_plan_source_invalid",
        )
        if receipt_body != partition_bodies[receipt_name]:
            raise KimiDiagnosticUnionError("diagnostic_plan_source_invalid")
    for lane, selector_body, config_body in (
        (
            standard_plan["lanes"]["legacy_sandoq"],
            split._selector_payload(standard_partition.legacy_sandoq),
            standard_launch_bodies[standard.LEGACY_CONFIG],
        ),
        (
            standard_plan["lanes"]["large_provider"],
            split._selector_payload(standard_partition.large_provider),
            standard_launch_bodies[standard.LARGE_CONFIG],
        ),
        (
            fallback_plan["lanes"]["memory_8g"],
            fallback_partition_bodies[fallback.MEMORY_8G_SELECTOR],
            fallback_launch_bodies[fallback.MEMORY_8G_CONFIG],
        ),
        (
            fallback_plan["lanes"]["memory_16g"],
            fallback_partition_bodies[fallback.MEMORY_16G_SELECTOR],
            fallback_launch_bodies[fallback.MEMORY_16G_CONFIG],
        ),
    ):
        _selector_path, retained_selector = _retain_artifact(
            lane["selector"],
            held,
            code="diagnostic_plan_lane_invalid",
        )
        _config_path, retained_config = _retain_artifact(
            lane["config"],
            held,
            code="diagnostic_plan_lane_invalid",
        )
        if retained_selector != selector_body or retained_config != config_body:
            raise KimiDiagnosticUnionError("diagnostic_plan_lane_invalid")
    return PlanBinding(
        standard_plan_sha256=standard_plan_sha256,
        fallback_plan_sha256=fallback_plan_sha256,
        manifest_sha256=manifest_digests[0],
        manifest_value=manifest_value,
        verifier_modes=standard_partition.verifier_modes,
        lanes=lanes,
        compose_excluded=compose,
        gpu_unsupported=gpu,
    )


def _source_contract(identity: Mapping[str, Any]) -> dict[str, Any]:
    source = identity.get("source")
    if not isinstance(source, dict):
        raise KimiDiagnosticUnionError("diagnostic_run_identity_invalid")
    keys = (
        "sandbox_provider",
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
        "sandoq_provider_commit",
        "sandoq_provider_tree",
        "sandoq_client_version",
        "sandoq_site_sha256",
        "sandoq_host_harness_sha256",
        "derived_image_manifest_sha256",
    )
    result = {key: source.get(key) for key in keys}
    if any(not isinstance(value, str) or not value for value in result.values()):
        raise KimiDiagnosticUnionError("diagnostic_source_contract_invalid")
    return result


def _validate_run_identity(
    identity: Mapping[str, Any],
    lane: LaneBinding,
    plan: PlanBinding,
    retained: split._HeldArtifactSet,
    direct_retained: direct_workers._HeldArtifactSet,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    source = identity.get("source")
    source_project_root = source.get("project_root") if isinstance(source, dict) else None
    config_record = identity.get("config")
    task_record = identity.get("inputs", {}).get("task_file")
    image_record = identity.get("inputs", {}).get("image_manifest")
    dataset = identity.get("dataset")
    execution = identity.get("execution")
    environment = execution.get("sandoq_environment") if isinstance(execution, dict) else None
    manifest_source = plan.manifest_value.get("source")
    if (
        identity.get("role") != lane.role
        or not isinstance(source, dict)
        or not isinstance(source_project_root, str)
        or not Path(source_project_root).is_absolute()
        or source.get("sandbox_provider") != "sandoq"
        or not isinstance(config_record, dict)
        or config_record.get("source", {}).get("sha256") != lane.config_sha256
        or not isinstance(task_record, dict)
        or task_record.get("sha256") != lane.selector_sha256
        or task_record.get("count") != len(lane.members)
        or not isinstance(image_record, dict)
        or not isinstance(manifest_source, dict)
        or image_record.get("sha256") != manifest_source.get("image_manifest_sha256")
        or source.get("derived_image_manifest_sha256") != manifest_source.get("image_manifest_sha256")
        or not isinstance(dataset, dict)
        or dataset.get("content_sha256") != manifest_source.get("dataset_content_sha256")
        or not isinstance(execution, dict)
        or execution.get("cleanup_must_succeed") is not True
        or execution.get("runtime", {}).get("type") != "sandoq"
        or any(
            execution.get(key) != lane.concurrency
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or not isinstance(environment, dict)
        or environment.get("environment") != "oci-runner"
        or environment.get("task_network") != "public"
        or environment.get("pool_size") != lane.concurrency
        or environment.get("pool_min_size") != 0
        or environment.get("lease_profile") != "kimi-tb4-long"
        or environment.get("lease_duration") != "12h"
        or environment.get("pool_renew_interval") != "5m"
    ):
        raise KimiDiagnosticUnionError("diagnostic_run_identity_invalid")

    selector_path = Path(str(task_record.get("path", "")))
    selector_body = split.read_regular(
        selector_path,
        code="diagnostic_run_selector_invalid",
        maximum_bytes=1 << 20,
        private=True,
        held=retained,
    )
    if selector_body != split._selector_payload(lane.members):
        raise KimiDiagnosticUnionError("diagnostic_run_selector_invalid")
    config = split._resolved_config(identity, retained)
    taskset = config.get("taskset")
    client = config.get("client")
    memory_resource_multiplier = taskset.get("memory_resource_multiplier") if isinstance(taskset, dict) else None
    if (
        config.get("num_tasks") != len(lane.members)
        or config.get("max_concurrent") != lane.concurrency
        or config.get("multiplex") != lane.concurrency
        or not isinstance(client, dict)
        or client.get("max_connections") != lane.concurrency
        or client.get("max_keepalive_connections") != lane.concurrency
        or not isinstance(taskset, dict)
        or taskset.get("task_file_sha256") != lane.selector_sha256
        or taskset.get("resource_multiplier") != lane.resource_multiplier
        or memory_resource_multiplier != lane.memory_resource_multiplier
        or taskset.get("enable_compose") is not lane.enable_compose
    ):
        raise KimiDiagnosticUnionError("diagnostic_run_config_invalid")
    try:
        model_contract = split._model_contract(identity)
        split._environment_identity(identity)
        deployment = identity.get("deployment")
        worker = deployment.get("worker_manifest") if isinstance(deployment, dict) else None
        if not isinstance(worker, dict):
            raise KimiDiagnosticUnionError("diagnostic_deployment_invalid")
        manifest_path = Path(str(worker.get("path", "")))
        manifest_body, worker_manifest = direct_workers.load_saved_manifest(
            manifest_path,
            revalidate_live_source=True,
            held=direct_retained,
        )
        if split.sha256_bytes(manifest_body) != worker.get("sha256"):
            raise KimiDiagnosticUnionError("diagnostic_deployment_invalid")
        direct_workers._validate_deployment_binding(
            dict(deployment),
            manifest_path,
            str(worker["sha256"]),
            worker_manifest,
        )
        source_router_body = split.read_regular(
            Path(source_project_root) / "user/tianhaowu/terminal_bench_vmvm/direct_kimi_router.py",
            code="diagnostic_deployment_invalid",
            maximum_bytes=4 * 1024 * 1024,
            private=False,
            held=retained,
        )
        if split.sha256_bytes(source_router_body) != worker_manifest["router"]["implementation_sha256"]:
            raise KimiDiagnosticUnionError("diagnostic_deployment_invalid")
        worker_generation = direct_workers.worker_generation_contract(
            worker_manifest,
            revalidate_live_source=False,
            held=direct_retained,
        )
    except (split.KimiProviderSplitError, direct_workers.DirectKimiWorkerError) as error:
        raise KimiDiagnosticUnionError("diagnostic_deployment_invalid") from error
    source_contract = _source_contract(identity)
    resolved_config = config_record.get("resolved")
    if (
        not isinstance(resolved_config, dict)
        or split.SHA256_RE.fullmatch(str(resolved_config.get("sha256", ""))) is None
    ):
        raise KimiDiagnosticUnionError("diagnostic_run_config_invalid")
    return (
        model_contract,
        split.sha256_bytes(split.canonical_json(worker_generation)),
        source_contract,
        {
            "source_closure_sha256": split.sha256_bytes(split.canonical_json(source_contract)),
            "resolved_config_sha256": str(resolved_config["sha256"]),
            "worker_manifest": {
                "bytes": len(manifest_body),
                "sha256": split.sha256_bytes(manifest_body),
            },
        },
    )


def _slurm_job_id(provenance: bytes) -> str:
    try:
        lines = provenance.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise KimiDiagnosticUnionError("diagnostic_run_provenance_invalid") from error
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or PROVENANCE_KEY_RE.fullmatch(key) is None or not value or key in records:
            raise KimiDiagnosticUnionError("diagnostic_run_provenance_invalid")
        records[key] = value
    job_id = records.get("slurm_job_id")
    if re.fullmatch(r"[1-9][0-9]*", str(job_id or "")) is None:
        raise KimiDiagnosticUnionError("diagnostic_run_provenance_invalid")
    return str(job_id)


def _digest_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {"bytes": record["bytes"], "sha256": record["sha256"]}


def _retain_run_references(
    identity: Mapping[str, Any],
    run_dir: Path,
    held: split._HeldArtifactSet,
) -> None:
    config = identity.get("config")
    inputs = identity.get("inputs")
    if not isinstance(config, dict) or not isinstance(inputs, dict):
        raise KimiDiagnosticUnionError("diagnostic_run_reference_invalid")
    references = (
        (config.get("resolved"), run_dir / "config.toml"),
        (config.get("source"), run_dir / "inputs/source_config.toml"),
        (inputs.get("manifest"), run_dir / "inputs/manifest.json"),
        (inputs.get("task_file"), run_dir / "inputs/task_file.txt"),
        (inputs.get("image_manifest"), run_dir / "inputs/image_manifest.json"),
    )
    for record, expected_path in references:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("path"), str)
            or Path(record["path"]) != expected_path
            or split.SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
        ):
            raise KimiDiagnosticUnionError("diagnostic_run_reference_invalid")
        try:
            body = split.read_regular(
                expected_path,
                code="diagnostic_run_reference_invalid",
                maximum_bytes=8 * 1024 * 1024,
                private=True,
                held=held,
            )
        except split.KimiProviderSplitError as error:
            raise KimiDiagnosticUnionError("diagnostic_run_reference_invalid") from error
        if split.sha256_bytes(body) != record["sha256"]:
            raise KimiDiagnosticUnionError("diagnostic_run_reference_invalid")


def _retain_identity_tree_roots(
    identity: Mapping[str, Any],
    retained: RetainedAuditEvidence,
) -> None:
    source = identity.get("source")
    dataset = identity.get("dataset")
    if not isinstance(source, dict) or not isinstance(dataset, dict):
        raise KimiDiagnosticUnionError("diagnostic_evidence_root_invalid")
    roots = (
        source.get("project_root"),
        source.get("sandoq_site"),
        dataset.get("path"),
    )
    if any(not isinstance(value, str) or not Path(value).is_absolute() for value in roots):
        raise KimiDiagnosticUnionError("diagnostic_evidence_root_invalid")
    retained.retain_source_closure(source)
    for value in roots:
        assert isinstance(value, str)
        retained.retain_tree_root(Path(value))


def _validate_expected_revision(value: str, *, code: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value or "") is None:
        raise KimiDiagnosticUnionError(code)
    return value


def _validate_source_revision_policy(
    sources: Mapping[str, Mapping[str, Any]],
    *,
    expected_standard_revision: str,
    expected_fallback_revision: str,
) -> None:
    standard_revision = _validate_expected_revision(
        expected_standard_revision,
        code="standard_source_revision_invalid",
    )
    fallback_revision = _validate_expected_revision(
        expected_fallback_revision,
        code="fallback_source_revision_invalid",
    )
    if standard_revision == fallback_revision:
        raise KimiDiagnosticUnionError("diagnostic_source_revisions_not_distinct")
    if set(sources) != set(EXPECTED_LANES):
        raise KimiDiagnosticUnionError("diagnostic_source_group_invalid")
    standard_source = sources["standard_legacy"]
    fallback_8g = sources["fallback_memory_8g"]
    fallback_16g = sources["fallback_memory_16g"]
    if fallback_8g != fallback_16g:
        raise KimiDiagnosticUnionError("fallback_source_revision_mismatch")
    if standard_source == fallback_8g:
        raise KimiDiagnosticUnionError("diagnostic_source_closures_not_distinct")
    if standard_source.get("prime_rl_commit") != standard_revision:
        raise KimiDiagnosticUnionError("standard_source_revision_mismatch")
    if (
        fallback_8g.get("prime_rl_commit") != fallback_revision
        or fallback_16g.get("prime_rl_commit") != fallback_revision
    ):
        raise KimiDiagnosticUnionError("fallback_source_revision_mismatch")


def _validate_output_location(output: Path, evidence_roots: tuple[Path, ...]) -> None:
    try:
        normalized = Path(os.path.abspath(os.fspath(output)))
        parent = output.parent.resolve(strict=True)
    except (OSError, TypeError, ValueError) as error:
        raise KimiDiagnosticUnionError("diagnostic_output_path_invalid") from error
    if not output.is_absolute() or output != normalized or parent != output.parent or not output.name:
        raise KimiDiagnosticUnionError("diagnostic_output_path_invalid")
    for root in evidence_roots:
        try:
            normalized_root = Path(os.path.abspath(os.fspath(root)))
            resolved_root = root.resolve(strict=True)
        except (OSError, TypeError, ValueError) as error:
            raise KimiDiagnosticUnionError("diagnostic_evidence_root_invalid") from error
        if not root.is_absolute() or root != normalized_root or resolved_root != root:
            raise KimiDiagnosticUnionError("diagnostic_evidence_root_invalid")
        if parent == root or parent.is_relative_to(root) or root.is_relative_to(parent):
            raise KimiDiagnosticUnionError("diagnostic_output_evidence_overlap")


def _directory_ancestry(descriptor: int) -> tuple[tuple[int, int], ...]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    current = os.dup(descriptor)
    identities: list[tuple[int, int]] = []
    try:
        for _depth in range(4096):
            metadata = os.fstat(current)
            identity = (metadata.st_dev, metadata.st_ino)
            if identity in identities:
                if identity == identities[-1]:
                    return tuple(identities)
                raise KimiDiagnosticUnionError("diagnostic_directory_ancestry_invalid")
            identities.append(identity)
            parent = -1
            try:
                parent = os.open("..", flags, dir_fd=current)
                parent_metadata = os.fstat(parent)
            except BaseException:
                if parent >= 0:
                    with suppress(OSError):
                        os.close(parent)
                raise
            parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
            previous = current
            current = parent
            os.close(previous)
            if parent_identity == identity:
                return tuple(identities)
    except OSError as error:
        raise KimiDiagnosticUnionError("diagnostic_directory_ancestry_invalid") from error
    finally:
        with suppress(OSError):
            os.close(current)
    raise KimiDiagnosticUnionError("diagnostic_directory_ancestry_invalid")


def _validate_output_inode_disjoint(
    output_parent: int,
    evidence_directories: tuple[int, ...],
) -> None:
    output_ancestry = _directory_ancestry(output_parent)
    output_identity = output_ancestry[0]
    for descriptor in evidence_directories:
        evidence_ancestry = _directory_ancestry(descriptor)
        evidence_identity = evidence_ancestry[0]
        if evidence_identity in output_ancestry or output_identity in evidence_ancestry:
            raise KimiDiagnosticUnionError("diagnostic_output_evidence_overlap")


@dataclass(slots=True)
class _PendingDiagnosticOutput:
    path: Path
    parent: Path
    parent_descriptor: int
    parent_identity: tuple[int, int, int, int]
    payload: bytes
    payload_identity: tuple[int, ...]
    marker_name: str
    marker_payload: bytes

    def revalidate(self, retained: RetainedAuditEvidence) -> None:
        try:
            if split._verify_file_at(self.parent_descriptor, self.path.name, self.payload) != self.payload_identity:
                raise KimiDiagnosticUnionError("diagnostic_output_changed")
            split._validate_private_parent(self.parent, self.parent_descriptor, self.parent_identity)
            _validate_output_location(self.path, retained.evidence_roots())
            _validate_output_inode_disjoint(
                self.parent_descriptor,
                retained.evidence_directory_descriptors(),
            )
            try:
                os.stat(self.marker_name, dir_fd=self.parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise KimiDiagnosticUnionError("diagnostic_output_marker_exists")
            os.fsync(self.parent_descriptor)
        except KimiDiagnosticUnionError:
            raise
        except (OSError, split.KimiProviderSplitError) as error:
            raise KimiDiagnosticUnionError("diagnostic_output_changed") from error

    def commit(self) -> None:
        """Publish the marker as the final acceptance operation."""

        try:
            split._write_at(self.parent_descriptor, self.marker_name, self.marker_payload)
        except (OSError, split.KimiProviderSplitError) as error:
            raise KimiDiagnosticUnionError("diagnostic_output_publication_indeterminate") from error

    def close_after_commit(self) -> None:
        with suppress(OSError):
            os.close(self.parent_descriptor)
        self.parent_descriptor = -1

    def close(self) -> None:
        if self.parent_descriptor >= 0:
            os.close(self.parent_descriptor)
            self.parent_descriptor = -1


def _prepare_diagnostic_output(
    output: Path,
    value: Mapping[str, Any],
    retained: RetainedAuditEvidence,
) -> _PendingDiagnosticOutput:
    _validate_output_location(output, retained.evidence_roots())
    try:
        path = split._absolute_path(output)
        parent, parent_descriptor, parent_identity = split._open_private_parent(path.parent)
    except split.KimiProviderSplitError as error:
        raise KimiDiagnosticUnionError("diagnostic_output_path_invalid") from error
    payload = split.canonical_json(value)
    marker_name = f".{path.name}{split.FILE_COMMIT_SUFFIX}"
    marker_payload = split._file_commit_payload(path.name, payload)
    try:
        _validate_output_inode_disjoint(
            parent_descriptor,
            retained.evidence_directory_descriptors(),
        )
        for name in (path.name, marker_name):
            try:
                os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise KimiDiagnosticUnionError("diagnostic_output_already_exists")
        payload_identity = split._write_at(parent_descriptor, path.name, payload)
        if split._verify_file_at(parent_descriptor, path.name, payload) != payload_identity:
            raise KimiDiagnosticUnionError("diagnostic_output_changed")
        split._validate_private_parent(parent, parent_descriptor, parent_identity)
        os.fsync(parent_descriptor)
        return _PendingDiagnosticOutput(
            path=path,
            parent=parent,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            payload=payload,
            payload_identity=payload_identity,
            marker_name=marker_name,
            marker_payload=marker_payload,
        )
    except BaseException:
        os.close(parent_descriptor)
        raise


def _validate_lane_compatibility(contracts: Mapping[str, Mapping[str, Any]]) -> None:
    if set(contracts) != set(EXPECTED_LANES):
        raise KimiDiagnosticUnionError("diagnostic_lane_set_invalid")
    reference = contracts["standard_legacy"]
    if any(contracts[name] != reference for name in EXPECTED_LANES[1:]):
        raise KimiDiagnosticUnionError("diagnostic_lane_contract_mismatch")


def audit_lane(
    lane: LaneBinding,
    plan: PlanBinding,
    *,
    seen_trace_ids: set[str] | None = None,
    retained_evidence: RetainedAuditEvidence | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Audit one real output lane without returning task-level material."""

    try:
        if retained_evidence is None:
            with RetainedAuditEvidence() as owned_evidence:
                result = _audit_lane_retained(lane, plan, seen_trace_ids, owned_evidence)
                owned_evidence.revalidate()
                return result
        return _audit_lane_retained(lane, plan, seen_trace_ids, retained_evidence)
    except KimiDiagnosticUnionError:
        raise
    except (EvalIdentityError, split.KimiProviderSplitError, direct_workers.DirectKimiWorkerError, OSError) as error:
        raise KimiDiagnosticUnionError("diagnostic_lane_audit_failed") from error


def _audit_lane_retained(
    lane: LaneBinding,
    plan: PlanBinding,
    seen_trace_ids: set[str] | None,
    retained: RetainedAuditEvidence,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    run_dir = lane.output_dir
    evidence = retained.retain_run(run_dir)
    identity_body = evidence.files["eval_run_identity.json"].body
    invocation_body = evidence.files["eval_invocations.jsonl"].body
    provenance_body = evidence.files["provenance.txt"].body
    envelope = load_eval_run_identity_bytes(
        identity_body,
        run_dir=run_dir,
        verify_references=False,
        verify_saved_provenance=False,
    )
    _retain_identity_tree_roots(envelope["identity"], retained)
    _retain_run_references(envelope["identity"], run_dir, retained.artifacts)
    envelope = load_eval_run_identity_bytes(
        identity_body,
        run_dir=run_dir,
        verify_references=True,
        verify_saved_provenance=False,
    )
    identity_sha256, invocation_sha256, bound_identity = direct_workers.validate_run_binding_bytes(
        identity_body,
        invocation_body,
        provenance_body,
    )
    if envelope.get("eval_run_identity_sha256") != identity_sha256 or envelope.get("identity") != bound_identity:
        raise KimiDiagnosticUnionError("diagnostic_run_binding_invalid")
    identity = envelope["identity"]
    model_contract, generation_sha256, source_contract, lane_contract_digests = _validate_run_identity(
        identity,
        lane,
        plan,
        retained.artifacts,
        retained.direct_artifacts,
    )
    trace_audit, rows, results_artifact = split._audit_cpu_results(
        run_dir / "results.jsonl",
        lane.members,
        plan.verifier_modes,
        retained.artifacts,
    )
    trace_ids = {str(row["id"]) for row in rows.values()}
    if len(trace_ids) != len(rows) or (seen_trace_ids is not None and trace_ids & seen_trace_ids):
        raise KimiDiagnosticUnionError("diagnostic_trace_id_overlap")
    if seen_trace_ids is not None:
        seen_trace_ids.update(trace_ids)
    _router_body, router_artifact, router_marker_artifact = split._validate_direct_router_receipt(
        run_dir / "direct_kimi_router_final.json",
        identity,
        minimum_chat_requests=len(lane.members),
        identity_sha256=identity_sha256,
        invocation_identity_sha256=invocation_sha256,
        held=retained.artifacts,
    )
    cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
        run_dir / "sandoq_cleanup_audit.json",
        run_dir,
        identity,
        identity_sha256,
        invocation_sha256,
        _slurm_job_id(provenance_body),
        len(lane.members),
        lane.concurrency,
        retained.artifacts,
    )
    retained.revalidate()
    result = {
        "state": "audited",
        "sandbox_provider": "sandoq",
        "task_count": len(lane.members),
        "passes": trace_audit["passes"],
        "failures": trace_audit["failures"],
        "resource_multiplier": lane.resource_multiplier,
        "memory_resource_multiplier": lane.memory_resource_multiplier,
        "resource_fidelity": False,
        "certification_eligible": False,
        "trace_rollout_eligible": False,
        "eval_run_identity_sha256": identity_sha256,
        "invocation_identity_sha256": invocation_sha256,
        "config_sha256": lane.config_sha256,
        "selector_sha256": lane.selector_sha256,
        "worker_generation_contract_sha256": generation_sha256,
        "source_closure_sha256": lane_contract_digests["source_closure_sha256"],
        "resolved_config_sha256": lane_contract_digests["resolved_config_sha256"],
        "trace_audit": {
            "traces": trace_audit["traces"],
            "tasks": trace_audit["tasks"],
            "model_io_turns": trace_audit["model_io_turns"],
            "sampled_tokens": trace_audit["sampled_tokens"],
            "trace_failures": trace_audit["trace_failures"],
        },
        "cleanup": cleanup,
        "artifacts": {
            "worker_manifest": lane_contract_digests["worker_manifest"],
            "results": _digest_record(results_artifact),
            "router_receipt": _digest_record(router_artifact),
            "router_receipt_commit": _digest_record(router_marker_artifact),
            "cleanup_receipt": _digest_record(cleanup_artifacts["cleanup_receipt"]),
        },
    }
    return (
        result,
        {
            "model_contract": model_contract,
            "worker_generation_contract_sha256": generation_sha256,
        },
        source_contract,
    )


def _summary(
    plan: PlanBinding,
    lane_results: Mapping[str, Mapping[str, Any]],
    implementation_sha256: str,
    *,
    standard_source_revision: str,
    fallback_source_revision: str,
) -> dict[str, Any]:
    if set(lane_results) != set(EXPECTED_LANES):
        raise KimiDiagnosticUnionError("diagnostic_lane_set_invalid")
    lane_counts = tuple(lane_results[name].get("task_count") for name in EXPECTED_LANES)
    if lane_counts != (split.LEGACY_SANDOQ_TASKS, fallback.MEMORY_8G_TASKS, fallback.MEMORY_16G_TASKS):
        raise KimiDiagnosticUnionError("diagnostic_executed_coverage_invalid")
    for name, count in zip(EXPECTED_LANES, lane_counts, strict=True):
        lane = lane_results[name]
        passes_value = _int_or_zero(lane.get("passes"))
        failures_value = _int_or_zero(lane.get("failures"))
        if (
            lane.get("state") != "audited"
            or lane.get("resource_fidelity") is not False
            or lane.get("certification_eligible") is not False
            or lane.get("trace_rollout_eligible") is not False
            or passes_value + failures_value != count
        ):
            raise KimiDiagnosticUnionError("diagnostic_lane_result_invalid")
    passes = sum(_int_or_zero(lane_results[name].get("passes")) for name in EXPECTED_LANES)
    executed = sum(_int_field(value, code="diagnostic_lane_count_invalid") for value in lane_counts)
    if executed != EXECUTED_TASKS or executed + SYNTHETIC_ZERO_TASKS != split.TOTAL_TASKS or passes > executed:
        raise KimiDiagnosticUnionError("diagnostic_denominator_invalid")
    trace_counts = tuple(lane_results[name].get("trace_audit", {}).get("traces") for name in EXPECTED_LANES)
    trace_tasks = tuple(lane_results[name].get("trace_audit", {}).get("tasks") for name in EXPECTED_LANES)
    trace_failures = tuple(lane_results[name].get("trace_audit", {}).get("trace_failures") for name in EXPECTED_LANES)
    if sum(map(_int_or_zero, trace_counts)) != EXECUTED_TASKS or trace_counts != trace_tasks or any(trace_failures):
        raise KimiDiagnosticUnionError("diagnostic_trace_coverage_invalid")
    model_io_turns = sum(
        _int_or_zero(lane_results[name]["trace_audit"].get("model_io_turns")) for name in EXPECTED_LANES
    )
    sampled_tokens = sum(
        _int_or_zero(lane_results[name]["trace_audit"].get("sampled_tokens")) for name in EXPECTED_LANES
    )
    if model_io_turns < EXECUTED_TASKS or sampled_tokens < 1:
        raise KimiDiagnosticUnionError("diagnostic_capture_audit_invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "complete",
        "classification": {
            "diagnostic_only": True,
            "official_result": False,
            "resource_fidelity": False,
            "certification_eligible": False,
            "trace_rollout_eligible": False,
        },
        "model": "Kimi-K3",
        "pass_at_1": True,
        "task_count": split.TOTAL_TASKS,
        "coverage": {
            "executed": EXECUTED_TASKS,
            "synthetic_unsupported_zero": SYNTHETIC_ZERO_TASKS,
            "compose_excluded_zero": fallback.COMPOSE_EXCLUDED_TASKS,
            "gpu_unsupported_zero": fallback.GPU_UNSUPPORTED_TASKS,
            "total": split.TOTAL_TASKS,
            "disjoint": True,
            "exhaustive": True,
        },
        "scores": {
            "passes": passes,
            "all_task_denominator": split.TOTAL_TASKS,
            "all_task_pass_rate": passes / split.TOTAL_TASKS,
            "executed_denominator": EXECUTED_TASKS,
            "executed_pass_rate": passes / EXECUTED_TASKS,
            "synthetic_passes": 0,
        },
        "trace_audit": {
            "scope": "executed_rows_only",
            "traces": EXECUTED_TASKS,
            "tasks": EXECUTED_TASKS,
            "synthetic_rows_audited": 0,
            "model_io_turns": model_io_turns,
            "sampled_tokens": sampled_tokens,
            "trace_failures": 0,
            "reasoning_required": True,
            "model_io_required": True,
            "request_graph_match_required": True,
            "exact_provider_json_required": True,
            "max_sequence_tokens": split.MAX_SEQUENCE_TOKENS,
        },
        "lanes": {name: dict(lane_results[name]) for name in EXPECTED_LANES},
        "plans": {
            "standard_provider_partition": {"sha256": plan.standard_plan_sha256},
            "sandoq_fallback": {"sha256": plan.fallback_plan_sha256},
            "resource_manifest_sha256": plan.manifest_sha256,
            "source_revision_policy": {
                "kind": "independently_authenticated_plan_bound_groups",
                "standard_prime_rl_revision": standard_source_revision,
                "fallback_prime_rl_revision": fallback_source_revision,
                "fallback_lanes_same_source_closure": True,
                "standard_and_fallback_revisions_distinct": True,
                "standard_and_fallback_source_closures_distinct": True,
            },
        },
        "implementation_sha256": implementation_sha256,
    }


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KimiDiagnosticUnionError("diagnostic_count_invalid")
    return value


def build_diagnostic_union(
    *,
    standard_plan_path: Path,
    standard_plan_sha256: str,
    fallback_plan_path: Path,
    fallback_plan_sha256: str,
    standard_source_revision: str,
    fallback_source_revision: str,
    output: Path,
) -> dict[str, Any]:
    with RetainedAuditEvidence() as retained:
        try:
            implementation_body = split.read_regular(
                Path(__file__),
                code="implementation_unreadable",
                maximum_bytes=4 * 1024 * 1024,
                private=False,
                held=retained.artifacts,
            )
        except split.KimiProviderSplitError as error:
            raise KimiDiagnosticUnionError("implementation_unreadable") from error
        plan = authenticate_plans(
            standard_plan_path,
            standard_plan_sha256,
            fallback_plan_path,
            fallback_plan_sha256,
            retained.artifacts,
        )
        lane_results: dict[str, dict[str, Any]] = {}
        compatibility: dict[str, dict[str, Any]] = {}
        sources: dict[str, dict[str, Any]] = {}
        seen_trace_ids: set[str] = set()
        for lane in plan.lanes:
            result, observed_compatibility, source_contract = audit_lane(
                lane,
                plan,
                seen_trace_ids=seen_trace_ids,
                retained_evidence=retained,
            )
            lane_results[lane.name] = result
            compatibility[lane.name] = observed_compatibility
            sources[lane.name] = source_contract
        _validate_lane_compatibility(compatibility)
        _validate_source_revision_policy(
            sources,
            expected_standard_revision=standard_source_revision,
            expected_fallback_revision=fallback_source_revision,
        )
        _validate_output_location(output, retained.evidence_roots())
        value = _summary(
            plan,
            lane_results,
            hashlib.sha256(implementation_body).hexdigest(),
            standard_source_revision=standard_source_revision,
            fallback_source_revision=fallback_source_revision,
        )
        pending: _PendingDiagnosticOutput | None = None
        committed = False
        try:
            retained.revalidate()
            retained.revalidate_source_closures()
            pending = _prepare_diagnostic_output(output, value, retained)
            retained.revalidate()
            retained.revalidate_source_closures()
            # Source verification invokes Git and hashes the bound Sandoq
            # closure. Recheck every retained inode afterwards so a source
            # pathname substitution during that verification cannot survive
            # to the authoritative marker commit.
            retained.revalidate()
            pending.revalidate(retained)
            pending.commit()
            committed = True
            pending.close_after_commit()
            retained.close_after_commit()
            return value
        except KimiDiagnosticUnionError:
            raise
        except (split.KimiProviderSplitError, direct_workers.DirectKimiWorkerError, OSError) as error:
            raise KimiDiagnosticUnionError("diagnostic_evidence_changed") from error
        finally:
            if pending is not None and not committed:
                with suppress(OSError):
                    pending.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard-plan", type=Path, required=True)
    parser.add_argument("--standard-plan-sha256", required=True)
    parser.add_argument("--fallback-plan", type=Path, required=True)
    parser.add_argument("--fallback-plan-sha256", required=True)
    parser.add_argument("--standard-source-revision", required=True)
    parser.add_argument("--fallback-source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = build_diagnostic_union(
            standard_plan_path=args.standard_plan,
            standard_plan_sha256=args.standard_plan_sha256,
            fallback_plan_path=args.fallback_plan,
            fallback_plan_sha256=args.fallback_plan_sha256,
            standard_source_revision=args.standard_source_revision,
            fallback_source_revision=args.fallback_source_revision,
            output=args.output,
        )
    except KimiDiagnosticUnionError as error:
        parser.error(str(error))
    except Exception:
        parser.error("diagnostic_union_failed")
    print(
        json.dumps(
            {
                "state": value["state"],
                "diagnostic_only": True,
                "task_count": value["task_count"],
                "executed": value["coverage"]["executed"],
                "synthetic_unsupported_zero": value["coverage"]["synthetic_unsupported_zero"],
                "passes": value["scores"]["passes"],
                "all_task_pass_rate": value["scores"]["all_task_pass_rate"],
                "executed_pass_rate": value["scores"]["executed_pass_rate"],
                "resource_fidelity": False,
                "certification_eligible": False,
                "trace_rollout_eligible": False,
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
