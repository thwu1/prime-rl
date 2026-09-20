from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import certify_direct_qwen_repair_provider as provider
import certify_direct_qwen_repair_provider_union as union
import materialize_qwen_repair_provider_union as materializer
import pytest
from audit_traces import qwen_repair_trace_contracts_value
from direct_qwen_union_contract import HOST_HARNESS_CONTRACT, canonical_json, sha256_bytes


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _materialization(vmvm_count: int) -> dict:
    sandoq_count = provider.EXPECTED_REPAIR_COUNT - vmvm_count
    return {
        "schema_version": 1,
        "kind": materializer.KIND,
        "state": "materialized",
        "deployment_namespace": materializer.DEPLOYMENT_NAMESPACE,
        "canonical_source": {
            "count": materializer.CANONICAL_SOURCE_COUNT,
            "sha256": materializer.CANONICAL_SOURCE_SHA256,
        },
        "repair_selection": {
            "count": provider.EXPECTED_REPAIR_COUNT,
            "manifest_sha256": "1" * 64,
            "source_partition": {
                "error_traces": 43,
                "exhaustive": True,
                "invalid_positive_traces": 82,
                "positive_reward_traces": 831,
                "repair_tasks": provider.EXPECTED_REPAIR_COUNT,
                "retained_original_tasks": 1_267,
                "retained_valid_positive_traces": 749,
                "reward_zero_traces": 518,
                "seen_traces": 1_392,
                "source_task_count": 2_500,
                "superseded_legacy_empty_reasoning_traces": 1,
                "unseen_tasks": 1_108,
            },
            "task_file_sha256": "2" * 64,
            "trace_contracts": qwen_repair_trace_contracts_value(),
            "union_indices_sha256": "3" * 64,
        },
        "partition": {
            "disjoint": True,
            "exhaustive": True,
            "sandoq_count": sandoq_count,
            "vmvm_count": vmvm_count,
            "total_count": provider.EXPECTED_REPAIR_COUNT,
        },
    }


def _shared_contract() -> dict:
    return {
        "contract": {
            "model": "Qwen3.8-2.4T-A95B",
            "pass_at_1": True,
            "num_rollouts": 1,
            "reasoning_effort": "high",
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
            "context_tokens": {
                "max_input_tokens": 262_144,
                "max_output_tokens": 262_144,
                "max_total_tokens": 262_144,
            },
            "sampling_max_tokens": 32_768,
            "capture_model_io": True,
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "return_token_ids",
                "top_logprobs",
            ],
            "retain_traces": False,
            "harness": HOST_HARNESS_CONTRACT,
        },
        "dataset": {"kind": "git_revision", "revision": "a" * 40},
        "deployment": {
            "endpoint_bundle_sha256": "4" * 64,
            "router": {
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "request_timeout_seconds": 7_200,
                "queue_timeout_seconds": 7_200,
                "retries": 0,
            },
            "spec_sha256": "5" * 64,
            "worker_count": 24,
            "worker_generation_sha256": "6" * 64,
        },
        "source": {
            "prime_rl_commit": "b" * 40,
            "prime_rl_tree_sha256": "7" * 64,
            "verifiers_commit": "c" * 40,
            "verifiers_tree_sha256": "8" * 64,
            "renderers_commit": "d" * 40,
            "renderers_tree_sha256": "9" * 64,
        },
    }


def _trace(count: int) -> dict:
    return {
        "traces": count,
        "tasks": count,
        "sampled_tokens": count * 10,
        "model_io_turns": count * 2,
        "provider_reported_zero_reasoning_tool_turns": 0,
        "provider_explicit_empty_reasoning_tool_turns": 0,
    }


def _cleanup(count: int) -> dict:
    return {
        "audit_sha256": "a" * 64,
        "assignment_attempts": count,
        "assignment_cancellations": 0,
        "assignment_measured_high_water": 64,
        "extra_assignment_attempts": 0,
        "gateway_close_warnings": 0,
        "outer_session_high_water": 64,
        "recorded_outer_sessions": 64,
        "recovered_poisoned_assignments": 0,
        "typed_http_404": 64,
        "zero_drop": True,
        "failures": 0,
    }


def _auth() -> dict:
    return {
        "audit_sha256": "b" * 64,
        "atomic_same_path": True,
        "batch_heartbeats": 3,
        "fail_closed_before_expiry_seconds": 1_800,
        "maximum_observed_refresh_gap_seconds": 1_000,
        "maximum_observed_heartbeat_gap_seconds": 60,
        "maximum_refresh_interval_seconds": 14_400,
        "minimum_observed_expiry_margin_seconds": 2_000,
        "run_duration_seconds": 3_600,
        "successful_replacements": 1,
    }


def _sandoq_certificate(materialization: dict, inputs: SimpleNamespace) -> dict:
    shared = _shared_contract()
    common = shared["source"]
    count = materialization["partition"]["sandoq_count"]
    return {
        "schema_version": 1,
        "kind": "direct-qwen-repair-sandoq-partition",
        "state": "passed",
        "sandbox_provider": "sandoq",
        "task_count": count,
        "selection": "sealed-repair-intersection",
        "lane_binding": {
            "task_file_sha256": _digest(inputs.sandoq_tasks.read_bytes()),
            "config_sha256": _digest(inputs.sandoq_config.read_bytes()),
            "eval_run_identity_sha256": "c" * 64,
            "results_sha256": "d" * 64,
            "worker_manifest_sha256": "e" * 64,
        },
        "worker_count": 24,
        "execution_proof": provider._sandoq_execution_proof(),
        "trace_audit": _trace(count),
        "pool_cleanup": _cleanup(count),
        "sanitized_cleanup_source_hashes": {
            "pool_drain_sha256": "1" * 64,
            "pool_event_log_sha256": "2" * 64,
            "pool_wal_sha256": "3" * 64,
            "raw_audit_sha256": "4" * 64,
        },
        "auth_rotation": _auth(),
        "predecessor": {"sha256": "5" * 64, "stage_count": 64},
        "materialization": materialization,
        "shared_contract": shared,
        "shared_contract_sha256": sha256_bytes(canonical_json(shared)),
        "provider_source": {
            "prime_rl_commit": common["prime_rl_commit"],
            "verifiers_commit": common["verifiers_commit"],
            "renderers_commit": common["renderers_commit"],
            "sandoq_provider_commit": "e" * 40,
            "sandoq_provider_tree": "f" * 40,
            "sandoq_client_version": "1.0",
            "sandoq_host_harness_sha256": "6" * 64,
            "sandoq_site_sha256": "7" * 64,
            "derived_image_manifest_sha256": "8" * 64,
            "direct_spec_sha256": shared["deployment"]["spec_sha256"],
            "direct_endpoint_bundle_sha256": shared["deployment"][
                "endpoint_bundle_sha256"
            ],
        },
    }


def _vmvm_certificate(materialization: dict, inputs: SimpleNamespace) -> dict:
    if materialization["partition"]["vmvm_count"] == 0:
        return {
            "schema_version": 1,
            "kind": "direct-qwen-repair-vmvm-absence",
            "state": "absent",
            "sandbox_provider": "vmvm",
            "task_count": 0,
            "selection": "sealed-repair-intersection",
            "lane_binding": {
                "task_file_sha256": _digest(inputs.vmvm_tasks.read_bytes()),
                "config_sha256": _digest(inputs.vmvm_config.read_bytes()),
            },
            "launch_evidence_present": False,
            "materialization": materialization,
        }
    shared = _shared_contract()
    common = shared["source"]
    return {
        "schema_version": 1,
        "kind": "direct-qwen-repair-vmvm-partition",
        "state": "passed",
        "sandbox_provider": "vmvm",
        "task_count": 1,
        "selection": "sealed-repair-intersection",
        "lane_binding": {
            "task_file_sha256": _digest(inputs.vmvm_tasks.read_bytes()),
            "config_sha256": _digest(inputs.vmvm_config.read_bytes()),
            "eval_run_identity_sha256": "f" * 64,
            "results_sha256": "0" * 64,
            "worker_manifest_sha256": "1" * 64,
        },
        "worker_count": 24,
        "execution_proof": provider._vmvm_execution_proof(),
        "trace_audit": _trace(1),
        "compose_proof": {
            "compose_count": 1,
            "network_policy": "both-phases-no-network",
            "runtime": "vmvm",
            "vmvm_tb_v2_sha256": "2" * 64,
        },
        "runtime_cleanup": {
            "state": "passed",
            "runtime_instances": 2,
            "cleanup_passes": 2,
            "agent_runtime_instances": 1,
            "verifier_runtime_instances": 1,
            "verifier_mode": "separate",
            "compose_runtime_instances": 1,
            "local_cleanup_failures": 0,
            "release_on_exit_completed": 2,
            "remote_deletion_verified": False,
        },
        "materialization": materialization,
        "shared_contract": shared,
        "shared_contract_sha256": sha256_bytes(canonical_json(shared)),
        "provider_source": {
            "prime_rl_commit": common["prime_rl_commit"],
            "verifiers_commit": common["verifiers_commit"],
            "renderers_commit": common["renderers_commit"],
            "vmvm_tb_v2_sha256": "2" * 64,
            "direct_spec_sha256": shared["deployment"]["spec_sha256"],
            "direct_endpoint_bundle_sha256": shared["deployment"][
                "endpoint_bundle_sha256"
            ],
        },
    }


def _inputs(tmp_path: Path, materialization: dict) -> SimpleNamespace:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    sandoq_tasks = private / "sandoq.tasks"
    vmvm_tasks = private / "vmvm.tasks"
    sandoq_config = private / "sandoq.toml"
    vmvm_config = private / "vmvm.toml"
    sandoq_tasks.write_bytes(b"sandoq-lane\n")
    vmvm_tasks.write_bytes(b"vmvm-lane\n" if materialization["partition"]["vmvm_count"] else b"")
    sandoq_config.write_bytes(b"sandoq-config\n")
    vmvm_config.write_bytes(b"vmvm-config\n")
    for path in (sandoq_tasks, vmvm_tasks, sandoq_config, vmvm_config):
        path.chmod(0o600)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    return SimpleNamespace(
        validate=lambda: copy.deepcopy(materialization),
        sandoq_tasks=sandoq_tasks,
        vmvm_tasks=vmvm_tasks,
        sandoq_config=sandoq_config,
        vmvm_config=vmvm_config,
        dataset=dataset,
        private_output_root=private,
    )


def _write_private(path: Path, value: dict) -> str:
    path.write_bytes(canonical_json(value))
    path.chmod(0o600)
    return _digest(path.read_bytes())


def _certify(tmp_path: Path, vmvm_count: int) -> tuple[dict, dict, dict]:
    materialization = _materialization(vmvm_count)
    inputs = _inputs(tmp_path, materialization)
    sandoq = _sandoq_certificate(materialization, inputs)
    vmvm = _vmvm_certificate(materialization, inputs)
    sandoq_path = inputs.private_output_root / "sandoq-certificate.json"
    vmvm_path = inputs.private_output_root / "vmvm-certificate.json"
    sandoq_sha = _write_private(sandoq_path, sandoq)
    vmvm_sha = _write_private(vmvm_path, vmvm)
    result = union.certify_union(
        sandoq_certificate=sandoq_path,
        sandoq_certificate_sha256=sandoq_sha,
        vmvm_certificate=vmvm_path,
        vmvm_certificate_sha256=vmvm_sha,
        materialization_inputs=inputs,
    )
    return result, sandoq, vmvm


def test_vmvm_execution_requires_c96_http48() -> None:
    execution = _vmvm_execution()

    provider._validate_vmvm_execution(execution)
    execution["rollout_concurrency"] = 64
    with pytest.raises(provider.RepairProviderCertificateError, match="^vmvm_execution_invalid$"):
        provider._validate_vmvm_execution(execution)


def _vmvm_execution() -> dict:
    return {
        "cleanup_must_succeed": True,
        "rollout_concurrency": 96,
        "multiplex": 96,
        "http_max_connections": 48,
        "http_max_keepalive_connections": 48,
        "cleanup_receipt_contract": {
            "kind": "vacli-release-on-exit-v1",
            "receipt": "private-aggregate-jsonl",
            "release_on_exit_completed": True,
            "remote_deletion_verified": False,
        },
        "runtime": {"type": "vmvm"},
    }


def test_sandoq_execution_requires_host_no_network_c64_http32_pool64() -> None:
    execution = _sandoq_execution()

    provider._validate_sandoq_execution(execution)
    execution["sandoq_environment"]["pool_size"] = 63
    with pytest.raises(provider.RepairProviderCertificateError, match="^sandoq_execution_invalid$"):
        provider._validate_sandoq_execution(execution)


def _sandoq_execution() -> dict:
    return {
        "cleanup_must_succeed": True,
        "rollout_concurrency": 64,
        "multiplex": 64,
        "http_max_connections": 32,
        "http_max_keepalive_connections": 32,
        "sandoq_environment": {
            "environment": "oci-runner-firecracker",
            "task_network": "none",
            "pool_size": 64,
            "pool_min_size": 0,
        },
        "runtime": {
            "type": "sandoq",
            "mode": "oci-runner",
            "network_access": False,
            "host_tunnel": "none",
            "expected_environment": "oci-runner-firecracker",
        },
    }


def test_sandoq_certificate_binds_dynamic_lane_and_stage64(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materialization = _materialization(0)
    inputs = _inputs(tmp_path, materialization)
    run_dir = tmp_path / "sandoq-run"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    for name in (".writer.lock", ".direct_router.lock"):
        (run_dir / name).touch(mode=0o600)
        (run_dir / name).chmod(0o600)
    shared = _shared_contract()
    envelope = {
        "eval_run_identity_sha256": "a" * 64,
        "identity": {
            "deployment": {"worker_manifest": {"sha256": "b" * 64}},
            "source": {},
        },
    }
    captured: dict[str, int] = {}
    monkeypatch.setattr(provider, "_load_identity", lambda **_kwargs: (envelope, shared, _sandoq_execution()))
    monkeypatch.setattr(provider.sandoq_evidence, "_provider_source", lambda _identity: {"source": "closed"})

    def predecessor(expected_count, *_args, **_kwargs):
        captured["predecessor_count"] = expected_count
        return {"sha256": "c" * 64, "stage_count": 64}

    def cleanup(_path, *, expected_task_count, expected_concurrency):
        captured["cleanup_count"] = expected_task_count
        captured["cleanup_concurrency"] = expected_concurrency
        return _cleanup(expected_task_count), {
            "pool_drain_sha256": "1" * 64,
            "pool_event_log_sha256": "2" * 64,
            "pool_wal_sha256": "3" * 64,
            "raw_audit_sha256": "4" * 64,
        }

    monkeypatch.setattr(provider.sandoq_ramp, "validate_predecessor", predecessor)
    monkeypatch.setattr(
        provider,
        "audit_results",
        lambda *_args: ("d" * 64, _trace(provider.EXPECTED_REPAIR_COUNT)),
    )
    monkeypatch.setattr(provider.sandoq_evidence, "validate_cleanup", cleanup)
    monkeypatch.setattr(provider.sandoq_evidence, "validate_auth_rotation", lambda *_args, **_kwargs: _auth())

    value = provider.certify_sandoq(
        run_dir=run_dir,
        task_file_sha256=_digest(inputs.sandoq_tasks.read_bytes()),
        config_sha256=_digest(inputs.sandoq_config.read_bytes()),
        cleanup_audit=tmp_path / "cleanup.json",
        auth_rotation_audit=tmp_path / "auth.json",
        predecessor=tmp_path / "predecessor.json",
        predecessor_sha256="c" * 64,
        materialization_inputs=inputs,
    )

    assert value["task_count"] == provider.EXPECTED_REPAIR_COUNT
    assert value["lane_binding"]["eval_run_identity_sha256"] == "a" * 64
    assert value["lane_binding"]["results_sha256"] == "d" * 64
    assert captured == {
        "predecessor_count": provider.CANONICAL_SANDOQ_COUNT,
        "cleanup_count": provider.EXPECTED_REPAIR_COUNT,
        "cleanup_concurrency": 64,
    }


def test_vmvm_repair_certificate_rejects_unexpected_selected_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materialization = _materialization(1)
    inputs = _inputs(tmp_path, materialization)
    run_dir = tmp_path / "vmvm-run"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    for name in (".writer.lock", ".direct_router.lock"):
        (run_dir / name).touch(mode=0o600)
        (run_dir / name).chmod(0o600)
    (run_dir / "results.jsonl").write_text("{}\n")
    shared = _shared_contract()
    envelope = {
        "eval_run_identity_sha256": "a" * 64,
        "identity": {
            "deployment": {"worker_manifest": {"sha256": "b" * 64}},
            "source": {"vmvm_tb_v2_sha256": "c" * 64},
        },
    }
    cleanup = {
        "state": "passed",
        "runtime_instances": 1,
        "cleanup_passes": 1,
        "agent_runtime_instances": 1,
        "verifier_runtime_instances": 0,
        "verifier_mode": "shared",
        "compose_runtime_instances": 1,
        "local_cleanup_failures": 0,
        "release_on_exit_completed": 1,
        "remote_deletion_verified": False,
    }
    monkeypatch.setattr(provider, "_load_identity", lambda **_kwargs: (envelope, shared, _vmvm_execution()))
    monkeypatch.setattr(provider, "audit_results", lambda *_args: ("d" * 64, _trace(1)))
    monkeypatch.setattr(provider.vmvm_evidence, "_verifier_mode_from_results", lambda _path: "shared")
    monkeypatch.setattr(
        provider.vmvm_evidence,
        "_read_private_lifecycle_receipts",
        lambda *_args, **_kwargs: frozenset({"0" * 32}),
    )
    monkeypatch.setattr(
        provider.vmvm_evidence,
        "_read_private_cleanup_receipts",
        lambda *_args, **_kwargs: cleanup,
    )
    monkeypatch.setattr(provider.vmvm_evidence, "_provider_source", lambda _identity: {"source": "closed"})

    with pytest.raises(
        provider.RepairProviderCertificateError,
        match="^repair_materialization_invalid$",
    ):
        provider.certify_vmvm(
            run_dir=run_dir,
            task_file_sha256=_digest(inputs.vmvm_tasks.read_bytes()),
            config_sha256=_digest(inputs.vmvm_config.read_bytes()),
            cleanup_receipt=tmp_path / "cleanup.jsonl",
            lifecycle_receipt=tmp_path / "lifecycle.jsonl",
            materialization_inputs=inputs,
        )


def test_vmvm_zero_lane_creates_absence_proof_without_run_inputs(
    tmp_path: Path,
) -> None:
    materialization = _materialization(0)
    inputs = _inputs(tmp_path, materialization)

    value = provider.certify_vmvm_absence(
        task_file_sha256=_digest(inputs.vmvm_tasks.read_bytes()),
        config_sha256=_digest(inputs.vmvm_config.read_bytes()),
        materialization_inputs=inputs,
    )

    assert value["state"] == "absent"
    assert value["task_count"] == 0
    assert value["launch_evidence_present"] is False
    assert "eval_run_identity_sha256" not in json.dumps(value)
    assert "results_sha256" not in json.dumps(value)


def test_vmvm_absence_rejects_selected_lane(tmp_path: Path) -> None:
    materialization = _materialization(1)
    inputs = _inputs(tmp_path, materialization)

    with pytest.raises(provider.RepairProviderCertificateError, match="^repair_materialization_invalid$"):
        provider.certify_vmvm_absence(
            task_file_sha256=_digest(inputs.vmvm_tasks.read_bytes()),
            config_sha256=_digest(inputs.vmvm_config.read_bytes()),
            materialization_inputs=inputs,
        )


def test_union_certifies_exact_repair_partition(tmp_path: Path) -> None:
    result, _sandoq, _vmvm = _certify(tmp_path, 0)

    assert result["task_count"] == provider.EXPECTED_REPAIR_COUNT
    assert result["partition"] == {
        "sandoq": provider.EXPECTED_REPAIR_COUNT,
        "vmvm": 0,
        "total": provider.EXPECTED_REPAIR_COUNT,
        "disjoint": True,
        "exhaustive": True,
        "member_details_public": False,
    }
    assert result["providers"]["vmvm"]["state"] == "absent"
    assert result["trace_audit"]["traces"] == provider.EXPECTED_REPAIR_COUNT
    assert result["generation"] == {"worker_count": 24, "provider_neutral": True}
    assert result["execution"]["vmvm"]["rollout_concurrency"] == 0


def test_union_rejects_any_unexpected_vmvm_repair_member(tmp_path: Path) -> None:
    materialization = _materialization(1)
    inputs = _inputs(tmp_path, materialization)
    sandoq = _sandoq_certificate(materialization, inputs)
    vmvm = _vmvm_certificate(materialization, inputs)
    private = inputs.private_output_root
    sandoq_path = private / "sandoq-certificate.json"
    vmvm_path = private / "vmvm-certificate.json"

    with pytest.raises(
        union.RepairProviderUnionCertificateError,
        match="^repair_materialization_invalid$",
    ):
        union.certify_union(
            sandoq_certificate=sandoq_path,
            sandoq_certificate_sha256=_write_private(sandoq_path, sandoq),
            vmvm_certificate=vmvm_path,
            vmvm_certificate_sha256=_write_private(vmvm_path, vmvm),
            materialization_inputs=inputs,
        )


def test_union_rejects_lane_artifact_drift(tmp_path: Path) -> None:
    materialization = _materialization(0)
    inputs = _inputs(tmp_path, materialization)
    sandoq = _sandoq_certificate(materialization, inputs)
    vmvm = _vmvm_certificate(materialization, inputs)
    sandoq["lane_binding"]["config_sha256"] = "0" * 64
    private = inputs.private_output_root
    sandoq_path = private / "sandoq-certificate.json"
    vmvm_path = private / "vmvm-certificate.json"

    with pytest.raises(
        union.RepairProviderUnionCertificateError,
        match="^provider_union_partition_invalid$",
    ):
        union.certify_union(
            sandoq_certificate=sandoq_path,
            sandoq_certificate_sha256=_write_private(sandoq_path, sandoq),
            vmvm_certificate=vmvm_path,
            vmvm_certificate_sha256=_write_private(vmvm_path, vmvm),
            materialization_inputs=inputs,
        )


def test_public_union_recursively_excludes_private_evidence(tmp_path: Path) -> None:
    result, sandoq, vmvm = _certify(tmp_path, 0)
    encoded = json.dumps(result, sort_keys=True)
    private_values = {
        *union._private_strings(sandoq),
        *union._private_strings(vmvm),
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = key.lower()
                assert key == "atomic_same_path" or not any(
                    fragment in lowered for fragment in union._PUBLIC_FORBIDDEN_FRAGMENTS
                )
                assert "task" not in lowered or key in union._PUBLIC_AGGREGATE_TASK_KEYS
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)
    assert all(private not in encoded for private in private_values)
    assert not any(
        union.SHA256_RE.fullmatch(item)
        for item in json.loads(json.dumps(list(_all_strings(result))))
    )


def _all_strings(value: object) -> set[str]:
    if isinstance(value, dict):
        return {item for child in value.values() for item in _all_strings(child)}
    if isinstance(value, list):
        return {item for child in value for item in _all_strings(child)}
    return {value} if isinstance(value, str) else set()


@pytest.mark.parametrize(
    "value",
    [
        {"config": 1},
        {"nested": {"results_sha256": "0" * 64}},
        {"nested": {"safe": "/private/path"}},
        {"nested": {"safe": "0" * 64}},
    ],
)
def test_public_privacy_guard_rejects_recursive_leaks(value: dict) -> None:
    with pytest.raises(
        union.RepairProviderUnionCertificateError,
        match="^public_union_privacy_violation$",
    ):
        union._validate_public_privacy(value, frozenset())


def test_private_certificate_reader_requires_mode_0600(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    certificate = private / "certificate.json"
    certificate.write_text("{}\n")
    certificate.chmod(0o644)

    with pytest.raises(
        union.RepairProviderUnionCertificateError,
        match="^provider_certificate_invalid$",
    ):
        union._load_private(certificate, _digest(certificate.read_bytes()))


def test_private_certificate_reader_rejects_hardlink(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    certificate = private / "certificate.json"
    _write_private(certificate, {"state": "passed"})
    os.link(certificate, private / "alias.json")

    with pytest.raises(
        union.RepairProviderUnionCertificateError,
        match="^provider_certificate_invalid$",
    ):
        union._load_private(certificate, _digest(certificate.read_bytes()))


def test_run_lock_rejects_active_router(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    writer = run_dir / ".writer.lock"
    router = run_dir / ".direct_router.lock"
    for path in (writer, router):
        path.touch(mode=0o600)
        path.chmod(0o600)
    with router.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(provider.RepairProviderCertificateError, match="^run_active$"):
            with provider._locked_run(run_dir):
                raise AssertionError("active router lock was accepted")


def test_private_certificate_writer_requires_private_parent(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir(mode=0o755)

    with pytest.raises(
        provider.RepairProviderCertificateError,
        match="^private_certificate_parent_invalid$",
    ):
        provider._write_private(public / "provider.json", {"state": "passed"})


def test_materialization_rejects_non_exact_union_count() -> None:
    value = _materialization(0)
    value["partition"]["total_count"] = 1_152

    with pytest.raises(
        provider.RepairProviderCertificateError,
        match="^repair_materialization_invalid$",
    ):
        provider._validate_materialization_value(value)
