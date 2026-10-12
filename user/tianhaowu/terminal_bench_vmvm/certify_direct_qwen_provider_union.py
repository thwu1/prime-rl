#!/usr/bin/env python3
"""Compose provider-specific Qwen certificates into one exact 2,500-task proof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from direct_qwen_union_contract import (
    FULL_CONTEXT_TOKENS,
    HOST_HARNESS_CONTRACT,
    QWEN_MODEL,
    SHA256_RE,
    UnionContractError,
    canonical_json,
    read_regular,
    sha256_bytes,
    write_exclusive,
)
from materialize_qwen_provider_union import (
    CANONICAL_SOURCE_COUNT,
    SANDOQ_COUNT,
    VMVM_COUNT,
    receipt_value,
)


class ProviderUnionCertificateError(ValueError):
    pass


_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "certificate",
        "config_sha256",
        "eval_run_identity_sha256",
        "materialization",
        "predecessor",
        "provider_exports",
        "provider_certificates",
        "provider_partition_sha256",
        "results_sha256",
        "sanitized_cleanup",
        "sanitized_cleanup_source_hashes",
        "shared_contract",
        "shared_contract_sha256",
        "task_id",
        "task_ids",
        "task_file_sha256",
        "train_task_sha256",
        "validation_task_sha256",
        "worker_manifest_sha256",
    }
)


def _validate_public_union_privacy(value: object, private_digests: frozenset[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or key in _FORBIDDEN_PUBLIC_KEYS
                or key == "path"
                or (key.endswith("_path") and key != "atomic_same_path")
            ):
                raise ProviderUnionCertificateError("public_union_privacy_violation")
            _validate_public_union_privacy(item, private_digests)
        return
    if isinstance(value, list):
        for item in value:
            _validate_public_union_privacy(item, private_digests)
        return
    if isinstance(value, str) and value in private_digests:
        raise ProviderUnionCertificateError("public_union_privacy_violation")


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _load(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = read_regular(path)
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnionContractError) as error:
        raise ProviderUnionCertificateError("provider_certificate_invalid") from error
    if (
        SHA256_RE.fullmatch(expected_sha256 or "") is None
        or sha256_bytes(raw) != expected_sha256
        or not isinstance(value, dict)
    ):
        raise ProviderUnionCertificateError("provider_certificate_invalid")
    return value, raw


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
        or value["traces"] != expected_count
        or value["tasks"] != expected_count
        or value["model_io_turns"] < expected_count
    ):
        raise ProviderUnionCertificateError("provider_trace_audit_invalid")
    return dict(value)


def _validate_materialization(value: object) -> dict[str, Any]:
    public = receipt_value()
    expected = {
        "sha256",
        "deployment_namespace",
        "source",
        "dataset",
        "templates",
        "partition",
        "derivation_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or SHA256_RE.fullmatch(str(value.get("sha256", ""))) is None
        or value.get("deployment_namespace") != public["deployment_namespace"]
        or value.get("source") != public["source"]
        or value.get("dataset") != public["dataset"]
        or value.get("templates") != public["templates"]
        or value.get("partition") != public["partition"]
        or value.get("derivation_sha256") != public["derivation_sha256"]
    ):
        raise ProviderUnionCertificateError("materialization_proof_invalid")
    return dict(value)


def _validate_common(value: Mapping[str, Any], *, provider: str, count: int, kind: str) -> None:
    if (
        value.get("schema_version") != 1
        or value.get("kind") != kind
        or value.get("state") != "passed"
        or value.get("sandbox_provider") != provider
        or value.get("task_count") != count
        or value.get("worker_count") != 24
        or SHA256_RE.fullmatch(str(value.get("eval_run_identity_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("results_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("worker_manifest_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(value.get("shared_contract_sha256", ""))) is None
        or not isinstance(value.get("shared_contract"), dict)
        or sha256_bytes(canonical_json(value["shared_contract"])) != value["shared_contract_sha256"]
    ):
        raise ProviderUnionCertificateError("provider_certificate_invalid")
    _validate_trace(value.get("trace_audit"), count)
    _validate_materialization(value.get("materialization"))
    shared = value["shared_contract"]
    deployment = shared.get("deployment")
    source = shared.get("source")
    if (
        not isinstance(deployment, dict)
        or not isinstance(source, dict)
    ):
        raise ProviderUnionCertificateError("provider_certificate_invalid")


def _validate_sandoq(value: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "kind",
        "state",
        "sandbox_provider",
        "task_count",
        "selection",
        "eval_run_identity_sha256",
        "results_sha256",
        "worker_manifest_sha256",
        "worker_count",
        "trace_audit",
        "pool_cleanup",
        "sanitized_cleanup_source_hashes",
        "auth_rotation",
        "materialization",
        "predecessor",
        "shared_contract",
        "shared_contract_sha256",
        "provider_source",
    }
    if set(value) != expected or value.get("selection") != "canonical-non-compose":
        raise ProviderUnionCertificateError("provider_certificate_invalid")
    _validate_common(
        value,
        provider="sandoq",
        count=SANDOQ_COUNT,
        kind="direct-qwen-sandoq-partition",
    )
    cleanup = value.get("pool_cleanup")
    cleanup_keys = {
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
    count_keys = cleanup_keys - {"audit_sha256", "zero_drop"}
    source_hashes = value.get("sanitized_cleanup_source_hashes")
    if (
        not isinstance(cleanup, dict)
        or set(cleanup) != cleanup_keys
        or any(not _integer(cleanup.get(key)) for key in count_keys)
        or SHA256_RE.fullmatch(str(cleanup.get("audit_sha256", ""))) is None
        or cleanup.get("zero_drop") is not True
        or cleanup.get("failures") != 0
        or cleanup.get("assignment_measured_high_water") != 64
        or cleanup.get("outer_session_high_water", 0) < 64
        or cleanup.get("assignment_attempts", 0) < SANDOQ_COUNT
        or cleanup.get("typed_http_404") != cleanup.get("recorded_outer_sessions")
        or not isinstance(source_hashes, dict)
        or set(source_hashes)
        != {
            "pool_drain_sha256",
            "pool_event_log_sha256",
            "pool_wal_sha256",
            "raw_audit_sha256",
        }
        or any(SHA256_RE.fullmatch(str(item)) is None for item in source_hashes.values())
    ):
        raise ProviderUnionCertificateError("sandoq_cleanup_proof_invalid")
    auth = value.get("auth_rotation")
    auth_keys = {
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
    if (
        not isinstance(auth, dict)
        or set(auth) != auth_keys
        or SHA256_RE.fullmatch(str(auth.get("audit_sha256", ""))) is None
        or auth.get("atomic_same_path") is not True
        or any(not _integer(auth.get(key)) for key in auth_keys - {"audit_sha256", "atomic_same_path"})
        or auth.get("maximum_refresh_interval_seconds") != 14_400
        or auth.get("maximum_observed_refresh_gap_seconds", 14_401) > 14_400
        or auth.get("maximum_observed_heartbeat_gap_seconds", 301) > 300
        or auth.get("fail_closed_before_expiry_seconds", 0) < 1_800
        or auth.get("minimum_observed_expiry_margin_seconds", 0)
        < auth.get("fail_closed_before_expiry_seconds", 0)
    ):
        raise ProviderUnionCertificateError("auth_rotation_proof_invalid")
    predecessor = value.get("predecessor")
    if (
        not isinstance(predecessor, dict)
        or set(predecessor) != {"sha256", "stage_count"}
        or predecessor.get("stage_count") != 64
        or SHA256_RE.fullmatch(str(predecessor.get("sha256", ""))) is None
    ):
        raise ProviderUnionCertificateError("sandoq_predecessor_invalid")
    provider_source = value.get("provider_source")
    expected_source_keys = {
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
    shared = value["shared_contract"]
    if (
        not isinstance(provider_source, dict)
        or set(provider_source) != expected_source_keys
        or any(not isinstance(item, str) or not item for item in provider_source.values())
        or any(
            SHA256_RE.fullmatch(provider_source[key]) is None
            for key in (
                "sandoq_site_sha256",
                "sandoq_host_harness_sha256",
                "derived_image_manifest_sha256",
                "direct_spec_sha256",
                "direct_endpoint_bundle_sha256",
            )
        )
        or provider_source["direct_spec_sha256"] != shared["deployment"].get("spec_sha256")
        or provider_source["direct_endpoint_bundle_sha256"]
        != shared["deployment"].get("endpoint_bundle_sha256")
        or any(
            provider_source[key] != shared["source"].get(key)
            for key in ("prime_rl_commit", "verifiers_commit", "renderers_commit")
        )
    ):
        raise ProviderUnionCertificateError("sandoq_source_closure_invalid")


def _validate_vmvm(value: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "kind",
        "state",
        "sandbox_provider",
        "task_count",
        "selection",
        "eval_run_identity_sha256",
        "results_sha256",
        "worker_manifest_sha256",
        "worker_count",
        "trace_audit",
        "compose_proof",
        "runtime_cleanup",
        "materialization",
        "shared_contract",
        "shared_contract_sha256",
        "provider_source",
    }
    if set(value) != expected or value.get("selection") != "canonical-compose":
        raise ProviderUnionCertificateError("provider_certificate_invalid")
    _validate_common(
        value,
        provider="vmvm",
        count=VMVM_COUNT,
        kind="direct-qwen-vmvm-compose-partition",
    )
    compose = value.get("compose_proof")
    if (
        not isinstance(compose, dict)
        or set(compose) != {"compose_count", "network_policy", "runtime", "vmvm_tb_v2_sha256"}
        or compose.get("compose_count") != 1
        or compose.get("network_policy") != "both-phases-no-network"
        or compose.get("runtime") != "vmvm"
        or SHA256_RE.fullmatch(str(compose.get("vmvm_tb_v2_sha256", ""))) is None
    ):
        raise ProviderUnionCertificateError("vmvm_compose_proof_invalid")
    cleanup = value.get("runtime_cleanup")
    cleanup_keys = {
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
    if (
        not isinstance(cleanup, dict)
        or set(cleanup) != cleanup_keys
        or cleanup.get("state") != "passed"
        or cleanup.get("verifier_mode") not in {"shared", "separate"}
        or any(
            not _integer(cleanup.get(key))
            for key in cleanup_keys
            - {"state", "verifier_mode", "remote_deletion_verified"}
        )
        or cleanup.get("agent_runtime_instances") != 1
        or cleanup.get("cleanup_passes", 0) < cleanup.get("runtime_instances", 0)
        or cleanup.get("compose_runtime_instances") != 1
        or cleanup.get("local_cleanup_failures") != 0
        or cleanup.get("runtime_instances") != cleanup.get("release_on_exit_completed")
        or cleanup.get("runtime_instances")
        != cleanup.get("agent_runtime_instances") + cleanup.get("verifier_runtime_instances")
        or cleanup.get("verifier_runtime_instances")
        != (0 if cleanup.get("verifier_mode") == "shared" else 1)
        or cleanup.get("remote_deletion_verified") is not False
    ):
        raise ProviderUnionCertificateError("vmvm_cleanup_proof_invalid")
    provider_source = value.get("provider_source")
    expected_source_keys = {
        "prime_rl_commit",
        "verifiers_commit",
        "renderers_commit",
        "vmvm_tb_v2_sha256",
        "direct_spec_sha256",
        "direct_endpoint_bundle_sha256",
    }
    shared = value["shared_contract"]
    if (
        not isinstance(provider_source, dict)
        or set(provider_source) != expected_source_keys
        or any(not isinstance(item, str) or not item for item in provider_source.values())
        or any(
            SHA256_RE.fullmatch(provider_source[key]) is None
            for key in (
                "vmvm_tb_v2_sha256",
                "direct_spec_sha256",
                "direct_endpoint_bundle_sha256",
            )
        )
        or provider_source["vmvm_tb_v2_sha256"] != value["compose_proof"].get("vmvm_tb_v2_sha256")
        or provider_source["direct_spec_sha256"] != shared["deployment"].get("spec_sha256")
        or provider_source["direct_endpoint_bundle_sha256"]
        != shared["deployment"].get("endpoint_bundle_sha256")
        or any(
            provider_source[key] != shared["source"].get(key)
            for key in ("prime_rl_commit", "verifiers_commit", "renderers_commit")
        )
    ):
        raise ProviderUnionCertificateError("vmvm_source_closure_invalid")


def certify_union(
    *,
    sandoq_certificate: Path,
    sandoq_certificate_sha256: str,
    vmvm_certificate: Path,
    vmvm_certificate_sha256: str,
) -> dict[str, Any]:
    sandoq, _sandoq_raw = _load(sandoq_certificate, sandoq_certificate_sha256)
    vmvm, _vmvm_raw = _load(vmvm_certificate, vmvm_certificate_sha256)
    _validate_sandoq(sandoq)
    _validate_vmvm(vmvm)
    if (
        sandoq["shared_contract"] != vmvm["shared_contract"]
        or sandoq["shared_contract_sha256"] != vmvm["shared_contract_sha256"]
        or sandoq["materialization"] != vmvm["materialization"]
        or sandoq["eval_run_identity_sha256"] == vmvm["eval_run_identity_sha256"]
        or sandoq["results_sha256"] == vmvm["results_sha256"]
    ):
        raise ProviderUnionCertificateError("provider_union_mismatch")
    shared = sandoq["shared_contract"]
    if (
        shared.get("contract", {}).get("model") != QWEN_MODEL
        or shared.get("contract", {}).get("harness") != HOST_HARNESS_CONTRACT
        or shared.get("contract", {}).get("context_tokens")
        != {
            "max_input_tokens": FULL_CONTEXT_TOKENS,
            "max_output_tokens": FULL_CONTEXT_TOKENS,
            "max_total_tokens": FULL_CONTEXT_TOKENS,
        }
    ):
        raise ProviderUnionCertificateError("shared_contract_invalid")
    counts = {
        "sandoq": SANDOQ_COUNT,
        "vmvm": VMVM_COUNT,
        "total": SANDOQ_COUNT + VMVM_COUNT,
    }
    if counts["total"] != CANONICAL_SOURCE_COUNT:
        raise ProviderUnionCertificateError("provider_union_count_invalid")
    public = {
        "schema_version": 1,
        "kind": "direct-qwen-provider-union",
        "state": "passed",
        "task_count": CANONICAL_SOURCE_COUNT,
        "partition": {
            **counts,
            "compose_count": 1,
            "disjoint": True,
            "exhaustive": True,
            "member_commitments_public": False,
        },
        "providers": {
            "sandoq": {"state": "passed", "task_count": SANDOQ_COUNT},
            "vmvm": {"state": "passed", "task_count": VMVM_COUNT},
        },
        "execution_contract": {
            "contract": shared["contract"],
            "deployment": shared["deployment"],
        },
        "trace_audit": {
            "traces": sandoq["trace_audit"]["traces"] + vmvm["trace_audit"]["traces"],
            "tasks": sandoq["trace_audit"]["tasks"] + vmvm["trace_audit"]["tasks"],
            "model_io_turns": sandoq["trace_audit"]["model_io_turns"]
            + vmvm["trace_audit"]["model_io_turns"],
            "reasoning_required": True,
            "request_graph_match_required": True,
            "max_sequence_tokens": FULL_CONTEXT_TOKENS,
        },
        "cleanup": {
            "sandoq": {
                "assignment_measured_high_water": sandoq["pool_cleanup"][
                    "assignment_measured_high_water"
                ],
                "failures": sandoq["pool_cleanup"]["failures"],
                "recorded_outer_sessions": sandoq["pool_cleanup"]["recorded_outer_sessions"],
                "typed_http_404": sandoq["pool_cleanup"]["typed_http_404"],
                "zero_drop": sandoq["pool_cleanup"]["zero_drop"],
            },
            "auth_rotation": {
                "atomic_same_path": sandoq["auth_rotation"]["atomic_same_path"],
                "batch_heartbeats": sandoq["auth_rotation"]["batch_heartbeats"],
                "successful_replacements": sandoq["auth_rotation"]["successful_replacements"],
            },
            "vmvm": vmvm["runtime_cleanup"],
        },
    }
    _validate_public_union_privacy(
        public,
        frozenset(
            {
                sandoq_certificate_sha256,
                vmvm_certificate_sha256,
                sandoq["eval_run_identity_sha256"],
                vmvm["eval_run_identity_sha256"],
                sandoq["results_sha256"],
                vmvm["results_sha256"],
                sandoq["materialization"]["sha256"],
                sandoq["pool_cleanup"]["audit_sha256"],
                sandoq["auth_rotation"]["audit_sha256"],
                *sandoq["sanitized_cleanup_source_hashes"].values(),
            }
        ),
    )
    return public


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandoq-certificate", type=Path, required=True)
    parser.add_argument("--sandoq-certificate-sha256", required=True)
    parser.add_argument("--vmvm-certificate", type=Path, required=True)
    parser.add_argument("--vmvm-certificate-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    try:
        value = certify_union(**args)
        digest = write_exclusive(output, value)
    except (OSError, ProviderUnionCertificateError) as error:
        code = str(error) if isinstance(error, ProviderUnionCertificateError) else "certification_failed"
        raise SystemExit(code) from None
    print(digest)


if __name__ == "__main__":
    main()
