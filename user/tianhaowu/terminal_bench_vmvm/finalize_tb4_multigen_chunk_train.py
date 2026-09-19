#!/usr/bin/env python3
"""Finalize a TB4 pass@1 artifact from complete generation-bound chunk roots.

The manifest is intentionally metadata-only: it names controller roots and
hash-pinned launch artifacts, but it does not contain task identifiers, prompts,
trace bodies, raw model output, endpoint URLs, or credentials.

Each controller entry must reference that generation's immutable readiness,
generated proxy-config snapshot, smoke artifact, and deployment-local
``proxy_info.json`` by path and SHA-256.  For the current worker-rotation scope,
do not use an external immutable copy of ``proxy_info.json``:
``load_deployment_endpoint`` requires the pinned proxy-info path to remain beside
that deployment's ``spec.yaml``.  Historical chunks stay finalizable across
worker rotations through the private per-generation generated-config snapshots;
a proxy-info path/hash change is still outside this contract and fails closed.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from finalize_tb4_shard_wave_train import (
    DEFAULT_LOCK_POLL_SECONDS,
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ControllerFinalizerInput,
    FinalizationError,
    MultiGenerationFinalizerConfig,
    WaveTrainConfig,
    _safe_error,
    _stable_private_bytes,
    finalize_multigen_wave_train,
)
from tb4_shard_workflow import ShardWorkflowError

TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "project_dir",
        "project_revision",
        "plan",
        "plan_sha256",
        "deployment_id",
        "deployment_spec",
        "deployment_spec_sha256",
        "dataset_revision",
        "dataset_archive",
        "dataset_archive_sha256",
        "dataset_content_sha256",
        "wave_size",
        "controller_poll_interval_seconds",
        "lock_poll_seconds",
        "lock_timeout_seconds",
        "controllers",
    }
)
CONTROLLER_KEYS = frozenset(
    {
        "controller_root",
        "train_sha256",
        "readiness_checkpoint",
        "readiness_checkpoint_sha256",
        "proxy_info",
        "proxy_info_sha256",
        "proxy_config_snapshot",
        "proxy_config_snapshot_sha256",
        "smoke_checkpoint",
        "smoke_checkpoint_sha256",
        "first_shard_index",
        "shard_count",
        "wave_size",
    }
)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        resolved, raw = _stable_private_bytes(path, label="multigen_manifest")
    except OSError as error:
        raise FinalizationError("manifest_unavailable") from error
    if resolved != path:
        raise FinalizationError("manifest_path_invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise FinalizationError("manifest_invalid") from error
    if not isinstance(value, dict):
        raise FinalizationError("manifest_invalid")
    if set(value) - TOP_LEVEL_KEYS:
        raise FinalizationError("manifest_unknown_key")
    return value


def _required_str(value: dict[str, Any], key: str) -> str:
    observed = value.get(key)
    if not isinstance(observed, str) or not observed:
        raise FinalizationError("manifest_invalid")
    return observed


def _required_path(value: dict[str, Any], key: str) -> Path:
    return Path(_required_str(value, key))


def _optional_float(value: dict[str, Any], key: str, default: float) -> float:
    observed = value.get(key, default)
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(float(observed)):
        raise FinalizationError("manifest_invalid")
    return float(observed)


def _controller_from_manifest(shared: dict[str, Any], item: dict[str, Any]) -> ControllerFinalizerInput:
    if set(item) - CONTROLLER_KEYS:
        raise FinalizationError("manifest_unknown_key")
    first = item.get("first_shard_index")
    count = item.get("shard_count")
    wave_size = item.get("wave_size", shared.get("wave_size", 4))
    if (
        isinstance(first, bool)
        or not isinstance(first, int)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or isinstance(wave_size, bool)
        or not isinstance(wave_size, int)
    ):
        raise FinalizationError("manifest_invalid")
    controller = WaveTrainConfig(
        controller_root=_required_path(item, "controller_root"),
        project_dir=_required_path(shared, "project_dir"),
        project_revision=_required_str(shared, "project_revision"),
        plan_path=_required_path(shared, "plan"),
        plan_sha256=_required_str(shared, "plan_sha256"),
        deployment_id=_required_str(shared, "deployment_id"),
        deployment_spec_path=_required_path(shared, "deployment_spec"),
        deployment_spec_sha256=_required_str(shared, "deployment_spec_sha256"),
        readiness_path=_required_path(item, "readiness_checkpoint"),
        readiness_sha256=_required_str(item, "readiness_checkpoint_sha256"),
        proxy_info_path=_required_path(item, "proxy_info"),
        proxy_info_sha256=_required_str(item, "proxy_info_sha256"),
        smoke_checkpoint_path=_required_path(item, "smoke_checkpoint"),
        smoke_checkpoint_sha256=_required_str(item, "smoke_checkpoint_sha256"),
        proxy_config_snapshot_path=_required_path(item, "proxy_config_snapshot"),
        proxy_config_snapshot_sha256=_required_str(item, "proxy_config_snapshot_sha256"),
        dataset_revision=shared.get("dataset_revision"),
        dataset_archive_path=Path(shared["dataset_archive"])
        if isinstance(shared.get("dataset_archive"), str)
        else None,
        dataset_archive_sha256=shared.get("dataset_archive_sha256"),
        dataset_content_sha256=shared.get("dataset_content_sha256"),
        first_shard_index=first,
        shard_count=count,
        wave_size=wave_size,
        poll_interval_seconds=_optional_float(shared, "controller_poll_interval_seconds", 15.0),
    )
    return ControllerFinalizerInput(
        controller=controller,
        expected_train_sha256=_required_str(item, "train_sha256"),
    )


def config_from_manifest(path: Path, output_dir: Path) -> MultiGenerationFinalizerConfig:
    value = _load_manifest(path)
    if value.get("schema_version") != 1:
        raise FinalizationError("manifest_invalid")
    controllers = value.get("controllers")
    if not isinstance(controllers, list) or not controllers:
        raise FinalizationError("manifest_invalid")
    if any(not isinstance(item, dict) for item in controllers):
        raise FinalizationError("manifest_invalid")
    has_revision = isinstance(value.get("dataset_revision"), str)
    has_archive = isinstance(value.get("dataset_archive"), str)
    if has_revision == has_archive:
        raise FinalizationError("manifest_invalid")
    if has_revision and any(key in value for key in ("dataset_archive_sha256", "dataset_content_sha256")):
        raise FinalizationError("manifest_invalid")
    if has_archive and not all(
        isinstance(value.get(key), str) for key in ("dataset_archive_sha256", "dataset_content_sha256")
    ):
        raise FinalizationError("manifest_invalid")
    return MultiGenerationFinalizerConfig(
        controllers=tuple(_controller_from_manifest(value, item) for item in controllers),
        output_dir=output_dir,
        lock_poll_seconds=_optional_float(value, "lock_poll_seconds", DEFAULT_LOCK_POLL_SECONDS),
        lock_timeout_seconds=_optional_float(value, "lock_timeout_seconds", DEFAULT_LOCK_TIMEOUT_SECONDS),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = config_from_manifest(args.manifest, args.output_dir)
        summary = finalize_multigen_wave_train(config, command_runner=subprocess.run)
    except (OSError, FinalizationError, ShardWorkflowError) as error:
        print(f"tb4_multigen_finalize_error:{_safe_error(str(error))}", file=sys.stderr)
        return 2
    except Exception:
        print("tb4_multigen_finalize_error:finalization_failed", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
