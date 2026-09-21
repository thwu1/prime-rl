#!/usr/bin/env python3
"""Prepare and verify the private Kimi TB4 Sandoq fallback diagnostic.

Only the 21 high-resource, non-Compose CPU tasks are runnable.  They are split
by declared memory so each task fits the fixed 8-GiB Sandoq outer sandbox after
an explicitly lossy diagnostic memory multiplier.  CPU and disk requests stay
at their declared values.  Task identities are written solely to private
mode-0600 selectors and never to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_provider_split_launch as common

KIND = "kimi-tb4-sandoq-high-resource-noncompose-fallback-diagnostic"
PARTITION_KIND = "kimi-tb4-sandoq-fallback-partition"
SERVER_ID = "cpu-132-021_8103"
SERVER_SLUG = "cpu132021-8103"
LOW_RESOURCE_TASKS = 31
FALLBACK_TASKS = 21
MEMORY_8G_TASKS = 17
MEMORY_16G_TASKS = 4
COMPOSE_EXCLUDED_TASKS = 11
GPU_UNSUPPORTED_TASKS = 3
MEMORY_8G_CONCURRENCY = 6
MEMORY_16G_CONCURRENCY = 2
TOTAL_CONCURRENCY = MEMORY_8G_CONCURRENCY + MEMORY_16G_CONCURRENCY
MEMORY_8G_MULTIPLIER = 0.75
MEMORY_16G_MULTIPLIER = 0.375
RESOURCE_MULTIPLIER = 1.0
PARTITION_SCHEMA_VERSION = 2
PLAN_SCHEMA_VERSION = 2

RESOURCE_MANIFEST = common.RESOURCE_MANIFEST
PINNED_IMAGE_MANIFEST = common.PINNED_IMAGE_MANIFEST
MEMORY_8G_SELECTOR = "high-resource-noncompose-8g.tasks.txt"
MEMORY_16G_SELECTOR = "high-resource-noncompose-16g.tasks.txt"
LOW_SELECTOR = "low-resource-noncompose.tasks.txt"
COMPOSE_SELECTOR = "compose-excluded.tasks.txt"
GPU_SELECTOR = "gpu-unsupported.tasks.txt"
PARTITION_RECEIPT = "fallback-partition.json"
MEMORY_8G_CONFIG = "sandoq-high-resource-noncompose-8g.diagnostic.toml"
MEMORY_16G_CONFIG = "sandoq-high-resource-noncompose-16g.diagnostic.toml"
BASE_CONFIG = common.REVIEWED_BASE_CONFIG
PLAN = "fallback-launch-plan.json"

LANES = {
    "memory_8g": {
        "stage": "sandoq-fallback-memory-8g",
        "count": MEMORY_8G_TASKS,
        "concurrency": MEMORY_8G_CONCURRENCY,
        "memory_multiplier": MEMORY_8G_MULTIPLIER,
        "selector": MEMORY_8G_SELECTOR,
        "config": MEMORY_8G_CONFIG,
    },
    "memory_16g": {
        "stage": "sandoq-fallback-memory-16g",
        "count": MEMORY_16G_TASKS,
        "concurrency": MEMORY_16G_CONCURRENCY,
        "memory_multiplier": MEMORY_16G_MULTIPLIER,
        "selector": MEMORY_16G_SELECTOR,
        "config": MEMORY_16G_CONFIG,
    },
}


class FallbackPreparationError(ValueError):
    """Aggregate-only fallback preparation failure."""


@dataclass(frozen=True, slots=True)
class FallbackPartition:
    low_resource: tuple[str, ...]
    memory_8g: tuple[str, ...]
    memory_16g: tuple[str, ...]
    compose_excluded: tuple[str, ...]
    gpu_unsupported: tuple[str, ...]


def _selector(values: tuple[str, ...]) -> bytes:
    return split._selector_payload(values)


def _has_compose(task_dir: Path) -> bool:
    names = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
    try:
        entries = tuple(os.scandir(task_dir / "environment"))
    except OSError as error:
        raise FallbackPreparationError("task_environment_invalid") from error
    matched = tuple(entry for entry in entries if entry.name in names)
    if any(not entry.is_file(follow_symlinks=False) for entry in matched):
        raise FallbackPreparationError("compose_declaration_invalid")
    return bool(matched)


def _admissible_with_memory_multiplier(entry: split.ManifestEntry, memory_multiplier: float) -> bool:
    for request in split._phase_requests(entry):
        if (
            request.gpu_count != 0
            or request.cpu_count > split.LEGACY_CPU_COUNT
            or math.ceil(request.memory_bytes * memory_multiplier) + split.MIN_MEMORY_HEADROOM_BYTES
            > split.LEGACY_OUTER_MEMORY_BYTES
            or request.disk_bytes + split.DISK_HEADROOM_BYTES > split.LEGACY_DISK_AVAILABLE_BYTES
        ):
            return False
    return True


def derive_fallback_partition(
    entries: tuple[split.ManifestEntry, ...],
    dataset_dir: Path,
) -> FallbackPartition:
    if len(entries) != split.TOTAL_TASKS:
        raise FallbackPreparationError("fallback_source_invalid")
    low: list[str] = []
    memory_8g: list[str] = []
    memory_16g: list[str] = []
    compose: list[str] = []
    gpu: list[str] = []
    for entry in entries:
        task_dir = dataset_dir / entry.task_id
        has_compose = _has_compose(task_dir)
        declared_compose = getattr(entry, "requires_compose", None)
        if not isinstance(declared_compose, bool) or declared_compose is not has_compose:
            raise FallbackPreparationError("compose_declaration_mismatch")
        gpu_count = max(request.gpu_count for request in split._phase_requests(entry))
        if has_compose and gpu_count:
            raise FallbackPreparationError("compose_gpu_overlap")
        if gpu_count:
            gpu.append(entry.task_id)
        elif has_compose:
            compose.append(entry.task_id)
        elif split._legacy_admissible(entry):
            low.append(entry.task_id)
        else:
            requests = split._phase_requests(entry)
            if any(
                request.cpu_count > split.LEGACY_CPU_COUNT
                or request.disk_bytes + split.DISK_HEADROOM_BYTES > split.LEGACY_DISK_AVAILABLE_BYTES
                for request in requests
            ):
                raise FallbackPreparationError("fallback_nonmemory_resource_unsupported")
            maximum_memory = max(request.memory_bytes for request in requests)
            if maximum_memory == 8 * split.GIB and _admissible_with_memory_multiplier(entry, MEMORY_8G_MULTIPLIER):
                memory_8g.append(entry.task_id)
            elif maximum_memory == 16 * split.GIB and _admissible_with_memory_multiplier(entry, MEMORY_16G_MULTIPLIER):
                memory_16g.append(entry.task_id)
            else:
                raise FallbackPreparationError("fallback_memory_class_unsupported")
    if (len(low), len(memory_8g), len(memory_16g), len(compose), len(gpu)) != (
        LOW_RESOURCE_TASKS,
        MEMORY_8G_TASKS,
        MEMORY_16G_TASKS,
        COMPOSE_EXCLUDED_TASKS,
        GPU_UNSUPPORTED_TASKS,
    ):
        raise FallbackPreparationError("fallback_partition_cardinality_mismatch")
    groups = tuple(map(set, (low, memory_8g, memory_16g, compose, gpu)))
    if any(groups[left] & groups[right] for left in range(5) for right in range(left + 1, 5)):
        raise FallbackPreparationError("fallback_partition_overlap")
    if set().union(*groups) != {entry.task_id for entry in entries}:
        raise FallbackPreparationError("fallback_partition_not_exhaustive")
    provider_partition = split.derive_partition(entries)
    if set(low) != set(provider_partition.legacy_sandoq) or set(memory_8g + memory_16g + compose) != set(
        provider_partition.large_provider
    ):
        raise FallbackPreparationError("fallback_provider_partition_mismatch")
    return FallbackPartition(tuple(low), tuple(memory_8g), tuple(memory_16g), tuple(compose), tuple(gpu))


def _partition_files(manifest_sha256: str, partition: FallbackPartition) -> dict[str, bytes]:
    selectors = {
        LOW_SELECTOR: _selector(partition.low_resource),
        MEMORY_8G_SELECTOR: _selector(partition.memory_8g),
        MEMORY_16G_SELECTOR: _selector(partition.memory_16g),
        COMPOSE_SELECTOR: _selector(partition.compose_excluded),
        GPU_SELECTOR: _selector(partition.gpu_unsupported),
    }
    receipt = {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "kind": PARTITION_KIND,
        "state": "materialized",
        "manifest_sha256": manifest_sha256,
        "counts": {
            "total": split.TOTAL_TASKS,
            "low_resource_noncompose": LOW_RESOURCE_TASKS,
            "high_resource_noncompose_fallback": FALLBACK_TASKS,
            "fallback_memory_8g": MEMORY_8G_TASKS,
            "fallback_memory_16g": MEMORY_16G_TASKS,
            "compose_excluded": COMPOSE_EXCLUDED_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
        },
        "selectors": {
            name: {"bytes": len(payload), "sha256": split.sha256_bytes(payload)}
            for name, payload in sorted(selectors.items())
        },
        "policy": {
            "fallback_provider": "sandoq",
            "outer_memory_bytes": split.LEGACY_OUTER_MEMORY_BYTES,
            "memory_headroom_bytes": split.MIN_MEMORY_HEADROOM_BYTES,
            "fallback_lanes": {
                "memory_8g": {
                    "resource_multiplier": RESOURCE_MULTIPLIER,
                    "memory_resource_multiplier": MEMORY_8G_MULTIPLIER,
                    "concurrency": MEMORY_8G_CONCURRENCY,
                },
                "memory_16g": {
                    "resource_multiplier": RESOURCE_MULTIPLIER,
                    "memory_resource_multiplier": MEMORY_16G_MULTIPLIER,
                    "concurrency": MEMORY_16G_CONCURRENCY,
                },
            },
            "resource_fidelity": False,
            "compose_execution": "excluded",
            "gpu_execution": "unsupported",
            "certification_eligible": False,
            "trace_rollout_eligible": False,
        },
    }
    return {**selectors, PARTITION_RECEIPT: split.canonical_json(receipt)}


def _fallback_config(
    base: dict[str, Any],
    *,
    count: int,
    concurrency: int,
    memory_multiplier: float,
    selector: Path,
    selector_sha256: str,
    image_manifest: Path,
    dataset_dir: Path,
) -> dict[str, Any]:
    value = common._lane_config(
        base,
        role="legacy_sandoq",
        selector=selector,
        selector_sha256=selector_sha256,
        image_manifest=image_manifest,
        dataset_dir=dataset_dir,
        concurrency=concurrency,
    )
    value["num_tasks"] = count
    value["taskset"]["resource_multiplier"] = RESOURCE_MULTIPLIER
    value["taskset"]["memory_resource_multiplier"] = memory_multiplier
    value["taskset"]["enable_compose"] = False
    value["client"]["max_retries"] = 0
    value["retries"]["rollout"]["max_retries"] = 0
    return value


def _artifact(path: Path, payload: bytes) -> dict[str, object]:
    return common._artifact(path, payload)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if common.RUN_LABEL_RE.fullmatch(args.run_label or "") is None:
        raise FallbackPreparationError("run_label_invalid")
    parent = args.private_parent.resolve(strict=True)
    metadata = parent.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise FallbackPreparationError("private_parent_invalid")
    manifest_payload, _old_partition = common.build_resource_manifest(
        task_file=args.task_file,
        dataset_dir=args.dataset_dir,
        dataset_archive=args.dataset_archive,
        image_manifest=args.image_manifest,
    )
    manifest_sha256 = split.sha256_bytes(manifest_payload)
    manifest, entries = split.parse_manifest(manifest_payload, manifest_sha256)
    if manifest.get("schema_version") != split.MANIFEST_SCHEMA_VERSION:
        raise FallbackPreparationError("fallback_requires_resource_manifest_v2")
    dataset_dir = args.dataset_dir.resolve(strict=True)
    partition = derive_fallback_partition(entries, dataset_dir)
    resource_dir = parent / f"{args.run_label}-resource"
    partition_dir = parent / f"{args.run_label}-partition"
    launch_dir = parent / f"{args.run_label}-launch"
    if any(path.exists() or path.is_symlink() for path in (resource_dir, partition_dir, launch_dir)):
        raise FallbackPreparationError("output_already_exists")
    image_payload = common._read(args.image_manifest, code="image_manifest_invalid")
    common._require_digest(
        image_payload,
        split.CANONICAL_IMAGE_MANIFEST_SHA256,
        code="image_manifest_digest_mismatch",
    )
    split._publish_private_bundle(
        resource_dir,
        {RESOURCE_MANIFEST: manifest_payload, PINNED_IMAGE_MANIFEST: image_payload},
    )
    partition_files = _partition_files(manifest_sha256, partition)
    split._publish_private_bundle(partition_dir, partition_files)

    base_payload = common._read(args.base_config, code="base_config_invalid", maximum_bytes=2 * 1024 * 1024)
    base = common._base_config(base_payload, args.base_config_sha256)
    image_path = resource_dir / PINNED_IMAGE_MANIFEST
    eval_root = args.eval_root.resolve(strict=True)
    launch_files: dict[str, bytes] = {BASE_CONFIG: base_payload}
    lane_values: dict[str, dict[str, object]] = {}
    members_by_lane = {
        "memory_8g": partition.memory_8g,
        "memory_16g": partition.memory_16g,
    }
    outputs: set[Path] = set()
    for lane_name, contract in LANES.items():
        selector_path = partition_dir / str(contract["selector"])
        selector_payload = _selector(members_by_lane[lane_name])
        config_value = _fallback_config(
            base,
            count=int(contract["count"]),
            concurrency=int(contract["concurrency"]),
            memory_multiplier=float(contract["memory_multiplier"]),
            selector=selector_path,
            selector_sha256=split.sha256_bytes(selector_payload),
            image_manifest=image_path,
            dataset_dir=dataset_dir,
        )
        config_payload = common._render_toml(config_value)
        config_name = str(contract["config"])
        launch_files[config_name] = config_payload
        output_dir = eval_root / (f"tb4-kimi-k3-{SERVER_SLUG}-{args.run_label}-{contract['stage']}-diagnostic")
        if output_dir in outputs or output_dir.exists() or output_dir.is_symlink():
            raise FallbackPreparationError("eval_output_not_fresh")
        outputs.add(output_dir)
        lane_values[lane_name] = {
            "stage": contract["stage"],
            "provider": "sandoq",
            "count": contract["count"],
            "concurrency": contract["concurrency"],
            "resource_multiplier": RESOURCE_MULTIPLIER,
            "memory_resource_multiplier": contract["memory_multiplier"],
            "resource_fidelity": False,
            "selector": _artifact(selector_path, selector_payload),
            "config": _artifact(launch_dir / config_name, config_payload),
            "output_dir": str(output_dir),
            "execution_mode": "sandoq-fallback-diagnostic",
        }
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "kind": KIND,
        "state": "materialized",
        "server_id": SERVER_ID,
        "evaluation": {
            "label": "diagnostic-high-resource-noncompose-fallback",
            "denominator": split.TOTAL_TASKS,
            "pass_at_1": True,
            "preflight_allowed": False,
            "smoke_checkpoint_required": False,
            "certification_eligible": False,
            "trace_rollout_eligible": False,
            "resource_fidelity": False,
        },
        "source": {
            "resource_manifest": _artifact(resource_dir / RESOURCE_MANIFEST, manifest_payload),
            "image_manifest": _artifact(image_path, image_payload),
            "partition_receipt": _artifact(partition_dir / PARTITION_RECEIPT, partition_files[PARTITION_RECEIPT]),
            "base_config": _artifact(launch_dir / BASE_CONFIG, base_payload),
        },
        "accounting": {
            "low_resource_noncompose": LOW_RESOURCE_TASKS,
            "high_resource_noncompose_fallback": FALLBACK_TASKS,
            "fallback_memory_8g": MEMORY_8G_TASKS,
            "fallback_memory_16g": MEMORY_16G_TASKS,
            "compose_excluded": COMPOSE_EXCLUDED_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "disjoint": True,
            "exhaustive": True,
        },
        "lanes": lane_values,
    }
    plan_payload = split.canonical_json(plan)
    launch_files[PLAN] = plan_payload
    split._publish_private_bundle(launch_dir, launch_files)
    return {
        "state": "materialized",
        "total": split.TOTAL_TASKS,
        "fallback": FALLBACK_TASKS,
        "compose_excluded": COMPOSE_EXCLUDED_TASKS,
        "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
        "fallback_memory_8g": MEMORY_8G_TASKS,
        "fallback_memory_16g": MEMORY_16G_TASKS,
        "concurrency": TOTAL_CONCURRENCY,
        "resource_fidelity": False,
        "certification_eligible": False,
        "trace_rollout_eligible": False,
    }


def _read_artifact(record: object, *, code: str, private: bool = True) -> tuple[Path, bytes]:
    try:
        return common._verified_artifact(record, code=code, private=private)
    except common.PreparationError as error:
        raise FallbackPreparationError(code) from error


def _verify_bundle(directory: Path, files: dict[str, bytes], *, code: str) -> None:
    try:
        common._verify_committed_bundle(directory, files, code=code)
    except common.PreparationError as error:
        raise FallbackPreparationError(code) from error


def verify(plan_path: Path, expected_sha256: str, lane_name: str) -> dict[str, str]:
    if lane_name not in LANES:
        raise FallbackPreparationError("fallback_lane_invalid")
    try:
        plan_payload = split.read_regular(plan_path, code="fallback_plan_invalid", private=True)
    except split.KimiProviderSplitError as error:
        raise FallbackPreparationError("fallback_plan_invalid") from error
    common._require_digest(plan_payload, expected_sha256, code="fallback_plan_digest_mismatch")
    if plan_path.name != PLAN:
        raise FallbackPreparationError("fallback_plan_invalid")
    launch_dir = plan_path.parent
    config_payloads = {
        str(contract["config"]): split.read_regular(
            launch_dir / str(contract["config"]), code="fallback_bundle_invalid", private=True
        )
        for contract in LANES.values()
    }
    base_payload = split.read_regular(launch_dir / BASE_CONFIG, code="fallback_bundle_invalid", private=True)
    _verify_bundle(
        launch_dir,
        {**config_payloads, BASE_CONFIG: base_payload, PLAN: plan_payload},
        code="fallback_bundle_invalid",
    )
    try:
        plan = json.loads(plan_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FallbackPreparationError("fallback_plan_invalid") from error
    evaluation = plan.get("evaluation")
    accounting = plan.get("accounting")
    lanes = plan.get("lanes")
    source = plan.get("source")
    if (
        split.canonical_json(plan) != plan_payload
        or set(plan) != {"schema_version", "kind", "state", "server_id", "evaluation", "source", "accounting", "lanes"}
        or plan.get("schema_version") != PLAN_SCHEMA_VERSION
        or plan.get("kind") != KIND
        or plan.get("state") != "materialized"
        or plan.get("server_id") != SERVER_ID
        or evaluation
        != {
            "label": "diagnostic-high-resource-noncompose-fallback",
            "denominator": split.TOTAL_TASKS,
            "pass_at_1": True,
            "preflight_allowed": False,
            "smoke_checkpoint_required": False,
            "certification_eligible": False,
            "trace_rollout_eligible": False,
            "resource_fidelity": False,
        }
        or accounting
        != {
            "low_resource_noncompose": LOW_RESOURCE_TASKS,
            "high_resource_noncompose_fallback": FALLBACK_TASKS,
            "fallback_memory_8g": MEMORY_8G_TASKS,
            "fallback_memory_16g": MEMORY_16G_TASKS,
            "compose_excluded": COMPOSE_EXCLUDED_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "disjoint": True,
            "exhaustive": True,
        }
        or not isinstance(source, dict)
        or set(source) != {"resource_manifest", "image_manifest", "partition_receipt", "base_config"}
        or not isinstance(lanes, dict)
        or set(lanes) != set(LANES)
    ):
        raise FallbackPreparationError("fallback_plan_contract_mismatch")
    manifest_path, manifest_payload = _read_artifact(source["resource_manifest"], code="resource_manifest_invalid")
    image_path, image_payload = _read_artifact(source["image_manifest"], code="image_manifest_invalid")
    if (
        manifest_path.name != RESOURCE_MANIFEST
        or image_path.parent != manifest_path.parent
        or image_path.name != PINNED_IMAGE_MANIFEST
        or split.sha256_bytes(image_payload) != split.CANONICAL_IMAGE_MANIFEST_SHA256
    ):
        raise FallbackPreparationError("resource_bundle_invalid")
    _verify_bundle(
        manifest_path.parent,
        {RESOURCE_MANIFEST: manifest_payload, PINNED_IMAGE_MANIFEST: image_payload},
        code="resource_bundle_invalid",
    )
    manifest_sha256 = split.sha256_bytes(manifest_payload)
    manifest, entries = split.parse_manifest(manifest_payload, manifest_sha256)
    if manifest.get("schema_version") != split.MANIFEST_SCHEMA_VERSION:
        raise FallbackPreparationError("fallback_requires_resource_manifest_v2")
    parsed_configs: dict[str, dict[str, Any]] = {}
    dataset_paths: set[Path] = set()
    for name, payload in config_payloads.items():
        try:
            config = tomllib.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise FallbackPreparationError("fallback_config_invalid") from error
        parsed_configs[name] = config
        dataset_value = config.get("taskset", {}).get("dataset_dir", "")
        dataset_path = Path(str(dataset_value))
        if not dataset_path.is_absolute():
            raise FallbackPreparationError("fallback_dataset_invalid")
        dataset_paths.add(dataset_path)
    if len(dataset_paths) != 1:
        raise FallbackPreparationError("fallback_dataset_invalid")
    dataset_path = next(iter(dataset_paths))
    if common._tree_digest(dataset_path) != split.CANONICAL_DATASET_CONTENT_SHA256:
        raise FallbackPreparationError("fallback_dataset_invalid")
    partition = derive_fallback_partition(entries, dataset_path)
    if common._tree_digest(dataset_path) != split.CANONICAL_DATASET_CONTENT_SHA256:
        raise FallbackPreparationError("fallback_dataset_changed")
    receipt_path, receipt_payload = _read_artifact(source["partition_receipt"], code="partition_receipt_invalid")
    partition_files = _partition_files(manifest_sha256, partition)
    if receipt_path.name != PARTITION_RECEIPT or receipt_payload != partition_files[PARTITION_RECEIPT]:
        raise FallbackPreparationError("partition_receipt_invalid")
    _verify_bundle(receipt_path.parent, partition_files, code="fallback_partition_invalid")
    base_path, observed_base = _read_artifact(source["base_config"], code="base_config_invalid")
    base = common._base_config(observed_base, common.APPROVED_BASE_CONFIG_SHA256)
    if base_path != launch_dir / BASE_CONFIG or observed_base != base_payload:
        raise FallbackPreparationError("base_config_invalid")
    members_by_lane = {
        "memory_8g": partition.memory_8g,
        "memory_16g": partition.memory_16g,
    }
    verified: dict[str, dict[str, str]] = {}
    seen_outputs: set[Path] = set()
    for name, contract in LANES.items():
        lane = lanes.get(name)
        if not isinstance(lane, dict):
            raise FallbackPreparationError("fallback_lane_invalid")
        selector_path, selector_payload = _read_artifact(lane.get("selector"), code="fallback_selector_invalid")
        config_path, observed_config = _read_artifact(lane.get("config"), code="fallback_config_invalid")
        output_value = lane.get("output_dir")
        expected_lane = {
            "stage": contract["stage"],
            "provider": "sandoq",
            "count": contract["count"],
            "concurrency": contract["concurrency"],
            "resource_multiplier": RESOURCE_MULTIPLIER,
            "memory_resource_multiplier": contract["memory_multiplier"],
            "resource_fidelity": False,
            "selector": lane.get("selector"),
            "config": lane.get("config"),
            "output_dir": output_value,
            "execution_mode": "sandoq-fallback-diagnostic",
        }
        expected_selector = _selector(members_by_lane[name])
        config_name = str(contract["config"])
        output_path = Path(str(output_value))
        if (
            lane != expected_lane
            or selector_path != receipt_path.parent / str(contract["selector"])
            or selector_payload != expected_selector
            or config_path != launch_dir / config_name
            or observed_config != config_payloads[config_name]
            or not isinstance(output_value, str)
            or not output_path.is_absolute()
            or output_path in seen_outputs
            or (name == lane_name and (output_path.exists() or output_path.is_symlink()))
        ):
            raise FallbackPreparationError("fallback_lane_invalid")
        seen_outputs.add(output_path)
        expected_config = _fallback_config(
            base,
            count=int(contract["count"]),
            concurrency=int(contract["concurrency"]),
            memory_multiplier=float(contract["memory_multiplier"]),
            selector=selector_path,
            selector_sha256=split.sha256_bytes(selector_payload),
            image_manifest=image_path,
            dataset_dir=dataset_path,
        )
        if parsed_configs[config_name] != expected_config:
            raise FallbackPreparationError("fallback_config_contract_mismatch")
        verified[name] = {
            "stage": str(contract["stage"]),
            "provider": "sandoq",
            "config": str(config_path),
            "config_sha256": split.sha256_bytes(observed_config),
            "selector": str(selector_path),
            "selector_sha256": split.sha256_bytes(selector_payload),
            "count": str(contract["count"]),
            "concurrency": str(contract["concurrency"]),
            "output_dir": output_value,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_sha256,
            "partition_dir": str(receipt_path.parent),
        }
    return verified[lane_name]


def _prepare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--dataset-archive", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--base-config-sha256", required=True)
    parser.add_argument("--private-parent", type=Path, required=True)
    parser.add_argument("--eval-root", type=Path, required=True)
    parser.add_argument("--run-label", required=True)
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        parser = argparse.ArgumentParser(description="Verify the Sandoq fallback diagnostic")
        parser.add_argument("command")
        parser.add_argument("--launch-plan", type=Path, required=True)
        parser.add_argument("--launch-plan-sha256", required=True)
        parser.add_argument("--lane", choices=tuple(LANES), required=True)
        parser.add_argument("--format", choices=("json", "tsv"), default="json")
        args = parser.parse_args()
        try:
            result = verify(args.launch_plan, args.launch_plan_sha256, args.lane)
        except (FallbackPreparationError, common.PreparationError, split.KimiProviderSplitError) as error:
            parser.error(str(error))
        except Exception:
            parser.error("fallback_verification_failed")
        if args.format == "tsv":
            fields = (
                "stage",
                "provider",
                "config",
                "config_sha256",
                "selector",
                "selector_sha256",
                "count",
                "concurrency",
                "output_dir",
                "manifest",
                "manifest_sha256",
                "partition_dir",
            )
            if any("\t" in result[key] or "\n" in result[key] for key in fields):
                parser.error("fallback_launch_value_invalid")
            print("\t".join(result[key] for key in fields))
        else:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return
    parser = _prepare_parser()
    args = parser.parse_args()
    try:
        result = prepare(args)
    except (FallbackPreparationError, common.PreparationError, split.KimiProviderSplitError) as error:
        parser.error(str(error))
    except Exception:
        parser.error("fallback_preparation_failed")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
