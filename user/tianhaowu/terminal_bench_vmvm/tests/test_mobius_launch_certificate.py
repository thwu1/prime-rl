from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import mobius_launch_certificate as certificate_module
import pytest
from deployment_endpoint import load_deployment_endpoint
from deployment_proxy_policy import load_deployment_proxy_policy
from guard_success_receipt import (
    build_guard_success_receipt,
    write_guard_success_receipt,
)
from mobius_launch_certificate import (
    LaunchCertificateError,
    create_launch_certificate,
    main,
    validate_launch_certificate_for_run,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import ConcurrencyTelemetry


@pytest.fixture(autouse=True)
def _strict_identity_loader(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def load(path: Path, *, verify_references: bool) -> dict:
        calls.append(path)
        return json.loads(path.read_text())

    monkeypatch.setattr(certificate_module, "load_eval_run_identity", load)
    return calls


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return _sha256(path.read_bytes())


def _flat_certificate(body: dict, hash_field: str) -> dict:
    return {**body, hash_field: _sha256(_canonical(body))}


def _artifact(path: Path, digest: str = "a" * 64) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": digest}


def test_sharded_tb4_checkpoint_uses_isolated_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {
        "certificate_sha256": "a" * 64,
        "deployment_spec_sha256": "b" * 64,
        "expected_routes": 1,
        "route_generation_sha256s": ["c" * 64],
        "endpoint_binding_sha256s": ["d" * 64],
        "proxy_policy_sha256": "e" * 64,
        "shard_count": 17,
        "supported_pass_rate": 4 / 63,
        "all_task_pass_rate": 4 / 66,
        "supported_passes": 4,
        "sharded": True,
    }
    calls: list[str] = []

    def validate(value: dict, *, deployment_id: str) -> dict:
        assert value == {"schema_version": 2}
        calls.append(deployment_id)
        return expected

    monkeypatch.setattr(certificate_module, "validate_sharded_checkpoint", validate)
    assert (
        certificate_module._validate_tb4_checkpoint(
            {"schema_version": 2},
            "deployment-test",
            {},
        )
        == expected
    )
    assert calls == ["deployment-test"]


def test_sharded_tb4_gate_record_uses_generation_digests_only() -> None:
    validated = {
        "certificate_sha256": "a" * 64,
        "deployment_spec_sha256": "b" * 64,
        "expected_routes": 1,
        "route_generation_sha256s": ["c" * 64],
        "endpoint_binding_sha256s": ["d" * 64],
        "proxy_policy_sha256": "e" * 64,
        "shard_count": 17,
        "supported_pass_rate": 4 / 63,
        "supported_passes": 4,
        "sharded": True,
    }
    record = certificate_module._tb4_gate_record(
        {"path": "/private/checkpoint", "sha256": "f" * 64},
        validated,
    )
    assert record["sharded"] is True
    assert record["shard_count"] == 17
    assert "serving_route_generation" not in record
    assert "proxy_policy" not in record


def _route_generation(count: int, *, first_job_id: int) -> dict:
    return {
        "schema_version": 2,
        "coordinator": {
            "slurm_job_id": "900",
            "started_at": "2026-09-17T00:00:00Z",
        },
        "proxy": {
            "slurm_job_id": "12345",
            "first_ready_at": "2026-09-17T00:30:00Z",
        },
        "routes": [
            {
                "slurm_job_id": str(first_job_id + index),
                "started_at": "2026-09-17T01:00:00Z",
                "backend_sha256": f"backend-sha256:{hashlib.sha256(f'http://worker-{index}:{8000 + index}/v1'.encode()).hexdigest()}",
            }
            for index in range(count)
        ],
    }


def _vmvm_sha256(project: Path) -> str:
    digest = hashlib.sha256()
    source_root = project / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    for path in sorted(source_root.glob("*.py")):
        relative = path.relative_to(project).as_posix()
        digest.update(f"{_sha256(path.read_bytes())}  {relative}\n".encode())
    return digest.hexdigest()


def _tb4_checkpoint(
    path: Path,
    deployment_id: str,
    endpoint: dict,
    route_generation: dict,
    proxy_policy: dict,
    spec_sha256: str,
) -> str:
    run_dir = path.parent / "tb4-run"
    run_dir.mkdir()
    artifact_paths = {
        name: run_dir / ("results.jsonl" if name == "results" else f"tb4-{name}.metadata")
        for name in (
            "results",
            "config",
            "inputs_manifest",
            "provenance",
            "readiness_checkpoint",
            "smoke_checkpoint",
        )
    }
    for artifact in artifact_paths.values():
        artifact.write_text("aggregate metadata\n")
    artifacts = {name: _artifact(artifact, _sha256(artifact.read_bytes())) for name, artifact in artifact_paths.items()}
    artifacts["proxy_info"] = endpoint["proxy_info"]
    identity_path = run_dir / "eval_run_identity.json"
    identity = {
        "role": "tb4",
        "config": {"resolved": artifacts["config"]},
        "inputs": {
            "manifest": artifacts["inputs_manifest"],
            "task_file": {**artifacts["inputs_manifest"], "count": 66},
        },
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": route_generation,
            "proxy_policy": proxy_policy,
            "spec": {"path": str(path.parent / "tb4-spec.metadata"), "sha256": spec_sha256},
            "readiness_checkpoint": artifacts["readiness_checkpoint"],
            "smoke_checkpoint": artifacts["smoke_checkpoint"],
        },
    }
    _write_json(
        identity_path,
        {
            "schema_version": 1,
            "eval_run_identity_sha256": "1" * 64,
            "identity": identity,
        },
    )
    artifacts["eval_run_identity"] = _artifact(identity_path, _sha256(identity_path.read_bytes()))
    invocations = run_dir / "eval_invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": "1" * 64,
                "role": "tb4",
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "1",
            }
        )
        + "\n"
    )
    guard_receipt_path = run_dir / "route_guard_success.json"
    guard_receipt = build_guard_success_receipt(
        eval_run_identity_sha256="1" * 64,
        eval_run_role="tb4",
        eval_run_identity=identity_path,
        eval_invocations=invocations,
        results=artifact_paths["results"],
        deployment_id=deployment_id,
        deployment_spec_sha256=spec_sha256,
        readiness_checkpoint=artifact_paths["readiness_checkpoint"],
        readiness_checkpoint_sha256=artifacts["readiness_checkpoint"]["sha256"],
        endpoint=endpoint,
        serving_route_generation=route_generation,
        proxy_policy=proxy_policy,
    )
    write_guard_success_receipt(guard_receipt_path, guard_receipt)
    artifacts["eval_invocations"] = _artifact(invocations, _sha256(invocations.read_bytes()))
    artifacts["route_guard_success"] = _artifact(
        guard_receipt_path,
        _sha256(guard_receipt_path.read_bytes()),
    )
    body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "eval_run_identity_sha256": "1" * 64,
        "deployment": {"id": deployment_id, "spec_sha256": spec_sha256},
        "endpoint": endpoint,
        "serving_route_generation": route_generation,
        "proxy_policy": proxy_policy,
        "audit_policy": {
            "expected_tasks": 66,
            "expected_supported_tasks": 63,
            "expected_cpu_unsupported_tasks": 3,
            "rollouts_per_task": 1,
            "model": "Kimi-K3",
            "model_io_contract": certificate_module.EXPECTED_MODEL_IO_CONTRACT,
            "reasoning_effort": "max",
            "max_sequence_tokens": 262_144,
            "rollout_concurrency": 4,
            "lease_start_concurrency": 2,
            "require_reasoning": True,
            "require_response": True,
            "require_model_io": True,
            "require_tool_schemas": True,
            "require_tool_call_lineage": True,
            "require_token_data": False,
            "require_logprobs": False,
            "binary_solved_reward": True,
            "min_supported_pass_rate": 0.04,
            "max_supported_pass_rate": 0.22,
        },
        "counts": {
            "observed_traces": 66,
            "supported_tasks": 63,
            "cpu_unsupported_tasks": 3,
            "supported_passes": 6,
            "trace_failures": 0,
            "supported_trace_failures": 0,
            "cpu_unsupported_trace_failures": 0,
            "global_problems": 0,
        },
        "scores": {
            "supported_pass_rate": 6 / 63,
            "all_task_pass_rate": 6 / 66,
        },
        "artifacts": artifacts,
    }
    return _write_json(path, _flat_certificate(body, "tb4_certificate_sha256"))


def _readiness_checkpoint(
    path: Path,
    deployment_id: str,
    spec_sha256: str,
    endpoint: dict,
    route_generation: dict,
    proxy_policy: dict,
) -> str:
    expected_routes = len(route_generation["routes"])
    backends = sorted(route["backend_sha256"] for route in route_generation["routes"])
    return _write_json(
        path,
        {
            "schema_version": 1,
            "deployment": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": route_generation,
            "proxy_policy": proxy_policy,
            "expected_routes": expected_routes,
            "required_consecutive_polls": 3,
            "max_consecutive_status_unavailable": 10,
            "updated_at": "2026-09-16T00:00:00Z",
            "state": "passed",
            "polls": 10,
            "consecutive_ready_polls": 3,
            "consecutive_status_unavailable": 0,
            "status_unavailable_reason": None,
            "proxy_info_readable": True,
            "observed_spec_sha256": spec_sha256,
            "last_status": {
                "schema_version": 4,
                "deployment_id": deployment_id,
                "phase": "serving",
                "desired": expected_routes,
                "ready": expected_routes,
                "running_not_ready": 0,
                "pending": 0,
                "coordinator_incarnation": route_generation["coordinator"],
                "coord_ticks_completed": 100,
                "serving_route_generation": route_generation,
            },
            "probe": {
                "ok": True,
                "endpoint_authority_sha256": endpoint["authority_sha256"],
                "coverage": {
                    "ok": True,
                    "expected_routes": expected_routes,
                    "discovered_routes": expected_routes,
                    "backends": backends,
                },
            },
        },
    )


def _capacity_checkpoint(
    path: Path,
    deployment_id: str,
    spec_sha256: str,
    readiness: Path,
    readiness_sha256: str,
    dataset_revision: str,
    image_manifest: Path,
    image_manifest_sha256: str,
    endpoint: dict,
    route_generation: dict,
    proxy_policy: dict,
) -> str:
    run_dir = path.parent / "capacity-run"
    run_dir.mkdir()
    artifact_paths = {
        name: run_dir / ("results.jsonl" if name == "results" else f"capacity-{name}.metadata")
        for name in ("results", "config", "inputs_manifest", "provenance")
    }
    for artifact in artifact_paths.values():
        artifact.write_text("aggregate metadata\n")
    artifact_paths["results"].write_text(
        "".join(
            json.dumps(
                {
                    "timing": {
                        "setup": {"start": 1.0, "end": 1.25},
                        "scoring": {"start": 1.75, "end": 2.0},
                    }
                },
                sort_keys=True,
            )
            + "\n"
            for _ in range(24)
        )
    )
    artifacts = {name: _artifact(artifact, _sha256(artifact.read_bytes())) for name, artifact in artifact_paths.items()}
    artifacts["readiness_checkpoint"] = _artifact(readiness, readiness_sha256)
    artifacts["proxy_info"] = endpoint["proxy_info"]
    identity_path = run_dir / "eval_run_identity.json"
    identity = {
        "role": "smoke",
        "config": {"resolved": artifacts["config"]},
        "inputs": {
            "manifest": artifacts["inputs_manifest"],
            "task_file": {**artifacts["inputs_manifest"], "count": 24},
            "image_manifest": _artifact(image_manifest, image_manifest_sha256),
        },
        "dataset": {"kind": "git_revision", "revision": dataset_revision},
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": route_generation,
            "proxy_policy": proxy_policy,
            "spec": {"path": str(path.parent / "capacity-spec.metadata"), "sha256": spec_sha256},
            "readiness_checkpoint": artifacts["readiness_checkpoint"],
            "smoke_checkpoint": None,
        },
        "execution": {
            "rollout_concurrency": 24,
            "multiplex": 24,
            "http_max_connections": 24,
            "http_max_keepalive_connections": 24,
            "vmvm_environment": {"lease_start_concurrency": 4},
        },
        "contract": {
            "capture_model_io": True,
            "context_tokens": {
                "max_input_tokens": 262_144,
                "max_output_tokens": 262_144,
                "max_total_tokens": 262_144,
            },
            "model": "Kimi-K3",
            "num_rollouts": 1,
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "return_token_ids",
                "top_logprobs",
            ],
            "pass_at_1": True,
            "reasoning_effort": "max",
            "retain_traces": False,
            "sampling_max_tokens": 32_768,
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
        },
    }
    _write_json(
        identity_path,
        {
            "schema_version": 1,
            "eval_run_identity_sha256": "3" * 64,
            "identity": identity,
        },
    )
    artifacts["eval_run_identity"] = _artifact(identity_path, _sha256(identity_path.read_bytes()))
    invocations = run_dir / "eval_invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": "3" * 64,
                "role": "smoke",
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "1",
            }
        )
        + "\n"
    )
    telemetry = ConcurrencyTelemetry(
        run_dir / "concurrency_telemetry.json",
        eval_run_identity_sha256="3" * 64,
        eval_run_role="smoke",
        slurm_job_id="1",
        register_atexit=False,
    )
    for _ in range(24):
        telemetry.vmvm_runtime_started()
    for _ in range(6):
        for _ in range(4):
            telemetry.lease_start_entered()
        for _ in range(4):
            telemetry.lease_tunnel_became_ready()
            telemetry.lease_start_finished()
            telemetry.vmvm_runtime_became_ready()
    for _ in range(24):
        telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    artifacts["concurrency_telemetry"] = _artifact(
        telemetry.path,
        _sha256(telemetry.path.read_bytes()),
    )
    guard_receipt_path = run_dir / "route_guard_success.json"
    guard_receipt = build_guard_success_receipt(
        eval_run_identity_sha256="3" * 64,
        eval_run_role="smoke",
        eval_run_identity=identity_path,
        eval_invocations=invocations,
        results=artifact_paths["results"],
        deployment_id=deployment_id,
        deployment_spec_sha256=spec_sha256,
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=readiness_sha256,
        endpoint=endpoint,
        serving_route_generation=route_generation,
        proxy_policy=proxy_policy,
        concurrency_telemetry=telemetry.path,
    )
    write_guard_success_receipt(guard_receipt_path, guard_receipt)
    artifacts["eval_invocations"] = _artifact(invocations, _sha256(invocations.read_bytes()))
    artifacts["route_guard_success"] = _artifact(
        guard_receipt_path,
        _sha256(guard_receipt_path.read_bytes()),
    )
    body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "eval_run_identity_sha256": "3" * 64,
        "deployment_id": deployment_id,
        "deployment_spec_sha256": spec_sha256,
        "readiness_checkpoint_sha256": readiness_sha256,
        "deployment": {"id": deployment_id, "spec_sha256": spec_sha256},
        "endpoint": endpoint,
        "serving_route_generation": route_generation,
        "proxy_policy": proxy_policy,
        "qualified_execution": {
            "rollout_concurrency": 24,
            "multiplex": 24,
            "http_max_connections": 24,
            "http_max_keepalive_connections": 24,
            "lease_start_concurrency": 4,
        },
        "observed_concurrency": {
            "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
            "lease_start_signal": "vacli_lease_start_semaphore_holders",
            "peak_active_rollouts_lower_bound": 24,
            "peak_concurrent_lease_startups": 4,
            "required_peak_active_rollouts_lower_bound": 24,
            "required_peak_concurrent_lease_startups": 4,
        },
        "audit_policy": {
            "expected_traces": 24,
            "rollouts_per_task": 1,
            "require_reasoning": True,
            "require_model_io": True,
            "model_io_contract": certificate_module.EXPECTED_MODEL_IO_CONTRACT,
            "require_token_data": False,
            "require_logprobs": False,
            "max_sequence_tokens": 262_144,
        },
        "counts": {
            "traces": 24,
            "tasks": 24,
            "sampled_tokens": 100,
            "model_io_turns": 24,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "artifacts": artifacts,
    }
    return _write_json(path, _flat_certificate(body, "smoke_checkpoint_sha256"))


def _oracle_receipt(
    path: Path,
    *,
    project: Path,
    manifest: Path,
    manifest_sha256: str,
    dataset_revision: str,
    image_manifest_sha256: str,
    source: dict[str, str],
    updated_configs: list[dict[str, str]],
) -> str:
    reasons = {"invalid": 18, "valid": 2_520}
    invocations = path.parent / "oracle-invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_identity_sha256": "b" * 64,
                "invoked_at": 1.0,
                "resume": False,
                "reuse_completed_rows": True,
                "rerun_invalid": False,
                "host": "opaque-host",
                "slurm_job_id": "1",
                "source": {
                    "prime_rl_commit": source["prime_rl_commit"],
                    "prime_rl_tree_sha256": source["prime_rl_tree_sha256"],
                    "verifiers_commit": source["verifiers_commit"],
                    "vmvm_tb_v2_sha256": source["vmvm_tb_v2_sha256"],
                },
            },
            sort_keys=True,
        )
        + "\n"
    )
    artifacts = {
        "invocations": {
            "path": str(invocations.resolve()),
            "sha256": _sha256(invocations.read_bytes()),
        },
        "provenance": {"path": "provenance.txt", "sha256": "9" * 64},
        "results": {"path": "results.jsonl", "sha256": "a" * 64},
        "run_identity": {
            "identity_sha256": "b" * 64,
            "path": "run_identity.json",
            "sha256": "c" * 64,
        },
        "summary": {"path": "summary.json", "sha256": "d" * 64},
    }
    counts = {
        "completed": 2_538,
        "configured_files": 2,
        "expected_total": 2_538,
        "invocation_count": 1,
        "oracle_reasons": reasons,
        "passed": 2_520,
        "removed_invalid": 3,
        "rerun_invalid_invocation_count": 0,
        "selected": 2_500,
    }
    acceptance = {
        "minimum_pass_rate": 0.9,
        "minimum_valid": 2_500,
        "observed_pass_rate": 2_520 / 2_538,
        "oracle_network_semantics": {
            "schema_version": 1,
            "trusted_reference_solution": "public",
            "verifier": "declared",
        },
        "selected_subset_valid": True,
    }
    summary = {
        "applied": True,
        "completed": 2_538,
        "configured_files": 2,
        "current_manifest_sha256": "e" * 64,
        "dataset_revision": dataset_revision,
        "invocation_count": 1,
        "minimum_pass_rate": 0.9,
        "minimum_valid": 2_500,
        "oracle_image_manifest_sha256": image_manifest_sha256,
        "oracle_invocations_sha256": artifacts["invocations"]["sha256"],
        "oracle_pass_rate": 2_520 / 2_538,
        "oracle_prime_rl_commit": source["prime_rl_commit"],
        "oracle_provenance_sha256": artifacts["provenance"]["sha256"],
        "oracle_reasons": reasons,
        "oracle_results_sha256": artifacts["results"]["sha256"],
        "oracle_run_identity_file_sha256": artifacts["run_identity"]["sha256"],
        "oracle_run_identity_sha256": artifacts["run_identity"]["identity_sha256"],
        "oracle_summary_sha256": artifacts["summary"]["sha256"],
        "oracle_verifiers_commit": source["verifiers_commit"],
        "oracle_vmvm_tb_v2_sha256": source["vmvm_tb_v2_sha256"],
        "passed": 2_520,
        "removed_invalid": 3,
        "rerun_invalid_invocation_count": 0,
        "selected": 2_500,
        "selected_manifest_sha256": manifest_sha256,
        "selected_subset_valid": True,
        "trusted_reference_solution": "public",
    }
    payload = {
        "acceptance": acceptance,
        "applied_manifest": {
            "path": manifest.relative_to(project).as_posix(),
            "sha256": manifest_sha256,
        },
        "artifact_type": "terminal_bench_vmvm_oracle_promotion_receipt",
        "counts": counts,
        "dataset": {"revision": dataset_revision},
        "image_manifest": {"sha256": image_manifest_sha256},
        "oracle_artifacts": artifacts,
        "promotion_summary": summary,
        "schema_version": 1,
        "source": source,
        "updated_configs": updated_configs,
    }
    envelope = {
        "receipt": payload,
        "receipt_sha256": _sha256(_canonical(payload)),
        "schema_version": 1,
    }
    digest = _write_json(path, envelope)
    path.chmod(0o444)
    return digest


def _fixture(
    tmp_path: Path,
    *,
    production_routes: int = 24,
    tb4_routes: int = 1,
    no_post_tb4_resize: bool = False,
) -> tuple[dict[str, object], Path]:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    configs = project / "configs"
    configs.mkdir()
    vmvm_source = project / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    vmvm_source.mkdir(parents=True)
    (vmvm_source / "client.py").write_text("VALUE = 1\n")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "metadata.txt").write_text("dataset fixture\n")
    subprocess.run(["git", "init", "-q", str(dataset)], check=True)
    subprocess.run(["git", "-C", str(dataset), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(dataset),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "dataset fixture",
        ],
        check=True,
    )
    dataset_revision = subprocess.run(
        ["git", "-C", str(dataset), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    deployment_id = "deployment-test"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text(
        "schema_version: 1\n"
        "spec:\n"
        f"  num_endpoints: {production_routes}\n"
        "  proxy:\n"
        "    config:\n"
        "      request_timeout: 43200\n"
        "      num_retries: 0\n"
    )
    (deployment_dir / "proxy_litellm_config.yaml").write_text(
        "litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n"
    )
    spec_sha256 = _sha256(spec.read_bytes())
    proxy_info = deployment_dir / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 8100,
                "url": "http://127.0.0.1:8100",
                "api_key": "unit-test-secret",
                "model": "Kimi-K3",
                "proxy_jobid": "12345",
                "extras": {"proxy_type": "litellm", "sticky": True, "redis_port": 6379},
            }
        )
        + "\n"
    )
    proxy_info_sha256 = _sha256(proxy_info.read_bytes())
    endpoint_info = load_deployment_endpoint(
        proxy_info,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=proxy_info_sha256,
    )
    endpoint = endpoint_info.binding
    proxy_policy = load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=spec_sha256,
        expected_request_timeout=43_200,
    )
    tb4_proxy_policy = {
        **proxy_policy,
        "proxy_litellm_config": {
            **proxy_policy["proxy_litellm_config"],
            "sha256": "f" * 64,
        },
    }
    tb4_route_generation = _route_generation(tb4_routes, first_job_id=12000)
    production_route_generation = _route_generation(production_routes, first_job_id=13000)
    manifest = project / "approved.txt"
    manifest.write_text("".join(f"synthetic-entry-{index:04d}\n" for index in range(2_500)))
    manifest_sha256 = _sha256(manifest.read_bytes())
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text("{}\n")
    image_manifest_sha256 = _sha256(image_manifest.read_bytes())
    config = configs / "mobius_kimi.toml"
    config.write_text(
        'model = "Kimi-K3"\n'
        "num_tasks = 2500\n"
        "num_rollouts = 1\n"
        "max_concurrent = 24\n"
        "max_input_tokens = 262144\n"
        "max_output_tokens = 262144\n"
        "max_total_tokens = 262144\n"
        "multiplex = 24\n"
        "rich = false\n"
        "retain_traces = false\n"
        "[client]\n"
        'type = "eval"\n'
        'base_url = "http://127.0.0.1:8000/v1"\n'
        "capture_model_io = true\n"
        'outbound_body_denylist = ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"]\n'
        "max_connections = 24\n"
        "max_keepalive_connections = 24\n"
        "timeout = 43200\n"
        "connect_timeout = 120\n"
        "[sampling]\n"
        "max_tokens = 32768\n"
        'reasoning_effort = "max"\n'
        "chat_template_kwargs = { enable_thinking = true, preserve_thinking = true }\n"
        "[taskset]\n"
        'id = "terminal-bench-vmvm"\n'
        f'dataset_dir = "{dataset}"\n'
        f'dataset_revision = "{dataset_revision}"\n'
        f'task_file = "{manifest.relative_to(project)}"\n'
        f'task_file_sha256 = "{manifest_sha256}"\n'
        f'image_manifest = "{image_manifest}"\n'
        f'image_manifest_sha256 = "{image_manifest_sha256}"\n'
        "[harness]\n"
        'id = "mini-swe-agent"\n'
        'config_overrides = ["model.model_kwargs.timeout=43200"]\n'
        "[harness.runtime]\n"
        'type = "vmvm"\n'
        "session_timeout = 43200\n"
        "[timeout]\n"
        "setup = 3600\n"
        "rollout = 36000\n"
        "finalize = 3600\n"
        "scoring = 21600\n"
        "[retries.rollout]\n"
        "max_retries = 2\n"
        'include = ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]\n'
    )
    config_sha256 = _sha256(config.read_bytes())
    second_config = configs / "mobius_qwen.toml"
    second_config.write_text("metadata_only = true\n")
    second_config_sha256 = _sha256(second_config.read_bytes())

    verifier = project / "deps/verifiers"
    verifier.mkdir(parents=True)
    (verifier / "metadata.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "init", "-q", str(verifier)], check=True)
    subprocess.run(["git", "-C", str(verifier), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(verifier),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "verifier fixture",
        ],
        check=True,
    )
    verifier_commit = subprocess.run(
        ["git", "-C", str(verifier), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    prime_rl_commit = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = {
        "minimum_prime_rl_ancestor": prime_rl_commit,
        "prime_rl_commit": prime_rl_commit,
        "prime_rl_tree_sha256": _sha256(b""),
        "required_prime_rl_ancestor": prime_rl_commit,
        "verifiers_commit": verifier_commit,
        "vmvm_tb_v2_sha256": _vmvm_sha256(project),
    }
    updated_configs = [
        {
            "path": config.relative_to(project).as_posix(),
            "sha256": config_sha256,
        },
        {
            "path": second_config.relative_to(project).as_posix(),
            "sha256": second_config_sha256,
        },
    ]

    tb4 = tmp_path / "tb4-checkpoint.json"
    tb4_sha256 = _tb4_checkpoint(
        tb4,
        deployment_id,
        endpoint,
        tb4_route_generation,
        tb4_proxy_policy,
        spec_sha256 if no_post_tb4_resize else "2" * 64,
    )
    readiness = tmp_path / "readiness-checkpoint.json"
    readiness_sha256 = _readiness_checkpoint(
        readiness,
        deployment_id,
        spec_sha256,
        endpoint,
        production_route_generation,
        proxy_policy,
    )
    capacity = tmp_path / "capacity-checkpoint.json"
    capacity_sha256 = _capacity_checkpoint(
        capacity,
        deployment_id,
        spec_sha256,
        readiness,
        readiness_sha256,
        dataset_revision,
        image_manifest,
        image_manifest_sha256,
        endpoint,
        production_route_generation,
        proxy_policy,
    )
    receipt = tmp_path / "oracle-receipt.json"
    receipt_sha256 = _oracle_receipt(
        receipt,
        project=project,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        dataset_revision=dataset_revision,
        image_manifest_sha256=image_manifest_sha256,
        source=source,
        updated_configs=updated_configs,
    )
    output = tmp_path / "launch-certificate.json"
    arguments: dict[str, object] = {
        "tb4_checkpoint": tb4,
        "tb4_checkpoint_sha256": tb4_sha256,
        "oracle_receipt": receipt,
        "oracle_receipt_sha256": receipt_sha256,
        "readiness_checkpoint": readiness,
        "readiness_checkpoint_sha256": readiness_sha256,
        "capacity_smoke_checkpoint": capacity,
        "capacity_smoke_checkpoint_sha256": capacity_sha256,
        "deployment_id": deployment_id,
        "deployment_spec": spec,
        "deployment_spec_sha256": spec_sha256,
        "deployment_proxy_info": proxy_info,
        "deployment_proxy_info_sha256": proxy_info_sha256,
        "production_config": config,
        "approved_manifest": manifest,
        "approved_manifest_sha256": manifest_sha256,
        "requested_lease_start_concurrency": 4,
        "output": output,
    }
    return arguments, output


def _rewrite_flat(path: Path, hash_field: str, mutate: Callable[[dict], None]) -> str:
    value = json.loads(path.read_text())
    value.pop(hash_field)
    mutate(value)
    return _write_json(path, _flat_certificate(value, hash_field))


def _rewrite_receipt(path: Path, mutate: Callable[[dict], None]) -> str:
    path.chmod(0o644)
    envelope = json.loads(path.read_text())
    payload = envelope["receipt"]
    mutate(payload)
    envelope["receipt_sha256"] = _sha256(_canonical(payload))
    digest = _write_json(path, envelope)
    path.chmod(0o444)
    return digest


def _append_oracle_invocation(payload: dict, *, rerun_invalid: bool) -> None:
    artifact = payload["oracle_artifacts"]["invocations"]
    path = Path(artifact["path"])
    count = len(path.read_text().splitlines())
    source = payload["source"]
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_identity_sha256": payload["oracle_artifacts"]["run_identity"]["identity_sha256"],
                    "invoked_at": float(count + 1),
                    "resume": True,
                    "reuse_completed_rows": True,
                    "rerun_invalid": rerun_invalid,
                    "host": "opaque-resume-host",
                    "slurm_job_id": str(count + 1),
                    "source": {
                        "prime_rl_commit": source["prime_rl_commit"],
                        "prime_rl_tree_sha256": source["prime_rl_tree_sha256"],
                        "verifiers_commit": source["verifiers_commit"],
                        "vmvm_tb_v2_sha256": source["vmvm_tb_v2_sha256"],
                    },
                },
                sort_keys=True,
            )
            + "\n"
        )
    artifact["sha256"] = _sha256(path.read_bytes())
    payload["counts"]["invocation_count"] += 1
    payload["counts"]["rerun_invalid_invocation_count"] += int(rerun_invalid)
    payload["promotion_summary"]["invocation_count"] += 1
    payload["promotion_summary"]["rerun_invalid_invocation_count"] += int(rerun_invalid)
    payload["promotion_summary"]["oracle_invocations_sha256"] = artifact["sha256"]


def _validate_for_run(
    arguments: dict[str, object],
    output: Path,
    certificate_sha256: str,
    *,
    requested_leases: int | None = None,
) -> dict:
    return validate_launch_certificate_for_run(
        output,
        certificate_sha256,
        production_config=Path(arguments["production_config"]),
        approved_manifest=Path(arguments["approved_manifest"]),
        approved_manifest_sha256=str(arguments["approved_manifest_sha256"]),
        deployment_id=str(arguments["deployment_id"]),
        deployment_spec=Path(arguments["deployment_spec"]),
        deployment_spec_sha256=str(arguments["deployment_spec_sha256"]),
        deployment_proxy_info=Path(arguments["deployment_proxy_info"]),
        deployment_proxy_info_sha256=str(arguments["deployment_proxy_info_sha256"]),
        readiness_checkpoint=Path(arguments["readiness_checkpoint"]),
        readiness_checkpoint_sha256=str(arguments["readiness_checkpoint_sha256"]),
        capacity_smoke_checkpoint=Path(arguments["capacity_smoke_checkpoint"]),
        capacity_smoke_checkpoint_sha256=str(arguments["capacity_smoke_checkpoint_sha256"]),
        requested_lease_start_concurrency=(
            int(arguments["requested_lease_start_concurrency"]) if requested_leases is None else requested_leases
        ),
    )


def _create_cli_arguments(arguments: dict[str, object]) -> list[str]:
    return [
        "create",
        "--tb4-checkpoint",
        str(arguments["tb4_checkpoint"]),
        "--tb4-checkpoint-sha256",
        str(arguments["tb4_checkpoint_sha256"]),
        "--oracle-receipt",
        str(arguments["oracle_receipt"]),
        "--oracle-receipt-sha256",
        str(arguments["oracle_receipt_sha256"]),
        "--readiness-checkpoint",
        str(arguments["readiness_checkpoint"]),
        "--readiness-checkpoint-sha256",
        str(arguments["readiness_checkpoint_sha256"]),
        "--capacity-smoke-checkpoint",
        str(arguments["capacity_smoke_checkpoint"]),
        "--capacity-smoke-checkpoint-sha256",
        str(arguments["capacity_smoke_checkpoint_sha256"]),
        "--deployment-id",
        str(arguments["deployment_id"]),
        "--deployment-spec",
        str(arguments["deployment_spec"]),
        "--deployment-spec-sha256",
        str(arguments["deployment_spec_sha256"]),
        "--deployment-proxy-info",
        str(arguments["deployment_proxy_info"]),
        "--deployment-proxy-info-sha256",
        str(arguments["deployment_proxy_info_sha256"]),
        "--production-config",
        str(arguments["production_config"]),
        "--approved-manifest",
        str(arguments["approved_manifest"]),
        "--approved-manifest-sha256",
        str(arguments["approved_manifest_sha256"]),
        "--requested-lease-start-concurrency",
        str(arguments["requested_lease_start_concurrency"]),
        "--output",
        str(arguments["output"]),
    ]


def _verify_cli_arguments(
    arguments: dict[str, object],
    output: Path,
    certificate_sha256: str,
) -> list[str]:
    return [
        "verify",
        str(output),
        "--certificate-sha256",
        certificate_sha256,
        "--production-config",
        str(arguments["production_config"]),
        "--approved-manifest",
        str(arguments["approved_manifest"]),
        "--approved-manifest-sha256",
        str(arguments["approved_manifest_sha256"]),
        "--deployment-id",
        str(arguments["deployment_id"]),
        "--deployment-spec",
        str(arguments["deployment_spec"]),
        "--deployment-spec-sha256",
        str(arguments["deployment_spec_sha256"]),
        "--deployment-proxy-info",
        str(arguments["deployment_proxy_info"]),
        "--deployment-proxy-info-sha256",
        str(arguments["deployment_proxy_info_sha256"]),
        "--readiness-checkpoint",
        str(arguments["readiness_checkpoint"]),
        "--readiness-checkpoint-sha256",
        str(arguments["readiness_checkpoint_sha256"]),
        "--capacity-smoke-checkpoint",
        str(arguments["capacity_smoke_checkpoint"]),
        "--capacity-smoke-checkpoint-sha256",
        str(arguments["capacity_smoke_checkpoint_sha256"]),
        "--requested-lease-start-concurrency",
        str(arguments["requested_lease_start_concurrency"]),
    ]


def test_create_and_verify_launch_certificate_without_task_metadata(
    tmp_path: Path,
    _strict_identity_loader: list[Path],
) -> None:
    arguments, output = _fixture(tmp_path)

    certificate = create_launch_certificate(**arguments)

    assert 'base_url = "http://127.0.0.1:8000/v1"' in Path(arguments["production_config"]).read_text()
    assert certificate["ok"] is True
    assert certificate["state"] == "passed"
    assert certificate["deployment"]["spec"]["sha256"] != certificate["gates"]["tb4"]["deployment_spec_sha256"]
    assert certificate["gates"]["readiness"]["expected_routes"] == 24
    assert certificate["gates"]["tb4"]["expected_routes"] == 1
    assert certificate["gates"]["tb4"]["proxy_policy"] != certificate["gates"]["readiness"]["proxy_policy"]
    assert certificate["deployment"]["endpoint"]["proxy_info"] == {
        "path": str(Path(arguments["deployment_proxy_info"]).resolve()),
        "sha256": arguments["deployment_proxy_info_sha256"],
    }
    assert certificate["production"]["approved_manifest"]["count"] == 2_500
    assert certificate["gates"]["capacity_smoke"]["qualified_execution"] == {
        "http_max_connections": 24,
        "http_max_keepalive_connections": 24,
        "lease_start_concurrency": 4,
        "multiplex": 24,
        "rollout_concurrency": 24,
    }
    assert certificate["gates"]["capacity_smoke"]["observed_concurrency"] == {
        "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
        "lease_start_signal": "vacli_lease_start_semaphore_holders",
        "peak_active_rollouts_lower_bound": 24,
        "peak_concurrent_lease_startups": 4,
        "required_peak_active_rollouts_lower_bound": 24,
        "required_peak_concurrent_lease_startups": 4,
    }
    unsigned = dict(certificate)
    self_hash = unsigned.pop("launch_certificate_sha256")
    assert self_hash == _sha256(_canonical(unsigned))
    assert "synthetic-entry-" not in output.read_text()
    assert "unit-test-secret" not in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o444

    file_sha256 = _sha256(output.read_bytes())
    assert _validate_for_run(arguments, output, file_sha256) == certificate
    assert len(_strict_identity_loader) == 4
    with pytest.raises(LaunchCertificateError, match="^launch_inputs_mismatch$"):
        _validate_for_run(arguments, output, file_sha256, requested_leases=3)


def test_create_rejects_nonstandard_production_lease_start_concurrency(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    arguments["requested_lease_start_concurrency"] = 3

    with pytest.raises(
        LaunchCertificateError,
        match="^production_lease_start_concurrency_invalid$",
    ):
        create_launch_certificate(**arguments)


def test_kimi_launch_rejects_structurally_valid_7200_readiness_policy(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    readiness = json.loads(Path(arguments["readiness_checkpoint"]).read_text())
    readiness["proxy_policy"]["request_timeout"] = 7_200

    with pytest.raises(LaunchCertificateError, match="readiness_checkpoint_schema_invalid"):
        certificate_module._validate_readiness_checkpoint(
            readiness,
            deployment_id=str(arguments["deployment_id"]),
            deployment_spec_sha256=str(arguments["deployment_spec_sha256"]),
            endpoint=readiness["endpoint"],
        )


def test_create_and_reconstruct_launch_certificate_with_sharded_tb4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, output = _fixture(tmp_path)
    sharded = {
        "certificate_sha256": "a" * 64,
        "deployment_spec_sha256": "b" * 64,
        "expected_routes": 1,
        "route_generation_sha256s": ["c" * 64, "d" * 64],
        "endpoint_binding_sha256s": ["e" * 64],
        "proxy_policy_sha256": "f" * 64,
        "shard_count": 17,
        "supported_pass_rate": 4 / 63,
        "all_task_pass_rate": 4 / 66,
        "supported_passes": 4,
        "sharded": True,
    }
    monkeypatch.setattr(
        certificate_module,
        "_validate_tb4_checkpoint",
        lambda _value, _deployment_id, _endpoint: sharded,
    )

    certificate = create_launch_certificate(**arguments)
    gate = certificate["gates"]["tb4"]
    assert gate["sharded"] is True
    assert gate["shard_count"] == 17
    assert gate["route_generation_sha256s"] == ["c" * 64, "d" * 64]
    assert "serving_route_generation" not in gate
    assert "proxy_policy" not in gate
    certificate_sha256 = _sha256(output.read_bytes())
    assert certificate_module._validate_launch_certificate(output, certificate_sha256) == certificate


def test_rejects_missing_post_tb4_resize(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path, no_post_tb4_resize=True)

    with pytest.raises(LaunchCertificateError, match="^post_tb4_deployment_spec_not_changed$"):
        create_launch_certificate(**arguments)


def test_rejects_post_tb4_route_count_below_two(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path, production_routes=1)

    with pytest.raises(LaunchCertificateError, match="^post_tb4_route_count_too_small$"):
        create_launch_certificate(**arguments)


def test_rejects_route_count_below_production_concurrency(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path, production_routes=23)

    with pytest.raises(
        LaunchCertificateError,
        match="^post_tb4_route_count_below_production_concurrency$",
    ):
        create_launch_certificate(**arguments)


def test_rejects_tb4_checkpoint_not_run_at_exactly_one_route(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path, tb4_routes=2, production_routes=3)

    with pytest.raises(LaunchCertificateError, match="^tb4_route_count_invalid$"):
        create_launch_certificate(**arguments)


@pytest.mark.parametrize(
    ("argument", "hash_argument", "hash_field", "error"),
    [
        (
            "tb4_checkpoint",
            "tb4_checkpoint_sha256",
            "tb4_certificate_sha256",
            "tb4_artifacts_invalid",
        ),
        (
            "capacity_smoke_checkpoint",
            "capacity_smoke_checkpoint_sha256",
            "smoke_checkpoint_sha256",
            "capacity_smoke_artifacts_invalid",
        ),
    ],
)
def test_rejects_certificate_chain_without_guard_receipt(
    tmp_path: Path,
    argument: str,
    hash_argument: str,
    hash_field: str,
    error: str,
) -> None:
    arguments, _ = _fixture(tmp_path)
    checkpoint = Path(arguments[argument])
    arguments[hash_argument] = _rewrite_flat(
        checkpoint,
        hash_field,
        lambda value: value["artifacts"].pop("route_guard_success"),
    )

    with pytest.raises(LaunchCertificateError, match=f"^{error}$"):
        create_launch_certificate(**arguments)


def test_rejects_existing_output_before_reading_inputs(tmp_path: Path) -> None:
    arguments, output = _fixture(tmp_path)
    output.write_bytes(b"existing\n")
    Path(arguments["tb4_checkpoint"]).unlink()

    with pytest.raises(LaunchCertificateError, match="^output_already_exists$"):
        create_launch_certificate(**arguments)
    assert output.read_bytes() == b"existing\n"


@pytest.mark.parametrize("input_name", ["readiness_checkpoint", "capacity_smoke_checkpoint"])
def test_verify_rejects_a_different_run_gate_with_identical_bytes(
    tmp_path: Path,
    input_name: str,
) -> None:
    arguments, output = _fixture(tmp_path)
    create_launch_certificate(**arguments)
    certificate_sha256 = _sha256(output.read_bytes())
    original = Path(arguments[input_name])
    replacement = tmp_path / f"replacement-{original.name}"
    replacement.write_bytes(original.read_bytes())
    changed = dict(arguments)
    changed[input_name] = replacement

    with pytest.raises(LaunchCertificateError, match="^launch_inputs_mismatch$"):
        _validate_for_run(changed, output, certificate_sha256)


def test_rejects_tb4_policy_even_with_valid_self_and_file_hashes(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    path = Path(arguments["tb4_checkpoint"])
    arguments["tb4_checkpoint_sha256"] = _rewrite_flat(
        path,
        "tb4_certificate_sha256",
        lambda value: value["audit_policy"].__setitem__("model", "not-approved"),
    )

    with pytest.raises(LaunchCertificateError, match="^tb4_policy_invalid$"):
        create_launch_certificate(**arguments)


def test_rejects_type_confused_model_io_policy(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    path = Path(arguments["tb4_checkpoint"])
    arguments["tb4_checkpoint_sha256"] = _rewrite_flat(
        path,
        "tb4_certificate_sha256",
        lambda value: value["audit_policy"]["model_io_contract"]["request_chat_template_kwargs"].__setitem__(
            "enable_thinking", 1
        ),
    )

    with pytest.raises(LaunchCertificateError, match="^tb4_policy_invalid$"):
        create_launch_certificate(**arguments)


def test_rejects_legacy_or_mismatched_endpoint_chain(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    tb4 = Path(arguments["tb4_checkpoint"])
    arguments["tb4_checkpoint_sha256"] = _rewrite_flat(
        tb4,
        "tb4_certificate_sha256",
        lambda value: value.pop("endpoint"),
    )
    with pytest.raises(LaunchCertificateError, match="^tb4_checkpoint_schema_invalid$"):
        create_launch_certificate(**arguments)

    arguments, _ = _fixture(tmp_path / "mismatch")
    capacity = Path(arguments["capacity_smoke_checkpoint"])
    arguments["capacity_smoke_checkpoint_sha256"] = _rewrite_flat(
        capacity,
        "smoke_checkpoint_sha256",
        lambda value: value["endpoint"].__setitem__("authority_sha256", "0" * 64),
    )
    with pytest.raises(LaunchCertificateError, match="^capacity_smoke_not_passed$"):
        create_launch_certificate(**arguments)


def test_rejects_changed_current_proxy_artifact(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    proxy_info = Path(arguments["deployment_proxy_info"])
    payload = json.loads(proxy_info.read_text())
    payload["proxy_jobid"] = "54321"
    proxy_info.write_text(json.dumps(payload) + "\n")

    with pytest.raises(LaunchCertificateError, match="^deployment_endpoint_invalid$"):
        create_launch_certificate(**arguments)


def test_rejects_proxy_rotation_during_gate_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, output = _fixture(tmp_path)
    proxy_info = Path(arguments["deployment_proxy_info"])
    original_validate_capacity = certificate_module._validate_capacity

    def validate_then_rotate(*args: object, **kwargs: object) -> None:
        original_validate_capacity(*args, **kwargs)
        payload = json.loads(proxy_info.read_text())
        payload["proxy_jobid"] = "54321"
        proxy_info.write_text(json.dumps(payload) + "\n")

    monkeypatch.setattr(
        certificate_module,
        "_validate_capacity",
        validate_then_rotate,
    )

    with pytest.raises(LaunchCertificateError, match="^deployment_endpoint_invalid$"):
        create_launch_certificate(**arguments)
    assert not output.exists()


def test_rejects_oracle_acceptance_even_with_valid_receipt_hashes(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    path = Path(arguments["oracle_receipt"])
    arguments["oracle_receipt_sha256"] = _rewrite_receipt(
        path,
        lambda payload: payload["acceptance"].__setitem__("selected_subset_valid", False),
    )

    with pytest.raises(LaunchCertificateError, match="^oracle_receipt_acceptance_invalid$"):
        create_launch_certificate(**arguments)


def test_accepts_one_attested_oracle_rerun_invalid_invocation(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    receipt = Path(arguments["oracle_receipt"])
    arguments["oracle_receipt_sha256"] = _rewrite_receipt(
        receipt,
        lambda payload: _append_oracle_invocation(payload, rerun_invalid=True),
    )

    certificate = create_launch_certificate(**arguments)

    gate = certificate["gates"]["oracle_promotion"]
    assert gate["invocation_count"] == 2
    assert gate["rerun_invalid_invocation_count"] == 1
    assert (
        gate["invocations_sha256"]
        == json.loads(receipt.read_text())["receipt"]["oracle_artifacts"]["invocations"]["sha256"]
    )


def test_rejects_legacy_or_unbounded_oracle_invocation_lineage(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    receipt = Path(arguments["oracle_receipt"])
    arguments["oracle_receipt_sha256"] = _rewrite_receipt(
        receipt,
        lambda payload: payload["oracle_artifacts"].pop("invocations"),
    )
    with pytest.raises(LaunchCertificateError, match="^oracle_receipt_artifacts_invalid$"):
        create_launch_certificate(**arguments)

    second = tmp_path / "second"
    second.mkdir()
    arguments, _ = _fixture(second)
    receipt = Path(arguments["oracle_receipt"])

    def append_two_recoveries(payload: dict) -> None:
        _append_oracle_invocation(payload, rerun_invalid=True)
        _append_oracle_invocation(payload, rerun_invalid=True)

    arguments["oracle_receipt_sha256"] = _rewrite_receipt(
        receipt,
        append_two_recoveries,
    )
    with pytest.raises(LaunchCertificateError, match="^oracle_receipt_counts_invalid$"):
        create_launch_certificate(**arguments)


def test_rejects_changed_oracle_invocation_artifact(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    receipt = json.loads(Path(arguments["oracle_receipt"]).read_text())["receipt"]
    invocation_path = Path(receipt["oracle_artifacts"]["invocations"]["path"])
    invocation_path.write_bytes(invocation_path.read_bytes() + b"\n")

    with pytest.raises(LaunchCertificateError, match="^oracle_invocations_sha256_mismatch$"):
        create_launch_certificate(**arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("invoked_at", 1.0),
        ("slurm_job_id", "01"),
    ],
)
def test_rejects_noncanonical_oracle_invocation_order(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    arguments, _ = _fixture(tmp_path)
    receipt = Path(arguments["oracle_receipt"])

    def mutate(payload: dict) -> None:
        _append_oracle_invocation(payload, rerun_invalid=False)
        artifact = payload["oracle_artifacts"]["invocations"]
        invocation_path = Path(artifact["path"])
        records = [json.loads(line) for line in invocation_path.read_text().splitlines()]
        records[-1][field] = value
        invocation_path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
        artifact["sha256"] = _sha256(invocation_path.read_bytes())
        payload["promotion_summary"]["oracle_invocations_sha256"] = artifact["sha256"]

    arguments["oracle_receipt_sha256"] = _rewrite_receipt(receipt, mutate)

    with pytest.raises(LaunchCertificateError, match="^oracle_invocations_invalid$"):
        create_launch_certificate(**arguments)


def test_rejects_oracle_invocation_change_during_launch_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, output = _fixture(tmp_path)
    receipt = json.loads(Path(arguments["oracle_receipt"]).read_text())["receipt"]
    invocation_path = Path(receipt["oracle_artifacts"]["invocations"]["path"])
    original_validate_capacity = certificate_module._validate_capacity

    def validate_then_mutate(*args: object, **kwargs: object) -> None:
        original_validate_capacity(*args, **kwargs)
        invocation_path.write_bytes(invocation_path.read_bytes() + b"\n")

    monkeypatch.setattr(
        certificate_module,
        "_validate_capacity",
        validate_then_mutate,
    )
    with pytest.raises(LaunchCertificateError, match="^oracle_invocations_sha256_mismatch$"):
        create_launch_certificate(**arguments)
    assert not output.exists()


def test_rejects_failed_readiness_and_capacity_below_production(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    readiness = Path(arguments["readiness_checkpoint"])
    readiness_value = json.loads(readiness.read_text())
    readiness_value["state"] = "failed"
    arguments["readiness_checkpoint_sha256"] = _write_json(readiness, readiness_value)

    with pytest.raises(LaunchCertificateError, match="^readiness_checkpoint_not_passed$"):
        create_launch_certificate(**arguments)

    arguments, _ = _fixture(tmp_path / "capacity")
    capacity = Path(arguments["capacity_smoke_checkpoint"])
    capacity_value = json.loads(capacity.read_text())
    capacity_value.pop("smoke_checkpoint_sha256")
    identity_record = capacity_value["artifacts"]["eval_run_identity"]
    identity_path = Path(identity_record["path"])
    identity = json.loads(identity_path.read_text())
    for key in (
        "http_max_connections",
        "http_max_keepalive_connections",
        "multiplex",
        "rollout_concurrency",
    ):
        identity["identity"]["execution"][key] = 23
        capacity_value["qualified_execution"][key] = 23
    _write_json(identity_path, identity)
    identity_record["sha256"] = _sha256(identity_path.read_bytes())
    guard_record = capacity_value["artifacts"]["route_guard_success"]
    guard_path = Path(guard_record["path"])
    guard_value = json.loads(guard_path.read_text())
    guard_value["artifacts"]["eval_run_identity"]["sha256"] = identity_record["sha256"]
    guard_value.pop("guard_success_receipt_sha256")
    guard_value["guard_success_receipt_sha256"] = _sha256(_canonical(guard_value))
    guard_record["sha256"] = _write_json(guard_path, guard_value)
    arguments["capacity_smoke_checkpoint_sha256"] = _write_json(
        capacity,
        _flat_certificate(capacity_value, "smoke_checkpoint_sha256"),
    )
    with pytest.raises(
        LaunchCertificateError,
        match="^capacity_smoke_below_production_concurrency$",
    ):
        create_launch_certificate(**arguments)


def test_rejects_capacity_smoke_with_misaligned_steady_state_concurrency() -> None:
    qualified = {
        "http_max_connections": 25,
        "http_max_keepalive_connections": 24,
        "multiplex": 24,
        "rollout_concurrency": 24,
        "lease_start_concurrency": 4,
    }
    observed = {
        "peak_active_rollouts_lower_bound": 24,
        "peak_concurrent_lease_startups": 4,
        "required_peak_active_rollouts_lower_bound": 24,
        "required_peak_concurrent_lease_startups": 4,
    }
    required = {
        "http_max_connections": 24,
        "http_max_keepalive_connections": 24,
        "multiplex": 24,
        "rollout_concurrency": 24,
    }

    with pytest.raises(
        LaunchCertificateError,
        match="^capacity_smoke_concurrency_contract_invalid$",
    ):
        certificate_module._validate_capacity(
            qualified,
            observed,
            required,
            requested_lease_start_concurrency=4,
            expected_traces=42,
        )


def test_rejects_capacity_smoke_above_production_concurrency() -> None:
    qualified = {
        "http_max_connections": 25,
        "http_max_keepalive_connections": 25,
        "multiplex": 25,
        "rollout_concurrency": 25,
        "lease_start_concurrency": 4,
    }
    observed = {
        "peak_active_rollouts_lower_bound": 25,
        "peak_concurrent_lease_startups": 4,
        "required_peak_active_rollouts_lower_bound": 25,
        "required_peak_concurrent_lease_startups": 4,
    }
    required = {
        "http_max_connections": 24,
        "http_max_keepalive_connections": 24,
        "multiplex": 24,
        "rollout_concurrency": 24,
    }

    with pytest.raises(
        LaunchCertificateError,
        match="^capacity_smoke_above_production_concurrency$",
    ):
        certificate_module._validate_capacity(
            qualified,
            observed,
            required,
            requested_lease_start_concurrency=4,
            expected_traces=42,
        )


def test_rejects_capacity_smoke_lease_start_above_production() -> None:
    qualified = {
        "http_max_connections": 24,
        "http_max_keepalive_connections": 24,
        "multiplex": 24,
        "rollout_concurrency": 24,
        "lease_start_concurrency": 5,
    }
    observed = {
        "peak_active_rollouts_lower_bound": 24,
        "peak_concurrent_lease_startups": 5,
        "required_peak_active_rollouts_lower_bound": 24,
        "required_peak_concurrent_lease_startups": 5,
    }
    required = {
        "http_max_connections": 24,
        "http_max_keepalive_connections": 24,
        "multiplex": 24,
        "rollout_concurrency": 24,
    }

    with pytest.raises(
        LaunchCertificateError,
        match="^capacity_smoke_lease_start_concurrency_mismatch$",
    ):
        certificate_module._validate_capacity(
            qualified,
            observed,
            required,
            requested_lease_start_concurrency=4,
            expected_traces=42,
        )


def test_rejects_capacity_execution_not_bound_to_strict_identity(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    capacity = Path(arguments["capacity_smoke_checkpoint"])
    arguments["capacity_smoke_checkpoint_sha256"] = _rewrite_flat(
        capacity,
        "smoke_checkpoint_sha256",
        lambda value: value["qualified_execution"].__setitem__("rollout_concurrency", 25),
    )

    with pytest.raises(LaunchCertificateError, match="^capacity_eval_run_identity_invalid$"):
        create_launch_certificate(**arguments)


def test_rejects_capacity_claim_not_bound_to_trace_timing_evidence(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    capacity = Path(arguments["capacity_smoke_checkpoint"])
    arguments["capacity_smoke_checkpoint_sha256"] = _rewrite_flat(
        capacity,
        "smoke_checkpoint_sha256",
        lambda value: value["observed_concurrency"].__setitem__(
            "peak_active_rollouts_lower_bound",
            23,
        ),
    )

    with pytest.raises(
        LaunchCertificateError,
        match="^capacity_trace_concurrency_invalid$",
    ):
        create_launch_certificate(**arguments)


def test_rejects_capacity_claim_not_bound_to_lease_telemetry(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    capacity = Path(arguments["capacity_smoke_checkpoint"])
    arguments["capacity_smoke_checkpoint_sha256"] = _rewrite_flat(
        capacity,
        "smoke_checkpoint_sha256",
        lambda value: value["observed_concurrency"].__setitem__(
            "peak_concurrent_lease_startups",
            3,
        ),
    )

    with pytest.raises(
        LaunchCertificateError,
        match="^capacity_concurrency_telemetry_invalid$",
    ):
        create_launch_certificate(**arguments)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("contract", "model", "not-approved"),
        ("dataset", "revision", "0" * 40),
    ],
)
def test_rejects_capacity_smoke_from_a_different_workload_contract(
    tmp_path: Path,
    section: str,
    key: str,
    value: object,
) -> None:
    arguments, _ = _fixture(tmp_path)
    capacity = Path(arguments["capacity_smoke_checkpoint"])
    capacity_value = json.loads(capacity.read_text())
    capacity_value.pop("smoke_checkpoint_sha256")
    identity_record = capacity_value["artifacts"]["eval_run_identity"]
    identity_path = Path(identity_record["path"])
    identity = json.loads(identity_path.read_text())
    identity["identity"][section][key] = value
    _write_json(identity_path, identity)
    identity_record["sha256"] = _sha256(identity_path.read_bytes())
    arguments["capacity_smoke_checkpoint_sha256"] = _write_json(
        capacity,
        _flat_certificate(capacity_value, "smoke_checkpoint_sha256"),
    )

    with pytest.raises(LaunchCertificateError, match="^capacity_eval_run_identity_invalid$"):
        create_launch_certificate(**arguments)


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        ('model = "Kimi-K3"', 'model = "other"', "production_model_contract_invalid"),
        ("max_tokens = 32768", "max_tokens = 262145", "production_model_contract_invalid"),
        (
            "timeout = 43200\nconnect_timeout = 120",
            "timeout = 36000\nconnect_timeout = 120",
            "production_timeout_contract_invalid",
        ),
        (
            "session_timeout = 43200",
            "session_timeout = 36000",
            "production_timeout_contract_invalid",
        ),
        (
            "rollout = 36000",
            "rollout = 43200",
            "production_timeout_contract_invalid",
        ),
        (
            "model.model_kwargs.timeout=43200",
            "model.model_kwargs.timeout=36000",
            "production_timeout_contract_invalid",
        ),
        ("setup = 3600", "setup = 3599", "production_timeout_contract_invalid"),
        ("finalize = 3600", "finalize = 3599", "production_timeout_contract_invalid"),
        ("scoring = 21600", "scoring = 21599", "production_timeout_contract_invalid"),
        ("connect_timeout = 120", "connect_timeout = 119", "production_timeout_contract_invalid"),
        ("max_connections = 24", "max_connections = 23", "production_concurrency_contract_invalid"),
        ("max_retries = 2", "max_retries = 1", "production_retry_contract_invalid"),
        (
            'include = ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]',
            'include = ["ProviderError", "SandboxError", "TunnelError", "HarnessError"]',
            "production_retry_contract_invalid",
        ),
        (
            'include = ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]',
            'include = ["ProviderError", "SandboxError", "TunnelError"]',
            "production_retry_contract_invalid",
        ),
        (
            'include = ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]',
            'include = ["ProviderError", "SandboxError", "TunnelError", "InterceptionError", "UnknownError"]',
            "production_retry_contract_invalid",
        ),
    ],
)
def test_rejects_invalid_production_config_even_when_receipt_matches(
    tmp_path: Path,
    old: str,
    new: str,
    error: str,
) -> None:
    arguments, _ = _fixture(tmp_path)
    config = Path(arguments["production_config"])
    config.write_text(config.read_text().replace(old, new))
    config_sha256 = _sha256(config.read_bytes())
    project = config.parents[1]
    subprocess.run(["git", "-C", str(project), "add", str(config)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "changed fixture",
        ],
        check=True,
    )
    receipt = Path(arguments["oracle_receipt"])

    def update_config_hash(payload: dict) -> None:
        for record in payload["updated_configs"]:
            if record["path"].endswith("mobius_kimi.toml"):
                record["sha256"] = config_sha256

    arguments["oracle_receipt_sha256"] = _rewrite_receipt(receipt, update_config_hash)
    with pytest.raises(LaunchCertificateError, match=f"^{error}$"):
        create_launch_certificate(**arguments)


def test_rejects_smoke_timeout_pair_for_mobius_production(tmp_path: Path) -> None:
    arguments, _ = _fixture(tmp_path)
    config = Path(arguments["production_config"])
    config.write_text(
        config.read_text()
        .replace("rollout = 36000", "rollout = 28800")
        .replace("session_timeout = 43200", "session_timeout = 32400")
    )
    config_sha256 = _sha256(config.read_bytes())
    project = config.parents[1]
    subprocess.run(["git", "-C", str(project), "add", str(config)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "changed fixture",
        ],
        check=True,
    )
    receipt = Path(arguments["oracle_receipt"])

    def update_config_hash(payload: dict) -> None:
        for record in payload["updated_configs"]:
            if record["path"].endswith("mobius_kimi.toml"):
                record["sha256"] = config_sha256

    arguments["oracle_receipt_sha256"] = _rewrite_receipt(receipt, update_config_hash)

    with pytest.raises(
        LaunchCertificateError,
        match="^production_timeout_contract_invalid$",
    ):
        create_launch_certificate(**arguments)


def test_verify_requires_external_hash_and_rechecks_dependencies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, output = _fixture(tmp_path)
    create_launch_certificate(**arguments)
    certificate_sha256 = _sha256(output.read_bytes())

    with pytest.raises(LaunchCertificateError, match="^launch_certificate_sha256_mismatch$"):
        _validate_for_run(arguments, output, "0" * 64)

    capacity = json.loads(Path(arguments["capacity_smoke_checkpoint"]).read_text())
    linked_results = Path(capacity["artifacts"]["results"]["path"])
    linked_results.write_bytes(linked_results.read_bytes() + b"changed\n")
    with pytest.raises(LaunchCertificateError, match="^capacity_results_sha256_mismatch$"):
        _validate_for_run(arguments, output, certificate_sha256)

    with pytest.raises(SystemExit, match="^2$"):
        main(["verify", str(output)])
    captured = capsys.readouterr()
    assert "--certificate-sha256" in captured.err


def test_verify_cli_binds_current_launch_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, output = _fixture(tmp_path)
    assert main(_create_cli_arguments(arguments)) == 0
    created = capsys.readouterr()
    assert created.err == ""
    assert "synthetic-entry-" not in created.out
    certificate_sha256 = _sha256(output.read_bytes())

    status = main(_verify_cli_arguments(arguments, output, certificate_sha256))

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "synthetic-entry-" not in captured.out
    assert json.loads(captured.out) == {
        "certificate": str(output.resolve()),
        "certificate_file_sha256": certificate_sha256,
        "launch_certificate_sha256": json.loads(output.read_text())["launch_certificate_sha256"],
        "ok": True,
    }
