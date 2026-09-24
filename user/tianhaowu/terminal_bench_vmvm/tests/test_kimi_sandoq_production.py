from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

import direct_kimi_capacity
import direct_kimi_workers
import kimi_sandoq_production as production
import pytest
from direct_qwen_union_contract import canonical_json


def _private_file(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    path.chmod(0o600)
    return path


def test_materialize_config_binds_dynamic_certified_concurrency(tmp_path: Path) -> None:
    selector = tmp_path / "selector.txt"
    selector_sha256 = "1" * 64
    template = production._canonical_template_path().read_bytes()

    body = production.materialize_config(template, selector, selector_sha256, 37)
    value = tomllib.loads(body.decode())

    assert value["num_tasks"] == 2499
    assert value["max_concurrent"] == 37
    assert value["multiplex"] == 37
    assert value["client"]["max_connections"] == 37
    assert value["client"]["max_keepalive_connections"] == 37
    assert value["sampling"]["max_tokens"] == 32768
    assert value["max_total_tokens"] == 262144
    assert value["max_turns"] == 200
    assert value["taskset"]["task_file"] == str(selector)
    assert value["taskset"]["task_file_sha256"] == selector_sha256
    assert value["taskset"]["resource_multiplier"] == 1.0
    assert value["retries"]["rollout"]["max_retries"] == 0


def test_materialize_config_rejects_uncertified_capacity() -> None:
    with pytest.raises(production.KimiProductionError, match="requested_concurrency_invalid"):
        production.materialize_config(
            production._canonical_template_path().read_bytes(),
            Path("/private/selector.txt"),
            "2" * 64,
            65,
        )


def test_w2_attestation_versions_and_contract_are_explicit() -> None:
    assert production.SCHEMA_VERSION == 1
    assert production.PROMOTION_SCHEMA_VERSION == 2
    assert production.LAUNCH_SCHEMA_VERSION == 2
    assert production.TRACE_SCHEMA_VERSION == 2
    assert production._production_contracts()["capacity_profile"] == "sandoq-c64-w2-v1"
    assert production._production_contracts()["per_worker_capacity"] == 2
    assert production._production_contracts()["max_forwarded_capacity"] == 48


def test_launch_value_binds_w2_forwarding_capacity(tmp_path: Path) -> None:
    artifact = production.Artifact(str(tmp_path / "artifact"), 1, "1" * 64)
    launch = production._launch_value(
        source={"prime_rl_commit": "2" * 40},
        selector=artifact,
        selector_receipt=artifact,
        config=artifact,
        template=artifact,
        image_manifest=artifact,
        promotion=artifact,
        promotion_value={"promotion_sha256": "3" * 64},
        worker_manifest=artifact,
        worker_value={
            "endpoint_bundle_sha256": "4" * 64,
            "source_spec_sha256": "5" * 64,
            "workers": [{} for _index in range(24)],
            "router": {"implementation_sha256": "6" * 64},
        },
        concurrency=64,
        output_dir=tmp_path / "run",
    )

    assert launch["schema_version"] == 2
    assert launch["deployment"]["capacity_profile"] == "sandoq-c64-w2-v1"
    assert launch["deployment"]["per_worker_capacity"] == 2
    assert launch["deployment"]["max_forwarded_capacity"] == 48


def test_production_capacity_gate_requires_schema3_w2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = {
        "schema_version": 3,
        "kind": production.CAPACITY_KIND,
        "state": "passed",
        "capacity_profile": production.CAPACITY_PROFILE,
        "qualified_concurrency": 64,
        "endpoint_identifier": production.DEPLOYMENT_NAMESPACE,
        "worker_manifest_sha256": "1" * 64,
        "config": {"source_sha256": "2" * 64},
    }
    path = _private_file(tmp_path / "capacity.json", canonical_json(value))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        direct_kimi_capacity,
        "validate_capacity_certificate",
        lambda *_args, **_kwargs: value,
    )

    observed, artifact = production._validate_capacity_certificate(
        path,
        digest,
        required_concurrency=64,
    )

    assert observed == value
    assert artifact.sha256 == digest

    stale = {**value, "schema_version": 2, "capacity_profile": "sandoq-c64-v1"}
    stale_path = _private_file(tmp_path / "stale-capacity.json", canonical_json(stale))
    with pytest.raises(production.KimiProductionError, match="capacity_certificate_invalid"):
        production._validate_capacity_certificate(
            stale_path,
            hashlib.sha256(stale_path.read_bytes()).hexdigest(),
            required_concurrency=64,
        )


def test_w2_promotion_reuses_tb4_endpoint_with_new_capacity_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    artifact_path = _private_file(root / "evidence.json", b"{}\n")
    artifact = production.Artifact(
        str(artifact_path),
        artifact_path.stat().st_size,
        hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    )
    endpoint_bundle_sha256 = "1" * 64
    source_spec_sha256 = "2" * 64
    new_commit = "3" * 40
    new_tree = "4" * 64
    tb4 = {
        "schema_version": 3,
        "deployment": {
            "endpoint_bundle_sha256": endpoint_bundle_sha256,
            "source_spec_sha256": source_spec_sha256,
        },
    }
    capacity_value = {
        "qualified_concurrency": 64,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
        "source": {
            "prime_rl_commit": new_commit,
            "prime_rl_tree_sha256": new_tree,
            "verifiers_commit": production.VERIFIERS_COMMIT,
            "router_implementation_sha256": "5" * 64,
        },
    }
    monkeypatch.setattr(production, "_validate_tb4_certificate", lambda *_args: (tb4, artifact))
    monkeypatch.setattr(production, "_validate_recovery_receipt", lambda *_args, **_kwargs: artifact)
    monkeypatch.setattr(
        production,
        "_validate_capacity_certificate",
        lambda *_args, **_kwargs: (capacity_value, artifact),
    )
    monkeypatch.setattr(
        production,
        "_validate_miniswe_compatibility_receipt",
        lambda *_args: artifact,
    )
    output = root / "promotion.json"

    production.create_promotion(
        tb4_certificate=artifact_path,
        tb4_certificate_sha256=artifact.sha256,
        forced_delete_receipt=artifact_path,
        forced_delete_receipt_sha256=artifact.sha256,
        idle_recovery_receipt=artifact_path,
        idle_recovery_receipt_sha256=artifact.sha256,
        capacity_certificate=artifact_path,
        capacity_certificate_sha256=artifact.sha256,
        miniswe_compatibility_receipt=artifact_path,
        miniswe_compatibility_receipt_sha256=artifact.sha256,
        requested_concurrency=64,
        output=output,
        private_output_root=root,
    )

    value = json.loads(output.read_bytes())
    assert value["schema_version"] == 2
    assert value["endpoint"]["endpoint_bundle_sha256"] == endpoint_bundle_sha256
    assert value["endpoint"]["source_spec_sha256"] == source_spec_sha256
    assert value["capacity_source"]["prime_rl_commit"] == new_commit
    assert value["capacity_source"]["prime_rl_tree_sha256"] == new_tree
    assert value["contracts"]["capacity_profile"] == "sandoq-c64-w2-v1"
    assert value["contracts"]["per_worker_capacity"] == 2
    assert value["contracts"]["max_forwarded_capacity"] == 48

    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    validated, _artifact = production.validate_promotion(output, output_sha256, required_concurrency=64)
    assert validated == value

    for section, field, replacement in (
        ("endpoint", "endpoint_bundle_sha256", "9" * 64),
        ("endpoint", "source_spec_sha256", "9" * 64),
        ("endpoint", "router_implementation_sha256", "9" * 64),
        ("capacity_source", "prime_rl_commit", "9" * 40),
        ("capacity_source", "prime_rl_tree_sha256", "9" * 64),
    ):
        tampered = json.loads(json.dumps(value))
        tampered[section][field] = replacement
        unsigned = dict(tampered)
        unsigned.pop("promotion_sha256")
        tampered["promotion_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        tampered_path = _private_file(
            root / f"promotion-{section}-{field}.json",
            canonical_json(tampered),
        )
        with pytest.raises(production.KimiProductionError, match="promotion_certificate_invalid"):
            production.validate_promotion(
                tampered_path,
                hashlib.sha256(tampered_path.read_bytes()).hexdigest(),
                required_concurrency=64,
            )

    capacity_value["qualified_concurrency"] = 63
    with pytest.raises(production.KimiProductionError, match="promotion_certificate_invalid"):
        production.validate_promotion(output, output_sha256, required_concurrency=64)


def test_production_launcher_consumes_selector_bound_resource_coverage() -> None:
    launcher = (
        Path(__file__).parents[1]
        / "configs/eval/servers/cpu-132-021_8103/run_mobius_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()

    assert "blocked aggregate_resource_coverage_not_certified" not in launcher
    assert "selector receipt is rederived" in launcher


def _router_receipt(
    root: Path,
    *,
    active_forwarded_requests: int = 0,
    max_active_forwarded_requests: int = 1,
    worker_queue_timeouts: int = 0,
    upstream_http_429: int = 0,
    upstream_http_5xx: int = 0,
) -> tuple[Path, dict[str, object]]:
    value: dict[str, object] = {
        "schema_version": 4,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        "eval_run_identity_sha256": "1" * 64,
        "invocation_identity_sha256": "2" * 64,
        "worker_manifest_sha256": "3" * 64,
        "endpoint_bundle_sha256": "4" * 64,
        "active_workers": 24,
        "implementation": production.ROUTER_IMPLEMENTATION,
        "implementation_sha256": "5" * 64,
        "policy": "consistent_hash",
        "request_id_headers": ["x-session-id"],
        "request_timeout_seconds": 43_200,
        "retries": 0,
        "source_generation_revalidated": True,
        "max_active_requests": 64,
        "total_requests": 8,
        "chat_requests": 8,
        "worker_request_counts_sha256": "6" * 64,
        "capacity_profile": production.CAPACITY_PROFILE,
        "endpoint_identifier": production.DEPLOYMENT_NAMESPACE,
        "configured_capacity": production.MAX_CAPACITY,
        "configured_per_worker_capacity": production.PER_WORKER_CAPACITY,
        "active_forwarded_requests": active_forwarded_requests,
        "max_active_forwarded_requests": max_active_forwarded_requests,
        "worker_max_active_request_counts_sha256": "7" * 64,
        "max_active_chat_requests": 64,
        "capacity_rejections": 0,
        "queue_overflow_rejections": 0,
        "route_tracking_overflows": 0,
        "cross_route_anomalies": 0,
        "worker_queue_timeouts": worker_queue_timeouts,
        "upstream_http_429": upstream_http_429,
        "upstream_http_5xx": upstream_http_5xx,
        "tracked_sessions": 8,
    }
    return _private_file(root / "router-final.json", canonical_json(value)), value


def test_production_router_receipt_accepts_unsaturated_w2_peak(tmp_path: Path) -> None:
    path, _value = _router_receipt(tmp_path, max_active_forwarded_requests=17)

    artifact, value = production._validate_router_receipt(
        path,
        identity_sha256="1" * 64,
        worker_manifest_sha256="3" * 64,
        endpoint_bundle_sha256="4" * 64,
        router_implementation_sha256="5" * 64,
        concurrency=64,
        minimum_chat_requests=1,
    )

    assert artifact.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert value["max_active_forwarded_requests"] == 17


@pytest.mark.parametrize(
    "overrides",
    (
        {"active_forwarded_requests": 1},
        {"max_active_forwarded_requests": 49},
        {"worker_queue_timeouts": 1},
        {"upstream_http_429": 1},
        {"upstream_http_5xx": 1},
    ),
)
def test_production_router_receipt_rejects_invalid_w2_evidence(
    tmp_path: Path,
    overrides: dict[str, int],
) -> None:
    path, _value = _router_receipt(tmp_path, **overrides)

    with pytest.raises(production.KimiProductionError, match="router_receipt_invalid"):
        production._validate_router_receipt(
            path,
            identity_sha256="1" * 64,
            worker_manifest_sha256="3" * 64,
            endpoint_bundle_sha256="4" * 64,
            router_implementation_sha256="5" * 64,
            concurrency=64,
            minimum_chat_requests=1,
        )


def test_production_worker_manifest_requires_schema3_w2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_file(tmp_path / "workers.json", b"opaque\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 3,
        "source_spec_sha256": "1" * 64,
        "endpoint_bundle_sha256": "2" * 64,
        "workers": [{} for _index in range(24)],
        "router": {
            "implementation": production.ROUTER_IMPLEMENTATION,
            "implementation_sha256": "3" * 64,
            "capacity_profile": production.CAPACITY_PROFILE,
            "endpoint_identifier": production.DEPLOYMENT_NAMESPACE,
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "max_concurrent_requests": 64,
            "per_worker_capacity": 2,
            "retries": 0,
        },
    }
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda _path: manifest)

    value, artifact = production._validate_worker_manifest(path, digest)

    assert value == manifest
    assert artifact.sha256 == digest

    manifest["router"]["per_worker_capacity"] = 1
    with pytest.raises(production.KimiProductionError, match="worker_manifest_invalid"):
        production._validate_worker_manifest(path, digest)


def test_selector_receipt_is_aggregate_only() -> None:
    body = b"opaque-a\nopaque-b\n"
    coverage = {
        "schema_version": 1,
        "kind": "declared-resource-envelope-v1",
        "selected_count": 2499,
        "membership_disclosed": False,
    }
    receipt = production._selector_receipt(body, coverage)
    rendered = canonical_json(receipt)

    assert receipt["selection"]["membership_disclosed"] is False
    assert receipt["selection"]["excluded_count"] == 1
    assert receipt["selection"]["selected_count"] == 2499
    assert receipt["resource_coverage"] == coverage
    assert receipt["resource_coverage_sha256"] == hashlib.sha256(canonical_json(coverage)).hexdigest()
    assert b"opaque-a" not in rendered
    assert b"opaque-b" not in rendered


def _write_synthetic_task(
    dataset: Path,
    member: str,
    *,
    cpus: int,
    memory_mb: int,
    storage_mb: int,
) -> None:
    task_dir = dataset / member
    task_dir.mkdir()
    (task_dir / "task.toml").write_text(
        "\n".join(
            (
                "[environment]",
                f"cpus = {cpus}",
                f"memory_mb = {memory_mb}",
                f"storage_mb = {storage_mb}",
                "gpus = 0",
                "",
                "[verifier]",
                'environment_mode = "shared"',
                "",
            )
        )
    )


def test_resource_coverage_rederives_aggregate_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(production, "EXPECTED_TASK_COUNT", 2)
    _write_synthetic_task(tmp_path, "synthetic-a", cpus=1, memory_mb=2048, storage_mb=10240)
    _write_synthetic_task(tmp_path, "synthetic-b", cpus=2, memory_mb=4096, storage_mb=10240)

    coverage = production._resource_coverage(tmp_path, ("synthetic-a", "synthetic-b"))
    rendered = canonical_json(coverage)

    assert coverage["selected_count"] == 2
    assert coverage["verifier_modes"] == {"shared": 2, "separate": 0}
    assert coverage["agent_maximum"] == {
        "cpu_cores": 2.0,
        "memory_gib": 4.0,
        "disk_gib": 10.0,
    }
    assert coverage["verifier_maximum"] == coverage["agent_maximum"]
    assert coverage["all_selected_within_qualified_request"] is True
    assert coverage["membership_disclosed"] is False
    assert b"synthetic-a" not in rendered
    assert b"synthetic-b" not in rendered


def test_resource_coverage_fails_closed_above_qualified_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(production, "EXPECTED_TASK_COUNT", 1)
    _write_synthetic_task(tmp_path, "synthetic-a", cpus=3, memory_mb=4096, storage_mb=10240)

    with pytest.raises(production.KimiProductionError, match="resource_coverage_invalid"):
        production._resource_coverage(tmp_path, ("synthetic-a",))


def test_capacity_selector_is_deterministic_and_receipt_stays_aggregate_only() -> None:
    members = tuple(f"opaque-{index:04d}" for index in range(production.EXPECTED_TASK_COUNT))

    selected = production._opaque_capacity_members(members)

    assert len(selected) == 64
    assert len(set(selected)) == 64
    assert selected == production._opaque_capacity_members(members)
    rendered = canonical_json(
        {
            "algorithm": "sha256-canonical-index-v1",
            "candidate_count": len(members),
            "membership_disclosed": False,
            "selected_count": len(selected),
            "selected_sha256": hashlib.sha256(("\n".join(selected) + "\n").encode()).hexdigest(),
        }
    )
    assert all(member.encode() not in rendered for member in selected)


def test_tb4_promotion_revalidates_complete_official_certificate(tmp_path: Path) -> None:
    artifact_names = {
        "cleanup_audit",
        "config",
        "eval_invocations",
        "eval_run_identity",
        "inputs_manifest",
        "provenance",
        "results",
        "router_receipt",
        "smoke_checkpoint",
    }
    artifacts = {}
    for name in artifact_names:
        artifact = tmp_path / name
        artifact.write_bytes(f"{name}\n".encode())
        artifacts[name] = {
            "path": str(artifact),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    passes = 7
    unsigned = {
        "schema_version": 1,
        "kind": production.TB4_KIND,
        "state": "passed",
        "model": production.MODEL,
        "eval_run_identity_sha256": "1" * 64,
        "results_sha256": artifacts["results"]["sha256"],
        "task_file_sha256": "2" * 64,
        "worker_manifest_sha256": "5" * 64,
        "source_spec_sha256": "3" * 64,
        "endpoint_bundle_sha256": "4" * 64,
        "worker_count": 24,
        "counts": {
            "observed_traces": 66,
            "supported_tasks": 63,
            "cpu_unsupported_tasks": 3,
            "supported_passes": passes,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "scores": {
            "supported_pass_rate": passes / 63,
            "all_task_pass_rate": passes / 66,
        },
        "policy": {
            "expected_tasks": 66,
            "expected_supported_tasks": 63,
            "rollouts_per_task": 1,
            "max_sequence_tokens": 262144,
            "min_supported_pass_rate": 0.04,
            "max_supported_pass_rate": 0.22,
            "router_policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "request_timeout_seconds": 43200,
            "retries": 0,
        },
        "pool_cleanup": {
            "audit_sha256": artifacts["cleanup_audit"]["sha256"],
            "assignment_measured_high_water": 24,
            "outer_session_high_water": 24,
            "failures": 0,
        },
        "artifacts": artifacts,
    }
    certificate = {
        **unsigned,
        "tb4_certificate_sha256": hashlib.sha256(canonical_json(unsigned)).hexdigest(),
    }
    path = tmp_path / "tb4-certificate.json"
    path.write_bytes(canonical_json(certificate))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    value, observed = production._validate_tb4_certificate(path, digest)

    assert value["counts"]["supported_passes"] == passes
    assert observed.sha256 == digest

    Path(artifacts["results"]["path"]).write_bytes(b"changed\n")
    with pytest.raises(production.KimiProductionError, match="tb4_artifact_changed"):
        production._validate_tb4_certificate(path, digest)


@pytest.mark.parametrize(
    ("mode", "idle_seconds"),
    (("forced-delete", 0), ("idle-endurance", 3900)),
)
def test_recovery_receipts_bind_long_lease_contract(tmp_path: Path, mode: str, idle_seconds: int) -> None:
    path = _private_file(
        tmp_path / f"{mode}.json",
        canonical_json(
            {
                "schema_version": 4,
                "state": "passed",
                "probe_kind": "task-free-managed-shell-recovery",
                "mode": mode,
                "idle_seconds": idle_seconds,
                "lease_profile": "kimi-tb4-long",
                "lease_duration": "12h",
                "renewal_interval": "5m",
                "recovery_policy": "definitive-404-410-single-replay-v1",
                "provider_environment": "oci-runner-firecracker",
                "task_network": "host",
                "network_access": True,
                "host_tunnel": "sandoq",
                "provider_token_file_path_sha256": production.FIRECRACKER_PROVIDER_TOKEN_PATH_SHA256,
                "provider_profile_sha256": production.PROVIDER_PROFILE_SHA256,
                "runtime_tunnel_receipt_sha256": production.RUNTIME_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": production.RUNTIME_RESOURCE_RECEIPT_SHA256,
                "miniswe_compatibility_receipt_sha256": production.MINISWE_COMPATIBILITY_SHA256,
                "provider_context_contract_sha256": "f" * 64,
                "outer_cleanup_verified": True,
                "duration_seconds": 1.5,
                "shell_replaced": True,
                "managed_shell_recovery_count": 1,
                "state_preserved": True,
            }
        ),
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    artifact = production._validate_recovery_receipt(path, digest, mode=mode)

    assert artifact.sha256 == digest


def _trace(index: int, outcome: str) -> dict[str, object]:
    value: dict[str, object] = {
        "id": f"trace-{index}",
        "task": {"slug": f"opaque-{index:04d}"},
        "errors": [],
        "rewards": {"reward": 0},
        "nodes": [],
    }
    if outcome == "positive":
        value["rewards"] = {"reward": 1}
    elif outcome == "error":
        value["errors"] = [{"category": "aggregate"}]
    return value


def test_pass_only_audit_accepts_exact_coverage_with_aggregate_errors(tmp_path: Path) -> None:
    selector = _private_file(
        tmp_path / "selector.txt",
        b"".join(f"opaque-{index:04d}\n".encode() for index in range(production.EXPECTED_TASK_COUNT)),
    )
    rows = []
    for index in range(production.EXPECTED_TASK_COUNT):
        outcome = "positive" if index == 0 else "error" if index == 1 else "zero"
        rows.append(canonical_json(_trace(index, outcome)))
    results = _private_file(tmp_path / "results.jsonl", b"".join(rows))

    audit = production.audit_pass_only_results(results, selector, trace_validator=lambda _trace: None)

    assert audit.traces == 2499
    assert audit.positive_traces == 1
    assert audit.error_traces == 1
    assert audit.zero_reward_traces == 2497


def test_pass_only_audit_rejects_duplicate_task_coverage(tmp_path: Path) -> None:
    selector = _private_file(
        tmp_path / "selector.txt",
        b"".join(f"opaque-{index:04d}\n".encode() for index in range(production.EXPECTED_TASK_COUNT)),
    )
    rows = [_trace(index, "zero") for index in range(production.EXPECTED_TASK_COUNT)]
    rows[-1]["task"] = {"slug": "opaque-0000"}
    results = _private_file(tmp_path / "results.jsonl", b"".join(canonical_json(row) for row in rows))

    with pytest.raises(production.KimiProductionError, match="trace_identity_invalid"):
        production.audit_pass_only_results(results, selector, trace_validator=lambda _trace: None)


def test_terminal_receipt_accepts_failed_but_quiescent_generation(tmp_path: Path) -> None:
    provenance = _private_file(tmp_path / "provenance.txt", b"slurm_job_id=12345\n")
    output = tmp_path / "terminal.json"

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if command[0] == "sacct":
            return subprocess.CompletedProcess(command, 0, b"12345|FAILED|1:0|1:0|0|cluster-a\n", b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    summary = production.record_terminal_job(provenance=provenance, output=output, runner=runner)

    assert summary == {"state": "terminal", "scheduler_state": "FAILED", "job_id": "12345"}
    assert stat_mode(output) == 0o600
    assert json.loads(output.read_text())["queue_rows"] == 0


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
