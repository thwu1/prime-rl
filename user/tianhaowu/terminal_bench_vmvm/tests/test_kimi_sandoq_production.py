from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

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


def test_production_launcher_consumes_selector_bound_resource_coverage() -> None:
    launcher = (
        Path(__file__).parents[1]
        / "configs/eval/servers/cpu-132-021_8103/run_mobius_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()

    assert "blocked aggregate_resource_coverage_not_certified" not in launcher
    assert "selector receipt is rederived" in launcher


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


def test_resource_coverage_rederives_aggregate_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
