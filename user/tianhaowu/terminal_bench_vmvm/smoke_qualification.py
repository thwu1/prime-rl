#!/usr/bin/env python3
"""Strict validation for Kimi smoke certificates and generation bridges.

Schema 1 is the original smoke certificate and is valid only for its exact
serving generation.  Schema 2 is a separate, write-once qualification bridge:
it never changes or relabels schema 1 and permits only a backend-worker route
generation change under the exact same deployment, coordinator, proxy,
deployment specification, proxy policy, model, and evaluator contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

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

SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
BRIDGE_SCHEMA_VERSION = 2
BRIDGE_KIND = "cross_worker_generation_smoke_qualification"
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": "/chat/completions",
    "request_model": "Kimi-K3",
    "response_model": "Kimi-K3",
    "request_reasoning_effort": "max",
    "request_chat_template_kwargs": {
        "enable_thinking": True,
        "preserve_thinking": True,
    },
}
EXPECTED_DENYLIST = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
SMOKE_ARTIFACT_PATHS = {
    "results": Path("results.jsonl"),
    "eval_run_identity": Path("eval_run_identity.json"),
    "eval_invocations": Path("eval_invocations.jsonl"),
    "route_guard_success": Path("route_guard_success.json"),
    "config": Path("config.toml"),
    "inputs_manifest": Path("inputs/manifest.json"),
    "provenance": Path("provenance.txt"),
}


class SmokeQualificationError(ValueError):
    """A smoke artifact cannot safely qualify the requested generation."""


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str
    raw: bytes | None = None

    @property
    def record(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256}


@dataclass(frozen=True)
class QualificationEvidence:
    schema_version: int
    qualification: Artifact
    source_smoke: Artifact
    source_generation: dict[str, Any]
    target_generation: dict[str, Any]
    evaluator_evidence: dict[str, Any]


IdentityLoader = Callable[..., dict[str, Any]]


def _proxy_policy_helpers() -> tuple[Callable[..., Any], Callable[..., Any]]:
    try:
        from deployment_proxy_policy import (
            revalidate_deployment_proxy_policy,
            validate_proxy_policy_binding,
        )
    except ImportError as error:
        raise SmokeQualificationError("proxy_policy_runtime_unavailable") from error
    return validate_proxy_policy_binding, revalidate_deployment_proxy_policy


def _guard_helpers() -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    try:
        from guard_success_receipt import (
            load_guard_success_receipt,
            validate_eval_invocations,
            validate_guard_success_linkage,
        )
    except ImportError as error:
        raise SmokeQualificationError("guard_receipt_runtime_unavailable") from error
    return (
        load_guard_success_receipt,
        validate_eval_invocations,
        validate_guard_success_linkage,
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _same_json(left: Any, right: Any) -> bool:
    try:
        return canonical_json(left) == canonical_json(right)
    except (TypeError, ValueError):
        return False


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SmokeQualificationError(f"{label}_duplicate_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise SmokeQualificationError(f"{label}_non_finite")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except SmokeQualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise SmokeQualificationError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise SmokeQualificationError(f"{label}_invalid")
    return value


def load_artifact(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
    load_bytes: bool = False,
) -> Artifact:
    if not isinstance(expected_sha256, str) or SHA256_RE.fullmatch(expected_sha256) is None:
        raise SmokeQualificationError(f"{label}_sha256_invalid")
    try:
        if path.is_symlink():
            raise SmokeQualificationError(f"{label}_unreadable")
        resolved = path.resolve(strict=True)
        if str(path) != str(resolved):
            raise SmokeQualificationError(f"{label}_path_not_canonical")
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise SmokeQualificationError(f"{label}_unreadable")
        digest = hashlib.sha256()
        chunks: list[bytes] | None = [] if load_bytes else None
        loaded = 0
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if chunks is not None:
                    loaded += len(chunk)
                    if loaded > MAX_ARTIFACT_BYTES:
                        raise SmokeQualificationError(f"{label}_too_large")
                    chunks.append(chunk)
        after = resolved.stat(follow_symlinks=False)
    except SmokeQualificationError:
        raise
    except (OSError, RuntimeError) as error:
        raise SmokeQualificationError(f"{label}_unreadable") from error
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
        raise SmokeQualificationError(f"{label}_changed")
    if digest.hexdigest() != expected_sha256:
        raise SmokeQualificationError(f"{label}_sha256_mismatch")
    return Artifact(
        path=resolved,
        sha256=expected_sha256,
        raw=b"".join(chunks) if chunks is not None else None,
    )


def artifact_from_record(
    value: Any,
    *,
    label: str,
    expected: Artifact | None = None,
    load_bytes: bool = False,
) -> Artifact:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not Path(value["path"]).is_absolute()
        or not isinstance(value.get("sha256"), str)
    ):
        raise SmokeQualificationError(f"{label}_invalid")
    artifact = load_artifact(
        Path(value["path"]),
        value["sha256"],
        label=label,
        load_bytes=load_bytes,
    )
    if expected is not None and artifact.record != expected.record:
        raise SmokeQualificationError(f"{label}_mismatch")
    return artifact


def load_json_artifact(artifact: Artifact, *, label: str) -> dict[str, Any]:
    raw = artifact.raw
    if raw is None:
        artifact = load_artifact(
            artifact.path,
            artifact.sha256,
            label=label,
            load_bytes=True,
        )
        raw = artifact.raw
    assert raw is not None
    return _strict_object(raw, label=label)


def _default_identity_loader(path: Path, *, verify_references: bool) -> dict[str, Any]:
    # Delayed import avoids a cycle: eval_run_identity uses this validator.
    from eval_run_identity import load_eval_run_identity

    return load_eval_run_identity(path, verify_references=verify_references)


def _validate_readiness(
    readiness: Artifact,
    *,
    deployment_id: str,
    deployment_spec: Artifact,
    endpoint: dict[str, Any],
    model: str,
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
    revalidate_live_proxy_policy: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = load_json_artifact(readiness, label="readiness_checkpoint")
    validate_proxy_policy_binding, revalidate_deployment_proxy_policy = _proxy_policy_helpers()
    from deployment_proxy_policy import request_timeout_for_model

    expected_request_timeout = request_timeout_for_model(model)
    try:
        readiness_endpoint = validate_endpoint_binding(payload.get("endpoint"))
        generation = validate_readiness_route_generation(
            payload,
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec.sha256,
        )
        proxy_policy = validate_proxy_policy_binding(
            payload.get("proxy_policy"),
            expected_request_timeout=expected_request_timeout,
        )
        if (deployment_spec_snapshot is None) != (proxy_policy_snapshot is None):
            raise ValueError("deployment_snapshot_incomplete")
        if not revalidate_live_proxy_policy and deployment_spec_snapshot is not None:
            raise ValueError("historical_readiness_snapshot_invalid")
        if not revalidate_live_proxy_policy:
            pass
        elif deployment_spec_snapshot is None:
            revalidate_deployment_proxy_policy(
                deployment_spec.path,
                expected_spec_sha256=deployment_spec.sha256,
                expected_binding=proxy_policy,
                expected_request_timeout=expected_request_timeout,
            )
        else:
            from deployment_proxy_policy import validate_deployment_proxy_policy_snapshot

            assert proxy_policy_snapshot is not None
            validate_deployment_proxy_policy_snapshot(
                deployment_spec_snapshot,
                proxy_policy_snapshot,
                expected_spec_sha256=deployment_spec.sha256,
                expected_binding=proxy_policy,
            )
    except (
        EndpointBindingError,
        RouteGenerationError,
        ValueError,
    ) as error:
        raise SmokeQualificationError("readiness_checkpoint_invalid") from error
    probe = payload.get("probe")
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or payload.get("state") != "passed"
        or payload.get("deployment") != deployment_id
        or payload.get("observed_spec_sha256") != deployment_spec.sha256
        or not isinstance(probe, dict)
        or probe.get("ok") is not True
        or not _same_json(readiness_endpoint, endpoint)
    ):
        raise SmokeQualificationError("readiness_checkpoint_not_passed")
    return generation, proxy_policy


def validate_readiness(
    readiness: Artifact,
    *,
    deployment_id: str,
    deployment_spec: Artifact,
    endpoint: dict[str, Any],
    model: str,
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a current readiness checkpoint and its live proxy policy."""

    return _validate_readiness(
        readiness,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        endpoint=endpoint,
        model=model,
        deployment_spec_snapshot=deployment_spec_snapshot,
        proxy_policy_snapshot=proxy_policy_snapshot,
        revalidate_live_proxy_policy=True,
    )


def validate_historical_readiness(
    readiness: Artifact,
    *,
    deployment_id: str,
    deployment_spec: Artifact,
    endpoint: dict[str, Any],
    model: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate readiness embedded in an immutable, hash-linked smoke.

    A worker rotation necessarily rewrites the live generated proxy config.
    This narrowly scoped validator verifies the historical binding and every
    other readiness invariant without comparing that old whole-file digest to
    the current mutable file. Callers must first obtain ``readiness`` from the
    immutable source smoke's authenticated artifact graph.
    """

    return _validate_readiness(
        readiness,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        endpoint=endpoint,
        model=model,
        revalidate_live_proxy_policy=False,
    )


def _expected_model_contract(model: str) -> dict[str, Any]:
    return {
        **EXPECTED_MODEL_IO_CONTRACT,
        "request_model": model,
        "response_model": model,
    }


def _tool_contract(config: Mapping[str, Any]) -> dict[str, Any]:
    harness = config.get("harness")
    client = config.get("client")
    sampling = config.get("sampling")
    if not all(isinstance(value, dict) for value in (harness, client, sampling)):
        raise SmokeQualificationError("smoke_evaluator_contract_invalid")
    assert isinstance(harness, dict) and isinstance(client, dict) and isinstance(sampling, dict)
    overrides = harness.get("config_overrides")
    runtime = harness.get("runtime")
    if (
        harness.get("id") != "mini-swe-agent"
        or harness.get("version") != "2.2.8"
        or harness.get("config_file") != "mini"
        or not isinstance(overrides, list)
        or any(not isinstance(item, str) for item in overrides)
        or len(set(overrides)) != len(overrides)
        or "environment.environment_class=local" not in overrides
        or "model.model_kwargs.drop_params=true" not in overrides
        or [item for item in overrides if item.startswith("model.model_kwargs.timeout=")]
        != ["model.model_kwargs.timeout=43200"]
        or "model.model_kwargs.parallel_tool_calls=true" not in overrides
        or not isinstance(runtime, dict)
        or runtime.get("type") != "vmvm"
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("api_key_var") != "OPENAI_API_KEY"
        or set(client.get("outbound_body_denylist") or []) != EXPECTED_DENYLIST
        or len(client.get("outbound_body_denylist") or []) != len(EXPECTED_DENYLIST)
        or sampling.get("reasoning_effort") != "max"
        or not _same_json(
            sampling.get("chat_template_kwargs"),
            {"enable_thinking": True, "preserve_thinking": True},
        )
    ):
        raise SmokeQualificationError("smoke_evaluator_contract_invalid")
    stable_overrides = sorted(
        item
        for item in overrides
        if not item.startswith("agent.step_limit=") and not item.startswith("environment.timeout=")
    )
    taskset = config.get("taskset")
    retries = config.get("retries")
    harness_environment = harness.get("env")
    if not isinstance(taskset, dict) or not isinstance(retries, dict) or not isinstance(harness_environment, dict):
        raise SmokeQualificationError("smoke_evaluator_contract_invalid")
    normalized = copy.deepcopy(dict(config))
    for key in (
        "output_dir",
        "num_tasks",
        "max_concurrent",
        "multiplex",
        "max_turns",
    ):
        normalized.pop(key, None)
    normalized_client = normalized.get("client")
    normalized_taskset = normalized.get("taskset")
    normalized_harness = normalized.get("harness")
    normalized_timeout = normalized.get("timeout")
    if not all(isinstance(value, dict) for value in (normalized_client, normalized_taskset, normalized_harness)):
        raise SmokeQualificationError("smoke_evaluator_contract_invalid")
    for key in ("max_connections", "max_keepalive_connections"):
        normalized_client.pop(key, None)
    for key in (
        "task_file",
        "task_file_sha256",
        "image_manifest",
        "image_manifest_sha256",
    ):
        normalized_taskset.pop(key, None)
    normalized_harness["config_overrides"] = stable_overrides
    normalized_runtime = normalized_harness.get("runtime")
    if not isinstance(normalized_runtime, dict):
        raise SmokeQualificationError("smoke_evaluator_contract_invalid")
    normalized_runtime.pop("session_timeout", None)
    if normalized_timeout is not None:
        if not isinstance(normalized_timeout, dict):
            raise SmokeQualificationError("smoke_evaluator_contract_invalid")
        normalized_timeout.pop("rollout", None)
    return {
        "schema_version": 1,
        "harness_id": harness["id"],
        "harness_version": harness["version"],
        "harness_config_file": harness["config_file"],
        "runtime_type": runtime["type"],
        "client_type": client["type"],
        "capture_model_io": True,
        "outbound_body_denylist": sorted(EXPECTED_DENYLIST),
        "parallel_tool_calls": True,
        "reasoning_effort": "max",
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "normalized_config_sha256": sha256_bytes(canonical_json(normalized)),
    }


def _evaluator_source_evidence(source: Mapping[str, Any]) -> dict[str, Any]:
    project_root = source.get("project_root")
    if not isinstance(project_root, str) or not Path(project_root).is_absolute():
        raise SmokeQualificationError("smoke_evaluator_source_invalid")
    try:
        root = Path(project_root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SmokeQualificationError("smoke_evaluator_source_invalid") from error
    if str(root) != project_root or not root.is_dir():
        raise SmokeQualificationError("smoke_evaluator_source_invalid")
    workflow = root / "user/tianhaowu/terminal_bench_vmvm"
    roots = (
        workflow / "terminal_bench_vmvm",
        root / "environments/vmvm_tb_v2/vmvm_tb_v2",
    )
    try:
        paths = [workflow / "run_eval.sbatch"]
        for source_root in roots:
            if not source_root.is_dir():
                raise SmokeQualificationError("smoke_evaluator_source_invalid")
            paths.extend(source_root.rglob("*.py"))
        paths = sorted(paths, key=lambda path: path.relative_to(root).as_posix())
    except (OSError, RuntimeError, ValueError) as error:
        raise SmokeQualificationError("smoke_evaluator_source_invalid") from error
    if not paths or len(set(paths)) != len(paths):
        raise SmokeQualificationError("smoke_evaluator_source_invalid")
    digest = hashlib.sha256()
    for path in paths:
        try:
            if path.is_symlink():
                raise SmokeQualificationError("smoke_evaluator_source_invalid")
            before = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise SmokeQualificationError("smoke_evaluator_source_invalid")
            raw = path.read_bytes()
            after = path.stat(follow_symlinks=False)
        except SmokeQualificationError:
            raise
        except OSError as error:
            raise SmokeQualificationError("smoke_evaluator_source_invalid") from error
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
            raise SmokeQualificationError("smoke_evaluator_source_changed")
        relative = path.relative_to(root).as_posix()
        digest.update(f"{hashlib.sha256(raw).hexdigest()}  {relative}\n".encode())
    return {"schema_version": 1, "files": len(paths), "sha256": digest.hexdigest()}


def _evaluator_evidence(
    identity: dict[str, Any],
    policy: dict[str, Any],
    config_artifact: Artifact,
    *,
    model: str,
) -> dict[str, Any]:
    raw = config_artifact.raw
    if raw is None:
        config_artifact = load_artifact(
            config_artifact.path,
            config_artifact.sha256,
            label="smoke_config",
            load_bytes=True,
        )
        raw = config_artifact.raw
    assert raw is not None
    try:
        config = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SmokeQualificationError("smoke_evaluator_config_invalid") from error
    source = identity.get("source")
    config_identity = identity.get("config")
    contract = identity.get("contract")
    model_io_contract = policy.get("model_io_contract")
    if (
        not isinstance(source, dict)
        or not isinstance(config_identity, dict)
        or set(config_identity) != {"source", "resolved"}
        or config_identity.get("resolved") != config_artifact.record
        or not isinstance(contract, dict)
        or contract.get("model") != model
        or contract.get("reasoning_effort") != "max"
        or not _same_json(
            contract.get("thinking"),
            {"enable_thinking": True, "preserve_thinking": True},
        )
        or contract.get("capture_model_io") is not True
        or set(contract.get("outbound_body_denylist") or []) != EXPECTED_DENYLIST
        or not _same_json(model_io_contract, _expected_model_contract(model))
        or config.get("model") != model
    ):
        raise SmokeQualificationError("smoke_evaluator_contract_invalid")
    source_config = artifact_from_record(
        config_identity.get("source"),
        label="smoke_source_config",
    )
    return {
        "source": source,
        "evaluator_source": _evaluator_source_evidence(source),
        "source_config": source_config.record,
        "resolved_config": config_artifact.record,
        "identity_contract": contract,
        "model_io_contract": model_io_contract,
        "tool_contract": _tool_contract(config),
    }


def validate_target_evaluator_compatibility(
    identity: Mapping[str, Any],
    evaluator_evidence: Mapping[str, Any],
) -> None:
    """Require the target run to use the source smoke's evaluator contract."""

    source = identity.get("source")
    config = identity.get("config")
    contract = identity.get("contract")
    if (
        identity.get("role") != "tb4"
        or not isinstance(source, dict)
        or not isinstance(config, dict)
        or set(config) != {"source", "resolved"}
        or not isinstance(contract, dict)
        or not isinstance(evaluator_evidence, dict)
        or set(evaluator_evidence)
        != {
            "source",
            "evaluator_source",
            "source_config",
            "resolved_config",
            "identity_contract",
            "model_io_contract",
            "tool_contract",
        }
    ):
        raise SmokeQualificationError("target_evaluator_contract_invalid")
    certified_source = evaluator_evidence.get("source")
    if not isinstance(certified_source, dict):
        raise SmokeQualificationError("target_evaluator_source_invalid")
    for key in (
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
        "vmvm_tb_v2_sha256",
    ):
        if source.get(key) != certified_source.get(key):
            raise SmokeQualificationError("target_evaluator_source_mismatch")
    if (
        not _same_json(
            _evaluator_source_evidence(source),
            evaluator_evidence.get("evaluator_source"),
        )
        or not _same_json(contract, evaluator_evidence.get("identity_contract"))
        or not _same_json(
            evaluator_evidence.get("model_io_contract"),
            _expected_model_contract(str(contract.get("model"))),
        )
    ):
        raise SmokeQualificationError("target_evaluator_contract_mismatch")
    resolved = artifact_from_record(
        config.get("resolved"),
        label="target_resolved_config",
        load_bytes=True,
    )
    assert resolved.raw is not None
    try:
        parsed = tomllib.loads(resolved.raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SmokeQualificationError("target_evaluator_config_invalid") from error
    if not _same_json(_tool_contract(parsed), evaluator_evidence.get("tool_contract")):
        raise SmokeQualificationError("target_evaluator_config_mismatch")


def _load_source_identity(
    artifact: Artifact,
    *,
    identity_loader: IdentityLoader,
) -> tuple[dict[str, Any], str]:
    # Reject duplicate keys before delegating to the full identity verifier.
    load_json_artifact(artifact, label="smoke_eval_run_identity")
    try:
        envelope = identity_loader(artifact.path, verify_references=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise SmokeQualificationError("smoke_eval_run_identity_invalid") from error
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"schema_version", "eval_run_identity_sha256", "identity"}
        or type(envelope.get("schema_version")) is not int
        or envelope["schema_version"] != 1
        or not isinstance(envelope.get("eval_run_identity_sha256"), str)
        or SHA256_RE.fullmatch(envelope["eval_run_identity_sha256"]) is None
        or not isinstance(envelope.get("identity"), dict)
        or envelope["eval_run_identity_sha256"] != sha256_bytes(canonical_json(envelope["identity"]))
    ):
        raise SmokeQualificationError("smoke_eval_run_identity_invalid")
    return envelope["identity"], envelope["eval_run_identity_sha256"]


def validate_v1_smoke(
    smoke: Artifact,
    *,
    deployment_id: str,
    deployment_spec: Artifact,
    readiness: Artifact,
    endpoint: dict[str, Any],
    generation: dict[str, Any],
    proxy_policy: dict[str, Any],
    model: str,
    identity_loader: IdentityLoader | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fully validate one immutable schema-1 smoke certificate."""

    if stat.S_IMODE(smoke.path.stat().st_mode) != 0o444:
        raise SmokeQualificationError("smoke_checkpoint_not_immutable")
    loader = identity_loader or _default_identity_loader
    payload = load_json_artifact(smoke, label="smoke_checkpoint")
    body = {key: value for key, value in payload.items() if key != "smoke_checkpoint_sha256"}
    allowed = {
        "schema_version",
        "state",
        "ok",
        "eval_run_identity_sha256",
        "deployment_id",
        "deployment_spec_sha256",
        "readiness_checkpoint_sha256",
        "deployment",
        "endpoint",
        "serving_route_generation",
        "proxy_policy",
        "qualified_execution",
        "audit_policy",
        "counts",
        "artifacts",
        "smoke_checkpoint_sha256",
    }
    if "observed_concurrency" in payload:
        allowed.add("observed_concurrency")
    deployment = payload.get("deployment")
    policy = payload.get("audit_policy")
    counts = payload.get("counts")
    artifacts = payload.get("artifacts")
    validate_proxy_policy_binding, _ = _proxy_policy_helpers()
    try:
        smoke_endpoint = validate_endpoint_binding(payload.get("endpoint"))
        smoke_generation = validate_route_generation(payload.get("serving_route_generation"))
        smoke_policy = validate_proxy_policy_binding(payload.get("proxy_policy"))
    except (
        EndpointBindingError,
        RouteGenerationError,
        ValueError,
    ) as error:
        raise SmokeQualificationError("smoke_checkpoint_invalid") from error
    if (
        set(payload) != allowed
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or payload.get("state") != "passed"
        or payload.get("ok") is not True
        or payload.get("smoke_checkpoint_sha256") != sha256_bytes(canonical_json(body))
        or payload.get("deployment_id") != deployment_id
        or payload.get("deployment_spec_sha256") != deployment_spec.sha256
        or payload.get("readiness_checkpoint_sha256") != readiness.sha256
        or not _same_json(
            deployment,
            {"id": deployment_id, "spec_sha256": deployment_spec.sha256},
        )
        or not _same_json(smoke_endpoint, endpoint)
        or not _same_json(smoke_generation, generation)
        or not _same_json(smoke_policy, proxy_policy)
        or not isinstance(policy, dict)
        or set(policy)
        != {
            "expected_traces",
            "rollouts_per_task",
            "require_reasoning",
            "require_model_io",
            "model_io_contract",
            "require_token_data",
            "require_logprobs",
            "max_sequence_tokens",
        }
        or type(policy.get("rollouts_per_task")) is not int
        or policy["rollouts_per_task"] != 1
        or policy.get("require_reasoning") is not True
        or policy.get("require_model_io") is not True
        or not _same_json(
            policy.get("model_io_contract"),
            _expected_model_contract(model),
        )
        or policy.get("require_token_data") is not False
        or policy.get("require_logprobs") is not False
        or type(policy.get("max_sequence_tokens")) is not int
        or policy["max_sequence_tokens"] != 262_144
        or not isinstance(counts, dict)
        or set(counts)
        != {
            "traces",
            "tasks",
            "sampled_tokens",
            "model_io_turns",
            "trace_failures",
            "global_problems",
        }
        or type(counts.get("trace_failures")) is not int
        or counts["trace_failures"] != 0
        or type(counts.get("global_problems")) is not int
        or counts["global_problems"] != 0
        or type(counts.get("sampled_tokens")) is not int
        or counts["sampled_tokens"] < 1
        or not isinstance(artifacts, dict)
    ):
        raise SmokeQualificationError("smoke_checkpoint_not_passed")
    expected_traces = policy.get("expected_traces")
    if (
        type(expected_traces) is not int
        or expected_traces < 1
        or type(counts.get("traces")) is not int
        or counts.get("traces") != expected_traces
        or type(counts.get("tasks")) is not int
        or counts.get("tasks") != expected_traces
        or type(counts.get("model_io_turns")) is not int
        or counts["model_io_turns"] < expected_traces
    ):
        raise SmokeQualificationError("smoke_checkpoint_counts_invalid")
    expected_artifact_names = {
        *SMOKE_ARTIFACT_PATHS,
        "readiness_checkpoint",
        "proxy_info",
    }
    if "concurrency_telemetry" in artifacts:
        expected_artifact_names.add("concurrency_telemetry")
    if set(artifacts) != expected_artifact_names:
        raise SmokeQualificationError("smoke_checkpoint_artifacts_invalid")
    artifact_records: dict[str, Artifact] = {}
    for name in sorted(artifacts):
        artifact_records[name] = artifact_from_record(
            artifacts[name],
            label=f"smoke_{name}",
            load_bytes=name
            in {
                "eval_run_identity",
                "eval_invocations",
                "route_guard_success",
                "config",
                "inputs_manifest",
                "provenance",
                "concurrency_telemetry",
            },
        )
    if artifact_records["readiness_checkpoint"].record != readiness.record:
        raise SmokeQualificationError("smoke_readiness_mismatch")
    if artifact_records["proxy_info"].record != endpoint["proxy_info"]:
        raise SmokeQualificationError("smoke_proxy_info_mismatch")
    run_dir = artifact_records["eval_run_identity"].path.parent
    if smoke.path != run_dir / "smoke_checkpoint.json":
        raise SmokeQualificationError("smoke_artifact_path_mismatch")
    for name, relative in SMOKE_ARTIFACT_PATHS.items():
        if artifact_records[name].path != run_dir / relative:
            raise SmokeQualificationError("smoke_artifact_path_mismatch")
    if (
        "concurrency_telemetry" in artifact_records
        and artifact_records["concurrency_telemetry"].path != run_dir / "concurrency_telemetry.json"
    ):
        raise SmokeQualificationError("smoke_artifact_path_mismatch")
    manifest = load_json_artifact(
        artifact_records["inputs_manifest"],
        label="smoke_inputs_manifest",
    )
    if not {"config", "task_file"}.issubset(manifest) or set(manifest) - {"config", "task_file", "image_manifest"}:
        raise SmokeQualificationError("smoke_inputs_manifest_invalid")

    identity, identity_sha256 = _load_source_identity(
        artifact_records["eval_run_identity"],
        identity_loader=loader,
    )
    identity_deployment = identity.get("deployment")
    identity_inputs = identity.get("inputs")
    if (
        payload.get("eval_run_identity_sha256") != identity_sha256
        or identity.get("role") != "smoke"
        or not isinstance(identity_deployment, dict)
        or identity_deployment.get("id") != deployment_id
        or not _same_json(identity_deployment.get("endpoint"), endpoint)
        or not _same_json(
            identity_deployment.get("serving_route_generation"),
            generation,
        )
        or not _same_json(identity_deployment.get("proxy_policy"), proxy_policy)
        or identity_deployment.get("spec") != deployment_spec.record
        or identity_deployment.get("readiness_checkpoint") != readiness.record
        or identity_deployment.get("smoke_checkpoint") is not None
        or not isinstance(identity_inputs, dict)
        or identity_inputs.get("task_file", {}).get("count") != expected_traces
        or identity.get("config", {}).get("resolved") != artifact_records["config"].record
        or identity_inputs.get("manifest") != artifact_records["inputs_manifest"].record
    ):
        raise SmokeQualificationError("smoke_checkpoint_identity_mismatch")

    task_record = identity_inputs.get("task_file")
    if (
        not isinstance(task_record, dict)
        or set(task_record) != {"path", "sha256", "count"}
        or task_record.get("count") != expected_traces
    ):
        raise SmokeQualificationError("smoke_task_file_invalid")
    task_file = load_artifact(
        Path(str(task_record.get("path"))),
        str(task_record.get("sha256")),
        label="smoke_task_file",
    )
    try:
        from audit_traces import (
            KIMI_K3_MAX_MODEL_IO_CONTRACT,
            _iter_traces,
            _read_expected_slugs,
            _summarize_traces,
        )
    except ImportError as error:
        raise SmokeQualificationError("smoke_trace_audit_runtime_unavailable") from error
    try:
        expected_tasks = _read_expected_slugs(task_file.path)
        summary, failed = _summarize_traces(
            _iter_traces(artifact_records["results"].path),
            expected_slugs=expected_tasks,
            expected_count=expected_traces,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
            max_sequence_tokens=262_144,
        )
    except (OSError, ValueError) as error:
        raise SmokeQualificationError("smoke_trace_audit_invalid") from error
    if (
        failed
        or summary.get("traces") != counts["traces"]
        or summary.get("tasks") != counts["tasks"]
        or summary.get("sampled_tokens") != counts["sampled_tokens"]
        or summary.get("model_io_turns") != counts["model_io_turns"]
        or summary.get("trace_failures") != 0
        or summary.get("global_problems")
    ):
        raise SmokeQualificationError("smoke_trace_audit_failed")

    (
        load_guard_success_receipt,
        validate_eval_invocations,
        validate_guard_success_linkage,
    ) = _guard_helpers()
    try:
        guard = load_guard_success_receipt(artifact_records["route_guard_success"].path)
        guard_artifacts = validate_guard_success_linkage(
            guard,
            run_dir=run_dir,
            eval_run_identity_sha256=identity_sha256,
            eval_run_role="smoke",
            eval_run_identity_file_sha256=artifact_records["eval_run_identity"].sha256,
            results_sha256=artifact_records["results"].sha256,
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec.sha256,
            readiness_checkpoint=readiness.record,
            endpoint=endpoint,
            serving_route_generation=generation,
            proxy_policy=proxy_policy,
            require_concurrency_telemetry="concurrency_telemetry" in artifact_records,
        )
        invocation, invocation_record = validate_eval_invocations(
            artifact_records["eval_invocations"].path,
            eval_run_identity_sha256=identity_sha256,
            eval_run_role="smoke",
        )
    except (OSError, ValueError) as error:
        raise SmokeQualificationError("smoke_guard_receipt_invalid") from error
    if (
        guard_artifacts.get("eval_invocations") != artifact_records["eval_invocations"].record
        or invocation_record != artifact_records["eval_invocations"].record
        or invocation.get("resume") is not False
    ):
        raise SmokeQualificationError("smoke_guard_receipt_invalid")
    assert artifact_records["provenance"].raw is not None
    try:
        provenance: dict[str, str] = {}
        for line in artifact_records["provenance"].raw.decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if not separator or not key or not value or key in provenance:
                raise SmokeQualificationError("smoke_provenance_invalid")
            provenance[key] = value
    except UnicodeDecodeError as error:
        raise SmokeQualificationError("smoke_provenance_invalid") from error
    if provenance.get("host") != invocation.get("host") or provenance.get("slurm_job_id") != invocation.get(
        "slurm_job_id"
    ):
        raise SmokeQualificationError("smoke_provenance_invocation_mismatch")
    if (
        "concurrency_telemetry" in artifact_records
        and guard_artifacts.get("concurrency_telemetry") != artifact_records["concurrency_telemetry"].record
    ):
        raise SmokeQualificationError("smoke_guard_receipt_invalid")
    telemetry: dict[str, Any] | None = None
    if "concurrency_telemetry" in artifact_records:
        try:
            from vmvm_tb_v2._vacli.concurrency_telemetry import (
                ConcurrencyTelemetryError,
                load_concurrency_telemetry_artifact,
            )

            telemetry, telemetry_record = load_concurrency_telemetry_artifact(
                artifact_records["concurrency_telemetry"].path,
                eval_run_identity_sha256=identity_sha256,
                eval_run_role="smoke",
                slurm_job_id=invocation["slurm_job_id"],
            )
        except ImportError as error:
            raise SmokeQualificationError("smoke_concurrency_telemetry_runtime_unavailable") from error
        except (OSError, ConcurrencyTelemetryError, KeyError, TypeError) as error:
            raise SmokeQualificationError("smoke_concurrency_telemetry_invalid") from error
        if telemetry_record != artifact_records["concurrency_telemetry"].record:
            raise SmokeQualificationError("smoke_concurrency_telemetry_invalid")
    qualified = payload.get("qualified_execution")
    execution = identity.get("execution")
    vmvm = execution.get("vmvm_environment") if isinstance(execution, dict) else None
    expected_qualified = {
        "rollout_concurrency": execution.get("rollout_concurrency") if isinstance(execution, dict) else None,
        "multiplex": execution.get("multiplex") if isinstance(execution, dict) else None,
        "http_max_connections": (execution.get("http_max_connections") if isinstance(execution, dict) else None),
        "http_max_keepalive_connections": (
            execution.get("http_max_keepalive_connections") if isinstance(execution, dict) else None
        ),
        "lease_start_concurrency": (vmvm.get("lease_start_concurrency") if isinstance(vmvm, dict) else None),
    }
    if not _same_json(qualified, expected_qualified) or any(
        type(value) is not int or value < 1 for value in expected_qualified.values()
    ):
        raise SmokeQualificationError("smoke_qualified_execution_invalid")
    observed = payload.get("observed_concurrency")
    if telemetry is None:
        if observed is not None:
            raise SmokeQualificationError("smoke_observed_concurrency_invalid")
    else:
        observations = telemetry.get("observations")
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
            or not isinstance(observations, dict)
            or type(observations.get("vmvm_runtime_ready")) is not int
            or observations["vmvm_runtime_ready"] < expected_traces
            or observed.get("active_rollout_signal") != "completed_trace_lifecycle_timing_overlap"
            or observed.get("lease_start_signal") != "vacli_lease_start_semaphore_holders"
            or type(observed.get("peak_active_rollouts_lower_bound")) is not int
            or observed["peak_active_rollouts_lower_bound"] < 1
            or type(observed.get("peak_concurrent_lease_startups")) is not int
            or observed["peak_concurrent_lease_startups"] < 1
            or observed.get("peak_concurrent_lease_startups") != observations.get("peak_concurrent_lease_startups")
            or not requirements_valid
            or observed["peak_active_rollouts_lower_bound"] > qualified["rollout_concurrency"]
            or observed["peak_concurrent_lease_startups"] > qualified["lease_start_concurrency"]
            or (required_rollouts is not None and required_rollouts > observed["peak_active_rollouts_lower_bound"])
            or (required_leases is not None and required_leases > observed["peak_concurrent_lease_startups"])
        ):
            raise SmokeQualificationError("smoke_observed_concurrency_invalid")
    evidence = _evaluator_evidence(
        identity,
        policy,
        artifact_records["config"],
        model=model,
    )
    for name, artifact in artifact_records.items():
        load_artifact(
            artifact.path,
            artifact.sha256,
            label=f"smoke_{name}",
        )
    load_artifact(
        task_file.path,
        task_file.sha256,
        label="smoke_task_file",
    )
    final_smoke = load_artifact(
        smoke.path,
        smoke.sha256,
        label="smoke_checkpoint",
    )
    if stat.S_IMODE(final_smoke.path.stat().st_mode) != 0o444:
        raise SmokeQualificationError("smoke_checkpoint_not_immutable")
    return payload, evidence


def _worker_only_rotation(source: dict[str, Any], target: dict[str, Any]) -> bool:
    return (
        source != target
        and source.get("coordinator") == target.get("coordinator")
        and source.get("proxy") == target.get("proxy")
        and isinstance(source.get("routes"), list)
        and isinstance(target.get("routes"), list)
        and len(source["routes"]) == len(target["routes"])
        and source.get("routes") != target.get("routes")
    )


def _validate_probe(
    value: Any,
    *,
    endpoint: dict[str, Any],
    generation: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SmokeQualificationError("generation_probe_invalid")
    body = {key: item for key, item in value.items() if key != "probe_sha256"}
    coverage = value.get("coverage")
    request_contract = value.get("request_contract")
    requests = value.get("requests")
    expected_backends = sorted(route["backend_sha256"] for route in generation["routes"])
    expected_contract = {
        "provider_route": "/chat/completions",
        "model": model,
        "reasoning_effort": "max",
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        },
        "tool_name": "generation_bridge_ping",
        "tool_choice": {"tool_call": "required", "tool_result": "none"},
        "temperature": 0,
        "max_tokens": 256,
    }
    if (
        set(value)
        != {
            "schema_version",
            "state",
            "ok",
            "endpoint_authority_sha256",
            "serving_route_generation_sha256",
            "request_contract",
            "coverage",
            "requests",
            "probe_sha256",
        }
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("state") != "passed"
        or value.get("ok") is not True
        or value.get("endpoint_authority_sha256") != endpoint["authority_sha256"]
        or value.get("serving_route_generation_sha256") != sha256_bytes(canonical_json(generation))
        or not _same_json(request_contract, expected_contract)
        or value.get("probe_sha256") != sha256_bytes(canonical_json(body))
        or not isinstance(coverage, dict)
        or set(coverage) != {"expected_routes", "tested_routes", "backends", "round_trips_per_backend"}
        or type(coverage.get("expected_routes")) is not int
        or coverage["expected_routes"] != len(expected_backends)
        or type(coverage.get("tested_routes")) is not int
        or coverage["tested_routes"] != len(expected_backends)
        or coverage.get("backends") != expected_backends
        or type(coverage.get("round_trips_per_backend")) is not int
        or coverage["round_trips_per_backend"] != 1
        or not isinstance(requests, list)
        or not requests
    ):
        raise SmokeQualificationError("generation_probe_invalid")
    phases_by_backend: dict[str, set[str]] = {backend: set() for backend in expected_backends}
    for request in requests:
        if (
            not isinstance(request, dict)
            or set(request)
            != {
                "phase",
                "backend_sha256",
                "request_sha256",
                "response_sha256",
                "status_code",
                "response_model",
                "reasoning_nonempty",
                "tool_call_valid",
            }
            or request.get("phase") not in {"tool_call", "tool_result"}
            or request.get("backend_sha256") not in phases_by_backend
            or not isinstance(request.get("request_sha256"), str)
            or SHA256_RE.fullmatch(request["request_sha256"]) is None
            or not isinstance(request.get("response_sha256"), str)
            or SHA256_RE.fullmatch(request["response_sha256"]) is None
            or type(request.get("status_code")) is not int
            or request["status_code"] != 200
            or request.get("response_model") != model
            or request.get("reasoning_nonempty") is not True
            or type(request.get("tool_call_valid")) is not bool
            or (request["phase"] == "tool_call" and request["tool_call_valid"] is not True)
            or (request["phase"] == "tool_result" and request["tool_call_valid"] is not False)
            or request["phase"] in phases_by_backend[request["backend_sha256"]]
        ):
            raise SmokeQualificationError("generation_probe_invalid")
        phases_by_backend[request["backend_sha256"]].add(request["phase"])
    if any(phases != {"tool_call", "tool_result"} for phases in phases_by_backend.values()):
        raise SmokeQualificationError("generation_probe_incomplete")
    return value


def _validate_bridge(
    bridge: Artifact,
    payload: dict[str, Any],
    *,
    deployment_id: str,
    deployment_spec: Artifact,
    readiness: Artifact,
    endpoint: dict[str, Any],
    generation: dict[str, Any],
    proxy_policy: dict[str, Any],
    model: str,
    identity_loader: IdentityLoader | None,
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
) -> QualificationEvidence:
    if stat.S_IMODE(bridge.path.stat().st_mode) != 0o444:
        raise SmokeQualificationError("smoke_bridge_not_immutable")
    body = {key: value for key, value in payload.items() if key != "smoke_qualification_sha256"}
    artifacts = payload.get("artifacts")
    source = payload.get("source")
    target = payload.get("target")
    if (
        set(payload)
        != {
            "schema_version",
            "kind",
            "state",
            "ok",
            "deployment_id",
            "deployment_spec_sha256",
            "model",
            "proxy_policy",
            "proxy_config_projection_sha256",
            "artifacts",
            "source",
            "target",
            "evaluator_evidence",
            "probe",
            "smoke_qualification_sha256",
        }
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != BRIDGE_SCHEMA_VERSION
        or payload.get("kind") != BRIDGE_KIND
        or payload.get("state") != "passed"
        or payload.get("ok") is not True
        or payload.get("deployment_id") != deployment_id
        or payload.get("deployment_spec_sha256") != deployment_spec.sha256
        or payload.get("model") != model
        or not _same_json(payload.get("proxy_policy"), proxy_policy)
        or not isinstance(payload.get("proxy_config_projection_sha256"), str)
        or SHA256_RE.fullmatch(payload["proxy_config_projection_sha256"]) is None
        or payload.get("smoke_qualification_sha256") != sha256_bytes(canonical_json(body))
        or not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "source_smoke_checkpoint",
            "target_readiness_checkpoint",
            "deployment_spec",
            "proxy_info",
            "source_proxy_config_snapshot",
            "target_proxy_config_snapshot",
        }
        or not isinstance(source, dict)
        or set(source) != {"endpoint", "serving_route_generation", "readiness_checkpoint"}
        or not isinstance(target, dict)
        or set(target) != {"endpoint", "serving_route_generation", "readiness_checkpoint"}
    ):
        raise SmokeQualificationError("smoke_bridge_invalid")
    if deployment_spec_snapshot is None:
        bridge_spec = artifact_from_record(
            artifacts["deployment_spec"],
            label="bridge_deployment_spec",
            expected=deployment_spec,
        )
    else:
        bridge_spec_record = artifacts["deployment_spec"]
        if not isinstance(bridge_spec_record, dict) or bridge_spec_record != deployment_spec.record:
            raise SmokeQualificationError("bridge_deployment_spec_mismatch")
        bridge_spec = Artifact(
            path=deployment_spec.path,
            sha256=deployment_spec.sha256,
            raw=None,
        )
    bridge_readiness = artifact_from_record(
        artifacts["target_readiness_checkpoint"],
        label="bridge_target_readiness",
        expected=readiness,
    )
    bridge_proxy = artifact_from_record(
        artifacts["proxy_info"],
        label="bridge_proxy_info",
    )
    if (
        bridge_spec.record != deployment_spec.record
        or bridge_readiness.record != readiness.record
        or bridge_proxy.record != endpoint["proxy_info"]
        or not _same_json(target.get("endpoint"), endpoint)
        or not _same_json(target.get("serving_route_generation"), generation)
        or target.get("readiness_checkpoint") != readiness.record
    ):
        raise SmokeQualificationError("smoke_bridge_target_mismatch")
    source_smoke = artifact_from_record(
        artifacts["source_smoke_checkpoint"],
        label="bridge_source_smoke",
        load_bytes=True,
    )
    source_payload = load_json_artifact(source_smoke, label="bridge_source_smoke")
    if type(source_payload.get("schema_version")) is not int or source_payload["schema_version"] != 1:
        raise SmokeQualificationError("smoke_bridge_source_not_v1")
    try:
        source_endpoint = validate_endpoint_binding(source.get("endpoint"))
        source_generation = validate_route_generation(source.get("serving_route_generation"))
    except (EndpointBindingError, RouteGenerationError) as error:
        raise SmokeQualificationError("smoke_bridge_source_invalid") from error
    source_readiness = artifact_from_record(
        source.get("readiness_checkpoint"),
        label="bridge_source_readiness",
        load_bytes=True,
    )
    if (
        not _same_json(source_endpoint, endpoint)
        or source_endpoint["proxy_info"] != endpoint["proxy_info"]
        or not _worker_only_rotation(source_generation, generation)
    ):
        raise SmokeQualificationError("smoke_bridge_not_worker_only_rotation")
    source_ready_generation, source_policy = validate_historical_readiness(
        source_readiness,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        endpoint=source_endpoint,
        model=model,
    )
    if not _same_json(source_ready_generation, source_generation):
        raise SmokeQualificationError("smoke_bridge_source_mismatch")
    source_proxy_config_snapshot = artifact_from_record(
        artifacts["source_proxy_config_snapshot"],
        label="bridge_source_proxy_config_snapshot",
    )
    target_proxy_config_snapshot = artifact_from_record(
        artifacts["target_proxy_config_snapshot"],
        label="bridge_target_proxy_config_snapshot",
    )
    from deployment_proxy_policy import (
        DeploymentProxyPolicyError,
        validate_worker_rotation_proxy_configs,
    )

    try:
        projection_sha256 = validate_worker_rotation_proxy_configs(
            source_snapshot=source_proxy_config_snapshot.path,
            source_binding=source_policy,
            source_backends=[route["backend_sha256"] for route in source_generation["routes"]],
            target_snapshot=target_proxy_config_snapshot.path,
            target_binding=proxy_policy,
            target_backends=[route["backend_sha256"] for route in generation["routes"]],
        )
    except DeploymentProxyPolicyError as error:
        raise SmokeQualificationError("smoke_bridge_proxy_config_mismatch") from error
    if projection_sha256 != payload["proxy_config_projection_sha256"]:
        raise SmokeQualificationError("smoke_bridge_proxy_config_mismatch")
    _, evaluator_evidence = validate_v1_smoke(
        source_smoke,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        readiness=source_readiness,
        endpoint=source_endpoint,
        generation=source_generation,
        proxy_policy=source_policy,
        model=model,
        identity_loader=identity_loader,
    )
    if not _same_json(payload.get("evaluator_evidence"), evaluator_evidence):
        raise SmokeQualificationError("smoke_bridge_evaluator_mismatch")
    _validate_probe(
        payload.get("probe"),
        endpoint=endpoint,
        generation=generation,
        model=model,
    )
    if deployment_spec_snapshot is None:
        final_spec = load_artifact(
            deployment_spec.path,
            deployment_spec.sha256,
            label="deployment_spec",
        )
    else:
        final_spec = Artifact(
            path=deployment_spec.path,
            sha256=deployment_spec.sha256,
            raw=None,
        )
    final_readiness = load_artifact(
        readiness.path,
        readiness.sha256,
        label="readiness_checkpoint",
        load_bytes=True,
    )
    final_proxy = load_artifact(
        bridge_proxy.path,
        bridge_proxy.sha256,
        label="proxy_info",
    )
    final_source_smoke = load_artifact(
        source_smoke.path,
        source_smoke.sha256,
        label="bridge_source_smoke",
    )
    load_artifact(
        source_readiness.path,
        source_readiness.sha256,
        label="bridge_source_readiness",
    )
    try:
        final_endpoint = load_deployment_endpoint(
            final_proxy.path,
            deployment_id=deployment_id,
            expected_model=model,
            deployment_spec=final_spec.path,
            expected_proxy_info_sha256=final_proxy.sha256,
        ).binding
    except EndpointBindingError as error:
        raise SmokeQualificationError("smoke_bridge_target_changed") from error
    final_generation, final_policy = validate_readiness(
        final_readiness,
        deployment_id=deployment_id,
        deployment_spec=final_spec,
        endpoint=final_endpoint,
        model=model,
        deployment_spec_snapshot=deployment_spec_snapshot,
        proxy_policy_snapshot=proxy_policy_snapshot,
    )
    try:
        final_projection_sha256 = validate_worker_rotation_proxy_configs(
            source_snapshot=source_proxy_config_snapshot.path,
            source_binding=source_policy,
            source_backends=[route["backend_sha256"] for route in source_generation["routes"]],
            target_snapshot=target_proxy_config_snapshot.path,
            target_binding=final_policy,
            target_backends=[route["backend_sha256"] for route in final_generation["routes"]],
        )
    except DeploymentProxyPolicyError as error:
        raise SmokeQualificationError("smoke_bridge_proxy_config_mismatch") from error
    if (
        not _same_json(final_endpoint, endpoint)
        or not _same_json(final_generation, generation)
        or not _same_json(final_policy, proxy_policy)
        or final_projection_sha256 != payload["proxy_config_projection_sha256"]
        or not _same_json(
            _evaluator_source_evidence(evaluator_evidence["source"]),
            evaluator_evidence["evaluator_source"],
        )
    ):
        raise SmokeQualificationError("smoke_bridge_target_changed")
    if stat.S_IMODE(final_source_smoke.path.stat().st_mode) != 0o444:
        raise SmokeQualificationError("smoke_checkpoint_not_immutable")
    load_artifact(
        bridge.path,
        bridge.sha256,
        label="smoke_qualification",
    )
    if stat.S_IMODE(bridge.path.stat().st_mode) != 0o444:
        raise SmokeQualificationError("smoke_bridge_not_immutable")
    return QualificationEvidence(
        schema_version=BRIDGE_SCHEMA_VERSION,
        qualification=bridge,
        source_smoke=source_smoke,
        source_generation=source_generation,
        target_generation=generation,
        evaluator_evidence=evaluator_evidence,
    )


def validate_smoke_qualification(
    qualification_path: Path,
    qualification_sha256: str,
    *,
    deployment_id: str,
    deployment_spec_path: Path,
    deployment_spec_sha256: str,
    readiness_path: Path,
    readiness_sha256: str,
    proxy_info_path: Path,
    proxy_info_sha256: str,
    model: str,
    identity_loader: IdentityLoader | None = None,
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
) -> QualificationEvidence:
    """Validate either an exact-generation v1 smoke or a schema-v2 bridge."""

    if model != "Kimi-K3":
        raise SmokeQualificationError("smoke_qualification_model_invalid")
    if (deployment_spec_snapshot is None) != (proxy_policy_snapshot is None):
        raise SmokeQualificationError("deployment_snapshot_incomplete")
    if deployment_spec_snapshot is None:
        deployment_spec = load_artifact(
            deployment_spec_path,
            deployment_spec_sha256,
            label="deployment_spec",
        )
    else:
        try:
            live_path = deployment_spec_path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise SmokeQualificationError("deployment_spec_unreadable") from error
        deployment_spec = Artifact(
            path=live_path,
            sha256=deployment_spec_sha256,
            raw=None,
        )
    readiness = load_artifact(
        readiness_path,
        readiness_sha256,
        label="readiness_checkpoint",
        load_bytes=True,
    )
    proxy_info = load_artifact(
        proxy_info_path,
        proxy_info_sha256,
        label="proxy_info",
    )
    try:
        endpoint_info = load_deployment_endpoint(
            proxy_info.path,
            deployment_id=deployment_id,
            expected_model=model,
            deployment_spec=deployment_spec.path,
            expected_proxy_info_sha256=proxy_info.sha256,
        )
    except EndpointBindingError as error:
        raise SmokeQualificationError("deployment_endpoint_invalid") from error
    endpoint = endpoint_info.binding
    generation, proxy_policy = validate_readiness(
        readiness,
        deployment_id=deployment_id,
        deployment_spec=deployment_spec,
        endpoint=endpoint,
        model=model,
        deployment_spec_snapshot=deployment_spec_snapshot,
        proxy_policy_snapshot=proxy_policy_snapshot,
    )
    qualification = load_artifact(
        qualification_path,
        qualification_sha256,
        label="smoke_qualification",
        load_bytes=True,
    )
    payload = load_json_artifact(qualification, label="smoke_qualification")
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int:
        raise SmokeQualificationError("smoke_qualification_schema_invalid")
    if schema_version == 1:
        _, evaluator_evidence = validate_v1_smoke(
            qualification,
            deployment_id=deployment_id,
            deployment_spec=deployment_spec,
            readiness=readiness,
            endpoint=endpoint,
            generation=generation,
            proxy_policy=proxy_policy,
            model=model,
            identity_loader=identity_loader,
        )
        return QualificationEvidence(
            schema_version=1,
            qualification=qualification,
            source_smoke=qualification,
            source_generation=generation,
            target_generation=generation,
            evaluator_evidence=evaluator_evidence,
        )
    if schema_version == BRIDGE_SCHEMA_VERSION:
        return _validate_bridge(
            qualification,
            payload,
            deployment_id=deployment_id,
            deployment_spec=deployment_spec,
            readiness=readiness,
            endpoint=endpoint,
            generation=generation,
            proxy_policy=proxy_policy,
            model=model,
            identity_loader=identity_loader,
            deployment_spec_snapshot=deployment_spec_snapshot,
            proxy_policy_snapshot=proxy_policy_snapshot,
        )
    raise SmokeQualificationError("smoke_qualification_schema_invalid")


def build_bridge_payload(
    *,
    deployment_id: str,
    deployment_spec: Artifact,
    model: str,
    proxy_policy: dict[str, Any],
    source_smoke: Artifact,
    source_readiness: Artifact,
    source_endpoint: dict[str, Any],
    source_generation: dict[str, Any],
    target_readiness: Artifact,
    target_endpoint: dict[str, Any],
    target_generation: dict[str, Any],
    source_proxy_config_snapshot: Artifact,
    target_proxy_config_snapshot: Artifact,
    proxy_config_projection_sha256: str,
    evaluator_evidence: dict[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any]:
    """Build, but do not publish, the canonical schema-2 bridge."""

    body = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "kind": BRIDGE_KIND,
        "state": "passed",
        "ok": True,
        "deployment_id": deployment_id,
        "deployment_spec_sha256": deployment_spec.sha256,
        "model": model,
        "proxy_policy": proxy_policy,
        "proxy_config_projection_sha256": proxy_config_projection_sha256,
        "artifacts": {
            "source_smoke_checkpoint": source_smoke.record,
            "target_readiness_checkpoint": target_readiness.record,
            "deployment_spec": deployment_spec.record,
            "proxy_info": target_endpoint["proxy_info"],
            "source_proxy_config_snapshot": source_proxy_config_snapshot.record,
            "target_proxy_config_snapshot": target_proxy_config_snapshot.record,
        },
        "source": {
            "endpoint": source_endpoint,
            "serving_route_generation": source_generation,
            "readiness_checkpoint": source_readiness.record,
        },
        "target": {
            "endpoint": target_endpoint,
            "serving_route_generation": target_generation,
            "readiness_checkpoint": target_readiness.record,
        },
        "evaluator_evidence": evaluator_evidence,
        "probe": probe,
    }
    return {
        **body,
        "smoke_qualification_sha256": sha256_bytes(canonical_json(body)),
    }
