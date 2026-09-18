from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

import certify_trace_smoke as smoke_module
import pytest
import smoke_qualification as qualification
from certify_trace_smoke import SmokeCertificateError, certify_smoke
from deployment_endpoint import load_deployment_endpoint
from deployment_proxy_policy import load_deployment_proxy_policy
from guard_success_receipt import (
    GuardReceiptError,
    build_guard_success_receipt,
    load_guard_success_receipt,
    write_guard_success_receipt,
)
from guard_success_receipt import (
    canonical_json as guard_canonical_json,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import ConcurrencyTelemetry


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record(path: Path, **extra: object) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256_bytes(path.read_bytes()),
        **extra,
    }


def _json_digest(value: dict) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _sha256_bytes(encoded)


def _trace(trace_id: str, task: str, *, start: float, end: float) -> dict:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [{"role": "user", "content": "synthetic"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "shell",
                    "description": "synthetic",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    response = {
        "id": "response",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "retained",
                    "reasoning_content": "retained reasoning",
                },
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    return {
        "id": trace_id,
        "task": {"slug": task},
        "timing": {
            "setup": {"start": start, "end": start + 0.25},
            "scoring": {"start": end - 0.25, "end": end},
        },
        "nodes": [
            {
                "parent": None,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "user", "content": "synthetic"},
            },
            {
                "parent": 0,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": response["choices"][0]["message"],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
                "finish_reason": "stop",
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _json_digest(request), "body": request},
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _json_digest(response),
                        "body": response,
                    },
                },
            },
        ],
    }


def _fixture(
    tmp_path: Path,
    *,
    overlapping_timings: bool = True,
) -> tuple[Path, Path, str, dict]:
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    task_file = tmp_path / "approved.txt"
    task_file.write_text("opaque-a\nopaque-b\n")
    task_sha256 = _sha256_bytes(task_file.read_bytes())
    results = run_dir / "results.jsonl"
    results.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                _trace("trace-a", "opaque-a", start=1.0, end=3.0),
                _trace(
                    "trace-b",
                    "opaque-b",
                    start=2.0 if overlapping_timings else 3.0,
                    end=4.0,
                ),
            )
        )
        + "\n"
    )
    config = run_dir / "config.toml"
    config.write_text('model = "Kimi-K3"\n')
    manifest = inputs / "manifest.json"
    manifest.write_text('{"config":{},"task_file":{}}\n')
    provenance = run_dir / "provenance.txt"
    provenance.write_text("eval_run_identity_sha256=placeholder\n")
    deployment_id = "deployment-test"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n")
    (deployment_dir / "proxy_litellm_config.yaml").write_text(
        "litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n"
    )
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
    endpoint = load_deployment_endpoint(
        proxy_info,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=_sha256_bytes(proxy_info.read_bytes()),
    ).binding
    backend = f"backend-sha256:{hashlib.sha256(b'http://worker-0:8000/v1').hexdigest()}"
    serving_route_generation = {
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
                "slurm_job_id": "12345",
                "started_at": "2026-09-17T01:00:00Z",
                "backend_sha256": backend,
            }
        ],
    }
    proxy_policy = load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=_sha256_bytes(spec.read_bytes()),
        expected_request_timeout=43_200,
    )
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "passed",
                "deployment": deployment_id,
                "observed_spec_sha256": _sha256_bytes(spec.read_bytes()),
                "expected_routes": 1,
                "endpoint": endpoint,
                "proxy_policy": proxy_policy,
                "serving_route_generation": serving_route_generation,
                "last_status": {
                    "schema_version": 4,
                    "deployment_id": deployment_id,
                    "phase": "serving",
                    "desired": 1,
                    "ready": 1,
                    "running_not_ready": 0,
                    "pending": 0,
                    "coordinator_incarnation": serving_route_generation["coordinator"],
                    "coord_ticks_completed": 10,
                    "serving_route_generation": serving_route_generation,
                },
                "probe": {
                    "ok": True,
                    "endpoint_authority_sha256": endpoint["authority_sha256"],
                    "coverage": {
                        "ok": True,
                        "expected_routes": 1,
                        "discovered_routes": 1,
                        "backends": [backend],
                    },
                },
            }
        )
        + "\n"
    )
    identity_path = run_dir / "eval_run_identity.json"
    identity_path.write_text("{}\n")
    (run_dir / ".writer.lock").touch()

    identity = {
        "schema_version": 1,
        "role": "smoke",
        "config": {"resolved": _record(config)},
        "inputs": {
            "manifest": _record(manifest),
            "task_file": _record(task_file, count=2),
        },
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": serving_route_generation,
            "proxy_policy": proxy_policy,
            "spec": _record(spec),
            "readiness_checkpoint": _record(readiness),
            "smoke_checkpoint": None,
        },
        "contract": {
            "model": "Kimi-K3",
            "pass_at_1": True,
            "num_rollouts": 1,
            "reasoning_effort": "max",
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
            "context_tokens": {
                "max_input_tokens": 262_144,
                "max_output_tokens": 262_144,
                "max_total_tokens": 262_144,
            },
            "sampling_max_tokens": 32_768,
            "capture_model_io": True,
            "retain_traces": False,
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "return_token_ids",
                "top_logprobs",
            ],
        },
        "execution": {
            "rollout_concurrency": 2,
            "multiplex": 2,
            "http_max_connections": 2,
            "http_max_keepalive_connections": 2,
            "vmvm_environment": {"lease_start_concurrency": 2},
        },
    }
    envelope = {
        "schema_version": 1,
        "eval_run_identity_sha256": _json_digest(identity),
        "identity": identity,
    }
    invocations = run_dir / "eval_invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
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
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        slurm_job_id="1",
        register_atexit=False,
    )
    for _ in range(2):
        telemetry.vmvm_runtime_started()
        telemetry.lease_start_entered()
    for _ in range(2):
        telemetry.lease_tunnel_became_ready()
        telemetry.lease_start_finished()
        telemetry.vmvm_runtime_became_ready()
    for _ in range(2):
        telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    receipt = build_guard_success_receipt(
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        eval_run_identity=identity_path,
        eval_invocations=invocations,
        results=results,
        deployment_id=deployment_id,
        deployment_spec_sha256=_sha256_bytes(spec.read_bytes()),
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=_sha256_bytes(readiness.read_bytes()),
        endpoint=endpoint,
        serving_route_generation=serving_route_generation,
        proxy_policy=proxy_policy,
        concurrency_telemetry=telemetry.path,
    )
    write_guard_success_receipt(run_dir / "route_guard_success.json", receipt)
    return run_dir, task_file, task_sha256, envelope


def _refresh_guard_receipt(
    run_dir: Path,
    envelope: dict,
    *,
    include_concurrency_telemetry: bool = True,
) -> None:
    receipt_path = run_dir / "route_guard_success.json"
    previous = json.loads(receipt_path.read_text())
    deployment = previous["deployment"]
    receipt = build_guard_success_receipt(
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        eval_run_identity=run_dir / "eval_run_identity.json",
        eval_invocations=run_dir / "eval_invocations.jsonl",
        results=run_dir / "results.jsonl",
        deployment_id=deployment["id"],
        deployment_spec_sha256=deployment["spec_sha256"],
        readiness_checkpoint=Path(deployment["readiness_checkpoint"]["path"]),
        readiness_checkpoint_sha256=deployment["readiness_checkpoint"]["sha256"],
        endpoint=deployment["endpoint"],
        serving_route_generation=deployment["serving_route_generation"],
        proxy_policy=deployment["proxy_policy"],
        concurrency_telemetry=(run_dir / "concurrency_telemetry.json" if include_concurrency_telemetry else None),
    )
    write_guard_success_receipt(receipt_path, receipt)


def _install_capacity_evaluator_contract(
    tmp_path: Path,
    run_dir: Path,
    task_file: Path,
    task_sha256: str,
    envelope: dict,
) -> None:
    workflow = Path(smoke_module.__file__).resolve().parent
    config_text = (workflow / "configs/eval/mobius_kimi_k3_capacity_smoke.toml").read_text()
    config_text = (
        config_text.replace("num_tasks = 42", "num_tasks = 2")
        .replace("max_concurrent = 24", "max_concurrent = 2")
        .replace("multiplex = 24", "multiplex = 2")
        .replace("max_connections = 24", "max_connections = 2")
        .replace("max_keepalive_connections = 24", "max_keepalive_connections = 2")
        .replace(
            'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/validate/mobius_repaired_tasks.txt"',
            f'task_file = "{task_file.resolve()}"',
        )
        .replace(
            'task_file_sha256 = "8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c"',
            f'task_file_sha256 = "{task_sha256}"',
        )
    )
    config = run_dir / "config.toml"
    config.write_text(config_text)
    source_config = run_dir / "inputs/source_config.toml"
    source_config.write_text(config_text)
    manifest = run_dir / "inputs/manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "config": {"source": str(source_config.resolve()), **_record(config)},
                "task_file": {"source": str(task_file.resolve()), **_record(task_file)},
            },
            sort_keys=True,
        )
        + "\n"
    )
    (run_dir / "provenance.txt").write_text("host=test-host\nslurm_job_id=1\n")

    project = tmp_path / "project"
    evaluator = project / "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm"
    vmvm = project / "environments/vmvm_tb_v2/vmvm_tb_v2"
    evaluator.mkdir(parents=True)
    vmvm.mkdir(parents=True)
    (evaluator / "taskset.py").write_text("VALUE = 1\n")
    (vmvm / "runtime.py").write_text("VALUE = 2\n")
    (evaluator.parent / "run_eval.sbatch").write_text("#!/bin/bash\n")

    identity = envelope["identity"]
    identity["source"] = {
        "project_root": str(project.resolve()),
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "0" * 64,
        "verifiers_commit": "2" * 40,
        "verifiers_tree_sha256": "0" * 64,
        "renderers_commit": "3" * 40,
        "renderers_tree_sha256": "0" * 64,
        "vmvm_tb_v2_sha256": "4" * 64,
    }
    identity["config"] = {
        "source": _record(source_config),
        "resolved": _record(config),
    }
    identity["inputs"]["manifest"] = _record(manifest)
    identity_sha256 = _json_digest(identity)
    envelope["eval_run_identity_sha256"] = identity_sha256
    (run_dir / "eval_run_identity.json").write_text(json.dumps(envelope, sort_keys=True) + "\n")
    (run_dir / "eval_invocations.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "role": "smoke",
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "1",
            }
        )
        + "\n"
    )
    telemetry_path = run_dir / "concurrency_telemetry.json"
    telemetry_path.unlink()
    telemetry = ConcurrencyTelemetry(
        telemetry_path,
        eval_run_identity_sha256=identity_sha256,
        eval_run_role="smoke",
        slurm_job_id="1",
        register_atexit=False,
    )
    for _ in range(2):
        telemetry.vmvm_runtime_started()
        telemetry.lease_start_entered()
    for _ in range(2):
        telemetry.lease_tunnel_became_ready()
        telemetry.lease_start_finished()
        telemetry.vmvm_runtime_became_ready()
    for _ in range(2):
        telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    _refresh_guard_receipt(run_dir, envelope)


def test_capacity_smoke_full_profile_certifies_qualifies_and_matches_target(
    tmp_path: Path,
) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    _install_capacity_evaluator_contract(
        tmp_path,
        run_dir,
        task_file,
        task_sha256,
        envelope,
    )

    certify_smoke(
        run_dir,
        expected_task_file=task_file,
        expected_task_file_sha256=task_sha256,
        expected_traces=2,
        required_rollout_concurrency=2,
        required_lease_start_concurrency=2,
        identity_loader=lambda *_args, **_kwargs: envelope,
    )
    identity = envelope["identity"]
    deployment = identity["deployment"]
    smoke = run_dir / "smoke_checkpoint.json"
    evidence = qualification.validate_smoke_qualification(
        smoke,
        _sha256_bytes(smoke.read_bytes()),
        deployment_id=deployment["id"],
        deployment_spec_path=Path(deployment["spec"]["path"]),
        deployment_spec_sha256=deployment["spec"]["sha256"],
        readiness_path=Path(deployment["readiness_checkpoint"]["path"]),
        readiness_sha256=deployment["readiness_checkpoint"]["sha256"],
        proxy_info_path=Path(deployment["endpoint"]["proxy_info"]["path"]),
        proxy_info_sha256=deployment["endpoint"]["proxy_info"]["sha256"],
        model="Kimi-K3",
        identity_loader=lambda *_args, **_kwargs: envelope,
    )

    target = {
        "role": "tb4",
        "source": identity["source"],
        "config": identity["config"],
        "contract": identity["contract"],
    }
    qualification.validate_target_evaluator_compatibility(
        target,
        evidence.evaluator_evidence,
    )


def test_certifies_valid_smoke_without_task_metadata(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)

    certificate = certify_smoke(
        run_dir,
        expected_task_file=task_file,
        expected_task_file_sha256=task_sha256,
        expected_traces=2,
        identity_loader=lambda *_args, **_kwargs: envelope,
    )

    assert certificate["ok"] is True
    assert certificate["state"] == "passed"
    assert certificate["counts"]["traces"] == 2
    assert certificate["counts"]["trace_failures"] == 0
    assert certificate["endpoint"] == envelope["identity"]["deployment"]["endpoint"]
    assert certificate["observed_concurrency"] == {
        "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
        "lease_start_signal": "vacli_lease_start_semaphore_holders",
        "peak_active_rollouts_lower_bound": 2,
        "peak_concurrent_lease_startups": 2,
        "required_peak_active_rollouts_lower_bound": None,
        "required_peak_concurrent_lease_startups": None,
    }
    assert certificate["artifacts"]["proxy_info"] == certificate["endpoint"]["proxy_info"]
    assert certificate["audit_policy"]["model_io_contract"]["request_model"] == "Kimi-K3"
    assert certificate["audit_policy"]["require_request_graph_match"] is True
    assert "opaque-a" not in json.dumps(certificate)
    body = {key: value for key, value in certificate.items() if key != "smoke_checkpoint_sha256"}
    assert certificate["smoke_checkpoint_sha256"] == _sha256_bytes(
        json.dumps(body, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    )


def test_rejects_hash_valid_request_that_diverges_from_graph(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    results_path = run_dir / "results.jsonl"
    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    request = rows[0]["nodes"][1]["model_io"]["request"]
    request["body"]["messages"] = [{"role": "user", "content": "wire-only context"}]
    request["sha256"] = _json_digest(request["body"])
    results_path.write_text("".join(f"{json.dumps(row)}\n" for row in rows))
    _refresh_guard_receipt(run_dir, envelope)

    with pytest.raises(SmokeCertificateError, match="^trace_audit_failed$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_smoke_qualification_reaudits_hash_valid_graph_wire_divergence(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    certificate = certify_smoke(
        run_dir,
        expected_task_file=task_file,
        expected_task_file_sha256=task_sha256,
        expected_traces=2,
        identity_loader=lambda *_args, **_kwargs: envelope,
    )
    results_path = run_dir / "results.jsonl"
    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    request = rows[0]["nodes"][1]["model_io"]["request"]
    request["body"]["messages"] = [{"role": "user", "content": "wire-only context"}]
    request["sha256"] = _json_digest(request["body"])
    results_path.write_text("".join(f"{json.dumps(row)}\n" for row in rows))
    _refresh_guard_receipt(run_dir, envelope)

    certificate["artifacts"]["results"] = _record(results_path)
    certificate["artifacts"]["route_guard_success"] = _record(run_dir / "route_guard_success.json")
    certificate_body = {key: value for key, value in certificate.items() if key != "smoke_checkpoint_sha256"}
    certificate["smoke_checkpoint_sha256"] = _sha256_bytes(smoke_module._canonical_json(certificate_body))
    smoke_path = run_dir / "smoke_checkpoint.json"
    smoke_path.chmod(0o600)
    smoke_path.write_text(json.dumps(certificate, sort_keys=True) + "\n")
    smoke_path.chmod(0o444)

    identity = envelope["identity"]
    deployment = identity["deployment"]
    spec_path = Path(deployment["spec"]["path"])
    readiness_path = Path(deployment["readiness_checkpoint"]["path"])
    with pytest.raises(qualification.SmokeQualificationError, match="^smoke_trace_audit_failed$"):
        qualification.validate_v1_smoke(
            qualification.Artifact(smoke_path.resolve(), _sha256_bytes(smoke_path.read_bytes())),
            deployment_id=deployment["id"],
            deployment_spec=qualification.Artifact(
                spec_path.resolve(),
                deployment["spec"]["sha256"],
            ),
            readiness=qualification.Artifact(
                readiness_path.resolve(),
                deployment["readiness_checkpoint"]["sha256"],
            ),
            endpoint=deployment["endpoint"],
            generation=deployment["serving_route_generation"],
            proxy_policy=deployment["proxy_policy"],
            model="Kimi-K3",
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_rejects_tool_turn_without_explicit_zero_reasoning_evidence(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    results_path = run_dir / "results.jsonl"
    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    node = rows[0]["nodes"][1]
    node["message"] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": None,
        "tool_calls": [{"id": "call-1", "name": "shell", "arguments": "{}"}],
    }
    node["usage"] = {"prompt_tokens": 8, "completion_tokens": 4}
    node["finish_reason"] = "tool_calls"
    response = {
        "id": "response",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    node["model_io"]["response"] = {
        "kind": "exact_provider_json",
        "sha256": _json_digest(response),
        "body": response,
    }
    results_path.write_text("".join(f"{json.dumps(row)}\n" for row in rows))
    _refresh_guard_receipt(run_dir, envelope)

    with pytest.raises(SmokeCertificateError, match="^trace_audit_failed$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_certifies_legacy_guard_without_concurrency_telemetry(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    (run_dir / "concurrency_telemetry.json").unlink()
    _refresh_guard_receipt(
        run_dir,
        envelope,
        include_concurrency_telemetry=False,
    )

    certificate = certify_smoke(
        run_dir,
        expected_task_file=task_file,
        expected_task_file_sha256=task_sha256,
        expected_traces=2,
        identity_loader=lambda *_args, **_kwargs: envelope,
    )

    assert certificate["ok"] is True
    assert "observed_concurrency" not in certificate
    assert "concurrency_telemetry" not in certificate["artifacts"]


def test_legacy_guard_cannot_satisfy_required_concurrency(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    (run_dir / "concurrency_telemetry.json").unlink()
    _refresh_guard_receipt(
        run_dir,
        envelope,
        include_concurrency_telemetry=False,
    )

    with pytest.raises(
        SmokeCertificateError,
        match="^observed_concurrency_below_required$",
    ):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            required_rollout_concurrency=2,
            required_lease_start_concurrency=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_rejects_active_writer(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    with (run_dir / ".writer.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SmokeCertificateError, match="^writer_active$"):
            certify_smoke(
                run_dir,
                expected_task_file=task_file,
                expected_task_file_sha256=task_sha256,
                expected_traces=2,
                identity_loader=lambda *_args, **_kwargs: envelope,
            )


def test_rejects_missing_or_below_target_concurrency_evidence(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(
        tmp_path,
        overlapping_timings=False,
    )
    telemetry_path = run_dir / "concurrency_telemetry.json"
    telemetry_path.unlink()
    with pytest.raises(SmokeCertificateError, match="^guard_success_receipt_invalid$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )

    telemetry = ConcurrencyTelemetry(
        telemetry_path,
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        slurm_job_id="1",
        register_atexit=False,
    )
    for _ in range(2):
        telemetry.vmvm_runtime_started()
        telemetry.lease_start_entered()
        telemetry.lease_tunnel_became_ready()
        telemetry.lease_start_finished()
        telemetry.vmvm_runtime_became_ready()
        telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    _refresh_guard_receipt(run_dir, envelope)
    with pytest.raises(
        SmokeCertificateError,
        match="^observed_concurrency_below_required$",
    ):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            required_rollout_concurrency=2,
            required_lease_start_concurrency=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_two_task_transcript_smoke_binds_observation_without_claiming_capacity(
    tmp_path: Path,
) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(
        tmp_path,
        overlapping_timings=False,
    )
    telemetry_path = run_dir / "concurrency_telemetry.json"
    telemetry_path.unlink()
    telemetry = ConcurrencyTelemetry(
        telemetry_path,
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        slurm_job_id="1",
        register_atexit=False,
    )
    for _ in range(2):
        telemetry.vmvm_runtime_started()
        telemetry.lease_start_entered()
        telemetry.lease_tunnel_became_ready()
        telemetry.lease_start_finished()
        telemetry.vmvm_runtime_became_ready()
        telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    _refresh_guard_receipt(run_dir, envelope)

    certificate = certify_smoke(
        run_dir,
        expected_task_file=task_file,
        expected_task_file_sha256=task_sha256,
        expected_traces=2,
        identity_loader=lambda *_args, **_kwargs: envelope,
    )

    assert certificate["observed_concurrency"]["peak_active_rollouts_lower_bound"] == 1
    assert certificate["observed_concurrency"]["required_peak_active_rollouts_lower_bound"] is None


def test_auxiliary_verifier_vms_do_not_inflate_active_rollout_evidence(
    tmp_path: Path,
) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    telemetry_path = run_dir / "concurrency_telemetry.json"
    telemetry_path.unlink()
    telemetry = ConcurrencyTelemetry(
        telemetry_path,
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        slurm_job_id="1",
        register_atexit=False,
    )
    for _ in range(4):
        telemetry.vmvm_runtime_started()
    for _ in range(2):
        for _ in range(2):
            telemetry.lease_start_entered()
        for _ in range(2):
            telemetry.lease_tunnel_became_ready()
            telemetry.lease_start_finished()
            telemetry.vmvm_runtime_became_ready()
    for _ in range(4):
        telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    _refresh_guard_receipt(run_dir, envelope)

    certificate = certify_smoke(
        run_dir,
        expected_task_file=task_file,
        expected_task_file_sha256=task_sha256,
        expected_traces=2,
        required_rollout_concurrency=2,
        required_lease_start_concurrency=2,
        identity_loader=lambda *_args, **_kwargs: envelope,
    )

    assert certificate["observed_concurrency"]["peak_active_rollouts_lower_bound"] == 2


def test_rejects_telemetry_replacement_after_stable_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    original_loader = smoke_module.load_concurrency_telemetry_artifact

    def load_then_replace(*args: object, **kwargs: object) -> tuple[dict, dict[str, str]]:
        telemetry, artifact = original_loader(*args, **kwargs)
        telemetry_path = run_dir / "concurrency_telemetry.json"
        telemetry_path.unlink()
        telemetry_path.write_bytes(b"replaced\n")
        return telemetry, artifact

    monkeypatch.setattr(
        smoke_module,
        "load_concurrency_telemetry_artifact",
        load_then_replace,
    )
    with pytest.raises(
        SmokeCertificateError,
        match="^artifact_hash_mismatch:concurrency_telemetry$",
    ):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_rejects_missing_or_stale_guard_success_receipt(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    (run_dir / "route_guard_success.json").unlink()

    with pytest.raises(SmokeCertificateError, match="^guard_success_receipt_invalid$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )

    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path / "stale")
    results = run_dir / "results.jsonl"
    results.write_text(results.read_text() + "\n")
    with pytest.raises(SmokeCertificateError, match="^guard_success_receipt_invalid$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "resume",
        "multiple",
        "forged_job",
        "forged_role",
        "forged_identity",
        "bool_schema",
    ],
)
def test_guard_receipt_rejects_invalid_invocation_ledger(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _, _, _ = _fixture(tmp_path)
    invocations = run_dir / "eval_invocations.jsonl"
    record = json.loads(invocations.read_text())
    if mutation == "resume":
        record["resume"] = True
        invocations.write_text(json.dumps(record) + "\n")
    elif mutation == "multiple":
        line = json.dumps(record) + "\n"
        invocations.write_text(line + line)
    elif mutation == "forged_job":
        record["slurm_job_id"] = "01"
        invocations.write_text(json.dumps(record) + "\n")
    elif mutation == "forged_role":
        record["role"] = "tb4"
        invocations.write_text(json.dumps(record) + "\n")
    elif mutation == "forged_identity":
        record["eval_run_identity_sha256"] = "f" * 64
        invocations.write_text(json.dumps(record) + "\n")
    else:
        record["schema_version"] = True
        invocations.write_text(json.dumps(record) + "\n")
    receipt_path = run_dir / "route_guard_success.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["artifacts"]["eval_invocations"]["sha256"] = _sha256_bytes(invocations.read_bytes())
    receipt.pop("guard_success_receipt_sha256")
    receipt["guard_success_receipt_sha256"] = _sha256_bytes(guard_canonical_json(receipt))
    receipt_path.write_text(json.dumps(receipt) + "\n")

    with pytest.raises(GuardReceiptError, match="eval_invocations_invalid"):
        load_guard_success_receipt(receipt_path)


def test_rejects_trace_failure_without_publishing(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    rows[0]["nodes"][1]["message"]["reasoning_content"] = ""
    (run_dir / "results.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    with pytest.raises(SmokeCertificateError, match="^trace_audit_failed$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )
    assert not (run_dir / "smoke_checkpoint.json").exists()


def test_rejects_readiness_endpoint_mismatch(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    readiness_record = envelope["identity"]["deployment"]["readiness_checkpoint"]
    readiness = Path(readiness_record["path"])
    payload = json.loads(readiness.read_text())
    payload["endpoint"]["authority_sha256"] = "0" * 64
    readiness.write_text(json.dumps(payload) + "\n")
    readiness_record["sha256"] = _sha256_bytes(readiness.read_bytes())

    with pytest.raises(SmokeCertificateError, match="^readiness_endpoint_mismatch$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_rejects_legacy_identity_without_endpoint(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    envelope["identity"]["deployment"].pop("endpoint")

    with pytest.raises(SmokeCertificateError, match="^eval_identity_endpoint_invalid$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )


def test_rejects_overwriting_different_checkpoint(tmp_path: Path) -> None:
    run_dir, task_file, task_sha256, envelope = _fixture(tmp_path)
    (run_dir / "smoke_checkpoint.json").write_text("{}\n")

    with pytest.raises(SmokeCertificateError, match="^checkpoint_already_exists$"):
        certify_smoke(
            run_dir,
            expected_task_file=task_file,
            expected_task_file_sha256=task_sha256,
            expected_traces=2,
            identity_loader=lambda *_args, **_kwargs: envelope,
        )
