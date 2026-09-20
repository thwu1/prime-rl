"""Shared, non-sensitive evidence helpers for mixed-provider Qwen completion."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Mapping

from materialize_qwen_provider_union import CANONICAL_DATASET_REVISION

SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40,64}")
QWEN_MODEL = "Qwen3.8-2.4T-A95B"
FULL_CONTEXT_TOKENS = 262_144
HOST_HARNESS_CONTRACT = {
    "id": "terminal-bench-sandoq-host",
    "placement": "host",
    "tool": "bash",
    "command_timeout_seconds": 240,
    "command_kill_grace_seconds": 10,
    "max_command_output_chars": 100_000,
    "request_timeout_seconds": 15_000,
    "request_max_retries": 0,
    "stream": False,
}


class UnionContractError(ValueError):
    pass


def canonical_json(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise UnionContractError("evidence_not_strict_json") from error


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_regular(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise UnionContractError("evidence_unreadable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise UnionContractError("evidence_invalid")
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise UnionContractError("evidence_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after):
        raise UnionContractError("evidence_changed")
    return bytes(body)


def artifact(path: Path) -> dict[str, Any]:
    body = read_regular(path)
    return {"bytes": len(body), "sha256": sha256_bytes(body)}


def _valid_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _source_provider(source: Mapping[str, Any]) -> str:
    return str(source.get("sandbox_provider", "vmvm"))


def validate_shared_identity(
    identity: Mapping[str, Any],
    *,
    expected_provider: str,
    expected_task_file: Path,
    expected_task_sha256: str,
    expected_count: int,
    expected_config: Path,
    expected_dataset: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate provider-local bindings and return a provider-neutral contract."""
    source = identity.get("source")
    contract = identity.get("contract")
    dataset = identity.get("dataset")
    deployment = identity.get("deployment")
    inputs = identity.get("inputs")
    config = identity.get("config")
    execution = identity.get("execution")
    if (
        identity.get("role") != "qwen-direct"
        or not isinstance(source, Mapping)
        or _source_provider(source) != expected_provider
        or not isinstance(contract, Mapping)
        or not isinstance(dataset, Mapping)
        or not isinstance(deployment, Mapping)
        or not isinstance(inputs, Mapping)
        or not isinstance(config, Mapping)
        or not isinstance(execution, Mapping)
    ):
        raise UnionContractError("provider_identity_invalid")
    context = contract.get("context_tokens")
    if (
        contract.get("model") != QWEN_MODEL
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "high"
        or contract.get("thinking") != {"enable_thinking": True, "preserve_thinking": True}
        or context
        != {
            "max_input_tokens": FULL_CONTEXT_TOKENS,
            "max_output_tokens": FULL_CONTEXT_TOKENS,
            "max_total_tokens": FULL_CONTEXT_TOKENS,
        }
        or not _valid_positive_integer(contract.get("sampling_max_tokens"))
        or contract["sampling_max_tokens"] > FULL_CONTEXT_TOKENS
        or contract.get("capture_model_io") is not True
        or contract.get("retain_traces") is not False
        or contract.get("harness") != HOST_HARNESS_CONTRACT
    ):
        raise UnionContractError("qwen_trace_contract_invalid")
    try:
        dataset_path = Path(str(dataset["path"])).resolve(strict=True)
        wanted_dataset = expected_dataset.resolve(strict=True)
        task_record = inputs["task_file"]
        config_record = config["source"]
        task_path = Path(str(task_record["path"])).resolve(strict=True)
        config_path = Path(str(config_record["path"])).resolve(strict=True)
    except (KeyError, OSError, TypeError) as error:
        raise UnionContractError("provider_input_binding_invalid") from error
    if (
        dataset.get("kind") != "git_revision"
        or dataset.get("revision") != CANONICAL_DATASET_REVISION
        or dataset.get("content_sha256") is not None
        or dataset_path != wanted_dataset
        or task_path != expected_task_file.resolve(strict=True)
        or task_record.get("sha256") != expected_task_sha256
        or task_record.get("count") != expected_count
        or config_path != expected_config.resolve(strict=True)
    ):
        raise UnionContractError("provider_input_binding_invalid")
    common_source_keys = (
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
    )
    common_source = {key: source.get(key) for key in common_source_keys}
    if (
        any(REVISION_RE.fullmatch(str(common_source[key] or "")) is None for key in common_source_keys[::2])
        or any(SHA256_RE.fullmatch(str(common_source[key] or "")) is None for key in common_source_keys[1::2])
    ):
        raise UnionContractError("source_closure_invalid")
    worker = deployment.get("worker_manifest")
    router = deployment.get("router")
    try:
        expected_config_value = tomllib.loads(read_regular(expected_config).decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, UnionContractError) as error:
        raise UnionContractError("direct_qwen_admission_invalid") from error
    expected_client = expected_config_value.get("client")
    rollout_concurrency = expected_config_value.get("max_concurrent")
    provider_concurrency = (
        expected_client.get("max_connections") if isinstance(expected_client, Mapping) else None
    )
    keepalive_concurrency = (
        expected_client.get("max_keepalive_connections")
        if isinstance(expected_client, Mapping)
        else None
    )
    if (
        deployment.get("kind") != "direct_qwen"
        or not isinstance(worker, Mapping)
        or SHA256_RE.fullmatch(str(worker.get("sha256", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("spec_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("endpoint_bundle_sha256", ""))) is None
        or not isinstance(deployment.get("base_url"), str)
        or not deployment["base_url"]
        or not isinstance(router, Mapping)
        or router.get("policy") != "consistent_hash"
        or router.get("request_id_headers") != ["x-session-id"]
        or not _valid_positive_integer(router.get("provider_concurrency"))
        or not _valid_positive_integer(rollout_concurrency)
        or not _valid_positive_integer(provider_concurrency)
        or keepalive_concurrency != provider_concurrency
        or provider_concurrency > rollout_concurrency
        or router.get("provider_concurrency") != provider_concurrency
    ):
        raise UnionContractError("direct_qwen_deployment_invalid")
    try:
        from direct_qwen_workers import validate_saved_manifest

        manifest = validate_saved_manifest(
            Path(str(worker["path"])),
            expected_admission=(
                rollout_concurrency,
                provider_concurrency,
                rollout_concurrency - provider_concurrency,
            ),
        )
    except Exception as error:
        raise UnionContractError("direct_qwen_worker_manifest_invalid") from error
    if len(manifest.get("workers", [])) != 24:
        raise UnionContractError("direct_qwen_worker_manifest_invalid")
    worker_generation = {
        "model": manifest["model"],
        "spec_sha256": manifest["spec_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "workers": manifest["workers"],
    }
    manifest_router = manifest["router"]
    shared = {
        "contract": {
            key: contract[key]
            for key in (
                "model",
                "pass_at_1",
                "num_rollouts",
                "reasoning_effort",
                "thinking",
                "context_tokens",
                "sampling_max_tokens",
                "capture_model_io",
                "outbound_body_denylist",
                "retain_traces",
                "harness",
            )
        },
        "dataset": {
            "kind": "git_revision",
            "revision": CANONICAL_DATASET_REVISION,
        },
        "deployment": {
            "endpoint_bundle_sha256": deployment["endpoint_bundle_sha256"],
            "router": {
                "policy": manifest_router["policy"],
                "request_id_headers": manifest_router["request_id_headers"],
                "request_timeout_seconds": manifest_router["request_timeout_seconds"],
                "queue_timeout_seconds": manifest_router["queue_timeout_seconds"],
                "retries": manifest_router["retries"],
            },
            "spec_sha256": deployment["spec_sha256"],
            "worker_count": 24,
            "worker_generation_sha256": sha256_bytes(canonical_json(worker_generation)),
        },
        "source": common_source,
    }
    return shared, dict(execution)


def audit_results(results: Path, task_file: Path, expected_count: int) -> tuple[str, dict[str, int]]:
    from audit_traces import (
        QWEN3_A95B_MODEL_IO_CONTRACT,
        _iter_traces,
        _read_expected_slugs,
        _summarize_traces,
    )

    before = artifact(results)["sha256"]
    expected = _read_expected_slugs(task_file)
    if len(expected) != expected_count:
        raise UnionContractError("task_selection_count_invalid")
    summary, failed = _summarize_traces(
        _iter_traces(results),
        expected_slugs=expected,
        expected_count=expected_count,
        rollouts_per_task=1,
        require_reasoning=True,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        aggregate_only=True,
        model_io_contract=QWEN3_A95B_MODEL_IO_CONTRACT,
        require_request_graph_match=True,
        max_sequence_tokens=FULL_CONTEXT_TOKENS,
    )
    if failed or summary.get("model_io_turns", 0) < expected_count:
        raise UnionContractError("trace_audit_failed")
    if artifact(results)["sha256"] != before:
        raise UnionContractError("results_changed_during_audit")
    allowed = (
        "traces",
        "tasks",
        "sampled_tokens",
        "model_io_turns",
        "provider_reported_zero_reasoning_tool_turns",
        "provider_explicit_empty_reasoning_tool_turns",
    )
    counts = {key: summary[key] for key in allowed}
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values()):
        raise UnionContractError("trace_audit_failed")
    return str(before), counts


def write_exclusive(path: Path, value: Mapping[str, Any]) -> str:
    body = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_bytes(body)
