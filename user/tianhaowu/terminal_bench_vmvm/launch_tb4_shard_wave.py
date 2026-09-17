#!/usr/bin/env python3
"""Validate and submit one fail-closed wave of singleton Kimi TB4 shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)
from inference_route_generation import (
    RouteGenerationError,
    validate_readiness_route_generation,
    validate_route_generation,
)
from smoke_qualification import (
    SmokeQualificationError,
    validate_smoke_qualification,
)
from tb4_shard_workflow import (
    PlannedShard,
    ShardWorkflowError,
    canonical_json,
    load_plan,
)

SCHEMA_VERSION = 1
MAX_WAVE_SIZE = 4
DEFAULT_SUBMISSION_TIMEOUT_SECONDS = 30.0
EXPECTED_MODEL = "Kimi-K3"
EXPECTED_VMVM_ENV = {
    "VACLI_MAX_CONCURRENT_LEASES": "2",
    "VACLI_LEASE_RETRIES": "20",
    "VACLI_MAX_PULL_RETRIES": "20",
    "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": "3600",
    "VACLI_CONTAINER_PRIVILEGED": "1",
}
DEFAULT_VACLI_BIN = "/public/fbpkgs/x86_64/vacli/stable/vacli"
DEFAULT_X86_SITE = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64"
DEFAULT_X86_UV = "/storage/home/tianhaowu/.local/x86_64/bin/uv"
DEFAULT_SBATCH = "/usr/bin/sbatch"
EXPECTED_TMUX_TARGET = "swebench_vmvm:Launcher.0"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
DEPLOYMENT_RE = re.compile(r"[A-Za-z0-9._:-]+")
SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
UTC_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
TELEMETRY_OBSERVATION_KEYS = {
    "active_vmvm_runtimes_at_publish",
    "counter_violations",
    "lease_start_attempts",
    "lease_start_finishes",
    "lease_startups_at_publish",
    "lease_tunnels_ready",
    "peak_active_vmvm_runtimes",
    "peak_concurrent_lease_startups",
    "vmvm_runtime_ready",
    "vmvm_runtime_starts",
    "vmvm_runtime_stops",
}
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": "/chat/completions",
    "request_model": EXPECTED_MODEL,
    "response_model": EXPECTED_MODEL,
    "request_reasoning_effort": "max",
    "request_chat_template_kwargs": {
        "enable_thinking": True,
        "preserve_thinking": True,
    },
}
SMOKE_ARTIFACT_PATHS = {
    "results": Path("results.jsonl"),
    "eval_run_identity": Path("eval_run_identity.json"),
    "eval_invocations": Path("eval_invocations.jsonl"),
    "route_guard_success": Path("route_guard_success.json"),
    "config": Path("config.toml"),
    "inputs_manifest": Path("inputs/manifest.json"),
    "provenance": Path("provenance.txt"),
}
OPTIONAL_SMOKE_ARTIFACT_PATHS = {
    "concurrency_telemetry": Path("concurrency_telemetry.json"),
}


class WaveLaunchError(ValueError):
    """The requested wave cannot be launched without weakening its bindings."""


class WaveSubmissionInterrupted(WaveLaunchError):
    """Submission stopped between jobs in response to a controller signal."""


class WaveSubmissionOutcomeUnknown(WaveLaunchError):
    """The scheduler call ended before its acceptance outcome was recorded."""


@dataclass(frozen=True)
class PinnedArtifact:
    path: Path
    sha256: str
    raw: bytes | None


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_artifact(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
    load_bytes: bool = False,
) -> PinnedArtifact:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise WaveLaunchError(f"{label}_sha256_invalid")
    try:
        if path.is_symlink():
            raise WaveLaunchError(f"{label}_unreadable")
        resolved = path.resolve(strict=True)
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            raise WaveLaunchError(f"{label}_unreadable")
        digest = hashlib.sha256()
        chunks: list[bytes] | None = [] if load_bytes else None
        loaded_size = 0
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
                    loaded_size += len(chunk)
                    if loaded_size > MAX_ARTIFACT_BYTES:
                        raise WaveLaunchError(f"{label}_too_large")
        after = resolved.stat()
    except WaveLaunchError:
        raise
    except (OSError, RuntimeError) as error:
        raise WaveLaunchError(f"{label}_unreadable") from error
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_signature != after_signature:
        raise WaveLaunchError(f"{label}_changed")
    if digest.hexdigest() != expected_sha256:
        raise WaveLaunchError(f"{label}_sha256_mismatch")
    return PinnedArtifact(
        path=resolved,
        sha256=expected_sha256,
        raw=b"".join(chunks) if chunks is not None else None,
    )


def _json_object(artifact: PinnedArtifact, *, label: str) -> dict[str, Any]:
    if artifact.raw is None:
        raise WaveLaunchError(f"{label}_invalid")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise WaveLaunchError(f"{label}_invalid")
            value[key] = item
        return value

    def reject_constant(_value: str) -> None:
        raise WaveLaunchError(f"{label}_invalid")

    try:
        value = json.loads(
            artifact.raw,
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except WaveLaunchError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WaveLaunchError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise WaveLaunchError(f"{label}_invalid")
    return value


def _artifact_record(
    value: Any,
    *,
    label: str,
    expected: PinnedArtifact | None = None,
    load_bytes: bool = False,
) -> PinnedArtifact:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not Path(value["path"]).is_absolute()
        or not isinstance(value.get("sha256"), str)
        or SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise WaveLaunchError(f"{label}_mismatch")
    try:
        recorded_path = Path(value["path"])
        recorded = recorded_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WaveLaunchError(f"{label}_mismatch") from error
    if str(recorded_path) != str(recorded):
        raise WaveLaunchError(f"{label}_mismatch")
    if expected is not None and (recorded != expected.path or value["sha256"] != expected.sha256):
        raise WaveLaunchError(f"{label}_mismatch")
    return _stable_artifact(
        recorded,
        value["sha256"],
        label=label,
        load_bytes=load_bytes,
    )


def _proxy_policy(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "request_timeout",
            "num_retries",
            "proxy_litellm_config",
        }
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or type(value.get("request_timeout")) is not int
        or value["request_timeout"] != 7200
        or type(value.get("num_retries")) is not int
        or value["num_retries"] != 0
    ):
        raise WaveLaunchError("proxy_policy_invalid")
    _artifact_record(
        value.get("proxy_litellm_config"),
        label="proxy_litellm_config",
    )
    return value


def _record(artifact: PinnedArtifact) -> dict[str, str]:
    return {"path": str(artifact.path), "sha256": artifact.sha256}


def _validate_invocation(
    artifact: PinnedArtifact,
    *,
    identity_sha256: str,
) -> dict[str, Any]:
    if artifact.raw is None or not artifact.raw.endswith(b"\n") or artifact.raw.count(b"\n") != 1:
        raise WaveLaunchError("smoke_guard_invocation_invalid")
    value = _json_object(artifact, label="smoke_guard_invocation")
    if (
        set(value)
        != {
            "schema_version",
            "eval_run_identity_sha256",
            "role",
            "resume",
            "host",
            "slurm_job_id",
        }
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("eval_run_identity_sha256") != identity_sha256
        or value.get("role") != "smoke"
        or value.get("resume") is not False
        or not isinstance(value.get("host"), str)
        or not value["host"].strip()
        or any(character in value["host"] for character in "\r\n")
        or not isinstance(value.get("slurm_job_id"), str)
        or SLURM_JOB_ID_RE.fullmatch(value["slurm_job_id"]) is None
    ):
        raise WaveLaunchError("smoke_guard_invocation_invalid")
    return value


def _validate_telemetry(
    artifact: PinnedArtifact,
    *,
    identity_sha256: str,
    slurm_job_id: str,
) -> dict[str, Any]:
    if artifact.raw is None or stat.S_IMODE(artifact.path.stat().st_mode) != 0o400:
        raise WaveLaunchError("smoke_concurrency_telemetry_invalid")
    value = _json_object(artifact, label="smoke_concurrency_telemetry")
    body = {key: item for key, item in value.items() if key != "concurrency_telemetry_sha256"}
    observations = value.get("observations")
    if (
        set(value)
        != {
            "schema_version",
            "state",
            "eval_run_identity_sha256",
            "eval_run_role",
            "slurm_job_id",
            "process_id",
            "measurement_scope",
            "observations",
            "concurrency_telemetry_sha256",
        }
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("state") != "complete"
        or value.get("eval_run_identity_sha256") != identity_sha256
        or value.get("eval_run_role") != "smoke"
        or value.get("slurm_job_id") != slurm_job_id
        or type(value.get("process_id")) is not int
        or value["process_id"] < 1
        or value.get("measurement_scope") != "single_evaluator_process"
        or not isinstance(observations, dict)
        or set(observations) != TELEMETRY_OBSERVATION_KEYS
        or value.get("concurrency_telemetry_sha256") != _sha256_bytes(canonical_json(body))
        or any(type(item) is not int or item < 0 for item in observations.values())
        or observations["counter_violations"] != 0
        or observations["active_vmvm_runtimes_at_publish"] != 0
        or observations["lease_startups_at_publish"] != 0
        or observations["vmvm_runtime_starts"] < 1
        or observations["vmvm_runtime_starts"] != observations["vmvm_runtime_stops"]
        or observations["vmvm_runtime_ready"] > observations["vmvm_runtime_starts"]
        or observations["lease_start_attempts"] < 1
        or observations["lease_start_attempts"] != observations["lease_start_finishes"]
        or observations["lease_tunnels_ready"] > observations["lease_start_attempts"]
        or observations["lease_start_attempts"] < observations["vmvm_runtime_starts"]
        or observations["lease_tunnels_ready"] < observations["vmvm_runtime_ready"]
        or not 1 <= observations["peak_active_vmvm_runtimes"] <= observations["vmvm_runtime_starts"]
        or not 1 <= observations["peak_concurrent_lease_startups"] <= observations["lease_start_attempts"]
    ):
        raise WaveLaunchError("smoke_concurrency_telemetry_invalid")
    return value


def _validate_guard_linkage(
    records: Mapping[str, PinnedArtifact],
    *,
    identity_sha256: str,
    deployment_id: str,
    deployment_spec: PinnedArtifact,
    readiness: PinnedArtifact,
    endpoint: dict[str, Any],
    generation: dict[str, Any],
    proxy_policy: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    receipt_artifact = records["route_guard_success"]
    receipt = _json_object(receipt_artifact, label="smoke_guard_receipt")
    receipt_body = {key: item for key, item in receipt.items() if key != "guard_success_receipt_sha256"}
    has_telemetry = "concurrency_telemetry" in records
    schema_version = 2 if has_telemetry else 1
    expected_artifacts = {
        "eval_run_identity": _record(records["eval_run_identity"]),
        "eval_invocations": _record(records["eval_invocations"]),
        "results": _record(records["results"]),
    }
    if has_telemetry:
        expected_artifacts["concurrency_telemetry"] = _record(records["concurrency_telemetry"])
    deployment = receipt.get("deployment")
    if (
        set(receipt)
        != {
            "schema_version",
            "state",
            "evaluator_exit_code",
            "completed_at",
            "eval_run_role",
            "eval_run_identity_sha256",
            "deployment",
            "artifacts",
            "guard_success_receipt_sha256",
        }
        or type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != schema_version
        or receipt.get("state") != "passed"
        or receipt.get("evaluator_exit_code") != 0
        or receipt.get("eval_run_role") != "smoke"
        or receipt.get("eval_run_identity_sha256") != identity_sha256
        or receipt.get("guard_success_receipt_sha256") != _sha256_bytes(canonical_json(receipt_body))
        or not isinstance(deployment, dict)
        or set(deployment)
        != {
            "id",
            "spec_sha256",
            "readiness_checkpoint",
            "endpoint",
            "serving_route_generation",
            "proxy_policy",
        }
        or deployment.get("id") != deployment_id
        or deployment.get("spec_sha256") != deployment_spec.sha256
        or deployment.get("readiness_checkpoint") != _record(readiness)
        or deployment.get("endpoint") != endpoint
        or deployment.get("serving_route_generation") != generation
        or deployment.get("proxy_policy") != proxy_policy
        or receipt.get("artifacts") != expected_artifacts
        or receipt_artifact.path.name != "route_guard_success.json"
    ):
        raise WaveLaunchError("smoke_guard_receipt_invalid")
    completed_at = receipt.get("completed_at")
    if not isinstance(completed_at, str) or UTC_TIMESTAMP_RE.fullmatch(completed_at) is None:
        raise WaveLaunchError("smoke_guard_receipt_invalid")
    try:
        datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise WaveLaunchError("smoke_guard_receipt_invalid") from error
    invocation = _validate_invocation(
        records["eval_invocations"],
        identity_sha256=identity_sha256,
    )
    if has_telemetry:
        return (
            _validate_telemetry(
                records["concurrency_telemetry"],
                identity_sha256=identity_sha256,
                slurm_job_id=invocation["slurm_job_id"],
            ),
            invocation,
        )
    return None, invocation


def _validate_identity_source(source: Any) -> None:
    expected_keys = {
        "project_root",
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
        "vmvm_tb_v2_sha256",
    }
    if not isinstance(source, dict) or set(source) != expected_keys:
        raise WaveLaunchError("smoke_identity_source_invalid")
    try:
        root = Path(source["project_root"]).resolve(strict=True)
    except (KeyError, OSError, RuntimeError) as error:
        raise WaveLaunchError("smoke_identity_source_invalid") from error
    for name, repository, revision_key, tree_key in (
        ("prime_rl", root, "prime_rl_commit", "prime_rl_tree_sha256"),
        ("verifiers", root / "deps/verifiers", "verifiers_commit", "verifiers_tree_sha256"),
        ("renderers", root / "deps/renderers", "renderers_commit", "renderers_tree_sha256"),
    ):
        revision = source.get(revision_key)
        tree_digest = source.get(tree_key)
        if (
            not isinstance(revision, str)
            or REVISION_RE.fullmatch(revision) is None
            or tree_digest != CLEAN_TREE_SHA256
            or _git(
                subprocess.run,
                repository,
                "rev-parse",
                "--verify",
                "HEAD",
                label=f"smoke_{name}",
            ).strip()
            != revision
            or _git(
                subprocess.run,
                repository,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                label=f"smoke_{name}",
            )
        ):
            raise WaveLaunchError("smoke_identity_source_invalid")
    source_root = root / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    paths = sorted(source_root.glob("*.py"))
    if not paths:
        raise WaveLaunchError("smoke_identity_source_invalid")
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest.update(f"{_sha256_path(path)}  {relative}\n".encode())
    if source.get("vmvm_tb_v2_sha256") != digest.hexdigest():
        raise WaveLaunchError("smoke_identity_source_invalid")


def _manifest_snapshot(
    value: Any,
    *,
    inputs_dir: Path,
    name: str,
    filename: str,
) -> PinnedArtifact:
    if (
        not isinstance(value, dict)
        or set(value) != {"source", "snapshot", "sha256"}
        or not isinstance(value.get("source"), str)
        or not Path(value["source"]).is_absolute()
        or value.get("snapshot") != str(inputs_dir / filename)
    ):
        raise WaveLaunchError("smoke_identity_inputs_invalid")
    return _artifact_record(
        {"path": value.get("snapshot"), "sha256": value.get("sha256")},
        label=f"smoke_identity_{name}",
        load_bytes=name == "config",
    )


def _validate_identity_dataset(dataset: Any, config: dict[str, Any]) -> None:
    if (
        not isinstance(dataset, dict)
        or set(dataset) != {"kind", "path", "revision", "archive", "content_sha256"}
        or not isinstance(dataset.get("path"), str)
        or not Path(dataset["path"]).is_absolute()
    ):
        raise WaveLaunchError("smoke_identity_dataset_invalid")
    taskset = config.get("taskset")
    if (
        not isinstance(taskset, dict)
        or not isinstance(taskset.get("dataset_dir"), str)
        or Path(taskset["dataset_dir"]).resolve(strict=True) != Path(dataset["path"]).resolve(strict=True)
    ):
        raise WaveLaunchError("smoke_identity_dataset_invalid")
    if dataset.get("kind") == "git_revision":
        revision = dataset.get("revision")
        if (
            not isinstance(revision, str)
            or REVISION_RE.fullmatch(revision) is None
            or dataset.get("archive") != {"path": None, "sha256": None}
            or dataset.get("content_sha256") is not None
            or taskset.get("dataset_revision") != revision
        ):
            raise WaveLaunchError("smoke_identity_dataset_invalid")
        root = Path(dataset["path"])
        if _git(
            subprocess.run,
            root,
            "rev-parse",
            "--verify",
            "HEAD",
            label="smoke_dataset",
        ).strip() != revision or _git(
            subprocess.run,
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            label="smoke_dataset",
        ):
            raise WaveLaunchError("smoke_identity_dataset_invalid")
        return
    content_sha256 = dataset.get("content_sha256")
    if (
        dataset.get("kind") != "archive"
        or dataset.get("revision") is not None
        or not isinstance(content_sha256, str)
        or SHA256_RE.fullmatch(content_sha256) is None
        or taskset.get("dataset_revision") is not None
        or taskset.get("use_declared_images") is not True
    ):
        raise WaveLaunchError("smoke_identity_dataset_invalid")
    archive = _artifact_record(
        dataset.get("archive"),
        label="smoke_identity_dataset_archive",
    )
    if (
        _archive_tasks_tree_digest(archive.path) != content_sha256
        or _tree_digest(Path(dataset["path"])) != content_sha256
    ):
        raise WaveLaunchError("smoke_identity_dataset_invalid")


def _validate_identity_references(
    identity: Any,
    records: Mapping[str, PinnedArtifact],
    *,
    run_dir: Path,
    expected_traces: int,
    deployment_id: str,
    deployment_spec: PinnedArtifact,
    readiness: PinnedArtifact,
    endpoint: Any,
    generation: dict[str, Any],
    proxy_policy: dict[str, Any],
    invocation: Mapping[str, Any],
) -> None:
    if (
        not isinstance(identity, dict)
        or set(identity)
        != {
            "schema_version",
            "role",
            "source",
            "config",
            "inputs",
            "dataset",
            "deployment",
            "contract",
            "execution",
        }
        or type(identity.get("schema_version")) is not int
        or identity["schema_version"] != 1
        or identity.get("role") != "smoke"
    ):
        raise WaveLaunchError("smoke_checkpoint_identity_mismatch")
    _validate_identity_source(identity.get("source"))
    config_section = identity.get("config")
    inputs = identity.get("inputs")
    if (
        not isinstance(config_section, dict)
        or set(config_section) != {"source", "resolved"}
        or not isinstance(inputs, dict)
        or set(inputs) != {"manifest", "task_file", "image_manifest"}
    ):
        raise WaveLaunchError("smoke_identity_inputs_invalid")
    resolved_config = _artifact_record(
        config_section.get("resolved"),
        label="smoke_identity_resolved_config",
        expected=records["config"],
        load_bytes=True,
    )
    manifest_artifact = _artifact_record(
        inputs.get("manifest"),
        label="smoke_identity_manifest",
        expected=records["inputs_manifest"],
        load_bytes=True,
    )
    if resolved_config.path != run_dir / "config.toml" or manifest_artifact.path != run_dir / "inputs/manifest.json":
        raise WaveLaunchError("smoke_identity_artifact_path_mismatch")
    manifest = _json_object(manifest_artifact, label="smoke_identity_manifest")
    if not {"config", "task_file"}.issubset(manifest) or set(manifest) - {
        "config",
        "task_file",
        "image_manifest",
    }:
        raise WaveLaunchError("smoke_identity_inputs_invalid")
    inputs_dir = run_dir / "inputs"
    source_config = _manifest_snapshot(
        manifest.get("config"),
        inputs_dir=inputs_dir,
        name="config",
        filename="source_config.toml",
    )
    task_file = _manifest_snapshot(
        manifest.get("task_file"),
        inputs_dir=inputs_dir,
        name="task_file",
        filename="task_file.txt",
    )
    image_manifest: PinnedArtifact | None = None
    if manifest.get("image_manifest") is not None:
        image_manifest = _manifest_snapshot(
            manifest["image_manifest"],
            inputs_dir=inputs_dir,
            name="image_manifest",
            filename="image_manifest.json",
        )
    if (
        config_section.get("source") != _record(source_config)
        or inputs.get("manifest") != _record(manifest_artifact)
        or inputs.get("task_file") != {**_record(task_file), "count": expected_traces}
        or inputs.get("image_manifest") != (_record(image_manifest) if image_manifest is not None else None)
    ):
        raise WaveLaunchError("smoke_identity_inputs_invalid")
    assert resolved_config.raw is not None
    try:
        config = tomllib.loads(resolved_config.raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise WaveLaunchError("smoke_identity_config_invalid") from error
    client = config.get("client")
    sampling = config.get("sampling")
    harness = config.get("harness")
    taskset = config.get("taskset")
    execution = identity.get("execution")
    contract = identity.get("contract")
    routing = identity.get("deployment", {}).get("routing")
    routing_id = routing.get("deployment_id") if isinstance(routing, dict) else None
    expected_headers = {} if routing_id is None else {"X-Deployment-Id": routing_id}
    image_selection_valid = (
        taskset.get("image_manifest") is None and taskset.get("image_manifest_sha256") is None
        if isinstance(taskset, dict) and image_manifest is None
        else isinstance(taskset, dict)
        and image_manifest is not None
        and taskset.get("image_manifest") == str(image_manifest.path)
        and taskset.get("image_manifest_sha256") == image_manifest.sha256
    )
    if (
        not isinstance(client, dict)
        or not isinstance(sampling, dict)
        or not isinstance(harness, dict)
        or not isinstance(taskset, dict)
        or config.get("output_dir") != str(run_dir)
        or taskset.get("task_file") != str(task_file.path)
        or taskset.get("task_file_sha256") != task_file.sha256
        or not image_selection_valid
        or config.get("num_tasks") != expected_traces
        or client.get("base_url") != endpoint.client_base_url
        or routing != {"deployment_id": routing_id, "headers": expected_headers}
        or (routing_id is not None and routing_id != deployment_id)
    ):
        raise WaveLaunchError("smoke_identity_config_invalid")
    expected_contract = {
        "model": config.get("model"),
        "pass_at_1": True,
        "num_rollouts": 1,
        "reasoning_effort": "max",
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "context_tokens": {
            "max_input_tokens": config.get("max_input_tokens"),
            "max_output_tokens": config.get("max_output_tokens"),
            "max_total_tokens": config.get("max_total_tokens"),
        },
        "sampling_max_tokens": sampling.get("max_tokens"),
        "capture_model_io": True,
        "outbound_body_denylist": sorted({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"}),
        "retain_traces": False,
    }
    expected_execution = {
        "rollout_concurrency": config.get("max_concurrent"),
        "multiplex": config.get("multiplex"),
        "http_max_connections": client.get("max_connections"),
        "http_max_keepalive_connections": client.get("max_keepalive_connections"),
        "runtime": harness.get("runtime"),
    }
    if (
        contract != expected_contract
        or config.get("model") != EXPECTED_MODEL
        or config.get("num_rollouts") != 1
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or set(expected_contract["context_tokens"].values()) != {262_144}
        or type(sampling.get("max_tokens")) is not int
        or not 0 < sampling["max_tokens"] <= 262_144
        or client.get("type") != "eval"
        or client.get("api_key_var") != "OPENAI_API_KEY"
        or client.get("capture_model_io") is not True
        or client.get("headers") != expected_headers
        or set(client.get("outbound_body_denylist") or [])
        != {"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"}
        or len(client.get("outbound_body_denylist") or []) != 4
        or config.get("retain_traces") is not False
        or config.get("rich") is not False
        or not isinstance(harness.get("runtime"), dict)
        or harness["runtime"].get("type") != "vmvm"
        or not isinstance(execution, dict)
        or set(execution)
        != {
            "rollout_concurrency",
            "multiplex",
            "http_max_connections",
            "http_max_keepalive_connections",
            "runtime",
            "vmvm_environment",
        }
        or any(execution.get(key) != value for key, value in expected_execution.items())
    ):
        raise WaveLaunchError("smoke_identity_config_invalid")
    vmvm = execution.get("vmvm_environment")
    if vmvm != {
        "vacli_bin": DEFAULT_VACLI_BIN,
        "lease_start_concurrency": 2,
        "lease_retries": 20,
        "max_pull_retries": 20,
        "image_pull_timeout_sec": 3600,
        "container_privileged": True,
    }:
        raise WaveLaunchError("smoke_identity_execution_invalid")
    deployment = identity.get("deployment")
    if (
        not isinstance(deployment, dict)
        or set(deployment)
        != {
            "id",
            "endpoint",
            "serving_route_generation",
            "proxy_policy",
            "routing",
            "spec",
            "readiness_checkpoint",
            "smoke_checkpoint",
            "promotion_certificate",
        }
        or deployment.get("id") != deployment_id
        or deployment.get("endpoint") != endpoint.binding
        or deployment.get("serving_route_generation") != generation
        or deployment.get("proxy_policy") != proxy_policy
        or deployment.get("spec") != _record(deployment_spec)
        or deployment.get("readiness_checkpoint") != _record(readiness)
        or deployment.get("smoke_checkpoint") is not None
        or deployment.get("promotion_certificate") is not None
    ):
        raise WaveLaunchError("smoke_checkpoint_identity_mismatch")
    _validate_identity_dataset(identity.get("dataset"), config)

    provenance: dict[str, str] = {}
    assert records["provenance"].raw is not None
    try:
        for line in records["provenance"].raw.decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if not separator or not key or not value or key in provenance:
                raise WaveLaunchError("smoke_identity_provenance_invalid")
            provenance[key] = value
    except UnicodeDecodeError as error:
        raise WaveLaunchError("smoke_identity_provenance_invalid") from error
    source = identity["source"]
    expected_provenance = {
        "prime_rl": source["prime_rl_commit"],
        "prime_rl_tree": source["prime_rl_tree_sha256"],
        "verifiers": source["verifiers_commit"],
        "verifiers_tree": source["verifiers_tree_sha256"],
        "renderers": source["renderers_commit"],
        "renderers_tree": source["renderers_tree_sha256"],
        "vmvm_tb_v2": source["vmvm_tb_v2_sha256"],
        "deployment_id": deployment_id,
        "deployment_endpoint_authority_sha256": endpoint.binding["authority_sha256"],
        "deployment_proxy_info_sha256": endpoint.binding["proxy_info"]["sha256"],
        "eval_run_role": "smoke",
        "eval_run_identity_sha256": _sha256_bytes(canonical_json(identity)),
        "approval_task_file_sha256": task_file.sha256,
        "approval_task_count": str(expected_traces),
    }
    if (
        set(provenance) != {*expected_provenance, "host", "slurm_job_id"}
        or any(provenance.get(key) != value for key, value in expected_provenance.items())
        or not provenance.get("host", "").strip()
        or provenance.get("host") != invocation.get("host")
        or provenance.get("slurm_job_id") != invocation.get("slurm_job_id")
    ):
        raise WaveLaunchError("smoke_identity_provenance_invalid")


def _validate_generation_bindings_legacy(
    *,
    deployment_id: str,
    deployment_spec: PinnedArtifact,
    readiness: PinnedArtifact,
    proxy_info: PinnedArtifact,
    smoke: PinnedArtifact,
) -> str:
    readiness_value = _json_object(readiness, label="readiness_checkpoint")
    probe = readiness_value.get("probe")
    try:
        endpoint = load_deployment_endpoint(
            proxy_info.path,
            deployment_id=deployment_id,
            expected_model=EXPECTED_MODEL,
            deployment_spec=deployment_spec.path,
            expected_proxy_info_sha256=proxy_info.sha256,
        )
        readiness_endpoint = validate_endpoint_binding(readiness_value.get("endpoint"))
        generation = validate_readiness_route_generation(
            readiness_value,
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec.sha256,
        )
    except (EndpointBindingError, RouteGenerationError) as error:
        raise WaveLaunchError("readiness_checkpoint_not_passed") from error
    readiness_policy = _proxy_policy(readiness_value.get("proxy_policy"))
    if (
        type(readiness_value.get("schema_version")) is not int
        or readiness_value.get("schema_version") != 1
        or readiness_value.get("state") != "passed"
        or readiness_value.get("deployment") != deployment_id
        or readiness_value.get("observed_spec_sha256") != deployment_spec.sha256
        or not isinstance(probe, dict)
        or probe.get("ok") is not True
        or readiness_endpoint != endpoint.binding
    ):
        raise WaveLaunchError("readiness_checkpoint_not_passed")
    smoke_value = _json_object(smoke, label="smoke_checkpoint")
    smoke_deployment = smoke_value.get("deployment")
    smoke_artifacts = smoke_value.get("artifacts")
    policy = smoke_value.get("audit_policy")
    counts = smoke_value.get("counts")
    smoke_body = {key: item for key, item in smoke_value.items() if key != "smoke_checkpoint_sha256"}
    try:
        smoke_endpoint = validate_endpoint_binding(smoke_value.get("endpoint"))
        smoke_generation = validate_route_generation(smoke_value.get("serving_route_generation"))
    except (EndpointBindingError, RouteGenerationError) as error:
        raise WaveLaunchError("smoke_checkpoint_not_passed") from error
    smoke_policy = _proxy_policy(smoke_value.get("proxy_policy"))
    if (
        type(smoke_value.get("schema_version")) is not int
        or smoke_value.get("schema_version") != 1
        or smoke_value.get("state") != "passed"
        or smoke_value.get("ok") is not True
        or smoke_value.get("deployment_id") != deployment_id
        or smoke_value.get("deployment_spec_sha256") != deployment_spec.sha256
        or smoke_value.get("readiness_checkpoint_sha256") != readiness.sha256
        or smoke_value.get("smoke_checkpoint_sha256") != _sha256_bytes(canonical_json(smoke_body))
        or not isinstance(smoke_deployment, dict)
        or smoke_deployment.get("id") != deployment_id
        or smoke_deployment.get("spec_sha256") != deployment_spec.sha256
        or smoke_endpoint != endpoint.binding
        or smoke_generation != generation
        or smoke_policy != readiness_policy
        or not isinstance(smoke_artifacts, dict)
        or set(smoke_artifacts)
        not in (
            set(SMOKE_ARTIFACT_PATHS) | {"readiness_checkpoint", "proxy_info"},
            set(SMOKE_ARTIFACT_PATHS) | set(OPTIONAL_SMOKE_ARTIFACT_PATHS) | {"readiness_checkpoint", "proxy_info"},
        )
        or not isinstance(policy, dict)
        or policy.get("rollouts_per_task") != 1
        or policy.get("require_reasoning") is not True
        or policy.get("require_model_io") is not True
        or canonical_json(policy.get("model_io_contract")) != canonical_json(EXPECTED_MODEL_IO_CONTRACT)
        or policy.get("require_token_data") is not False
        or policy.get("require_logprobs") is not False
        or policy.get("max_sequence_tokens") != 262_144
        or not isinstance(counts, dict)
        or counts.get("trace_failures") != 0
        or counts.get("global_problems") != 0
        or not isinstance(counts.get("sampled_tokens"), int)
        or isinstance(counts.get("sampled_tokens"), bool)
        or counts["sampled_tokens"] < 1
    ):
        raise WaveLaunchError("smoke_checkpoint_not_passed")
    expected_traces = policy.get("expected_traces")
    if (
        not isinstance(expected_traces, int)
        or isinstance(expected_traces, bool)
        or expected_traces < 1
        or counts.get("traces") != expected_traces
        or counts.get("tasks") != expected_traces
        or not isinstance(counts.get("model_io_turns"), int)
        or isinstance(counts.get("model_io_turns"), bool)
        or counts["model_io_turns"] < 1
    ):
        raise WaveLaunchError("smoke_checkpoint_not_passed")
    _artifact_record(
        smoke_artifacts.get("readiness_checkpoint"),
        label="smoke_readiness_checkpoint",
        expected=readiness,
    )
    _artifact_record(
        smoke_artifacts.get("proxy_info"),
        label="smoke_proxy_info",
        expected=proxy_info,
    )
    expected_paths = {
        **SMOKE_ARTIFACT_PATHS,
        **{name: relative for name, relative in OPTIONAL_SMOKE_ARTIFACT_PATHS.items() if name in smoke_artifacts},
    }
    records = {
        name: _artifact_record(
            smoke_artifacts.get(name),
            label=f"smoke_{name}",
            load_bytes=name
            in {
                "eval_run_identity",
                "eval_invocations",
                "route_guard_success",
                "concurrency_telemetry",
                "config",
                "inputs_manifest",
                "provenance",
            },
        )
        for name in expected_paths
    }
    run_dir = records["eval_run_identity"].path.parent
    if smoke.path != run_dir / "smoke_checkpoint.json" or any(
        records[name].path != run_dir / relative for name, relative in expected_paths.items()
    ):
        raise WaveLaunchError("smoke_artifact_path_mismatch")
    identity_envelope = _json_object(
        records["eval_run_identity"],
        label="smoke_eval_run_identity",
    )
    identity = identity_envelope.get("identity")
    identity_digest = identity_envelope.get("eval_run_identity_sha256")
    identity_deployment = identity.get("deployment") if isinstance(identity, dict) else None
    identity_inputs = identity.get("inputs") if isinstance(identity, dict) else None
    identity_task_file = identity_inputs.get("task_file") if isinstance(identity_inputs, dict) else None
    if (
        set(identity_envelope)
        != {
            "schema_version",
            "eval_run_identity_sha256",
            "identity",
        }
        or identity_envelope.get("schema_version") != 1
        or not isinstance(identity, dict)
        or not isinstance(identity_digest, str)
        or identity_digest != _sha256_bytes(canonical_json(identity))
        or smoke_value.get("eval_run_identity_sha256") != identity_digest
        or identity.get("role") != "smoke"
        or not isinstance(identity_deployment, dict)
        or identity_deployment.get("id") != deployment_id
        or identity_deployment.get("endpoint") != endpoint.binding
        or identity_deployment.get("serving_route_generation") != generation
        or identity_deployment.get("proxy_policy") != readiness_policy
        or not isinstance(identity_deployment.get("spec"), dict)
        or identity_deployment["spec"].get("sha256") != deployment_spec.sha256
        or identity_deployment.get("readiness_checkpoint") != {"path": str(readiness.path), "sha256": readiness.sha256}
        or not isinstance(identity_task_file, dict)
        or identity_task_file.get("count") != expected_traces
    ):
        raise WaveLaunchError("smoke_checkpoint_identity_mismatch")
    telemetry, invocation = _validate_guard_linkage(
        records,
        identity_sha256=identity_digest,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        readiness=readiness,
        endpoint=endpoint.binding,
        generation=generation,
        proxy_policy=readiness_policy,
    )
    _validate_identity_references(
        identity,
        records,
        run_dir=run_dir,
        expected_traces=expected_traces,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        readiness=readiness,
        endpoint=endpoint,
        generation=generation,
        proxy_policy=readiness_policy,
        invocation=invocation,
    )
    qualified = smoke_value.get("qualified_execution")
    identity_execution = identity.get("execution")
    identity_vmvm_environment = (
        identity_execution.get("vmvm_environment") if isinstance(identity_execution, dict) else None
    )
    expected_qualified = {
        "rollout_concurrency": (
            identity_execution.get("rollout_concurrency") if isinstance(identity_execution, dict) else None
        ),
        "multiplex": (identity_execution.get("multiplex") if isinstance(identity_execution, dict) else None),
        "http_max_connections": (
            identity_execution.get("http_max_connections") if isinstance(identity_execution, dict) else None
        ),
        "http_max_keepalive_connections": (
            identity_execution.get("http_max_keepalive_connections") if isinstance(identity_execution, dict) else None
        ),
        "lease_start_concurrency": (
            identity_vmvm_environment.get("lease_start_concurrency")
            if isinstance(identity_vmvm_environment, dict)
            else None
        ),
    }
    if (
        not isinstance(qualified, dict)
        or set(qualified)
        != {
            "rollout_concurrency",
            "multiplex",
            "http_max_connections",
            "http_max_keepalive_connections",
            "lease_start_concurrency",
        }
        or any(type(value) is not int or value < 1 for value in qualified.values())
        or qualified != expected_qualified
    ):
        raise WaveLaunchError("smoke_qualified_execution_invalid")
    observed = smoke_value.get("observed_concurrency")
    if telemetry is None:
        if observed is not None:
            raise WaveLaunchError("smoke_observed_concurrency_invalid")
    else:
        observations = telemetry["observations"]
        required_rollouts = (
            observed.get("required_peak_active_rollouts_lower_bound") if isinstance(observed, dict) else None
        )
        required_leases = (
            observed.get("required_peak_concurrent_lease_startups") if isinstance(observed, dict) else None
        )
        requirements_valid = (required_rollouts is None and required_leases is None) or (
            type(required_rollouts) is int
            and required_rollouts >= 1
            and type(required_leases) is int
            and required_leases >= 1
        )
        if (
            not isinstance(observed, dict)
            or set(observed)
            != {
                "active_rollout_signal",
                "lease_start_signal",
                "peak_active_rollouts_lower_bound",
                "peak_concurrent_lease_startups",
                "required_peak_active_rollouts_lower_bound",
                "required_peak_concurrent_lease_startups",
            }
            or observed.get("active_rollout_signal") != "completed_trace_lifecycle_timing_overlap"
            or observed.get("lease_start_signal") != "vacli_lease_start_semaphore_holders"
            or type(observed.get("peak_active_rollouts_lower_bound")) is not int
            or observed["peak_active_rollouts_lower_bound"] < 1
            or observed.get("peak_concurrent_lease_startups") != observations["peak_concurrent_lease_startups"]
            or observations["vmvm_runtime_ready"] < expected_traces
            or not requirements_valid
            or observed["peak_active_rollouts_lower_bound"] > qualified["rollout_concurrency"]
            or observed["peak_concurrent_lease_startups"] > qualified["lease_start_concurrency"]
            or (required_rollouts is not None and required_rollouts > observed["peak_active_rollouts_lower_bound"])
            or (required_leases is not None and required_leases > observed["peak_concurrent_lease_startups"])
        ):
            raise WaveLaunchError("smoke_observed_concurrency_invalid")
    return _sha256_bytes(canonical_json(generation))


def _validate_generation_bindings(
    *,
    deployment_id: str,
    deployment_spec: PinnedArtifact,
    readiness: PinnedArtifact,
    proxy_info: PinnedArtifact,
    smoke: PinnedArtifact,
) -> str:
    """Validate v1 or bridged smoke through the shared qualification gate."""

    payload = _json_object(smoke, label="smoke_checkpoint")
    if payload.get("schema_version") == 1:
        return _validate_generation_bindings_legacy(
            deployment_id=deployment_id,
            deployment_spec=deployment_spec,
            readiness=readiness,
            proxy_info=proxy_info,
            smoke=smoke,
        )
    try:
        evidence = validate_smoke_qualification(
            smoke.path,
            smoke.sha256,
            deployment_id=deployment_id,
            deployment_spec_path=deployment_spec.path,
            deployment_spec_sha256=deployment_spec.sha256,
            readiness_path=readiness.path,
            readiness_sha256=readiness.sha256,
            proxy_info_path=proxy_info.path,
            proxy_info_sha256=proxy_info.sha256,
            model=EXPECTED_MODEL,
        )
    except SmokeQualificationError as error:
        raise WaveLaunchError("smoke_checkpoint_not_passed") from error
    return _sha256_bytes(canonical_json(evidence.target_generation))


def _git(
    runner: RunCommand,
    repository: Path,
    *arguments: str,
    label: str,
) -> str:
    try:
        result = runner(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise WaveLaunchError(f"{label}_unverifiable") from error
    if result.returncode != 0:
        raise WaveLaunchError(f"{label}_unverifiable")
    return result.stdout


def validate_clean_project(project_dir: Path, *, runner: RunCommand = subprocess.run) -> dict[str, str]:
    try:
        root = project_dir.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WaveLaunchError("project_unreadable") from error
    repositories = {
        "prime_rl": root,
        "verifiers": root / "deps/verifiers",
        "renderers": root / "deps/renderers",
    }
    revisions: dict[str, str] = {}
    for name, repository in repositories.items():
        status = _git(
            runner,
            repository,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            label=name,
        )
        if status:
            raise WaveLaunchError(f"{name}_worktree_not_clean")
        revision = _git(runner, repository, "rev-parse", "--verify", "HEAD", label=name).strip()
        if REVISION_RE.fullmatch(revision) is None:
            raise WaveLaunchError(f"{name}_revision_invalid")
        revisions[name] = revision
    return revisions


def _private_write(path: Path, raw: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise WaveLaunchError("wave_metadata_write_failed") from error


def _replace_private_json(path: Path, value: dict[str, Any]) -> str:
    body = dict(value)
    body.pop("wave_sha256", None)
    envelope = {**body, "wave_sha256": _sha256_bytes(canonical_json(body))}
    raw = json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise WaveLaunchError("wave_metadata_write_failed") from error
    return envelope["wave_sha256"]


def _encode_environment(values: Mapping[str, str]) -> bytes:
    records: list[bytes] = []
    for key in sorted(values):
        value = values[key]
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise WaveLaunchError("job_environment_invalid")
        records.append(f"{key}={value}".encode("utf-8") + b"\x00")
    return b"".join(records)


def _job_environment(
    *,
    project_dir: Path,
    project_revision: str,
    shard: PlannedShard,
    output_dir: Path,
    deployment_id: str,
    deployment_spec: PinnedArtifact,
    readiness: PinnedArtifact,
    proxy_info: PinnedArtifact,
    smoke: PinnedArtifact,
    dataset_revision: str | None,
    dataset_archive: PinnedArtifact | None,
    dataset_content_sha256: str | None,
) -> dict[str, str]:
    values = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PROJECT_DIR": str(project_dir),
        "EVAL_EXPECTED_PRIME_RL_REVISION": project_revision,
        "EVAL_CONFIG": str(shard.config),
        "EVAL_CONFIG_SHA256": shard.config_sha256,
        "OUTPUT_DIR": str(output_dir),
        "EVAL_APPROVED_TASK_FILE": str(shard.task_manifest),
        "EVAL_APPROVED_TASK_FILE_SHA256": shard.task_manifest_sha256,
        "EVAL_RUN_ROLE": "tb4",
        "EVAL_DEPLOYMENT_ID": deployment_id,
        "EVAL_EXPECTED_MODEL": EXPECTED_MODEL,
        "INFERENCE_DEPLOYMENT_SPEC": str(deployment_spec.path),
        "INFERENCE_DEPLOYMENT_SPEC_SHA256": deployment_spec.sha256,
        "INFERENCE_READINESS_CHECKPOINT": str(readiness.path),
        "INFERENCE_READINESS_CHECKPOINT_SHA256": readiness.sha256,
        "INFERENCE_PROXY_INFO": str(proxy_info.path),
        "INFERENCE_PROXY_INFO_SHA256": proxy_info.sha256,
        "INFERENCE_SMOKE_CHECKPOINT": str(smoke.path),
        "INFERENCE_SMOKE_CHECKPOINT_SHA256": smoke.sha256,
        "VACLI_BIN": DEFAULT_VACLI_BIN,
        "PYTHON_SITE_X86_64": DEFAULT_X86_SITE,
        "UV_BIN_X86_64": DEFAULT_X86_UV,
        "PYTHON_BIN_X86_64": "python3",
        **EXPECTED_VMVM_ENV,
    }
    if dataset_revision is not None:
        values["EVAL_DATASET_REVISION"] = dataset_revision
    else:
        assert dataset_archive is not None and dataset_content_sha256 is not None
        values.update(
            {
                "EVAL_DATASET_ARCHIVE": str(dataset_archive.path),
                "EVAL_DATASET_ARCHIVE_SHA256": dataset_archive.sha256,
                "EVAL_DATASET_CONTENT_SHA256": dataset_content_sha256,
            }
        )
    return values


def _parse_job_id(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode != 0:
        raise WaveLaunchError("sbatch_submission_failed")
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise WaveLaunchError("sbatch_response_invalid")
    job_id = lines[0].split(";", 1)[0]
    if SLURM_JOB_ID_RE.fullmatch(job_id) is None:
        raise WaveLaunchError("sbatch_response_invalid")
    return job_id


def _require_tmux_launcher(
    environment: Mapping[str, str],
    *,
    runner: RunCommand,
) -> None:
    pane = environment.get("TMUX_PANE")
    if not pane:
        raise WaveLaunchError("submission_requires_tmux_launcher")
    try:
        result = runner(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                pane,
                "#{session_name}:#{window_name}.#{pane_index}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise WaveLaunchError("submission_requires_tmux_launcher") from error
    if result.returncode != 0 or result.stdout.strip() != EXPECTED_TMUX_TARGET:
        raise WaveLaunchError("submission_requires_tmux_launcher")


def _tree_digest(root: Path) -> str:
    try:
        resolved = root.resolve(strict=True)
        paths = sorted(
            resolved.rglob("*"),
            key=lambda item: item.relative_to(resolved).as_posix(),
        )
    except (OSError, RuntimeError) as error:
        raise WaveLaunchError("dataset_tree_unreadable") from error
    if not paths:
        raise WaveLaunchError("dataset_tree_empty")
    entries: list[dict[str, Any]] = []
    for path in paths:
        try:
            before = path.lstat()
            entry: dict[str, Any] = {
                "path": path.relative_to(resolved).as_posix(),
                "mode": stat.S_IMODE(before.st_mode),
            }
            if stat.S_ISDIR(before.st_mode):
                entry["type"] = "directory"
            elif stat.S_ISREG(before.st_mode):
                entry.update(
                    {
                        "type": "file",
                        "size": before.st_size,
                        "sha256": _sha256_path(path),
                    }
                )
            elif stat.S_ISLNK(before.st_mode):
                entry.update({"type": "symlink", "target": os.readlink(path)})
            else:
                raise WaveLaunchError("dataset_tree_entry_unsupported")
            after = path.lstat()
        except WaveLaunchError:
            raise
        except OSError as error:
            raise WaveLaunchError("dataset_tree_unreadable") from error
        if (
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ino,
            before.st_dev,
        ) != (
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
            after.st_dev,
        ):
            raise WaveLaunchError("dataset_tree_changed")
        entries.append(entry)
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(canonical_json(entry))
        digest.update(b"\n")
    try:
        final_paths = {path.relative_to(resolved).as_posix() for path in resolved.rglob("*")}
    except OSError as error:
        raise WaveLaunchError("dataset_tree_unreadable") from error
    if final_paths != {entry["path"] for entry in entries}:
        raise WaveLaunchError("dataset_tree_changed")
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise WaveLaunchError("artifact_unreadable")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except WaveLaunchError:
        raise
    except OSError as error:
        raise WaveLaunchError("artifact_unreadable") from error
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise WaveLaunchError("artifact_changed")
    return digest.hexdigest()


def _archive_tasks_tree_digest(path: Path) -> str:
    entries: dict[str, dict[str, Any]] = {}
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                member_path = PurePosixPath(member.name)
                if not member_path.parts or member_path.parts[0] != "tasks":
                    continue
                if len(member_path.parts) == 1:
                    continue
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise WaveLaunchError("dataset_archive_invalid")
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                if relative in entries:
                    raise WaveLaunchError("dataset_archive_invalid")
                entry: dict[str, Any] = {
                    "path": relative,
                    "mode": member.mode & 0o7777,
                }
                if member.isdir():
                    entry["type"] = "directory"
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise WaveLaunchError("dataset_archive_invalid")
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                    if size != member.size:
                        raise WaveLaunchError("dataset_archive_invalid")
                    entry.update({"type": "file", "size": size, "sha256": digest.hexdigest()})
                elif member.issym():
                    entry.update({"type": "symlink", "target": member.linkname})
                else:
                    raise WaveLaunchError("dataset_archive_invalid")
                entries[relative] = entry
    except WaveLaunchError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise WaveLaunchError("dataset_archive_invalid") from error
    if not entries:
        raise WaveLaunchError("dataset_archive_invalid")
    digest = hashlib.sha256()
    for relative in sorted(entries):
        digest.update(canonical_json(entries[relative]))
        digest.update(b"\n")
    return digest.hexdigest()


def _selected_dataset(
    shards: Sequence[PlannedShard],
) -> tuple[Path, list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    dataset_path: Path | None = None
    for shard in shards:
        artifact = _stable_artifact(
            shard.config,
            shard.config_sha256,
            label="shard_config",
            load_bytes=True,
        )
        assert artifact.raw is not None
        try:
            config = tomllib.loads(artifact.raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise WaveLaunchError("shard_config_invalid") from error
        taskset = config.get("taskset")
        if not isinstance(taskset, dict) or not isinstance(taskset.get("dataset_dir"), str):
            raise WaveLaunchError("dataset_config_invalid")
        try:
            current_path = Path(taskset["dataset_dir"]).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise WaveLaunchError("dataset_unreadable") from error
        if dataset_path is None:
            dataset_path = current_path
        elif current_path != dataset_path:
            raise WaveLaunchError("dataset_config_mismatch")
        parsed.append(config)
    assert dataset_path is not None
    return dataset_path, parsed


def _validate_dataset(
    *,
    shards: Sequence[PlannedShard],
    dataset_revision: str | None,
    dataset_archive: PinnedArtifact | None,
    dataset_content_sha256: str | None,
    runner: RunCommand,
) -> None:
    dataset_path, configs = _selected_dataset(shards)
    tasksets = [config["taskset"] for config in configs]
    if dataset_revision is not None:
        if any(taskset.get("dataset_revision") != dataset_revision for taskset in tasksets):
            raise WaveLaunchError("dataset_revision_config_mismatch")
        observed = _git(
            runner,
            dataset_path,
            "rev-parse",
            "--verify",
            "HEAD",
            label="dataset_revision",
        ).strip()
        status = _git(
            runner,
            dataset_path,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            label="dataset_revision",
        )
        if observed != dataset_revision or status:
            raise WaveLaunchError("dataset_revision_mismatch")
        return
    assert dataset_archive is not None and dataset_content_sha256 is not None
    if any(
        taskset.get("dataset_revision") is not None or taskset.get("use_declared_images") is not True
        for taskset in tasksets
    ):
        raise WaveLaunchError("dataset_archive_config_invalid")
    if _archive_tasks_tree_digest(dataset_archive.path) != dataset_content_sha256:
        raise WaveLaunchError("dataset_archive_content_sha256_mismatch")
    _stable_artifact(
        dataset_archive.path,
        dataset_archive.sha256,
        label="dataset_archive",
    )
    if _tree_digest(dataset_path) != dataset_content_sha256:
        raise WaveLaunchError("dataset_content_sha256_mismatch")


def launch_wave(
    *,
    project_dir: Path,
    project_revision: str,
    plan_path: Path,
    plan_sha256: str,
    shard_indices: Sequence[int],
    output_root: Path,
    deployment_id: str,
    deployment_spec_path: Path,
    deployment_spec_sha256: str,
    readiness_path: Path,
    readiness_sha256: str,
    proxy_info_path: Path,
    proxy_info_sha256: str,
    smoke_checkpoint_path: Path,
    smoke_checkpoint_sha256: str,
    dataset_revision: str | None = None,
    dataset_archive_path: Path | None = None,
    dataset_archive_sha256: str | None = None,
    dataset_content_sha256: str | None = None,
    dry_run: bool = False,
    ambient_env: Mapping[str, str] | None = None,
    command_runner: RunCommand = subprocess.run,
    stop_requested: Callable[[], bool] | None = None,
    submission_timeout_seconds: float = DEFAULT_SUBMISSION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Validate a complete wave before any submission and publish private metadata."""

    environment = os.environ if ambient_env is None else ambient_env
    if (
        (stop_requested is not None and not callable(stop_requested))
        or isinstance(submission_timeout_seconds, bool)
        or not isinstance(submission_timeout_seconds, (int, float))
        or not 1 <= submission_timeout_seconds <= 120
    ):
        raise WaveLaunchError("submission_control_invalid")
    if "RESUME_DIR" in environment:
        raise WaveLaunchError("resume_forbidden")
    if not isinstance(deployment_id, str) or DEPLOYMENT_RE.fullmatch(deployment_id) is None:
        raise WaveLaunchError("deployment_id_invalid")
    if REVISION_RE.fullmatch(project_revision) is None:
        raise WaveLaunchError("project_revision_invalid")
    indices = list(shard_indices)
    if (
        not indices
        or len(indices) > MAX_WAVE_SIZE
        or len(set(indices)) != len(indices)
        or any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in indices)
    ):
        raise WaveLaunchError("shard_indices_invalid")
    plan_artifact = _stable_artifact(plan_path, plan_sha256, label="plan")
    if stat.S_IMODE(plan_artifact.path.stat().st_mode) != 0o600:
        raise WaveLaunchError("plan_not_private")
    try:
        plan, shards = load_plan(plan_artifact.path)
    except ShardWorkflowError as error:
        raise WaveLaunchError("plan_invalid") from error
    _stable_artifact(plan_artifact.path, plan_sha256, label="plan")
    if plan.get("shard_size") != 1 or any(shard.task_count != 1 for shard in shards):
        raise WaveLaunchError("singleton_plan_required")
    if any(index >= len(shards) for index in indices):
        raise WaveLaunchError("shard_indices_invalid")
    selected = tuple(shards[index] for index in indices)
    try:
        project = project_dir.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WaveLaunchError("project_unreadable") from error
    workflow_dir = project / "user/tianhaowu/terminal_bench_vmvm"
    run_eval = workflow_dir / "run_eval.sbatch"
    if not run_eval.is_file():
        raise WaveLaunchError("run_eval_unreadable")
    revisions = validate_clean_project(project, runner=command_runner)
    if revisions.get("prime_rl") != project_revision:
        raise WaveLaunchError("project_revision_mismatch")

    deployment_spec = _stable_artifact(
        deployment_spec_path,
        deployment_spec_sha256,
        label="deployment_spec",
    )
    readiness = _stable_artifact(
        readiness_path,
        readiness_sha256,
        label="readiness_checkpoint",
        load_bytes=True,
    )
    proxy_info = _stable_artifact(proxy_info_path, proxy_info_sha256, label="proxy_info")
    smoke = _stable_artifact(
        smoke_checkpoint_path,
        smoke_checkpoint_sha256,
        label="smoke_checkpoint",
        load_bytes=True,
    )
    generation_sha256 = _validate_generation_bindings(
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        readiness=readiness,
        proxy_info=proxy_info,
        smoke=smoke,
    )
    has_revision = dataset_revision is not None
    has_archive = any(
        value is not None for value in (dataset_archive_path, dataset_archive_sha256, dataset_content_sha256)
    )
    if has_revision == has_archive:
        raise WaveLaunchError("dataset_authority_invalid")
    dataset_archive: PinnedArtifact | None = None
    if has_revision:
        if REVISION_RE.fullmatch(str(dataset_revision)) is None:
            raise WaveLaunchError("dataset_revision_invalid")
    else:
        if (
            dataset_archive_path is None
            or dataset_archive_sha256 is None
            or dataset_content_sha256 is None
            or SHA256_RE.fullmatch(dataset_content_sha256) is None
        ):
            raise WaveLaunchError("dataset_archive_invalid")
        dataset_archive = _stable_artifact(
            dataset_archive_path,
            dataset_archive_sha256,
            label="dataset_archive",
        )

    _validate_dataset(
        shards=selected,
        dataset_revision=dataset_revision,
        dataset_archive=dataset_archive,
        dataset_content_sha256=dataset_content_sha256,
        runner=command_runner,
    )

    if output_root.exists() or output_root.is_symlink():
        raise WaveLaunchError("output_root_exists")
    try:
        output = output_root.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise WaveLaunchError("output_root_invalid") from error
    if output.exists() or output.is_symlink():
        raise WaveLaunchError("output_root_exists")
    try:
        output.relative_to(project)
    except ValueError:
        pass
    else:
        raise WaveLaunchError("output_root_inside_project")
    if not dry_run:
        _require_tmux_launcher(environment, runner=command_runner)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.mkdir(mode=0o700)
    except FileExistsError as error:
        raise WaveLaunchError("output_root_exists") from error
    except OSError as error:
        raise WaveLaunchError("output_root_invalid") from error
    os.chmod(output, 0o700)
    jobs: list[dict[str, Any]] = []
    for shard in selected:
        output_dir = output / f"shard-{shard.index:03d}-attempt-001"
        env_path = output / f"shard-{shard.index:03d}.env"
        environment_values = _job_environment(
            project_dir=project,
            project_revision=project_revision,
            shard=shard,
            output_dir=output_dir,
            deployment_id=deployment_id,
            deployment_spec=deployment_spec,
            readiness=readiness,
            proxy_info=proxy_info,
            smoke=smoke,
            dataset_revision=dataset_revision,
            dataset_archive=dataset_archive,
            dataset_content_sha256=dataset_content_sha256,
        )
        encoded_environment = _encode_environment(environment_values)
        _private_write(env_path, encoded_environment)
        jobs.append(
            {
                "shard_index": shard.index,
                "task_count": shard.task_count,
                "config_sha256": shard.config_sha256,
                "task_manifest_sha256": shard.task_manifest_sha256,
                "environment": {
                    "path": str(env_path),
                    "sha256": _sha256_bytes(encoded_environment),
                },
                "output_dir": str(output_dir),
                "submission_started_at": None,
                "submission_token": None,
                "slurm_job_id": None,
            }
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "state": "validated" if dry_run else "submitting",
        "dry_run": dry_run,
        "plan": {
            "path": str(plan_artifact.path),
            "sha256": plan_artifact.sha256,
            "plan_sha256": plan["plan_sha256"],
        },
        "project": {"path": str(project), "revisions": revisions},
        "deployment": {
            "id": deployment_id,
            "spec_sha256": deployment_spec.sha256,
            "readiness_checkpoint_sha256": readiness.sha256,
            "proxy_info_sha256": proxy_info.sha256,
            "smoke_checkpoint_sha256": smoke.sha256,
            "route_generation_sha256": generation_sha256,
            "model": EXPECTED_MODEL,
        },
        "dataset": (
            {"kind": "git_revision", "revision": dataset_revision}
            if dataset_revision is not None
            else {
                "kind": "archive",
                "archive_sha256": dataset_archive.sha256,
                "content_sha256": dataset_content_sha256,
            },
        ),
        "vmvm_environment": EXPECTED_VMVM_ENV,
        "wave_size": len(jobs),
        "jobs": jobs,
    }
    wave_sha256 = _replace_private_json(output / "wave.json", body)
    directory_fd = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

    if dry_run:
        return {**body, "wave_sha256": wave_sha256}

    try:
        for shard, job in zip(selected, jobs, strict=True):
            if stop_requested is not None and stop_requested():
                raise WaveSubmissionInterrupted("submission_interrupted")
            if validate_clean_project(project, runner=command_runner) != revisions:
                raise WaveLaunchError("project_changed")
            for path, digest, label in (
                (plan_artifact.path, plan_artifact.sha256, "plan"),
                (shard.config, shard.config_sha256, "shard_config"),
                (shard.task_manifest, shard.task_manifest_sha256, "shard_manifest"),
                (deployment_spec.path, deployment_spec.sha256, "deployment_spec"),
                (readiness.path, readiness.sha256, "readiness_checkpoint"),
                (proxy_info.path, proxy_info.sha256, "proxy_info"),
                (smoke.path, smoke.sha256, "smoke_checkpoint"),
            ):
                _stable_artifact(path, digest, label=label)
            if dataset_archive is not None:
                _stable_artifact(
                    dataset_archive.path,
                    dataset_archive.sha256,
                    label="dataset_archive",
                )
            current_readiness = _stable_artifact(
                readiness.path,
                readiness.sha256,
                label="readiness_checkpoint",
                load_bytes=True,
            )
            current_smoke = _stable_artifact(
                smoke.path,
                smoke.sha256,
                label="smoke_checkpoint",
                load_bytes=True,
            )
            _validate_generation_bindings(
                deployment_id=deployment_id,
                deployment_spec=deployment_spec,
                readiness=current_readiness,
                proxy_info=proxy_info,
                smoke=current_smoke,
            )
            _validate_dataset(
                shards=(shard,),
                dataset_revision=dataset_revision,
                dataset_archive=dataset_archive,
                dataset_content_sha256=dataset_content_sha256,
                runner=command_runner,
            )
            environment_path = Path(job["environment"]["path"])
            submission_token = secrets.token_hex(8)
            job["submission_token"] = submission_token
            job["submission_started_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            body["state"] = "submitting"
            _replace_private_json(output / "wave.json", body)
            if stop_requested is not None and stop_requested():
                job["submission_token"] = None
                job["submission_started_at"] = None
                raise WaveSubmissionInterrupted("submission_interrupted")
            _stable_artifact(
                environment_path,
                job["environment"]["sha256"],
                label="job_environment",
            )
            result = command_runner(
                [
                    DEFAULT_SBATCH,
                    "--parsable",
                    f"--job-name=tb4-shard-{job['shard_index']:03d}-{submission_token}",
                    f"--export-file={environment_path}",
                    str(run_eval),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=project,
                env={},
                timeout=submission_timeout_seconds,
            )
            try:
                job["slurm_job_id"] = _parse_job_id(result)
            except WaveLaunchError as error:
                if result.returncode == 0:
                    raise WaveSubmissionOutcomeUnknown("sbatch_submission_outcome_unknown") from error
                raise
            _replace_private_json(output / "wave.json", body)
    except WaveSubmissionInterrupted:
        body["state"] = "submission_interrupted"
        _replace_private_json(output / "wave.json", body)
        raise
    except subprocess.TimeoutExpired as error:
        # The persisted random submission token permits exact scheduler lookup;
        # do not label this as a known failure or submit it again.
        body["state"] = "submitting"
        _replace_private_json(output / "wave.json", body)
        raise WaveSubmissionOutcomeUnknown("sbatch_submission_outcome_unknown") from error
    except (OSError, WaveLaunchError) as error:
        body["state"] = "partial_submission_failed"
        _replace_private_json(output / "wave.json", body)
        raise WaveLaunchError("wave_submission_incomplete") from error
    body["state"] = "submitted"
    wave_sha256 = _replace_private_json(output / "wave.json", body)
    return {**body, "wave_sha256": wave_sha256}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--project-revision", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--shard-index", type=int, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--deployment-spec", type=Path, required=True)
    parser.add_argument("--deployment-spec-sha256", required=True)
    parser.add_argument("--readiness-checkpoint", type=Path, required=True)
    parser.add_argument("--readiness-checkpoint-sha256", required=True)
    parser.add_argument("--proxy-info", type=Path, required=True)
    parser.add_argument("--proxy-info-sha256", required=True)
    parser.add_argument("--smoke-checkpoint", type=Path, required=True)
    parser.add_argument("--smoke-checkpoint-sha256", required=True)
    dataset = parser.add_mutually_exclusive_group(required=True)
    dataset.add_argument("--dataset-revision")
    dataset.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--dataset-archive-sha256")
    parser.add_argument("--dataset-content-sha256")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        wave = launch_wave(
            project_dir=args.project_dir,
            project_revision=args.project_revision,
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            shard_indices=args.shard_index,
            output_root=args.output_root,
            deployment_id=args.deployment_id,
            deployment_spec_path=args.deployment_spec,
            deployment_spec_sha256=args.deployment_spec_sha256,
            readiness_path=args.readiness_checkpoint,
            readiness_sha256=args.readiness_checkpoint_sha256,
            proxy_info_path=args.proxy_info,
            proxy_info_sha256=args.proxy_info_sha256,
            smoke_checkpoint_path=args.smoke_checkpoint,
            smoke_checkpoint_sha256=args.smoke_checkpoint_sha256,
            dataset_revision=args.dataset_revision,
            dataset_archive_path=args.dataset_archive,
            dataset_archive_sha256=args.dataset_archive_sha256,
            dataset_content_sha256=args.dataset_content_sha256,
            dry_run=args.dry_run,
        )
    except (OSError, WaveLaunchError) as error:
        print(f"tb4_shard_wave_error:{error}", file=os.sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "state": wave["state"],
                "wave_size": wave["wave_size"],
                "wave_sha256": wave["wave_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
