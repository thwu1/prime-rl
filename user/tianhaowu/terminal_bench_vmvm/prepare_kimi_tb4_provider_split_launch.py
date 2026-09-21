#!/usr/bin/env python3
"""Build private Kimi TB4 resource, partition, and diagnostic launch inputs.

The command never writes task identifiers to stdout.  They exist only in the
mode-0600 private manifest and selectors needed by the evaluator.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any

import kimi_tb4_provider_split as split
from eval_run_identity import _archive_tasks_tree_digest, _tree_digest

KIND = "kimi-tb4-provider-split-diagnostic-launch"
MANIFEST_BUNDLE_SUFFIX = "-resource"
PARTITION_BUNDLE_SUFFIX = "-partition"
LAUNCH_BUNDLE_SUFFIX = "-launch"
RESOURCE_MANIFEST = "image-resource-manifest.json"
PINNED_IMAGE_MANIFEST = "tb4-images.sandoq.json"
LEGACY_CONFIG = "legacy-sandoq.diagnostic.toml"
LARGE_CONFIG = "large-vmvm.diagnostic.toml"
REVIEWED_BASE_CONFIG = "reviewed-base.toml"
LAUNCH_PLAN = "launch-plan.json"
DEFAULT_LEGACY_CONCURRENCY = 24
DEFAULT_LARGE_CONCURRENCY = 4
APPROVED_BASE_CONFIG_SHA256 = "80b969d5423400b1eedf65e617e49ad946935ed5cc78bf228adb41c8e39c2177"
RUN_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


class PreparationError(ValueError):
    """Aggregate-only preparation failure."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read(path: Path, *, code: str, maximum_bytes: int = 8 * 1024 * 1024) -> bytes:
    try:
        return split.read_regular(path, code=code, maximum_bytes=maximum_bytes)
    except split.KimiProviderSplitError as error:
        raise PreparationError(code) from error


def _require_digest(payload: bytes, expected: str, *, code: str) -> None:
    if split.SHA256_RE.fullmatch(expected or "") is None or _sha256(payload) != expected:
        raise PreparationError(code)


def _task_ids(payload: bytes) -> tuple[str, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PreparationError("task_file_invalid") from error
    identifiers = tuple(text.splitlines())
    if (
        len(identifiers) != split.TOTAL_TASKS
        or len(set(identifiers)) != split.TOTAL_TASKS
        or any(split.TASK_ID_RE.fullmatch(value) is None for value in identifiers)
        or payload != split._selector_payload(identifiers)
    ):
        raise PreparationError("task_file_invalid")
    return identifiers


def _json(payload: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreparationError(code) from error
    if not isinstance(value, dict) or split.canonical_json(value) != payload:
        raise PreparationError(code)
    return value


def _resource(value: object, *, allow_default_gpu: bool) -> dict[str, int]:
    if not isinstance(value, dict):
        raise PreparationError("task_resource_invalid")
    gpu = value.get("gpus", 0 if allow_default_gpu else None)
    fields = {
        "cpu_count": value.get("cpus"),
        "memory_bytes": value.get("memory_mb"),
        "disk_bytes": value.get("storage_mb"),
        "gpu_count": gpu,
    }
    if (
        any(isinstance(item, bool) or not isinstance(item, int) for item in fields.values())
        or fields["cpu_count"] <= 0
        or fields["memory_bytes"] <= 0
        or fields["disk_bytes"] <= 0
        or fields["gpu_count"] < 0
    ):
        raise PreparationError("task_resource_invalid")
    return {
        "cpu_count": fields["cpu_count"],
        "memory_bytes": fields["memory_bytes"] * 1024 * 1024,
        "disk_bytes": fields["disk_bytes"] * 1024 * 1024,
        "gpu_count": fields["gpu_count"],
    }


def _image_digest(value: object) -> str:
    if not isinstance(value, str) or split.IMAGE_RE.fullmatch(value) is None:
        raise PreparationError("task_image_invalid")
    return value.rsplit("@", 1)[1]


def _task_entry(
    task_id: str,
    task_toml: bytes,
    images: object,
) -> dict[str, Any]:
    try:
        value = tomllib.loads(task_toml.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PreparationError("task_config_invalid") from error
    if not isinstance(value, dict) or not isinstance(images, dict) or set(images) != {"agent", "verifier"}:
        raise PreparationError("task_config_invalid")
    environment = value.get("environment")
    verifier = value.get("verifier")
    if not isinstance(environment, dict) or not isinstance(verifier, dict):
        raise PreparationError("task_config_invalid")
    mode = verifier.get("environment_mode", "shared")
    if mode not in {"shared", "separate"}:
        raise PreparationError("verifier_mode_invalid")
    verifier_environment = verifier.get("environment") if mode == "separate" else environment
    if not isinstance(verifier_environment, dict):
        raise PreparationError("verifier_resource_invalid")
    agent_image = environment.get("docker_image")
    verifier_image = verifier_environment.get("docker_image")
    if (
        _image_digest(agent_image) != _image_digest(images.get("agent"))
        or _image_digest(verifier_image) != _image_digest(images.get("verifier"))
    ):
        raise PreparationError("task_image_binding_mismatch")
    return {
        "task_id": task_id,
        "images": {"agent": images["agent"], "verifier": images["verifier"]},
        "agent_resources": _resource(environment, allow_default_gpu=True),
        "verifier_resources": _resource(verifier_environment, allow_default_gpu=True),
        "verifier_mode": mode,
    }


def build_resource_manifest(
    *,
    task_file: Path,
    dataset_dir: Path,
    dataset_archive: Path,
    image_manifest: Path,
) -> tuple[bytes, split.Partition]:
    selection_payload = _read(task_file, code="task_file_invalid", maximum_bytes=1 << 20)
    _require_digest(selection_payload, split.CANONICAL_TASK_FILE_SHA256, code="task_file_digest_mismatch")
    identifiers = _task_ids(selection_payload)

    image_payload = _read(image_manifest, code="image_manifest_invalid")
    _require_digest(image_payload, split.CANONICAL_IMAGE_MANIFEST_SHA256, code="image_manifest_digest_mismatch")
    image_value = _json(image_payload, code="image_manifest_invalid")
    images = image_value.get("images")
    if (
        set(image_value) != {"schema_version", "source", "images"}
        or image_value.get("schema_version") != 1
        or not isinstance(images, dict)
        or set(images) != set(identifiers)
    ):
        raise PreparationError("image_manifest_invalid")

    try:
        root = dataset_dir.resolve(strict=True)
        if not root.is_dir() or _tree_digest(root) != split.CANONICAL_DATASET_CONTENT_SHA256:
            raise PreparationError("dataset_content_digest_mismatch")
        archive = dataset_archive.resolve(strict=True)
        archive_payload_hash = hashlib.sha256()
        with archive.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                archive_payload_hash.update(chunk)
        if archive_payload_hash.hexdigest() != split.CANONICAL_DATASET_ARCHIVE_SHA256:
            raise PreparationError("dataset_archive_digest_mismatch")
        if _archive_tasks_tree_digest(archive) != split.CANONICAL_DATASET_CONTENT_SHA256:
            raise PreparationError("dataset_archive_content_mismatch")
    except PreparationError:
        raise
    except Exception as error:
        raise PreparationError("dataset_authority_invalid") from error

    entries: list[dict[str, Any]] = []
    for task_id in identifiers:
        task_path = root / task_id / "task.toml"
        task_payload = _read(task_path, code="task_config_invalid", maximum_bytes=1 << 20)
        entries.append(_task_entry(task_id, task_payload, images[task_id]))
    if (
        _tree_digest(root) != split.CANONICAL_DATASET_CONTENT_SHA256
        or _read(task_file, code="task_file_invalid", maximum_bytes=1 << 20) != selection_payload
    ):
        raise PreparationError("dataset_authority_changed")
    if _read(image_manifest, code="image_manifest_invalid") != image_payload:
        raise PreparationError("image_manifest_changed")
    value = {
        "schema_version": 1,
        "kind": split.MANIFEST_KIND,
        "source": {
            "dataset_archive_sha256": split.CANONICAL_DATASET_ARCHIVE_SHA256,
            "dataset_content_sha256": split.CANONICAL_DATASET_CONTENT_SHA256,
            "image_manifest_sha256": split.CANONICAL_IMAGE_MANIFEST_SHA256,
            "task_file_sha256": split.CANONICAL_TASK_FILE_SHA256,
        },
        "entries": entries,
    }
    payload = split.canonical_json(value)
    _parsed, parsed_entries = split.parse_manifest(payload, _sha256(payload))
    partition = split.derive_partition(parsed_entries)
    return payload, partition


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _quoted(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not value == value or value in {float("inf"), float("-inf")}:
            raise PreparationError("base_config_invalid")
        return repr(value)
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise PreparationError("base_config_invalid")


def _render_toml(value: dict[str, Any]) -> bytes:
    lines = ["# Generated diagnostic input. Not trace-rollout eligible until capture qualification."]

    def emit(table: dict[str, Any], prefix: tuple[str, ...]) -> None:
        if prefix:
            lines.extend(("", "[" + ".".join(prefix) + "]"))
        for key, item in table.items():
            if not isinstance(item, dict):
                lines.append(f"{key} = {_toml_value(item)}")
        for key, item in table.items():
            if isinstance(item, dict):
                emit(item, (*prefix, key))

    emit(value, ())
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    try:
        if tomllib.loads(payload.decode("utf-8")) != value:
            raise PreparationError("generated_config_invalid")
    except tomllib.TOMLDecodeError as error:
        raise PreparationError("generated_config_invalid") from error
    return payload


def _base_config(payload: bytes, expected_sha256: str) -> dict[str, Any]:
    if expected_sha256 != APPROVED_BASE_CONFIG_SHA256:
        raise PreparationError("base_config_not_approved")
    _require_digest(payload, expected_sha256, code="base_config_digest_mismatch")
    try:
        value = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PreparationError("base_config_invalid") from error
    client = value.get("client") if isinstance(value, dict) else None
    sampling = value.get("sampling") if isinstance(value, dict) else None
    taskset = value.get("taskset") if isinstance(value, dict) else None
    harness = value.get("harness") if isinstance(value, dict) else None
    retry = value.get("retries", {}).get("rollout") if isinstance(value, dict) else None
    expected_context = (split.MAX_SEQUENCE_TOKENS,) * 3
    observed_context = tuple(value.get(key) for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
    if (
        value.get("model") != "Kimi-K3"
        or value.get("num_tasks") != split.TOTAL_TASKS
        or value.get("num_rollouts") != 1
        or value.get("retain_traces") is not False
        or observed_context != expected_context
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or sorted(client.get("outbound_body_denylist", [])) != split.EXPECTED_DENYLIST
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != split.SAMPLING_MAX_TOKENS
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, dict)
        or taskset.get("task_file_sha256") != split.CANONICAL_TASK_FILE_SHA256
        or taskset.get("image_manifest_sha256") != split.CANONICAL_IMAGE_MANIFEST_SHA256
        or taskset.get("use_declared_images") is not True
        or taskset.get("verifier_runtime_retries") != 0
        or not isinstance(harness, dict)
        or harness.get("id") != "terminal-bench-sandoq-host"
        or not isinstance(harness.get("runtime"), dict)
        or harness["runtime"].get("type") != "sandoq"
        or not isinstance(retry, dict)
        or retry.get("max_retries") != 0
    ):
        raise PreparationError("base_config_contract_mismatch")
    return value


def _lane_config(
    base: dict[str, Any],
    *,
    role: str,
    selector: Path,
    selector_sha256: str,
    image_manifest: Path,
    dataset_dir: Path,
    concurrency: int,
) -> dict[str, Any]:
    value = copy.deepcopy(base)
    is_legacy = role == "legacy_sandoq"
    value["num_tasks"] = split.LEGACY_SANDOQ_TASKS if is_legacy else split.LARGE_PROVIDER_TASKS
    value["max_concurrent"] = concurrency
    value["multiplex"] = concurrency
    value["client"]["max_connections"] = concurrency
    value["client"]["max_keepalive_connections"] = concurrency
    value["client"]["max_retries"] = 0
    value["taskset"]["dataset_dir"] = str(dataset_dir)
    value["taskset"]["task_file"] = str(selector)
    value["taskset"]["task_file_sha256"] = selector_sha256
    value["taskset"]["image_manifest"] = str(image_manifest)
    value["taskset"]["image_manifest_sha256"] = split.CANONICAL_IMAGE_MANIFEST_SHA256
    value["taskset"]["resource_multiplier"] = 1.0 if is_legacy else 2.0
    value["taskset"]["verifier_runtime_retries"] = 0
    value["retries"]["rollout"]["max_retries"] = 0
    if not is_legacy:
        value["harness"]["runtime"] = {
            "type": "vmvm",
            "session_timeout": 43200,
            "tenant_id": "async_2347641",
            "lease_ttl": "60s",
            "max_session_buffer_size": 67108864,
        }
    return value


def _artifact(path: Path, payload: bytes) -> dict[str, object]:
    return {"path": str(path), "bytes": len(payload), "sha256": _sha256(payload)}


def _verified_artifact(record: object, *, code: str, private: bool) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise PreparationError(code)
    path_value = record.get("path")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise PreparationError(code)
    path = Path(path_value)
    try:
        payload = split.read_regular(path, code=code, maximum_bytes=8 * 1024 * 1024, private=private)
    except split.KimiProviderSplitError as error:
        raise PreparationError(code) from error
    if record.get("bytes") != len(payload) or record.get("sha256") != _sha256(payload):
        raise PreparationError(code)
    return path, payload


def _verify_committed_bundle(directory: Path, files: dict[str, bytes], *, code: str) -> None:
    try:
        root, descriptor, _identity = split._open_private_parent(directory)
    except split.KimiProviderSplitError as error:
        raise PreparationError(code) from error
    else:
        os.close(descriptor)
    expected = split._committed_bundle_files(files)
    try:
        observed_names = {entry.name for entry in os.scandir(root)}
    except OSError as error:
        raise PreparationError(code) from error
    if observed_names != set(expected):
        raise PreparationError(code)
    for name, payload in expected.items():
        try:
            observed = split.read_regular(root / name, code=code, private=True)
        except split.KimiProviderSplitError as error:
            raise PreparationError(code) from error
        if observed != payload:
            raise PreparationError(code)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_LABEL_RE.fullmatch(args.run_label or "") is None:
        raise PreparationError("run_label_invalid")
    if not (1 <= args.legacy_concurrency <= 24 and 1 <= args.large_concurrency <= 4):
        raise PreparationError("concurrency_invalid")
    parent = args.private_parent.resolve(strict=True)
    parent_stat = parent.stat()
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
    ):
        raise PreparationError("private_parent_invalid")

    manifest_payload, partition = build_resource_manifest(
        task_file=args.task_file,
        dataset_dir=args.dataset_dir,
        dataset_archive=args.dataset_archive,
        image_manifest=args.image_manifest,
    )
    manifest_digest = _sha256(manifest_payload)
    resource_dir = parent / f"{args.run_label}{MANIFEST_BUNDLE_SUFFIX}"
    partition_dir = parent / f"{args.run_label}{PARTITION_BUNDLE_SUFFIX}"
    launch_dir = parent / f"{args.run_label}{LAUNCH_BUNDLE_SUFFIX}"
    if any(path.exists() or path.is_symlink() for path in (resource_dir, partition_dir, launch_dir)):
        raise PreparationError("output_already_exists")
    source_image_payload = _read(args.image_manifest, code="image_manifest_invalid")
    _require_digest(
        source_image_payload,
        split.CANONICAL_IMAGE_MANIFEST_SHA256,
        code="image_manifest_digest_mismatch",
    )
    split._publish_private_bundle(
        resource_dir,
        {
            RESOURCE_MANIFEST: manifest_payload,
            PINNED_IMAGE_MANIFEST: source_image_payload,
        },
    )
    manifest_path = resource_dir / RESOURCE_MANIFEST
    pinned_image_manifest = resource_dir / PINNED_IMAGE_MANIFEST
    split.materialize_partition(manifest_path, manifest_digest, partition_dir)

    base_payload = _read(args.base_config, code="base_config_invalid", maximum_bytes=2 * 1024 * 1024)
    base = _base_config(base_payload, args.base_config_sha256)
    legacy_selector = partition_dir / split.LEGACY_SELECTOR
    large_selector = partition_dir / split.LARGE_SELECTOR
    legacy_selector_payload = split._selector_payload(partition.legacy_sandoq)
    large_selector_payload = split._selector_payload(partition.large_provider)
    legacy_value = _lane_config(
        base,
        role="legacy_sandoq",
        selector=legacy_selector,
        selector_sha256=_sha256(legacy_selector_payload),
        image_manifest=pinned_image_manifest,
        dataset_dir=args.dataset_dir.resolve(strict=True),
        concurrency=args.legacy_concurrency,
    )
    large_value = _lane_config(
        base,
        role="large_provider",
        selector=large_selector,
        selector_sha256=_sha256(large_selector_payload),
        image_manifest=pinned_image_manifest,
        dataset_dir=args.dataset_dir.resolve(strict=True),
        concurrency=args.large_concurrency,
    )
    if split._provider_neutral_config(legacy_value) != split._provider_neutral_config(large_value):
        raise PreparationError("lane_contract_mismatch")
    legacy_payload = _render_toml(legacy_value)
    large_payload = _render_toml(large_value)
    eval_root = args.eval_root.resolve(strict=True)
    legacy_output = eval_root / f"tb4-kimi-k3-{args.run_label}-diagnostic-legacy-sandoq"
    large_output = eval_root / f"tb4-kimi-k3-{args.run_label}-diagnostic-large-vmvm"
    if legacy_output == large_output or any(path.exists() or path.is_symlink() for path in (legacy_output, large_output)):
        raise PreparationError("eval_output_not_fresh")
    plan = {
        "schema_version": 1,
        "kind": KIND,
        "state": "materialized",
        "evaluation": {
            "label": "diagnostic-full-denominator",
            "denominator": split.TOTAL_TASKS,
            "pass_at_1": True,
            "smoke_checkpoint_required": False,
            "preflight_allowed": False,
            "certification_eligible": False,
            "trace_rollout_eligible": False,
            "promotion_gate": "post-run-captured-reasoning-and-model-io-audit",
        },
        "source": {
            "resource_manifest": _artifact(manifest_path, manifest_payload),
            "image_manifest": _artifact(pinned_image_manifest, source_image_payload),
            "partition_receipt": _artifact(
                partition_dir / split.PARTITION_RECEIPT,
                split.canonical_json(split._partition_receipt_value(manifest_digest, partition)),
            ),
            "base_config": _artifact(launch_dir / REVIEWED_BASE_CONFIG, base_payload),
        },
        "lanes": {
            "legacy_sandoq": {
                "provider": "sandoq",
                "count": split.LEGACY_SANDOQ_TASKS,
                "concurrency": args.legacy_concurrency,
                "selector": _artifact(legacy_selector, legacy_selector_payload),
                "config": _artifact(launch_dir / LEGACY_CONFIG, legacy_payload),
                "output_dir": str(legacy_output),
                "execution_mode": "diagnostic",
            },
            "large_provider": {
                "provider": "vmvm",
                "count": split.LARGE_PROVIDER_TASKS,
                "concurrency": args.large_concurrency,
                "selector": _artifact(large_selector, large_selector_payload),
                "config": _artifact(launch_dir / LARGE_CONFIG, large_payload),
                "output_dir": str(large_output),
                "execution_mode": "diagnostic",
            },
            "gpu_unsupported": {
                "provider": "unsupported",
                "count": split.GPU_UNSUPPORTED_TASKS,
                "selector_sha256": _sha256(split._selector_payload(partition.gpu_unsupported)),
            },
        },
    }
    plan_payload = split.canonical_json(plan)
    split._publish_private_bundle(
        launch_dir,
        {
            LEGACY_CONFIG: legacy_payload,
            LARGE_CONFIG: large_payload,
            REVIEWED_BASE_CONFIG: base_payload,
            LAUNCH_PLAN: plan_payload,
        },
    )
    return {
        "state": "materialized",
        "manifest_sha256": manifest_digest,
        "total": split.TOTAL_TASKS,
        "legacy_sandoq": split.LEGACY_SANDOQ_TASKS,
        "large_provider": split.LARGE_PROVIDER_TASKS,
        "gpu_unsupported": split.GPU_UNSUPPORTED_TASKS,
        "diagnostic": True,
        "certification_eligible": False,
        "trace_rollout_eligible": False,
    }


def verify_launch_plan(plan_path: Path, expected_sha256: str, role: str) -> dict[str, str]:
    try:
        plan_payload = split.read_regular(
            plan_path,
            code="launch_plan_invalid",
            maximum_bytes=2 * 1024 * 1024,
            private=True,
        )
    except split.KimiProviderSplitError as error:
        raise PreparationError("launch_plan_invalid") from error
    _require_digest(plan_payload, expected_sha256, code="launch_plan_digest_mismatch")
    launch_dir = plan_path.parent
    if plan_path.name != LAUNCH_PLAN:
        raise PreparationError("launch_plan_invalid")
    try:
        local_legacy = split.read_regular(launch_dir / LEGACY_CONFIG, code="launch_bundle_invalid", private=True)
        local_large = split.read_regular(launch_dir / LARGE_CONFIG, code="launch_bundle_invalid", private=True)
        local_base = split.read_regular(
            launch_dir / REVIEWED_BASE_CONFIG,
            code="launch_bundle_invalid",
            private=True,
        )
    except split.KimiProviderSplitError as error:
        raise PreparationError("launch_bundle_invalid") from error
    _verify_committed_bundle(
        launch_dir,
        {
            LEGACY_CONFIG: local_legacy,
            LARGE_CONFIG: local_large,
            REVIEWED_BASE_CONFIG: local_base,
            LAUNCH_PLAN: plan_payload,
        },
        code="launch_bundle_invalid",
    )
    plan = _json(plan_payload, code="launch_plan_invalid")
    evaluation = plan.get("evaluation")
    lanes = plan.get("lanes")
    source = plan.get("source")
    if (
        set(plan) != {"schema_version", "kind", "state", "evaluation", "source", "lanes"}
        or plan.get("schema_version") != 1
        or plan.get("kind") != KIND
        or plan.get("state") != "materialized"
        or not isinstance(evaluation, dict)
        or evaluation
        != {
            "label": "diagnostic-full-denominator",
            "denominator": split.TOTAL_TASKS,
            "pass_at_1": True,
            "smoke_checkpoint_required": False,
            "preflight_allowed": False,
            "certification_eligible": False,
            "trace_rollout_eligible": False,
            "promotion_gate": "post-run-captured-reasoning-and-model-io-audit",
        }
        or not isinstance(lanes, dict)
        or set(lanes) != {"legacy_sandoq", "large_provider", "gpu_unsupported"}
        or not isinstance(source, dict)
        or set(source) != {"resource_manifest", "image_manifest", "partition_receipt", "base_config"}
        or role not in {"legacy_sandoq", "large_provider"}
    ):
        raise PreparationError("launch_plan_contract_mismatch")
    manifest_path, manifest_payload = _verified_artifact(
        source["resource_manifest"], code="resource_manifest_invalid", private=True
    )
    if manifest_path.name != RESOURCE_MANIFEST:
        raise PreparationError("resource_manifest_invalid")
    image_manifest_path, image_manifest_payload = _verified_artifact(
        source["image_manifest"], code="image_manifest_invalid", private=True
    )
    if (
        image_manifest_path.parent != manifest_path.parent
        or image_manifest_path.name != PINNED_IMAGE_MANIFEST
        or _sha256(image_manifest_payload) != split.CANONICAL_IMAGE_MANIFEST_SHA256
    ):
        raise PreparationError("image_manifest_invalid")
    _verify_committed_bundle(
        manifest_path.parent,
        {
            RESOURCE_MANIFEST: manifest_payload,
            PINNED_IMAGE_MANIFEST: image_manifest_payload,
        },
        code="resource_bundle_invalid",
    )
    manifest_sha256 = _sha256(manifest_payload)
    receipt_path, _receipt_payload = _verified_artifact(
        source["partition_receipt"], code="partition_receipt_invalid", private=True
    )
    partition_dir = receipt_path.parent
    partition, _receipt = split._read_partition_bundle(partition_dir, manifest_path, manifest_sha256)
    base_path, base_payload = _verified_artifact(source["base_config"], code="base_config_invalid", private=True)
    base = _base_config(base_payload, APPROVED_BASE_CONFIG_SHA256)

    expected_lanes = {
        "legacy_sandoq": {
            "provider": "sandoq",
            "count": split.LEGACY_SANDOQ_TASKS,
            "concurrency": DEFAULT_LEGACY_CONCURRENCY,
            "members": partition.legacy_sandoq,
            "selector_name": split.LEGACY_SELECTOR,
            "config_name": LEGACY_CONFIG,
        },
        "large_provider": {
            "provider": "vmvm",
            "count": split.LARGE_PROVIDER_TASKS,
            "concurrency": DEFAULT_LARGE_CONCURRENCY,
            "members": partition.large_provider,
            "selector_name": split.LARGE_SELECTOR,
            "config_name": LARGE_CONFIG,
        },
    }
    configs: dict[str, dict[str, Any]] = {}
    for lane_role, expected in expected_lanes.items():
        lane = lanes.get(lane_role)
        if not isinstance(lane, dict) or set(lane) != {
            "provider",
            "count",
            "concurrency",
            "selector",
            "config",
            "output_dir",
            "execution_mode",
        }:
            raise PreparationError("launch_lane_invalid")
        selector_path, selector_payload = _verified_artifact(
            lane["selector"], code="launch_selector_invalid", private=True
        )
        config_path, config_payload = _verified_artifact(lane["config"], code="launch_config_invalid", private=True)
        output_value = lane.get("output_dir")
        if (
            lane.get("provider") != expected["provider"]
            or lane.get("count") != expected["count"]
            or lane.get("concurrency") != expected["concurrency"]
            or lane.get("execution_mode") != "diagnostic"
            or selector_path != partition_dir / expected["selector_name"]
            or selector_payload != split._selector_payload(expected["members"])
            or config_path.parent != plan_path.parent
            or config_path.name != expected["config_name"]
            or not isinstance(output_value, str)
            or not Path(output_value).is_absolute()
        ):
            raise PreparationError("launch_lane_invalid")
        try:
            config = tomllib.loads(config_payload.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise PreparationError("launch_config_invalid") from error
        expected_config = _lane_config(
            base,
            role=lane_role,
            selector=selector_path,
            selector_sha256=_sha256(selector_payload),
            image_manifest=image_manifest_path,
            dataset_dir=Path(config.get("taskset", {}).get("dataset_dir", "")),
            concurrency=expected["concurrency"],
        )
        if config != expected_config:
            raise PreparationError("launch_config_contract_mismatch")
        configs[lane_role] = config
    if split._provider_neutral_config(configs["legacy_sandoq"]) != split._provider_neutral_config(
        configs["large_provider"]
    ):
        raise PreparationError("lane_contract_mismatch")
    gpu_lane = lanes["gpu_unsupported"]
    if (
        not isinstance(gpu_lane, dict)
        or gpu_lane
        != {
            "provider": "unsupported",
            "count": split.GPU_UNSUPPORTED_TASKS,
            "selector_sha256": _sha256(split._selector_payload(partition.gpu_unsupported)),
        }
    ):
        raise PreparationError("gpu_lane_invalid")
    lane = lanes[role]
    return {
        "role": role,
        "stage": "provider-split-legacy" if role == "legacy_sandoq" else "provider-split-large",
        "provider": lane["provider"],
        "config": lane["config"]["path"],
        "selector": lane["selector"]["path"],
        "selector_sha256": lane["selector"]["sha256"],
        "output_dir": lane["output_dir"],
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "partition_dir": str(partition_dir),
        "base_config": str(base_path),
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        parser = argparse.ArgumentParser(description="Verify one diagnostic launch lane")
        parser.add_argument("command")
        parser.add_argument("--launch-plan", type=Path, required=True)
        parser.add_argument("--launch-plan-sha256", required=True)
        parser.add_argument("--role", choices=("legacy_sandoq", "large_provider"), required=True)
        parser.add_argument("--format", choices=("json", "tsv"), default="json")
        args = parser.parse_args()
        try:
            result = verify_launch_plan(args.launch_plan, args.launch_plan_sha256, args.role)
        except (PreparationError, split.KimiProviderSplitError) as error:
            parser.error(str(error))
        if args.format == "tsv":
            fields = (
                "stage",
                "provider",
                "config",
                "selector",
                "selector_sha256",
                "output_dir",
                "manifest",
                "manifest_sha256",
                "partition_dir",
            )
            if any("\t" in result[key] or "\n" in result[key] for key in fields):
                parser.error("launch_value_invalid")
            print("\t".join(result[key] for key in fields))
        else:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return
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
    parser.add_argument("--legacy-concurrency", type=int, default=DEFAULT_LEGACY_CONCURRENCY)
    parser.add_argument("--large-concurrency", type=int, default=DEFAULT_LARGE_CONCURRENCY)
    args = parser.parse_args()
    try:
        result = prepare(args)
    except (PreparationError, split.KimiProviderSplitError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
