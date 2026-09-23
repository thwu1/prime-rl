from __future__ import annotations

import hashlib
import json
import stat
import tomllib
from pathlib import Path

import direct_kimi_capacity as capacity
import pytest
from direct_qwen_union_contract import canonical_json
from direct_kimi_workers import _atomic_write


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}


def _private_file(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    path.chmod(0o600)
    return path.resolve()


def _selector_receipt(root: Path, selector_sha256: str) -> tuple[Path, str]:
    selection = {
        "algorithm": "sha256-canonical-index-v1",
        "candidate_count": capacity.CAPACITY_CANDIDATE_COUNT,
        "membership_disclosed": False,
        "selected_count": capacity.CAPACITY,
        "selected_sha256": selector_sha256,
    }
    value = {
        "schema_version": 1,
        "kind": capacity.CAPACITY_SELECTOR_KIND,
        "state": "materialized",
        "deployment_namespace": "cpu-132-021_8103",
        "approved_source": {
            "count": capacity.APPROVED_SOURCE_COUNT,
            "sha256": capacity.APPROVED_SOURCE_SHA256,
        },
        "dataset": {
            "revision": capacity.DATASET_REVISION,
            "tree": capacity.DATASET_TREE,
        },
        "selection": selection,
        # Match kimi_sandoq_production.materialize_capacity_selector, which
        # uses the shared newline-terminated canonical artifact encoding.
        "selection_contract_sha256": hashlib.sha256(canonical_json(selection)).hexdigest(),
    }
    path = _private_file(root / "capacity-selector-receipt.json", canonical_json(value))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_context(root: Path) -> Path:
    return _private_file(
        root / capacity.PROVIDER_CONTEXT_FILENAME,
        capacity._canonical_json(
            {
                "schema_version": 1,
                "kind": "sandoq-provider-context-snapshot",
                "state": "validated",
                "provider_environment": capacity.PROVIDER_ENVIRONMENT,
                "effective_task_network": "public",
                "task_network": capacity.PROVIDER_TASK_NETWORK,
                "network_access": True,
                "allow_dockerhub_fallback": False,
                "provider_profile_sha256": capacity.PROVIDER_PROFILE_SHA256,
                "provider_token_file_path_sha256": "9" * 64,
                "runtime_tunnel_receipt_sha256": capacity.RUNTIME_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": capacity.RUNTIME_RESOURCE_RECEIPT_SHA256,
                "provider_context_contract_sha256": "a" * 64,
            }
        ),
    )


def _install_live_smoke(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    relay = [
        {
            "call": index,
            "status_code": 200,
            "response_reasoning_present": True,
            "response_tool_calls": 1,
        }
        for index in range(1, 4)
    ]
    value = {
        "schema_version": 1,
        "kind": capacity.MINISWE_LIVE_SMOKE_KIND,
        "state": "passed",
        "sandbox_environment": capacity.MINISWE_LIVE_SMOKE_ENVIRONMENT,
        "task_network": capacity.PROVIDER_TASK_NETWORK,
        "model_calls": 3,
        "prior_reasoning_forwarded_calls": 2,
        "tool_result_forwarded_calls": 2,
        "program_exit_code": 0,
        "cleanup_verified": True,
        "relay_audit": relay,
        "trajectory_audit": {
            "mini_version": "2.4.6",
            "api_calls": 3,
            "assistant_reasoning_messages": 3,
            "native_submit_marker_actions": 1,
            "exit_status": "Submitted",
        },
    }
    path = _private_file(root / "miniswe-live-smoke.json", capacity._canonical_json(value))
    monkeypatch.setattr(capacity, "MINISWE_LIVE_SMOKE_RECEIPT", path)
    monkeypatch.setattr(
        capacity,
        "MINISWE_LIVE_SMOKE_RECEIPT_SHA256",
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    return path


def _capacity_certificate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    queue_overflow_rejections: int = 0,
    nonzero_tool_exits: int = 0,
) -> tuple[Path, str]:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    live_smoke = _install_live_smoke(root, monkeypatch)
    artifacts: dict[str, dict[str, str]] = {}
    for name in (
        "results",
        "eval_run_identity",
        "config_source",
        "config_resolved",
        "task_file",
        "worker_manifest",
        "capacity_probe",
        "router_receipt",
        "cleanup_audit",
    ):
        artifacts[name] = _artifact(_private_file(root / f"{name}.data", f"{name}\n".encode()))
    selector_receipt, selector_receipt_sha256 = _selector_receipt(
        root,
        artifacts["task_file"]["sha256"],
    )
    provider_context = _provider_context(root)
    provider_profile = capacity._provider_profile_path().resolve(strict=True)
    artifacts.update(
        {
            "capacity_selector_receipt": _artifact(selector_receipt),
            "provider_profile": _artifact(provider_profile),
            "provider_context": _artifact(provider_context),
            "runtime_tunnel_receipt": _artifact(capacity.RUNTIME_TUNNEL_RECEIPT),
            "runtime_resource_receipt": _artifact(capacity.RUNTIME_RESOURCE_RECEIPT),
            "miniswe_live_smoke_receipt": _artifact(live_smoke),
        }
    )
    unsigned = {
        "schema_version": capacity.CAPACITY_SCHEMA_VERSION,
        "kind": "direct-kimi-sandoq-capacity",
        "state": "passed",
        "model": "Kimi-K3",
        "capacity_profile": "sandoq-c64-v1",
        "qualified_concurrency": 64,
        "endpoint_identifier": "cpu-132-021_8103",
        "eval_run_identity_sha256": "1" * 64,
        "worker_manifest_sha256": artifacts["worker_manifest"]["sha256"],
        "endpoint_bundle_sha256": "3" * 64,
        "source": {
            "prime_rl_commit": "4" * 40,
            "prime_rl_tree_sha256": "5" * 64,
            "verifiers_commit": capacity.VERIFIERS_COMMIT,
            "router_implementation_sha256": "6" * 64,
            "sandoq_provider_commit": "7" * 40,
            "sandoq_provider_tree": "8" * 40,
        },
        "config": {
            "source_sha256": artifacts["config_source"]["sha256"],
            "resolved_sha256": artifacts["config_resolved"]["sha256"],
        },
        "selection": {
            "task_count": 64,
            "selector_sha256": artifacts["task_file"]["sha256"],
            "selector_receipt_sha256": selector_receipt_sha256,
        },
        "runtime": {
            "harness": {"id": "mini-swe-agent", "version": "2.4.6", "max_steps": 3},
            "sandbox": {
                "environment": capacity.PROVIDER_ENVIRONMENT,
                "task_network": "host",
                "effective_task_network": "public",
                "network_access": True,
                "host_tunnel": "sandoq",
                "guest_tunnel_url": "http://127.0.0.1:8485",
                "tunnel_pool_size": 4,
                "provider_profile_sha256": capacity.PROVIDER_PROFILE_SHA256,
                "provider_context_sha256": artifacts["provider_context"]["sha256"],
                "runtime_tunnel_receipt_sha256": capacity.RUNTIME_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": capacity.RUNTIME_RESOURCE_RECEIPT_SHA256,
            },
            "compatibility": {
                "kind": capacity.MINISWE_LIVE_SMOKE_KIND,
                "receipt_sha256": capacity.MINISWE_LIVE_SMOKE_RECEIPT_SHA256,
                "evidence_scope": "relay-reasoning-native-submission-only",
            },
        },
        "router": {
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "retries": 0,
            "configured_capacity": 64,
            "max_active_requests": 64,
            "max_active_chat_requests": 64,
            "capacity_rejections": queue_overflow_rejections,
            "queue_overflow_rejections": queue_overflow_rejections,
            "route_tracking_overflows": 0,
            "cross_route_anomalies": 0,
            "tracked_sessions": 64,
        },
        "probe": {
            "rounds": 2,
            "client_parallelism": 64,
            "successful_requests": 128,
            "receipt_sha256": artifacts["capacity_probe"]["sha256"],
        },
        "sandoq": {
            "assignment_event_order_high_water": 64,
            "assignment_measured_high_water": 64,
            "outer_session_high_water": 64,
            "assignments_acquired": 64,
            "assignments_cleanup_verified": 64,
            "outer_sessions_deleted": 64,
            "cleanup_gateway_retry_count": 0,
            "gateway_close_warnings": 0,
            "recovered_poisoned_assignments": 0,
            "failures": 0,
            "cleanup_audit_sha256": artifacts["cleanup_audit"]["sha256"],
        },
        "traces": {
            "count": 64,
            "model_io_turns": 64,
            "sampled_tokens": 64,
            "trace_failures": 0,
            "global_problem_count": 0,
            "tool_observations": 64,
            "successful_tool_exits": 64 - nonzero_tool_exits,
            "nonzero_tool_exits": nonzero_tool_exits,
            "results_sha256": artifacts["results"]["sha256"],
        },
        "artifacts": artifacts,
    }
    certificate = {
        **unsigned,
        "capacity_certificate_payload_sha256": hashlib.sha256(capacity._canonical_json(unsigned)).hexdigest(),
    }
    output = root / capacity.CAPACITY_FILENAME
    _atomic_write(output, capacity._canonical_json(certificate) + b"\n", exclusive=True)
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


def test_capacity_certificate_validator_accepts_exact_c64_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = _capacity_certificate(tmp_path, monkeypatch)

    certificate = capacity.validate_capacity_certificate(
        path,
        expected_sha256=digest,
        required_concurrency=64,
        expected_endpoint_identifier="cpu-132-021_8103",
        expected_worker_manifest_sha256=hashlib.sha256(
            (tmp_path / "private/worker_manifest.data").read_bytes()
        ).hexdigest(),
        expected_config_sha256=hashlib.sha256((tmp_path / "private/config_source.data").read_bytes()).hexdigest(),
    )

    assert certificate["qualified_concurrency"] == 64
    assert certificate["traces"]["successful_tool_exits"] == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_capacity_certificate_validator_rejects_any_queue_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = _capacity_certificate(tmp_path, monkeypatch, queue_overflow_rejections=1)

    with pytest.raises(capacity.DirectKimiCapacityError, match="capacity_certificate_not_qualified"):
        capacity.validate_capacity_certificate(path, expected_sha256=digest)


def test_capacity_certificate_validator_rejects_nonzero_tool_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = _capacity_certificate(tmp_path, monkeypatch, nonzero_tool_exits=1)

    with pytest.raises(capacity.DirectKimiCapacityError, match="capacity_certificate_not_qualified"):
        capacity.validate_capacity_certificate(path, expected_sha256=digest)


def test_materialize_capacity_config_binds_opaque_selector_receipt(tmp_path: Path) -> None:
    selector_root = tmp_path / "selector"
    selector_root.mkdir(mode=0o700)
    selector = _private_file(
        selector_root / "tasks.txt",
        "".join(f"opaque-{index:02d}\n" for index in range(64)).encode(),
    )
    selector_receipt, selector_receipt_sha256 = _selector_receipt(
        selector_root,
        hashlib.sha256(selector.read_bytes()).hexdigest(),
    )
    template = (
        Path(capacity.__file__).parent
        / "configs/eval/servers/cpu-132-021_8103/mobius_kimi_k3_sandoq_capacity64.example.toml"
    ).resolve()
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output = (output_root / "capacity.toml").resolve()

    summary = capacity.materialize_config(
        template,
        selector,
        selector_receipt,
        selector_receipt_sha256,
        output,
    )

    rendered = tomllib.loads(output.read_text())
    assert summary == {
        "config_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "task_file_sha256": hashlib.sha256(selector.read_bytes()).hexdigest(),
        "task_count": 64,
        "selector_receipt_sha256": selector_receipt_sha256,
    }
    assert rendered["harness"]["id"] == "mini-swe-agent"
    assert rendered["harness"]["version"] == "2.4.6"
    assert rendered["harness"]["runtime"]["expected_environment"] == capacity.PROVIDER_ENVIRONMENT
    assert rendered["harness"]["runtime"]["network_access"] is True
    assert rendered["harness"]["runtime"]["host_tunnel"] == "sandoq"
    assert "agent.step_limit=3" in rendered["harness"]["config_overrides"]


def test_tool_exit_observations_fail_closed() -> None:
    traces = [
        {
            "nodes": [
                {"message": {"role": "tool", "content": json.dumps({"returncode": 0})}},
                {"message": {"role": "tool", "content": json.dumps({"returncode": 1})}},
                {"message": {"role": "tool", "content": "not-json"}},
            ]
        }
    ]

    assert capacity._tool_exit_observations(traces) == (3, 1, 2)
