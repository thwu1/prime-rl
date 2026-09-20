#!/usr/bin/env python3
"""Certify the public, aggregate-only union of private Qwen repair lanes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import certify_direct_qwen_repair_provider as provider_certificate
from direct_qwen_union_contract import (
    FULL_CONTEXT_TOKENS,
    HOST_HARNESS_CONTRACT,
    QWEN_MODEL,
    REVISION_RE,
    SHA256_RE,
    UnionContractError,
    canonical_json,
    sha256_bytes,
    write_exclusive,
)


class RepairProviderUnionCertificateError(ValueError):
    """A stable, aggregate-only repair union certification failure."""


_PUBLIC_FORBIDDEN_FRAGMENTS = frozenset(
    {
        "certificate",
        "commitment",
        "config",
        "dataset",
        "digest",
        "identity",
        "materialization",
        "path",
        "result",
        "sha",
        "source",
    }
)
_PUBLIC_AGGREGATE_TASK_KEYS = frozenset({"task_count", "tasks"})


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _load_private(path: Path, expected_sha256: str) -> dict[str, Any]:
    try:
        raw = provider_certificate._read_private_artifact(
            path,
            path.parent,
            "provider_certificate_invalid",
        )
        value = json.loads(raw)
    except (
        OSError,
        json.JSONDecodeError,
        UnionContractError,
        provider_certificate.RepairProviderCertificateError,
    ) as error:
        raise RepairProviderUnionCertificateError("provider_certificate_invalid") from error
    if (
        SHA256_RE.fullmatch(expected_sha256 or "") is None
        or sha256_bytes(raw) != expected_sha256
        or not isinstance(value, dict)
    ):
        raise RepairProviderUnionCertificateError("provider_certificate_invalid")
    return value


def _artifact_sha256(path: Path, private_output_root: Path) -> str:
    try:
        return provider_certificate._private_artifact_sha256(
            path,
            private_output_root,
            "provider_partition_artifact_invalid",
        )
    except (OSError, provider_certificate.RepairProviderCertificateError) as error:
        raise RepairProviderUnionCertificateError("provider_partition_artifact_invalid") from error


def _validate_lane_binding(value: object, *, absence: bool = False) -> dict[str, str]:
    keys = (
        {"task_file_sha256", "config_sha256"}
        if absence
        else {
            "task_file_sha256",
            "config_sha256",
            "eval_run_identity_sha256",
            "results_sha256",
            "worker_manifest_sha256",
        }
    )
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in keys)
    ):
        raise RepairProviderUnionCertificateError("lane_binding_invalid")
    return value


def _validate_trace(value: object, expected_count: int) -> dict[str, int]:
    keys = {
        "traces",
        "tasks",
        "sampled_tokens",
        "model_io_turns",
        "provider_reported_zero_reasoning_tool_turns",
        "provider_explicit_empty_reasoning_tool_turns",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(not _integer(value.get(key)) for key in keys)
        or value.get("traces") != expected_count
        or value.get("tasks") != expected_count
        or value.get("model_io_turns", 0) < expected_count
    ):
        raise RepairProviderUnionCertificateError("provider_trace_audit_invalid")
    return value


def _validate_shared_contract(value: object, expected_sha256: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or SHA256_RE.fullmatch(str(expected_sha256 or "")) is None
        or sha256_bytes(canonical_json(value)) != expected_sha256
    ):
        raise RepairProviderUnionCertificateError("shared_contract_invalid")
    contract = value.get("contract")
    deployment = value.get("deployment")
    source = value.get("source")
    dataset = value.get("dataset")
    contract_keys = {
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
    }
    deployment_keys = {
        "endpoint_bundle_sha256",
        "router",
        "spec_sha256",
        "worker_count",
        "worker_generation_sha256",
    }
    source_keys = {
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
    }
    if (
        set(value) != {"contract", "dataset", "deployment", "source"}
        or not isinstance(contract, dict)
        or set(contract) != contract_keys
        or contract.get("model") != QWEN_MODEL
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "max"
        or contract.get("thinking") != {"enable_thinking": True, "preserve_thinking": True}
        or contract.get("context_tokens")
        != {
            "max_input_tokens": FULL_CONTEXT_TOKENS,
            "max_output_tokens": FULL_CONTEXT_TOKENS,
            "max_total_tokens": FULL_CONTEXT_TOKENS,
        }
        or contract.get("capture_model_io") is not True
        or not _integer(contract.get("sampling_max_tokens"), minimum=1)
        or contract.get("sampling_max_tokens", FULL_CONTEXT_TOKENS + 1)
        > FULL_CONTEXT_TOKENS
        or contract.get("outbound_body_denylist")
        != ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
        or contract.get("retain_traces") is not False
        or contract.get("harness") != HOST_HARNESS_CONTRACT
        or not isinstance(deployment, dict)
        or set(deployment) != deployment_keys
        or deployment.get("worker_count") != 24
        or not isinstance(source, dict)
        or set(source) != source_keys
        or not isinstance(dataset, dict)
        or set(dataset) != {"kind", "revision"}
        or dataset.get("kind") != "git_revision"
        or REVISION_RE.fullmatch(str(dataset.get("revision", ""))) is None
        or any(
            REVISION_RE.fullmatch(str(source.get(key, ""))) is None
            for key in ("prime_rl_commit", "verifiers_commit", "renderers_commit")
        )
        or any(
            SHA256_RE.fullmatch(str(source.get(key, ""))) is None
            for key in (
                "prime_rl_tree_sha256",
                "verifiers_tree_sha256",
                "renderers_tree_sha256",
            )
        )
        or any(
            SHA256_RE.fullmatch(str(deployment.get(key, ""))) is None
            for key in ("endpoint_bundle_sha256", "spec_sha256", "worker_generation_sha256")
        )
    ):
        raise RepairProviderUnionCertificateError("shared_contract_invalid")
    router = deployment.get("router")
    if (
        not isinstance(router, dict)
        or set(router)
        != {
            "policy",
            "request_id_headers",
            "request_timeout_seconds",
            "queue_timeout_seconds",
            "retries",
        }
        or router.get("policy") != "consistent_hash"
        or router.get("request_id_headers") != ["x-session-id"]
        or any(
            not _integer(router.get(key))
            for key in ("request_timeout_seconds", "queue_timeout_seconds", "retries")
        )
    ):
        raise RepairProviderUnionCertificateError("shared_contract_invalid")
    return value


def _validate_sandoq_cleanup(value: object, task_count: int) -> dict[str, Any]:
    keys = {
        "audit_sha256",
        "assignment_attempts",
        "assignment_cancellations",
        "assignment_measured_high_water",
        "extra_assignment_attempts",
        "gateway_close_warnings",
        "outer_session_high_water",
        "recorded_outer_sessions",
        "recovered_poisoned_assignments",
        "typed_http_404",
        "zero_drop",
        "failures",
    }
    count_keys = keys - {"audit_sha256", "zero_drop"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or SHA256_RE.fullmatch(str(value.get("audit_sha256", ""))) is None
        or any(not _integer(value.get(key)) for key in count_keys)
        or value.get("assignment_attempts", 0) < task_count
        or value.get("assignment_measured_high_water") != provider_certificate.SANDOQ_CONCURRENCY
        or value.get("outer_session_high_water", 0) < provider_certificate.SANDOQ_CONCURRENCY
        or value.get("typed_http_404") != value.get("recorded_outer_sessions")
        or value.get("zero_drop") is not True
        or value.get("failures") != 0
    ):
        raise RepairProviderUnionCertificateError("sandoq_cleanup_invalid")
    return value


def _validate_auth(value: object) -> dict[str, Any]:
    keys = {
        "audit_sha256",
        "atomic_same_path",
        "batch_heartbeats",
        "fail_closed_before_expiry_seconds",
        "maximum_observed_refresh_gap_seconds",
        "maximum_observed_heartbeat_gap_seconds",
        "maximum_refresh_interval_seconds",
        "minimum_observed_expiry_margin_seconds",
        "run_duration_seconds",
        "successful_replacements",
    }
    integer_keys = keys - {"audit_sha256", "atomic_same_path"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or SHA256_RE.fullmatch(str(value.get("audit_sha256", ""))) is None
        or value.get("atomic_same_path") is not True
        or any(not _integer(value.get(key)) for key in integer_keys)
        or value.get("maximum_refresh_interval_seconds") != 14_400
        or value.get("maximum_observed_refresh_gap_seconds", 14_401) > 14_400
        or value.get("maximum_observed_heartbeat_gap_seconds", 301) > 300
        or value.get("fail_closed_before_expiry_seconds", 0) < 1_800
        or value.get("minimum_observed_expiry_margin_seconds", 0)
        < value.get("fail_closed_before_expiry_seconds", 0)
    ):
        raise RepairProviderUnionCertificateError("sandoq_auth_invalid")
    return value


def _validate_sandoq(
    value: dict[str, Any],
    *,
    materialization: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = {
        "schema_version",
        "kind",
        "state",
        "sandbox_provider",
        "task_count",
        "selection",
        "lane_binding",
        "worker_count",
        "execution_proof",
        "trace_audit",
        "pool_cleanup",
        "sanitized_cleanup_source_hashes",
        "auth_rotation",
        "predecessor",
        "materialization",
        "shared_contract",
        "shared_contract_sha256",
        "provider_source",
    }
    task_count = materialization["partition"]["sandoq_count"]
    if (
        set(value) != expected
        or value.get("schema_version") != 1
        or value.get("kind") != "direct-qwen-repair-sandoq-partition"
        or value.get("state") != "passed"
        or value.get("sandbox_provider") != "sandoq"
        or value.get("task_count") != task_count
        or value.get("selection") != "sealed-repair-intersection"
        or value.get("worker_count") != 24
        or value.get("execution_proof") != provider_certificate._sandoq_execution_proof()
        or value.get("materialization") != materialization
    ):
        raise RepairProviderUnionCertificateError("sandoq_certificate_invalid")
    lane = _validate_lane_binding(value.get("lane_binding"))
    shared = _validate_shared_contract(value.get("shared_contract"), value.get("shared_contract_sha256"))
    _validate_trace(value.get("trace_audit"), task_count)
    cleanup = _validate_sandoq_cleanup(value.get("pool_cleanup"), task_count)
    auth = _validate_auth(value.get("auth_rotation"))
    source_hashes = value.get("sanitized_cleanup_source_hashes")
    predecessor = value.get("predecessor")
    provider_source = value.get("provider_source")
    provider_source_keys = {
        "prime_rl_commit",
        "verifiers_commit",
        "renderers_commit",
        "sandoq_provider_commit",
        "sandoq_provider_tree",
        "sandoq_client_version",
        "sandoq_host_harness_sha256",
        "sandoq_site_sha256",
        "derived_image_manifest_sha256",
        "direct_spec_sha256",
        "direct_endpoint_bundle_sha256",
    }
    if (
        not isinstance(source_hashes, dict)
        or set(source_hashes)
        != {
            "pool_drain_sha256",
            "pool_event_log_sha256",
            "pool_wal_sha256",
            "raw_audit_sha256",
        }
        or any(SHA256_RE.fullmatch(str(item)) is None for item in source_hashes.values())
        or not isinstance(predecessor, dict)
        or set(predecessor) != {"sha256", "stage_count"}
        or predecessor.get("stage_count") != 64
        or SHA256_RE.fullmatch(str(predecessor.get("sha256", ""))) is None
        or not isinstance(provider_source, dict)
        or set(provider_source) != provider_source_keys
        or any(not isinstance(item, str) or not item for item in provider_source.values())
        or provider_source.get("direct_spec_sha256")
        != shared.get("deployment", {}).get("spec_sha256")
        or provider_source.get("direct_endpoint_bundle_sha256")
        != shared.get("deployment", {}).get("endpoint_bundle_sha256")
        or any(
            provider_source.get(key) != shared.get("source", {}).get(key)
            for key in ("prime_rl_commit", "verifiers_commit", "renderers_commit")
        )
    ):
        raise RepairProviderUnionCertificateError("sandoq_certificate_invalid")
    return lane, {"trace": value["trace_audit"], "cleanup": cleanup, "auth": auth, "shared": shared}


def _validate_vmvm_cleanup(value: object) -> dict[str, Any]:
    keys = {
        "state",
        "runtime_instances",
        "cleanup_passes",
        "agent_runtime_instances",
        "verifier_runtime_instances",
        "verifier_mode",
        "compose_runtime_instances",
        "local_cleanup_failures",
        "release_on_exit_completed",
        "remote_deletion_verified",
    }
    integer_keys = keys - {"state", "verifier_mode", "remote_deletion_verified"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("state") != "passed"
        or value.get("verifier_mode") not in {"shared", "separate"}
        or any(not _integer(value.get(key)) for key in integer_keys)
        or value.get("agent_runtime_instances") != 1
        or value.get("compose_runtime_instances") != 1
        or value.get("local_cleanup_failures") != 0
        or value.get("cleanup_passes", 0) < value.get("runtime_instances", 0)
        or value.get("runtime_instances") != value.get("release_on_exit_completed")
        or value.get("runtime_instances")
        != value.get("agent_runtime_instances") + value.get("verifier_runtime_instances")
        or value.get("verifier_runtime_instances")
        != (0 if value.get("verifier_mode") == "shared" else 1)
        or value.get("remote_deletion_verified") is not False
    ):
        raise RepairProviderUnionCertificateError("vmvm_cleanup_invalid")
    return value


def _validate_vmvm(
    value: dict[str, Any],
    *,
    materialization: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    vmvm_count = materialization["partition"]["vmvm_count"]
    if vmvm_count == 0:
        expected = {
            "schema_version",
            "kind",
            "state",
            "sandbox_provider",
            "task_count",
            "selection",
            "lane_binding",
            "launch_evidence_present",
            "materialization",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != 1
            or value.get("kind") != "direct-qwen-repair-vmvm-absence"
            or value.get("state") != "absent"
            or value.get("sandbox_provider") != "vmvm"
            or value.get("task_count") != 0
            or value.get("selection") != "sealed-repair-intersection"
            or value.get("launch_evidence_present") is not False
            or value.get("materialization") != materialization
        ):
            raise RepairProviderUnionCertificateError("vmvm_absence_invalid")
        return _validate_lane_binding(value.get("lane_binding"), absence=True), None
    expected = {
        "schema_version",
        "kind",
        "state",
        "sandbox_provider",
        "task_count",
        "selection",
        "lane_binding",
        "worker_count",
        "execution_proof",
        "trace_audit",
        "compose_proof",
        "runtime_cleanup",
        "materialization",
        "shared_contract",
        "shared_contract_sha256",
        "provider_source",
    }
    if (
        set(value) != expected
        or value.get("schema_version") != 1
        or value.get("kind") != "direct-qwen-repair-vmvm-partition"
        or value.get("state") != "passed"
        or value.get("sandbox_provider") != "vmvm"
        or value.get("task_count") != 1
        or value.get("selection") != "sealed-repair-intersection"
        or value.get("worker_count") != 24
        or value.get("execution_proof") != provider_certificate._vmvm_execution_proof()
        or value.get("materialization") != materialization
    ):
        raise RepairProviderUnionCertificateError("vmvm_certificate_invalid")
    lane = _validate_lane_binding(value.get("lane_binding"))
    shared = _validate_shared_contract(value.get("shared_contract"), value.get("shared_contract_sha256"))
    trace = _validate_trace(value.get("trace_audit"), 1)
    cleanup = _validate_vmvm_cleanup(value.get("runtime_cleanup"))
    compose = value.get("compose_proof")
    provider_source = value.get("provider_source")
    provider_source_keys = {
        "prime_rl_commit",
        "verifiers_commit",
        "renderers_commit",
        "vmvm_tb_v2_sha256",
        "direct_spec_sha256",
        "direct_endpoint_bundle_sha256",
    }
    if (
        not isinstance(compose, dict)
        or set(compose) != {"compose_count", "network_policy", "runtime", "vmvm_tb_v2_sha256"}
        or compose.get("compose_count") != 1
        or compose.get("network_policy") != "both-phases-no-network"
        or compose.get("runtime") != "vmvm"
        or SHA256_RE.fullmatch(str(compose.get("vmvm_tb_v2_sha256", ""))) is None
        or not isinstance(provider_source, dict)
        or set(provider_source) != provider_source_keys
        or any(not isinstance(item, str) or not item for item in provider_source.values())
        or provider_source.get("vmvm_tb_v2_sha256") != compose.get("vmvm_tb_v2_sha256")
        or provider_source.get("direct_spec_sha256")
        != shared.get("deployment", {}).get("spec_sha256")
        or provider_source.get("direct_endpoint_bundle_sha256")
        != shared.get("deployment", {}).get("endpoint_bundle_sha256")
        or any(
            provider_source.get(key) != shared.get("source", {}).get(key)
            for key in ("prime_rl_commit", "verifiers_commit", "renderers_commit")
        )
    ):
        raise RepairProviderUnionCertificateError("vmvm_certificate_invalid")
    return lane, {"trace": trace, "cleanup": cleanup, "shared": shared}


def _private_strings(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            found.update(_private_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_private_strings(item))
    elif isinstance(value, str) and (
        SHA256_RE.fullmatch(value) is not None
        or REVISION_RE.fullmatch(value) is not None
        or value.startswith("/")
    ):
        found.add(value)
    return found


def _validate_public_privacy(value: object, private_values: frozenset[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if (
                not isinstance(key, str)
                or (
                    key != "atomic_same_path"
                    and any(fragment in lowered for fragment in _PUBLIC_FORBIDDEN_FRAGMENTS)
                )
                or ("task" in lowered and key not in _PUBLIC_AGGREGATE_TASK_KEYS)
            ):
                raise RepairProviderUnionCertificateError("public_union_privacy_violation")
            _validate_public_privacy(item, private_values)
        return
    if isinstance(value, list):
        for item in value:
            _validate_public_privacy(item, private_values)
        return
    if isinstance(value, str) and (
        value in private_values or SHA256_RE.fullmatch(value) is not None or value.startswith("/")
    ):
        raise RepairProviderUnionCertificateError("public_union_privacy_violation")


def certify_union(
    *,
    sandoq_certificate: Path,
    sandoq_certificate_sha256: str,
    vmvm_certificate: Path,
    vmvm_certificate_sha256: str,
    materialization_inputs: provider_certificate.RepairMaterializationInputs,
) -> dict[str, Any]:
    try:
        materialization = provider_certificate._validate_materialization_value(
            materialization_inputs.validate()
        )
    except provider_certificate.RepairProviderCertificateError as error:
        raise RepairProviderUnionCertificateError("repair_materialization_invalid") from error
    sandoq = _load_private(sandoq_certificate, sandoq_certificate_sha256)
    vmvm = _load_private(vmvm_certificate, vmvm_certificate_sha256)
    sandoq_lane, sandoq_evidence = _validate_sandoq(
        sandoq,
        materialization=materialization,
    )
    vmvm_lane, vmvm_evidence = _validate_vmvm(vmvm, materialization=materialization)
    vmvm_count = materialization["partition"]["vmvm_count"]
    sandoq_count = materialization["partition"]["sandoq_count"]
    if (
        sandoq_count + vmvm_count != provider_certificate.EXPECTED_REPAIR_COUNT
        or sandoq_lane["task_file_sha256"]
        != _artifact_sha256(
            materialization_inputs.sandoq_tasks,
            materialization_inputs.private_output_root,
        )
        or sandoq_lane["config_sha256"]
        != _artifact_sha256(
            materialization_inputs.sandoq_config,
            materialization_inputs.private_output_root,
        )
        or vmvm_lane["task_file_sha256"]
        != _artifact_sha256(
            materialization_inputs.vmvm_tasks,
            materialization_inputs.private_output_root,
        )
        or vmvm_lane["config_sha256"]
        != _artifact_sha256(
            materialization_inputs.vmvm_config,
            materialization_inputs.private_output_root,
        )
        or sandoq_lane["task_file_sha256"] == vmvm_lane["task_file_sha256"]
        or sandoq_lane["config_sha256"] == vmvm_lane["config_sha256"]
    ):
        raise RepairProviderUnionCertificateError("provider_union_partition_invalid")
    if vmvm_evidence is not None:
        if (
            sandoq_evidence["shared"] != vmvm_evidence["shared"]
            or sandoq["shared_contract_sha256"] != vmvm["shared_contract_sha256"]
            or sandoq_lane["eval_run_identity_sha256"]
            == vmvm_lane["eval_run_identity_sha256"]
            or sandoq_lane["results_sha256"] == vmvm_lane["results_sha256"]
        ):
            raise RepairProviderUnionCertificateError("provider_union_generation_drift")
    vmvm_trace = vmvm_evidence["trace"] if vmvm_evidence is not None else None
    traces = sandoq_evidence["trace"]["traces"] + (vmvm_trace["traces"] if vmvm_trace else 0)
    tasks = sandoq_evidence["trace"]["tasks"] + (vmvm_trace["tasks"] if vmvm_trace else 0)
    turns = sandoq_evidence["trace"]["model_io_turns"] + (
        vmvm_trace["model_io_turns"] if vmvm_trace else 0
    )
    if traces != provider_certificate.EXPECTED_REPAIR_COUNT or tasks != traces or turns < traces:
        raise RepairProviderUnionCertificateError("provider_union_trace_invalid")
    public = {
        "schema_version": 1,
        "kind": "direct-qwen-repair-provider-union",
        "state": "passed",
        "task_count": provider_certificate.EXPECTED_REPAIR_COUNT,
        "partition": {
            "sandoq": sandoq_count,
            "vmvm": vmvm_count,
            "total": provider_certificate.EXPECTED_REPAIR_COUNT,
            "disjoint": True,
            "exhaustive": True,
            "member_details_public": False,
        },
        "providers": {
            "sandoq": {"state": "passed", "task_count": sandoq_count},
            "vmvm": {
                "state": "passed" if vmvm_evidence is not None else "absent",
                "task_count": vmvm_count,
            },
        },
        "generation": {"worker_count": 24, "provider_neutral": True},
        "execution": {
            "harness_placement": "host",
            "sandoq": {
                "rollout_concurrency": provider_certificate.SANDOQ_CONCURRENCY,
                "http_concurrency": provider_certificate.SANDOQ_HTTP_CONCURRENCY,
                "pool_size": provider_certificate.SANDOQ_CONCURRENCY,
                "network_access": False,
                "predecessor_stage": 64,
            },
            "vmvm": {
                "selected": vmvm_evidence is not None,
                "rollout_concurrency": (
                    provider_certificate.VMVM_CONCURRENCY if vmvm_evidence is not None else 0
                ),
                "http_concurrency": (
                    provider_certificate.VMVM_HTTP_CONCURRENCY if vmvm_evidence is not None else 0
                ),
                "network_access": False,
            },
        },
        "trace_audit": {
            "traces": traces,
            "tasks": tasks,
            "model_io_turns": turns,
            "reasoning_required": True,
            "request_graph_match_required": True,
            "max_sequence_tokens": FULL_CONTEXT_TOKENS,
        },
        "cleanup": {
            "sandoq": {
                "assignment_measured_high_water": sandoq_evidence["cleanup"][
                    "assignment_measured_high_water"
                ],
                "failures": 0,
                "zero_drop": True,
            },
            "auth_rotation": {
                "atomic_same_path": True,
                "batch_heartbeats": sandoq_evidence["auth"]["batch_heartbeats"],
                "successful_replacements": sandoq_evidence["auth"]["successful_replacements"],
            },
            "vmvm": (
                {
                    "state": "passed",
                    "runtime_instances": vmvm_evidence["cleanup"]["runtime_instances"],
                    "cleanup_passes": vmvm_evidence["cleanup"]["cleanup_passes"],
                    "local_cleanup_failures": 0,
                    "release_on_exit_completed": vmvm_evidence["cleanup"][
                        "release_on_exit_completed"
                    ],
                }
                if vmvm_evidence is not None
                else {"state": "absent", "runtime_instances": 0, "cleanup_passes": 0}
            ),
        },
    }
    private_values = frozenset(
        {
            sandoq_certificate_sha256,
            vmvm_certificate_sha256,
            *_private_strings(materialization),
            *_private_strings(sandoq),
            *_private_strings(vmvm),
        }
    )
    _validate_public_privacy(public, private_values)
    return public


def _add_materialization_arguments(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--materialization-receipt-sha256", required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    _add_materialization_arguments(parser)
    parser.add_argument("--sandoq-certificate", type=Path, required=True)
    parser.add_argument("--sandoq-certificate-sha256", required=True)
    parser.add_argument("--vmvm-certificate", type=Path, required=True)
    parser.add_argument("--vmvm-certificate-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = provider_certificate.RepairMaterializationInputs(
        source=args.source,
        dataset=args.dataset,
        sandoq_template=args.sandoq_template,
        vmvm_template=args.vmvm_template,
        repair_selection_manifest=args.repair_selection_manifest,
        repair_selection_manifest_sha256=args.repair_selection_manifest_sha256,
        historical_source_dir=args.historical_source_dir,
        sandoq_tasks=args.sandoq_tasks,
        vmvm_tasks=args.vmvm_tasks,
        sandoq_config=args.sandoq_config,
        vmvm_config=args.vmvm_config,
        receipt=args.materialization_receipt,
        receipt_sha256=args.materialization_receipt_sha256,
        private_output_root=args.private_output_root,
    )
    try:
        value = certify_union(
            sandoq_certificate=args.sandoq_certificate,
            sandoq_certificate_sha256=args.sandoq_certificate_sha256,
            vmvm_certificate=args.vmvm_certificate,
            vmvm_certificate_sha256=args.vmvm_certificate_sha256,
            materialization_inputs=inputs,
        )
        digest = write_exclusive(args.output, value)
    except (OSError, RepairProviderUnionCertificateError) as error:
        code = (
            str(error)
            if isinstance(error, RepairProviderUnionCertificateError)
            else "certification_failed"
        )
        raise SystemExit(code) from None
    print(digest)


if __name__ == "__main__":
    main()
